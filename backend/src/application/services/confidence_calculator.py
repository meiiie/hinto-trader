"""
Confidence Score Calculator - Application Layer

Calculates signal confidence score based on indicator alignment.
"""

import logging
from typing import Dict, Optional
from dataclasses import dataclass
from enum import Enum


class RSIZone(Enum):
    """RSI zones for confidence calculation"""
    OVERSOLD = "oversold"  # RSI < 20
    NEUTRAL_BOTTOM = "neutral_bottom"  # RSI 20-35
    NEUTRAL = "neutral"  # RSI 35-65
    NEUTRAL_TOP = "neutral_top"  # RSI 65-80
    OVERBOUGHT = "overbought"  # RSI > 80


@dataclass
class ConfidenceResult:
    """
    Confidence calculation result.

    Attributes:
        confidence_score: Overall confidence (0-100)
        indicator_scores: Individual indicator scores
        indicator_alignment: Boolean alignment for each indicator
        breakdown: Detailed score breakdown
    """
    confidence_score: float
    indicator_scores: Dict[str, float]
    indicator_alignment: Dict[str, bool]
    breakdown: Dict[str, str]


class ConfidenceCalculator:
    """
    Calculator for signal confidence score.

    Calculates confidence based on indicator alignment:
    - EMA Crossover: 40% weight
    - Volume Spike: 30% weight
    - RSI Zone: 30% weight

    Score ranges:
    - 80-100: Excellent (all indicators aligned)
    - 60-79: Good (most indicators aligned)
    - 40-59: Fair (some indicators aligned)
    - 0-39: Poor (few indicators aligned)

    Usage:
        calculator = ConfidenceCalculator()
        result = calculator.calculate_confidence(
            direction='BUY',
            ema_crossover='bullish',
            volume_spike=True,
            rsi_value=25.0
        )
    """

    # Weights for each indicator
    WEIGHT_EMA = 0.40  # 40%
    WEIGHT_VOLUME = 0.30  # 30%
    WEIGHT_RSI = 0.30  # 30%

    # RSI thresholds
    RSI_OVERSOLD = 20
    RSI_NEUTRAL_BOTTOM = 35
    RSI_NEUTRAL_TOP = 65
    RSI_OVERBOUGHT = 80

    def __init__(self):
        """Initialize confidence calculator"""
        self.logger = logging.getLogger(__name__)
        self.logger.info("ConfidenceCalculator initialized")

    def calculate_confidence(
        self,
        direction: str,
        ema_crossover: Optional[str],
        volume_spike: bool,
        rsi_value: float,
        ema7: Optional[float] = None,
        ema25: Optional[float] = None,
        price: Optional[float] = None
    ) -> ConfidenceResult:
        """
        Calculate confidence score based on indicator alignment.

        Args:
            direction: Signal direction ('BUY' or 'SELL')
            ema_crossover: Crossover type ('bullish', 'bearish', None)
            volume_spike: Whether volume spike detected
            rsi_value: Current RSI value
            ema7: EMA(7) value (optional, for additional validation)
            ema25: EMA(25) value (optional, for additional validation)
            price: Current price (optional, for additional validation)

        Returns:
            ConfidenceResult with score and breakdown

        Example:
            >>> calculator = ConfidenceCalculator()
            >>> result = calculator.calculate_confidence(
            ...     direction='BUY',
            ...     ema_crossover='bullish',
            ...     volume_spike=True,
            ...     rsi_value=25.0
            ... )
            >>> print(f"Confidence: {result.confidence_score:.0f}%")
        """
        # Validate inputs
        if direction not in ['BUY', 'SELL']:
            self.logger.error(f"Invalid direction: {direction}")
            return self._create_zero_confidence("Invalid direction")

        if not (0 <= rsi_value <= 100):
            self.logger.error(f"Invalid RSI value: {rsi_value}")
            return self._create_zero_confidence("Invalid RSI value")

        # Calculate individual indicator scores
        ema_score, ema_aligned = self._score_ema_crossover(direction, ema_crossover)
        volume_score, volume_aligned = self._score_volume_spike(volume_spike)
        rsi_score, rsi_aligned = self._score_rsi_zone(direction, rsi_value)

        # Additional validation with EMA/price if provided
        if ema7 and ema25 and price:
            trend_aligned = self._validate_trend_alignment(direction, ema7, ema25, price)
            if not trend_aligned:
                # Reduce EMA score if trend not aligned
                ema_score *= 0.5
                ema_aligned = False

        # Calculate weighted confidence score
        confidence_score = (
            ema_score * self.WEIGHT_EMA +
            volume_score * self.WEIGHT_VOLUME +
            rsi_score * self.WEIGHT_RSI
        )

        # Create result
        result = ConfidenceResult(
            confidence_score=confidence_score,
            indicator_scores={
                'ema': ema_score,
                'volume': volume_score,
                'rsi': rsi_score
            },
            indicator_alignment={
                'ema': ema_aligned,
                'volume': volume_aligned,
                'rsi': rsi_aligned
            },
            breakdown={
                'ema': f"EMA crossover: {ema_crossover or 'none'} ({ema_score:.0f}/100)",
                'volume': f"Volume spike: {volume_spike} ({volume_score:.0f}/100)",
                'rsi': f"RSI zone: {self._get_rsi_zone(rsi_value).value} ({rsi_score:.0f}/100)"
            }
        )

        self.logger.info(
            f"{direction} signal confidence: {confidence_score:.0f}% "
            f"(EMA:{ema_score:.0f}, Vol:{volume_score:.0f}, RSI:{rsi_score:.0f})"
        )

        return result

    def _score_ema_crossover(
        self,
        direction: str,
        ema_crossover: Optional[str]
    ) -> tuple[float, bool]:
        """
        Score EMA crossover alignment (40% weight).

        Args:
            direction: Signal direction
            ema_crossover: Crossover type

        Returns:
            Tuple of (score, is_aligned)
        """
        if not ema_crossover:
            return (50.0, False)  # Neutral if no crossover

        # Check alignment
        if direction == 'BUY' and ema_crossover == 'bullish':
            return (100.0, True)  # Perfect alignment
        elif direction == 'SELL' and ema_crossover == 'bearish':
            return (100.0, True)  # Perfect alignment
        elif direction == 'BUY' and ema_crossover == 'bearish':
            return (0.0, False)  # Opposite signal
        elif direction == 'SELL' and ema_crossover == 'bullish':
            return (0.0, False)  # Opposite signal
        else:
            return (50.0, False)  # Neutral

    def _score_volume_spike(self, volume_spike: bool) -> tuple[float, bool]:
        """
        Score volume spike confirmation (30% weight).

        Args:
            volume_spike: Whether volume spike detected

        Returns:
            Tuple of (score, is_aligned)
        """
        if volume_spike:
            return (100.0, True)  # Strong confirmation
        else:
            return (50.0, False)  # No confirmation (neutral)

    def _score_rsi_zone(
        self,
        direction: str,
        rsi_value: float
    ) -> tuple[float, bool]:
        """
        Score RSI zone alignment (30% weight).

        For BUY signals:
        - Oversold (< 20): 100 points (excellent)
        - Neutral bottom (20-35): 80 points (good)
        - Neutral (35-65): 50 points (neutral)
        - Neutral top (65-80): 20 points (poor)
        - Overbought (> 80): 0 points (bad)

        For SELL signals:
        - Overbought (> 80): 100 points (excellent)
        - Neutral top (65-80): 80 points (good)
        - Neutral (35-65): 50 points (neutral)
        - Neutral bottom (20-35): 20 points (poor)
        - Oversold (< 20): 0 points (bad)

        Args:
            direction: Signal direction
            rsi_value: RSI value

        Returns:
            Tuple of (score, is_aligned)
        """
        rsi_zone = self._get_rsi_zone(rsi_value)

        if direction == 'BUY':
            if rsi_zone == RSIZone.OVERSOLD:
                return (100.0, True)  # Excellent for BUY
            elif rsi_zone == RSIZone.NEUTRAL_BOTTOM:
                return (80.0, True)  # Good for BUY
            elif rsi_zone == RSIZone.NEUTRAL:
                return (50.0, False)  # Neutral
            elif rsi_zone == RSIZone.NEUTRAL_TOP:
                return (20.0, False)  # Poor for BUY
            else:  # OVERBOUGHT
                return (0.0, False)  # Bad for BUY

        else:  # SELL
            if rsi_zone == RSIZone.OVERBOUGHT:
                return (100.0, True)  # Excellent for SELL
            elif rsi_zone == RSIZone.NEUTRAL_TOP:
                return (80.0, True)  # Good for SELL
            elif rsi_zone == RSIZone.NEUTRAL:
                return (50.0, False)  # Neutral
            elif rsi_zone == RSIZone.NEUTRAL_BOTTOM:
                return (20.0, False)  # Poor for SELL
            else:  # OVERSOLD
                return (0.0, False)  # Bad for SELL

    def _get_rsi_zone(self, rsi_value: float) -> RSIZone:
        """
        Get RSI zone for given value.

        Args:
            rsi_value: RSI value

        Returns:
            RSIZone enum
        """
        if rsi_value < self.RSI_OVERSOLD:
            return RSIZone.OVERSOLD
        elif rsi_value < self.RSI_NEUTRAL_BOTTOM:
            return RSIZone.NEUTRAL_BOTTOM
        elif rsi_value < self.RSI_NEUTRAL_TOP:
            return RSIZone.NEUTRAL
        elif rsi_value < self.RSI_OVERBOUGHT:
            return RSIZone.NEUTRAL_TOP
        else:
            return RSIZone.OVERBOUGHT

    def _validate_trend_alignment(
        self,
        direction: str,
        ema7: float,
        ema25: float,
        price: float
    ) -> bool:
        """
        Validate trend alignment with EMAs and price.

        For BUY: price > EMA7 > EMA25
        For SELL: price < EMA7 < EMA25

        Args:
            direction: Signal direction
            ema7: EMA(7) value
            ema25: EMA(25) value
            price: Current price

        Returns:
            True if trend aligned, False otherwise
        """
        if direction == 'BUY':
            return price > ema7 > ema25
        else:  # SELL
            return price < ema7 < ema25

    def _create_zero_confidence(self, reason: str) -> ConfidenceResult:
        """
        Create zero confidence result for invalid inputs.

        Args:
            reason: Reason for zero confidence

        Returns:
            ConfidenceResult with zero score
        """
        return ConfidenceResult(
            confidence_score=0.0,
            indicator_scores={'ema': 0.0, 'volume': 0.0, 'rsi': 0.0},
            indicator_alignment={'ema': False, 'volume': False, 'rsi': False},
            breakdown={'error': reason}
        )

    def get_confidence_level(self, confidence_score: float) -> str:
        """
        Get confidence level description.

        Args:
            confidence_score: Confidence score (0-100)

        Returns:
            Confidence level string
        """
        if confidence_score >= 80:
            return "Excellent"
        elif confidence_score >= 60:
            return "Good"
        elif confidence_score >= 40:
            return "Fair"
        else:
            return "Poor"

    def __repr__(self) -> str:
        """String representation"""
        return (
            f"ConfidenceCalculator("
            f"weights: EMA={self.WEIGHT_EMA:.0%}, "
            f"Volume={self.WEIGHT_VOLUME:.0%}, "
            f"RSI={self.WEIGHT_RSI:.0%})"
        )
