"""
Bollinger Bands Calculator

Replaces ATR for volatility measurement and dynamic support/resistance.
"""

from typing import List, Optional
from dataclasses import dataclass
import pandas as pd
import numpy as np

from ...domain.entities.candle import Candle


@dataclass
class BollingerResult:
    """Bollinger Bands calculation result"""
    upper_band: float
    middle_band: float  # SMA
    lower_band: float
    bandwidth: float  # (upper - lower) / middle
    percent_b: float  # Where price is within bands (0-1 scale)


class BollingerCalculator:
    """
    Calculate Bollinger Bands.

    Formula:
        Middle Band = SMA(period)
        Upper Band = SMA + (std_dev * multiplier)
        Lower Band = SMA - (std_dev * multiplier)

    Usage:
        - Price touching lower band in uptrend = buy opportunity
        - Price touching upper band in downtrend = sell opportunity
        - Bandwidth shows volatility (expanding = high volatility)
    """

    def __init__(self, period: int = 20, std_multiplier: float = 2.0):
        """
        Initialize Bollinger Bands calculator.

        Args:
            period: SMA period (default: 20)
            std_multiplier: Standard deviation multiplier (default: 2.0)
        """
        self.period = period
        self.std_multiplier = std_multiplier

    def calculate_bands(
        self,
        candles: List[Candle],
        current_price: Optional[float] = None
    ) -> Optional[BollingerResult]:
        """
        Calculate Bollinger Bands for given candles.

        Args:
            candles: List of Candle objects (chronological order)
            current_price: Current price for %B calculation (defaults to last close)

        Returns:
            BollingerResult or None if insufficient data
        """
        if not candles or len(candles) < self.period:
            return None

        # Extract only the required window (O(1) calculation)
        calc_candles = candles[-self.period:]
        closes = [c.close for c in calc_candles]

        # Calculate SMA directly
        middle_band = sum(closes) / self.period

        # Calculate standard deviation (Pandas rolling uses sample std dev ddof=1)
        variance = sum((x - middle_band) ** 2 for x in closes) / (self.period - 1) if self.period > 1 else 0
        std = variance ** 0.5

        # Calculate bands
        upper_band = middle_band + (std * self.std_multiplier)
        lower_band = middle_band - (std * self.std_multiplier)

        # Calculate bandwidth
        bandwidth = (upper_band - lower_band) / middle_band if middle_band != 0 else 0

        # Calculate %B (where price is within bands)
        price = current_price if current_price is not None else candles[-1].close

        if upper_band != lower_band:
            percent_b = (price - lower_band) / (upper_band - lower_band)
        else:
            percent_b = 0.5  # Middle if bands collapsed

        return BollingerResult(
            upper_band=upper_band,
            middle_band=middle_band,
            lower_band=lower_band,
            bandwidth=bandwidth,
            percent_b=percent_b
        )

    def is_near_lower_band(
        self,
        price: float,
        lower_band: float,
        threshold_pct: float = 0.01
    ) -> bool:
        """
        Check if price is near lower Bollinger Band.

        Args:
            price: Current price
            lower_band: Lower band value
            threshold_pct: Distance threshold (e.g., 0.01 = within 1%)

        Returns:
            True if price is near or touching lower band
        """
        distance = abs(price - lower_band) / lower_band
        return distance <= threshold_pct or price <= lower_band

    def is_near_upper_band(
        self,
        price: float,
        upper_band: float,
        threshold_pct: float = 0.01
    ) -> bool:
        """
        Check if price is near upper Bollinger Band.

        Args:
            price: Current price
            upper_band: Upper band value
            threshold_pct: Distance threshold (e.g., 0.01 = within 1%)

        Returns:
            True if price is near or touching upper band
        """
        distance = abs(price - upper_band) / upper_band
        return distance <= threshold_pct or price >= upper_band

    def is_squeezing(self, bandwidth: float, threshold: float = 0.05) -> bool:
        """
        Check if Bollinger Bands are squeezing (low volatility).

        Args:
            bandwidth: Current bandwidth value
            threshold: Squeeze threshold (e.g., 0.05 = 5%)

        Returns:
            True if bandwidth is below threshold
        """
        return bandwidth < threshold

    def is_expanding(
        self,
        current_bandwidth: float,
        previous_bandwidth: float
    ) -> bool:
        """
        Check if Bollinger Bands are expanding (increasing volatility).

        Args:
            current_bandwidth: Current bandwidth
            previous_bandwidth: Previous bandwidth

        Returns:
            True if bands are expanding
        """
        return current_bandwidth > previous_bandwidth

    def calculate_bands_series(
        self,
        candles: List[Candle]
    ) -> Optional['BollingerSeriesResult']:
        """
        Calculate Bollinger Bands for all candles (returns arrays).

        Args:
            candles: List of Candle objects (chronological order)

        Returns:
            BollingerSeriesResult with arrays for each band, or None if insufficient data
        """
        if not candles or len(candles) < self.period:
            return None

        # Extract close prices
        closes = [c.close for c in candles]

        # Use pandas for rolling calculations
        series = pd.Series(closes)

        # Calculate SMA (middle band)
        sma = series.rolling(window=self.period).mean()

        # Calculate standard deviation
        std = series.rolling(window=self.period).std()

        # Calculate bands
        upper = sma + (std * self.std_multiplier)
        lower = sma - (std * self.std_multiplier)

        # SOTA: Use forward fill for mid-series gaps, then 0 for warm-up period
        # Frontend trims first 50 candles (WARMUP_PERIOD) so warm-up zeros are not displayed
        # This ensures indicators appear correctly after warm-up, not as flat lines at start
        upper = upper.ffill().fillna(0.0).tolist()
        lower = lower.ffill().fillna(0.0).tolist()
        middle = sma.ffill().fillna(0.0).tolist()

        return BollingerSeriesResult(
            upper_band=upper,
            middle_band=middle,
            lower_band=lower
        )


@dataclass
class BollingerSeriesResult:
    """Bollinger Bands series result (arrays for all candles)"""
    upper_band: List[float]
    middle_band: List[float]
    lower_band: List[float]
