"""
SFP Detector - Infrastructure Layer

Detects Swing Failure Patterns (SFP) where price sweeps a key level
but fails to hold, indicating a potential reversal.
"""

import logging
import numpy as np
from typing import List, Optional

from ...domain.entities.candle import Candle
from ...domain.interfaces import (
    ISFPDetector,
    SFPResult,
    SFPType
)
from .swing_point_detector import SwingPointDetector


logger = logging.getLogger(__name__)


class SFPDetector(ISFPDetector):
    """
    Detects Bullish and Bearish SFP patterns.

    Algorithm:
    1. Find recent Swing Highs and Lows
    2. Check if current candle sweeps the level (High > Swing High or Low < Swing Low)
    3. Check if candle closes INSIDE the range (Close < Swing High or Close > Swing Low)
    4. Validate with Volume (optional but recommended)
    """

    def __init__(self, swing_detector: Optional[SwingPointDetector] = None):
        """
        Initialize SFP Detector.

        Args:
            swing_detector: Instance of SwingPointDetector (optional)
        """
        self.swing_detector = swing_detector or SwingPointDetector(lookback=5)
        logger.info("SFPDetector initialized")

    def detect(
        self,
        candles: List[Candle],
        swing_lookback: int = 20,
        volume_ma_period: int = 20
    ) -> SFPResult:
        """
        Detect SFP on the latest candle.

        Args:
            candles: List of candles
            swing_lookback: How far back to look for swing points
            volume_ma_period: Period for volume average

        Returns:
            SFPResult with detection details
        """
        if len(candles) < max(swing_lookback, volume_ma_period) + 5:
            return self._empty_result()

        current = candles[-1]
        prev_candles = candles[:-1]  # Exclude current for swing detection

        # 1. Detect Bullish SFP (Sweep Low -> Close High)
        swing_low = self.swing_detector.find_recent_swing_low(
            prev_candles, max_age=swing_lookback
        )

        if swing_low:
            # Condition 1: Sweep Low (Current Low < Swing Low)
            # Condition 2: Close Above (Current Close > Swing Low)
            if current.low < swing_low.price and current.close > swing_low.price:
                return self._analyze_bullish_sfp(current, swing_low.price, candles, volume_ma_period)

        # 2. Detect Bearish SFP (Sweep High -> Close Low)
        swing_high = self.swing_detector.find_recent_swing_high(
            prev_candles, max_age=swing_lookback
        )

        if swing_high:
            # Condition 1: Sweep High (Current High > Swing High)
            # Condition 2: Close Below (Current Close < Swing High)
            if current.high > swing_high.price and current.close < swing_high.price:
                return self._analyze_bearish_sfp(current, swing_high.price, candles, volume_ma_period)

        return self._empty_result()

    def _analyze_bullish_sfp(
        self,
        current: Candle,
        swing_price: float,
        candles: List[Candle],
        volume_ma_period: int
    ) -> SFPResult:
        """Analyze confirmed Bullish SFP candidates."""
        # Calculate penetration %
        penetration = (swing_price - current.low) / swing_price * 100

        # Calculate rejection strength (wick size / total range)
        candle_range = current.high - current.low
        lower_wick = current.close - current.low
        rejection_strength = lower_wick / candle_range if candle_range > 0 else 0

        # Calculate volume ratio
        volumes = [c.volume for c in candles[-(volume_ma_period+1):-1]]
        avg_volume = np.mean(volumes) if volumes else current.volume
        volume_ratio = current.volume / avg_volume if avg_volume > 0 else 1.0

        # Confidence score calculation
        # Base confidence from rejection strength
        confidence = rejection_strength

        # Boost confidence if volume is high (> 1.5x)
        if volume_ratio > 1.5:
            confidence = min(1.0, confidence * 1.2)

        # Boost confidence if penetration is significant (> 0.1%) but not too deep (> 1.5%)
        # Too deep might mean breakdown instead of sweep
        if 0.1 < penetration < 1.5:
             confidence = min(1.0, confidence * 1.1)

        return SFPResult(
            sfp_type=SFPType.BULLISH,
            swing_price=swing_price,
            penetration_pct=round(penetration, 2),
            rejection_strength=round(rejection_strength, 2),
            volume_ratio=round(volume_ratio, 2),
            is_valid=True,
            confidence=round(confidence, 2)
        )

    def _analyze_bearish_sfp(
        self,
        current: Candle,
        swing_price: float,
        candles: List[Candle],
        volume_ma_period: int
    ) -> SFPResult:
        """Analyze confirmed Bearish SFP candidates."""
        # Calculate penetration %
        penetration = (current.high - swing_price) / swing_price * 100

        # Calculate rejection strength (wick size / total range)
        candle_range = current.high - current.low
        upper_wick = current.high - current.close
        rejection_strength = upper_wick / candle_range if candle_range > 0 else 0

        # Calculate volume ratio
        volumes = [c.volume for c in candles[-(volume_ma_period+1):-1]]
        avg_volume = np.mean(volumes) if volumes else current.volume
        volume_ratio = current.volume / avg_volume if avg_volume > 0 else 1.0

        # Confidence score
        confidence = rejection_strength

        if volume_ratio > 1.5:
            confidence = min(1.0, confidence * 1.2)

        if 0.1 < penetration < 1.5:
             confidence = min(1.0, confidence * 1.1)

        return SFPResult(
            sfp_type=SFPType.BEARISH,
            swing_price=swing_price,
            penetration_pct=round(penetration, 2),
            rejection_strength=round(rejection_strength, 2),
            volume_ratio=round(volume_ratio, 2),
            is_valid=True,
            confidence=round(confidence, 2)
        )

    def _empty_result(self) -> SFPResult:
        return SFPResult(
            sfp_type=SFPType.NONE,
            swing_price=0.0,
            penetration_pct=0.0,
            rejection_strength=0.0,
            volume_ratio=0.0,
            is_valid=False,
            confidence=0.0
        )
