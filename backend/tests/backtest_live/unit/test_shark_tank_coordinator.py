"""
Unit Tests for Shark Tank Coordinator

Tests batch signal processing with Smart Recycling logic.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock

from src.domain.entities.trading_signal import TradingSignal, SignalType

shark_tank_module = pytest.importorskip(
    "src.application.backtest_live.core.shark_tank_coordinator",
    reason="legacy backtest_live shark tank coordinator module is not available in this codebase",
)
SharkTankCoordinator = shark_tank_module.SharkTankCoordinator


@pytest.fixture
def coordinator():
    """Create coordinator with default settings."""
    return SharkTankCoordinator(
        max_positions=5,
        collection_window_seconds=2.0,
        proximity_threshold_pct=0.002,
        confidence_buffer_pct=0.10,
        enable_smart_recycling=True
    )


@pytest.fixture
def mock_signal():
    """Create mock signal factory."""
    def _create_signal(symbol: str, confidence: float, price: float = 100.0):
        signal = Mock(spec=TradingSignal)
        signal.symbol = symbol
        signal.confidence = confidence
        signal.signal_type = SignalType.BUY
        signal.price = price
        signal.entry_price = price
        signal.stop_loss = price * 0.995
        signal.tp_levels = [price * 1.005]
        signal.generated_at = datetime.utcnow()
        signal.indicators = {'atr': 1.0}
        return signal
    return _create_signal


class TestSignalCollection:
    """Test signal collection and buffering."""

    def test_add_signal(self, coordinator, mock_signal):
        """Test adding signal to buffer."""
        signal = mock_signal('BTCUSDT', 0.85)

        coordinator.add_signal(signal)

        assert len(coordinator._signal_buffer) == 1
        assert coordinator._signal_buffer[0] == signal

    def test_multiple_signals(self, coordinator, mock_signal):
        """Test adding multiple signals."""
        signals = [
            mock_signal('BTCUSDT', 0.85),
            mock_signal('ETHUSDT', 0.90),
            mock_signal('BNBUSDT', 0.80)
        ]

        for signal in signals:
            coordinator.add_signal(signal)

        assert len(coordinator._signal_buffer) == 3

    def test_should_process_empty_buffer(self, coordinator):
        """Test should_process with empty buffer."""
        current_time = datetime.utcnow()

        assert not coordinator.should_process(current_time)

    def test_should_process_first_time(self, coordinator, mock_signal):
        """Test should_process on first call."""
        signal = mock_signal('BTCUSDT', 0.85)
        coordinator.add_signal(signal)

        current_time = datetime.utcnow()

        assert coordinator.should_process(current_time)

    def test_should_process_window_elapsed(self, coordinator, mock_signal):
        """Test should_process after window elapsed."""
        signal = mock_signal('BTCUSDT', 0.85)
        coordinator.add_signal(signal)

        start_time = datetime.utcnow()
        coordinator._last_process_time = start_time

        # Wait for window to elapse
        current_time = start_time + timedelta(seconds=2.5)

        assert coordinator.should_process(current_time)

    def test_should_process_window_not_elapsed(self, coordinator, mock_signal):
        """Test should_process before window elapsed."""
        signal = mock_signal('BTCUSDT', 0.85)
        coordinator.add_signal(signal)

        start_time = datetime.utcnow()
        coordinator._last_process_time = start_time

        # Window not elapsed
        current_time = start_time + timedelta(seconds=1.0)

        assert not coordinator.should_process(current_time)


class TestStandardFill:
    """Test standard fill logic (slots available)."""

    def test_standard_fill_empty_tank(self, coordinator, mock_signal):
        """Test standard fill with empty tank."""
        signals = [
            mock_signal('BTCUSDT', 0.85),
            mock_signal('ETHUSDT', 0.90),
            mock_signal('BNBUSDT', 0.80)
        ]

        for signal in signals:
            coordinator.add_signal(signal)

        current_time = datetime.utcnow()
        selected = coordinator.process_signals({}, {}, current_time)

        # Should select all 3 (sorted by confidence)
        assert len(selected) == 3
        assert selected[0].symbol == 'ETHUSDT'  # Highest confidence (0.90)
        assert selected[1].symbol == 'BTCUSDT'  # Second (0.85)
        assert selected[2].symbol == 'BNBUSDT'  # Third (0.80)

    def test_standard_fill_partial_slots(self, coordinator, mock_signal):
        """Test standard fill with partial slots available."""
        signals = [
            mock_signal('BTCUSDT', 0.85),
            mock_signal('ETHUSDT', 0.90),
            mock_signal('BNBUSDT', 0.80),
            mock_signal('ADAUSDT', 0.75)
        ]

        for signal in signals:
            coordinator.add_signal(signal)

        # 2 positions + 1 pending = 3 active, 2 slots available
        current_positions = {
            'SOLUSDT': {'symbol': 'SOLUSDT'},
            'DOGEUSDT': {'symbol': 'DOGEUSDT'}
        }
        pending_orders = {
            'XRPUSDT': {'symbol': 'XRPUSDT', 'confidence': 0.70}
        }

        current_time = datetime.utcnow()
        selected = coordinator.process_signals(
            current_positions,
            pending_orders,
            current_time
        )

        # Should select top 2 (2 slots available)
        assert len(selected) == 2
        assert selected[0].symbol == 'ETHUSDT'  # Highest (0.90)
        assert selected[1].symbol == 'BTCUSDT'  # Second (0.85)

    def test_standard_fill_filter_existing(self, coordinator, mock_signal):
        """Test filtering signals for existing positions/pending."""
        signals = [
            mock_signal('BTCUSDT', 0.85),
            mock_signal('ETHUSDT', 0.90),
            mock_signal('SOLUSDT', 0.88)  # Already in position
        ]

        for signal in signals:
            coordinator.add_signal(signal)

        current_positions = {
            'SOLUSDT': {'symbol': 'SOLUSDT'}
        }

        current_time = datetime.utcnow()
        selected = coordinator.process_signals(
            current_positions,
            {},
            current_time
        )

        # Should exclude SOLUSDT
        assert len(selected) == 2
        assert all(s.symbol != 'SOLUSDT' for s in selected)


class TestSmartRecycling:
    """Test Smart Recycling logic (tank full)."""

    def test_smart_recycling_better_signal(self, coordinator, mock_signal):
        """Test recycling with better signal available."""
        # New signal with high confidence
        new_signal = mock_signal('BTCUSDT', 0.95)
        coordinator.add_signal(new_signal)

        # Tank full with 5 pending orders
        pending_orders = {
            'ETHUSDT': {'symbol': 'ETHUSDT', 'confidence': 0.85, 'target_price': 2000.0},
            'BNBUSDT': {'symbol': 'BNBUSDT', 'confidence': 0.80, 'target_price': 300.0},
            'ADAUSDT': {'symbol': 'ADAUSDT', 'confidence': 0.75, 'target_price': 0.5},
            'DOGEUSDT': {'symbol': 'DOGEUSDT', 'confidence': 0.70, 'target_price': 0.1},
            'XRPUSDT': {'symbol': 'XRPUSDT', 'confidence': 0.65, 'target_price': 0.6}  # Worst
        }

        # Update prices (not close to fill)
        for symbol, order in pending_orders.items():
            coordinator.update_price(symbol, order['target_price'] * 1.05)  # 5% away

        current_time = datetime.utcnow()
        selected = coordinator.process_signals(
            {},
            pending_orders,
            current_time
        )

        # Should recycle worst (XRPUSDT) for best new (BTCUSDT)
        assert len(selected) == 1
        assert selected[0].symbol == 'BTCUSDT'
        assert selected[0].confidence == 0.95

    def test_smart_recycling_no_better_signal(self, coordinator, mock_signal):
        """Test recycling with no better signal."""
        # New signal with low confidence
        new_signal = mock_signal('BTCUSDT', 0.60)
        coordinator.add_signal(new_signal)

        # Tank full with decent pending orders
        pending_orders = {
            'ETHUSDT': {'symbol': 'ETHUSDT', 'confidence': 0.85, 'target_price': 2000.0},
            'BNBUSDT': {'symbol': 'BNBUSDT', 'confidence': 0.80, 'target_price': 300.0},
            'ADAUSDT': {'symbol': 'ADAUSDT', 'confidence': 0.75, 'target_price': 0.5},
            'DOGEUSDT': {'symbol': 'DOGEUSDT', 'confidence': 0.70, 'target_price': 0.1},
            'XRPUSDT': {'symbol': 'XRPUSDT', 'confidence': 0.65, 'target_price': 0.6}  # Worst
        }

        # Update prices
        for symbol, order in pending_orders.items():
            coordinator.update_price(symbol, order['target_price'] * 1.05)

        current_time = datetime.utcnow()
        selected = coordinator.process_signals(
            {},
            pending_orders,
            current_time
        )

        # Should NOT recycle (new signal not 10% better than worst)
        # Worst: 0.65, threshold: 0.65 * 1.1 = 0.715, new: 0.60 < 0.715
        assert len(selected) == 0

    def test_smart_recycling_confidence_buffer(self, coordinator, mock_signal):
        """Test confidence buffer (10% requirement)."""
        # New signal slightly better than worst
        new_signal = mock_signal('BTCUSDT', 0.70)
        coordinator.add_signal(new_signal)

        pending_orders = {
            'ETHUSDT': {'symbol': 'ETHUSDT', 'confidence': 0.85, 'target_price': 2000.0},
            'BNBUSDT': {'symbol': 'BNBUSDT', 'confidence': 0.80, 'target_price': 300.0},
            'ADAUSDT': {'symbol': 'ADAUSDT', 'confidence': 0.75, 'target_price': 0.5},
            'DOGEUSDT': {'symbol': 'DOGEUSDT', 'confidence': 0.70, 'target_price': 0.1},
            'XRPUSDT': {'symbol': 'XRPUSDT', 'confidence': 0.65, 'target_price': 0.6}  # Worst
        }

        for symbol, order in pending_orders.items():
            coordinator.update_price(symbol, order['target_price'] * 1.05)

        current_time = datetime.utcnow()
        selected = coordinator.process_signals(
            {},
            pending_orders,
            current_time
        )

        # Should NOT recycle (0.70 < 0.65 * 1.1 = 0.715)
        assert len(selected) == 0


class TestProximitySentry:
    """Test Proximity Sentry (lock orders close to fill)."""

    def test_proximity_lock_prevents_recycling(self, coordinator, mock_signal):
        """Test that locked orders are not recycled."""
        # New signal with high confidence
        new_signal = mock_signal('BTCUSDT', 0.95)
        coordinator.add_signal(new_signal)

        # Tank full, worst order is LOCKED (close to fill)
        pending_orders = {
            'ETHUSDT': {'symbol': 'ETHUSDT', 'confidence': 0.85, 'target_price': 2000.0},
            'BNBUSDT': {'symbol': 'BNBUSDT', 'confidence': 0.80, 'target_price': 300.0},
            'ADAUSDT': {'symbol': 'ADAUSDT', 'confidence': 0.75, 'target_price': 0.5},
            'DOGEUSDT': {'symbol': 'DOGEUSDT', 'confidence': 0.70, 'target_price': 0.1},
            'XRPUSDT': {'symbol': 'XRPUSDT', 'confidence': 0.65, 'target_price': 0.6}  # Worst
        }

        # Update prices - XRPUSDT is LOCKED (within 0.2%)
        coordinator.update_price('ETHUSDT', 2100.0)  # 5% away
        coordinator.update_price('BNBUSDT', 315.0)   # 5% away
        coordinator.update_price('ADAUSDT', 0.525)   # 5% away
        coordinator.update_price('DOGEUSDT', 0.105)  # 5% away
        coordinator.update_price('XRPUSDT', 0.601)   # 0.17% away (LOCKED!)

        current_time = datetime.utcnow()
        selected = coordinator.process_signals(
            {},
            pending_orders,
            current_time
        )

        # Should recycle DOGEUSDT (second worst, not locked) instead of XRPUSDT
        assert len(selected) == 1
        assert selected[0].symbol == 'BTCUSDT'

    def test_all_orders_locked(self, coordinator, mock_signal):
        """Test when all orders are locked."""
        # New signal with high confidence
        new_signal = mock_signal('BTCUSDT', 0.95)
        coordinator.add_signal(new_signal)

        # Tank full (5 orders), ALL orders are LOCKED
        pending_orders = {
            'ETHUSDT': {'symbol': 'ETHUSDT', 'confidence': 0.85, 'target_price': 2000.0},
            'BNBUSDT': {'symbol': 'BNBUSDT', 'confidence': 0.80, 'target_price': 300.0},
            'ADAUSDT': {'symbol': 'ADAUSDT', 'confidence': 0.75, 'target_price': 0.5},
            'DOGEUSDT': {'symbol': 'DOGEUSDT', 'confidence': 0.70, 'target_price': 0.1},
            'XRPUSDT': {'symbol': 'XRPUSDT', 'confidence': 0.65, 'target_price': 0.6}
        }

        # All within 0.2%
        coordinator.update_price('ETHUSDT', 2001.0)  # 0.05% away
        coordinator.update_price('BNBUSDT', 300.5)   # 0.17% away
        coordinator.update_price('ADAUSDT', 0.5009)  # 0.18% away
        coordinator.update_price('DOGEUSDT', 0.1001) # 0.10% away
        coordinator.update_price('XRPUSDT', 0.601)   # 0.17% away

        current_time = datetime.utcnow()
        selected = coordinator.process_signals(
            {},
            pending_orders,
            current_time
        )

        # Should NOT recycle (all locked)
        assert len(selected) == 0

    def test_is_order_locked(self, coordinator):
        """Test _is_order_locked method."""
        order = {
            'symbol': 'BTCUSDT',
            'target_price': 100.0
        }

        # Not locked (5% away)
        coordinator.update_price('BTCUSDT', 105.0)
        assert not coordinator._is_order_locked('BTCUSDT', order)

        # Locked (0.1% away)
        coordinator.update_price('BTCUSDT', 100.1)
        assert coordinator._is_order_locked('BTCUSDT', order)

        # Locked (0.19% away)
        coordinator.update_price('BTCUSDT', 100.19)
        assert coordinator._is_order_locked('BTCUSDT', order)

        # Not locked (0.3% away)
        coordinator.update_price('BTCUSDT', 100.3)
        assert not coordinator._is_order_locked('BTCUSDT', order)


class TestConfiguration:
    """Test configuration options."""

    def test_smart_recycling_disabled(self, mock_signal):
        """Test with Smart Recycling disabled."""
        coordinator = SharkTankCoordinator(
            max_positions=3,
            enable_smart_recycling=False
        )

        # New signal with high confidence
        new_signal = mock_signal('BTCUSDT', 0.95)
        coordinator.add_signal(new_signal)

        # Tank full
        pending_orders = {
            'ETHUSDT': {'symbol': 'ETHUSDT', 'confidence': 0.85, 'target_price': 2000.0},
            'BNBUSDT': {'symbol': 'BNBUSDT', 'confidence': 0.80, 'target_price': 300.0},
            'ADAUSDT': {'symbol': 'ADAUSDT', 'confidence': 0.75, 'target_price': 0.5}
        }

        for symbol, order in pending_orders.items():
            coordinator.update_price(symbol, order['target_price'] * 1.05)

        current_time = datetime.utcnow()
        selected = coordinator.process_signals(
            {},
            pending_orders,
            current_time
        )

        # Should NOT recycle (disabled)
        assert len(selected) == 0

    def test_get_stats(self, coordinator, mock_signal):
        """Test get_stats method."""
        signal = mock_signal('BTCUSDT', 0.85)
        coordinator.add_signal(signal)

        stats = coordinator.get_stats()

        assert stats['buffer_size'] == 1
        assert stats['max_positions'] == 5
        assert stats['collection_window'] == 2.0
        assert stats['proximity_threshold'] == 0.002
        assert stats['confidence_buffer'] == 0.10
        assert stats['smart_recycling_enabled'] is True


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_pending_orders_full_tank(self, coordinator, mock_signal):
        """Test full tank with no pending orders (should not happen)."""
        new_signal = mock_signal('BTCUSDT', 0.95)
        coordinator.add_signal(new_signal)

        # 5 positions, no pending (edge case)
        current_positions = {
            f'SYM{i}USDT': {'symbol': f'SYM{i}USDT'}
            for i in range(5)
        }

        current_time = datetime.utcnow()
        selected = coordinator.process_signals(
            current_positions,
            {},
            current_time
        )

        # Should return empty (no pending to recycle)
        assert len(selected) == 0

    def test_signal_already_in_position(self, coordinator, mock_signal):
        """Test signal for symbol already in position."""
        signal = mock_signal('BTCUSDT', 0.85)
        coordinator.add_signal(signal)

        current_positions = {
            'BTCUSDT': {'symbol': 'BTCUSDT'}
        }

        current_time = datetime.utcnow()
        selected = coordinator.process_signals(
            current_positions,
            {},
            current_time
        )

        # Should filter out BTCUSDT
        assert len(selected) == 0

    def test_buffer_cleared_after_process(self, coordinator, mock_signal):
        """Test buffer is cleared after processing."""
        signals = [
            mock_signal('BTCUSDT', 0.85),
            mock_signal('ETHUSDT', 0.90)
        ]

        for signal in signals:
            coordinator.add_signal(signal)

        assert len(coordinator._signal_buffer) == 2

        current_time = datetime.utcnow()
        coordinator.process_signals({}, {}, current_time)

        # Buffer should be cleared
        assert len(coordinator._signal_buffer) == 0
