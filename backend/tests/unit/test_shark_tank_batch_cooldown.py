"""
Unit tests for SharkTankCoordinator batch cooldown fix.

CRITICAL FIX (Jan 2026): Tests that only 1 batch is processed per 15-minute period.
This matches backtest behavior where only 1 batch is processed per candle close.

Created: 2026-01-23
"""

import pytest
import time
import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch

from backend.src.application.services.shark_tank_coordinator import SharkTankCoordinator
from backend.src.domain.entities.trading_signal import TradingSignal, SignalType


@pytest.fixture
def coordinator():
    """Create coordinator with short cooldown for testing."""
    coord = SharkTankCoordinator(
        max_positions=5,
        batch_interval_seconds=0.1,  # Short interval for testing
        enable_smart_recycling=False
    )

    # Override cooldown for faster testing
    coord.batch_cooldown_seconds = 2  # 2 seconds instead of 900

    # Set up callbacks
    coord.set_callbacks(
        execute_callback=Mock(),
        get_open_positions_callback=Mock(return_value=0),
        get_available_margin_callback=Mock(return_value=1000.0),
        get_position_symbols_callback=Mock(return_value=set())
    )

    return coord


@pytest.fixture
def sample_signal():
    """Create a sample trading signal."""
    def _create_signal(symbol: str, confidence: float = 0.8):
        signal = TradingSignal(
            symbol=symbol,
            signal_type=SignalType.BUY,
            confidence=confidence,
            price=100.0,
            entry_price=100.0,
            stop_loss=95.0,
            tp_levels={'tp1': 105.0, 'tp2': 110.0},
            generated_at=datetime.now()
        )
        return signal
    return _create_signal


