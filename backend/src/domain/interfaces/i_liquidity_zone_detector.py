"""
ILiquidityZoneDetector - Domain Interface

Interface for detecting liquidity zones (SL clusters, TP zones).
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict
from dataclasses import dataclass

from ..entities.candle import Candle


@dataclass
class LiquidityZone:
    """A detected liquidity zone."""

    zone_low: float
    zone_high: float
    zone_type: str  # "stop_loss_cluster", "take_profit_zone", "breakout_zone"
    strength: float  # 0-1 based on volume and touch count
    touch_count: int  # How many times price tested this zone
    last_touch_idx: int  # Index of last touch in candles
    is_broken: bool  # Whether zone has been invalidated

    @property
    def midpoint(self) -> float:
        """Zone midpoint price."""
        return (self.zone_high + self.zone_low) / 2

    @property
    def width(self) -> float:
        """Zone width in price."""
        return self.zone_high - self.zone_low

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            'zone_low': self.zone_low,
            'zone_high': self.zone_high,
            'zone_type': self.zone_type,
            'strength': self.strength,
            'touch_count': self.touch_count,
            'midpoint': self.midpoint,
            'width': self.width,
            'is_broken': self.is_broken
        }


@dataclass
class LiquidityZonesResult:
    """Complete liquidity zones analysis result."""

    stop_loss_clusters: List[LiquidityZone]
    take_profit_zones: List[LiquidityZone]
    breakout_zones: List[LiquidityZone]

    # Current price context
    nearest_support: Optional[LiquidityZone]
    nearest_resistance: Optional[LiquidityZone]

    # Risk management recommendations
    recommended_stop_loss: Optional[float]  # Outside SL cluster
    recommended_take_profit: Optional[float]  # At TP zone

    # Metadata
    analysis_high: float
    analysis_low: float
    calculation_time_ms: float

    def to_dict(self) -> Dict:
        """Convert to dictionary for API response."""
        return {
            'stop_loss_clusters': [z.to_dict() for z in self.stop_loss_clusters],
            'take_profit_zones': [z.to_dict() for z in self.take_profit_zones],
            'breakout_zones': [z.to_dict() for z in self.breakout_zones],
            'nearest_support': self.nearest_support.to_dict() if self.nearest_support else None,
            'nearest_resistance': self.nearest_resistance.to_dict() if self.nearest_resistance else None,
            'recommended_stop_loss': self.recommended_stop_loss,
            'recommended_take_profit': self.recommended_take_profit,
            'analysis_high': self.analysis_high,
            'analysis_low': self.analysis_low,
            'calculation_time_ms': self.calculation_time_ms
        }


class ILiquidityZoneDetector(ABC):
    """
    Interface for Liquidity Zone detection.
    """

    @abstractmethod
    def detect_zones(
        self,
        candles: List[Candle],
        current_price: Optional[float] = None,
        atr_value: Optional[float] = None
    ) -> Optional[LiquidityZonesResult]:
        """Detect all liquidity zones from candles."""
        pass
