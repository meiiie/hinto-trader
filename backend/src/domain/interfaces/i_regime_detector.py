"""
Regime Detector Interface - Domain Layer

Abstract interface for market regime detection.
Implementations can use HMM, rule-based, or other methods.
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from ..entities.candle import Candle
from ..value_objects.regime_result import RegimeResult


class IRegimeDetector(ABC):
    """
    Interface for market regime detection.

    Implementations should classify market into regimes
    (TRENDING_LOW_VOL, TRENDING_HIGH_VOL, RANGING) based on
    price action and volume analysis.

    Example:
        >>> detector = ConcreteRegimeDetector()
        >>> detector.fit(historical_candles)
        >>> result = detector.detect_regime(recent_candles)
        >>> if result.should_trade:
        ...     # Proceed with signal generation
    """

    @abstractmethod
    def detect_regime(self, candles: List[Candle]) -> Optional[RegimeResult]:
        """
        Detect current market regime from candle data.

        Args:
            candles: List of recent candles (minimum 50 recommended)

        Returns:
            RegimeResult with classification and probabilities,
            or None if insufficient data
        """
        pass

    @abstractmethod
    def fit(self, candles: List[Candle]) -> "IRegimeDetector":
        """
        Train the detector on historical data.

        Args:
            candles: Historical candles for training (minimum 100-200)

        Returns:
            self (for method chaining)
        """
        pass

    @property
    @abstractmethod
    def is_fitted(self) -> bool:
        """Check if detector has been trained."""
        pass
