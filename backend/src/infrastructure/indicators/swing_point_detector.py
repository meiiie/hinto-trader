"""
Swing Point Detector - Infrastructure Layer

Detects swing highs and lows for entry price and stop loss calculation.
"""

import logging
from typing import List, Optional, Tuple
from dataclasses import dataclass

from ...domain.entities.candle import Candle


@dataclass
class SwingPoint:
    """
    Swing point information.

    Attributes:
        price: Price at swing point
        index: Index in candle list
        candle: The candle at swing point
        strength: Strength of swing (number of candles on each side)
    """
    price: float
    index: int
    candle: Candle
    strength: int


class SwingPointDetector:
    """
    Detector for swing highs and lows in price action.

    Features:
    - Find recent swing highs (local maxima)
    - Find recent swing lows (local minima)
    - Configurable lookback window
    - Strength-based validation

    Usage:
        detector = SwingPointDetector(lookback=5)
        swing_high = detector.find_recent_swing_high(candles)
        swing_low = detector.find_recent_swing_low(candles)
    """

    def __init__(self, lookback: int = 5):
        """
        Initialize swing point detector.

        Args:
            lookback: Number of candles to look back on each side (default: 5)

        Example:
            With lookback=5, a swing high at index i requires:
            - candles[i].high > candles[i-5:i].high (all previous 5)
            - candles[i].high > candles[i+1:i+6].high (all next 5)
        """
        if lookback < 1:
            raise ValueError("Lookback must be at least 1")

        self.lookback = lookback
        self.logger = logging.getLogger(__name__)

        self.logger.info(f"SwingPointDetector initialized with lookback={lookback}")

    def find_recent_swing_high(
        self,
        candles: List[Candle],
        max_age: Optional[int] = None
    ) -> Optional[SwingPoint]:
        """
        Find the most recent swing high.

        A swing high is a candle whose high is greater than the highs
        of 'lookback' candles before and after it.

        Args:
            candles: List of Candle entities (chronological order)
            max_age: Maximum age in candles from the end (optional)

        Returns:
            SwingPoint or None if no swing high found

        Example:
            >>> detector = SwingPointDetector(lookback=5)
            >>> swing_high = detector.find_recent_swing_high(candles)
            >>> if swing_high:
            ...     print(f"Swing high at ${swing_high.price:.2f}")
        """
        if len(candles) < (2 * self.lookback + 1):
            self.logger.debug(
                f"Insufficient candles for swing detection: "
                f"need {2 * self.lookback + 1}, got {len(candles)}"
            )
            return None

        # Search from most recent to oldest (excluding last 'lookback' candles)
        # We can't identify a swing until we have 'lookback' candles after it
        search_end = len(candles) - self.lookback
        search_start = self.lookback

        # Apply max_age filter if specified
        if max_age:
            search_start = max(search_start, len(candles) - max_age)

        # Search backwards for most recent swing high
        for i in range(search_end - 1, search_start - 1, -1):
            if self._is_swing_high(candles, i):
                swing_point = SwingPoint(
                    price=candles[i].high,
                    index=i,
                    candle=candles[i],
                    strength=self.lookback
                )

                self.logger.debug(
                    f"Swing high found at index {i}: ${swing_point.price:.2f}"
                )

                return swing_point

        self.logger.debug("No swing high found")
        return None

    def find_recent_swing_low(
        self,
        candles: List[Candle],
        max_age: Optional[int] = None
    ) -> Optional[SwingPoint]:
        """
        Find the most recent swing low.

        A swing low is a candle whose low is less than the lows
        of 'lookback' candles before and after it.

        Args:
            candles: List of Candle entities (chronological order)
            max_age: Maximum age in candles from the end (optional)

        Returns:
            SwingPoint or None if no swing low found

        Example:
            >>> detector = SwingPointDetector(lookback=5)
            >>> swing_low = detector.find_recent_swing_low(candles)
            >>> if swing_low:
            ...     print(f"Swing low at ${swing_low.price:.2f}")
        """
        if len(candles) < (2 * self.lookback + 1):
            self.logger.debug(
                f"Insufficient candles for swing detection: "
                f"need {2 * self.lookback + 1}, got {len(candles)}"
            )
            return None

        # Search from most recent to oldest (excluding last 'lookback' candles)
        search_end = len(candles) - self.lookback
        search_start = self.lookback

        # Apply max_age filter if specified
        if max_age:
            search_start = max(search_start, len(candles) - max_age)

        # Search backwards for most recent swing low
        for i in range(search_end - 1, search_start - 1, -1):
            if self._is_swing_low(candles, i):
                swing_point = SwingPoint(
                    price=candles[i].low,
                    index=i,
                    candle=candles[i],
                    strength=self.lookback
                )

                self.logger.debug(
                    f"Swing low found at index {i}: ${swing_point.price:.2f}"
                )

                return swing_point

        self.logger.debug("No swing low found")
        return None

    def find_support_resistance_levels(
        self,
        candles: List[Candle],
        num_levels: int = 3
    ) -> Tuple[List[float], List[float]]:
        """
        Find support and resistance levels from swing points.

        Args:
            candles: List of Candle entities
            num_levels: Number of levels to find (default: 3)

        Returns:
            Tuple of (support_levels, resistance_levels)

        Example:
            >>> detector = SwingPointDetector(lookback=5)
            >>> supports, resistances = detector.find_support_resistance_levels(candles)
            >>> print(f"Support levels: {supports}")
            >>> print(f"Resistance levels: {resistances}")
        """
        if len(candles) < (2 * self.lookback + 1):
            return ([], [])

        # Find all swing highs and lows
        swing_highs = []
        swing_lows = []

        search_end = len(candles) - self.lookback
        search_start = self.lookback

        for i in range(search_start, search_end):
            if self._is_swing_high(candles, i):
                swing_highs.append(candles[i].high)

            if self._is_swing_low(candles, i):
                swing_lows.append(candles[i].low)

        # Sort and get most significant levels
        resistance_levels = sorted(swing_highs, reverse=True)[:num_levels]
        support_levels = sorted(swing_lows)[:num_levels]

        self.logger.debug(
            f"Found {len(resistance_levels)} resistance and "
            f"{len(support_levels)} support levels"
        )

        return (support_levels, resistance_levels)

    def _is_swing_high(self, candles: List[Candle], index: int) -> bool:
        """
        Check if candle at index is a swing high.

        Args:
            candles: List of candles
            index: Index to check

        Returns:
            True if swing high, False otherwise
        """
        if index < self.lookback or index >= len(candles) - self.lookback:
            return False

        current_high = candles[index].high

        # Check previous candles
        for i in range(index - self.lookback, index):
            if candles[i].high >= current_high:
                return False

        # Check next candles
        for i in range(index + 1, index + self.lookback + 1):
            if candles[i].high >= current_high:
                return False

        return True

    def _is_swing_low(self, candles: List[Candle], index: int) -> bool:
        """
        Check if candle at index is a swing low.

        Args:
            candles: List of candles
            index: Index to check

        Returns:
            True if swing low, False otherwise
        """
        if index < self.lookback or index >= len(candles) - self.lookback:
            return False

        current_low = candles[index].low

        # Check previous candles
        for i in range(index - self.lookback, index):
            if candles[i].low <= current_low:
                return False

        # Check next candles
        for i in range(index + 1, index + self.lookback + 1):
            if candles[i].low <= current_low:
                return False

        return True

    def get_nearest_level(
        self,
        price: float,
        levels: List[float],
        direction: str = 'above'
    ) -> Optional[float]:
        """
        Get nearest support/resistance level relative to price.

        Args:
            price: Current price
            levels: List of support/resistance levels
            direction: 'above' for resistance, 'below' for support

        Returns:
            Nearest level or None if no suitable level found
        """
        if not levels:
            return None

        if direction == 'above':
            # Find nearest level above price
            above_levels = [l for l in levels if l > price]
            return min(above_levels) if above_levels else None
        else:  # below
            # Find nearest level below price
            below_levels = [l for l in levels if l < price]
            return max(below_levels) if below_levels else None

    def __repr__(self) -> str:
        """String representation"""
        return f"SwingPointDetector(lookback={self.lookback})"
