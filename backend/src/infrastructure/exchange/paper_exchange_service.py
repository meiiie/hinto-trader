"""
PaperExchangeService - Infrastructure Layer

Paper trading implementation of IExchangeService.
Simulates exchange operations using local database.

This service allows StateRecoveryService to verify positions
during paper trading mode, maintaining consistent behavior
with real trading.
"""

import logging
from typing import Optional

from ...domain.interfaces.i_exchange_service import IExchangeService, ExchangeError
from ...domain.entities.exchange_models import Position, OrderStatus
from ...domain.repositories.i_order_repository import IOrderRepository


class PaperExchangeService(IExchangeService):
    """
    Paper trading implementation of IExchangeService.

    Uses local database (via IOrderRepository) to simulate
    exchange operations. This enables position verification
    during state recovery without calling real exchange APIs.

    Usage:
        order_repo = SQLiteOrderRepository(db_path)
        paper_service = PaperExchangeService(order_repo)

        position = await paper_service.get_position("BTCUSDT")
        if position:
            print(f"Open position: {position.side} {position.size}")
    """

    def __init__(self, order_repository: IOrderRepository):
        """
        Initialize PaperExchangeService.

        Args:
            order_repository: Repository for accessing paper trading orders
        """
        self._order_repository = order_repository
        self.logger = logging.getLogger(__name__)

    async def get_position(self, symbol: str) -> Optional[Position]:
        """
        Get open position for symbol from local database.

        Queries the order repository for active (OPEN) positions
        and converts to Position entity.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')

        Returns:
            Position if found, None otherwise
        """
        try:
            # Get all active orders from database
            active_orders = self._order_repository.get_active_orders()

            # Filter by symbol (case-insensitive)
            symbol_upper = symbol.upper()
            matching_orders = [
                order for order in active_orders
                if order.symbol.upper() == symbol_upper and order.status == 'OPEN'
            ]

            if not matching_orders:
                self.logger.debug(f"No open position found for {symbol}")
                return None

            # Take the most recent open position
            # (In practice, there should only be one per symbol)
            paper_position = matching_orders[0]

            # Convert PaperPosition to Position entity
            position = Position(
                symbol=paper_position.symbol,
                side=paper_position.side,
                size=paper_position.quantity,
                entry_price=paper_position.entry_price,
                unrealized_pnl=0.0  # Will be calculated with current price
            )

            self.logger.debug(
                f"Found paper position: {position.side} {position.size} @ {position.entry_price}"
            )
            return position

        except Exception as e:
            self.logger.error(f"Error getting paper position: {e}")
            raise ExchangeError(f"Failed to get paper position: {e}")

    async def get_order_status(self, symbol: str, order_id: str) -> OrderStatus:
        """
        Get status of a specific order from local database.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            order_id: Unique order identifier

        Returns:
            OrderStatus with current order state

        Raises:
            ExchangeError: If order not found
        """
        try:
            order = self._order_repository.get_order(order_id)

            if not order:
                raise ExchangeError(f"Order {order_id} not found", code="ORDER_NOT_FOUND")

            # Map PaperPosition status to OrderStatus
            # PaperPosition uses: 'OPEN', 'CLOSED', 'PENDING'
            # OrderStatus uses: 'NEW', 'FILLED', 'CANCELED', 'REJECTED'
            status_map = {
                'OPEN': 'FILLED',      # Open position means order was filled
                'CLOSED': 'FILLED',    # Closed position was also filled
                'PENDING': 'NEW',      # Pending order is still new
            }

            mapped_status = status_map.get(order.status, 'FILLED')

            return OrderStatus(
                order_id=order_id,
                status=mapped_status,
                filled_qty=order.quantity if mapped_status == 'FILLED' else 0.0,
                avg_price=order.entry_price if mapped_status == 'FILLED' else None
            )

        except ExchangeError:
            raise
        except Exception as e:
            self.logger.error(f"Error getting order status: {e}")
            raise ExchangeError(f"Failed to get order status: {e}")

    def get_exchange_type(self) -> str:
        """
        Get the type of exchange service.

        Returns:
            'paper' to indicate paper trading mode
        """
        return "paper"

    def __repr__(self) -> str:
        return f"PaperExchangeService(repository={self._order_repository})"
