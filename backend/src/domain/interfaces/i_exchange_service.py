"""
IExchangeService Interface - Domain Layer

Abstract interface for exchange operations.
Enables switching between paper trading and live trading modes
without changing application logic.

This follows the Dependency Inversion Principle:
- Application layer depends on this interface
- Infrastructure layer provides concrete implementations
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict

from ..entities.exchange_models import Position, OrderStatus


class IExchangeService(ABC):
    """
    Abstract interface for exchange operations.

    This interface defines the contract for exchange services,
    allowing the application to work with both paper trading
    and real exchange implementations interchangeably.

    Implementations:
        - PaperExchangeService: Simulated trading using local database
        - BinanceExchangeService: Real trading via Binance API

    Usage:
        # Application code doesn't know which implementation is used
        exchange_service: IExchangeService = container.get_exchange_service()
        position = await exchange_service.get_position("BTCUSDT")
    """

    @abstractmethod
    async def get_position(self, symbol: str) -> Optional[Position]:
        """
        Get open position for a symbol.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')

        Returns:
            Position object if position exists, None otherwise

        Raises:
            ExchangeError: If API call fails (for real exchange)
        """
        pass

    @abstractmethod
    async def get_order_status(self, symbol: str, order_id: str) -> OrderStatus:
        """
        Get status of a specific order.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            order_id: Unique order identifier

        Returns:
            OrderStatus with current order state

        Raises:
            ExchangeError: If order not found or API fails
        """
        pass

    @abstractmethod
    async def get_exchange_type(self) -> str:
        """
        Get the type of exchange service.

        Returns:
            'paper' for paper trading, 'binance' for real exchange
        """
        pass

    @abstractmethod
    async def create_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        time_in_force: str = "GTC",
        reduce_only: bool = False
    ) -> Dict:
        """
        Create a new order.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            side: 'BUY' or 'SELL'
            order_type: 'LIMIT', 'MARKET', etc.
            quantity: Order quantity
            price: Limit price (required for LIMIT)
            stop_loss: Stop loss price (optional)
            take_profit: Take profit price (optional)
            time_in_force: Time in force policy
            reduce_only: Whether to only reduce position

        Returns:
            Dict containing order details
        """
        pass

    @abstractmethod
    async def cancel_order(self, symbol: str, order_id: str) -> Dict:
        """
        Cancel an existing order.

        Args:
            symbol: Trading pair
            order_id: Order ID to cancel

        Returns:
            Dict containing cancellation result
        """
        pass

    @abstractmethod
    async def get_balance(self, asset: str = "USDT") -> float:
        """
        Get available balance for an asset.

        Args:
            asset: Asset symbol (default: 'USDT')

        Returns:
            Available balance as float
        """
        pass

    @abstractmethod
    async def set_leverage(self, symbol: str, leverage: int) -> Dict:
        """
        Set leverage for a symbol.

        Args:
            symbol: Trading pair
            leverage: Leverage value (e.g. 10)

        Returns:
            Dict containing response
        """
        pass


class ExchangeError(Exception):
    """
    Exception raised for exchange operation errors.

    Attributes:
        message: Error description
        code: Optional error code from exchange
    """

    def __init__(self, message: str, code: Optional[str] = None):
        self.message = message
        self.code = code
        super().__init__(self.message)

    def __str__(self) -> str:
        if self.code:
            return f"[{self.code}] {self.message}"
        return self.message
