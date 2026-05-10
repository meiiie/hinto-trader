from abc import ABC, abstractmethod
from typing import List, Optional, Tuple
from src.domain.entities.paper_position import PaperPosition

class IOrderRepository(ABC):
    """Interface for Order/Position Repository"""

    @abstractmethod
    def save_order(self, position: PaperPosition) -> None:
        pass

    @abstractmethod
    def update_order(self, position: PaperPosition) -> None:
        pass

    @abstractmethod
    def get_order(self, position_id: str) -> Optional[PaperPosition]:
        pass

    @abstractmethod
    def get_active_orders(self) -> List[PaperPosition]:
        pass

    @abstractmethod
    def get_pending_orders(self) -> List[PaperPosition]:
        """Get all pending orders (PENDING)"""
        pass

    @abstractmethod
    def get_closed_orders(self, limit: int = 50) -> List[PaperPosition]:
        pass

    @abstractmethod
    def get_closed_orders_paginated(
        self, page: int, limit: int,
        symbol: Optional[str] = None,
        side: Optional[str] = None,
        pnl_filter: Optional[str] = None
    ) -> Tuple[List[PaperPosition], int]:
        """Get closed orders with pagination and optional filters. Returns (orders, total_count)"""
        pass

    @abstractmethod
    def get_account_balance(self) -> float:
        pass

    @abstractmethod
    def update_account_balance(self, balance: float) -> None:
        pass

    @abstractmethod
    def reset_database(self) -> None:
        """Reset database to initial state"""
        pass

    # Settings methods
    @abstractmethod
    def get_setting(self, key: str) -> Optional[str]:
        """Get a setting value by key"""
        pass

    @abstractmethod
    def set_setting(self, key: str, value: str) -> None:
        """Set a setting value"""
        pass

    @abstractmethod
    def get_all_settings(self) -> dict:
        """Get all settings as a dictionary"""
        pass
