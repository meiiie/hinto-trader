"""
ExportDataUseCase - Application Layer

Use case for exporting market data to CSV.
"""

from datetime import datetime
from typing import Optional
import pandas as pd

from ...domain.repositories.market_data_repository import MarketDataRepository


class ExportDataUseCase:
    """Use case for exporting data to CSV"""

    def __init__(self, repository: MarketDataRepository):
        self.repository = repository

    def execute(
        self,
        timeframe: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: Optional[int] = None
    ) -> str:
        """
        Export data to CSV format.

        Returns:
            CSV string
        """
        # Get data
        if start and end:
            market_data_list = self.repository.get_candles_by_date_range(
                timeframe, start, end
            )
        else:
            market_data_list = self.repository.get_latest_candles(
                timeframe, limit or 1000
            )

        if not market_data_list:
            return "timestamp,open,high,low,close,volume,ema_7,rsi_6,volume_ma_20\n"

        # Convert to DataFrame
        data = [md.to_dict() for md in market_data_list]
        df = pd.DataFrame(data)

        # Convert to CSV
        return df.to_csv(index=False)