class TestBatchCooldown:
    """Test batch cooldown functionality."""

    def test_first_batch_executes_immediately(self, coordinator, sample_signal):
        """First batch should execute without cooldown."""
        # Arrange
        signal = sample_signal("BTCUSDT", 0.9)

        # Act - Mock asyncio.create_task to avoid event loop issues
        with patch('asyncio.create_task'):
            coordinator.collect_signal(signal, "BTCUSDT")
            coordinator.force_process()

        # Assert
        assert coordinator.metrics['batches_processed'] == 1
        assert coordinator.metrics['batches_rejected_cooldown'] == 0
        assert coordinator._execute_callback.call_count == 1

    def test_second_batch_within_cooldown_deferred(self, coordinator, sample_signal):
        """Second batch within cooldown should be retained for the next allowed batch."""
        # Arrange
        signal1 = sample_signal("BTCUSDT", 0.9)
        signal2 = sample_signal("ETHUSDT", 0.85)

        # Act - Batch 1
        with patch('asyncio.create_task'):
            coordinator.collect_signal(signal1, "BTCUSDT")
            coordinator.force_process()

        # Act - Batch 2 (immediately after, within cooldown)
        with patch('asyncio.create_task'):
            coordinator.collect_signal(signal2, "ETHUSDT")
            coordinator.force_process()

        # Assert
        assert coordinator.metrics['batches_processed'] == 1
        assert coordinator.metrics['batches_rejected_cooldown'] == 1
        assert coordinator.metrics['batches_deferred_cooldown'] == 1
        assert coordinator.metrics['total_signals_rejected'] == 0
        assert coordinator.get_pending_count() == 1
        assert coordinator._execute_callback.call_count == 1  # Only first batch

    def test_third_batch_after_cooldown_executes(self, coordinator, sample_signal):
        """Third batch after cooldown should execute."""
        # Arrange
        signal1 = sample_signal("BTCUSDT", 0.9)
        signal2 = sample_signal("ETHUSDT", 0.85)
        signal3 = sample_signal("BNBUSDT", 0.88)

        # Act - Batch 1
        with patch('asyncio.create_task'):
            coordinator.collect_signal(signal1, "BTCUSDT")
            coordinator.force_process()

        # Act - Batch 2 (within cooldown)
        time.sleep(1.0)  # 1 second < 2 second cooldown
        with patch('asyncio.create_task'):
            coordinator.collect_signal(signal2, "ETHUSDT")
            coordinator.force_process()

        # Act - Batch 3 (after cooldown)
        time.sleep(1.5)  # Total 2.5 seconds > 2 second cooldown
        with patch('asyncio.create_task'):
            coordinator.collect_signal(signal3, "BNBUSDT")
            coordinator.force_process()

        # Assert
        assert coordinator.metrics['batches_processed'] == 2
        assert coordinator.metrics['batches_rejected_cooldown'] == 1
        assert coordinator._execute_callback.call_count == 3  # Batch 1, then deferred + new

    def test_multiple_signals_in_deferred_batch(self, coordinator, sample_signal):
        """All signals in a cooldown batch should be retained."""
        # Arrange
        signal1 = sample_signal("BTCUSDT", 0.9)
        signal2 = sample_signal("ETHUSDT", 0.85)
        signal3 = sample_signal("BNBUSDT", 0.88)
        signal4 = sample_signal("ADAUSDT", 0.82)

        # Act - Batch 1
        with patch('asyncio.create_task'):
            coordinator.collect_signal(signal1, "BTCUSDT")
            coordinator.force_process()

        # Act - Batch 2 (multiple signals, within cooldown)
        with patch('asyncio.create_task'):
            coordinator.collect_signal(signal2, "ETHUSDT")
            coordinator.collect_signal(signal3, "BNBUSDT")
            coordinator.collect_signal(signal4, "ADAUSDT")
            coordinator.force_process()

        # Assert
        assert coordinator.metrics['batches_rejected_cooldown'] == 1
        assert coordinator.metrics['batches_deferred_cooldown'] == 1
        assert coordinator.metrics['total_signals_rejected'] == 0
        assert coordinator.get_pending_count() == 3

    def test_cooldown_timing_precision(self, coordinator, sample_signal):
        """Test cooldown timing is precise."""
        # Arrange
        signal1 = sample_signal("BTCUSDT", 0.9)
        signal2 = sample_signal("ETHUSDT", 0.85)
        signal3 = sample_signal("BNBUSDT", 0.88)

        # Act - Batch 1
        with patch('asyncio.create_task'):
            coordinator.collect_signal(signal1, "BTCUSDT")
            coordinator.force_process()
            batch1_time = coordinator._last_batch_processed_time

        # Act - Batch 2 (1.9 seconds - just before cooldown)
        time.sleep(1.9)
        with patch('asyncio.create_task'):
            coordinator.collect_signal(signal2, "ETHUSDT")
            coordinator.force_process()

        # Assert - Should be deferred, not discarded
        assert coordinator.metrics['batches_rejected_cooldown'] == 1
        assert coordinator.get_pending_count() == 1

        # Act - Batch 3 (wait remaining time + buffer)
        time.sleep(0.2)  # Total 2.1 seconds > 2 second cooldown
        with patch('asyncio.create_task'):
            coordinator.collect_signal(signal3, "BNBUSDT")
            coordinator.force_process()

        # Assert - Should execute
        assert coordinator.metrics['batches_processed'] == 2
        assert coordinator._last_batch_processed_time > batch1_time

    def test_get_metrics_includes_cooldown_info(self, coordinator, sample_signal):
        """Metrics should include cooldown information."""
        # Arrange
        signal = sample_signal("BTCUSDT", 0.9)

        # Act
        with patch('asyncio.create_task'):
            coordinator.collect_signal(signal, "BTCUSDT")
            coordinator.force_process()
            metrics = coordinator.get_metrics()

        # Assert
        assert 'batches_processed' in metrics
        assert 'batches_rejected_cooldown' in metrics
        assert 'batches_deferred_cooldown' in metrics
        assert 'total_signals_processed' in metrics
        assert 'total_signals_rejected' in metrics
        assert 'last_batch_time' in metrics
        assert 'cooldown_seconds' in metrics
        assert metrics['cooldown_seconds'] == 2

    def test_cooldown_with_no_slots_available(self, coordinator, sample_signal):
        """Cooldown should work even when no slots available."""
        # Arrange
        coordinator._get_open_positions_callback = Mock(return_value=5)  # All slots full
        signal1 = sample_signal("BTCUSDT", 0.9)
        signal2 = sample_signal("ETHUSDT", 0.85)

        # Act - Batch 1 (no slots - will be rejected but still sets cooldown time)
        with patch('asyncio.create_task'):
            coordinator.collect_signal(signal1, "BTCUSDT")
            coordinator.force_process()

        # Act - Batch 2 (within cooldown, no slots)
        with patch('asyncio.create_task'):
            coordinator.collect_signal(signal2, "ETHUSDT")
            coordinator.force_process()

        # Assert - First batch rejected for no slots (but doesn't set cooldown)
        # Second batch also rejected for no slots (not cooldown since first didn't process)
        # This is expected behavior - cooldown only applies to successful batches
        assert coordinator._execute_callback.call_count == 0


