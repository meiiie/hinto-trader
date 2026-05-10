"""
TTL Scheduler Service - SOTA Background Cleanup

Runs every 60 seconds to cleanup expired pending orders/signals.
Pattern: APScheduler-style asyncio task (Binance/Freqtrade pattern)

Features:
- Paper mode: Mark expired SQLite orders as CANCELLED
- Testnet/Live: Call LocalSignalTracker.cleanup_expired()
- Graceful shutdown support
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class TTLScheduler:
    """
    SOTA: Background scheduler for TTL enforcement.

    Runs every 60 seconds to cleanup expired orders/signals across all modes.
    This ensures zombie orders don't persist even without user interaction.
    """

    # Configuration
    CLEANUP_INTERVAL_SECONDS = 60  # Run every 1 minute
    TTL_PAPER_MINUTES = 45  # Paper mode TTL
    TTL_LIVE_MINUTES = 45   # Testnet/Live TTL (via LocalSignalTracker)

    def __init__(
        self,
        paper_cleanup_callback: Optional[Callable] = None,
        live_cleanup_callback: Optional[Callable] = None
    ):
        """
        Args:
            paper_cleanup_callback: Called to cleanup Paper mode orders
            live_cleanup_callback: Called to cleanup Testnet/Live signals
        """
        self._paper_cleanup = paper_cleanup_callback
        self._live_cleanup = live_cleanup_callback
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._cleanup_count = 0

    async def start(self):
        """Start the background scheduler."""
        if self._running:
            logger.warning("TTLScheduler already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info(f"🕐 TTLScheduler started (interval: {self.CLEANUP_INTERVAL_SECONDS}s)")

    async def stop(self):
        """Stop the scheduler gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(f"🕐 TTLScheduler stopped (total cleanups: {self._cleanup_count})")

    async def _scheduler_loop(self):
        """Main scheduler loop - runs every CLEANUP_INTERVAL_SECONDS."""
        while self._running:
            try:
                await self._run_cleanup()
                await asyncio.sleep(self.CLEANUP_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"TTLScheduler error: {e}")
                await asyncio.sleep(10)  # Back off on error

    async def _run_cleanup(self):
        """Execute cleanup for all modes."""
        self._cleanup_count += 1
        start_time = datetime.now()

        paper_cleaned = 0
        live_cleaned = 0

        # Paper mode cleanup
        if self._paper_cleanup:
            try:
                paper_cleaned = await self._cleanup_paper_mode()
            except Exception as e:
                logger.error(f"Paper cleanup error: {e}")

        # Live/Testnet cleanup
        if self._live_cleanup:
            try:
                live_cleaned = await self._cleanup_live_mode()
            except Exception as e:
                logger.error(f"Live cleanup error: {e}")

        duration_ms = (datetime.now() - start_time).total_seconds() * 1000

        if paper_cleaned > 0 or live_cleaned > 0:
            logger.info(
                f"🕐 TTL Cleanup #{self._cleanup_count}: "
                f"Paper={paper_cleaned}, Live={live_cleaned} ({duration_ms:.1f}ms)"
            )

    async def _cleanup_paper_mode(self) -> int:
        """
        Cleanup expired Paper mode pending orders.
        Returns number of orders cleaned.
        """
        if not self._paper_cleanup:
            return 0

        # Call the callback (sync function wrapped in to_thread)
        result = await asyncio.to_thread(self._paper_cleanup)
        return result if isinstance(result, int) else 0

    async def _cleanup_live_mode(self) -> int:
        """
        Cleanup expired Testnet/Live signals via LocalSignalTracker.
        Returns number of signals cleaned.
        """
        if not self._live_cleanup:
            return 0

        # LocalSignalTracker.cleanup_expired() is sync
        result = await asyncio.to_thread(self._live_cleanup)
        return result if isinstance(result, int) else 0

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def cleanup_count(self) -> int:
        return self._cleanup_count


# Singleton instance
_ttl_scheduler: Optional[TTLScheduler] = None


def get_ttl_scheduler() -> TTLScheduler:
    """Get or create the TTL scheduler singleton."""
    global _ttl_scheduler
    if _ttl_scheduler is None:
        _ttl_scheduler = TTLScheduler()
    return _ttl_scheduler


def init_ttl_scheduler(
    paper_cleanup_callback: Optional[Callable] = None,
    live_cleanup_callback: Optional[Callable] = None
) -> TTLScheduler:
    """Initialize TTL scheduler with callbacks."""
    global _ttl_scheduler
    _ttl_scheduler = TTLScheduler(
        paper_cleanup_callback=paper_cleanup_callback,
        live_cleanup_callback=live_cleanup_callback
    )
    return _ttl_scheduler
