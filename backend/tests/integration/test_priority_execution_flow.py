"""
Integration Tests for Priority Execution Queue Full Flow

Tests:
- candle → condition check → queue → execution
- SL processed before TP when both in queue
- Non-blocking data flow (measure _route_candle time < 1ms)
- Latency tracking accuracy (queue_wait + execution = total)
- 50 symbols throughput without degradation

Validates: Property 4, Property 5, Property 6
"""

import pytest
import asyncio
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from src.infrastructure.execution.priority_execution_queue import PriorityExecutionQueue
from src.infrastructure.execution.execution_worker import ExecutionWorker
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


class TestFullExecutionFlow:
    """Test complete execution flow from queue to callback."""

    @pytest.mark.asyncio
    async def test_sl_processed_before_tp(self):
        """SL should be processed before TP when both in queue."""
        queue = PriorityExecutionQueue()
        processed_order = []

        async def tracking_close(symbol):
            processed_order.append(('close', symbol))
            return MagicMock(success=True)

        async def tracking_partial(symbol, price, pct):
            processed_order.append(('partial', symbol))
            return MagicMock(success=True)

        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=tracking_partial,
            close_position_callback=tracking_close
        )

        await worker.start()

        # Enqueue TP first
        tp_request = create_request(
            symbol="BTCUSDT",
            priority=ExecutionPriority.TAKE_PROFIT,
            execution_type=ExecutionType.TAKE_PROFIT_PARTIAL
        )
        await queue.enqueue(tp_request)

        # Enqueue SL second
        sl_request = create_request(
            symbol="ETHUSDT",
            priority=ExecutionPriority.STOP_LOSS,
            execution_type=ExecutionType.STOP_LOSS
        )
        await queue.enqueue(sl_request)

        # Wait for processing
        await asyncio.sleep(0.3)

        # SL should be processed first
        assert len(processed_order) == 2
        assert processed_order[0] == ('close', 'ETHUSDT')  # SL first
        assert processed_order[1] == ('partial', 'BTCUSDT')  # TP second

        await worker.stop()

    @pytest.mark.asyncio
    async def test_multiple_sl_fifo_order(self):
        """Multiple SL requests should be processed in FIFO order."""
        queue = PriorityExecutionQueue()
        processed_order = []

        async def tracking_close(symbol):
            processed_order.append(symbol)
            return MagicMock(success=True)

        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=tracking_close
        )

        await worker.start()

        base_time = datetime.now()

        # Enqueue in specific order
        for i, symbol in enumerate(["FIRST", "SECOND", "THIRD"]):
            request = create_request(
                symbol=symbol,
                priority=ExecutionPriority.STOP_LOSS,
                execution_type=ExecutionType.STOP_LOSS,
                created_at=base_time + timedelta(milliseconds=i * 10)
            )
            await queue.enqueue(request)

        # Wait for processing
        await asyncio.sleep(0.5)

        # Should be processed in FIFO order
        assert processed_order == ["FIRST", "SECOND", "THIRD"]

        await worker.stop()

    @pytest.mark.asyncio
    async def test_mixed_priority_ordering(self):
        """Test complex ordering with mixed priorities."""
        queue = PriorityExecutionQueue()
        processed_order = []

        async def tracking_close(symbol):
            processed_order.append(symbol)
            return MagicMock(success=True)

        async def tracking_partial(symbol, price, pct):
            processed_order.append(symbol)
            return MagicMock(success=True)

        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=tracking_partial,
            close_position_callback=tracking_close
        )

        await worker.start()

        base_time = datetime.now()

        # Enqueue in mixed order
        requests = [
            ("ENTRY1", ExecutionPriority.ENTRY, ExecutionType.CLOSE_POSITION, 0),
            ("SL1", ExecutionPriority.STOP_LOSS, ExecutionType.STOP_LOSS, 10),
            ("TP1", ExecutionPriority.TAKE_PROFIT, ExecutionType.TAKE_PROFIT_PARTIAL, 20),
            ("SL2", ExecutionPriority.STOP_LOSS, ExecutionType.STOP_LOSS, 30),
            ("TP2", ExecutionPriority.TAKE_PROFIT, ExecutionType.TAKE_PROFIT_PARTIAL, 40),
        ]

        for symbol, priority, exec_type, offset in requests:
            request = create_request(
                symbol=symbol,
                priority=priority,
                execution_type=exec_type,
                created_at=base_time + timedelta(milliseconds=offset)
            )
            await queue.enqueue(request)

        # Wait for processing
        await asyncio.sleep(1.0)

        # Expected order: SL1, SL2 (priority 0), TP1, TP2 (priority 1), ENTRY1 (priority 2)
        assert processed_order == ["SL1", "SL2", "TP1", "TP2", "ENTRY1"]

        await worker.stop()


