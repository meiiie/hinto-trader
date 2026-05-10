"""
IDataAggregator - Domain Interface

Abstract interface for candle data aggregation.
Infrastructure layer provides concrete implementations.
"""

from abc import ABC, abstractmethod
from typing import List, Callable, Optional

from ..entities.candle import Candle


class IDataAggregator(ABC):
    """
    Abstract interface for data aggregation.

    Application layer uses this interface.
    Infrastructure layer (DataAggregator) implements it.
    """

    @abstractmethod
    def add_candle_1m(self, candle: Candle, is_closed: bool = False) -> None:
        """
        Add a 1-minute candle to the aggregator.

        Args:
            candle: 1-minute candle
            is_closed: Whether the candle is closed
        """
        pass

    @abstractmethod
    def on_15m_complete(self, callback: Callable[[Candle], None]) -> None:
        """
        Register callback for when 15-minute candle completes.

        Args:
            callback: Function to call with completed 15m candle
        """
        pass

    @abstractmethod
    def on_1h_complete(self, callback: Callable[[Candle], None]) -> None:
        """
        Register callback for when 1-hour candle completes.

        Args:
            callback: Function to call with completed 1h candle
        """
        pass

    @abstractmethod
    def get_latest_candles(self, timeframe: str, limit: int = 100) -> List[Candle]:
        """
        Get latest candles for a timeframe.

        Args:
            timeframe: '1m', '15m', or '1h'
            limit: Maximum number of candles

        Returns:
            List of candles
        """
        pass

    @abstractmethod
    def clear_buffers(self) -> None:
        """Clear all candle buffers."""
        pass
