"""
MarketData Aggregate - Domain Model

Combines Candle and Indicator entities into a single aggregate root.
This represents complete market data with technical indicators.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .candle import Candle
from .indicator import Indicator


@dataclass(frozen=True)
class MarketData:
    """
    Aggregate root combining candle data with technical indicators.

    This is the main entity that represents a complete market data point
    including both price action (candle) and technical analysis (indicators).

    Attributes:
        candle: The candlestick data (OHLCV)
        indicator: The technical indicators (EMA, RSI, Volume MA)
        timeframe: The timeframe of the data ('15m', '1h', etc.)

    Example:
        >>> candle = Candle(...)
        >>> indicator = Indicator(...)
        >>> market_data = MarketData(
        ...     candle=candle,
        ...     indicator=indicator,
        ...     timeframe='15m'
        ... )
    """

    candle: Candle
    indicator: Indicator
    timeframe: str

    def __post_init__(self):
        """
        Validate market data after initialization.

        Validation rules:
        - Candle must be valid Candle entity
        - Indicator must be valid Indicator entity
        - Timeframe must be valid string

        Raises:
            ValueError: If any validation rule fails
        """
        # Validate candle
        if not isinstance(self.candle, Candle):
            raise ValueError(
                f"Candle must be Candle entity, got {type(self.candle)}"
            )

        # Validate indicator
        if not isinstance(self.indicator, Indicator):
            raise ValueError(
                f"Indicator must be Indicator entity, got {type(self.indicator)}"
            )

        # Validate timeframe
        valid_timeframes = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '12h', '1d', '1w']
        if self.timeframe not in valid_timeframes:
            raise ValueError(
                f"Timeframe must be one of {valid_timeframes}, got {self.timeframe}"
            )

    @property
    def timestamp(self) -> datetime:
        """Get the timestamp from the candle"""
        return self.candle.timestamp

    # =========================================================================
    # SOTA Property Delegation (Dec 2025)
    #
    # Following institutional trading patterns, aggregate roots should expose
    # commonly-accessed child properties via delegation for API consistency.
    # This prevents bugs like `candles[0].close` (should be .candle.close)
    # =========================================================================

    @property
    def open(self) -> float:
        """Delegate to candle.open for API consistency"""
        return self.candle.open

    @property
    def high(self) -> float:
        """Delegate to candle.high for API consistency"""
        return self.candle.high

    @property
    def low(self) -> float:
        """Delegate to candle.low for API consistency"""
        return self.candle.low

    @property
    def close(self) -> float:
        """Delegate to candle.close for API consistency"""
        return self.candle.close

    @property
    def close_price(self) -> float:
        """Get the closing price from the candle (alias for .close)"""
        return self.candle.close

    @property
    def volume(self) -> float:
        """Get the volume from the candle"""
        return self.candle.volume

    @property
    def is_complete(self) -> bool:
        """Check if all indicators have been calculated"""
        return self.indicator.is_complete()

    @property
    def data_quality_score(self) -> float:
        """
        Calculate data quality score (0-100).

        Based on:
        - Candle validity (always 100 if valid)
        - Indicator completeness (0-100%)

        Returns:
            Quality score from 0 to 100
        """
        # Candle is always valid if we got here (validation in __post_init__)
        candle_score = 100.0

        # Indicator completeness
        indicator_score = self.indicator.get_completion_percentage()

        # Average of both
        return (candle_score + indicator_score) / 2

    def validate(self) -> tuple[bool, list[str]]:
        """
        Comprehensive validation of market data.

        Returns:
            Tuple of (is_valid, list_of_issues)
        """
        issues = []

        # Check candle validity (already validated in __post_init__)
        # But we can add business logic checks here

        # Check if price is reasonable (not zero, not negative)
        if self.candle.close <= 0:
            issues.append(f"Invalid close price: {self.candle.close}")

        # Check if volume is reasonable
        if self.candle.volume < 0:
            issues.append(f"Invalid volume: {self.candle.volume}")

        # Check RSI validity
        if not self.indicator.validate_rsi():
            issues.append(f"Invalid RSI: {self.indicator.rsi_6}")

        # Check for missing indicators (warning, not error)
        missing = self.indicator.get_missing_indicators()
        if missing:
            issues.append(f"Missing indicators: {', '.join(missing)}")

        is_valid = len([i for i in issues if not i.startswith("Missing")]) == 0
        return is_valid, issues

    def get_trading_signal(self) -> dict:
        """
        Get trading signals based on indicators.

        Returns:
            Dictionary with signal information
        """
        signal = {
            'timestamp': self.timestamp,
            'price': self.close_price,
            'rsi_signal': self.indicator.rsi_signal,
            'trend': None,
            'recommendation': 'HOLD'
        }

        # Determine trend based on EMA
        if self.indicator.ema_7 is not None:
            if self.close_price > self.indicator.ema_7:
                signal['trend'] = 'UPTREND'
            elif self.close_price < self.indicator.ema_7:
                signal['trend'] = 'DOWNTREND'
            else:
                signal['trend'] = 'NEUTRAL'

        # Simple recommendation logic
        if self.indicator.is_oversold and signal['trend'] == 'UPTREND':
            signal['recommendation'] = 'BUY'
        elif self.indicator.is_overbought and signal['trend'] == 'DOWNTREND':
            signal['recommendation'] = 'SELL'

        return signal

    def to_dict(self) -> dict:
        """
        Convert market data to dictionary.

        Returns:
            Dictionary representation of market data
        """
        return {
            'timestamp': self.timestamp.isoformat(),
            'timeframe': self.timeframe,
            'open': self.candle.open,
            'high': self.candle.high,
            'low': self.candle.low,
            'close': self.candle.close,
            'volume': self.candle.volume,
            'ema_7': self.indicator.ema_7,
            'rsi_6': self.indicator.rsi_6,
            'volume_ma_20': self.indicator.volume_ma_20,
            'is_complete': self.is_complete,
            'quality_score': self.data_quality_score
        }

    def __str__(self) -> str:
        """String representation of market data"""
        is_valid, issues = self.validate()
        status = "✓" if is_valid else "✗"
        return (
            f"MarketData({status} {self.timeframe}, "
            f"{self.timestamp.strftime('%Y-%m-%d %H:%M')}, "
            f"Close:{self.close_price:.2f}, "
            f"Quality:{self.data_quality_score:.0f}%, "
            f"Signal:{self.indicator.rsi_signal})"
        )

    def __repr__(self) -> str:
        """Developer-friendly representation"""
        return (
            f"MarketData(candle={self.candle!r}, "
            f"indicator={self.indicator!r}, "
            f"timeframe={self.timeframe!r})"
        )
