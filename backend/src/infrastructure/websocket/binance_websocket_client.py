"""
BinanceWebSocketClient - Infrastructure Layer

WebSocket client for real-time Binance market data streaming.
Supports both SPOT and FUTURES markets.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Callable, Dict, Any
from dataclasses import dataclass
from enum import Enum

try:
    import websockets
    from websockets.client import WebSocketClientProtocol
except ImportError:
    raise ImportError(
        "websockets library is required for real-time streaming. "
        "Install it with: pip install websockets>=12.0"
    )

from .message_parser import BinanceMessageParser
from ...domain.entities.candle import Candle
from ...config.market_mode import MarketMode, get_market_config, get_default_market_mode


class ConnectionState(Enum):
    """WebSocket connection states"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


@dataclass
class ConnectionStatus:
    """Connection status information"""
    is_connected: bool
    state: ConnectionState
    last_update: datetime
    latency_ms: int
    reconnect_count: int
    error_message: Optional[str] = None


class BinanceWebSocketClient:
    """
    WebSocket client for Binance real-time data streaming.

    SOTA: Supports both SPOT and FUTURES modes via MarketMode parameter.
    Default is FUTURES for Limit Sniper strategy accuracy.

    Features:
    - Persistent WebSocket connection
    - Dual market mode (SPOT/FUTURES)
    - Automatic reconnection with exponential backoff
    - Message parsing and validation
    - Connection health monitoring
    """

    # URL constants for reference
    SPOT_WS_URL = "wss://stream.binance.com:9443"
    FUTURES_WS_URL = "wss://fstream.binance.com"

    def __init__(
        self,
        market_mode: Optional[MarketMode] = None,
        initial_reconnect_delay: float = 1.0,
        max_reconnect_delay: float = 60.0
    ):
        """
        Initialize WebSocket client.

        Args:
            market_mode: SPOT or FUTURES (default: from env or FUTURES)
            initial_reconnect_delay: Initial delay for reconnection (seconds)
            max_reconnect_delay: Maximum delay for reconnection (seconds)
        """
        self._market_mode = market_mode or get_default_market_mode()
        self._config = get_market_config(self._market_mode)
        self.base_url = f"{self._config.ws_base_url}"
        self.stream_base_url = self._config.ws_stream_url
        self.initial_reconnect_delay = initial_reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay

        # Connection state
        self._websocket: Optional[WebSocketClientProtocol] = None
        self._state = ConnectionState.DISCONNECTED
        self._reconnect_count = 0
        self._current_reconnect_delay = initial_reconnect_delay
        self._last_update = datetime.now()
        self._latency_ms = 0
        self._error_message: Optional[str] = None

        # Callbacks
        self._message_callbacks: list[Callable] = []
        self._candle_callbacks: list[Callable] = []
        self._connection_callbacks: list[Callable] = []

        # Control flags
        self._should_run = False
        self._receive_task: Optional[asyncio.Task] = None

        # Message parser
        self._parser = BinanceMessageParser()

        # Connection parameters (for reconnection)
        self._symbol: Optional[str] = None
        self._interval: Optional[str] = None
        self._intervals: list[str] = []  # SOTA: Multi-timeframe support
        self._symbols: list[str] = []     # SOTA: Multi-symbol support

        # SOTA (Jan 2026): Subscription verification & health check
        self._pending_subscribe_ids: set[int] = set()  # Track pending SUBSCRIBE requests
        self._subscribe_responses: dict[int, dict] = {}  # Store responses by ID
        self._symbols_received: set[str] = set()  # Track symbols that received data
        self._subscribe_verified = False  # Flag for subscription verification status

        # FIX P0 (Feb 13, 2026): Track ACTUALLY subscribed symbols on WebSocket
        # _symbols is the "intended" list (shared with SharedBinanceClient via reference).
        # register_handler() adds to _symbols BEFORE actual subscription, causing
        # subscribe_symbol() to short-circuit and never send SUBSCRIBE payload.
        # _confirmed_subscriptions tracks what's REALLY subscribed.
        self._confirmed_subscriptions: set = set()

        # Logging
        self.logger = logging.getLogger(__name__)

    async def connect(
        self,
        symbol: str = "btcusdt",
        interval: str = "1m",
        intervals: Optional[list[str]] = None,  # SOTA: Multi-timeframe support
        symbols: Optional[list[str]] = None,     # SOTA: Multi-symbol support
        start_loop: bool = True
    ) -> None:
        """
        Connect to Binance WebSocket stream.

        SOTA: Supports multi-symbol + multi-timeframe via Combined Streams.

        Args:
            symbol: Trading pair symbol (legacy single symbol, e.g., 'btcusdt')
            interval: Kline interval for single stream (legacy, e.g., '1m')
            intervals: List of intervals for combined streams (e.g., ['1m', '15m', '1h'])
            symbols: List of symbols for multi-symbol combined streams (e.g., ['btcusdt', 'ethusdt'])
            start_loop: Whether to start the receive loop task (default: True)

        Raises:
            Exception: If connection fails

        Example:
            # Multi-symbol + multi-timeframe (SOTA)
            await client.connect(
                symbols=['btcusdt', 'ethusdt', 'solusdt'],
                intervals=['1m', '15m', '1h']
            )
        """
        if self._state == ConnectionState.CONNECTED:
            self.logger.warning("Already connected to WebSocket")
            return

        self._should_run = True
        # Only update state if not reconnecting (to preserve RECONNECTING status if applicable)
        if self._state != ConnectionState.RECONNECTING:
            self._state = ConnectionState.CONNECTING

        # Store connection parameters for reconnection
        self._symbol = symbol
        self._interval = interval
        self._intervals = intervals or [interval]  # Default to single interval
        self._symbols = symbols or [symbol]         # SOTA: Default to single symbol

        # SOTA: Build WebSocket URL for combined streams (multi-symbol + multi-timeframe)
        streams = []
        for sym in self._symbols:
            for intv in self._intervals:
                streams.append(f"{sym.lower()}@kline_{intv}")

        if len(streams) > 50:
            # SOTA (Jan 2026): For large number of streams, use STREAM URL + SUBSCRIBE request
            # This avoids "URI Too Long" errors (Binance limit ~2000 chars)
            # We will send subscription frames AFTER connection
            # CRITICAL FIX: Use stream_base_url, NOT base_url + "/stream"!
            url = self.stream_base_url  # wss://fstream.binance.com/stream
            self.logger.info(f"🚀 SOTA: Large Scale Mode ({len(streams)} streams) - Using SUBSCRIBE payload")
        else:
            # SOTA FIX (Feb 2026): ALWAYS use Combined Stream URL (even for single symbol)
            # This ensures consistent message format {"stream":..., "data":...}
            # which is required for correct routing of dynamically subscribed symbols.
            stream_query = "/".join(streams)
            url = f"{self.stream_base_url}?streams={stream_query}"
            mode_str = "Single-Stream" if len(streams) == 1 else "Multi-Stream"
            self.logger.info(f"🚀 SOTA: {self._market_mode.value.upper()} {mode_str} (Combined Mode): {len(streams)} streams")

        self.logger.info(f"Connecting to Binance WebSocket: {url[:100]}...")

        try:
            self._websocket = await websockets.connect(
                url,
                ping_interval=20,
                ping_timeout=10
            )

            self._state = ConnectionState.CONNECTED
            self._last_update = datetime.now()
            self._error_message = None

            self.logger.info(f"✅ WebSocket connected successfully ({len(streams)} streams)")

            # SOTA (Jan 2026): Send SUBSCRIBE payload with verification
            if len(streams) > 50:
                # Reset tracking state
                self._pending_subscribe_ids.clear()
                self._subscribe_responses.clear()
                self._symbols_received.clear()

                # Split into chunks of 50 to match Binance payload limits
                chunk_size = 50
                total_chunks = (len(streams) + chunk_size - 1) // chunk_size

                for i in range(0, len(streams), chunk_size):
                    chunk = streams[i:i + chunk_size]
                    request_id = i // chunk_size + 1
                    payload = {
                        "method": "SUBSCRIBE",
                        "params": chunk,
                        "id": request_id
                    }
                    self._pending_subscribe_ids.add(request_id)
                    await self._websocket.send(json.dumps(payload))
                    self.logger.info(f"📤 SUBSCRIBE [{request_id}/{total_chunks}]: {len(chunk)} streams (first: {chunk[0]})")
                    await asyncio.sleep(0.2)  # SOTA: Slightly longer delay for rate limit safety

                # Log subscription summary
                self.logger.info(f"✅ Sent {total_chunks} SUBSCRIBE requests for {len(streams)} total streams")
                self.logger.info(f"📊 Symbols registered: {len(self._symbols)}, Intervals: {self._intervals}")

                # FIX P0 (Feb 13, 2026): Mark all symbols as confirmed subscribed
                self._confirmed_subscriptions = set(self._symbols)
            else:
                # URL-based mode: streams subscribed via URL, mark as confirmed
                self._confirmed_subscriptions = set(self._symbols)

            # Notify connection callbacks
            await self._notify_connection_status()

            # Start receiving messages ONLY if requested and not already running
            if start_loop:
                if self._receive_task is None or self._receive_task.done():
                    self._receive_task = asyncio.create_task(self._receive_messages())
                else:
                    self.logger.warning("Receive task already running")

        except Exception as e:
            self._state = ConnectionState.ERROR
            self._error_message = str(e)
            self.logger.error(f"❌ WebSocket connection failed: {e}")
            raise


    async def disconnect(self) -> None:
        """
        Disconnect from WebSocket stream.
        """
        self.logger.info("Disconnecting from WebSocket...")

        self._should_run = False

        # Cancel receive task
        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass

        # Close WebSocket connection
        if self._websocket:
            await self._websocket.close()
            self._websocket = None

        self._state = ConnectionState.DISCONNECTED
        self.logger.info("✅ WebSocket disconnected")

    async def _receive_messages(self) -> None:
        """
        Receive and process messages from WebSocket.

        Handles reconnection on connection loss.
        """
        while self._should_run:
            try:
                if not self._websocket:
                    self.logger.warning("WebSocket not connected, attempting reconnection...")
                    await self._reconnect()
                    continue

                # Receive message
                message = await self._websocket.recv()
                # print(f"DEBUG: Received message: {message[:50]}...") # Uncomment for extreme debug

                # Update last update time
                self._last_update = datetime.now()

                # Parse and process message
                await self._process_message(message)

            except websockets.exceptions.ConnectionClosed as e:
                self.logger.warning(f"WebSocket connection closed: {e}")
                self._state = ConnectionState.DISCONNECTED

                if self._should_run:
                    await self._reconnect()
                else:
                    break

            except asyncio.CancelledError:
                self.logger.info("Receive task cancelled")
                break

            except Exception as e:
                self.logger.error(f"Error receiving message: {e}")
                await asyncio.sleep(1)

    async def _reconnect(self) -> None:
        """
        Reconnect to WebSocket with exponential backoff.
        """
        self._state = ConnectionState.RECONNECTING
        self._reconnect_count += 1

        self.logger.info(
            f"Reconnecting... (attempt {self._reconnect_count}, "
            f"delay: {self._current_reconnect_delay:.1f}s)"
        )

        # Wait before reconnecting
        await asyncio.sleep(self._current_reconnect_delay)

        # Increase delay for next attempt (exponential backoff)
        self._current_reconnect_delay = min(
            self._current_reconnect_delay * 2,
            self.max_reconnect_delay
        )

        try:
            # Attempt to reconnect using stored parameters
            if self._symbols and self._intervals:
                # SOTA: Reconnect with same symbols and intervals
                await self.connect(
                    symbols=self._symbols,
                    intervals=self._intervals,
                    start_loop=False
                )

                # Reset delay on successful connection
                self._current_reconnect_delay = self.initial_reconnect_delay
            elif self._symbol and (self._interval or self._intervals):
                # Legacy single-symbol reconnect
                await self.connect(
                    self._symbol,
                    self._interval,
                    intervals=self._intervals if len(self._intervals) > 1 else None,
                    start_loop=False
                )

                # Reset delay on successful connection
                self._current_reconnect_delay = self.initial_reconnect_delay
            else:
                self.logger.error("Cannot reconnect: missing symbol/interval")
                self._state = ConnectionState.ERROR

        except Exception as e:
            self.logger.error(f"Reconnection failed: {e}")
            self._state = ConnectionState.ERROR
            self._error_message = str(e)


    async def _process_message(self, message: str) -> None:
        """
        Parse and process incoming WebSocket message.

        SOTA: Handles both single stream and combined stream formats.
        Combined stream format: {"stream": "btcusdt@kline_15m", "data": {...}}

        Args:
            message: Raw JSON message from WebSocket
        """
        try:
            raw_data = json.loads(message)

            # SOTA (Jan 2026): Handle SUBSCRIBE responses
            if "id" in raw_data and ("result" in raw_data or "error" in raw_data):
                request_id = raw_data.get("id")
                if raw_data.get("result") is None and "error" not in raw_data:
                    # Success: {"result": null, "id": X}
                    self._subscribe_responses[request_id] = {"success": True}
                    if request_id in self._pending_subscribe_ids:
                        self._pending_subscribe_ids.remove(request_id)
                        self.logger.info(f"✅ SUBSCRIBE ACK [{request_id}] - Success")
                        if not self._pending_subscribe_ids:
                            self._subscribe_verified = True
                            self.logger.info(f"🎉 All {len(self._subscribe_responses)} SUBSCRIBE requests verified!")
                elif "error" in raw_data:
                    # Error: {"error": {"code": X, "msg": "..."}, "id": X}
                    error = raw_data["error"]
                    self._subscribe_responses[request_id] = {"success": False, "error": error}
                    self.logger.error(f"❌ SUBSCRIBE FAILED [{request_id}]: {error}")
                return  # Don't process as candle data

            # SOTA: Handle combined stream wrapper for multi-symbol + multi-timeframe
            if "stream" in raw_data and "data" in raw_data:
                # Combined stream format
                stream_name = raw_data["stream"]  # e.g., "btcusdt@kline_15m"
                data = raw_data["data"]
                # Extract symbol and interval from stream name: "btcusdt@kline_15m"
                parts = stream_name.split("@kline_")
                symbol = parts[0] if parts else self._symbol
                interval = parts[1] if len(parts) > 1 else "1m"

                # SOTA (Jan 2026): Log first message per symbol for health monitoring
                if symbol and symbol not in self._symbols_received:
                    self._symbols_received.add(symbol)
                    self.logger.info(f"🟢 First data received for: {symbol.upper()} (total: {len(self._symbols_received)}/{len(self._symbols)})")
            else:
                # Single stream format (legacy)
                data = raw_data
                symbol = self._symbol or "unknown"
                interval = self._interval or "1m"

            # Calculate latency
            if 'E' in data:  # Event time
                # SOTA FIX: Use timezone-aware datetime for correct conversion
                event_time = datetime.fromtimestamp(data['E'] / 1000, tz=timezone.utc)
                latency = (datetime.now(tz=timezone.utc) - event_time).total_seconds() * 1000
                self._latency_ms = int(latency)

            # Parse message to Candle entity
            candle = self._parser.parse_kline_message(data)
            metadata = self._parser.extract_metadata(data)

            # SOTA: Add symbol AND interval to metadata for multi-symbol/timeframe routing
            metadata['interval'] = interval
            metadata['symbol'] = symbol

            # Notify raw message callbacks
            for callback in self._message_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(data)
                    else:
                        callback(data)
                except Exception as e:
                    self.logger.error(f"Error in message callback: {e}")

            # Notify candle callbacks if parsing successful
            if candle:
                # SOTA: Log with interval info
                self.logger.debug(f"📊 [{interval}] Candle: {candle.close:.2f} - notifying {len(self._candle_callbacks)} callbacks")
                for callback in self._candle_callbacks:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(candle, metadata)
                        else:
                            callback(candle, metadata)
                    except Exception as e:
                        self.logger.error(f"Error in candle callback: {e}", exc_info=True)

        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse message: {e}")
        except Exception as e:
            self.logger.error(f"Error processing message: {e}")

    async def _notify_connection_status(self) -> None:
        """Notify all connection status callbacks"""
        status = self.get_connection_status()

        for callback in self._connection_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(status)
                else:
                    callback(status)
            except Exception as e:
                self.logger.error(f"Error in connection callback: {e}")

    def subscribe_kline(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """
        Subscribe to raw kline messages.

        Args:
            callback: Function to call when new kline message arrives
                     Signature: callback(data: Dict[str, Any]) -> None
        """
        self._message_callbacks.append(callback)
        self.logger.debug(f"Added kline callback (total: {len(self._message_callbacks)})")

    def subscribe_candle(self, callback: Callable[[Candle, Dict[str, Any]], None]) -> None:
        """
        Subscribe to parsed Candle entities.

        Args:
            callback: Function to call when new candle is parsed
                     Signature: callback(candle: Candle, metadata: Dict) -> None
        """
        self._candle_callbacks.append(callback)
        self.logger.debug(f"Added candle callback (total: {len(self._candle_callbacks)})")

    def subscribe_connection_status(self, callback: Callable[[ConnectionStatus], None]) -> None:
        """
        Subscribe to connection status changes.

        Args:
            callback: Function to call when connection status changes
                     Signature: callback(status: ConnectionStatus) -> None
        """
        self._connection_callbacks.append(callback)
        self.logger.debug(f"Added connection callback (total: {len(self._connection_callbacks)})")

    def is_connected(self) -> bool:
        """
        Check if WebSocket is currently connected.

        Returns:
            True if connected, False otherwise
        """
        return self._state == ConnectionState.CONNECTED and self._websocket is not None

    def get_connection_status(self) -> ConnectionStatus:
        """
        Get current connection status.

        Returns:
            ConnectionStatus object with current state
        """
        return ConnectionStatus(
            is_connected=self.is_connected(),
            state=self._state,
            last_update=self._last_update,
            latency_ms=self._latency_ms,
            reconnect_count=self._reconnect_count,
            error_message=self._error_message
        )

    def get_subscription_health(self) -> dict:
        """
        SOTA (Jan 2026): Get subscription health status.

        Returns dict with:
        - symbols_expected: Total symbols in subscription
        - symbols_received: Symbols that have received at least one message
        - symbols_missing: Symbols with no data yet
        - subscribe_verified: Whether all SUBSCRIBE requests were acknowledged
        - coverage_pct: Percentage of symbols receiving data
        """
        expected = set(self._symbols)
        received = self._symbols_received
        missing = expected - received
        coverage = (len(received) / len(expected) * 100) if expected else 0

        return {
            "symbols_expected": len(expected),
            "symbols_received": len(received),
            "symbols_missing": list(missing)[:10],  # Limit output size
            "symbols_missing_count": len(missing),
            "subscribe_verified": self._subscribe_verified,
            "pending_subscribe_ids": list(self._pending_subscribe_ids),
            "coverage_pct": round(coverage, 1)
        }

    async def subscribe_symbol(self, symbol: str) -> bool:
        """
        SOTA (Jan 2026): Dynamically subscribe to a new symbol on existing connection.

        Binance supports sending SUBSCRIBE on active WebSocket:
        {"method": "SUBSCRIBE", "params": ["btcusdt@kline_1m"], "id": 123}

        Used when new position opened for symbol not in initial subscription list.
        This ensures PositionMonitor receives price ticks for TP/SL monitoring.

        Args:
            symbol: Symbol to subscribe (e.g., 'vvvusdt')

        Returns:
            True if subscription sent successfully
        """
        if not self._websocket or self._state != ConnectionState.CONNECTED:
            self.logger.warning(f"Cannot subscribe {symbol}: WS not connected")
            return False

        symbol_lower = symbol.lower()
        # FIX P0 (Feb 13, 2026): Check _confirmed_subscriptions, NOT _symbols
        # _symbols is shared with SharedBinanceClient and gets populated by
        # register_handler() BEFORE actual WebSocket subscription. This caused
        # subscribe_symbol() to short-circuit → restored positions got NO ticks.
        if symbol_lower in self._confirmed_subscriptions:
            self.logger.debug(f"Symbol {symbol_lower} already subscribed (confirmed)")
            return True  # Actually subscribed on WebSocket

        # Build stream names for all configured intervals
        streams = [f"{symbol_lower}@kline_{intv}" for intv in self._intervals]

        # Generate unique request ID
        request_id = int(datetime.now(timezone.utc).timestamp() * 1000) % 1000000
        payload = {
            "method": "SUBSCRIBE",
            "params": streams,
            "id": request_id
        }

        try:
            await self._websocket.send(json.dumps(payload))
            if symbol_lower not in self._symbols:
                self._symbols.append(symbol_lower)
            self._confirmed_subscriptions.add(symbol_lower)  # FIX P0: Track actual subscription
            self._pending_subscribe_ids.add(request_id)
            self.logger.info(f"📡 Dynamic SUBSCRIBE: {symbol_lower} ({len(streams)} streams)")
            return True
        except Exception as e:
            self.logger.error(f"Failed to subscribe {symbol_lower}: {e}")
            return False

    def __repr__(self) -> str:
        """String representation"""
        return (
            f"BinanceWebSocketClient("
            f"state={self._state.value}, "
            f"reconnects={self._reconnect_count}, "
            f"latency={self._latency_ms}ms"
            f")"
        )
