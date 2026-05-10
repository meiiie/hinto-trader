"""
Indicator Entity - Domain Model

Represents technical indicators calculated from market data.
This is a pure domain entity with no external dependencies.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Indicator:
    """
    Immutable indicator entity representing technical analysis values.

    Attributes:
        ema_7: Exponential Moving Average with period 7
        rsi_6: Relative Strength Index with period 6 (0-100 range)
        volume_ma_20: Volume Moving Average with period 20

    Note:
        None values are valid and represent indicators that haven't been
        calculated yet (e.g., during warmup period).

    Example:
        >>> indicator = Indicator(
        ...     ema_7=90500.0,
        ...     rsi_6=45.5,
        ...     volume_ma_20=1000.0
        ... )
    """

    ema_7: Optional[float] = None
    rsi_6: Optional[float] = None
    volume_ma_20: Optional[float] = None

    def __post_init__(self):
        """
        Validate indicator values after initialization.

        Validation rules:
        - RSI must be in range [0, 100] if not None
        - EMA must be positive if not None
        - Volume MA must be non-negative if not None

        Raises:
            ValueError: If any validation rule fails
        """
        # Validate RSI range
        if self.rsi_6 is not None:
            if not (0 <= self.rsi_6 <= 100):
                raise ValueError(
                    f"RSI must be in range [0, 100], got {self.rsi_6}"
                )

        # Validate EMA is positive
        if self.ema_7 is not None:
            if self.ema_7 <= 0:
                raise ValueError(
                    f"EMA must be positive, got {self.ema_7}"
                )

        # Validate Volume MA is non-negative
        if self.volume_ma_20 is not None:
            if self.volume_ma_20 < 0:
                raise ValueError(
                    f"Volume MA must be non-negative, got {self.volume_ma_20}"
                )

    def is_complete(self) -> bool:
        """
        Check if all indicators have been calculated.

        Returns:
            True if all indicators have values, False otherwise
        """
        return all([
            self.ema_7 is not None,
            self.rsi_6 is not None,
            self.volume_ma_20 is not None
        ])

    def validate_rsi(self) -> bool:
        """
        Validate RSI is in valid range.

        Returns:
            True if RSI is valid or None, False otherwise
        """
        if self.rsi_6 is None:
            return True  # None is valid (warmup period)
        return 0 <= self.rsi_6 <= 100

    @property
    def is_oversold(self) -> bool:
        """Check if RSI indicates oversold condition (< 30)"""
        if self.rsi_6 is None:
            return False
        return self.rsi_6 < 30

    @property
    def is_overbought(self) -> bool:
        """Check if RSI indicates overbought condition (> 70)"""
        if self.rsi_6 is None:
            return False
        return self.rsi_6 > 70

    @property
    def is_neutral(self) -> bool:
        """Check if RSI is in neutral zone (30-70)"""
        if self.rsi_6 is None:
            return False
        return 30 <= self.rsi_6 <= 70

    @property
    def rsi_signal(self) -> str:
        """
        Get RSI signal as string.

        Returns:
            'OVERSOLD', 'OVERBOUGHT', 'NEUTRAL', or 'N/A'
        """
        if self.rsi_6 is None:
            return 'N/A'
        if self.is_oversold:
            return 'OVERSOLD'
        if self.is_overbought:
            return 'OVERBOUGHT'
        return 'NEUTRAL'

    def get_missing_indicators(self) -> list[str]:
        """
        Get list of indicators that are missing (None).

        Returns:
            List of indicator names that are None
        """
        missing = []
        if self.ema_7 is None:
            missing.append('ema_7')
        if self.rsi_6 is None:
            missing.append('rsi_6')
        if self.volume_ma_20 is None:
            missing.append('volume_ma_20')
        return missing

    def get_completion_percentage(self) -> float:
        """
        Get percentage of indicators that have been calculated.

        Returns:
            Percentage (0-100) of indicators with values
        """
        total = 3
        calculated = sum([
            self.ema_7 is not None,
            self.rsi_6 is not None,
            self.volume_ma_20 is not None
        ])
        return (calculated / total) * 100

    def __str__(self) -> str:
        """String representation of the indicator"""
        ema_str = f"{self.ema_7:.2f}" if self.ema_7 is not None else "N/A"
        rsi_str = f"{self.rsi_6:.2f}" if self.rsi_6 is not None else "N/A"
        vma_str = f"{self.volume_ma_20:.2f}" if self.volume_ma_20 is not None else "N/A"

        return (
            f"Indicator(EMA7:{ema_str}, RSI6:{rsi_str} [{self.rsi_signal}], "
            f"VMA20:{vma_str}, Complete:{self.get_completion_percentage():.0f}%)"
        )

    def __repr__(self) -> str:
        """Developer-friendly representation"""
        return (
            f"Indicator(ema_7={self.ema_7}, rsi_6={self.rsi_6}, "
            f"volume_ma_20={self.volume_ma_20})"
        )
