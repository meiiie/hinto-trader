"""
Signal Repository Interface - Domain Layer

Abstract interface for signal persistence.
Follows Repository pattern from Clean Architecture.
"""

from abc import ABC, abstractmethod
from typing import List, Optional
from datetime import datetime

from ..entities.trading_signal import TradingSignal
from ..value_objects.signal_status import SignalStatus


class ISignalRepository(ABC):
    """
    Interface for signal persistence.

    Implementations should handle:
    - Signal storage (create/update)
    - Signal retrieval (by id, status, order_id)
    - Historical queries with pagination
    - Expiration of stale signals
    """

    @abstractmethod
    def save(self, signal: TradingSignal) -> None:
        """
        Persist a new signal.

        Args:
            signal: Signal to save
        """
        pass

    @abstractmethod
    def update(self, signal: TradingSignal) -> None:
        """
        Update an existing signal.

        Args:
            signal: Signal with updated fields
        """
        pass

    @abstractmethod
    def get_by_id(self, signal_id: str) -> Optional[TradingSignal]:
        """
        Get signal by ID.

        Args:
            signal_id: UUID of the signal

        Returns:
            TradingSignal if found, None otherwise
        """
        pass

    @abstractmethod
    def get_by_status(
        self,
        status: SignalStatus,
        limit: int = 50
    ) -> List[TradingSignal]:
        """
        Get signals by status.

        Args:
            status: Status to filter by
            limit: Maximum number of results

        Returns:
            List of matching signals
        """
        pass

    @abstractmethod
    def get_by_order_id(self, order_id: str) -> Optional[TradingSignal]:
        """
        Get signal linked to an order.

        Args:
            order_id: UUID of the order

        Returns:
            TradingSignal if found, None otherwise
        """
        pass

    @abstractmethod
    def get_history(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[TradingSignal]:
        """
        Get signal history with pagination.

        Args:
            start_date: Filter signals after this date
            end_date: Filter signals before this date
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of signals matching criteria
        """
        pass

    @abstractmethod
    def get_pending_count(self) -> int:
        """
        Count pending signals.

        Returns:
            Number of signals in PENDING status
        """
        pass

    @abstractmethod
    def expire_old_pending(self, ttl_seconds: int = 300) -> int:
        """
        Expire pending signals older than TTL.

        Args:
            ttl_seconds: Time-to-live in seconds

        Returns:
            Number of signals expired
        """
        pass

    @abstractmethod
    def get_total_count(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> int:
        """
        Get total count of signals for pagination.

        Args:
            start_date: Filter signals after this date
            end_date: Filter signals before this date

        Returns:
            Total count of matching signals
        """
        pass
