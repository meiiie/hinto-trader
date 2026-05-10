"""
SOTA: Backend Scheduler Service

Runs periodic tasks like updating market intelligence.
Uses APScheduler for reliable async scheduling.
"""

import asyncio
import logging
import subprocess
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class SchedulerService:
    """
    Manages scheduled background tasks for the trading system.

    Features:
    - Hourly market intelligence updates
    - Configurable intervals
    - Error recovery
    """

    def __init__(self, interval_hours: int = 1, intelligence_service = None):
        self.interval_hours = interval_hours
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self._scripts_dir = Path(__file__).parent.parent.parent.parent / "scripts"
        self.intelligence_service = intelligence_service

    async def start(self):
        """Start the scheduler."""
        if self.running:
            logger.warning("Scheduler already running")
            return

        self.running = True
        self._task = asyncio.create_task(self._schedule_loop())
        logger.info(f"🕐 Scheduler started: updating market intelligence every {self.interval_hours}h")

    async def stop(self):
        """Stop the scheduler."""
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("🛑 Scheduler stopped")

    async def _schedule_loop(self):
        """Main scheduling loop."""
        # Run immediately on start
        await self.update_market_intelligence()

        while self.running:
            try:
                # Wait for next interval
                await asyncio.sleep(self.interval_hours * 3600)

                if self.running:
                    await self.update_market_intelligence()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
                # Continue running, retry on next interval

    async def update_market_intelligence(self):
        """
        Run market intelligence update via Service.
        Updates: funding rates, leverage brackets, min notional, step size.
        """
        try:
            logger.info("📊 Scheduler: Updating market intelligence...")

            if self.intelligence_service:
                # Use injected service (SOTA)
                # Note: fetch_and_update is synchronous or async?
                # It does network calls, so it blocks if not run in executor.
                # But requests library is blocking.
                # To be safe in async loop, run in executor.
                loop = asyncio.get_event_loop()
                success = await loop.run_in_executor(
                    None,
                    self.intelligence_service.fetch_and_update
                )

                if success:
                    logger.info(f"✅ Market intelligence updated at {datetime.now().strftime('%H:%M:%S')}")
                else:
                    logger.error("❌ Market intelligence update failed")
            else:
                # Fallback to old script method (Legacy)
                logger.warning("⚠️ No intelligence service injected, using legacy script")
                script_path = self._scripts_dir / "get_market_intelligence.py"

                result = await asyncio.create_subprocess_exec(
                    sys.executable,
                    str(script_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(self._scripts_dir.parent)
                )

                stdout, stderr = await result.communicate()

                if result.returncode == 0:
                    logger.info(f"✅ Market intelligence updated (script) at {datetime.now().strftime('%H:%M:%S')}")
                else:
                    logger.error(f"❌ Script failed: {stderr.decode()}")

        except Exception as e:
            logger.error(f"Failed to update market intelligence: {e}")

    async def run_once(self):
        """Run single update (for manual trigger)."""
        await self.update_market_intelligence()


# Singleton instance
_scheduler: Optional[SchedulerService] = None


def get_scheduler() -> SchedulerService:
    """Get or create scheduler instance."""
    global _scheduler
    if _scheduler is None:
        # SOTA: Inject Intelligence Service via DI Container
        try:
            # Lazy import to avoid circular dependency
            from ...api.dependencies import get_container
            container = get_container()
            intel_service = container.get_market_intelligence_service()
            _scheduler = SchedulerService(intelligence_service=intel_service)
        except Exception as e:
            logger.error(f"Failed to inject intelligence service into scheduler: {e}")
            # Fallback to default (will use script)
            _scheduler = SchedulerService()

    return _scheduler
