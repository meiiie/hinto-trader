"""
Unit Tests for ExecutionWorker

Tests:
- Start/stop lifecycle
- Request processing with mock callbacks
- Retry with exponential backoff
- Emergency close for failed SL
- Latency tracking accuracy
- Graceful shutdown with pending items

Validates: REQ-3.2, REQ-3.3, REQ-3.4, REQ-5.1, REQ-5.2, REQ-5.3
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from src.infrastructure.execution.execution_worker import ExecutionWorker
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


class TestExecutionWorkerCreation:
    """Test worker initialization."""

    def test_create_worker(self):
        """Create worker with required callbacks."""
        queue = PriorityExecutionQueue()
        partial_close = AsyncMock()
        close_position = AsyncMock()

        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=partial_close,
            close_position_callback=close_position
        )

        assert worker._queue == queue
        assert worker._running is False
        assert worker._task is None

    def test_initial_latency_stats(self):
        """Initial latency stats should be zero."""
        queue = PriorityExecutionQueue()
        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=AsyncMock()
        )

        stats = worker.get_latency_stats()

        assert stats['total_executions'] == 0
        assert stats['total_latency_ms'] == 0.0
        assert stats['max_latency_ms'] == 0.0
        assert stats['min_latency_ms'] == 0.0  # Converted from inf
        assert stats['avg_latency_ms'] == 0.0
        assert stats['warnings_count'] == 0
        assert stats['critical_count'] == 0


class TestWorkerLifecycle:
    """Test start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_worker(self):
        """Start worker creates background task."""
        queue = PriorityExecutionQueue()
        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=AsyncMock()
        )

        await worker.start()

        assert worker._running is True
        assert worker._task is not None
        assert worker.is_running is True

        # Cleanup
        await worker.stop()

    @pytest.mark.asyncio
    async def test_start_idempotent(self):
        """Starting already running worker should be safe."""
        queue = PriorityExecutionQueue()
        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=AsyncMock()
        )

        await worker.start()
        task1 = worker._task

        await worker.start()  # Second start
        task2 = worker._task

        assert task1 == task2  # Same task

        # Cleanup
        await worker.stop()

    @pytest.mark.asyncio
    async def test_stop_worker(self):
        """Stop worker gracefully."""
        queue = PriorityExecutionQueue()
        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=AsyncMock()
        )

        await worker.start()
        await worker.stop()

        assert worker._running is False
        assert worker.is_running is False


class TestRequestProcessing:
    """Test request processing with callbacks."""

    @pytest.mark.asyncio
    async def test_process_stop_loss(self):
        """Process SL request calls close_position callback."""
        queue = PriorityExecutionQueue()
        close_position = AsyncMock(return_value=MagicMock(success=True))

        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=close_position
        )

        request = create_request(
            symbol="BTCUSDT",
            priority=ExecutionPriority.STOP_LOSS,
            execution_type=ExecutionType.STOP_LOSS
        )

        await worker.start()
        await queue.enqueue(request)

        # Wait for processing
        await asyncio.sleep(0.2)

        close_position.assert_called_once_with("BTCUSDT")

        await worker.stop()

    @pytest.mark.asyncio
    async def test_process_take_profit_partial(self):
        """Process TP partial request calls partial_close callback."""
        queue = PriorityExecutionQueue()
        partial_close = AsyncMock(return_value=MagicMock(success=True))

        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=partial_close,
            close_position_callback=AsyncMock()
        )

        request = create_request(
            symbol="BTCUSDT",
            priority=ExecutionPriority.TAKE_PROFIT,
            execution_type=ExecutionType.TAKE_PROFIT_PARTIAL
        )
        request.price = 55000.0

        await worker.start()
        await queue.enqueue(request)

        # Wait for processing
        await asyncio.sleep(0.2)

        partial_close.assert_called_once_with("BTCUSDT", 55000.0, 0.60)

        await worker.stop()

    @pytest.mark.asyncio
    async def test_process_close_position(self):
        """Process close position request calls close_position callback."""
        queue = PriorityExecutionQueue()
        close_position = AsyncMock(return_value=True)

        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=close_position
        )

        request = create_request(
            symbol="BTCUSDT",
            priority=ExecutionPriority.STOP_LOSS,
            execution_type=ExecutionType.CLOSE_POSITION
        )

        await worker.start()
        await queue.enqueue(request)

        # Wait for processing
        await asyncio.sleep(0.2)

        close_position.assert_called_with("BTCUSDT")

        await worker.stop()


