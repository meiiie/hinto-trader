"""
SharedBinanceClient - SOTA Multi-Symbol Combined Streams Manager

Single WebSocket connection for all symbols, routes data to registered handlers.
Follows Binance official best practices (Dec 2025).

Usage:
    client = SharedBinanceClient()
    client.register_handler('btcusdt', my_callback)
    client.register_handler('ethusdt', other_callback)
    await client.connect()  # 1 connection for ALL symbols
"""

import asyncio
import logging
from typing import Callable, Dict, List, Optional, Any
from datetime import datetime

from .binance_websocket_client import BinanceWebSocketClient, ConnectionStatus
from ...domain.entities.candle import Candle


class SharedBinanceClient:
    """
    SOTA: Shared WebSocket client for multi-symbol combined streams.

    Uses single Binance WebSocket connection for all symbols.
    Routes data to registered symbol-specific handlers.

    Benefits:
    - 1 connection instead of N (no timeout issues)
    - Lower latency (single connection to maintain)
    - Binance rate limit compliant
    - Scales to 100+ symbols easily
    """

    _instance: Optional['SharedBinanceClient'] = None

    def __new__(cls):
        """Singleton pattern"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self._client = BinanceWebSocketClient()
        self._handlers: Dict[str, List[Callable]] = {}  # symbol -> [callbacks]
        self._connection_handlers: List[Callable] = []
        self._symbols: List[str] = []
        self._intervals: List[str] = ['1m', '15m', '1h']  # Default timeframes
        self._is_running = False
        self.logger = logging.getLogger(__name__)
        # MEMORY FIX (Feb 8, 2026): Track fire-and-forget tasks for cleanup
        self._background_tasks: set = set()

        # Subscribe to client callbacks and route to handlers
        self._client.subscribe_candle(self._route_candle)
        self._client.subscribe_connection_status(self._route_connection_status)

    def register_handler(
        self,
        symbol: str,
        callback: Callable[[Candle, Dict[str, Any]], None],
        is_critical: bool = False
    ) -> None:
        """
        Register a callback for a specific symbol.

        SOTA (Jan 2026): Idempotent - safe to call multiple times without duplicates.

        DEPRECATED: is_critical parameter is ignored. All handlers now use fire-and-forget.
        Execution is handled by PriorityExecutionQueue for non-blocking data flow.

        Args:
            symbol: Symbol to receive data for (e.g., 'btcusdt')
            callback: Function to call with candle data
            is_critical: DEPRECATED - ignored, all handlers use fire-and-forget
        """
        symbol_lower = symbol.lower()
        is_new_symbol = symbol_lower not in self._handlers

        if is_new_symbol:
            self._handlers[symbol_lower] = []
            if symbol_lower not in self._symbols:
                self._symbols.append(symbol_lower)

        # SOTA (Jan 2026): Log deprecation warning if is_critical is used
        if is_critical:
            self.logger.warning(
                f"⚠️ DEPRECATED: is_critical=True for {symbol_lower} is ignored. "
                f"All handlers now use fire-and-forget. "
                f"Execution is handled by PriorityExecutionQueue."
            )

        # SOTA FIX: Idempotent registration - prevent duplicates
        if callback not in self._handlers[symbol_lower]:
            self._handlers[symbol_lower].append(callback)
            self.logger.info(f"📝 Registered handler for {symbol_lower} (total: {len(self._handlers[symbol_lower])})")
        else:
            self.logger.debug(f"Handler already registered for {symbol_lower}, skipping")

        # SOTA CRITICAL FIX (Feb 2026): Dynamic WebSocket subscription
        # If already connected and this is a NEW symbol, subscribe it NOW
        # This fixes the bug where Shark Tank symbols entered after startup
        # never received price ticks, causing Local SL to fail -> Backup SL (-2%) hit.
        if is_new_symbol and self._is_running:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                task = loop.create_task(self._subscribe_new_symbol(symbol_lower))
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
                self.logger.info(f"🚀 Dynamic subscription queued for {symbol_lower}")
            except RuntimeError:
                # No running loop - will be subscribed on next reconnect
                self.logger.warning(f"⚠️ No event loop for dynamic subscribe: {symbol_lower} (will sub on reconnect)")

    def unregister_handler(self, symbol: str, callback: Callable = None) -> bool:
        """
        SOTA (Feb 2026): Unregister handler(s) for a symbol.

        If callback is None, removes ALL handlers for symbol.
        If callback is provided, removes only that specific callback.

        This is critical for preventing:
        - Handler accumulation (memory leak)
        - Stale handlers processing wrong positions

        Args:
            symbol: Trading pair symbol (lowercase)
            callback: Specific callback to remove, or None to remove all

        Returns:
            True if any handler was removed
        """
        symbol_lower = symbol.lower()

        if symbol_lower not in self._handlers:
            self.logger.debug(f"No handlers to unregister for {symbol_lower}")
            return False

        if callback is None:
            # Remove ALL handlers for symbol
            count = len(self._handlers[symbol_lower])
            del self._handlers[symbol_lower]
            self.logger.info(f"🗑️ Unregistered ALL {count} handler(s) for {symbol_lower}")
            return True

        # Remove specific callback
        if callback in self._handlers[symbol_lower]:
            self._handlers[symbol_lower].remove(callback)
            self.logger.info(
                f"🗑️ Unregistered handler for {symbol_lower} "
                f"(remaining: {len(self._handlers[symbol_lower])})"
            )

            # Cleanup empty list
            if not self._handlers[symbol_lower]:
                del self._handlers[symbol_lower]

            return True

        self.logger.debug(f"Handler not found for {symbol_lower}")
        return False

    def register_connection_handler(self, callback: Callable[[ConnectionStatus], None]) -> None:
        """Register callback for connection status changes"""
        self._connection_handlers.append(callback)

    async def connect(self) -> None:
        """
        Connect to Binance with combined streams for all registered symbols.
        """
        if self._is_running:
            self.logger.warning("SharedBinanceClient already running")
            return

        if not self._symbols:
            self.logger.error("No symbols registered! Call register_handler first.")
            return

        self._is_running = True
        self.logger.info(f"🚀 SOTA Combined Streams: {len(self._symbols)} symbols × {len(self._intervals)} timeframes")

        try:
            await self._client.connect(
                symbols=self._symbols,
                intervals=self._intervals
            )
        except Exception as e:
            self.logger.error(f"❌ Failed to connect to Binance: {e}", exc_info=True)
            self._is_running = False
            raise

    async def disconnect(self) -> None:
        """Disconnect from Binance and cleanup all tracked tasks."""
        self._is_running = False
        # MEMORY FIX (Feb 8, 2026): Cancel all pending background tasks
        for task in list(self._background_tasks):
            if not task.done():
                task.cancel()
        self._background_tasks.clear()

    async def _subscribe_new_symbol(self, symbol: str) -> None:
        """
        SOTA (Feb 2026): Subscribe a new symbol to existing WebSocket connection.

        Called when a handler is registered for a symbol AFTER connect() was called.
        This fixes the bug where Shark Tank symbols (PIPPINUSDT, etc.) entered
        after backend startup never received price ticks.
        """
        try:
            result = await self._client.subscribe_symbol(symbol)
            if result:
                self.logger.info(f"✅ Dynamic subscription SUCCESS: {symbol}")
            else:
                self.logger.warning(f"⚠️ Dynamic subscription FAILED: {symbol}")
        except Exception as e:
            self.logger.error(f"❌ Dynamic subscription ERROR for {symbol}: {e}")

    async def _route_candle(self, candle: Candle, metadata: Dict[str, Any]) -> None:
        """
        Route candle data to the correct symbol handler.

        SOTA (Jan 2026): ALL handlers use fire-and-forget pattern.
        No is_critical distinction - execution is handled by PriorityExecutionQueue.

        SOTA (Jan 2026): Multi-position realtime prices
        Also publishes price_update events for portfolio positions.

        This ensures:
        - Non-blocking event loop for 50 symbols × 3 timeframes
        - No handler can block other symbols' data processing
        - TP/SL execution latency handled by dedicated ExecutionWorker
        """
        symbol = metadata.get('symbol', '').lower()
        interval = metadata.get('interval', '1m')

        # SOTA (Jan 2026): Publish price_update for ALL symbols on 1m candles
        # This enables realtime prices for portfolio positions
        if interval == '1m' and candle.close:
            try:
                from src.api.event_bus import get_event_bus
                event_bus = get_event_bus()
                event_bus.publish_price_update(
                    symbol=symbol,
                    price=candle.close,
                    timestamp=int(candle.timestamp.timestamp() * 1000) if hasattr(candle.timestamp, 'timestamp') else None
                )
            except Exception as e:
                self.logger.debug(f"Could not publish price_update for {symbol}: {e}")

        if symbol in self._handlers:
            for callback in self._handlers[symbol]:
                # SOTA (Jan 2026): Fire-and-forget for ALL handlers
                # No is_critical distinction - execution handled by PriorityExecutionQueue
                if asyncio.iscoroutinefunction(callback):
                    task = asyncio.create_task(self._safe_callback(callback, candle, metadata, symbol))
                    # MEMORY FIX (Feb 8, 2026): Track task and auto-discard on completion
                    self._background_tasks.add(task)
                    task.add_done_callback(self._background_tasks.discard)
                else:
                    # Sync callback (discouraged but supported)
                    try:
                        callback(candle, metadata)
                    except Exception as e:
                        self.logger.error(f"Error in sync handler for {symbol}: {e}")

    async def _safe_callback(self, callback, candle, metadata, symbol):
        """Wrapper to catch exceptions in fire-and-forget tasks"""
        try:
            await callback(candle, metadata)
        except Exception as e:
            self.logger.error(f"❌ Error in async handler for {symbol}: {e}", exc_info=True)

    async def _route_connection_status(self, status: ConnectionStatus) -> None:
        """Route connection status to all handlers"""
        for callback in self._connection_handlers:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(status)
                else:
                    callback(status)
            except Exception as e:
                self.logger.error(f"Error in connection handler: {e}")

    async def subscribe_symbol(self, symbol: str) -> bool:
        """
        SOTA (Jan 2026): Dynamic subscribe to new symbol on existing connection.

        Called when new position opened for symbol not in initial list.
        Routes to underlying BinanceWebSocketClient.subscribe_symbol().

        Args:
            symbol: Symbol to subscribe (e.g., 'vvvusdt')

        Returns:
            True if subscription successful
        """
        symbol_lower = symbol.lower()

        # FIX P0 (Feb 13, 2026): Removed _symbols short-circuit check.
        # register_handler() adds to _symbols BEFORE actual WebSocket subscription.
        # The underlying BinanceWebSocketClient.subscribe_symbol() has its own
        # _confirmed_subscriptions check which accurately tracks actual subscriptions.

        # Subscribe via underlying client
        success = await self._client.subscribe_symbol(symbol_lower)

        if success:
            # Update local tracking
            if symbol_lower not in self._symbols:
                self._symbols.append(symbol_lower)
            if symbol_lower not in self._handlers:
                self._handlers[symbol_lower] = []
            self.logger.info(f"✅ Dynamic subscription active: {symbol_lower}")

        return success

    @property
    def is_connected(self) -> bool:
        return self._client.is_connected()

    def get_status(self) -> ConnectionStatus:
        return self._client.get_connection_status()


# Singleton getter
_shared_client: Optional[SharedBinanceClient] = None

def get_shared_binance_client() -> SharedBinanceClient:
    """Get the singleton SharedBinanceClient instance"""
    global _shared_client
    if _shared_client is None:
        _shared_client = SharedBinanceClient()
    return _shared_client
