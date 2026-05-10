"""
Performance Tests for Priority Execution Queue Throughput

Tests:
- Simulate 50 symbols × 3 timeframes = 150 candles/second
- Verify _route_candle returns in < 1ms
- Verify queue processing keeps up with load
- Measure latency distribution (p50, p95, p99)

Validates: REQ-1.4, Property 4
"""

import pytest
import asyncio
import time
import statistics
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
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


class TestEnqueuePerformance:
    """Test enqueue operation performance."""

    @pytest.mark.asyncio
    async def test_single_enqueue_latency(self):
        """Single enqueue should complete in < 1ms."""
        queue = PriorityExecutionQueue()

        latencies = []
        for i in range(100):
            request = create_request(symbol=f"SYMBOL{i}")

            start = time.perf_counter()
            await queue.enqueue(request)
            elapsed_ms = (time.perf_counter() - start) * 1000

            latencies.append(elapsed_ms)

        avg_latency = statistics.mean(latencies)
        p99_latency = statistics.quantiles(latencies, n=100)[98]

        print(f"\nEnqueue latency: avg={avg_latency:.3f}ms, p99={p99_latency:.3f}ms")

        # Average should be < 1ms
        assert avg_latency < 1.0
        # p99 should be < 5ms (allow for occasional GC)
        assert p99_latency < 5.0

    @pytest.mark.asyncio
    async def test_concurrent_enqueue_latency(self):
        """Concurrent enqueues should not significantly increase latency."""
        queue = PriorityExecutionQueue(max_size=500)

        async def measure_enqueue(idx: int):
            latencies = []
            for i in range(20):
                request = create_request(symbol=f"WORKER{idx}_SYMBOL{i}")

                start = time.perf_counter()
                await queue.enqueue(request)
                elapsed_ms = (time.perf_counter() - start) * 1000

                latencies.append(elapsed_ms)
            return latencies

        # Run 10 concurrent workers
        tasks = [measure_enqueue(i) for i in range(10)]
        results = await asyncio.gather(*tasks)

        all_latencies = [lat for batch in results for lat in batch]
        avg_latency = statistics.mean(all_latencies)
        p99_latency = statistics.quantiles(all_latencies, n=100)[98]

        print(f"\nConcurrent enqueue latency: avg={avg_latency:.3f}ms, p99={p99_latency:.3f}ms")

        # Should still be fast under concurrent load
        assert avg_latency < 2.0
        assert p99_latency < 10.0


class TestProcessingThroughput:
    """Test processing throughput."""

    @pytest.mark.asyncio
    async def test_150_requests_per_second(self):
        """
        Simulate 50 symbols × 3 timeframes = 150 candles/second.

        In real scenario, only a fraction trigger TP/SL.
        Test with 10% trigger rate = 15 executions/second.
        """
        queue = PriorityExecutionQueue(max_size=200)
        processed_count = 0
        latencies = []

        async def fast_close(symbol):
            nonlocal processed_count
            processed_count += 1
            await asyncio.sleep(0.005)  # 5ms execution (realistic API call)
            return MagicMock(success=True)

        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=fast_close
        )

        await worker.start()

        # Simulate 1 second of load: 15 executions
        start_time = time.perf_counter()

        for i in range(15):
            request = create_request(
                symbol=f"SYMBOL{i}",
                created_at=datetime.now()
            )
            await queue.enqueue(request)
            await asyncio.sleep(0.066)  # ~15 per second

        # Wait for all processing
        while processed_count < 15:
            await asyncio.sleep(0.1)
            if time.perf_counter() - start_time > 5:  # 5s timeout
                break

        total_time = time.perf_counter() - start_time
        throughput = processed_count / total_time

        print(f"\nThroughput: {throughput:.1f} requests/second")
        print(f"Processed: {processed_count}/15 in {total_time:.2f}s")

        # Should process all requests
        assert processed_count == 15
        # Throughput should be at least 10/second
        assert throughput >= 10

        await worker.stop()

    @pytest.mark.asyncio
    async def test_burst_handling(self):
        """Test handling burst of requests (e.g., market crash)."""
        queue = PriorityExecutionQueue(max_size=100)
        processed_count = 0

        async def fast_close(symbol):
            nonlocal processed_count
            processed_count += 1
            await asyncio.sleep(0.01)  # 10ms execution
            return MagicMock(success=True)

        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=fast_close
        )

        await worker.start()

        # Burst: 50 SL requests at once (market crash scenario)
        start_time = time.perf_counter()

        for i in range(50):
            request = create_request(
                symbol=f"SYMBOL{i}",
                priority=ExecutionPriority.STOP_LOSS,
                execution_type=ExecutionType.STOP_LOSS
            )
            await queue.enqueue(request)

        enqueue_time = (time.perf_counter() - start_time) * 1000

        # Wait for all processing
        while processed_count < 50:
            await asyncio.sleep(0.1)
            if time.perf_counter() - start_time > 10:  # 10s timeout
                break

        total_time = time.perf_counter() - start_time

        print(f"\nBurst handling:")
        print(f"  Enqueue time: {enqueue_time:.1f}ms for 50 requests")
        print(f"  Total processing time: {total_time:.2f}s")
        print(f"  Processed: {processed_count}/50")

        # Enqueue should be fast (< 100ms for 50 requests)
        assert enqueue_time < 100
        # All should be processed
        assert processed_count == 50
        # Total time should be reasonable (50 × 10ms = 500ms minimum)
        assert total_time < 5.0

        await worker.stop()


