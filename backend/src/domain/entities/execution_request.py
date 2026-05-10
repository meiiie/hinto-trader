"""
ExecutionRequest - SOTA Priority Execution Queue Data Model

Pattern: NautilusTrader, Two Sigma, Citadel
Defines execution requests for priority-based order processing.

Features:
- Priority ordering (SL > TP > Entry)
- FIFO within same priority
- Dataclass with comparison for PriorityQueue
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum, Enum
from typing import Optional


class ExecutionPriority(IntEnum):
    """
    Priority levels for execution queue.

    Lower number = higher priority.
    SL is highest priority for risk management.
    """
    STOP_LOSS = 0      # Highest priority - risk management
    TAKE_PROFIT = 1    # Second priority - profit taking
    ENTRY = 2          # Lowest priority - new positions


class ExecutionType(Enum):
    """Type of execution request."""
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT_PARTIAL = "take_profit_partial"  # 60% close at TP1
    TAKE_PROFIT_FULL = "take_profit_full"        # Full close
    ENTRY = "entry"
    CLOSE_POSITION = "close_position"


@dataclass
class ExecutionRequest:
    """
    Request for order execution via priority queue.

    SOTA Pattern (Jan 2026):
    - Implements comparison for asyncio.PriorityQueue ordering
    - Lower priority number = higher priority (processed first)
    - FIFO within same priority level (by created_at)

    Usage:
        request = ExecutionRequest(
            priority=ExecutionPriority.STOP_LOSS,
            created_at=datetime.now(),
            symbol="BTCUSDT",
            execution_type=ExecutionType.STOP_LOSS,
            side="SELL",
            quantity=0.001,
            price=50000.0
        )
        await queue.put(request)
    """
    # Comparison fields (used for PriorityQueue ordering)
    priority: int
    created_at: datetime

    # Non-comparison fields (execution details)
    symbol: str
    execution_type: ExecutionType
    side: str  # 'BUY' or 'SELL'
    quantity: float
    price: float  # Trigger price (for logging)

    # Optional fields with defaults
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    position_entry_price: float = field(default=0.0)
    retry_count: int = field(default=0)

    def __post_init__(self):
        """Validate and normalize fields after initialization."""
        # Convert float timestamp to datetime if needed
        if isinstance(self.created_at, (int, float)):
            self.created_at = datetime.fromtimestamp(self.created_at)

        # Ensure priority is int (in case ExecutionPriority enum passed)
        if isinstance(self.priority, ExecutionPriority):
            self.priority = int(self.priority)

        # Normalize symbol to uppercase
        self.symbol = self.symbol.upper()

        # Normalize side to uppercase
        self.side = self.side.upper()

    def __lt__(self, other: 'ExecutionRequest') -> bool:
        """
        Compare for PriorityQueue ordering.

        Priority order:
        1. Lower priority number first (SL=0 before TP=1)
        2. Earlier created_at first (FIFO within same priority)
        """
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.created_at < other.created_at

    def increment_retry(self) -> 'ExecutionRequest':
        """Return new request with incremented retry count."""
        return ExecutionRequest(
            priority=self.priority,
            created_at=self.created_at,
            symbol=self.symbol,
            execution_type=self.execution_type,
            side=self.side,
            quantity=self.quantity,
            price=self.price,
            request_id=self.request_id,
            position_entry_price=self.position_entry_price,
            retry_count=self.retry_count + 1
        )

    @property
    def is_stop_loss(self) -> bool:
        """Check if this is a stop loss request."""
        return self.priority == ExecutionPriority.STOP_LOSS

    @property
    def is_take_profit(self) -> bool:
        """Check if this is a take profit request."""
        return self.priority == ExecutionPriority.TAKE_PROFIT

    @property
    def age_ms(self) -> float:
        """Get age of request in milliseconds."""
        return (datetime.now() - self.created_at).total_seconds() * 1000

    def __repr__(self) -> str:
        return (
            f"ExecutionRequest("
            f"symbol={self.symbol}, "
            f"type={self.execution_type.value}, "
            f"priority={self.priority}, "
            f"side={self.side}, "
            f"qty={self.quantity:.6f}, "
            f"price={self.price:.4f}, "
            f"retry={self.retry_count})"
        )
