"""
IVolumeDeltaCalculator - Domain Interface

Interface for Volume Delta calculation.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Any
from dataclasses import dataclass

from ..entities.candle import Candle


@dataclass
class VolumeDeltaResult:
    """Result of Volume Delta calculation for a single candle."""

    # Delta values
    delta: float  # buy_volume - sell_volume
    buy_volume: float  # Estimated aggressive buying
    sell_volume: float  # Estimated aggressive selling

    # Normalized values
    delta_percent: float  # Delta as % of total volume (-100 to +100)
    aggression_ratio: float  # Dominant side volume / total (0.5-1.0)

    # Metadata
    confidence: float  # 0-1 based on volatility (lower in high vol)
    is_bullish_delta: bool
    is_bearish_delta: bool


@dataclass
class CumulativeDeltaResult:
    """Result of Cumulative Volume Delta over multiple candles."""

    cumulative_delta: float
    delta_series: List[float]

    # Divergence detection
    has_bullish_divergence: bool  # Price making lower lows, delta making higher lows
    has_bearish_divergence: bool  # Price making higher highs, delta making lower highs

    # Trend
    delta_trend: str  # "rising", "falling", "neutral"
    delta_momentum: float  # Rate of change


class IVolumeDeltaCalculator(ABC):
    """
    Interface for Volume Delta calculations.
    """

    @abstractmethod
    def calculate(
        self,
        candle: Candle,
        volume_ma20: Optional[float] = None,
        atr: Optional[float] = None
    ) -> VolumeDeltaResult:
        """Calculate Volume Delta for a single candle."""
        pass

    @abstractmethod
    def calculate_cumulative(
        self,
        candles: List[Candle],
        volume_ma_period: int = 20
    ) -> CumulativeDeltaResult:
        """Calculate Cumulative Volume Delta over multiple candles."""
        pass
