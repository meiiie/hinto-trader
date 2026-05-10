"""
Unit tests for SharkTank Filter Gap Fix (Jan 2026)

Bug: SharkTank in LIVE was missing filter to exclude signals from symbols
that already have open positions or pending orders.

BACKTEST has this filter:
    candidates = [s for s in signals
                  if s.symbol not in self.positions
                  and s.symbol not in self.pending_orders]

LIVE (SharkTank) was missing this filter, causing:
1. Slot waste - signals from symbols with positions take slots
2. Wrong ranking - invalid signals participate in ranking
3. Smart recycling bugs - invalid signals can trigger recycle

Fix: Added filter logic in SharkTankCoordinator._process_batch()
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import MagicMock, patch
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.application.services.shark_tank_coordinator import SharkTankCoordinator, BatchedSignal
from src.domain.entities.trading_signal import TradingSignal, SignalType


def create_test_signal(symbol: str, confidence: float, signal_type: SignalType = SignalType.BUY) -> TradingSignal:
    """Create a test trading signal."""
    return TradingSignal(
        symbol=symbol,
        signal_type=signal_type,
        price=100.0,
        entry_price=100.0,
        stop_loss=95.0,
        tp_levels=[105.0, 110.0],
        confidence=confidence,
        generated_at=datetime.now(),
        indicators={}
    )


class TestSharkTankFilterGapFix:
    """Test suite for SharkTank filter gap fix."""

    def test_filter_signals_with_existing_position(self):
        """
        Signals from symbols with open positions should be filtered out.

        Scenario:
        - BTCUSDT has open position
        - Signals: BTCUSDT (conf=0.95), ETHUSDT (conf=0.90)
        - Expected: Only ETHUSDT should be executed
        """
        executed_signals = []

        def mock_execute(signal):
            executed_signals.append(signal.symbol)

        shark_tank = SharkTankCoordinator(max_positions=3)
        shark_tank.set_callbacks(
            execute_callback=mock_execute,
            get_open_positions_callback=lambda: 1,  # 1 position (BTCUSDT)
            get_available_margin_callback=lambda: 1000.0,
            get_pending_orders_callback=lambda: [],
            get_current_prices_callback=lambda: {},
            cancel_order_callback=lambda s: True,
            get_position_symbols_callback=lambda: {'BTCUSDT'}  # BTCUSDT has position
        )

        # Add signals directly to _pending_signals (bypass collect_signal async)
        btc_signal = create_test_signal('BTCUSDT', 0.95)
        eth_signal = create_test_signal('ETHUSDT', 0.90)

        shark_tank._pending_signals['BTCUSDT'] = BatchedSignal(
            signal=btc_signal, symbol='BTCUSDT',
            received_at=datetime.now(), confidence=0.95
        )
        shark_tank._pending_signals['ETHUSDT'] = BatchedSignal(
            signal=eth_signal, symbol='ETHUSDT',
            received_at=datetime.now(), confidence=0.90
        )

        # Call _process_batch directly (not force_process which uses lock)
        shark_tank._process_batch()

        # Verify: Only ETHUSDT should be executed
        assert 'ETHUSDT' in executed_signals, f"ETHUSDT should be executed, got: {executed_signals}"
        assert 'BTCUSDT' not in executed_signals, "BTCUSDT should be filtered (has position)"

    def test_filter_signals_with_existing_pending(self):
        """
        Signals from symbols with pending orders should be filtered out.

        Scenario:
        - XRPUSDT has pending order
        - Signals: XRPUSDT (conf=0.85), ADAUSDT (conf=0.80)
        - Expected: Only ADAUSDT should be executed
        """
        executed_signals = []

        def mock_execute(signal):
            executed_signals.append(signal.symbol)

        shark_tank = SharkTankCoordinator(max_positions=3)
        shark_tank.set_callbacks(
            execute_callback=mock_execute,
            get_open_positions_callback=lambda: 1,  # 1 pending
            get_available_margin_callback=lambda: 1000.0,
            get_pending_orders_callback=lambda: [{'symbol': 'XRPUSDT', 'confidence': 0.7}],
            get_current_prices_callback=lambda: {},
            cancel_order_callback=lambda s: True,
            get_position_symbols_callback=lambda: set()  # No positions
        )

        # Add signals directly
        xrp_signal = create_test_signal('XRPUSDT', 0.85)
        ada_signal = create_test_signal('ADAUSDT', 0.80)

        shark_tank._pending_signals['XRPUSDT'] = BatchedSignal(
            signal=xrp_signal, symbol='XRPUSDT',
            received_at=datetime.now(), confidence=0.85
        )
        shark_tank._pending_signals['ADAUSDT'] = BatchedSignal(
            signal=ada_signal, symbol='ADAUSDT',
            received_at=datetime.now(), confidence=0.80
        )

        # Call _process_batch directly
        shark_tank._process_batch()

        # Verify: Only ADAUSDT should be executed
        assert 'ADAUSDT' in executed_signals, f"ADAUSDT should be executed, got: {executed_signals}"
        assert 'XRPUSDT' not in executed_signals, "XRPUSDT should be filtered (has pending)"

    def test_ranking_only_considers_filtered_signals(self):
        """
        Ranking should only consider signals that pass the filter.

        Scenario:
        - BTCUSDT has position
        - Signals: BTCUSDT (conf=0.95), ETHUSDT (conf=0.90), SOLUSDT (conf=0.85)
        - Only 1 slot available
        - Expected: ETHUSDT should be executed (highest conf among valid signals)
        """
        executed_signals = []

        def mock_execute(signal):
            executed_signals.append(signal.symbol)

        shark_tank = SharkTankCoordinator(max_positions=2)
        shark_tank.set_callbacks(
            execute_callback=mock_execute,
            get_open_positions_callback=lambda: 1,  # 1 position, 1 slot available
            get_available_margin_callback=lambda: 1000.0,
            get_pending_orders_callback=lambda: [],
            get_current_prices_callback=lambda: {},
            cancel_order_callback=lambda s: True,
            get_position_symbols_callback=lambda: {'BTCUSDT'}  # BTCUSDT has position
        )

        # Add signals directly - BTCUSDT has highest conf but should be filtered
        btc_signal = create_test_signal('BTCUSDT', 0.95)
        eth_signal = create_test_signal('ETHUSDT', 0.90)
        sol_signal = create_test_signal('SOLUSDT', 0.85)

        shark_tank._pending_signals['BTCUSDT'] = BatchedSignal(
            signal=btc_signal, symbol='BTCUSDT',
            received_at=datetime.now(), confidence=0.95
        )
        shark_tank._pending_signals['ETHUSDT'] = BatchedSignal(
            signal=eth_signal, symbol='ETHUSDT',
            received_at=datetime.now(), confidence=0.90
        )
        shark_tank._pending_signals['SOLUSDT'] = BatchedSignal(
            signal=sol_signal, symbol='SOLUSDT',
            received_at=datetime.now(), confidence=0.85
        )

        # Call _process_batch directly
        shark_tank._process_batch()

        # Verify: ETHUSDT should be executed (highest among valid)
        assert 'ETHUSDT' in executed_signals, f"ETHUSDT should be executed (highest valid conf), got: {executed_signals}"
        assert 'BTCUSDT' not in executed_signals, "BTCUSDT should be filtered"
        # SOLUSDT may or may not be executed depending on slots

    def test_all_signals_filtered_out(self):
        """
        When all signals are from symbols with positions/pending, none should execute.
        """
        executed_signals = []

        def mock_execute(signal):
            executed_signals.append(signal.symbol)

        shark_tank = SharkTankCoordinator(max_positions=3)
        shark_tank.set_callbacks(
            execute_callback=mock_execute,
            get_open_positions_callback=lambda: 2,
            get_available_margin_callback=lambda: 1000.0,
            get_pending_orders_callback=lambda: [],
            get_current_prices_callback=lambda: {},
            cancel_order_callback=lambda s: True,
            get_position_symbols_callback=lambda: {'BTCUSDT', 'ETHUSDT'}  # Both have positions
        )

        # Add signals directly - all from symbols with positions
        btc_signal = create_test_signal('BTCUSDT', 0.95)
        eth_signal = create_test_signal('ETHUSDT', 0.90)

        shark_tank._pending_signals['BTCUSDT'] = BatchedSignal(
            signal=btc_signal, symbol='BTCUSDT',
            received_at=datetime.now(), confidence=0.95
        )
        shark_tank._pending_signals['ETHUSDT'] = BatchedSignal(
            signal=eth_signal, symbol='ETHUSDT',
            received_at=datetime.now(), confidence=0.90
        )

        # Call _process_batch directly
        shark_tank._process_batch()

        # Verify: No signals should be executed
        assert len(executed_signals) == 0, "No signals should be executed when all are filtered"

    def test_filter_with_no_callback(self):
        """
        When position callback is not set, filter should gracefully skip.
        """
        executed_signals = []

        def mock_execute(signal):
            executed_signals.append(signal.symbol)

        shark_tank = SharkTankCoordinator(max_positions=3)
        shark_tank.set_callbacks(
            execute_callback=mock_execute,
            get_open_positions_callback=lambda: 0,
            get_available_margin_callback=lambda: 1000.0,
            get_pending_orders_callback=None,  # No callback
            get_current_prices_callback=None,
            cancel_order_callback=None,
            get_position_symbols_callback=None  # No callback
        )

        # Add signal directly
        btc_signal = create_test_signal('BTCUSDT', 0.95)
        shark_tank._pending_signals['BTCUSDT'] = BatchedSignal(
            signal=btc_signal, symbol='BTCUSDT',
            received_at=datetime.now(), confidence=0.95
        )

        # Call _process_batch directly - should not crash
        shark_tank._process_batch()

        # Signal should be executed (no filter applied)
        assert 'BTCUSDT' in executed_signals, f"BTCUSDT should be executed, got: {executed_signals}"


class TestLocalSignalTrackerPositionCheck:
    """Test LocalSignalTracker position check (defense in depth)."""

    def test_block_signal_with_open_position(self):
        """
        LocalSignalTracker should block signals for symbols with open positions.
        """
        from src.application.services.local_signal_tracker import (
            LocalSignalTracker, SignalDirection
        )

        # Mock position check - BTCUSDT has position
        def has_position(symbol: str) -> bool:
            return symbol.upper() == 'BTCUSDT'

        tracker = LocalSignalTracker(
            max_pending=10,
            has_position_callback=has_position
        )

        # Try to add signal for BTCUSDT (has position)
        result = tracker.add_signal(
            symbol='BTCUSDT',
            direction=SignalDirection.LONG,
            target_price=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            quantity=0.1,
            confidence=0.9
        )

        # Should be blocked
        assert result is None, "Signal should be blocked (symbol has position)"
        assert tracker._signals_blocked_by_position == 1
        assert 'BTCUSDT' not in tracker.pending_signals

    def test_allow_signal_without_position(self):
        """
        LocalSignalTracker should allow signals for symbols without positions.
        """
        from src.application.services.local_signal_tracker import (
            LocalSignalTracker, SignalDirection
        )

        # Mock position check - no positions
        def has_position(symbol: str) -> bool:
            return False

        tracker = LocalSignalTracker(
            max_pending=10,
            has_position_callback=has_position
        )

        # Add signal for ETHUSDT (no position)
        result = tracker.add_signal(
            symbol='ETHUSDT',
            direction=SignalDirection.LONG,
            target_price=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            quantity=0.1,
            confidence=0.9
        )

        # Should be allowed
        assert result is not None, "Signal should be allowed (no position)"
        assert 'ETHUSDT' in tracker.pending_signals


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