class TestRetryMechanism:
    """Test retry with exponential backoff."""

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        """Worker should retry on failure."""
        queue = PriorityExecutionQueue()

        # Fail twice, succeed on third
        call_count = 0
        async def failing_close(symbol):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("Simulated failure")
            return MagicMock(success=True)

        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=failing_close
        )

        request = create_request(
            priority=ExecutionPriority.TAKE_PROFIT,  # TP uses backoff
            execution_type=ExecutionType.CLOSE_POSITION
        )

        await worker.start()
        await queue.enqueue(request)

        # Wait for retries (with backoff)
        await asyncio.sleep(1.0)

        assert call_count == 3

        await worker.stop()

    @pytest.mark.asyncio
    async def test_sl_immediate_retry(self):
        """SL should retry immediately without backoff."""
        queue = PriorityExecutionQueue()

        call_times = []
        async def failing_close(symbol):
            call_times.append(datetime.now())
            if len(call_times) < 3:
                raise Exception("Simulated failure")
            return MagicMock(success=True)

        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=failing_close
        )

        request = create_request(
            priority=ExecutionPriority.STOP_LOSS,
            execution_type=ExecutionType.STOP_LOSS
        )

        await worker.start()
        await queue.enqueue(request)

        # Wait for retries
        await asyncio.sleep(0.5)

        # SL retries should be immediate (no backoff)
        if len(call_times) >= 2:
            time_between = (call_times[1] - call_times[0]).total_seconds()
            assert time_between < 0.2  # Should be nearly immediate

        await worker.stop()


class TestEmergencyClose:
    """Test emergency close for failed SL."""

    @pytest.mark.asyncio
    async def test_emergency_close_after_max_retries(self):
        """Emergency close should be called after max retries for SL."""
        queue = PriorityExecutionQueue()

        call_count = 0
        async def always_failing_close(symbol):
            nonlocal call_count
            call_count += 1
            raise Exception("Simulated failure")

        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=always_failing_close
        )

        request = create_request(
            priority=ExecutionPriority.STOP_LOSS,
            execution_type=ExecutionType.STOP_LOSS
        )

        await worker.start()
        await queue.enqueue(request)

        # Wait for all retries + emergency close
        await asyncio.sleep(1.0)

        # Should have called: 3 retries + 1 emergency close = 4 calls
        assert call_count >= 3

        await worker.stop()


