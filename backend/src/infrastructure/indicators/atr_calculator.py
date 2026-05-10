"""
ATR Calculator - Infrastructure Layer

Calculate Average True Range (ATR) for volatility measurement using Wilder's smoothing method.
"""

import logging
from typing import List, Optional
from dataclasses import dataclass

from ...domain.entities.candle import Candle


@dataclass
class ATRResult:
    """
    ATR calculation result.

    Attributes:
        atr_value: Calculated ATR value in price units
        period: ATR period used
        timeframe: Timeframe of the candles (e.g., '15m', '1h')
        num_candles: Number of candles used in calculation
    """
    atr_value: float
    period: int
    timeframe: str
    num_candles: int

    def get_stop_distance(self, multiplier: float = 3.0) -> float:
        """
        Get stop loss distance based on ATR.

        Args:
            multiplier: ATR multiplier (default: 3.0 for 15m timeframe)

        Returns:
            Stop loss distance in price units
        """
        return self.atr_value * multiplier

    def get_tp_distance(self, multiplier: float = 2.0) -> float:
        """
        Get take profit distance based on ATR.

        Args:
            multiplier: ATR multiplier (default: 2.0)

        Returns:
            Take profit distance in price units
        """
        return self.atr_value * multiplier


class ATRCalculator:
    """
    Calculate Average True Range (ATR) for volatility measurement.

    ATR measures market volatility by calculating the average of true ranges
    over a specified period. Uses Wilder's smoothing method for calculation.

    True Range (TR) is the maximum of:
    - Current High - Current Low
    - |Current High - Previous Close|
    - |Current Low - Previous Close|

    ATR is then calculated using Wilder's smoothing:
    - Initial ATR = Average of first N true ranges
    - Subsequent ATR = ((Previous ATR × (N-1)) + Current TR) / N

    Usage:
        calculator = ATRCalculator(period=14)
        atr_result = calculator.calculate_atr(candles, timeframe='15m')
        stop_distance = atr_result.get_stop_distance(multiplier=3.0)
    """

    def __init__(self, period: int = 14):
        """
        Initialize ATR calculator.

        Args:
            period: ATR period (default: 14)

        Raises:
            ValueError: If period is less than 1
        """
        if period < 1:
            raise ValueError("ATR period must be at least 1")

        self.period = period
        self.logger = logging.getLogger(__name__)

        self.logger.info(f"ATRCalculator initialized with period={period}")

    def calculate_atr(
        self,
        candles: List[Candle],
        period: Optional[int] = None,
        timeframe: str = '15m'
    ) -> ATRResult:
        """
        Calculate ATR value for given candles.

        Args:
            candles: List of Candle entities (chronological order)
            period: Override default period (optional)
            timeframe: Timeframe identifier (default: '15m')

        Returns:
            ATRResult with calculated ATR value

        Raises:
            ValueError: If insufficient candles provided

        Example:
            >>> calculator = ATRCalculator(period=14)
            >>> candles = load_candles()  # Load historical data
            >>> result = calculator.calculate_atr(candles)
            >>> print(f"ATR: ${result.atr_value:.2f}")
            >>> print(f"Stop distance (3x ATR): ${result.get_stop_distance():.2f}")
        """
        # Use provided period or default
        calc_period = period if period is not None else self.period

        # Validate input
        min_candles = calc_period + 1
        if not candles or len(candles) < min_candles:
            self.logger.warning(
                f"Insufficient candles for ATR calculation: "
                f"need {min_candles}, got {len(candles) if candles else 0}"
            )
            return ATRResult(
                atr_value=0.0,
                period=calc_period,
                timeframe=timeframe,
                num_candles=len(candles) if candles else 0
            )

        # Limit history to stabilize Wilder's smoothing (~10x period)
        history_needed = max(150, calc_period * 10)
        calc_candles = candles[-history_needed:] if len(candles) > history_needed else candles

        # Calculate true ranges
        true_ranges = self._calculate_true_ranges(calc_candles)

        if not true_ranges or len(true_ranges) < calc_period:
            self.logger.warning(
                f"Insufficient true ranges: need {calc_period}, got {len(true_ranges)}"
            )
            return ATRResult(
                atr_value=0.0,
                period=calc_period,
                timeframe=timeframe,
                num_candles=len(calc_candles)
            )

        # Calculate ATR using Wilder's smoothing
        atr_value = self._apply_wilders_smoothing(true_ranges, calc_period)

        self.logger.debug(
            f"ATR calculated: {atr_value:.2f} "
            f"(period={calc_period}, candles={len(candles)})"
        )

        return ATRResult(
            atr_value=atr_value,
            period=calc_period,
            timeframe=timeframe,
            num_candles=len(candles)
        )

    def calculate_true_range(
        self,
        current_candle: Candle,
        previous_candle: Candle
    ) -> float:
        """
        Calculate single true range value.

        True Range is the maximum of:
        1. Current High - Current Low
        2. |Current High - Previous Close|
        3. |Current Low - Previous Close|

        Args:
            current_candle: Current candle
            previous_candle: Previous candle

        Returns:
            True range value

        Example:
            >>> calculator = ATRCalculator()
            >>> current = Candle(high=100, low=95, close=98, ...)
            >>> previous = Candle(close=97, ...)
            >>> tr = calculator.calculate_true_range(current, previous)
            >>> print(f"True Range: {tr}")  # max(5, 3, 2) = 5
        """
        # Method 1: High - Low
        high_low = current_candle.high - current_candle.low

        # Method 2: |High - Previous Close|
        high_prev_close = abs(current_candle.high - previous_candle.close)

        # Method 3: |Low - Previous Close|
        low_prev_close = abs(current_candle.low - previous_candle.close)

        # True Range is the maximum of the three
        true_range = max(high_low, high_prev_close, low_prev_close)

        return true_range

    def _calculate_true_ranges(self, candles: List[Candle]) -> List[float]:
        """
        Calculate true ranges for all candles.

        Args:
            candles: List of candles

        Returns:
            List of true range values
        """
        true_ranges = []

        # Start from index 1 (need previous candle)
        for i in range(1, len(candles)):
            tr = self.calculate_true_range(candles[i], candles[i-1])
            true_ranges.append(tr)

        return true_ranges

    def _apply_wilders_smoothing(
        self,
        true_ranges: List[float],
        period: int
    ) -> float:
        """
        Apply Wilder's smoothing method to calculate ATR.

        Wilder's smoothing formula:
        - Initial ATR = Simple average of first N true ranges
        - Subsequent ATR = ((Previous ATR × (N-1)) + Current TR) / N

        This gives more weight to recent values while maintaining smoothness.

        Args:
            true_ranges: List of true range values
            period: Smoothing period

        Returns:
            Final ATR value
        """
        if len(true_ranges) < period:
            return 0.0

        # Step 1: Calculate initial ATR as simple average of first N true ranges
        initial_atr = sum(true_ranges[:period]) / period

        # Step 2: Apply Wilder's smoothing for remaining true ranges
        atr = initial_atr

        for tr in true_ranges[period:]:
            # Wilder's smoothing: ((ATR_prev × (N-1)) + TR_current) / N
            atr = ((atr * (period - 1)) + tr) / period

        return atr

    def get_atr_multiplier_for_timeframe(self, timeframe: str) -> float:
        """
        Get recommended ATR multiplier for stop loss based on timeframe.

        Different timeframes require different multipliers:
        - 15m: 3.0x (more volatile, wider stops)
        - 1h: 2.5x
        - 4h: 2.0x (less volatile, tighter stops)

        Args:
            timeframe: Timeframe string (e.g., '15m', '1h', '4h')

        Returns:
            Recommended ATR multiplier
        """
        multipliers = {
            '1m': 4.0,
            '5m': 3.5,
            '15m': 3.0,
            '30m': 2.75,
            '1h': 2.5,
            '2h': 2.25,
            '4h': 2.0,
            '1d': 1.5
        }

        return multipliers.get(timeframe, 3.0)  # Default to 3.0

    def __repr__(self) -> str:
        """String representation"""
        return f"ATRCalculator(period={self.period})"
