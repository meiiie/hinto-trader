"""
Candle Entity - Domain Model

Represents a candlestick with OHLCV data.
This is a pure domain entity with no external dependencies.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class Candle:
    """
    Immutable candlestick entity representing market data for a time period.

    Attributes:
        timestamp: Time when the candle opened
        open: Opening price
        high: Highest price during the period
        low: Lowest price during the period
        close: Closing price
        volume: Trading volume during the period

    Raises:
        ValueError: If validation fails

    Example:
        >>> candle = Candle(
        ...     timestamp=datetime(2025, 11, 18, 10, 0),
        ...     open=90000.0,
        ...     high=91000.0,
        ...     low=89500.0,
        ...     close=90500.0,
        ...     volume=100.5
        ... )
    """

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self):
        """
        Validate candle data after initialization.

        Validation rules:
        - High must be >= Low
        - All prices must be positive
        - Volume must be non-negative
        - Timestamp must be valid datetime

        Raises:
            ValueError: If any validation rule fails
        """
        # Validate timestamp
        if not isinstance(self.timestamp, datetime):
            raise ValueError(f"Timestamp must be datetime, got {type(self.timestamp)}")

        # Validate price relationships
        if self.high < self.low:
            raise ValueError(
                f"High price ({self.high}) must be >= Low price ({self.low})"
            )

        # Validate positive prices
        if self.open <= 0:
            raise ValueError(f"Open price must be positive, got {self.open}")

        if self.high <= 0:
            raise ValueError(f"High price must be positive, got {self.high}")

        if self.low <= 0:
            raise ValueError(f"Low price must be positive, got {self.low}")

        if self.close <= 0:
            raise ValueError(f"Close price must be positive, got {self.close}")

        # Validate volume
        if self.volume < 0:
            raise ValueError(f"Volume must be non-negative, got {self.volume}")

    @property
    def is_bullish(self) -> bool:
        """Check if candle is bullish (close > open)"""
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        """Check if candle is bearish (close < open)"""
        return self.close < self.open

    @property
    def is_doji(self) -> bool:
        """Check if candle is doji (close ≈ open)"""
        # Consider doji if close and open differ by less than 0.1%
        body_size = abs(self.close - self.open)
        price_range = self.high - self.low
        if price_range == 0:
            return True
        return (body_size / price_range) < 0.001

    @property
    def body_size(self) -> float:
        """Get the size of the candle body"""
        return abs(self.close - self.open)

    @property
    def upper_shadow(self) -> float:
        """Get the size of the upper shadow (wick)"""
        return self.high - max(self.open, self.close)

    @property
    def lower_shadow(self) -> float:
        """Get the size of the lower shadow (wick)"""
        return min(self.open, self.close) - self.low

    @property
    def price_range(self) -> float:
        """Get the total price range (high - low)"""
        return self.high - self.low

    @property
    def typical_price(self) -> float:
        """Calculate typical price: (high + low + close) / 3"""
        return (self.high + self.low + self.close) / 3

    def __str__(self) -> str:
        """String representation of the candle"""
        direction = "🟢" if self.is_bullish else "🔴" if self.is_bearish else "⚪"
        return (
            f"Candle({direction} {self.timestamp.strftime('%Y-%m-%d %H:%M')}, "
            f"O:{self.open:.2f}, H:{self.high:.2f}, "
            f"L:{self.low:.2f}, C:{self.close:.2f}, V:{self.volume:.2f})"
        )

    def __repr__(self) -> str:
        """Developer-friendly representation"""
        return (
            f"Candle(timestamp={self.timestamp!r}, "
            f"open={self.open}, high={self.high}, "
            f"low={self.low}, close={self.close}, volume={self.volume})"
        )
