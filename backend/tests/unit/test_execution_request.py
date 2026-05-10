"""
Unit Tests for ExecutionRequest Data Model

Tests:
- Priority ordering (SL < TP < Entry)
- FIFO within same priority
- __lt__ comparison
- Dataclass field defaults

Validates: Property 1, Property 2
"""

import pytest
from datetime import datetime, timedelta
from src.domain.entities.execution_request import (
    ExecutionRequest,
    ExecutionPriority,
    ExecutionType
)


class TestExecutionPriority:
    """Test ExecutionPriority enum values."""

    def test_priority_values(self):
        """SL=0, TP=1, Entry=2 (lower = higher priority)."""
        assert ExecutionPriority.STOP_LOSS == 0
        assert ExecutionPriority.TAKE_PROFIT == 1
        assert ExecutionPriority.ENTRY == 2

    def test_priority_ordering(self):
        """SL < TP < Entry in numeric comparison."""
        assert ExecutionPriority.STOP_LOSS < ExecutionPriority.TAKE_PROFIT
        assert ExecutionPriority.TAKE_PROFIT < ExecutionPriority.ENTRY
        assert ExecutionPriority.STOP_LOSS < ExecutionPriority.ENTRY


class TestExecutionType:
    """Test ExecutionType enum values."""

    def test_execution_types(self):
        """All execution types are defined."""
        assert ExecutionType.STOP_LOSS.value == "stop_loss"
        assert ExecutionType.TAKE_PROFIT_PARTIAL.value == "take_profit_partial"
        assert ExecutionType.TAKE_PROFIT_FULL.value == "take_profit_full"
        assert ExecutionType.ENTRY.value == "entry"
        assert ExecutionType.CLOSE_POSITION.value == "close_position"


class TestExecutionRequestCreation:
    """Test ExecutionRequest dataclass creation."""

    def test_create_sl_request(self):
        """Create a stop loss request."""
        now = datetime.now()
        request = ExecutionRequest(
            priority=ExecutionPriority.STOP_LOSS,
            created_at=now,
            symbol="BTCUSDT",
            execution_type=ExecutionType.STOP_LOSS,
            side="SELL",
            quantity=0.001,
            price=50000.0
        )

        assert request.priority == 0
        assert request.symbol == "BTCUSDT"
        assert request.execution_type == ExecutionType.STOP_LOSS
        assert request.side == "SELL"
        assert request.quantity == 0.001
        assert request.price == 50000.0
        assert request.retry_count == 0
        assert request.request_id is not None

    def test_create_tp_request(self):
        """Create a take profit request."""
        request = ExecutionRequest(
            priority=ExecutionPriority.TAKE_PROFIT,
            created_at=datetime.now(),
            symbol="ethusdt",  # lowercase should be normalized
            execution_type=ExecutionType.TAKE_PROFIT_PARTIAL,
            side="sell",  # lowercase should be normalized
            quantity=0.5,
            price=3000.0
        )

        assert request.priority == 1
        assert request.symbol == "ETHUSDT"  # normalized to uppercase
        assert request.side == "SELL"  # normalized to uppercase

    def test_default_values(self):
        """Test default field values."""
        request = ExecutionRequest(
            priority=ExecutionPriority.ENTRY,
            created_at=datetime.now(),
            symbol="BTCUSDT",
            execution_type=ExecutionType.ENTRY,
            side="BUY",
            quantity=0.001,
            price=50000.0
        )

        assert request.position_entry_price == 0.0
        assert request.retry_count == 0
        assert len(request.request_id) == 36  # UUID format

    def test_timestamp_conversion(self):
        """Test float timestamp conversion to datetime."""
        timestamp = datetime.now().timestamp()
        request = ExecutionRequest(
            priority=ExecutionPriority.STOP_LOSS,
            created_at=timestamp,  # float timestamp
            symbol="BTCUSDT",
            execution_type=ExecutionType.STOP_LOSS,
            side="SELL",
            quantity=0.001,
            price=50000.0
        )

        assert isinstance(request.created_at, datetime)


