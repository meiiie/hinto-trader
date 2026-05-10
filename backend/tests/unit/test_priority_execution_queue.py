"""
Unit Tests for PriorityExecutionQueue

Tests:
- Enqueue/dequeue ordering
- Duplicate rejection
- is_symbol_pending()
- stop_accepting() behavior
- Metrics tracking
- Concurrent producers (thread-safety)

Validates: REQ-2.1, REQ-2.2, REQ-2.4, REQ-2.5, Property 3
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from src.infrastructure.execution.priority_execution_queue import PriorityExecutionQueue
from src.domain.entities.execution_request import (
    ExecutionRequest,
    ExecutionPriority,
    ExecutionType
)


def create_request(
    symbol: str = "BTCUSDT",
    priority: ExecutionPriority = ExecutionPriority.STOP_LOSS,
    execution_type: ExecutionType = ExecutionType.STOP_LOSS,
    created_at: datetime = None
) -> ExecutionRequest:
    """Helper to create test requests."""
    return ExecutionRequest(
        priority=priority,
        created_at=created_at or datetime.now(),
        symbol=symbol,
        execution_type=execution_type,
        side="SELL",
        quantity=0.001,
        price=50000.0
    )


class TestPriorityExecutionQueueCreation:
    """Test queue initialization."""

    def test_create_queue(self):
        """Create queue with default size."""
        queue = PriorityExecutionQueue()

        assert queue.size == 0
        assert queue.is_empty is True
        assert queue.is_full is False
        assert queue.is_accepting is True

    def test_create_queue_with_custom_size(self):
        """Create queue with custom max size."""
        queue = PriorityExecutionQueue(max_size=10)

        assert queue._max_size == 10


class TestEnqueueDequeue:
    """Test enqueue and dequeue operations."""

    @pytest.mark.asyncio
    async def test_enqueue_single_request(self):
        """Enqueue a single request."""
        queue = PriorityExecutionQueue()
        request = create_request()

        success = await queue.enqueue(request)

        assert success is True
        assert queue.size == 1
        assert queue.is_empty is False

    @pytest.mark.asyncio
    async def test_dequeue_single_request(self):
        """Dequeue a single request."""
        queue = PriorityExecutionQueue()
        request = create_request()
        await queue.enqueue(request)

        dequeued = await queue.dequeue()

        assert dequeued.symbol == request.symbol
        assert queue.size == 0
        assert queue.is_empty is True

    @pytest.mark.asyncio
    async def test_priority_ordering_sl_before_tp(self):
        """SL should be dequeued before TP."""
        queue = PriorityExecutionQueue()
        now = datetime.now()

        # Enqueue TP first
        tp_request = create_request(
            symbol="BTCUSDT",
            priority=ExecutionPriority.TAKE_PROFIT,
            execution_type=ExecutionType.TAKE_PROFIT_PARTIAL,
            created_at=now
        )
        await queue.enqueue(tp_request)

        # Enqueue SL second
        sl_request = create_request(
            symbol="ETHUSDT",
            priority=ExecutionPriority.STOP_LOSS,
            execution_type=ExecutionType.STOP_LOSS,
            created_at=now + timedelta(milliseconds=100)
        )
        await queue.enqueue(sl_request)

        # SL should come out first despite being enqueued second
        first = await queue.dequeue()
        second = await queue.dequeue()

        assert first.symbol == "ETHUSDT"  # SL
        assert second.symbol == "BTCUSDT"  # TP

    @pytest.mark.asyncio
    async def test_fifo_within_same_priority(self):
        """Earlier requests should be dequeued first within same priority."""
        queue = PriorityExecutionQueue()
        base_time = datetime.now()

        # Enqueue in reverse order
        for i in [3, 1, 2]:
            request = create_request(
                symbol=f"SYMBOL{i}",
                priority=ExecutionPriority.STOP_LOSS,
                execution_type=ExecutionType.STOP_LOSS,
                created_at=base_time + timedelta(milliseconds=i * 100)
            )
            await queue.enqueue(request)

        # Should come out in FIFO order
        first = await queue.dequeue()
        second = await queue.dequeue()
        third = await queue.dequeue()

        assert first.symbol == "SYMBOL1"
        assert second.symbol == "SYMBOL2"
        assert third.symbol == "SYMBOL3"


class TestDuplicateRejection:
    """Test duplicate request rejection (Property 3)."""

    @pytest.mark.asyncio
    async def test_reject_duplicate_symbol_type(self):
        """Reject duplicate request for same symbol and type."""
        queue = PriorityExecutionQueue()

        request1 = create_request(symbol="BTCUSDT")
        request2 = create_request(symbol="BTCUSDT")  # Same symbol and type

        success1 = await queue.enqueue(request1)
        success2 = await queue.enqueue(request2)

        assert success1 is True
        assert success2 is False
        assert queue.size == 1

    @pytest.mark.asyncio
    async def test_allow_same_symbol_different_type(self):
        """Allow same symbol with different execution type."""
        queue = PriorityExecutionQueue()

        sl_request = create_request(
            symbol="BTCUSDT",
            priority=ExecutionPriority.STOP_LOSS,
            execution_type=ExecutionType.STOP_LOSS
        )
        tp_request = create_request(
            symbol="BTCUSDT",
            priority=ExecutionPriority.TAKE_PROFIT,
            execution_type=ExecutionType.TAKE_PROFIT_PARTIAL
        )

        success1 = await queue.enqueue(sl_request)
        success2 = await queue.enqueue(tp_request)

        assert success1 is True
        assert success2 is True
        assert queue.size == 2

    @pytest.mark.asyncio
    async def test_allow_different_symbol_same_type(self):
        """Allow different symbols with same execution type."""
        queue = PriorityExecutionQueue()

        request1 = create_request(symbol="BTCUSDT")
        request2 = create_request(symbol="ETHUSDT")

        success1 = await queue.enqueue(request1)
        success2 = await queue.enqueue(request2)

        assert success1 is True
        assert success2 is True
        assert queue.size == 2

    @pytest.mark.asyncio
    async def test_allow_requeue_after_dequeue(self):
        """Allow re-enqueue after request is dequeued."""
        queue = PriorityExecutionQueue()

        request = create_request(symbol="BTCUSDT")

        await queue.enqueue(request)
        await queue.dequeue()

        # Should be able to enqueue again
        success = await queue.enqueue(request)
        assert success is True


class TestSymbolPending:
    """Test is_symbol_pending functionality."""

    @pytest.mark.asyncio
    async def test_symbol_pending_after_enqueue(self):
        """Symbol should be pending after enqueue."""
        queue = PriorityExecutionQueue()
        request = create_request(symbol="BTCUSDT")

        await queue.enqueue(request)

        assert queue.is_symbol_pending("BTCUSDT") is True
        assert queue.is_symbol_pending("ETHUSDT") is False

    @pytest.mark.asyncio
    async def test_symbol_not_pending_after_dequeue(self):
        """Symbol should not be pending after dequeue."""
        queue = PriorityExecutionQueue()
        request = create_request(symbol="BTCUSDT")

        await queue.enqueue(request)
        await queue.dequeue()

        assert queue.is_symbol_pending("BTCUSDT") is False

    @pytest.mark.asyncio
    async def test_is_pending_specific_type(self):
        """Test is_pending with specific execution type."""
        queue = PriorityExecutionQueue()

        sl_request = create_request(
            symbol="BTCUSDT",
            execution_type=ExecutionType.STOP_LOSS
        )
        await queue.enqueue(sl_request)

        assert queue.is_pending("BTCUSDT", ExecutionType.STOP_LOSS) is True
        assert queue.is_pending("BTCUSDT", ExecutionType.TAKE_PROFIT_PARTIAL) is False


class TestStopAccepting:
    """Test graceful shutdown via stop_accepting."""

    @pytest.mark.asyncio
    async def test_stop_accepting_rejects_new_requests(self):
        """Queue should reject new requests after stop_accepting."""
        queue = PriorityExecutionQueue()

        queue.stop_accepting()

        request = create_request()
        success = await queue.enqueue(request)

        assert success is False
        assert queue.is_accepting is False

    @pytest.mark.asyncio
    async def test_existing_items_remain_after_stop(self):
        """Existing items should remain in queue after stop_accepting."""
        queue = PriorityExecutionQueue()
        request = create_request()

        await queue.enqueue(request)
        queue.stop_accepting()

        assert queue.size == 1

        # Should still be able to dequeue
        dequeued = await queue.dequeue()
        assert dequeued.symbol == request.symbol

    @pytest.mark.asyncio
    async def test_resume_accepting(self):
        """Queue should accept requests after resume_accepting."""
        queue = PriorityExecutionQueue()

        queue.stop_accepting()
        queue.resume_accepting()

        request = create_request()
        success = await queue.enqueue(request)

        assert success is True
        assert queue.is_accepting is True


class TestMetrics:
    """Test metrics tracking."""

    @pytest.mark.asyncio
    async def test_initial_metrics(self):
        """Initial metrics should be zero."""
        queue = PriorityExecutionQueue()
        metrics = queue.get_metrics()

        assert metrics['total_enqueued'] == 0
        assert metrics['total_processed'] == 0
        assert metrics['duplicates_rejected'] == 0
        assert metrics['sl_count'] == 0
        assert metrics['tp_count'] == 0
        assert metrics['entry_count'] == 0

    @pytest.mark.asyncio
    async def test_enqueue_updates_metrics(self):
        """Enqueue should update metrics."""
        queue = PriorityExecutionQueue()

        sl_request = create_request(
            priority=ExecutionPriority.STOP_LOSS,
            execution_type=ExecutionType.STOP_LOSS
        )
        tp_request = create_request(
            symbol="ETHUSDT",
            priority=ExecutionPriority.TAKE_PROFIT,
            execution_type=ExecutionType.TAKE_PROFIT_PARTIAL
        )

        await queue.enqueue(sl_request)
        await queue.enqueue(tp_request)

        metrics = queue.get_metrics()
        assert metrics['total_enqueued'] == 2
        assert metrics['sl_count'] == 1
        assert metrics['tp_count'] == 1

    @pytest.mark.asyncio
    async def test_dequeue_updates_metrics(self):
        """Dequeue should update processed count."""
        queue = PriorityExecutionQueue()
        request = create_request()

        await queue.enqueue(request)
        await queue.dequeue()

        metrics = queue.get_metrics()
        assert metrics['total_processed'] == 1

    @pytest.mark.asyncio
    async def test_duplicate_rejection_updates_metrics(self):
        """Duplicate rejection should update metrics."""
        queue = PriorityExecutionQueue()

        request1 = create_request()
        request2 = create_request()  # Duplicate

        await queue.enqueue(request1)
        await queue.enqueue(request2)

        metrics = queue.get_metrics()
        assert metrics['duplicates_rejected'] == 1

    @pytest.mark.asyncio
    async def test_metrics_include_current_size(self):
        """Metrics should include current queue size."""
        queue = PriorityExecutionQueue()

        await queue.enqueue(create_request(symbol="BTC"))
        await queue.enqueue(create_request(symbol="ETH"))

        metrics = queue.get_metrics()
        assert metrics['current_size'] == 2

    @pytest.mark.asyncio
    async def test_metrics_include_pending_symbols(self):
        """Metrics should include list of pending symbols."""
        queue = PriorityExecutionQueue()

        await queue.enqueue(create_request(symbol="BTCUSDT"))
        await queue.enqueue(create_request(symbol="ETHUSDT"))

        metrics = queue.get_metrics()
        assert "BTCUSDT" in metrics['pending_symbols']
        assert "ETHUSDT" in metrics['pending_symbols']


class TestConcurrentProducers:
    """Test thread-safety with concurrent producers."""

    @pytest.mark.asyncio
    async def test_concurrent_enqueue(self):
        """Multiple concurrent enqueues should be thread-safe."""
        queue = PriorityExecutionQueue(max_size=100)

        async def enqueue_requests(start_idx: int, count: int):
            results = []
            for i in range(count):
                request = create_request(
                    symbol=f"SYMBOL{start_idx + i}",
                    created_at=datetime.now() + timedelta(milliseconds=i)
                )
                success = await queue.enqueue(request)
                results.append(success)
            return results

        # Run 5 concurrent producers, each enqueuing 10 requests
        tasks = [enqueue_requests(i * 10, 10) for i in range(5)]
        results = await asyncio.gather(*tasks)

        # All should succeed (different symbols)
        all_results = [r for batch in results for r in batch]
        assert all(all_results)
        assert queue.size == 50

    @pytest.mark.asyncio
    async def test_concurrent_enqueue_dequeue(self):
        """Concurrent enqueue and dequeue should be thread-safe."""
        queue = PriorityExecutionQueue(max_size=100)
        processed = []

        async def producer():
            for i in range(20):
                request = create_request(
                    symbol=f"SYMBOL{i}",
                    created_at=datetime.now() + timedelta(milliseconds=i)
                )
                await queue.enqueue(request)
                await asyncio.sleep(0.001)

        async def consumer():
            for _ in range(20):
                try:
                    request = await asyncio.wait_for(queue.dequeue(), timeout=1.0)
                    processed.append(request)
                except asyncio.TimeoutError:
                    break

        await asyncio.gather(producer(), consumer())

        assert len(processed) == 20
        assert queue.is_empty


class TestQueueCapacity:
    """Test queue capacity limits."""

    @pytest.mark.asyncio
    async def test_reject_when_full(self):
        """Queue should reject requests when full."""
        queue = PriorityExecutionQueue(max_size=2)

        await queue.enqueue(create_request(symbol="BTC"))
        await queue.enqueue(create_request(symbol="ETH"))

        # Third request should fail
        success = await queue.enqueue(create_request(symbol="SOL"))

        assert success is False
        assert queue.is_full is True

    @pytest.mark.asyncio
    async def test_accept_after_dequeue_from_full(self):
        """Queue should accept requests after dequeue from full state."""
        queue = PriorityExecutionQueue(max_size=2)

        await queue.enqueue(create_request(symbol="BTC"))
        await queue.enqueue(create_request(symbol="ETH"))
        await queue.dequeue()

        # Should now accept
        success = await queue.enqueue(create_request(symbol="SOL"))

        assert success is True
        assert queue.is_full is True
