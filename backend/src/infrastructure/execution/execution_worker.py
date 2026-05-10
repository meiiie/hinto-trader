"""
ExecutionWorker - SOTA Background Worker for Order Execution

Pattern: NautilusTrader background services, Two Sigma, Citadel
Processes execution requests from PriorityExecutionQueue sequentially.

Features:
- Background coroutine (non-blocking)
- Sequential processing (no race conditions)
- Retry with exponential backoff (TP/Entry)
- Immediate retry for SL (critical)
- Emergency close for failed SL
- Latency tracking
- Graceful shutdown
"""

import asyncio
import time
import logging
from datetime import datetime
from typing import Callable, Optional, Dict, Any

from .priority_execution_queue import PriorityExecutionQueue
from ...domain.entities.execution_request import (
    ExecutionRequest,
    ExecutionPriority,
    ExecutionType
)
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PositionAdapter:
    """
    SOTA FIX (Feb 2026): Adapter to convert ExecutionRequest to MonitoredPosition-like object.

    Problem: close_position_async expects MonitoredPosition with .symbol and .quantity
    But ExecutionWorker only has ExecutionRequest.

    Solution: Create adapter with same interface as MonitoredPosition.
    """
    symbol: str
    quantity: float
    side: str = ""
    entry_price: float = 0.0


