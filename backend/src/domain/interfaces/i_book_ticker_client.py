"""
IBookTickerClient - Domain Interface

Abstract interface for book ticker (best bid/ask) data provider.
Used by HardFilters to get real-time spread data.

Binance bookTicker stream provides:
- Best bid price and quantity
- Best ask price and quantity
- Updated in real-time (faster than kline)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple


@dataclass
class BookTickerData:
    """
    Best bid/ask data from exchange.

    Attributes:
        symbol: Trading pair (e.g., 'btcusdt')
        bid_price: Best bid price
        bid_qty: Best bid quantity
        ask_price: Best ask price
        ask_qty: Best ask quantity
        timestamp: When data was received
    """
    symbol: str
    bid_price: float
    bid_qty: float
    ask_price: float
    ask_qty: float
    timestamp: datetime

    @property
    def spread(self) -> float:
        """Calculate spread as percentage: (ask - bid) / bid"""
        if self.bid_price <= 0:
            return float('inf')
        return (self.ask_price - self.bid_price) / self.bid_price

    @property
    def spread_bps(self) -> float:
        """Spread in basis points (1 bp = 0.01%)"""
        return self.spread * 10000

    def __repr__(self) -> str:
        return (
            f"BookTickerData({self.symbol}, "
            f"bid={self.bid_price:.2f}, ask={self.ask_price:.2f}, "
            f"spread={self.spread_bps:.2f}bps)"
        )


class IBookTickerClient(ABC):
    """
    Interface for book ticker data provider.

    Implementations should:
    1. Subscribe to exchange's bookTicker WebSocket stream
    2. Parse incoming messages and update bid/ask
    3. Track timestamp for freshness checking

    Usage:
        client = BinanceBookTickerClient()
        await client.subscribe("btcusdt")

        # Later, when checking spread
        if client.is_data_fresh():
            bid, ask = client.get_best_bid_ask()
            spread = (ask - bid) / bid
    """

    @abstractmethod
    async def subscribe(self, symbol: str) -> None:
        """
        Subscribe to bookTicker stream for a symbol.

        Args:
            symbol: Trading pair (e.g., 'btcusdt')
        """
        pass

    @abstractmethod
    async def unsubscribe(self, symbol: str) -> None:
        """
        Unsubscribe from bookTicker stream.

        Args:
            symbol: Trading pair to unsubscribe
        """
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    def get_book_ticker_data(self, symbol: str = "btcusdt") -> Optional[BookTickerData]:
        """
        Get full book ticker data including quantities.

        Args:
            symbol: Trading pair

        Returns:
            BookTickerData or None if not available
        """
        pass

    @abstractmethod
    def is_data_fresh(self, symbol: str = "btcusdt", max_age_seconds: float = 5.0) -> bool:
        """
        Check if data is fresh (not stale).

        Args:
            symbol: Trading pair
            max_age_seconds: Maximum age in seconds (default: 5.0)

        Returns:
            True if data is fresh, False if stale or unavailable
        """
        pass

    @abstractmethod
    def get_last_update_time(self, symbol: str = "btcusdt") -> Optional[datetime]:
        """
        Get timestamp of last data update.

        Args:
            symbol: Trading pair

        Returns:
            Datetime of last update or None
        """
        pass
