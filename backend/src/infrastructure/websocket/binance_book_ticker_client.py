"""
BinanceBookTickerClient - Infrastructure Layer

WebSocket client for Binance bookTicker stream.
Provides real-time best bid/ask prices for spread calculation.

Binance bookTicker stream format:
{
    "u": 400900217,     // order book updateId
    "s": "BTCUSDT",     // symbol
    "b": "25.35190000", // best bid price
    "B": "31.21000000", // best bid qty
    "a": "25.36520000", // best ask price
    "A": "40.66000000"  // best ask qty
}

Stream URL: wss://stream.binance.com:9443/ws/<symbol>@bookTicker
"""

import asyncio
import json
import logging
import threading
from datetime import datetime
from typing import Optional, Dict, Tuple, Callable, Any

from ...domain.interfaces import IBookTickerClient, BookTickerData


class BinanceBookTickerClient(IBookTickerClient):
    """
    Binance WebSocket client for bookTicker stream.

    Uses asyncio websockets library for async WebSocket connection.
    Thread-safe access to bid/ask data.

    Usage:
        client = BinanceBookTickerClient()
        await client.subscribe("btcusdt")

        # Check spread
        if client.is_data_fresh():
            bid, ask = client.get_best_bid_ask()
    """

    BASE_URL = "wss://stream.binance.com:9443/ws"

    def __init__(self):
        """Initialize the book ticker client."""
        self._data: Dict[str, BookTickerData] = {}
        self._lock = threading.Lock()
        self._ws: Optional[Any] = None
        self._ws_task: Optional[asyncio.Task] = None
        self._is_connected = False
        self._is_running = False
        self._subscribed_symbols: set = set()

        # Callbacks
        self._on_update_callback: Optional[Callable[[BookTickerData], None]] = None

        self.logger = logging.getLogger(__name__)

    async def subscribe(self, symbol: str) -> None:
        """
        Subscribe to bookTicker stream for a symbol.

        Args:
            symbol: Trading pair (e.g., 'btcusdt')
        """
        symbol = symbol.lower()

        if symbol in self._subscribed_symbols:
            self.logger.debug(f"Already subscribed to {symbol}")
            return

        self._subscribed_symbols.add(symbol)

        # Start WebSocket if not running
        if not self._is_running:
            await self._start_websocket()

        self.logger.info(f"📊 Subscribed to bookTicker: {symbol}")

    async def unsubscribe(self, symbol: str) -> None:
        """
        Unsubscribe from bookTicker stream.

        Args:
            symbol: Trading pair to unsubscribe
        """
        symbol = symbol.lower()
        self._subscribed_symbols.discard(symbol)

        with self._lock:
            self._data.pop(symbol, None)

        # Stop WebSocket if no more subscriptions
        if not self._subscribed_symbols and self._is_running:
            await self._stop_websocket()

        self.logger.info(f"Unsubscribed from bookTicker: {symbol}")

    def get_best_bid_ask(self, symbol: str = "btcusdt") -> Tuple[float, float]:
        """
        Get current best bid and ask prices.

        Args:
            symbol: Trading pair (default: 'btcusdt')

        Returns:
            Tuple of (bid_price, ask_price)

        Raises:
            ValueError: If no data available for symbol
        """
        symbol = symbol.lower()

        with self._lock:
            data = self._data.get(symbol)

        if not data:
            raise ValueError(f"No bookTicker data available for {symbol}")

        return data.bid_price, data.ask_price

    def get_book_ticker_data(self, symbol: str = "btcusdt") -> Optional[BookTickerData]:
        """
        Get full book ticker data including quantities.

        Args:
            symbol: Trading pair

        Returns:
            BookTickerData or None if not available
        """
        symbol = symbol.lower()

        with self._lock:
            return self._data.get(symbol)

    def is_data_fresh(self, symbol: str = "btcusdt", max_age_seconds: float = 5.0) -> bool:
        """
        Check if data is fresh (not stale).

        Args:
            symbol: Trading pair
            max_age_seconds: Maximum age in seconds (default: 5.0)

        Returns:
            True if data is fresh, False if stale or unavailable
        """
        symbol = symbol.lower()

        with self._lock:
            data = self._data.get(symbol)

        if not data:
            return False

        age = (datetime.now() - data.timestamp).total_seconds()
        return age <= max_age_seconds

    def get_last_update_time(self, symbol: str = "btcusdt") -> Optional[datetime]:
        """
        Get timestamp of last data update.

        Args:
            symbol: Trading pair

        Returns:
            Datetime of last update or None
        """
        symbol = symbol.lower()

        with self._lock:
            data = self._data.get(symbol)

        return data.timestamp if data else None

    def set_on_update_callback(self, callback: Callable[[BookTickerData], None]) -> None:
        """Set callback for when data is updated."""
        self._on_update_callback = callback

    async def _start_websocket(self) -> None:
        """Start WebSocket connection."""
        if self._is_running:
            return

        self._is_running = True
        self._ws_task = asyncio.create_task(self._websocket_loop())
        self.logger.info("🔌 Starting bookTicker WebSocket...")

    async def _stop_websocket(self) -> None:
        """Stop WebSocket connection."""
        self._is_running = False

        if self._ws:
            await self._ws.close()
            self._ws = None

        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
            self._ws_task = None

        self._is_connected = False
        self.logger.info("BookTicker WebSocket stopped")

    async def _websocket_loop(self) -> None:
        """Main WebSocket loop with reconnection."""
        import websockets

        while self._is_running:
            try:
                # Build stream URL
                streams = [f"{s}@bookTicker" for s in self._subscribed_symbols]
                if not streams:
                    await asyncio.sleep(1)
                    continue

                if len(streams) == 1:
                    url = f"{self.BASE_URL}/{streams[0]}"
                else:
                    url = f"{self.BASE_URL}/stream?streams={'/'.join(streams)}"

                self.logger.info(f"🔌 Connecting to: {url}")

                async with websockets.connect(url) as ws:
                    self._ws = ws
                    self._is_connected = True
                    self.logger.info("✅ BookTicker WebSocket connected")

                    async for message in ws:
                        await self._handle_message(message)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"BookTicker WebSocket error: {e}")
                self._is_connected = False
                await asyncio.sleep(5)  # Reconnect delay

    async def _handle_message(self, message: str) -> None:
        """
        Handle incoming WebSocket message.

        Args:
            message: Raw message string
        """
        try:
            data = json.loads(message)

            # Handle combined stream format
            if 'stream' in data:
                data = data['data']

            # Parse bookTicker message
            symbol = data.get('s', '').lower()
            if not symbol:
                return

            book_ticker = BookTickerData(
                symbol=symbol,
                bid_price=float(data.get('b', 0)),
                bid_qty=float(data.get('B', 0)),
                ask_price=float(data.get('a', 0)),
                ask_qty=float(data.get('A', 0)),
                timestamp=datetime.now()
            )

            # Update data (thread-safe)
            with self._lock:
                self._data[symbol] = book_ticker

            # Call callback if set
            if self._on_update_callback:
                try:
                    self._on_update_callback(book_ticker)
                except Exception as e:
                    self.logger.error(f"Callback error: {e}")

            self.logger.debug(f"📊 {book_ticker}")

        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse message: {e}")
        except Exception as e:
            self.logger.error(f"Error processing message: {e}")

    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self._is_connected

    def get_status(self) -> dict:
        """Get client status."""
        return {
            'is_connected': self._is_connected,
            'is_running': self._is_running,
            'subscribed_symbols': list(self._subscribed_symbols),
            'data_count': len(self._data),
            'symbols_with_data': list(self._data.keys())
        }

    def __repr__(self) -> str:
        return f"BinanceBookTickerClient(connected={self._is_connected}, symbols={list(self._subscribed_symbols)})"
