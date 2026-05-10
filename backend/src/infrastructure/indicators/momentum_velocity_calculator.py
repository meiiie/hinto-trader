"""
Momentum Velocity Calculator - Infrastructure Layer

Calculates the speed (velocity) and rate of change (acceleration) of price movement.
Used to detect unsustainable moves (FOMO) and safe entry points (Deceleration).
"""

import logging
from typing import List

from ...domain.entities.candle import Candle
from ...domain.interfaces import (
    IMomentumVelocityCalculator,
    VelocityResult
)


logger = logging.getLogger(__name__)


class MomentumVelocityCalculator(IMomentumVelocityCalculator):
    """
    Calculates price velocity and acceleration.

    Velocity = (% Change) / Time
    Acceleration = (Velocity_current - Velocity_prev)
    """

    def __init__(self):
        logger.info("MomentumVelocityCalculator initialized")

    def calculate(
        self,
        candles: List[Candle],
        lookback: int = 5,
        fomo_threshold: float = 0.5  # 0.5% per minute
    ) -> VelocityResult:
        """
        Calculate momentum velocity.

        Args:
            candles: List of candles
            lookback: Window for calculation
            fomo_threshold: Velocity threshold for FOMO warning
        """
        if len(candles) < lookback + 2:
            return VelocityResult(0, 0, False, False, False)

        # 1. Calculate Current Velocity
        # Velocity = (Price_now - Price_start) / Price_start * 100 / Time_minutes
        # For simple comparison, we assume uniform time intervals (1 unit per candle)
        # So Velocity = % Change / lookback

        current_price = candles[-1].close
        start_price = candles[-lookback].close

        pct_change = (current_price - start_price) / start_price * 100
        current_velocity = pct_change / lookback  # % per candle

        # 2. Calculate Previous Velocity (for Acceleration)
        # Shift back by 1 candle
        prev_price = candles[-2].close
        prev_start_price = candles[-(lookback+1)].close

        prev_pct_change = (prev_price - prev_start_price) / prev_start_price * 100
        prev_velocity = prev_pct_change / lookback

        # 3. Calculate Acceleration
        acceleration = current_velocity - prev_velocity

        # 4. Determine State
        # FOMO Spike: Velocity is very positive (price shooting up fast)
        is_fomo = current_velocity > fomo_threshold

        # Crash Drop: Velocity is very negative (price crashing down fast)
        is_crash = current_velocity < -fomo_threshold

        # Decelerating: Speed is decreasing (e.g., going up but slower, or going down but slower)
        # If Velocity > 0 (Up), Acceleration < 0 means slowing down
        # If Velocity < 0 (Down), Acceleration > 0 means slowing down (less negative)
        is_decelerating = False
        if current_velocity > 0 and acceleration < 0:
            is_decelerating = True
        elif current_velocity < 0 and acceleration > 0:
            is_decelerating = True

        return VelocityResult(
            velocity=round(current_velocity, 4),
            acceleration=round(acceleration, 4),
            is_fomo_spike=is_fomo,
            is_crash_drop=is_crash,
            is_decelerating=is_decelerating,
            is_accelerating=not is_decelerating and abs(acceleration) > 0.0001
        )
