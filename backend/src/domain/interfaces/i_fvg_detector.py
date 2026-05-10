from abc import ABC, abstractmethod
from typing import List
from dataclasses import dataclass
from ..entities.candle import Candle

@dataclass
class FVG:
    top: float
    bottom: float
    midpoint: float
    fvg_type: str  # 'BULLISH' or 'BEARISH'
    creation_time: float # Timestamp
    mitigated: bool = False

class IFVGDetector(ABC):
    @abstractmethod
    def detect(self, candles: List[Candle]) -> List[FVG]:
        """Detect Fair Value Gaps."""
        pass