class TestBatchCooldownIntegration:
    """Integration tests for batch cooldown with real scenarios."""

    def test_15_minute_scenario(self, coordinator, sample_signal):
        """Simulate 15-minute period with multiple signal events."""
        # Override cooldown to 5 seconds for faster testing (represents 15 minutes)
        coordinator.batch_cooldown_seconds = 5

        # Scenario: 4 signal events in 15 minutes
        # Expected: Only 1st and 4th should execute

        with patch('asyncio.create_task'):
            # Event 1: 00:00 - Should execute
            coordinator.collect_signal(sample_signal("BTCUSDT", 0.9), "BTCUSDT")
            coordinator.force_process()

            # Event 2: 00:05 (2s later) - Should defer
            time.sleep(2)
            coordinator.collect_signal(sample_signal("ETHUSDT", 0.85), "ETHUSDT")
            coordinator.force_process()

            # Event 3: 00:10 (4s later) - Should still defer
            time.sleep(2)
            coordinator.collect_signal(sample_signal("BNBUSDT", 0.88), "BNBUSDT")
            coordinator.force_process()

            # Event 4: 00:15 (6s later) - Should execute deferred + new
            time.sleep(2)
            coordinator.collect_signal(sample_signal("ADAUSDT", 0.82), "ADAUSDT")
            coordinator.force_process()

        # Assert
        assert coordinator.metrics['batches_processed'] == 2  # Event 1 and 4
        assert coordinator.metrics['batches_rejected_cooldown'] == 1  # Same cooldown window
        assert coordinator.metrics['batches_deferred_cooldown'] == 1
        assert coordinator._execute_callback.call_count == 4

    def test_realistic_live_scenario(self, coordinator, sample_signal):
        """Test realistic live scenario with async events."""
        coordinator.batch_cooldown_seconds = 3

        # Simulate realistic live events
        events = [
            (0.0, "BTCUSDT", 0.90),   # Candle close
            (0.5, "ETHUSDT", 0.85),   # WebSocket event
            (1.5, "BNBUSDT", 0.88),   # Timer check
            (2.5, "ADAUSDT", 0.82),   # State sync
            (3.5, "SOLUSDT", 0.87),   # Next candle close
        ]

        start_time = time.time()
        with patch('asyncio.create_task'):
            for delay, symbol, confidence in events:
                # Wait until event time
                elapsed = time.time() - start_time
                if delay > elapsed:
                    time.sleep(delay - elapsed)

                coordinator.collect_signal(sample_signal(symbol, confidence), symbol)
                coordinator.force_process()

        # Assert - First executes, middle signals are retained, final flush executes all retained.
        assert coordinator.metrics['batches_processed'] == 2
        assert coordinator.metrics['batches_rejected_cooldown'] == 1
        assert coordinator.metrics['batches_deferred_cooldown'] == 1
        assert coordinator._execute_callback.call_count == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
