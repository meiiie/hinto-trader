"""
IStateRepository - Domain Layer

Abstract interface for state persistence.

This interface defines the contract for persisting and loading
trading state machine state for recovery after restart.
"""

from abc import ABC, abstractmethod
from typing import Optional

from ..entities.state_models import PersistedState
from ..state_machine import SystemState


class IStateRepository(ABC):
    """
    Interface for state persistence.

    Implementations:
    - SQLiteStateRepository: Persist to SQLite database
    - FileStateRepository: Persist to JSON file
    - RedisStateRepository: Persist to Redis (for distributed systems)
    """

    @abstractmethod
    def save_state(self, state: PersistedState) -> bool:
        """
        Persist current state.

        Args:
            state: PersistedState object to save

        Returns:
            True if saved successfully, False otherwise
        """
        pass

    @abstractmethod
    def load_state(self, symbol: str = "btcusdt") -> Optional[PersistedState]:
        """
        Load persisted state.

        Args:
            symbol: Trading symbol to load state for

        Returns:
            PersistedState if found, None otherwise
        """
        pass

    @abstractmethod
    def delete_state(self, symbol: str = "btcusdt") -> bool:
        """
        Delete persisted state.

        Args:
            symbol: Trading symbol to delete state for

        Returns:
            True if deleted successfully, False otherwise
        """
        pass

    @abstractmethod
    def has_state(self, symbol: str = "btcusdt") -> bool:
        """
        Check if state exists for symbol.

        Args:
            symbol: Trading symbol to check

        Returns:
            True if state exists, False otherwise
        """
        pass
