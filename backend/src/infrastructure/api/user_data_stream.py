"""
UserDataStreamService - Infrastructure Layer

SOTA Binance Futures User Data Stream for real-time account updates.

Features:
- listenKey lifecycle management (create, keep-alive, delete)
- WebSocket connection with auto-reconnect
- ACCOUNT_UPDATE event processing
- Balance/position cache with real-time updates

Reference: https://developers.binance.com/docs/derivatives/usds-margined-futures/user-data-stream

Usage:
    service = UserDataStreamService(use_testnet=True)
    await service.start()

    # Get cached balance (instant)
    balance = service.get_cached_balance()

    # Stop on shutdown
    await service.stop()
"""

import os
import json
import asyncio
import logging
import threading
from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass, field
from datetime import datetime, timezone
import websockets
import requests


@dataclass
class AccountBalance:
    """Cached account balance from User Data Stream."""
    asset: str
    wallet_balance: float
    available_balance: float
    unrealized_pnl: float
    margin_balance: float
    last_update: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class StreamPosition:
    """Cached position from User Data Stream."""
    symbol: str
    position_amt: float
    entry_price: float
    unrealized_pnl: float
    margin_type: str  # 'cross' or 'isolated'
    last_update: datetime = field(default_factory=datetime.utcnow)


