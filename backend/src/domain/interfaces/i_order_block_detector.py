from abc import ABC, abstractmethod
from typing import List, Optional
from dataclasses import dataclass
from ..entities.candle import Candle

@dataclass
class OrderBlock:
    top: float
    bottom: float
    mitigated: bool
    ob_type: str  # 'BULLISH' or 'BEARISH'
    creation_time: float # Timestamp
    volume: float

class IOrderBlockDetector(ABC):
    @abstractmethod
    def detect(self, candles: List[Candle]) -> List[OrderBlock]:
        """Detect potential order blocks."""
        pass
