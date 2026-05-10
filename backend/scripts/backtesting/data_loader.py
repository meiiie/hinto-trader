"""
Historical Data Loader for Backtesting

Loads historical candle data from database or Binance API for backtesting.
"""

from datetime import datetime, timedelta
from typing import List, Optional
import logging

from src.domain.entities.candle import Candle
from src.infrastructure.api.binance_rest_client import BinanceRestClient

logger = logging.getLogger(__name__)


class HistoricalDataLoader:
    """Load historical candle data for backtesting"""

    def __init__(self):
        self.client = BinanceRestClient()

    def load_candles(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime
    ) -> List[Candle]:
        """
        Load candles from Binance API

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            timeframe: Candle timeframe (e.g., '15m', '1h')
            start_date: Start date for data
            end_date: End date for data

        Returns:
            List of Candle objects
        """
        logger.info(f"Loading {symbol} {timeframe} candles from {start_date} to {end_date}")

        try:
            # Convert timeframe to Binance format
            interval = self._convert_timeframe(timeframe)

            # Load candles in batches (Binance limit is 1000 per request)
            all_candles = []
            current_end = int(end_date.timestamp() * 1000)

            # Calculate how many requests we need
            total_duration = end_date - start_date
            candle_duration = self._get_candle_duration(timeframe)
            estimated_candles = int(total_duration.total_seconds() / candle_duration.total_seconds())
            batches_needed = (estimated_candles // 1000) + 1

            logger.info(f"Estimated {estimated_candles} candles, fetching in {batches_needed} batches")

            for batch in range(batches_needed):
                # Fetch batch
                batch_candles = self.client.get_klines(
                    symbol=symbol,
                    interval=interval,
                    limit=1000,
                    end_time=current_end
                )

                if not batch_candles:
                    break

                # Add to collection (in reverse order since we're going backwards)
                all_candles = batch_candles + all_candles

                # Update end time for next batch
                current_end = int(batch_candles[0].timestamp.timestamp() * 1000) - 1

                # Check if we've reached start date
                if batch_candles[0].timestamp <= start_date:
                    break

                logger.info(f"Batch {batch + 1}/{batches_needed}: Loaded {len(batch_candles)} candles")

            # Filter to exact date range
            all_candles = [
                c for c in all_candles
                if start_date <= c.timestamp <= end_date
            ]

            logger.info(f"Loaded {len(all_candles)} candles total")
            return all_candles

        except Exception as e:
            logger.error(f"Error loading candles: {e}")
            raise

    def validate_data(self, candles: List[Candle]) -> bool:
        """
        Validate data completeness and quality

        Args:
            candles: List of candles to validate

        Returns:
            True if data is valid
        """
        if not candles:
            logger.warning("No candles to validate")
            return False

        # Check for missing candles
        expected_count = self._calculate_expected_count(candles)
        actual_count = len(candles)

        if actual_count < expected_count * 0.95:  # Allow 5% missing
            logger.warning(
                f"Missing candles: expected ~{expected_count}, got {actual_count}"
            )
            return False

        # Check for invalid data
        for candle in candles:
            if candle.high < candle.low:
                logger.error(f"Invalid candle: high < low at {candle.timestamp}")
                return False
            if candle.close < 0 or candle.volume < 0:
                logger.error(f"Invalid candle: negative values at {candle.timestamp}")
                return False

        logger.info("Data validation passed")
        return True

    def _convert_timeframe(self, timeframe: str) -> str:
        """Convert timeframe to Binance interval format"""
        mapping = {
            '1m': '1m',
            '5m': '5m',
            '15m': '15m',
            '30m': '30m',
            '1h': '1h',
            '4h': '4h',
            '1d': '1d'
        }
        return mapping.get(timeframe, timeframe)

    def _get_candle_duration(self, timeframe: str) -> timedelta:
        """Get duration of one candle for given timeframe"""
        durations = {
            '1m': timedelta(minutes=1),
            '5m': timedelta(minutes=5),
            '15m': timedelta(minutes=15),
            '30m': timedelta(minutes=30),
            '1h': timedelta(hours=1),
            '4h': timedelta(hours=4),
            '1d': timedelta(days=1)
        }
        return durations.get(timeframe, timedelta(minutes=15))

    def _calculate_expected_count(self, candles: List[Candle]) -> int:
        """Calculate expected number of candles based on timeframe"""
        if len(candles) < 2:
            return len(candles)

        # Calculate time difference between first and last candle
        time_diff = candles[-1].timestamp - candles[0].timestamp

        # Estimate candle interval from first two candles
        candle_interval = candles[1].timestamp - candles[0].timestamp

        # Calculate expected count
        expected = int(time_diff.total_seconds() / candle_interval.total_seconds()) + 1
        return expected