class TestExecutionRequestComparison:
    """Test __lt__ comparison for PriorityQueue ordering."""

    def test_priority_comparison_sl_before_tp(self):
        """SL request should be processed before TP request."""
        now = datetime.now()
        sl_request = ExecutionRequest(
            priority=ExecutionPriority.STOP_LOSS,
            created_at=now,
            symbol="BTCUSDT",
            execution_type=ExecutionType.STOP_LOSS,
            side="SELL",
            quantity=0.001,
            price=50000.0
        )
        tp_request = ExecutionRequest(
            priority=ExecutionPriority.TAKE_PROFIT,
            created_at=now,
            symbol="BTCUSDT",
            execution_type=ExecutionType.TAKE_PROFIT_PARTIAL,
            side="SELL",
            quantity=0.001,
            price=55000.0
        )

        assert sl_request < tp_request
        assert not tp_request < sl_request

    def test_priority_comparison_tp_before_entry(self):
        """TP request should be processed before Entry request."""
        now = datetime.now()
        tp_request = ExecutionRequest(
            priority=ExecutionPriority.TAKE_PROFIT,
            created_at=now,
            symbol="BTCUSDT",
            execution_type=ExecutionType.TAKE_PROFIT_PARTIAL,
            side="SELL",
            quantity=0.001,
            price=55000.0
        )
        entry_request = ExecutionRequest(
            priority=ExecutionPriority.ENTRY,
            created_at=now,
            symbol="ETHUSDT",
            execution_type=ExecutionType.ENTRY,
            side="BUY",
            quantity=0.5,
            price=3000.0
        )

        assert tp_request < entry_request
        assert not entry_request < tp_request

    def test_fifo_within_same_priority(self):
        """Earlier request should be processed first within same priority."""
        earlier = datetime.now()
        later = earlier + timedelta(milliseconds=100)

        first_request = ExecutionRequest(
            priority=ExecutionPriority.STOP_LOSS,
            created_at=earlier,
            symbol="BTCUSDT",
            execution_type=ExecutionType.STOP_LOSS,
            side="SELL",
            quantity=0.001,
            price=50000.0
        )
        second_request = ExecutionRequest(
            priority=ExecutionPriority.STOP_LOSS,
            created_at=later,
            symbol="ETHUSDT",
            execution_type=ExecutionType.STOP_LOSS,
            side="SELL",
            quantity=0.5,
            price=3000.0
        )

        assert first_request < second_request
        assert not second_request < first_request

    def test_priority_takes_precedence_over_time(self):
        """Priority should take precedence over creation time."""
        earlier = datetime.now()
        later = earlier + timedelta(seconds=10)

        # TP created earlier
        tp_request = ExecutionRequest(
            priority=ExecutionPriority.TAKE_PROFIT,
            created_at=earlier,
            symbol="BTCUSDT",
            execution_type=ExecutionType.TAKE_PROFIT_PARTIAL,
            side="SELL",
            quantity=0.001,
            price=55000.0
        )
        # SL created later
        sl_request = ExecutionRequest(
            priority=ExecutionPriority.STOP_LOSS,
            created_at=later,
            symbol="BTCUSDT",
            execution_type=ExecutionType.STOP_LOSS,
            side="SELL",
            quantity=0.001,
            price=50000.0
        )

        # SL should still be processed first despite being created later
        assert sl_request < tp_request


class TestExecutionRequestHelpers:
    """Test helper methods and properties."""

    def test_is_stop_loss(self):
        """Test is_stop_loss property."""
        sl_request = ExecutionRequest(
            priority=ExecutionPriority.STOP_LOSS,
            created_at=datetime.now(),
            symbol="BTCUSDT",
            execution_type=ExecutionType.STOP_LOSS,
            side="SELL",
            quantity=0.001,
            price=50000.0
        )
        tp_request = ExecutionRequest(
            priority=ExecutionPriority.TAKE_PROFIT,
            created_at=datetime.now(),
            symbol="BTCUSDT",
            execution_type=ExecutionType.TAKE_PROFIT_PARTIAL,
            side="SELL",
            quantity=0.001,
            price=55000.0
        )

        assert sl_request.is_stop_loss is True
        assert tp_request.is_stop_loss is False

    def test_is_take_profit(self):
        """Test is_take_profit property."""
        sl_request = ExecutionRequest(
            priority=ExecutionPriority.STOP_LOSS,
            created_at=datetime.now(),
            symbol="BTCUSDT",
            execution_type=ExecutionType.STOP_LOSS,
            side="SELL",
            quantity=0.001,
            price=50000.0
        )
        tp_request = ExecutionRequest(
            priority=ExecutionPriority.TAKE_PROFIT,
            created_at=datetime.now(),
            symbol="BTCUSDT",
            execution_type=ExecutionType.TAKE_PROFIT_PARTIAL,
            side="SELL",
            quantity=0.001,
            price=55000.0
        )

        assert sl_request.is_take_profit is False
        assert tp_request.is_take_profit is True

    def test_age_ms(self):
        """Test age_ms property."""
        old_time = datetime.now() - timedelta(milliseconds=500)
        request = ExecutionRequest(
            priority=ExecutionPriority.STOP_LOSS,
            created_at=old_time,
            symbol="BTCUSDT",
            execution_type=ExecutionType.STOP_LOSS,
            side="SELL",
            quantity=0.001,
            price=50000.0
        )

        # Age should be approximately 500ms (with some tolerance)
        assert request.age_ms >= 500
        assert request.age_ms < 1000

    def test_increment_retry(self):
        """Test increment_retry method."""
        request = ExecutionRequest(
            priority=ExecutionPriority.STOP_LOSS,
            created_at=datetime.now(),
            symbol="BTCUSDT",
            execution_type=ExecutionType.STOP_LOSS,
            side="SELL",
            quantity=0.001,
            price=50000.0,
            retry_count=0
        )

        new_request = request.increment_retry()

        assert new_request.retry_count == 1
        assert new_request.symbol == request.symbol
        assert new_request.request_id == request.request_id
        assert request.retry_count == 0  # Original unchanged

    def test_repr(self):
        """Test string representation."""
        request = ExecutionRequest(
            priority=ExecutionPriority.STOP_LOSS,
            created_at=datetime.now(),
            symbol="BTCUSDT",
            execution_type=ExecutionType.STOP_LOSS,
            side="SELL",
            quantity=0.001,
            price=50000.0
        )

        repr_str = repr(request)
        assert "BTCUSDT" in repr_str
        assert "stop_loss" in repr_str
        assert "SELL" in repr_str


