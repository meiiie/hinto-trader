"""
Data Retention Service - Application Layer

SOTA Pattern: Rolling Window Retention Policy (Binance Dec 2025)

Automatically cleans up old candle data to prevent database bloat.

Retention Policy:
| Timeframe | Days | Reason                    |
|-----------|------|---------------------------|
| 1m        | 7    | High-frequency, large     |
| 15m       | 30   | Medium-term analysis      |
| 1h        | 90   | Long-term trend analysis  |
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

from src.domain.repositories.market_data_repository import MarketDataRepository


class DataRetentionService:
    """
    Manages data retention and cleanup for market data.

    SOTA Pattern: Time-based rolling window cleanup
    - Runs daily at low-traffic time (00:00 local)
    - Deletes candles older than retention period
    - Logs cleanup statistics

    Usage:
        service = DataRetentionService(repository)
        await service.start()  # Starts background task
        await service.stop()   # Stops background task
    """

    # Default retention periods (in days)
    DEFAULT_RETENTION = {
        '1m': 7,    # 7 days = ~10,080 candles
        '15m': 30,  # 30 days = ~2,880 candles
        '1h': 90    # 90 days = ~2,160 candles
    }

    # Cleanup interval (24 hours)
    CLEANUP_INTERVAL_HOURS = 24

    def __init__(
        self,
        repository: MarketDataRepository,
        retention_days: Optional[Dict[str, int]] = None
    ):
        """
        Initialize retention service.

        Args:
            repository: MarketDataRepository for database operations
            retention_days: Optional custom retention periods
        """
        self._repository = repository
        self._retention = retention_days or self.DEFAULT_RETENTION
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self.logger = logging.getLogger(__name__)

        self.logger.info(
            f"📦 DataRetentionService initialized: "
            f"1m={self._retention.get('1m', 7)}d, "
            f"15m={self._retention.get('15m', 30)}d, "
            f"1h={self._retention.get('1h', 90)}d"
        )

    async def start(self) -> None:
        """Start the background cleanup task."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._cleanup_loop())
        self.logger.info("🧹 DataRetentionService started")

    async def stop(self) -> None:
        """Stop the background cleanup task."""
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        self.logger.info("🧹 DataRetentionService stopped")

    async def _cleanup_loop(self) -> None:
        """Background loop that runs cleanup periodically."""
        # Run cleanup immediately on startup
        await self._run_cleanup()

        while self._running:
            try:
                # Wait for next cleanup interval
                await asyncio.sleep(self.CLEANUP_INTERVAL_HOURS * 3600)

                if self._running:
                    await self._run_cleanup()

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in cleanup loop: {e}")
                # Wait a bit before retrying
                await asyncio.sleep(300)  # 5 minutes

    async def _run_cleanup(self) -> None:
        """
        Execute cleanup for all timeframes and all symbols.

        SOTA Multi-Symbol: Loops through all enabled symbols from config.
        """
        from src.config import MultiTokenConfig

        self.logger.info("🧹 Starting retention cleanup...")

        # SOTA: Get all enabled symbols from config
        config = MultiTokenConfig()
        symbols = [s.lower() for s in config.symbols]

        total_deleted = 0

        for timeframe, days in self._retention.items():
            for symbol in symbols:
                try:
                    cutoff = datetime.now() - timedelta(days=days)
                    deleted = self._repository.delete_candles_before(timeframe, cutoff, symbol)

                    if deleted > 0:
                        self.logger.info(
                            f"🧹 Cleaned {symbol}/{timeframe}: {deleted} candles "
                            f"(older than {days} days)"
                        )
                        total_deleted += deleted

                except Exception as e:
                    self.logger.error(f"Failed to cleanup {symbol}/{timeframe}: {e}")

        # Log database size after cleanup
        try:
            db_size = self._repository.get_database_size()
            self.logger.info(
                f"🧹 Cleanup complete: {total_deleted} candles removed, "
                f"DB size: {db_size:.2f} MB"
            )
        except Exception:
            self.logger.info(f"🧹 Cleanup complete: {total_deleted} candles removed")

    def run_cleanup_sync(self) -> int:
        """
        Run cleanup synchronously (for testing or manual trigger).

        SOTA Multi-Symbol: Cleans up all enabled symbols.

        Returns:
            Total number of candles deleted
        """
        from src.config import MultiTokenConfig

        config = MultiTokenConfig()
        symbols = [s.lower() for s in config.symbols]

        total_deleted = 0

        for timeframe, days in self._retention.items():
            for symbol in symbols:
                try:
                    cutoff = datetime.now() - timedelta(days=days)
                    deleted = self._repository.delete_candles_before(timeframe, cutoff, symbol)
                    total_deleted += deleted
                except Exception as e:
                    self.logger.error(f"Failed to cleanup {symbol}/{timeframe}: {e}")

        return total_deleted
