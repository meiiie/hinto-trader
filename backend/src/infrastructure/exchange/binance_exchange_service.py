"""
BinanceExchangeService - Infrastructure Layer

Real Binance exchange implementation of IExchangeService.
Makes actual API calls to Binance Futures for position and order data.

NOTE: This service is for REAL trading mode. Use with caution!
"""

import logging
import asyncio
from typing import Optional, Dict, Any
import ccxt.async_support as ccxt  # Use async version of ccxt

from ...domain.interfaces.i_exchange_service import IExchangeService, ExchangeError
from ...domain.entities.exchange_models import Position, OrderStatus


class BinanceExchangeService(IExchangeService):
    """
    Real Binance exchange implementation using CCXT.

    Implements robust connection to Binance Futures with:
    - Automatic Leverage Setting
    - Margin Mode Configuration (Isolated/Cross)
    - Order Execution
    - Position Management
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        use_testnet: bool = False,
        timeout: int = 30000  # 30s timeout
    ):
        self.logger = logging.getLogger(__name__)
        self._api_key = api_key
        self._api_secret = api_secret
        self._use_testnet = use_testnet
        self._timeout = timeout

        # Initialize CCXT exchange
        self.exchange = ccxt.binance({
            'apiKey': self._api_key,
            'secret': self._api_secret,
            'timeout': self._timeout,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future',  # Default to futures
                'adjustForTimeDifference': True,
            }
        })

        if self._use_testnet:
            self.exchange.set_sandbox_mode(True)
            self.logger.warning("⚠️ BinanceExchangeService running in TESTNET mode")

        # Cache for leverage/margin settings to avoid redundant API calls
        self._leverage_cache: Dict[str, int] = {}
        self._margin_mode_cache: Dict[str, str] = {}

    async def initialize(self):
        """Async initialization (load markets)."""
        try:
            await self.exchange.load_markets()
            self.logger.info("✅ Binance markets loaded")
        except Exception as e:
            self.logger.error(f"Failed to load markets: {e}")
            raise ExchangeError(f"Failed to load markets: {e}")

    async def close(self):
        """Close exchange connection."""
        await self.exchange.close()

    async def get_position(self, symbol: str) -> Optional[Position]:
        try:
            # fetch_positions in ccxt usually returns all positions
            # For binance futures, we can filter by symbol in params or client side
            positions = await self.exchange.fetch_positions([symbol])

            target_pos = None
            for pos in positions:
                # CCXT unifies symbols, e.g. BTC/USDT:USDT
                if pos['symbol'].replace('/', '').replace(':USDT', '') == symbol.upper().replace('/', ''):
                    target_pos = pos
                    break

            if not target_pos:
                return None

            amt = float(target_pos.get('contracts', 0) or target_pos.get('info', {}).get('positionAmt', 0))

            if amt == 0:
                return None

            side = 'LONG' if amt > 0 else 'SHORT'

            return Position(
                symbol=symbol,
                side=side,
                size=abs(amt),
                entry_price=float(target_pos.get('entryPrice', 0)),
                unrealized_pnl=float(target_pos.get('unrealizedPnl', 0)),
                leverage=target_pos.get('leverage', 1),
                liquidation_price=float(target_pos.get('liquidationPrice', 0)),
                margin_type=target_pos.get('marginType', 'cross')
            )

        except Exception as e:
            self.logger.error(f"Error getting position for {symbol}: {e}")
            raise ExchangeError(f"Failed to get position: {e}")

    async def get_order_status(self, symbol: str, order_id: str) -> OrderStatus:
        try:
            order = await self.exchange.fetch_order(order_id, symbol)

            return OrderStatus(
                order_id=str(order['id']),
                status=order['status'].upper(),
                filled_qty=float(order['filled']),
                avg_price=float(order['average']) if order['average'] else None
            )
        except Exception as e:
            raise ExchangeError(f"Failed to get order status: {e}")

    async def create_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        time_in_force: str = "GTC",
        reduce_only: bool = False,
        leverage: int = 10,  # Default leverage
        margin_mode: str = "isolated"  # Default margin mode
    ) -> Dict:
        """
        Create an order with auto-leverage and margin mode setting.
        """
        try:
            # 1. Set Leverage (if changed)
            if self._leverage_cache.get(symbol) != leverage:
                await self.set_leverage(symbol, leverage)

            # 2. Set Margin Mode (if changed)
            # Note: Binance API throws error if you try to set same margin mode again,
            # so we should check cache or handle error gracefully.
            if self._margin_mode_cache.get(symbol) != margin_mode:
                try:
                    await self.exchange.set_margin_mode(margin_mode.upper(), symbol)
                    self._margin_mode_cache[symbol] = margin_mode
                except Exception as e:
                    # Ignore "No need to change margin type" error
                    if "No need to change margin type" not in str(e):
                        self.logger.warning(f"Set margin mode warning: {e}")

            # 3. Prepare Order Params
            params = {}
            if time_in_force != "GTC":
                params['timeInForce'] = time_in_force
            if reduce_only:
                params['reduceOnly'] = True

            # 4. Create Main Order
            order = await self.exchange.create_order(
                symbol=symbol,
                type=order_type.lower(),
                side=side.lower(),
                amount=quantity,
                price=price,
                params=params
            )

            self.logger.info(f"✅ Order created: {side} {quantity} {symbol} @ {price or 'MARKET'}")

            # 5. Place Bracket Orders (Stop Loss / Take Profit) if provided
            # Note: This is simplified. In production, you might want to use batch orders
            # or strategy-specific logic.
            if stop_loss:
                sl_side = 'sell' if side.lower() == 'buy' else 'buy'
                await self.exchange.create_order(
                    symbol=symbol,
                    type='STOP_MARKET',
                    side=sl_side,
                    amount=quantity,
                    params={
                        'stopPrice': stop_loss,
                        'reduceOnly': True
                    }
                )
                self.logger.info(f"🛡️ SL placed @ {stop_loss}")

            if take_profit:
                tp_side = 'sell' if side.lower() == 'buy' else 'buy'
                await self.exchange.create_order(
                    symbol=symbol,
                    type='TAKE_PROFIT_MARKET',
                    side=tp_side,
                    amount=quantity,
                    params={
                        'stopPrice': take_profit,
                        'reduceOnly': True
                    }
                )
                self.logger.info(f"🎯 TP placed @ {take_profit}")

            return order

        except Exception as e:
            self.logger.error(f"Failed to create order: {e}")
            raise ExchangeError(f"Create order failed: {e}")

    async def cancel_order(self, symbol: str, order_id: str) -> Dict:
        try:
            return await self.exchange.cancel_order(order_id, symbol)
        except Exception as e:
            raise ExchangeError(f"Cancel order failed: {e}")

    async def get_balance(self, asset: str = "USDT") -> float:
        try:
            balance = await self.exchange.fetch_balance()
            return float(balance.get(asset, {}).get('free', 0.0))
        except Exception as e:
            self.logger.error(f"Failed to get balance: {e}")
            return 0.0

    async def set_leverage(self, symbol: str, leverage: int) -> Dict:
        try:
            # CCXT set_leverage
            response = await self.exchange.set_leverage(leverage, symbol)
            self._leverage_cache[symbol] = leverage
            self.logger.info(f"⚙️ Leverage set to {leverage}x for {symbol}")
            return response
        except Exception as e:
            self.logger.error(f"Failed to set leverage: {e}")
            raise ExchangeError(f"Set leverage failed: {e}")

    async def get_exchange_type(self) -> str:
        return "binance"
