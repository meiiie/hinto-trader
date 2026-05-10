"""
DataAggregator - Infrastructure Layer

Aggregates 1-minute candles to higher timeframes (15m, 1h) in real-time.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Callable, List, Dict
from collections import deque

from ...domain.entities.candle import Candle


class DataAggregator:
    """
    Real-time data aggregator for converting 1-minute candles
    to 15-minute and 1-hour timeframes.

    Features:
    - Buffer management for 1-minute candles
    - OHLCV aggregation logic
    - Automatic detection of completed candles
    - Callback system for completed aggregated candles
    """

    def __init__(self, buffer_size: int = 100):
        """
        Initialize data aggregator.

        Args:
            buffer_size: Maximum number of 1m candles to keep in buffer
        """
        self.buffer_size = buffer_size

        # Buffers for 1-minute candles
        self._candles_1m: deque[Candle] = deque(maxlen=buffer_size)

        # SOTA FIX: Track current FORMING 1m candle for realtime aggregation
        self._current_forming_1m: Optional[Candle] = None

        # Current aggregating candles
        self._current_15m: Optional[Candle] = None
        self._current_1h: Optional[Candle] = None

        # Buffers for building aggregated candles
        self._buffer_15m: List[Candle] = []
        self._buffer_1h: List[Candle] = []

        # Callbacks
        self._callbacks_15m: List[Callable] = []
        self._callbacks_1h: List[Callable] = []

        # Logging
        self.logger = logging.getLogger(__name__)

    def add_candle_1m(self, candle: Candle, is_closed: bool = False) -> None:
        """
        Add a 1-minute candle to the aggregator.

        Args:
            candle: 1-minute Candle entity
            is_closed: Whether the candle is closed (completed)
        """
        # Add to 1m buffer
        self._candles_1m.append(candle)

        # SOTA FIX: Always track current forming candle for realtime 15m/1h
        self._current_forming_1m = candle

        # Only aggregate closed candles for permanent buffer
        if not is_closed:
            self.logger.debug(f"Candle forming (tracked for realtime): {candle.timestamp}")
            return

        self.logger.debug(f"Processing closed 1m candle: {candle.timestamp}")

        # Add to aggregation buffers
        self._buffer_15m.append(candle)
        self._buffer_1h.append(candle)

        # Check if 15m candle is complete
        self._check_15m_completion(candle.timestamp)

        # Check if 1h candle is complete
        self._check_1h_completion(candle.timestamp)


    def _check_15m_completion(self, timestamp: datetime) -> None:
        """
        Check if 15-minute candle is complete and aggregate if needed.

        Args:
            timestamp: Timestamp of the latest 1m candle
        """
        # 15m candle completes every 15 minutes (at :00, :15, :30, :45)
        if len(self._buffer_15m) >= 15:
            # Check if we've crossed a 15-minute boundary
            minute = timestamp.minute
            if minute % 15 == 0 or len(self._buffer_15m) == 15:
                # Aggregate the candles
                aggregated = self._aggregate_candles(self._buffer_15m, '15m')

                if aggregated:
                    self.logger.debug(f"✅ 15m candle completed: {aggregated.timestamp}")
                    self._current_15m = aggregated

                    # Notify callbacks
                    self._notify_callbacks(self._callbacks_15m, aggregated)

                    # Clear buffer
                    self._buffer_15m.clear()

    def _check_1h_completion(self, timestamp: datetime) -> None:
        """
        Check if 1-hour candle is complete and aggregate if needed.

        Args:
            timestamp: Timestamp of the latest 1m candle
        """
        # 1h candle completes every 60 minutes (at :00)
        if len(self._buffer_1h) >= 60:
            # Check if we've crossed an hour boundary
            minute = timestamp.minute
            if minute == 0 or len(self._buffer_1h) == 60:
                # Aggregate the candles
                aggregated = self._aggregate_candles(self._buffer_1h, '1h')

                if aggregated:
                    self.logger.debug(f"✅ 1h candle completed: {aggregated.timestamp}")
                    self._current_1h = aggregated

                    # Notify callbacks
                    self._notify_callbacks(self._callbacks_1h, aggregated)

                    # Clear buffer
                    self._buffer_1h.clear()


    def _aggregate_candles(
        self,
        candles: List[Candle],
        timeframe: str
    ) -> Optional[Candle]:
        """
        Aggregate multiple 1-minute candles into a single candle.

        Aggregation logic:
        - Open: First candle's open
        - High: Maximum of all highs
        - Low: Minimum of all lows
        - Close: Last candle's close
        - Volume: Sum of all volumes
        - Timestamp: First candle's timestamp

        Args:
            candles: List of 1-minute candles to aggregate
            timeframe: Target timeframe ('15m' or '1h')

        Returns:
            Aggregated Candle or None if candles list is empty
        """
        if not candles:
            self.logger.warning(f"No candles to aggregate for {timeframe}")
            return None

        try:
            # SOTA FIX: Normalize timestamps to naive UTC before comparison
            # This avoids "can't compare offset-naive and offset-aware datetimes" error
            def to_naive_utc(ts):
                """Convert any datetime to naive UTC for consistent comparison."""
                if ts is None:
                    return datetime.min
                if hasattr(ts, 'tzinfo') and ts.tzinfo is not None:
                    # Convert aware to naive UTC
                    return ts.replace(tzinfo=None)
                return ts

            # Sort candles by timestamp (normalized)
            sorted_candles = sorted(candles, key=lambda c: to_naive_utc(c.timestamp))

            # Extract OHLCV data
            first_candle = sorted_candles[0]
            last_candle = sorted_candles[-1]

            open_price = first_candle.open
            high_price = max(c.high for c in sorted_candles)
            low_price = min(c.low for c in sorted_candles)
            close_price = last_candle.close
            total_volume = sum(c.volume for c in sorted_candles)

            # SOTA FIX: Align timestamp to timeframe boundary (15m or 1h)
            # Instead of using first candle's raw timestamp, calculate the correct boundary
            first_ts = first_candle.timestamp
            if '15m' in timeframe:
                # Align to 15-minute boundary: 00, 15, 30, 45
                aligned_minute = (first_ts.minute // 15) * 15
                timestamp = first_ts.replace(minute=aligned_minute, second=0, microsecond=0)
            elif '1h' in timeframe:
                # Align to hour boundary
                timestamp = first_ts.replace(minute=0, second=0, microsecond=0)
            else:
                # Default to first candle's timestamp
                timestamp = first_ts

            # Create aggregated candle
            aggregated = Candle(
                timestamp=timestamp,
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=total_volume
            )

            self.logger.debug(
                f"Aggregated {len(sorted_candles)} candles to {timeframe}: "
                f"{timestamp} O:{open_price:.2f} H:{high_price:.2f} "
                f"L:{low_price:.2f} C:{close_price:.2f} V:{total_volume:.2f}"
            )

            return aggregated

        except Exception as e:
            self.logger.error(f"Error aggregating candles: {e}")
            return None


    def _notify_callbacks(self, callbacks: List[Callable], candle: Candle) -> None:
        """
        Notify all callbacks with the completed candle.

        Args:
            callbacks: List of callback functions
            candle: Completed aggregated candle
        """
        for callback in callbacks:
            try:
                callback(candle)
            except Exception as e:
                self.logger.error(f"Error in callback: {e}")

    def get_current_15m(self) -> Optional[Candle]:
        """
        Get the current (last completed) 15-minute candle.

        Returns:
            Current 15m Candle or None if not available
        """
        return self._current_15m

    def get_current_1h(self) -> Optional[Candle]:
        """
        Get the current (last completed) 1-hour candle.

        Returns:
            Current 1h Candle or None if not available
        """
        return self._current_1h

    def get_forming_15m(self) -> Optional[Candle]:
        """
        SOTA: Get the FORMING 15-minute candle (aggregated from current buffer + forming 1m).

        This enables realtime updates for 15m chart before candle completes.
        Includes the current forming 1m candle for true tick-by-tick updates.

        Returns:
            Forming 15m Candle aggregated from buffer + current tick, or None if no data
        """
        # Build list: closed candles + current forming candle
        candles_to_aggregate = self._buffer_15m.copy()

        # SOTA FIX: Include current forming 1m candle for realtime updates
        if self._current_forming_1m:
            candles_to_aggregate.append(self._current_forming_1m)

        if not candles_to_aggregate:
            return None

        return self._aggregate_candles(candles_to_aggregate, '15m_forming')

    def get_forming_1h(self) -> Optional[Candle]:
        """
        SOTA: Get the FORMING 1-hour candle (aggregated from current buffer + forming 1m).

        This enables realtime updates for 1h chart before candle completes.
        Includes the current forming 1m candle for true tick-by-tick updates.

        Returns:
            Forming 1h Candle aggregated from buffer + current tick, or None if no data
        """
        # Build list: closed candles + current forming candle
        candles_to_aggregate = self._buffer_1h.copy()

        # SOTA FIX: Include current forming 1m candle for realtime updates
        if self._current_forming_1m:
            candles_to_aggregate.append(self._current_forming_1m)

        if not candles_to_aggregate:
            return None

        return self._aggregate_candles(candles_to_aggregate, '1h_forming')

    def get_latest_1m_candles(self, count: int = 10) -> List[Candle]:
        """
        Get the latest 1-minute candles from buffer.

        Args:
            count: Number of candles to retrieve

        Returns:
            List of latest 1m candles (most recent first)
        """
        candles = list(self._candles_1m)
        return candles[-count:] if len(candles) >= count else candles

    def on_15m_complete(self, callback: Callable[[Candle], None]) -> None:
        """
        Register callback for 15-minute candle completion.

        Args:
            callback: Function to call when 15m candle completes
                     Signature: callback(candle: Candle) -> None
        """
        self._callbacks_15m.append(callback)
        self.logger.debug(f"Registered 15m callback (total: {len(self._callbacks_15m)})")

    def on_1h_complete(self, callback: Callable[[Candle], None]) -> None:
        """
        Register callback for 1-hour candle completion.

        Args:
            callback: Function to call when 1h candle completes
                     Signature: callback(candle: Candle) -> None
        """
        self._callbacks_1h.append(callback)
        self.logger.debug(f"Registered 1h callback (total: {len(self._callbacks_1h)})")

    def get_buffer_status(self) -> Dict[str, int]:
        """
        Get current buffer status.

        Returns:
            Dict with buffer counts for each timeframe
        """
        return {
            '1m_total': len(self._candles_1m),
            '15m_pending': len(self._buffer_15m),
            '1h_pending': len(self._buffer_1h)
        }

    def clear_buffers(self) -> None:
        """Clear all buffers (useful for testing or reset)"""
        self._candles_1m.clear()
        self._buffer_15m.clear()
        self._buffer_1h.clear()
        self._current_15m = None
        self._current_1h = None
        self.logger.info("All buffers cleared")

    def __repr__(self) -> str:
        """String representation"""
        status = self.get_buffer_status()
        return (
            f"DataAggregator("
            f"1m={status['1m_total']}, "
            f"15m_pending={status['15m_pending']}, "
            f"1h_pending={status['1h_pending']}"
            f")"
        )
