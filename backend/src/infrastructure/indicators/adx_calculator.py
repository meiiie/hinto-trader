"""
ADX Calculator - Infrastructure Layer

Calculate Average Directional Index (ADX) for trend strength measurement.
"""

import logging
from typing import List, Optional, Tuple
from dataclasses import dataclass

from ...domain.entities.candle import Candle
from .atr_calculator import ATRCalculator


@dataclass
class ADXResult:
    """
    ADX calculation result.

    Attributes:
        adx_value: ADX value (0-100 scale)
        plus_di: +DI (Positive Directional Indicator)
        minus_di: -DI (Negative Directional Indicator)
        period: Period used for calculation
        num_candles: Number of candles used
    """
    adx_value: float
    plus_di: float
    minus_di: float
    period: int
    num_candles: int

    @property
    def is_trending(self) -> bool:
        """
        Check if market is trending.

        Returns:
            True if ADX > 25 (trending market)
        """
        return self.adx_value > 25

    @property
    def trend_strength(self) -> str:
        """
        Get trend strength label.

        Returns:
            Trend strength: VERY_STRONG, STRONG, WEAK, or NO_TREND
        """
        if self.adx_value > 50:
            return "VERY_STRONG"
        elif self.adx_value > 25:
            return "STRONG"
        elif self.adx_value > 20:
            return "WEAK"
        else:
            return "NO_TREND"

    @property
    def trend_direction(self) -> str:
        """
        Get trend direction based on DI comparison.

        Returns:
            BULLISH if +DI > -DI, BEARISH if -DI > +DI, NEUTRAL if equal
        """
        if self.plus_di > self.minus_di:
            return "BULLISH"
        elif self.minus_di > self.plus_di:
            return "BEARISH"
        else:
            return "NEUTRAL"


