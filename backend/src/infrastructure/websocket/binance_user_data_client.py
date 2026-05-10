"""
BinanceUserDataClient - User Data Stream WebSocket Client

SOTA: Listens to account/order updates in real-time.

Events handled:
- ORDER_TRADE_UPDATE: Order fills, cancels, etc.
- ACCOUNT_UPDATE: Position and balance changes

Created: 2026-01-03
Purpose: Enable Live Trading to detect order fills and manage OCO
"""

import asyncio
import logging
import json
from datetime import datetime
from typing import Optional, Callable, Dict, Any
from dataclasses import dataclass

import websockets


@dataclass
class OrderUpdate:
    """Parsed order update from Binance."""
    symbol: str
    order_id: int
    client_order_id: str
    side: str  # BUY, SELL
    order_type: str  # LIMIT, MARKET, STOP_MARKET, etc.
    status: str  # NEW, FILLED, CANCELED, EXPIRED, etc.
    price: float
    stop_price: float
    quantity: float
    filled_quantity: float
    average_price: float
    commission: float
    commission_asset: str
    update_time: datetime
    is_reduce_only: bool

    @classmethod
    def from_binance(cls, data: Dict) -> 'OrderUpdate':
        """Parse from Binance ORDER_TRADE_UPDATE event."""
        return cls(
            symbol=data.get('s', ''),
            order_id=int(data.get('i', 0)),
            client_order_id=data.get('c', ''),
            side=data.get('S', ''),
            order_type=data.get('o', ''),
            status=data.get('X', ''),
            price=float(data.get('p', 0)),
            stop_price=float(data.get('sp', 0)),
            quantity=float(data.get('q', 0)),
            filled_quantity=float(data.get('z', 0)),
            average_price=float(data.get('ap', 0)),
            commission=float(data.get('n', 0)),
            commission_asset=data.get('N', ''),
            update_time=datetime.fromtimestamp(data.get('T', 0) / 1000),
            is_reduce_only=data.get('R', False)
        )


@dataclass
class AccountUpdate:
    """Parsed account update from Binance."""
    event_time: datetime
    balances: Dict[str, float]  # asset -> wallet_balance
    positions: Dict[str, Dict]  # symbol -> position info

    @classmethod
    def from_binance(cls, data: Dict) -> 'AccountUpdate':
        """Parse from Binance ACCOUNT_UPDATE event."""
        balances = {}
        positions = {}

        for balance in data.get('B', []):
            asset = balance.get('a', '')
            balances[asset] = float(balance.get('wb', 0))

        for position in data.get('P', []):
            symbol = position.get('s', '')
            positions[symbol] = {
                'position_amt': float(position.get('pa', 0)),
                'entry_price': float(position.get('ep', 0)),
                'unrealized_pnl': float(position.get('up', 0)),
            }

        return cls(
            event_time=datetime.now(),
            balances=balances,
            positions=positions
        )