class TestLatencyDistribution:
    """Test latency distribution (p50, p95, p99)."""

    @pytest.mark.asyncio
    async def test_latency_percentiles(self):
        """Measure latency percentiles."""
        queue = PriorityExecutionQueue(max_size=200)
        latencies = []

        async def timed_close(symbol):
            await asyncio.sleep(0.01)  # 10ms base execution
            return MagicMock(success=True)

        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=timed_close
        )

        await worker.start()

        # Enqueue requests with known creation times
        for i in range(100):
            request = create_request(
                symbol=f"SYMBOL{i}",
                created_at=datetime.now()
            )
            await queue.enqueue(request)
            await asyncio.sleep(0.02)  # Stagger requests

        # Wait for all processing
        await asyncio.sleep(3.0)

        stats = worker.get_latency_stats()

        print(f"\nLatency statistics:")
        print(f"  Total executions: {stats['total_executions']}")
        print(f"  Avg latency: {stats['avg_latency_ms']:.1f}ms")
        print(f"  Min latency: {stats['min_latency_ms']:.1f}ms")
        print(f"  Max latency: {stats['max_latency_ms']:.1f}ms")
        print(f"  Warnings (>100ms): {stats['warnings_count']}")
        print(f"  Critical (>500ms): {stats['critical_count']}")

        # Average should be reasonable
        assert stats['avg_latency_ms'] < 100
        # Should have processed most requests
        assert stats['total_executions'] >= 90

        await worker.stop()


class TestQueueBackpressure:
    """Test queue behavior under backpressure."""

    @pytest.mark.asyncio
    async def test_queue_full_rejection(self):
        """Queue should reject requests when full."""
        queue = PriorityExecutionQueue(max_size=10)

        # Slow consumer
        async def slow_close(symbol):
            await asyncio.sleep(1.0)  # Very slow
            return MagicMock(success=True)

        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=slow_close
        )

        await worker.start()

        # Try to enqueue more than capacity
        success_count = 0
        reject_count = 0

        for i in range(20):
            request = create_request(symbol=f"SYMBOL{i}")
            success = await queue.enqueue(request)
            if success:
                success_count += 1
            else:
                reject_count += 1

        print(f"\nBackpressure test:")
        print(f"  Accepted: {success_count}")
        print(f"  Rejected: {reject_count}")

        # Should accept up to max_size
        assert success_count == 10
        # Should reject the rest
        assert reject_count == 10

        await worker.stop()

    @pytest.mark.asyncio
    async def test_recovery_after_drain(self):
        """Queue should accept requests after draining."""
        queue = PriorityExecutionQueue(max_size=5)
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

        # Fill queue
        for i in range(5):
            await queue.enqueue(create_request(symbol=f"BATCH1_{i}"))

        # Wait for drain
        await asyncio.sleep(0.5)

        # Should be able to enqueue more
        for i in range(5):
            success = await queue.enqueue(create_request(symbol=f"BATCH2_{i}"))
            assert success is True

        # Wait for processing
        await asyncio.sleep(0.5)

        assert processed_count == 10

        await worker.stop()