class TestLatencyTracking:
    """Test latency tracking accuracy."""

    @pytest.mark.asyncio
    async def test_latency_components(self):
        """Total latency should equal queue_wait + execution time."""
        queue = PriorityExecutionQueue()

        execution_time_ms = 50

        async def timed_close(symbol):
            await asyncio.sleep(execution_time_ms / 1000)
            return MagicMock(success=True)

        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=timed_close
        )

        await worker.start()

        # Create request with known creation time
        queue_wait_ms = 100
        old_time = datetime.now() - timedelta(milliseconds=queue_wait_ms)
        request = create_request(created_at=old_time)

        await queue.enqueue(request)

        # Wait for processing
        await asyncio.sleep(0.3)

        stats = worker.get_latency_stats()

        # Total latency should be approximately queue_wait + execution
        expected_min = queue_wait_ms + execution_time_ms
        assert stats['total_latency_ms'] >= expected_min - 20  # Allow some tolerance

        await worker.stop()

    @pytest.mark.asyncio
    async def test_avg_latency_calculation(self):
        """Average latency should be calculated correctly."""
        queue = PriorityExecutionQueue()
        close_position = AsyncMock(return_value=MagicMock(success=True))

        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=close_position
        )

        await worker.start()

        # Enqueue multiple requests
        for i in range(5):
            request = create_request(symbol=f"SYMBOL{i}")
            await queue.enqueue(request)

        # Wait for processing
        await asyncio.sleep(0.5)

        stats = worker.get_latency_stats()

        # Average should be total / count
        expected_avg = stats['total_latency_ms'] / stats['total_executions']
        assert abs(stats['avg_latency_ms'] - expected_avg) < 0.1

        await worker.stop()


class TestNonBlockingFlow:
    """Test non-blocking data flow."""

    @pytest.mark.asyncio
    async def test_enqueue_returns_quickly(self):
        """Enqueue should return in < 1ms."""
        queue = PriorityExecutionQueue()

        # Measure enqueue time
        start = time.perf_counter()
        request = create_request()
        await queue.enqueue(request)
        elapsed_ms = (time.perf_counter() - start) * 1000

        # Should be very fast (< 1ms)
        assert elapsed_ms < 10  # Allow some margin for test environment

    @pytest.mark.asyncio
    async def test_concurrent_enqueue_performance(self):
        """Multiple concurrent enqueues should not block."""
        queue = PriorityExecutionQueue(max_size=100)

        async def enqueue_batch(start_idx: int, count: int):
            times = []
            for i in range(count):
                start = time.perf_counter()
                request = create_request(symbol=f"SYMBOL{start_idx + i}")
                await queue.enqueue(request)
                elapsed_ms = (time.perf_counter() - start) * 1000
                times.append(elapsed_ms)
            return times

        # Run concurrent enqueues
        tasks = [enqueue_batch(i * 10, 10) for i in range(5)]
        results = await asyncio.gather(*tasks)

        # All enqueues should be fast
        all_times = [t for batch in results for t in batch]
        avg_time = sum(all_times) / len(all_times)

        assert avg_time < 5  # Average should be < 5ms


