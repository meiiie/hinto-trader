"""
ISFPDetector - Domain Interface

Interface for detecting Swing Failure Patterns (SFP).
SFP is a reversal pattern where price sweeps a swing high/low but closes inside the range.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict
from dataclasses import dataclass
from enum import Enum

from ..entities.candle import Candle


class SFPType(Enum):
    BULLISH = "bullish"  # Sweep Low -> Close High
    BEARISH = "bearish"  # Sweep High -> Close Low
    NONE = "none"


@dataclass
class SFPResult:
    """Result of SFP detection."""

    sfp_type: SFPType
    swing_price: float       # The price level that was swept
    penetration_pct: float   # How far price went beyond swing level (%)
    rejection_strength: float # 0-1 score (wick length vs body)
    volume_ratio: float      # Volume vs Moving Average
    is_valid: bool
    confidence: float        # Combined score 0-1

    def to_dict(self) -> Dict:
        return {
            'type': self.sfp_type.value,
            'swing_price': self.swing_price,
            'penetration_pct': self.penetration_pct,
            'rejection_strength': self.rejection_strength,
            'volume_ratio': self.volume_ratio,
            'confidence': self.confidence
        }


class ISFPDetector(ABC):
    """
    Interface for SFP Detection.
    """

    @abstractmethod
    def detect(
        self,
        candles: List[Candle],
        swing_lookback: int = 20,
        volume_ma_period: int = 20
    ) -> SFPResult:
        """
        Detect SFP on the latest candle.

        Args:
            candles: List of candles (latest is current)
            swing_lookback: How far back to look for swing points
            volume_ma_period: Period for volume average

        Returns:
            SFPResult
        """
        pass