class ExecutionWorker:
    """
    SOTA Background worker for processing execution queue.

    Pattern: NautilusTrader background services
    - Runs in dedicated coroutine
    - Sequential processing (no race conditions)
    - Retry with exponential backoff
    - Latency tracking

    Usage:
        worker = ExecutionWorker(
            queue=queue,
            partial_close_callback=live_trading.partial_close_position_async,
            close_position_callback=live_trading.close_position_async
        )
        await worker.start()
        # ... later
        await worker.stop()
    """

    MAX_RETRIES = 3
    BASE_RETRY_DELAY = 0.1  # 100ms
    SHUTDOWN_TIMEOUT = 30.0  # seconds

    def __init__(
        self,
        queue: PriorityExecutionQueue,
        partial_close_callback: Callable,
        close_position_callback: Callable
    ):
        """
        Initialize ExecutionWorker.

        Args:
            queue: PriorityExecutionQueue to process
            partial_close_callback: async (symbol, price, pct) -> success
            close_position_callback: async (symbol, reason) -> success
        """
        self._queue = queue
        self._partial_close = partial_close_callback
        self._close_position = close_position_callback

        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Latency tracking
        self._latency_stats = {
            'total_executions': 0,
            'total_latency_ms': 0.0,
            'max_latency_ms': 0.0,
            'min_latency_ms': float('inf'),
            'avg_latency_ms': 0.0,
            'warnings_count': 0,  # > 100ms
            'critical_count': 0   # > 500ms
        }

        logger.info("🔧 ExecutionWorker initialized")

    async def start(self):
        """
        Start the execution worker.

        Creates background task that processes queue items.
        Safe to call multiple times (idempotent).
        """
        if self._running:
            logger.warning("⚠️ ExecutionWorker already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("🚀 ExecutionWorker started")

    async def stop(self):
        """
        Stop the execution worker gracefully.

        1. Stop accepting new requests
        2. Wait for queue to drain (up to SHUTDOWN_TIMEOUT)
        3. Cancel worker task
        """
        logger.info("🛑 ExecutionWorker stopping...")
        self._running = False
        self._queue.stop_accepting()

        # Wait for queue to drain
        start_time = time.time()
        while not self._queue.is_empty:
            elapsed = time.time() - start_time
            if elapsed > self.SHUTDOWN_TIMEOUT:
                logger.critical(
                    f"🚨 Shutdown timeout! {self._queue.size} items remaining in queue"
                )
                break
            await asyncio.sleep(0.1)

        # Cancel task
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("✅ ExecutionWorker stopped")

    async def _run(self):
        """
        Main worker loop.

        Continuously dequeues and processes requests.
        Uses timeout to periodically check running flag.
        """
        logger.info("🔄 ExecutionWorker loop started")

        while self._running or not self._queue.is_empty:
            try:
                # Wait for next request (with timeout to check running flag)
                try:
                    request = await asyncio.wait_for(
                        self._queue.dequeue(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    # No request available, check if should continue
                    continue

                # Process request
                await self._process_request(request)

            except asyncio.CancelledError:
                logger.info("🛑 ExecutionWorker cancelled")
                break
            except Exception as e:
                logger.error(f"❌ ExecutionWorker error: {e}", exc_info=True)

        logger.info("🔄 ExecutionWorker loop ended")

    async def _process_request(self, request: ExecutionRequest):
        """
        Process a single execution request with retry.

        - Measures queue wait time and execution time
        - Retries with exponential backoff (TP/Entry)
        - Immediate retry for SL (critical)
        - Emergency close for failed SL
        """
        start_time = time.perf_counter()
        queue_wait_ms = request.age_ms

        logger.info(
            f"⚡ Processing {request.execution_type.value} for {request.symbol} | "
            f"Priority: {request.priority} | Queue wait: {queue_wait_ms:.1f}ms | "
            f"Retry: {request.retry_count}"
        )

        success = False
        last_error = None

        for attempt in range(self.MAX_RETRIES):
            try:
                success = await self._execute_request(request)
                if success:
                    break
            except Exception as e:
                last_error = e

                if request.is_stop_loss:
                    # SL is critical - retry immediately without backoff
                    logger.critical(
                        f"🚨 SL execution attempt {attempt + 1}/{self.MAX_RETRIES} failed: {e}"
                    )
                else:
                    # TP/Entry - exponential backoff
                    delay = self.BASE_RETRY_DELAY * (2 ** attempt)
                    logger.warning(
                        f"⚠️ Execution attempt {attempt + 1}/{self.MAX_RETRIES} failed: {e}. "
                        f"Retrying in {delay*1000:.0f}ms"
                    )
                    await asyncio.sleep(delay)

        # Calculate latency
        execution_time_ms = (time.perf_counter() - start_time) * 1000
        total_latency_ms = queue_wait_ms + execution_time_ms

        self._update_latency_stats(total_latency_ms)

        if success:
            logger.info(
                f"✅ {request.execution_type.value} executed for {request.symbol} | "
                f"Total latency: {total_latency_ms:.1f}ms "
                f"(queue: {queue_wait_ms:.1f}ms, exec: {execution_time_ms:.1f}ms)"
            )
        else:
            logger.critical(
                f"🚨 FAILED {request.execution_type.value} for {request.symbol} | "
                f"Error: {last_error} | Attempts: {self.MAX_RETRIES}"
            )

            # Emergency handling for SL
            if request.is_stop_loss:
                await self._emergency_close(request)

    async def _execute_request(self, request: ExecutionRequest) -> bool:
        """
        Execute the actual order.

        Routes to correct callback based on execution_type.

        Args:
            request: ExecutionRequest to execute

        Returns:
            True if execution successful
        """
        try:
            # SOTA FIX (Feb 2026): Create adapter for close_position_async
            # Callback expects MonitoredPosition-like object with .symbol, .quantity
            pos_adapter = PositionAdapter(
                symbol=request.symbol,
                quantity=request.quantity,
                side=request.side,
                entry_price=request.position_entry_price
            )

            # FIX P2 (Feb 13, 2026): Pass reason to close_position_async
            # Without reason, default "MANUAL" skips _pending_exit_reasons → "DEFERRED" in DB
            # Map execution_type to correct exit reason for CB/DB/notification accuracy
            REASON_MAP = {
                ExecutionType.STOP_LOSS: "stop_loss",
                ExecutionType.TAKE_PROFIT_FULL: "take_profit",
                ExecutionType.CLOSE_POSITION: "MANUAL",
            }

            if request.execution_type == ExecutionType.STOP_LOSS:
                # Full close for SL
                result = await self._close_position(pos_adapter, reason="stop_loss")
                return self._check_result(result)

            elif request.execution_type == ExecutionType.TAKE_PROFIT_PARTIAL:
                # 60% partial close for TP1
                result = await self._partial_close(
                    request.symbol,
                    request.price,
                    0.60  # 60% partial close
                )
                return self._check_result(result)

            elif request.execution_type == ExecutionType.TAKE_PROFIT_FULL:
                # Full close for TP
                result = await self._close_position(pos_adapter, reason="take_profit")
                return self._check_result(result)

            elif request.execution_type == ExecutionType.CLOSE_POSITION:
                # Generic close
                result = await self._close_position(pos_adapter, reason="MANUAL")
                return self._check_result(result)

            elif request.execution_type == ExecutionType.ENTRY:
                # Entry orders not handled here (use LocalSignalTracker)
                logger.warning(f"⚠️ Entry orders should use LocalSignalTracker, not ExecutionWorker")
                return False

            else:
                logger.error(f"❌ Unknown execution type: {request.execution_type}")
                return False

        except Exception as e:
            logger.error(f"❌ Execute request error: {e}", exc_info=True)
            raise

    def _check_result(self, result: Any) -> bool:
        """
        Check if execution result indicates success.

        Handles various result types from callbacks.
        """
        if result is None:
            return False
        if hasattr(result, 'success'):
            return result.success
        if isinstance(result, bool):
            return result
        if isinstance(result, dict):
            return result.get('success', False)
        # Assume truthy value means success
        return bool(result)

    async def _emergency_close(self, request: ExecutionRequest):
        """
        Emergency market close when SL fails.

        Last resort - direct market order without retry.
        Logs CRITICAL for manual intervention.
        """
        logger.critical(f"🚨 EMERGENCY CLOSE: {request.symbol}")

        try:
            # SOTA FIX (Feb 2026): Use PositionAdapter for callback compatibility
            pos_adapter = PositionAdapter(
                symbol=request.symbol,
                quantity=request.quantity,
                side=request.side,
                entry_price=request.position_entry_price
            )
            # Direct market order without retry
            result = await self._close_position(pos_adapter, reason="stop_loss")

            if self._check_result(result):
                logger.critical(f"🚨 EMERGENCY CLOSE SUCCESS: {request.symbol}")
            else:
                logger.critical(
                    f"🚨 EMERGENCY CLOSE FAILED: {request.symbol} - "
                    f"MANUAL INTERVENTION REQUIRED!"
                )
        except Exception as e:
            logger.critical(
                f"🚨 EMERGENCY CLOSE EXCEPTION: {request.symbol} - {e} - "
                f"MANUAL INTERVENTION REQUIRED!"
            )

    def _update_latency_stats(self, latency_ms: float):
        """
        Update latency statistics.

        Tracks total, max, min, avg latency.
        Counts warnings (>100ms) and critical (>500ms).
        """
        stats = self._latency_stats
        stats['total_executions'] += 1
        stats['total_latency_ms'] += latency_ms
        stats['max_latency_ms'] = max(stats['max_latency_ms'], latency_ms)

        if stats['min_latency_ms'] == float('inf'):
            stats['min_latency_ms'] = latency_ms
        else:
            stats['min_latency_ms'] = min(stats['min_latency_ms'], latency_ms)

        stats['avg_latency_ms'] = stats['total_latency_ms'] / stats['total_executions']

        # Log warnings for high latency
        if latency_ms > 500:
            stats['critical_count'] += 1
            logger.critical(f"🚨 CRITICAL LATENCY: {latency_ms:.1f}ms")
        elif latency_ms > 100:
            stats['warnings_count'] += 1
            logger.warning(f"⚠️ HIGH LATENCY: {latency_ms:.1f}ms")

    def get_latency_stats(self) -> Dict:
        """
        Get latency statistics.

        Returns:
            Dict with total_executions, total_latency_ms, max_latency_ms,
            min_latency_ms, avg_latency_ms, warnings_count, critical_count
        """
        stats = self._latency_stats.copy()

        # Handle case where no executions yet
        if stats['min_latency_ms'] == float('inf'):
            stats['min_latency_ms'] = 0.0

        return stats

    @property
    def is_running(self) -> bool:
        """Check if worker is running."""
        return self._running

    def __repr__(self) -> str:
        return (
            f"ExecutionWorker("
            f"running={self._running}, "
            f"executions={self._latency_stats['total_executions']}, "
            f"avg_latency={self._latency_stats['avg_latency_ms']:.1f}ms)"
        )
