"""
Exchange Models - Domain Layer

Data models for exchange operations used by IExchangeService interface.
These models provide a unified representation of positions and orders
across different exchange implementations (paper/real).
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Position:
    """
    Represents an open trading position.

    Used by both PaperExchangeService and BinanceExchangeService
    to provide a consistent position representation.

    Attributes:
        symbol: Trading pair (e.g., 'BTCUSDT')
        side: Position direction ('LONG' or 'SHORT')
        size: Position size in base currency
        entry_price: Average entry price
        unrealized_pnl: Current unrealized profit/loss

    Example:
        position = Position(
            symbol='BTCUSDT',
            side='LONG',
            size=0.001,
            entry_price=95000.0,
            unrealized_pnl=50.0
        )
    """
    symbol: str
    side: str  # 'LONG' | 'SHORT'
    size: float
    entry_price: float
    unrealized_pnl: float = 0.0

    def __post_init__(self):
        """Validate position data."""
        if self.side not in ('LONG', 'SHORT'):
            raise ValueError(f"Invalid side: {self.side}. Must be 'LONG' or 'SHORT'")
        if self.size < 0:
            raise ValueError(f"Size must be non-negative: {self.size}")
        if self.entry_price <= 0:
            raise ValueError(f"Entry price must be positive: {self.entry_price}")

    @property
    def is_long(self) -> bool:
        """Check if position is long."""
        return self.side == 'LONG'

    @property
    def is_short(self) -> bool:
        """Check if position is short."""
        return self.side == 'SHORT'

    @property
    def notional_value(self) -> float:
        """Calculate notional value of position."""
        return self.size * self.entry_price


@dataclass
class OrderStatus:
    """
    Represents order status from exchange.

    Used to check order fill status during state recovery
    and position verification.

    Attributes:
        order_id: Unique order identifier
        status: Order status ('NEW', 'FILLED', 'CANCELED', 'REJECTED')
        filled_qty: Quantity that has been filled
        avg_price: Average fill price (None if not filled)

    Example:
        status = OrderStatus(
            order_id='12345',
            status='FILLED',
            filled_qty=0.001,
            avg_price=95000.0
        )
    """
    order_id: str
    status: str  # 'NEW' | 'FILLED' | 'CANCELED' | 'REJECTED'
    filled_qty: float
    avg_price: Optional[float] = None

    # Valid order statuses
    VALID_STATUSES = ('NEW', 'FILLED', 'CANCELED', 'REJECTED', 'PARTIALLY_FILLED')

    def __post_init__(self):
        """Validate order status data."""
        if self.status not in self.VALID_STATUSES:
            raise ValueError(
                f"Invalid status: {self.status}. "
                f"Must be one of {self.VALID_STATUSES}"
            )
        if self.filled_qty < 0:
            raise ValueError(f"Filled quantity must be non-negative: {self.filled_qty}")

    @property
    def is_filled(self) -> bool:
        """Check if order is fully filled."""
        return self.status == 'FILLED'

    @property
    def is_active(self) -> bool:
        """Check if order is still active (can be filled)."""
        return self.status in ('NEW', 'PARTIALLY_FILLED')

    @property
    def is_terminal(self) -> bool:
        """Check if order is in terminal state."""
        return self.status in ('FILLED', 'CANCELED', 'REJECTED')