class BinanceUserDataClient:
    """
    SOTA: WebSocket client for Binance User Data Stream.

    Handles:
    - ORDER_TRADE_UPDATE: Order status changes
    - ACCOUNT_UPDATE: Position/balance changes

    Usage:
        client = BinanceUserDataClient(listen_key)
        client.set_order_callback(on_order_update)
        await client.connect()
    """

    # WebSocket URLs (Binance Futures User Data Stream)
    # Production: wss://fstream.binance.com/ws/<listenKey>
    # Testnet: wss://stream.binancefuture.com/ws/<listenKey>
    WS_URL_PRODUCTION = "wss://fstream.binance.com/ws"
    WS_URL_TESTNET = "wss://stream.binancefuture.com/ws"

    def __init__(
        self,
        listen_key: str,
        use_testnet: bool = True
    ):
        """
        Initialize User Data Stream client.

        Args:
            listen_key: Listen key from get_listen_key()
            use_testnet: Use testnet WebSocket URL
        """
        self.listen_key = listen_key
        self.use_testnet = use_testnet

        # Build URL
        base_url = self.WS_URL_TESTNET if use_testnet else self.WS_URL_PRODUCTION
        self.ws_url = f"{base_url}/{listen_key}"

        # State
        self._websocket: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._reconnect_delay = 5  # seconds

        # Callbacks
        self._order_callback: Optional[Callable[[OrderUpdate], None]] = None
        self._account_callback: Optional[Callable[[AccountUpdate], None]] = None

        self.logger = logging.getLogger(__name__)
        self.logger.info(f"🔌 UserDataClient initialized: {'TESTNET' if use_testnet else 'PRODUCTION'}")

    def set_order_callback(self, callback: Callable[[OrderUpdate], None]):
        """Set callback for order updates."""
        self._order_callback = callback

    def set_account_callback(self, callback: Callable[[AccountUpdate], None]):
        """Set callback for account updates."""
        self._account_callback = callback

    async def connect(self):
        """
        Connect to User Data Stream and start listening.

        Automatically reconnects on disconnect.
        """
        self._running = True

        while self._running:
            try:
                self.logger.info(f"🔌 Connecting to User Data Stream...")

                async with websockets.connect(
                    self.ws_url,
                    ping_interval=180,  # Binance recommend < 10 min
                    ping_timeout=30
                ) as websocket:
                    self._websocket = websocket
                    self.logger.info("✅ User Data Stream connected")

                    # Listen loop
                    async for message in websocket:
                        await self._handle_message(message)

            except websockets.exceptions.ConnectionClosed as e:
                self.logger.warning(f"🔌 Connection closed: {e}")
                if self._running:
                    self.logger.info(f"⏳ Reconnecting in {self._reconnect_delay}s...")
                    await asyncio.sleep(self._reconnect_delay)

            except Exception as e:
                self.logger.error(f"❌ WebSocket error: {e}")
                if self._running:
                    await asyncio.sleep(self._reconnect_delay)

    async def disconnect(self):
        """Disconnect from User Data Stream."""
        self._running = False
        if self._websocket:
            await self._websocket.close()
            self._websocket = None
        self.logger.info("🔌 User Data Stream disconnected")

    async def _handle_message(self, message: str):
        """Handle incoming WebSocket message."""
        try:
            data = json.loads(message)
            event_type = data.get('e')

            if event_type == 'ORDER_TRADE_UPDATE':
                await self._handle_order_update(data)
            elif event_type == 'ACCOUNT_UPDATE':
                await self._handle_account_update(data)
            elif event_type == 'listenKeyExpired':
                self.logger.warning("⚠️ Listen key expired! Need to refresh.")
                # Could trigger reconnect with new listen key
            else:
                self.logger.debug(f"Unknown event: {event_type}")

        except json.JSONDecodeError:
            self.logger.error(f"Failed to parse message: {message[:100]}")
        except Exception as e:
            self.logger.error(f"Error handling message: {e}")

    async def _handle_order_update(self, data: Dict):
        """Handle ORDER_TRADE_UPDATE event."""
        order_data = data.get('o', {})
        order = OrderUpdate.from_binance(order_data)

        # Log important updates
        if order.status == 'FILLED':
            self.logger.info(
                f"✅ ORDER FILLED: {order.symbol} {order.side} "
                f"{order.filled_quantity} @ {order.average_price}"
            )
        elif order.status == 'NEW':
            self.logger.debug(f"📝 NEW order: {order.symbol} {order.order_type}")
        elif order.status == 'CANCELED':
            self.logger.info(f"❌ Order cancelled: {order.symbol} #{order.order_id}")

        # Invoke callback
        if self._order_callback:
            try:
                # Support both sync and async callbacks
                result = self._order_callback(order)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                self.logger.error(f"Order callback error: {e}")

    async def _handle_account_update(self, data: Dict):
        """Handle ACCOUNT_UPDATE event."""
        account_data = data.get('a', {})
        update = AccountUpdate.from_binance(account_data)

        self.logger.debug(
            f"📊 Account update: {len(update.balances)} balances, "
            f"{len(update.positions)} positions"
        )

        # Invoke callback
        if self._account_callback:
            try:
                result = self._account_callback(update)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                self.logger.error(f"Account callback error: {e}")

    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self._websocket is not None and self._websocket.open

    def __repr__(self) -> str:
        status = "CONNECTED" if self.is_connected else "DISCONNECTED"
        mode = "TESTNET" if self.use_testnet else "PRODUCTION"
        return f"BinanceUserDataClient({mode}, {status})"
