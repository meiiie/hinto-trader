"""
EMA Crossover Detector - Application Layer

Detects EMA(7)/EMA(25) crossover signals for professional trend identification.
"""

import logging
from typing import Optional, List
from dataclasses import dataclass
from enum import Enum

from ...domain.entities.candle import Candle


class CrossoverType(Enum):
    """EMA crossover signal types"""
    BULLISH = "bullish"   # EMA(7) crosses above EMA(25)
    BEARISH = "bearish"   # EMA(7) crosses below EMA(25)
    NONE = "none"         # No crossover


@dataclass
class CrossoverSignal:
    """
    EMA crossover signal information.

    Attributes:
        type: Type of crossover (bullish/bearish/none)
        ema7: Current EMA(7) value
        ema25: Current EMA(25) value
        spread_pct: Percentage spread between EMA7 and EMA25
        strength: Signal strength (0-100)
    """
    type: CrossoverType
    ema7: float
    ema25: float
    spread_pct: float
    strength: float


class EMACrossoverDetector:
    """
    Detector for EMA(7)/EMA(25) crossover signals.

    Features:
    - Detects bullish and bearish crossovers
    - Calculates spread percentage
    - Provides signal strength scoring
    - Validates crossover quality
    """

    def __init__(self):
        """Initialize crossover detector"""
        self.logger = logging.getLogger(__name__)

    def detect_crossover(
        self,
        ema7_current: float,
        ema25_current: float,
        ema7_previous: float,
        ema25_previous: float
    ) -> CrossoverType:
        """
        Detect EMA crossover between current and previous values.

        Args:
            ema7_current: Current EMA(7) value
            ema25_current: Current EMA(25) value
            ema7_previous: Previous EMA(7) value
            ema25_previous: Previous EMA(25) value

        Returns:
            CrossoverType indicating the type of crossover detected

        Example:
            >>> detector = EMACrossoverDetector()
            >>> crossover = detector.detect_crossover(100, 99, 98, 99)
            >>> crossover == CrossoverType.BULLISH
            True
        """
        # Validate inputs
        if any(v is None or v <= 0 for v in [ema7_current, ema25_current,
                                               ema7_previous, ema25_previous]):
            return CrossoverType.NONE

        # Check for bullish crossover (EMA7 crosses above EMA25)
        if ema7_previous < ema25_previous and ema7_current > ema25_current:
            self.logger.info(
                f"Bullish crossover detected: EMA7 {ema7_previous:.2f}→{ema7_current:.2f}, "
                f"EMA25 {ema25_previous:.2f}→{ema25_current:.2f}"
            )
            return CrossoverType.BULLISH

        # Check for bearish crossover (EMA7 crosses below EMA25)
        if ema7_previous > ema25_previous and ema7_current < ema25_current:
            self.logger.info(
                f"Bearish crossover detected: EMA7 {ema7_previous:.2f}→{ema7_current:.2f}, "
                f"EMA25 {ema25_previous:.2f}→{ema25_current:.2f}"
            )
            return CrossoverType.BEARISH

        return CrossoverType.NONE

    def get_current_trend(self, ema7: float, ema25: float) -> str:
        """
        Get current trend based on EMA positions.

        Args:
            ema7: Current EMA(7) value
            ema25: Current EMA(25) value

        Returns:
            'bullish', 'bearish', or 'neutral'
        """
        if ema7 > ema25:
            return 'bullish'
        elif ema7 < ema25:
            return 'bearish'
        else:
            return 'neutral'

    def calculate_spread_pct(self, ema7: float, ema25: float) -> float:
        """
        Calculate percentage spread between EMA7 and EMA25.

        Args:
            ema7: EMA(7) value
            ema25: EMA(25) value

        Returns:
            Percentage spread (positive if EMA7 > EMA25, negative otherwise)
        """
        if ema25 == 0:
            return 0.0

        return ((ema7 - ema25) / ema25) * 100

    def calculate_signal_strength(
        self,
        ema7: float,
        ema25: float,
        price: float
    ) -> float:
        """
        Calculate signal strength based on EMA alignment and price position.

        Args:
            ema7: EMA(7) value
            ema25: EMA(25) value
            price: Current price

        Returns:
            Signal strength score (0-100)

        Scoring:
        - Base score: 50
        - +20 if price aligned with trend (above both EMAs for bullish)
        - +15 for strong spread (> 0.5%)
        - +15 for moderate spread (0.2% - 0.5%)
        """
        score = 50.0  # Base score

        spread_pct = abs(self.calculate_spread_pct(ema7, ema25))
        trend = self.get_current_trend(ema7, ema25)

        # Price alignment with trend
        if trend == 'bullish' and price > ema7 > ema25:
            score += 20
        elif trend == 'bearish' and price < ema7 < ema25:
            score += 20

        # Spread strength
        if spread_pct > 0.5:
            score += 15  # Strong spread
        elif spread_pct > 0.2:
            score += 15  # Moderate spread
        elif spread_pct > 0.1:
            score += 10  # Weak spread

        return min(score, 100.0)

    def create_crossover_signal(
        self,
        ema7_current: float,
        ema25_current: float,
        ema7_previous: float,
        ema25_previous: float,
        price: float
    ) -> CrossoverSignal:
        """
        Create complete crossover signal with all metadata.

        Args:
            ema7_current: Current EMA(7) value
            ema25_current: Current EMA(25) value
            ema7_previous: Previous EMA(7) value
            ema25_previous: Previous EMA(25) value
            price: Current price

        Returns:
            CrossoverSignal with complete information
        """
        crossover_type = self.detect_crossover(
            ema7_current, ema25_current,
            ema7_previous, ema25_previous
        )

        spread_pct = self.calculate_spread_pct(ema7_current, ema25_current)
        strength = self.calculate_signal_strength(ema7_current, ema25_current, price)

        return CrossoverSignal(
            type=crossover_type,
            ema7=ema7_current,
            ema25=ema25_current,
            spread_pct=spread_pct,
            strength=strength
        )

    def __repr__(self) -> str:
        """String representation"""
        return "EMACrossoverDetector(ema7=7, ema25=25)"