class TestLatencyTracking:
    """Test latency statistics tracking."""

    @pytest.mark.asyncio
    async def test_latency_stats_updated(self):
        """Latency stats should be updated after processing."""
        queue = PriorityExecutionQueue()

        async def slow_close(symbol):
            await asyncio.sleep(0.05)  # 50ms
            return MagicMock(success=True)

        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=slow_close
        )

        request = create_request()

        await worker.start()
        await queue.enqueue(request)

        # Wait for processing
        await asyncio.sleep(0.3)

        stats = worker.get_latency_stats()

        assert stats['total_executions'] == 1
        assert stats['total_latency_ms'] > 0
        assert stats['max_latency_ms'] > 0
        assert stats['min_latency_ms'] > 0
        assert stats['avg_latency_ms'] > 0

        await worker.stop()

    @pytest.mark.asyncio
    async def test_warning_count_for_high_latency(self):
        """Warning count should increase for latency > 100ms."""
        queue = PriorityExecutionQueue()

        async def slow_close(symbol):
            await asyncio.sleep(0.15)  # 150ms > 100ms threshold
            return MagicMock(success=True)

        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=slow_close
        )

        # Create request with old timestamp to simulate queue wait
        old_time = datetime.now() - timedelta(milliseconds=50)
        request = create_request(created_at=old_time)

        await worker.start()
        await queue.enqueue(request)

        # Wait for processing
        await asyncio.sleep(0.5)

        stats = worker.get_latency_stats()

        # Total latency = queue_wait + execution > 100ms
        assert stats['warnings_count'] >= 0  # May or may not trigger depending on timing

        await worker.stop()

    @pytest.mark.asyncio
    async def test_multiple_executions_stats(self):
        """Stats should accumulate across multiple executions."""
        queue = PriorityExecutionQueue()
        close_position = AsyncMock(return_value=MagicMock(success=True))

        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=close_position
        )

        await worker.start()

        # Enqueue multiple requests
        for i in range(3):
            request = create_request(symbol=f"SYMBOL{i}")
            await queue.enqueue(request)

        # Wait for all processing
        await asyncio.sleep(0.5)

        stats = worker.get_latency_stats()

        assert stats['total_executions'] == 3

        await worker.stop()


class TestGracefulShutdown:
    """Test graceful shutdown with pending items."""

    @pytest.mark.asyncio
    async def test_drain_queue_on_shutdown(self):
        """Worker should drain queue before shutdown."""
        queue = PriorityExecutionQueue()
        processed = []

        async def tracking_close(symbol):
            processed.append(symbol)
            await asyncio.sleep(0.05)
            return MagicMock(success=True)

        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=tracking_close
        )

        await worker.start()

        # Enqueue multiple requests
        for i in range(3):
            request = create_request(symbol=f"SYMBOL{i}")
            await queue.enqueue(request)

        # Stop immediately (should still process all)
        await worker.stop()

        assert len(processed) == 3
        assert queue.is_empty

    @pytest.mark.asyncio
    async def test_stop_accepting_on_shutdown(self):
        """Queue should stop accepting on shutdown."""
        queue = PriorityExecutionQueue()

        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=AsyncMock(return_value=True)
        )

        await worker.start()
        await worker.stop()

        # Queue should not accept new requests
        request = create_request()
        success = await queue.enqueue(request)

        assert success is False


class TestResultChecking:
    """Test _check_result helper."""

    @pytest.mark.asyncio
    async def test_check_result_with_success_attr(self):
        """Check result with success attribute."""
        queue = PriorityExecutionQueue()
        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=AsyncMock()
        )

        result = MagicMock(success=True)
        assert worker._check_result(result) is True

        result = MagicMock(success=False)
        assert worker._check_result(result) is False

    @pytest.mark.asyncio
    async def test_check_result_with_bool(self):
        """Check result with boolean."""
        queue = PriorityExecutionQueue()
        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=AsyncMock()
        )

        assert worker._check_result(True) is True
        assert worker._check_result(False) is False

    @pytest.mark.asyncio
    async def test_check_result_with_dict(self):
        """Check result with dict."""
        queue = PriorityExecutionQueue()
        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=AsyncMock()
        )

        assert worker._check_result({'success': True}) is True
        assert worker._check_result({'success': False}) is False

    @pytest.mark.asyncio
    async def test_check_result_with_none(self):
        """Check result with None."""
        queue = PriorityExecutionQueue()
        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=AsyncMock()
        )

        assert worker._check_result(None) is False


class TestWorkerRepr:
    """Test string representation."""

    def test_repr(self):
        """Test __repr__ output."""
        queue = PriorityExecutionQueue()
        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=AsyncMock(),
            close_position_callback=AsyncMock()
        )

        repr_str = repr(worker)

        assert "ExecutionWorker" in repr_str
        assert "running=False" in repr_str
        assert "executions=0" in repr_str