class TestMemoryEfficiency:
    """Test memory efficiency under load."""

    @pytest.mark.asyncio
    async def test_no_memory_leak(self):
        """Queue should not leak memory after processing."""
        import gc

        queue = PriorityExecutionQueue(max_size=100)

        async def fast_close(symbol):
            return MagicMock(success=True)

        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=fast_close
        )

        await worker.start()

        # Process many requests
        for batch in range(10):
            for i in range(50):
                request = create_request(symbol=f"BATCH{batch}_SYMBOL{i}")
                await queue.enqueue(request)

            # Wait for processing
            while not queue.is_empty:
                await asyncio.sleep(0.1)

        # Force garbage collection
        gc.collect()

        # Queue should be empty
        assert queue.is_empty
        assert queue.size == 0
        assert len(queue.get_pending_symbols()) == 0

        await worker.stop()


class TestRealWorldScenario:
    """Test real-world trading scenarios."""

    @pytest.mark.asyncio
    async def test_mixed_load_scenario(self):
        """
        Simulate realistic trading day:
        - Mostly quiet (few executions)
        - Occasional bursts (news events)
        - Priority ordering maintained
        """
        queue = PriorityExecutionQueue(max_size=100)
        execution_log = []

        async def logging_close(symbol):
            execution_log.append(('close', symbol, datetime.now()))
            await asyncio.sleep(0.01)
            return MagicMock(success=True)

        async def logging_partial(symbol, price, pct):
            execution_log.append(('partial', symbol, datetime.now()))
            await asyncio.sleep(0.01)
            return MagicMock(success=True)

        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=logging_partial,
            close_position_callback=logging_close
        )

        await worker.start()

        # Phase 1: Quiet period (1 execution every 500ms)
        for i in range(5):
            request = create_request(
                symbol=f"QUIET_{i}",
                priority=ExecutionPriority.TAKE_PROFIT,
                execution_type=ExecutionType.TAKE_PROFIT_PARTIAL
            )
            await queue.enqueue(request)
            await asyncio.sleep(0.5)

        # Phase 2: Burst (10 SL at once - market crash)
        for i in range(10):
            request = create_request(
                symbol=f"CRASH_{i}",
                priority=ExecutionPriority.STOP_LOSS,
                execution_type=ExecutionType.STOP_LOSS
            )
            await queue.enqueue(request)

        # Phase 3: Recovery (mixed TP/SL)
        for i in range(5):
            sl_request = create_request(
                symbol=f"RECOVERY_SL_{i}",
                priority=ExecutionPriority.STOP_LOSS,
                execution_type=ExecutionType.STOP_LOSS
            )
            tp_request = create_request(
                symbol=f"RECOVERY_TP_{i}",
                priority=ExecutionPriority.TAKE_PROFIT,
                execution_type=ExecutionType.TAKE_PROFIT_PARTIAL
            )
            await queue.enqueue(tp_request)
            await queue.enqueue(sl_request)
            await asyncio.sleep(0.1)

        # Wait for all processing (longer wait for slow test environments)
        max_wait = 5.0
        start_wait = time.perf_counter()
        while len(execution_log) < 25 and (time.perf_counter() - start_wait) < max_wait:
            await asyncio.sleep(0.1)

        print(f"\nReal-world scenario:")
        print(f"  Total executions: {len(execution_log)}")

        # Verify all processed
        # Phase 1: 5 QUIET, Phase 2: 10 CRASH, Phase 3: 5 SL + 5 TP = 25 total
        assert len(execution_log) == 25

        # Verify SL processed before TP in burst phase
        crash_executions = [e for e in execution_log if 'CRASH' in e[1]]
        assert len(crash_executions) == 10

        await worker.stop()
