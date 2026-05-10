"""
Volume Spike Detector - Infrastructure Layer

Detects volume spikes for signal confirmation in professional trading.
"""

import logging
from typing import List, Optional
from dataclasses import dataclass
from enum import Enum


class SpikeIntensity(Enum):
    """Volume spike intensity levels"""
    NONE = "none"           # No spike
    MODERATE = "moderate"   # 1.5x - 2.0x average
    STRONG = "strong"       # 2.0x - 3.0x average
    EXTREME = "extreme"     # > 3.0x average


@dataclass
class VolumeSpikeResult:
    """
    Volume spike detection result.

    Attributes:
        is_spike: Whether a spike was detected
        intensity: Spike intensity level
        current_volume: Current volume value
        average_volume: Average volume (MA)
        ratio: Current volume / Average volume
        threshold: Threshold used for detection
    """
    is_spike: bool
    intensity: SpikeIntensity
    current_volume: float
    average_volume: float
    ratio: float
    threshold: float


class VolumeSpikeDetector:
    """
    Detector for volume spikes above moving average.

    Features:
    - Configurable spike threshold (default: 2.0x)
    - Multiple intensity levels
    - Volume ratio calculation
    - Professional spike validation

    Usage:
        detector = VolumeSpikeDetector(threshold=2.0)
        result = detector.detect_spike(current_volume=500, volume_ma=200)
        if result.is_spike:
            print(f"Spike detected: {result.ratio:.2f}x average")
    """

    def __init__(
        self,
        threshold: float = 2.0,
        min_threshold: float = 1.5,
        max_threshold: float = 3.0
    ):
        """
        Initialize volume spike detector.

        Args:
            threshold: Spike threshold multiplier (default: 2.0)
            min_threshold: Minimum allowed threshold (default: 1.5)
            max_threshold: Maximum allowed threshold (default: 3.0)

        Raises:
            ValueError: If threshold is outside allowed range
        """
        if not min_threshold <= threshold <= max_threshold:
            raise ValueError(
                f"Threshold {threshold} must be between "
                f"{min_threshold} and {max_threshold}"
            )

        self.threshold = threshold
        self.min_threshold = min_threshold
        self.max_threshold = max_threshold

        self.logger = logging.getLogger(__name__)
        self.logger.info(
            f"VolumeSpikeDetector initialized with threshold={threshold}x"
        )

    def detect_spike(
        self,
        current_volume: float,
        volume_ma: float
    ) -> VolumeSpikeResult:
        """
        Detect if current volume is a spike above average.

        Args:
            current_volume: Current volume value
            volume_ma: Volume moving average

        Returns:
            VolumeSpikeResult with detection details

        Example:
            >>> detector = VolumeSpikeDetector(threshold=2.0)
            >>> result = detector.detect_spike(400, 200)
            >>> result.is_spike
            True
            >>> result.ratio
            2.0
        """
        # Validate inputs
        if current_volume < 0 or volume_ma <= 0:
            self.logger.warning(
                f"Invalid volume values: current={current_volume}, ma={volume_ma}"
            )
            return VolumeSpikeResult(
                is_spike=False,
                intensity=SpikeIntensity.NONE,
                current_volume=current_volume,
                average_volume=volume_ma,
                ratio=0.0,
                threshold=self.threshold
            )

        # Calculate ratio
        ratio = current_volume / volume_ma

        # Determine spike and intensity
        is_spike = ratio >= self.threshold
        intensity = self._calculate_intensity(ratio)

        if is_spike:
            self.logger.info(
                f"Volume spike detected: {current_volume:.2f} / {volume_ma:.2f} "
                f"= {ratio:.2f}x (threshold: {self.threshold}x, "
                f"intensity: {intensity.value})"
            )

        return VolumeSpikeResult(
            is_spike=is_spike,
            intensity=intensity,
            current_volume=current_volume,
            average_volume=volume_ma,
            ratio=ratio,
            threshold=self.threshold
        )

    def _calculate_intensity(self, ratio: float) -> SpikeIntensity:
        """
        Calculate spike intensity based on ratio.

        Args:
            ratio: Volume ratio (current / average)

        Returns:
            SpikeIntensity level
        """
        if ratio >= 3.0:
            return SpikeIntensity.EXTREME
        elif ratio >= 2.0:
            return SpikeIntensity.STRONG
        elif ratio >= 1.5:
            return SpikeIntensity.MODERATE
        else:
            return SpikeIntensity.NONE

    def detect_spike_from_list(
        self,
        volumes: List[float],
        ma_period: int = 20
    ) -> Optional[VolumeSpikeResult]:
        """
        Detect spike from list of volumes.

        Args:
            volumes: List of volume values (most recent last)
            ma_period: Moving average period (default: 20)

        Returns:
            VolumeSpikeResult for the latest volume, or None if insufficient data
        """
        if len(volumes) < ma_period:
            self.logger.warning(
                f"Insufficient data: {len(volumes)} volumes, need {ma_period}"
            )
            return None

        # Calculate MA of previous volumes (excluding current)
        volume_ma = sum(volumes[-(ma_period+1):-1]) / ma_period
        current_volume = volumes[-1]

        return self.detect_spike(current_volume, volume_ma)

    def set_threshold(self, threshold: float) -> None:
        """
        Update spike threshold.

        Args:
            threshold: New threshold value

        Raises:
            ValueError: If threshold is outside allowed range
        """
        if not self.min_threshold <= threshold <= self.max_threshold:
            raise ValueError(
                f"Threshold {threshold} must be between "
                f"{self.min_threshold} and {self.max_threshold}"
            )

        old_threshold = self.threshold
        self.threshold = threshold
        self.logger.info(
            f"Threshold updated: {old_threshold}x → {threshold}x"
        )

    def get_threshold_range(self) -> tuple:
        """
        Get allowed threshold range.

        Returns:
            Tuple of (min_threshold, max_threshold)
        """
        return (self.min_threshold, self.max_threshold)

    def calculate_confidence_boost(self, spike_result: VolumeSpikeResult) -> float:
        """
        Calculate confidence boost for signal based on spike intensity.

        Args:
            spike_result: Volume spike detection result

        Returns:
            Confidence boost percentage (0-30)

        Scoring:
        - EXTREME: +30%
        - STRONG: +20%
        - MODERATE: +10%
        - NONE: 0%

        Note: MODERATE spikes (1.5x-2.0x) still provide confidence boost
        even if below the main threshold.
        """
        intensity_boost = {
            SpikeIntensity.EXTREME: 30.0,
            SpikeIntensity.STRONG: 20.0,
            SpikeIntensity.MODERATE: 10.0,
            SpikeIntensity.NONE: 0.0
        }

        return intensity_boost.get(spike_result.intensity, 0.0)

    def __repr__(self) -> str:
        """String representation"""
        return (
            f"VolumeSpikeDetector(threshold={self.threshold}x, "
            f"range={self.min_threshold}-{self.max_threshold})"
        )
