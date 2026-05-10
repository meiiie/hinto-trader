"""
Regime Result - Value Object for Market Regime Detection

Part of the HMM Regime Detection system (Layer 0).
Provides classification of market into 3 regimes for signal filtering.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Dict


class RegimeType(Enum):
    """Market regime classifications for trading decisions."""

    TRENDING_LOW_VOL = "trending_low_vol"    # State 0: Best for trend pullback
    TRENDING_HIGH_VOL = "trending_high_vol"  # State 1: OK but careful sizing
    RANGING = "ranging"                       # State 2: DO NOT TRADE


@dataclass(frozen=True)
class RegimeResult:
    """
    Result of regime detection analysis.

    Immutable value object containing regime classification,
    probabilities, and trading recommendation.

    Attributes:
        regime: Current regime classification
        probabilities: Probability of being in each state (sum = 1.0)
        confidence: Confidence in classification (highest probability)
        features: Raw features used for detection (for debugging)
        should_trade: Recommendation for trading

    Example:
        >>> result = RegimeResult(
        ...     regime=RegimeType.TRENDING_LOW_VOL,
        ...     probabilities={RegimeType.TRENDING_LOW_VOL: 0.8, ...},
        ...     confidence=0.8,
        ...     features={"adx_normalized": 0.32, ...},
        ...     should_trade=True
        ... )
        >>> if result.should_trade:
        ...     # Continue with signal generation
    """

    # Current regime classification
    regime: RegimeType

    # Probability of being in each state (sum = 1.0)
    probabilities: Dict[RegimeType, float]

    # Confidence in classification (highest probability)
    confidence: float

    # Raw features used for detection (for debugging)
    features: Dict[str, float]

    # Recommendation for trading
    should_trade: bool

    @property
    def is_trending(self) -> bool:
        """Check if market is in a trending regime (low or high volatility)."""
        return self.regime in [RegimeType.TRENDING_LOW_VOL, RegimeType.TRENDING_HIGH_VOL]

    @property
    def is_ranging(self) -> bool:
        """Check if market is in a ranging/choppy regime."""
        return self.regime == RegimeType.RANGING

    @property
    def regime_name(self) -> str:
        """Get human-readable regime name."""
        return self.regime.value.replace("_", " ").title()

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization/logging."""
        return {
            "regime": self.regime.value,
            "is_trending": self.is_trending,
            "is_ranging": self.is_ranging,
            "confidence": self.confidence,
            "should_trade": self.should_trade,
            "probabilities": {k.value: v for k, v in self.probabilities.items()},
            "features": self.features
        }

    def __repr__(self) -> str:
        status = "✅ TRADE" if self.should_trade else "❌ NO TRADE"
        return f"RegimeResult({self.regime.value}, confidence={self.confidence:.2%}, {status})"
