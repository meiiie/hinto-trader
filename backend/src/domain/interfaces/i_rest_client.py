"""
IRestClient - Domain Interface

Abstract interface for REST API client operations.
Infrastructure layer provides concrete implementations (Binance, etc.).
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from ..entities.candle import Candle


class IRestClient(ABC):
    """
    Abstract interface for REST API client.

    Application layer uses this interface.
    Infrastructure layer (BinanceRestClient) implements it.
    """

    @abstractmethod
    def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 100
    ) -> List[Candle]:
        """
        Get historical klines/candles.

        Args:
            symbol: Trading pair symbol
            interval: Candle interval (1m, 15m, 1h, etc.)
            limit: Number of candles to fetch

        Returns:
            List of Candle entities
        """
        pass

    @abstractmethod
    def get_ticker_price(self, symbol: str) -> Optional[float]:
        """
        Get current ticker price.

        Args:
            symbol: Trading pair symbol

        Returns:
            Current price or None
        """
        pass