class TestExecutionRequestSorting:
    """Test sorting behavior for PriorityQueue simulation."""

    def test_sort_mixed_priorities(self):
        """Test sorting a list of mixed priority requests."""
        now = datetime.now()

        requests = [
            ExecutionRequest(
                priority=ExecutionPriority.ENTRY,
                created_at=now,
                symbol="BTCUSDT",
                execution_type=ExecutionType.ENTRY,
                side="BUY",
                quantity=0.001,
                price=50000.0
            ),
            ExecutionRequest(
                priority=ExecutionPriority.STOP_LOSS,
                created_at=now + timedelta(milliseconds=100),
                symbol="ETHUSDT",
                execution_type=ExecutionType.STOP_LOSS,
                side="SELL",
                quantity=0.5,
                price=3000.0
            ),
            ExecutionRequest(
                priority=ExecutionPriority.TAKE_PROFIT,
                created_at=now + timedelta(milliseconds=50),
                symbol="BTCUSDT",
                execution_type=ExecutionType.TAKE_PROFIT_PARTIAL,
                side="SELL",
                quantity=0.001,
                price=55000.0
            ),
        ]

        sorted_requests = sorted(requests)

        # SL should be first (priority 0)
        assert sorted_requests[0].execution_type == ExecutionType.STOP_LOSS
        # TP should be second (priority 1)
        assert sorted_requests[1].execution_type == ExecutionType.TAKE_PROFIT_PARTIAL
        # Entry should be last (priority 2)
        assert sorted_requests[2].execution_type == ExecutionType.ENTRY

    def test_sort_same_priority_fifo(self):
        """Test FIFO ordering within same priority."""
        base_time = datetime.now()

        requests = [
            ExecutionRequest(
                priority=ExecutionPriority.STOP_LOSS,
                created_at=base_time + timedelta(milliseconds=200),
                symbol="SOLUSDT",
                execution_type=ExecutionType.STOP_LOSS,
                side="SELL",
                quantity=1.0,
                price=100.0
            ),
            ExecutionRequest(
                priority=ExecutionPriority.STOP_LOSS,
                created_at=base_time,
                symbol="BTCUSDT",
                execution_type=ExecutionType.STOP_LOSS,
                side="SELL",
                quantity=0.001,
                price=50000.0
            ),
            ExecutionRequest(
                priority=ExecutionPriority.STOP_LOSS,
                created_at=base_time + timedelta(milliseconds=100),
                symbol="ETHUSDT",
                execution_type=ExecutionType.STOP_LOSS,
                side="SELL",
                quantity=0.5,
                price=3000.0
            ),
        ]

        sorted_requests = sorted(requests)

        # Should be sorted by created_at (FIFO)
        assert sorted_requests[0].symbol == "BTCUSDT"
        assert sorted_requests[1].symbol == "ETHUSDT"
        assert sorted_requests[2].symbol == "SOLUSDT"
