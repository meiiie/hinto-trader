"""
IMomentumVelocityCalculator - Domain Interface

Interface for calculating price momentum velocity and acceleration.
Used to detect FOMO spikes (too fast) and deceleration (safe entry).
"""

from abc import ABC, abstractmethod
from typing import List, Dict
from dataclasses import dataclass

from ..entities.candle import Candle


@dataclass
class VelocityResult:
    """Result of momentum velocity calculation."""

    velocity: float       # Percent change per minute
    acceleration: float   # Change in velocity
    is_fomo_spike: bool   # True if velocity > threshold (unsafe to buy)
    is_crash_drop: bool   # True if velocity < -threshold (price crashing)
    is_decelerating: bool # True if acceleration < 0 (slowing down)
    is_accelerating: bool # True if acceleration > 0 (speeding up)

    def to_dict(self) -> Dict:
        return {
            'velocity': self.velocity,
            'acceleration': self.acceleration,
            'is_fomo_spike': self.is_fomo_spike,
            'is_crash_drop': self.is_crash_drop,
            'is_decelerating': self.is_decelerating,
            'is_accelerating': self.is_accelerating
        }


class IMomentumVelocityCalculator(ABC):
    """
    Interface for Momentum Velocity Calculation.
    """

    @abstractmethod
    def calculate(
        self,
        candles: List[Candle],
        lookback: int = 5,
        fomo_threshold: float = 0.5  # 0.5% per minute is very fast
    ) -> VelocityResult:
        """
        Calculate momentum velocity for the latest candle.

        Args:
            candles: List of candles
            lookback: Number of candles to calculate rate of change
            fomo_threshold: Threshold for FOMO detection (%/min)

        Returns:
            VelocityResult
        """
        pass
