"""
MarketDataRepository Interface - Domain Layer

Abstract repository interface for market data persistence.
This defines the contract that infrastructure implementations must follow.
"""

from abc import ABC, abstractmethod
from typing import List, Optional
from datetime import datetime

from ..entities.candle import Candle
from ..entities.indicator import Indicator
from ..entities.market_data import MarketData


class MarketDataRepository(ABC):
    """
    Abstract repository interface for market data operations.

    This interface defines the contract for persisting and retrieving
    market data (candles with indicators). Infrastructure layer will
    provide concrete implementations (e.g., SQLite, PostgreSQL, etc.).

    Following the Repository Pattern, this interface:
    - Abstracts data access logic from business logic
    - Allows easy swapping of data sources
    - Facilitates testing with mock implementations
    """

    @abstractmethod
    def save_candle(
        self,
        candle: Candle,
        indicator: Indicator,
        timeframe: str
    ) -> None:
        """
        Save a candle with its indicators to the repository.

        Args:
            candle: The candle entity to save
            indicator: The indicator entity to save
            timeframe: The timeframe (e.g., '15m', '1h')

        Raises:
            RepositoryError: If save operation fails

        Note:
            If a candle with the same timestamp already exists,
            it should be updated (upsert behavior).
        """
        pass

    @abstractmethod
    def save_market_data(self, market_data: MarketData) -> None:
        """
        Save market data aggregate to the repository.

        Args:
            market_data: The market data aggregate to save

        Raises:
            RepositoryError: If save operation fails
        """
        pass

    @abstractmethod
    def get_latest_candles(
        self,
        timeframe: str,
        limit: int = 100
    ) -> List[MarketData]:
        """
        Get the latest N candles with indicators.

        Args:
            timeframe: The timeframe to query (e.g., '15m', '1h')
            limit: Maximum number of candles to return (default: 100)

        Returns:
            List of MarketData aggregates, ordered by timestamp DESC

        Raises:
            RepositoryError: If query fails
        """
        pass

    @abstractmethod
    def get_candles_by_date_range(
        self,
        timeframe: str,
        start: datetime,
        end: datetime
    ) -> List[MarketData]:
        """
        Get candles within a specific date range.

        Args:
            timeframe: The timeframe to query
            start: Start datetime (inclusive)
            end: End datetime (inclusive)

        Returns:
            List of MarketData aggregates within the date range

        Raises:
            RepositoryError: If query fails
        """
        pass

    @abstractmethod
    def get_candle_by_timestamp(
        self,
        timeframe: str,
        timestamp: datetime
    ) -> Optional[MarketData]:
        """
        Get a specific candle by timestamp.

        Args:
            timeframe: The timeframe to query
            timestamp: The exact timestamp to find

        Returns:
            MarketData if found, None otherwise

        Raises:
            RepositoryError: If query fails
        """
        pass

    @abstractmethod
    def get_record_count(self, timeframe: str) -> int:
        """
        Get the total number of records for a timeframe.

        Args:
            timeframe: The timeframe to count

        Returns:
            Total number of records

        Raises:
            RepositoryError: If query fails
        """
        pass

    @abstractmethod
    def get_latest_timestamp(self, timeframe: str) -> Optional[datetime]:
        """
        Get the timestamp of the most recent candle.

        Args:
            timeframe: The timeframe to query

        Returns:
            Latest timestamp if records exist, None otherwise

        Raises:
            RepositoryError: If query fails
        """
        pass

    @abstractmethod
    def delete_candles_before(
        self,
        timeframe: str,
        before: datetime
    ) -> int:
        """
        Delete candles older than a specific date.

        Useful for data retention policies.

        Args:
            timeframe: The timeframe to clean
            before: Delete records before this datetime

        Returns:
            Number of records deleted

        Raises:
            RepositoryError: If delete operation fails
        """
        pass

    @abstractmethod
    def get_database_size(self) -> float:
        """
        Get the size of the database in megabytes.

        Returns:
            Database size in MB

        Raises:
            RepositoryError: If operation fails
        """
        pass

    @abstractmethod
    def backup_database(self, backup_path: str) -> None:
        """
        Create a backup of the database.

        Args:
            backup_path: Path where backup should be saved

        Raises:
            RepositoryError: If backup fails
        """
        pass

    @abstractmethod
    def get_table_info(self, timeframe: str) -> dict:
        """
        Get information about a specific table/timeframe.

        Args:
            timeframe: The timeframe to query

        Returns:
            Dictionary with table information:
            - record_count: int
            - size_mb: float
            - latest_record: Optional[datetime]
            - oldest_record: Optional[datetime]

        Raises:
            RepositoryError: If query fails
        """
        pass

    @abstractmethod
    def update_realtime_price(self, symbol: str, price: float) -> None:
        """
        Update the real-time price cache for a symbol.
        Hot-path method for sub-second updates.

        Args:
            symbol: Trading pair symbol
            price: Current market price
        """
        pass

    @abstractmethod
    def get_realtime_price(self, symbol: str) -> float:
        """
        Get the latest real-time price from cache.
        Returns 0.0 if not found.

        Args:
            symbol: Trading pair symbol
        """
        pass


class RepositoryError(Exception):
    """
    Exception raised for repository operation errors.

    This is a domain-level exception that wraps infrastructure-specific
    errors (e.g., database errors) to maintain clean architecture.
    """

    def __init__(self, message: str, original_error: Optional[Exception] = None):
        """
        Initialize repository error.

        Args:
            message: Error message
            original_error: The original exception that caused this error
        """
        super().__init__(message)
        self.original_error = original_error

    def __str__(self) -> str:
        """String representation of the error"""
        if self.original_error:
            return f"{super().__str__()} (caused by: {self.original_error})"
        return super().__str__()