class ADXCalculator:
    """
    Calculate Average Directional Index (ADX) for trend strength measurement.

    ADX measures the strength of a trend (not direction) on a scale of 0-100:
    - ADX > 25: Strong trend (good for trend-following strategies)
    - ADX < 25: Weak trend or choppy market (avoid trading)
    - ADX > 50: Very strong trend

    The calculation involves:
    1. Calculate +DM (Positive Directional Movement) and -DM (Negative Directional Movement)
    2. Calculate True Range (TR) using ATR calculator
    3. Smooth +DM, -DM, and TR using Wilder's smoothing
    4. Calculate +DI and -DI (Directional Indicators)
    5. Calculate DX (Directional Index)
    6. Calculate ADX as smoothed average of DX

    Usage:
        calculator = ADXCalculator(period=14)
        result = calculator.calculate_adx(candles)
        if result.is_trending:
            print(f"Trending market: ADX={result.adx_value:.1f}")
    """

    def __init__(self, period: int = 14):
        """
        Initialize ADX calculator.

        Args:
            period: ADX period (default: 14)

        Raises:
            ValueError: If period is less than 1
        """
        if period < 1:
            raise ValueError("ADX period must be at least 1")

        self.period = period
        self.atr_calculator = ATRCalculator(period=period)
        self.logger = logging.getLogger(__name__)

        self.logger.info(f"ADXCalculator initialized with period={period}")

    def calculate_adx(
        self,
        candles: List[Candle],
        period: Optional[int] = None
    ) -> ADXResult:
        """
        Calculate ADX value for given candles.

        Args:
            candles: List of Candle entities (chronological order)
            period: Override default period (optional)

        Returns:
            ADXResult with ADX, +DI, -DI values

        Example:
            >>> calculator = ADXCalculator(period=14)
            >>> candles = load_candles()
            >>> result = calculator.calculate_adx(candles)
            >>> if result.is_trending:
            ...     print(f"Strong trend: {result.trend_strength}")
            ...     print(f"Direction: {result.trend_direction}")
        """
        # Use provided period or default
        calc_period = period if period is not None else self.period

        # Limit history to stabilize Wilder's smoothing (~15x period)
        history_needed = max(200, calc_period * 15)
        calc_candles = candles[-history_needed:] if len(candles) > history_needed else candles

        # Need at least period * 2 candles for accurate ADX
        min_candles = calc_period * 2
        if not calc_candles or len(calc_candles) < min_candles:
            self.logger.warning(
                f"Insufficient candles for ADX calculation: "
                f"need {min_candles}, got {len(calc_candles) if calc_candles else 0}"
            )
            return ADXResult(
                adx_value=0.0,
                plus_di=0.0,
                minus_di=0.0,
                period=calc_period,
                num_candles=len(calc_candles) if calc_candles else 0
            )

        # Step 1: Calculate directional movements
        plus_dm_list, minus_dm_list = self._calculate_directional_movements(calc_candles)

        # Step 2: Calculate true ranges
        true_ranges = self.atr_calculator._calculate_true_ranges(calc_candles)

        if len(plus_dm_list) < calc_period or len(true_ranges) < calc_period:
            self.logger.warning("Insufficient data for ADX calculation")
            return ADXResult(
                adx_value=0.0,
                plus_di=0.0,
                minus_di=0.0,
                period=calc_period,
                num_candles=len(candles)
            )

        # Step 3: Smooth +DM, -DM, and TR using Wilder's method
        smoothed_plus_dm = self._apply_wilders_smoothing(plus_dm_list, calc_period)
        smoothed_minus_dm = self._apply_wilders_smoothing(minus_dm_list, calc_period)
        smoothed_tr = self._apply_wilders_smoothing(true_ranges, calc_period)

        # Step 4: Calculate +DI and -DI
        if smoothed_tr == 0:
            plus_di = 0.0
            minus_di = 0.0
        else:
            plus_di = (smoothed_plus_dm / smoothed_tr) * 100
            minus_di = (smoothed_minus_dm / smoothed_tr) * 100

        # Step 5: Calculate DX (Directional Index)
        di_sum = plus_di + minus_di
        if di_sum == 0:
            dx = 0.0
        else:
            dx = (abs(plus_di - minus_di) / di_sum) * 100

        # Step 6: Calculate ADX (smoothed DX)
        # For simplicity, we'll use DX as ADX for the final value
        # In a full implementation, you'd smooth multiple DX values
        adx_value = dx

        # If we have enough data, calculate proper ADX with smoothing
        if len(calc_candles) >= calc_period * 3:
            adx_value = self._calculate_adx_with_smoothing(
                calc_candles, calc_period, plus_dm_list, minus_dm_list, true_ranges
            )

        self.logger.debug(
            f"ADX calculated: {adx_value:.1f} "
            f"(+DI={plus_di:.1f}, -DI={minus_di:.1f}, period={calc_period})"
        )

        return ADXResult(
            adx_value=adx_value,
            plus_di=plus_di,
            minus_di=minus_di,
            period=calc_period,
            num_candles=len(calc_candles)
        )

    def calculate_directional_movement(
        self,
        current_candle: Candle,
        previous_candle: Candle
    ) -> Tuple[float, float]:
        """
        Calculate +DM and -DM for a single candle pair.

        +DM (Positive Directional Movement):
        - If current high > previous high: +DM = current high - previous high
        - Otherwise: +DM = 0

        -DM (Negative Directional Movement):
        - If previous low > current low: -DM = previous low - current low
        - Otherwise: -DM = 0

        Special rule: If both +DM and -DM are positive, only the larger one is kept.

        Args:
            current_candle: Current candle
            previous_candle: Previous candle

        Returns:
            Tuple of (+DM, -DM)

        Example:
            >>> calculator = ADXCalculator()
            >>> current = Candle(high=105, low=100, ...)
            >>> previous = Candle(high=102, low=98, ...)
            >>> plus_dm, minus_dm = calculator.calculate_directional_movement(current, previous)
            >>> print(f"+DM: {plus_dm}, -DM: {minus_dm}")
        """
        # Calculate upward movement
        up_move = current_candle.high - previous_candle.high

        # Calculate downward movement
        down_move = previous_candle.low - current_candle.low

        # Initialize +DM and -DM
        plus_dm = 0.0
        minus_dm = 0.0

        # Apply directional movement rules
        if up_move > down_move and up_move > 0:
            plus_dm = up_move
        elif down_move > up_move and down_move > 0:
            minus_dm = down_move

        return plus_dm, minus_dm

    def _calculate_directional_movements(
        self,
        candles: List[Candle]
    ) -> Tuple[List[float], List[float]]:
        """
        Calculate +DM and -DM for all candles.

        Args:
            candles: List of candles

        Returns:
            Tuple of (+DM list, -DM list)
        """
        plus_dm_list = []
        minus_dm_list = []

        # Start from index 1 (need previous candle)
        for i in range(1, len(candles)):
            plus_dm, minus_dm = self.calculate_directional_movement(
                candles[i], candles[i-1]
            )
            plus_dm_list.append(plus_dm)
            minus_dm_list.append(minus_dm)

        return plus_dm_list, minus_dm_list

    def _apply_wilders_smoothing(
        self,
        values: List[float],
        period: int
    ) -> float:
        """
        Apply Wilder's smoothing method to a list of values.

        Same algorithm as used in ATR calculation.

        Args:
            values: List of values to smooth
            period: Smoothing period

        Returns:
            Final smoothed value
        """
        if len(values) < period:
            return 0.0

        # Initial smoothed value = average of first N values
        smoothed = sum(values[:period]) / period

        # Apply Wilder's smoothing for remaining values
        for value in values[period:]:
            smoothed = ((smoothed * (period - 1)) + value) / period

        return smoothed

    def _calculate_adx_with_smoothing(
        self,
        candles: List[Candle],
        period: int,
        plus_dm_list: List[float],
        minus_dm_list: List[float],
        true_ranges: List[float]
    ) -> float:
        """
        Calculate ADX with proper smoothing of DX values.

        This calculates multiple DX values and then smooths them to get ADX.

        Args:
            candles: List of candles
            period: Calculation period
            plus_dm_list: List of +DM values
            minus_dm_list: List of -DM values
            true_ranges: List of true range values

        Returns:
            Smoothed ADX value
        """
        dx_values = []

        # Calculate DX for each period
        for i in range(period, len(plus_dm_list)):
            # Get slice of data for this period
            pdm_slice = plus_dm_list[i-period+1:i+1]
            mdm_slice = minus_dm_list[i-period+1:i+1]
            tr_slice = true_ranges[i-period+1:i+1]

            # Smooth the slices
            smoothed_pdm = self._apply_wilders_smoothing(pdm_slice, period)
            smoothed_mdm = self._apply_wilders_smoothing(mdm_slice, period)
            smoothed_tr = self._apply_wilders_smoothing(tr_slice, period)

            # Calculate DI values
            if smoothed_tr == 0:
                continue

            plus_di = (smoothed_pdm / smoothed_tr) * 100
            minus_di = (smoothed_mdm / smoothed_tr) * 100

            # Calculate DX
            di_sum = plus_di + minus_di
            if di_sum == 0:
                continue

            dx = (abs(plus_di - minus_di) / di_sum) * 100
            dx_values.append(dx)

        # Smooth DX values to get ADX
        if len(dx_values) >= period:
            adx = self._apply_wilders_smoothing(dx_values, period)
            return adx
        elif dx_values:
            # Not enough for full smoothing, return average
            return sum(dx_values) / len(dx_values)
        else:
            return 0.0

    def __repr__(self) -> str:
        """String representation"""
        return f"ADXCalculator(period={self.period})"
