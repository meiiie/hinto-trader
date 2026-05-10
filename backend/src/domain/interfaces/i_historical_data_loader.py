from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional, Dict
from ..entities.candle import Candle

class IHistoricalDataLoader(ABC):
    @abstractmethod
    async def load_portfolio_data(
        self,
        symbols: List[str],
        interval: str,
        start_time: datetime,
        end_time: Optional[datetime] = None
    ) -> Dict[datetime, Dict[str, Candle]]:
        pass