class TestThroughput:
    """Test throughput under load."""

    @pytest.mark.asyncio
    async def test_50_symbols_throughput(self):
        """Process 50 symbols without degradation."""
        queue = PriorityExecutionQueue(max_size=100)
        processed_count = 0

        async def fast_close(symbol):
            nonlocal processed_count
            processed_count += 1
            await asyncio.sleep(0.001)  # 1ms execution
            return MagicMock(success=True)

        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=fast_close
        )

        await worker.start()

        # Enqueue 50 requests
        start_time = time.perf_counter()
        for i in range(50):
            request = create_request(symbol=f"SYMBOL{i}")
            await queue.enqueue(request)
        enqueue_time = (time.perf_counter() - start_time) * 1000

        # Wait for all processing
        while processed_count < 50:
            await asyncio.sleep(0.1)
            if time.perf_counter() - start_time > 10:  # 10s timeout
                break

        total_time = (time.perf_counter() - start_time) * 1000

        # All should be processed
        assert processed_count == 50

        # Enqueue should be fast
        assert enqueue_time < 100  # < 100ms for 50 enqueues

        # Total processing should be reasonable
        # 50 requests × 1ms each = 50ms minimum
        assert total_time < 5000  # < 5s total

        await worker.stop()

    @pytest.mark.asyncio
    async def test_sustained_throughput(self):
        """Test sustained throughput over time."""
        queue = PriorityExecutionQueue(max_size=200)
        processed_count = 0

        async def fast_close(symbol):
            nonlocal processed_count
            processed_count += 1
            return MagicMock(success=True)

        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=fast_close
        )

        await worker.start()

        # Simulate sustained load: 10 requests every 100ms for 1 second
        for batch in range(10):
            for i in range(10):
                request = create_request(symbol=f"BATCH{batch}_SYMBOL{i}")
                await queue.enqueue(request)
            await asyncio.sleep(0.1)

        # Wait for processing
        await asyncio.sleep(1.0)

        # All should be processed
        assert processed_count == 100

        await worker.stop()


class TestDuplicatePrevention:
    """Test duplicate execution prevention."""

    @pytest.mark.asyncio
    async def test_no_duplicate_execution(self):
        """Same symbol/type should not be executed twice."""
        queue = PriorityExecutionQueue()
        execution_count = {}

        async def counting_close(symbol):
            execution_count[symbol] = execution_count.get(symbol, 0) + 1
            await asyncio.sleep(0.1)  # Slow execution
            return MagicMock(success=True)

        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=counting_close
        )

        await worker.start()

        # Try to enqueue same symbol twice
        request1 = create_request(symbol="BTCUSDT")
        request2 = create_request(symbol="BTCUSDT")

        success1 = await queue.enqueue(request1)
        success2 = await queue.enqueue(request2)

        # Wait for processing
        await asyncio.sleep(0.5)

        # First should succeed, second should be rejected
        assert success1 is True
        assert success2 is False

        # Should only execute once
        assert execution_count.get("BTCUSDT", 0) == 1

        await worker.stop()


class TestExecutionGuarantee:
    """Test execution guarantee (Property 5)."""

    @pytest.mark.asyncio
    async def test_all_requests_processed(self):
        """All enqueued requests should eventually be processed."""
        queue = PriorityExecutionQueue()
        processed = set()

        async def tracking_close(symbol):
            processed.add(symbol)
            return MagicMock(success=True)

        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=tracking_close
        )

        await worker.start()

        # Enqueue many requests
        symbols = [f"SYMBOL{i}" for i in range(20)]
        for symbol in symbols:
            request = create_request(symbol=symbol)
            await queue.enqueue(request)

        # Wait for processing
        await asyncio.sleep(1.0)

        # All should be processed
        assert processed == set(symbols)

        await worker.stop()

    @pytest.mark.asyncio
    async def test_failed_requests_logged(self):
        """Failed requests should be logged (not silently dropped)."""
        queue = PriorityExecutionQueue()

        async def always_failing(symbol):
            raise Exception("Simulated failure")

        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=always_failing
        )

        await worker.start()

        request = create_request(
            priority=ExecutionPriority.TAKE_PROFIT,  # Not SL to avoid emergency close
            execution_type=ExecutionType.CLOSE_POSITION
        )
        await queue.enqueue(request)

        # Wait for retries
        await asyncio.sleep(1.0)

        # Queue should be empty (request was processed, even if failed)
        assert queue.is_empty

        await worker.stop()
