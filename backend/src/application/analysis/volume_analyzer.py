"""
VolumeAnalyzer - Application Layer

Analyzes volume data to detect spikes and anomalies for trading signals.
"""

import logging
from typing import List, Optional
from dataclasses import dataclass
from enum import Enum

from ...domain.entities.candle import Candle


class SpikeLevel(Enum):
    """Volume spike severity levels"""
    NORMAL = "normal"              # < 1.5x average
    ELEVATED = "elevated"          # 1.5x - 2.0x average
    SPIKE = "spike"                # 2.0x - 2.5x average
    STRONG_SPIKE = "strong_spike"  # >= 2.5x average


@dataclass
class VolumeAnalysis:
    """
    Volume analysis result.

    Attributes:
        current_volume: Current candle's volume
        average_volume: 20-period moving average volume
        spike_level: Severity level of volume spike
        ratio: Current volume / average volume
    """
    current_volume: float
    average_volume: float
    spike_level: SpikeLevel
    ratio: float

    def is_spike(self) -> bool:
        """Check if volume is at spike level or higher"""
        return self.spike_level in [SpikeLevel.SPIKE, SpikeLevel.STRONG_SPIKE]

    def is_elevated(self) -> bool:
        """Check if volume is elevated or higher"""
        return self.spike_level != SpikeLevel.NORMAL


class VolumeAnalyzer:
    """
    Analyzer for detecting volume spikes and patterns.

    Features:
    - 20-period volume moving average calculation
    - Spike level detection (2x, 2.5x thresholds)
    - Volume ratio calculation
    - Alert generation for significant spikes
    """


    def __init__(self, ma_period: int = 20):
        """
        Initialize volume analyzer.

        Args:
            ma_period: Period for volume moving average (default: 20)
        """
        self.ma_period = ma_period
        self.logger = logging.getLogger(__name__)

    def analyze(self, candles: List[Candle]) -> Optional[VolumeAnalysis]:
        """
        Analyze volume data from a list of candles.

        Args:
            candles: List of Candle entities (most recent last)

        Returns:
            VolumeAnalysis object or None if insufficient data
        """
        if not candles:
            self.logger.warning("No candles provided for volume analysis")
            return None

        if len(candles) < self.ma_period:
            self.logger.debug(
                f"Insufficient candles for MA({self.ma_period}): "
                f"got {len(candles)}, need {self.ma_period}"
            )
            return None

        # Get current volume
        current_candle = candles[-1]
        current_volume = current_candle.volume

        # Calculate volume MA
        average_volume = self.get_volume_ma(candles, self.ma_period)

        # Calculate ratio
        ratio = current_volume / average_volume if average_volume > 0 else 0

        # Detect spike level
        spike_level = self.detect_spike(current_volume, average_volume)

        analysis = VolumeAnalysis(
            current_volume=current_volume,
            average_volume=average_volume,
            spike_level=spike_level,
            ratio=ratio
        )

        self.logger.debug(
            f"Volume analysis: {current_volume:.2f} / {average_volume:.2f} "
            f"= {ratio:.2f}x ({spike_level.value})"
        )

        return analysis

    def get_volume_ma(
        self,
        candles: List[Candle],
        period: int = 20
    ) -> float:
        """
        Calculate volume moving average.

        Args:
            candles: List of Candle entities
            period: MA period (default: 20)

        Returns:
            Volume moving average
        """
        if len(candles) < period:
            return 0.0

        # Get last N candles
        recent_candles = candles[-period:]

        # Calculate average
        total_volume = sum(c.volume for c in recent_candles)
        average = total_volume / period

        return average


    def detect_spike(
        self,
        current_volume: float,
        avg_volume: float
    ) -> SpikeLevel:
        """
        Detect volume spike level based on thresholds.

        Thresholds:
        - NORMAL: < 1.5x average
        - ELEVATED: 1.5x - 2.0x average
        - SPIKE: 2.0x - 2.5x average
        - STRONG_SPIKE: >= 2.5x average

        Args:
            current_volume: Current candle's volume
            avg_volume: Average volume

        Returns:
            SpikeLevel enum
        """
        if avg_volume == 0:
            return SpikeLevel.NORMAL

        ratio = current_volume / avg_volume

        if ratio >= 2.5:
            return SpikeLevel.STRONG_SPIKE
        elif ratio >= 2.0:
            return SpikeLevel.SPIKE
        elif ratio >= 1.5:
            return SpikeLevel.ELEVATED
        else:
            return SpikeLevel.NORMAL

    def generate_alerts(
        self,
        analysis: VolumeAnalysis
    ) -> List[str]:
        """
        Generate alert messages based on volume analysis.

        Args:
            analysis: VolumeAnalysis object

        Returns:
            List of alert messages
        """
        alerts = []

        if analysis.spike_level == SpikeLevel.STRONG_SPIKE:
            alerts.append(
                f"🔴 STRONG VOLUME SPIKE: {analysis.ratio:.2f}x average "
                f"({analysis.current_volume:.2f} vs {analysis.average_volume:.2f})"
            )
        elif analysis.spike_level == SpikeLevel.SPIKE:
            alerts.append(
                f"🟠 VOLUME SPIKE: {analysis.ratio:.2f}x average "
                f"({analysis.current_volume:.2f} vs {analysis.average_volume:.2f})"
            )
        elif analysis.spike_level == SpikeLevel.ELEVATED:
            alerts.append(
                f"🟡 ELEVATED VOLUME: {analysis.ratio:.2f}x average "
                f"({analysis.current_volume:.2f} vs {analysis.average_volume:.2f})"
            )

        return alerts

    def compare_volumes(
        self,
        candles: List[Candle],
        lookback: int = 5
    ) -> dict:
        """
        Compare current volume with recent volumes.

        Args:
            candles: List of Candle entities
            lookback: Number of previous candles to compare

        Returns:
            Dict with comparison statistics
        """
        if len(candles) < lookback + 1:
            return {}

        current_volume = candles[-1].volume
        recent_volumes = [c.volume for c in candles[-(lookback+1):-1]]

        avg_recent = sum(recent_volumes) / len(recent_volumes)
        max_recent = max(recent_volumes)
        min_recent = min(recent_volumes)

        return {
            'current': current_volume,
            'avg_recent': avg_recent,
            'max_recent': max_recent,
            'min_recent': min_recent,
            'vs_avg': current_volume / avg_recent if avg_recent > 0 else 0,
            'vs_max': current_volume / max_recent if max_recent > 0 else 0,
            'is_highest': current_volume > max_recent
        }

    def __repr__(self) -> str:
        """String representation"""
        return f"VolumeAnalyzer(ma_period={self.ma_period})"