class UserDataStreamService:
    """
    SOTA User Data Stream Service.

    Manages Binance Futures User Data Stream for real-time account updates.

    Architecture:
    - listenKey management (create, keep-alive every 30min, delete)
    - WebSocket connection with auto-reconnect
    - Event processing (ACCOUNT_UPDATE, ORDER_TRADE_UPDATE)
    - In-memory cache for instant balance/position queries
    - Callback system for broadcasting updates
    """

    # API Endpoints
    PRODUCTION_BASE_URL = "https://fapi.binance.com"
    TESTNET_BASE_URL = "https://testnet.binancefuture.com"

    PRODUCTION_WS_URL = "wss://fstream.binance.com/ws"
    TESTNET_WS_URL = "wss://fstream.binancefuture.com/ws"

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        use_testnet: Optional[bool] = None,
        on_balance_update: Optional[Callable[[Dict[str, AccountBalance]], None]] = None,
        on_position_update: Optional[Callable[[Dict[str, StreamPosition]], None]] = None,
        on_order_update: Optional[Callable[[Dict[str, Any]], None]] = None
    ):
        """
        Initialize User Data Stream Service.

        Args:
            api_key: Binance API key (defaults to env var)
            api_secret: Binance API secret (defaults to env var)
            use_testnet: Use testnet (defaults to ENV variable)
            on_balance_update: Callback when balance changes
            on_position_update: Callback when position changes
            on_order_update: Callback when order status changes
        """
        self.logger = logging.getLogger(__name__)

        # Determine testnet from ENV variable
        if use_testnet is not None:
            self.use_testnet = use_testnet
        else:
            env = os.getenv("ENV", "paper").lower()
            if env == "testnet":
                self.use_testnet = True
            elif env == "live":
                self.use_testnet = False
            else:
                self.use_testnet = True  # Default to testnet for safety

        # Load API credentials
        if self.use_testnet:
            self.api_key = api_key or os.getenv("BINANCE_TESTNET_API_KEY")
            self.api_secret = api_secret or os.getenv("BINANCE_TESTNET_API_SECRET")
            self.base_url = self.TESTNET_BASE_URL
            self.ws_url = self.TESTNET_WS_URL
        else:
            self.api_key = api_key or os.getenv("BINANCE_API_KEY")
            self.api_secret = api_secret or os.getenv("BINANCE_API_SECRET")
            self.base_url = self.PRODUCTION_BASE_URL
            self.ws_url = self.PRODUCTION_WS_URL

        if not self.api_key:
            self.logger.warning("No API key provided - User Data Stream cannot start")

        # Callbacks
        self.on_balance_update = on_balance_update
        self.on_position_update = on_position_update
        self.on_order_update = on_order_update

        # State
        self._listen_key: Optional[str] = None
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._keep_alive_task: Optional[asyncio.Task] = None
        self._ws_task: Optional[asyncio.Task] = None
        self._reconnect_count = 0
        self._max_reconnects = 10

        # Cache: per-asset balances
        self._balances: Dict[str, AccountBalance] = {}
        self._positions: Dict[str, StreamPosition] = {}

        # Cache: account-level totals (SOTA: from /fapi/v3/account)
        self._total_wallet_balance: float = 0.0
        self._total_unrealized_pnl: float = 0.0
        self._total_margin_balance: float = 0.0
        self._total_available_balance: float = 0.0

        mode_str = "🧪 TESTNET" if self.use_testnet else "🔴 PRODUCTION"
        self.logger.info(f"UserDataStreamService initialized | {mode_str}")

    # =========================================================================
    # LISTEN KEY MANAGEMENT
    # =========================================================================

    def _create_listen_key(self) -> Optional[str]:
        """
        Create a new listenKey via REST API.

        Returns:
            listenKey string or None on failure
        """
        try:
            response = requests.post(
                f"{self.base_url}/fapi/v1/listenKey",
                headers={"X-MBX-APIKEY": self.api_key},
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                listen_key = data.get("listenKey")
                self.logger.info(f"✅ Created listenKey: {listen_key[:16]}...")
                return listen_key
            else:
                self.logger.error(f"Failed to create listenKey: {response.text}")
                return None

        except Exception as e:
            self.logger.error(f"Error creating listenKey: {e}")
            return None

    def _keep_alive_listen_key(self) -> bool:
        """
        Extend listenKey validity by 60 minutes.

        Should be called every 30 minutes to prevent timeout.

        Returns:
            True on success, False on failure
        """
        if not self._listen_key:
            return False

        try:
            response = requests.put(
                f"{self.base_url}/fapi/v1/listenKey",
                headers={"X-MBX-APIKEY": self.api_key},
                timeout=10
            )

            if response.status_code == 200:
                self.logger.debug("♻️ listenKey keep-alive success")
                return True
            else:
                self.logger.warning(f"listenKey keep-alive failed: {response.text}")
                return False

        except Exception as e:
            self.logger.error(f"Error in keep-alive: {e}")
            return False

    def _delete_listen_key(self) -> bool:
        """
        Invalidate the current listenKey.

        Call this on graceful shutdown.

        Returns:
            True on success, False on failure
        """
        if not self._listen_key:
            return True

        try:
            response = requests.delete(
                f"{self.base_url}/fapi/v1/listenKey",
                headers={"X-MBX-APIKEY": self.api_key},
                timeout=10
            )

            if response.status_code == 200:
                self.logger.info("🗑️ listenKey deleted")
                self._listen_key = None
                return True
            else:
                self.logger.warning(f"Failed to delete listenKey: {response.text}")
                return False

        except Exception as e:
            self.logger.error(f"Error deleting listenKey: {e}")
            return False

    # =========================================================================
    # WEBSOCKET CONNECTION
    # =========================================================================

    async def start(self):
        """
        Start the User Data Stream.

        1. Create listenKey
        2. Connect to WebSocket
        3. Start keep-alive loop
        """
        if self._running:
            self.logger.warning("UserDataStream already running")
            return

        if not self.api_key:
            self.logger.error("Cannot start - no API key")
            return

        self._running = True
        self._reconnect_count = 0

        # Create listenKey
        self._listen_key = self._create_listen_key()
        if not self._listen_key:
            self.logger.error("Failed to create listenKey - cannot start stream")
            self._running = False
            return

        # SOTA: Fetch initial balance via REST API to populate cache
        # This ensures cached_balance is available immediately
        self._fetch_initial_balance()

        # Start keep-alive loop (every 30 minutes)
        self._keep_alive_task = asyncio.create_task(self._keep_alive_loop())

        # Start WebSocket connection
        self._ws_task = asyncio.create_task(self._ws_loop())

        self.logger.info("🚀 UserDataStream started")

    async def stop(self):
        """
        Stop the User Data Stream gracefully.

        1. Cancel tasks
        2. Close WebSocket
        3. Delete listenKey
        """
        self.logger.info("🛑 Stopping UserDataStream...")
        self._running = False

        # Cancel tasks
        if self._keep_alive_task:
            self._keep_alive_task.cancel()
            try:
                await self._keep_alive_task
            except asyncio.CancelledError:
                pass

        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass

        # Close WebSocket
        if self._ws:
            await self._ws.close()
            self._ws = None

        # Delete listenKey
        self._delete_listen_key()

        self.logger.info("✅ UserDataStream stopped")

    async def _keep_alive_loop(self):
        """Background loop to keep listenKey alive every 30 minutes."""
        while self._running:
            try:
                await asyncio.sleep(30 * 60)  # 30 minutes
                if self._running:
                    success = self._keep_alive_listen_key()
                    if not success:
                        # listenKey expired, need to recreate
                        self._listen_key = self._create_listen_key()
                        if self._listen_key:
                            # Reconnect WebSocket with new key
                            if self._ws:
                                await self._ws.close()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in keep-alive loop: {e}")

    async def _ws_loop(self):
        """Main WebSocket connection loop with auto-reconnect."""
        while self._running:
            try:
                ws_url = f"{self.ws_url}/{self._listen_key}"
                self.logger.info(f"🔌 Connecting to User Data Stream...")

                async with websockets.connect(ws_url) as ws:
                    self._ws = ws
                    self._reconnect_count = 0
                    self.logger.info("✅ Connected to User Data Stream")

                    async for message in ws:
                        if not self._running:
                            break
                        await self._process_message(message)

            except websockets.ConnectionClosed as e:
                self.logger.warning(f"WebSocket closed: {e}")
            except Exception as e:
                self.logger.error(f"WebSocket error: {e}")

            # Reconnect logic
            if self._running:
                self._reconnect_count += 1
                if self._reconnect_count >= self._max_reconnects:
                    self.logger.error("Max reconnects reached - stopping stream")
                    self._running = False
                    break

                # Exponential backoff: 1s, 2s, 4s, 8s... max 60s
                delay = min(2 ** self._reconnect_count, 60)
                self.logger.info(f"Reconnecting in {delay}s... (attempt {self._reconnect_count})")
                await asyncio.sleep(delay)

                # Recreate listenKey if needed
                if not self._keep_alive_listen_key():
                    self._listen_key = self._create_listen_key()
                    if not self._listen_key:
                        self.logger.error("Failed to recreate listenKey")
                        self._running = False
                        break

    # =========================================================================
    # MESSAGE PROCESSING
    # =========================================================================

    async def _process_message(self, raw_message: str):
        """
        Process incoming WebSocket message.

        Event types:
        - ACCOUNT_UPDATE: Balance/position changes
        - ORDER_TRADE_UPDATE: Order status changes
        - listenKeyExpired: Need to recreate key
        """
        try:
            data = json.loads(raw_message)
            event_type = data.get("e")

            if event_type == "ACCOUNT_UPDATE":
                await self._handle_account_update(data)
            elif event_type == "ORDER_TRADE_UPDATE":
                # SOTA (Jan 2026): Extract fill data for LOCAL PnL tracking
                # This ensures we have exact fill prices and fees
                await self._handle_order_update(data)

            elif event_type == "CONDITIONAL_ORDER_TRADE_UPDATE":
                # SOTA (Jan 2026): Handle Algo Order updates (STOP_MARKET, TAKE_PROFIT_MARKET)
                # Structure is very similar to ORDER_TRADE_UPDATE but with 'st' (strategy type)
                await self._handle_order_update(data, is_conditional=True)
            elif event_type == "ALGO_UPDATE":
                # SOTA (Jan 2026): New Algo Service event (Binance migration Dec 2025)
                # This is the PRIMARY event for Algo Orders now, includes status:
                # NEW, TRIGGERING, TRIGGERED, FINISHED, CANCELED, REJECTED, EXPIRED
                await self._handle_algo_update(data)
            elif event_type == "listenKeyExpired":
                self.logger.warning("⚠️ listenKey expired - reconnecting")
                self._listen_key = self._create_listen_key()
                if self._ws:
                    await self._ws.close()
            else:
                self.logger.debug(f"Unknown event type: {event_type}")

        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse message: {e}")
        except Exception as e:
            self.logger.error(f"Error processing message: {e}")

    async def _handle_account_update(self, data: Dict[str, Any]):
        """
        Handle ACCOUNT_UPDATE event.

        Updates balance and position caches, triggers callbacks.

        Event data structure:
        {
            "e": "ACCOUNT_UPDATE",
            "T": 1234567890,
            "a": {
                "m": "ORDER",  # reason type
                "B": [{"a": "USDT", "wb": "100.0", "cw": "90.0", "bc": "10.0"}],
                "P": [{"s": "BTCUSDT", "pa": "0.001", "ep": "95000.0", ...}]
            }
        }
        """
        account_data = data.get("a", {})
        reason = account_data.get("m", "UNKNOWN")

        self.logger.info(f"📊 ACCOUNT_UPDATE received | reason: {reason}")

        # Update balances
        balances = account_data.get("B", [])
        for b in balances:
            asset = b.get("a", "")
            self._balances[asset] = AccountBalance(
                asset=asset,
                wallet_balance=float(b.get("wb", 0)),
                available_balance=float(b.get("cw", 0)),  # crossWalletBalance
                unrealized_pnl=0,  # Not in this event
                margin_balance=float(b.get("wb", 0)),  # Approximate
                last_update=datetime.now(timezone.utc)
            )
            self.logger.info(f"   💰 {asset}: ${float(b.get('wb', 0)):.2f}")

        # Update positions
        positions = account_data.get("P", [])
        for p in positions:
            symbol = p.get("s", "")
            pos_unrealized = float(p.get("up", 0))
            self._positions[symbol] = StreamPosition(
                symbol=symbol,
                position_amt=float(p.get("pa", 0)),
                entry_price=float(p.get("ep", 0)),
                unrealized_pnl=pos_unrealized,
                margin_type=p.get("mt", "cross"),
                last_update=datetime.now(timezone.utc)
            )
            if pos_unrealized != 0:
                self.logger.info(f"   📈 {symbol}: PnL ${pos_unrealized:.2f}")


        # SOTA: Recalculate account totals from cached per-asset and per-position data
        self._recalculate_totals()

        # SOTA (Feb 2026): Update Circuit Breaker portfolio state
        # Monitors daily drawdown and triggers global halt if > 10%
        try:
            from src.api.dependencies import get_container
            import os
            env = os.getenv("ENV", "paper").lower()
            if env in ["testnet", "live"] and self._total_wallet_balance > 0:
                container = get_container()
                live_service = container.get_live_trading_service()
                if live_service and hasattr(live_service, 'circuit_breaker') and live_service.circuit_breaker:
                    live_service.circuit_breaker.update_portfolio_state(
                        self._total_wallet_balance,
                        datetime.now(timezone.utc)
                    )
        except Exception as e:
            self.logger.debug(f"CB portfolio update failed (non-critical): {e}")

        # ═══════════════════════════════════════════════════════════════════════
        # DYNAMIC Portfolio Target (Jan 2026)
        #
        # SOTA: Target = current_wallet_balance * pct (NOT fixed initial_balance)
        # This ensures target adjusts after deposits/withdrawals
        #
        # On EVERY ACCOUNT_UPDATE:
        # 1. Update initial_balance if it was 0 (first time)
        # 2. ALWAYS recalculate portfolio_target_usd based on current balance
        # ═══════════════════════════════════════════════════════════════════════
        try:
            from src.api.dependencies import get_container
            import os
            env = os.getenv("ENV", "paper").lower()
            if env in ["testnet", "live"]:
                container = get_container()
                live_service = container.get_live_trading_service()

                if live_service and self._total_wallet_balance > 0:
                    # Track if this is first time (for logging)
                    is_first_time = live_service.initial_balance == 0

                    # First time balance is available - set initial_balance
                    if is_first_time:
                        live_service.initial_balance = self._total_wallet_balance
                        live_service.peak_balance = self._total_wallet_balance
                        self.logger.info(
                            f"💰 Initial balance set: ${self._total_wallet_balance:.2f}"
                        )

                    # DYNAMIC: ALWAYS recalculate portfolio target based on CURRENT balance
                    if (hasattr(live_service, 'portfolio_target_pct') and
                        live_service.portfolio_target_pct > 0):

                        # Use current wallet balance, NOT initial_balance
                        target_usd = self._total_wallet_balance * (live_service.portfolio_target_pct / 100.0)

                        # Update PositionMonitor
                        if hasattr(live_service, 'position_monitor') and live_service.position_monitor:
                            old_target = live_service.position_monitor.portfolio_target_usd
                            live_service.position_monitor.set_portfolio_target(target_usd)

                            # Only log if target actually changed
                            if is_first_time or abs(old_target - target_usd) > 0.01:
                                self.logger.info(
                                    f"🎯 DYNAMIC Portfolio Target: ${target_usd:.2f} "
                                    f"({live_service.portfolio_target_pct}% of ${self._total_wallet_balance:.2f})"
                                )
        except Exception as e:
            self.logger.debug(f"Portfolio target auto-update skipped: {e}")

        # SOTA: Publish to EventBus for real-time frontend push
        try:
            from src.api.event_bus import get_event_bus
            event_bus = get_event_bus()
            event_bus.publish_balance_update({
                "wallet_balance": self._total_wallet_balance,
                "unrealized_pnl": self._total_unrealized_pnl,
                "margin_balance": self._total_margin_balance,
                "available_balance": self._total_available_balance,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            self.logger.info(f"📡 Balance published: Wallet=${self._total_wallet_balance:.2f}, PnL=${self._total_unrealized_pnl:.2f}")
        except Exception as e:
            self.logger.error(f"Failed to publish balance update: {e}")

        # Trigger callback (legacy)
        if self.on_balance_update and balances:
            self.on_balance_update(self._balances)
        if self.on_position_update and positions:
            self.on_position_update(self._positions)

    async def _handle_order_update(self, data: Dict[str, Any], is_conditional: bool = False):
        """
        Handle ORDER_TRADE_UPDATE and CONDITIONAL_ORDER_TRADE_UPDATE events.

        SOTA v3 (Jan 2026): Supports Algo Orders (STOP_MARKET, etc.)

        Event data structure (ORDER_TRADE_UPDATE):
        {
            "e": "ORDER_TRADE_UPDATE",
            "o": { "s": "BTCUSDT", "S": "BUY", "o": "LIMIT", "X": "NEW", ... }
        }

        Event data structure (CONDITIONAL_ORDER_TRADE_UPDATE):
        {
            "e": "CONDITIONAL_ORDER_TRADE_UPDATE",
            "o": { "s": "BTCUSDT", "S": "SELL", "st": "STOP_MARKET", "X": "NEW", ... }
        }
        """
        order_data = data.get("o", {})

        symbol = order_data.get("s", "")
        side = order_data.get("S", "")
        # For Algo Orders, 'st' (Strategy Type) is the order type (STOP_MARKET)
        # For Regular Orders, 'o' is the order type (LIMIT, MARKET)
        order_type = order_data.get("st") if is_conditional else order_data.get("o", "")
        if not order_type and not is_conditional:
             order_type = order_data.get("o", "") # Fallback

        status = order_data.get("X", "")
        order_id = order_data.get("i", 0) # For Algo, this is algoId or orderId depending on state

        self.logger.info(f"📝 {'ALGO_' if is_conditional else ''}ORDER_UPDATE | {symbol} {side} {order_type} → {status}")

        # SOTA: Normalize order data for cache
        normalized_order = {
            'orderId': order_id,
            'symbol': symbol,
            'side': side,
            'type': order_type,
            'status': status,
            'price': float(order_data.get("p", 0)),
            'origQty': float(order_data.get("q", 0)),
            'executedQty': float(order_data.get("z", 0)),
            'stopPrice': float(order_data.get("sp", 0)),
            'avgPrice': float(order_data.get("ap", 0)),
            'is_algo': is_conditional
        }

        # Determine if order is closed
        is_closed = status in ['FILLED', 'CANCELED', 'EXPIRED', 'REJECTED']

        # Call back with normalized data + is_closed flag
        if self.on_order_update:
            # Inject is_closed for cache update
            normalized_order['_is_closed'] = is_closed
            self.on_order_update(normalized_order)

        # SOTA (Jan 2026): Record fill to LOCAL tracker (Two Sigma Pattern)
        # Check if we have live_service reference via container (since UserDataStream is infra level)
        try:
             # Only record actual fills
            if status in ['FILLED', 'PARTIALLY_FILLED']:
                fill_qty = float(order_data.get("l", 0))     # Last Filled Quantity

                if fill_qty > 0:
                    fill_price = float(order_data.get("L", 0))  # Last Filled Price (exact)
                    if fill_price == 0:
                        fill_price = float(order_data.get("ap", 0)) # Average Price fallback

                    fill_fee = float(order_data.get("n", 0))    # Commission Amount
                    is_maker = order_data.get("m", False)       # Is Maker?

                    # We need to access LiveTradingService instance to call _record_fill_to_local_tracker
                    # Use dependency injection container pattern
                    from src.api.dependencies import get_container
                    container = get_container()
                    live_service = container.get_live_trading_service()

                    if live_service:
                        live_service._record_fill_to_local_tracker(
                            symbol=symbol,
                            fill_price=fill_price,
                            fill_qty=fill_qty,
                            fill_fee=fill_fee,
                            order_id=str(order_id),
                            side=side,  # SOTA FIX (Jan 2026): Pass side for Entry/Exit detection
                            is_maker=is_maker
                        )
        except Exception as e:
            self.logger.error(f"Failed to record local fill: {e}")



    async def _handle_algo_update(self, data: Dict[str, Any]):
        """
        Handle ALGO_UPDATE event (Binance Algo Service, Dec 2025+).

        SOTA: This is the PRIMARY event for tracking Algo Order lifecycle.
        Status values:
        - NEW: Algo order created, waiting for trigger
        - TRIGGERING: Price hit trigger, order being sent to matching engine
        - TRIGGERED: Order successfully placed in matching engine
        - FINISHED: Triggered order was executed or cancelled in matching engine
        - CANCELED: Algo order was cancelled before trigger
        - REJECTED: Algo order was rejected (margin check failed, etc.)
        - EXPIRED: Algo order expired (e.g., all positions closed)

        Key fields:
        - algoId: Unique ID for this algo order
        - symbol: Trading pair
        - side: BUY or SELL
        - type: STOP_MARKET, TAKE_PROFIT_MARKET, etc.
        - status: NEW, TRIGGERING, TRIGGERED, FINISHED, CANCELED, REJECTED, EXPIRED
        - triggerPrice: The price that triggers this order
        """
        # SOTA DEBUG (Feb 2026): Log raw message to diagnose algoId extraction
        self.logger.debug(f"🔍 RAW ALGO_UPDATE: {data}")

        # SOTA (Feb 2026): Try multiple structures - Binance may wrap data differently
        # Structure 1: data["o"] wrapper (like ORDER_TRADE_UPDATE)
        # Structure 2: Top-level data (direct fields)
        algo_data = data.get("o", {}) if "o" in data else data

        # SOTA FIX (Feb 2026): Multiple fallback keys for algoId
        # Binance may use: algoId, aI, i, orderId depending on message type
        algo_id = (
            algo_data.get("algoId") or
            algo_data.get("aI") or  # Short form used in some WS messages
            algo_data.get("i") or   # Generic order ID field
            data.get("algoId") or   # Try top-level
            data.get("aI") or
            data.get("i") or
            0
        )

        # Ensure algo_id is converted to string for consistency
        algo_id = str(algo_id) if algo_id else "0"

        symbol = (algo_data.get("s") or algo_data.get("symbol") or data.get("s") or "").upper()
        side = algo_data.get("S") or algo_data.get("side") or data.get("S") or ""
        order_type = algo_data.get("st") or algo_data.get("type") or data.get("st") or ""  # 'st' for strategy type
        status = algo_data.get("X") or algo_data.get("status") or data.get("X") or ""
        trigger_price = float(algo_data.get("sp") or algo_data.get("triggerPrice") or data.get("sp") or 0)
        quantity = float(algo_data.get("q") or algo_data.get("quantity") or data.get("q") or 0)
        fill_price = float(algo_data.get("ap") or algo_data.get("avgPrice") or data.get("ap") or 0)  # Average fill price


        # SOTA (Jan 2026): Enhanced logging for order lifecycle tracking (Task 9.3)
        if status in ['TRIGGERED', 'FINISHED']:
            self.logger.info(
                f"📊 ALGO TRIGGERED: {symbol} | AlgoID: {algo_id} | Type: {order_type} | "
                f"Side: {side} | TriggerPrice: ${trigger_price:.4f} | FillPrice: ${fill_price:.4f} | "
                f"Qty: {quantity:.6f} | Status: {status}"
            )
        else:
            self.logger.info(f"📊 ALGO_UPDATE | {symbol} {order_type} {side} → {status} (algoId={algo_id})")

        # Determine if this is a terminal status that requires cleanup
        is_terminal = status in ['TRIGGERED', 'FINISHED', 'CANCELED', 'REJECTED', 'EXPIRED']

        # Normalize for callback
        normalized = {
            'algoId': algo_id,
            'orderId': algo_id,  # Use algoId as orderId for compatibility
            'symbol': symbol,
            'side': side,
            'type': order_type,
            'status': status,
            'stopPrice': trigger_price,
            'is_algo': True,
            '_is_closed': is_terminal,
            '_is_terminal': is_terminal,
            '_algo_status': status  # Raw Algo status for precise handling
        }

        # Call order update callback (will trigger LiveTradingService.update_cached_order)
        if self.on_order_update:
            self.on_order_update(normalized)

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    def get_cached_balance(self, asset: str = "USDT") -> Optional[AccountBalance]:
        """Get cached balance for an asset (instant, no API call)."""
        return self._balances.get(asset)

    def get_cached_usdt_wallet_balance(self) -> float:
        """Get cached USDT wallet balance."""
        balance = self._balances.get("USDT")
        return balance.wallet_balance if balance else 0.0

    def get_cached_usdt_available(self) -> float:
        """Get cached USDT available balance."""
        balance = self._balances.get("USDT")
        return balance.available_balance if balance else 0.0

    # SOTA: Account-level total getters
    @property
    def total_wallet_balance(self) -> float:
        """Get total wallet balance across all assets."""
        return self._total_wallet_balance

    @property
    def total_unrealized_pnl(self) -> float:
        """Get total unrealized PnL from all positions."""
        return self._total_unrealized_pnl

    @property
    def total_margin_balance(self) -> float:
        """Get total margin balance (wallet + unrealized PnL)."""
        return self._total_margin_balance

    @property
    def total_available_balance(self) -> float:
        """Get total available balance for new trades."""
        return self._total_available_balance

    def _recalculate_totals(self):
        """
        SOTA (USDT-M Futures): Calculate totals using USDT only.

        For USDT-M Futures, only USDT is used as margin collateral.
        Other assets (USDC, BTC) are not used for trading.

        Called after each ACCOUNT_UPDATE to ensure fresh totals before publishing.
        """
        # USDT-M Futures: Use USDT only (not USDC/BTC)
        usdt_balance = self._balances.get("USDT")

        if usdt_balance:
            self._total_wallet_balance = usdt_balance.wallet_balance
            self._total_available_balance = usdt_balance.available_balance
        else:
            self._total_wallet_balance = 0.0
            self._total_available_balance = 0.0

        # Sum unrealized PnL from all positions
        self._total_unrealized_pnl = sum(
            p.unrealized_pnl for p in self._positions.values()
        )

        # Margin = Wallet + Unrealized PnL
        self._total_margin_balance = self._total_wallet_balance + self._total_unrealized_pnl

        self.logger.debug(
            f"Recalculated totals (USDT only): W=${self._total_wallet_balance:.2f}, "
            f"U=${self._total_unrealized_pnl:.2f}, M=${self._total_margin_balance:.2f}"
        )

    def get_cached_position(self, symbol: str) -> Optional[StreamPosition]:
        """Get cached position for a symbol (instant, no API call)."""
        return self._positions.get(symbol)

    def get_all_cached_positions(self) -> Dict[str, StreamPosition]:
        """Get all cached positions."""
        return self._positions.copy()

    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self._ws is not None and self._running

    @property
    def last_balance_update(self) -> Optional[datetime]:
        """Get timestamp of last balance update."""
        usdt = self._balances.get("USDT")
        return usdt.last_update if usdt else None

    def _fetch_initial_balance(self):
        """
        Fetch initial balance via REST API to populate cache.

        SOTA: Call /fapi/v3/account on stream start to have
        immediate balance data before any ACCOUNT_UPDATE arrives.
        """
        try:
            import hmac
            import hashlib
            import time

            timestamp = int(time.time() * 1000)
            query_string = f"timestamp={timestamp}"

            signature = hmac.new(
                self.api_secret.encode('utf-8') if self.api_secret else b'',
                query_string.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()

            response = requests.get(
                f"{self.base_url}/fapi/v3/account?{query_string}&signature={signature}",
                headers={"X-MBX-APIKEY": self.api_key},
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()

                # SOTA: Save account-level totals first
                self._total_wallet_balance = float(data.get("totalWalletBalance", 0))
                self._total_unrealized_pnl = float(data.get("totalUnrealizedProfit", 0))
                self._total_margin_balance = float(data.get("totalMarginBalance", 0))
                self._total_available_balance = float(data.get("availableBalance", 0))

                # Parse per-asset balances
                assets = data.get("assets", [])
                for item in assets:
                    asset = item.get("asset", "")
                    wallet_balance = float(item.get("walletBalance", 0))

                    if wallet_balance > 0 or asset == "USDT":
                        self._balances[asset] = AccountBalance(
                            asset=asset,
                            wallet_balance=wallet_balance,
                            available_balance=float(item.get("availableBalance", 0)),
                            unrealized_pnl=float(item.get("unrealizedProfit", 0)),
                            margin_balance=float(item.get("marginBalance", 0)),
                            last_update=datetime.now(timezone.utc)
                        )

                self.logger.info(
                    f"💰 Initial balance loaded: "
                    f"Wallet=${self._total_wallet_balance:.2f}, "
                    f"Unrealized=${self._total_unrealized_pnl:.2f}, "
                    f"Margin=${self._total_margin_balance:.2f}"
                )
            else:
                self.logger.warning(f"Failed to fetch initial balance: {response.text}")

        except Exception as e:
            self.logger.error(f"Error fetching initial balance: {e}")
