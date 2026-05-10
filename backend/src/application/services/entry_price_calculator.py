"""
Entry Price Calculator - Application Layer

Calculates optimal entry price for trading signals based on swing points.
"""

import logging
from typing import Optional, List
from dataclasses import dataclass

from ...domain.entities.candle import Candle
from ...domain.interfaces import ISwingPointDetector


@dataclass
class EntryPriceResult:
    """
    Entry price calculation result.

    Attributes:
        entry_price: Calculated entry price
        swing_price: Swing point price used for calculation
        offset_pct: Offset percentage applied
        ema7_distance_pct: Distance from EMA(7) in percentage
        is_valid: Whether entry is valid (within 0.5% of EMA7)
    """
    entry_price: float
    swing_price: float
    offset_pct: float
    ema7_distance_pct: float
    is_valid: bool


class EntryPriceCalculator:
    """
    Calculator for optimal entry prices based on swing points.

    Features:
    - Calculate entry from swing highs (BUY) or swing lows (SELL)
    - Apply 0.1% offset for better entry positioning
    - Validate entry within 0.5% of EMA(7)
    - Return None if no valid entry found

    Usage:
        calculator = EntryPriceCalculator(offset_pct=0.001, max_ema_distance_pct=0.005)
        entry = calculator.calculate_entry_price(
            direction='BUY',
            candles=candles,
            ema7=50000.0
        )
    """

    def __init__(
        self,
        offset_pct: float = 0.001,  # 0.1%
        max_ema_distance_pct: float = 0.005,  # 0.5%
        swing_detector: Optional[ISwingPointDetector] = None
    ):
        """
        Initialize entry price calculator.

        Args:
            offset_pct: Offset percentage for entry (default: 0.001 = 0.1%)
            max_ema_distance_pct: Max distance from EMA(7) (default: 0.005 = 0.5%)
            swing_detector: Swing point detector (injected)
        """
        if offset_pct < 0 or offset_pct > 0.01:
            raise ValueError("Offset percentage must be between 0 and 0.01 (1%)")

        if max_ema_distance_pct < 0 or max_ema_distance_pct > 0.02:
            raise ValueError("Max EMA distance must be between 0 and 0.02 (2%)")

        self.offset_pct = offset_pct
        self.max_ema_distance_pct = max_ema_distance_pct
        self.swing_detector = swing_detector  # Injected dependency
        self.logger = logging.getLogger(__name__)

        self.logger.info(
            f"EntryPriceCalculator initialized: "
            f"offset={offset_pct:.3%}, max_ema_distance={max_ema_distance_pct:.3%}"
        )

    def calculate_entry_price(
        self,
        direction: str,
        candles: List[Candle],
        ema7: float
    ) -> Optional[EntryPriceResult]:
        """
        Calculate optimal entry price based on direction and swing points.

        For BUY signals:
        - Find recent swing high
        - Entry = swing_high * (1 + offset_pct)
        - Validate entry within 0.5% of EMA(7)

        For SELL signals:
        - Find recent swing low
        - Entry = swing_low * (1 - offset_pct)
        - Validate entry within 0.5% of EMA(7)

        Args:
            direction: 'BUY' or 'SELL'
            candles: List of Candle entities (chronological order)
            ema7: Current EMA(7) value

        Returns:
            EntryPriceResult or None if no valid entry found

        Example:
            >>> calculator = EntryPriceCalculator()
            >>> entry = calculator.calculate_entry_price('BUY', candles, 50000.0)
            >>> if entry and entry.is_valid:
            ...     print(f"Entry at ${entry.entry_price:.2f}")
        """
        # Validate inputs
        if direction not in ['BUY', 'SELL']:
            self.logger.error(f"Invalid direction: {direction}")
            return None

        if not candles or len(candles) < 11:  # Need at least 2*lookback + 1
            self.logger.warning(
                f"Insufficient candles for entry calculation: "
                f"need 11, got {len(candles)}"
            )
            return None

        if ema7 <= 0:
            self.logger.error(f"Invalid EMA(7) value: {ema7}")
            return None

        # Calculate entry based on direction
        if direction == 'BUY':
            return self._calculate_buy_entry(candles, ema7)
        else:  # SELL
            return self._calculate_sell_entry(candles, ema7)

    def _calculate_buy_entry(
        self,
        candles: List[Candle],
        ema7: float
    ) -> Optional[EntryPriceResult]:
        """
        Calculate BUY entry price from swing high.

        Args:
            candles: List of candles
            ema7: Current EMA(7) value

        Returns:
            EntryPriceResult or None if no valid entry
        """
        # Find recent swing high
        swing_high = self.swing_detector.find_recent_swing_high(candles)

        if not swing_high:
            self.logger.debug("No swing high found for BUY entry")
            return None

        # Calculate entry with offset (0.1% above swing high)
        entry_price = swing_high.price * (1 + self.offset_pct)

        # Calculate distance from EMA(7)
        ema7_distance_pct = abs((entry_price - ema7) / ema7)

        # Validate entry is within 0.5% of EMA(7)
        is_valid = ema7_distance_pct <= self.max_ema_distance_pct

        result = EntryPriceResult(
            entry_price=entry_price,
            swing_price=swing_high.price,
            offset_pct=self.offset_pct,
            ema7_distance_pct=ema7_distance_pct,
            is_valid=is_valid
        )

        if is_valid:
            self.logger.info(
                f"BUY entry calculated: ${entry_price:.2f} "
                f"(swing: ${swing_high.price:.2f}, "
                f"EMA7 distance: {ema7_distance_pct:.3%})"
            )
        else:
            self.logger.warning(
                f"BUY entry invalid: ${entry_price:.2f} "
                f"too far from EMA(7) ${ema7:.2f} "
                f"(distance: {ema7_distance_pct:.3%} > {self.max_ema_distance_pct:.3%})"
            )

        return result

    def _calculate_sell_entry(
        self,
        candles: List[Candle],
        ema7: float
    ) -> Optional[EntryPriceResult]:
        """
        Calculate SELL entry price from swing low.

        Args:
            candles: List of candles
            ema7: Current EMA(7) value

        Returns:
            EntryPriceResult or None if no valid entry
        """
        # Find recent swing low
        swing_low = self.swing_detector.find_recent_swing_low(candles)

        if not swing_low:
            self.logger.debug("No swing low found for SELL entry")
            return None

        # Calculate entry with offset (0.1% below swing low)
        entry_price = swing_low.price * (1 - self.offset_pct)

        # Calculate distance from EMA(7)
        ema7_distance_pct = abs((entry_price - ema7) / ema7)

        # Validate entry is within 0.5% of EMA(7)
        is_valid = ema7_distance_pct <= self.max_ema_distance_pct

        result = EntryPriceResult(
            entry_price=entry_price,
            swing_price=swing_low.price,
            offset_pct=self.offset_pct,
            ema7_distance_pct=ema7_distance_pct,
            is_valid=is_valid
        )

        if is_valid:
            self.logger.info(
                f"SELL entry calculated: ${entry_price:.2f} "
                f"(swing: ${swing_low.price:.2f}, "
                f"EMA7 distance: {ema7_distance_pct:.3%})"
            )
        else:
            self.logger.warning(
                f"SELL entry invalid: ${entry_price:.2f} "
                f"too far from EMA(7) ${ema7:.2f} "
                f"(distance: {ema7_distance_pct:.3%} > {self.max_ema_distance_pct:.3%})"
            )

        return result

    def validate_entry_against_ema(
        self,
        entry_price: float,
        ema7: float
    ) -> bool:
        """
        Validate if entry price is within acceptable distance from EMA(7).

        Args:
            entry_price: Proposed entry price
            ema7: Current EMA(7) value

        Returns:
            True if valid, False otherwise
        """
        if entry_price <= 0 or ema7 <= 0:
            return False

        distance_pct = abs((entry_price - ema7) / ema7)
        return distance_pct <= self.max_ema_distance_pct

    def __repr__(self) -> str:
        """String representation"""
        return (
            f"EntryPriceCalculator("
            f"offset={self.offset_pct:.3%}, "
            f"max_ema_distance={self.max_ema_distance_pct:.3%}, "
            f"swing_lookback={self.swing_detector.lookback})"
        )
