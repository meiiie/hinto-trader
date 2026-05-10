"""
PriorityExecutionQueue - SOTA Priority Queue for Order Execution

Pattern: NautilusTrader, Two Sigma, Citadel
Manages execution requests with priority ordering and duplicate detection.

Features:
- Priority ordering (SL > TP > Entry)
- Duplicate detection (prevent double execution)
- Metrics tracking
- Graceful shutdown support
- Thread-safe with asyncio.Lock
"""

import asyncio
import logging
from typing import Dict, Set, Optional
from datetime import datetime

from ...domain.entities.execution_request import (
    ExecutionRequest,
    ExecutionPriority,
    ExecutionType
)

logger = logging.getLogger(__name__)


class PriorityExecutionQueue:
    """
    SOTA Priority Queue for order execution.

    Features:
    - Priority ordering (SL=0 > TP=1 > Entry=2)
    - Duplicate detection (prevent double execution for same symbol/type)
    - Metrics tracking (enqueued, processed, rejected)
    - Graceful shutdown support (stop accepting, drain queue)
    - Thread-safe with asyncio.Lock

    Usage:
        queue = PriorityExecutionQueue(max_size=100)

        # Enqueue request
        success = await queue.enqueue(request)

        # Dequeue (blocks if empty)
        request = await queue.dequeue()

        # Check pending
        if queue.is_symbol_pending("BTCUSDT"):
            logger.warning("BTCUSDT already in queue")
    """

    def __init__(self, max_size: int = 100):
        """
        Initialize PriorityExecutionQueue.

        Args:
            max_size: Maximum queue capacity (default 100, ~20x safety margin for 5 positions)
        """
        self._queue: asyncio.PriorityQueue[ExecutionRequest] = asyncio.PriorityQueue(maxsize=max_size)
        self._pending_symbols: Set[str] = set()  # Track symbols in queue
        self._pending_by_type: Dict[str, ExecutionType] = {}  # "SYMBOL:type" -> ExecutionType
        self._metrics = {
            'total_enqueued': 0,
            'total_processed': 0,
            'duplicates_rejected': 0,
            'sl_count': 0,
            'tp_count': 0,
            'entry_count': 0
        }
        self._accepting_requests = True
        self._lock = asyncio.Lock()
        self._max_size = max_size

        logger.info(f"📦 PriorityExecutionQueue initialized (max_size={max_size})")

    async def enqueue(self, request: ExecutionRequest) -> bool:
        """
        Add execution request to queue.

        Returns False if:
        - Queue is not accepting requests (shutdown)
        - Duplicate request for same symbol/type
        - Queue is full

        Args:
            request: ExecutionRequest to enqueue

        Returns:
            True if enqueued successfully, False otherwise
        """
        async with self._lock:
            # Check if accepting requests
            if not self._accepting_requests:
                logger.warning(f"⚠️ Queue not accepting requests, rejecting {request.symbol}")
                return False

            # Check for duplicate (same symbol + execution type)
            key = f"{request.symbol}:{request.execution_type.value}"
            if key in self._pending_by_type:
                self._metrics['duplicates_rejected'] += 1
                logger.warning(
                    f"⚠️ Duplicate rejected: {request.symbol} {request.execution_type.value} "
                    f"(already pending)"
                )
                return False

            # Check queue capacity
            if self._queue.full():
                logger.critical(f"🚨 Queue FULL! Rejecting {request.symbol}")
                return False

            # Add to queue
            await self._queue.put(request)
            self._pending_symbols.add(request.symbol)
            self._pending_by_type[key] = request.execution_type

            # Update metrics
            self._metrics['total_enqueued'] += 1
            if request.priority == ExecutionPriority.STOP_LOSS:
                self._metrics['sl_count'] += 1
            elif request.priority == ExecutionPriority.TAKE_PROFIT:
                self._metrics['tp_count'] += 1
            else:
                self._metrics['entry_count'] += 1

            logger.info(
                f"📤 Enqueued {request.execution_type.value} for {request.symbol} | "
                f"Priority: {request.priority} | Queue size: {self._queue.qsize()}"
            )

            return True

    async def dequeue(self) -> ExecutionRequest:
        """
        Get next request from queue.

        Blocks if queue is empty (no busy-waiting).
        Updates tracking sets after dequeue.

        Returns:
            Next ExecutionRequest by priority order
        """
        request = await self._queue.get()

        async with self._lock:
            # Remove from tracking
            key = f"{request.symbol}:{request.execution_type.value}"
            self._pending_symbols.discard(request.symbol)
            self._pending_by_type.pop(key, None)
            self._metrics['total_processed'] += 1

        return request

    def is_symbol_pending(self, symbol: str) -> bool:
        """
        Check if symbol has pending execution.

        Args:
            symbol: Trading pair (e.g., "BTCUSDT")

        Returns:
            True if symbol has pending request in queue
        """
        return symbol.upper() in self._pending_symbols

    def is_pending(self, symbol: str, execution_type: ExecutionType) -> bool:
        """
        Check if specific symbol/type combination is pending.

        Args:
            symbol: Trading pair
            execution_type: Type of execution

        Returns:
            True if exact combination is pending
        """
        key = f"{symbol.upper()}:{execution_type.value}"
        return key in self._pending_by_type

    def stop_accepting(self):
        """
        Stop accepting new requests (for graceful shutdown).

        Existing items in queue will still be processed.
        """
        self._accepting_requests = False
        logger.info(f"🛑 Queue stopped accepting new requests (remaining: {self._queue.qsize()})")

    def resume_accepting(self):
        """Resume accepting new requests."""
        self._accepting_requests = True
        logger.info("✅ Queue resumed accepting requests")

    @property
    def size(self) -> int:
        """Current number of items in queue."""
        return self._queue.qsize()

    @property
    def is_empty(self) -> bool:
        """Check if queue is empty."""
        return self._queue.empty()

    @property
    def is_full(self) -> bool:
        """Check if queue is full."""
        return self._queue.full()

    @property
    def is_accepting(self) -> bool:
        """Check if queue is accepting new requests."""
        return self._accepting_requests

    def get_metrics(self) -> Dict:
        """
        Get queue metrics.

        Returns:
            Dict with total_enqueued, total_processed, duplicates_rejected,
            sl_count, tp_count, entry_count, current_size
        """
        metrics = self._metrics.copy()
        metrics['current_size'] = self._queue.qsize()
        metrics['pending_symbols'] = list(self._pending_symbols)
        return metrics

    def get_pending_symbols(self) -> Set[str]:
        """Get set of symbols with pending executions."""
        return self._pending_symbols.copy()

    def __repr__(self) -> str:
        return (
            f"PriorityExecutionQueue("
            f"size={self._queue.qsize()}/{self._max_size}, "
            f"accepting={self._accepting_requests}, "
            f"pending={len(self._pending_symbols)})"
        )
