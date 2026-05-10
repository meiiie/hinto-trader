"""
Integration Tests: Auto-Close Feature in BACKTEST Mode

Tests the complete auto-close flow in backtest mode:
- Position opens
- ROE increases above threshold
- Position closes automatically
- Exit reason is correct
- Log format matches expected output

SOTA (Jan 2026): Integration tests validate end-to-end flows.
"""

import pytest
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_path))

from src.application.backtest.execution_simulator import ExecutionSimulator
from src.domain.entities.trading_signal import TradingSignal, SignalType


class TestAutoCloseBacktestIntegration:
    """Integration tests for auto-close feature in BACKTEST mode."""

    def test_backtest_auto_close_end_to_end_long(self):
        """
        Test 7.1: BACKTEST auto-close end-to-end (LONG position).

        Scenario:
        1. Open LONG position at $100
        2. Price rises to $110 (10% gain)
        3. With 10x leverage, ROE = 100%
        4. With threshold = 5%, position should close
        5. Exit reason should be "AUTO_CLOSE_PROFITABLE"
        """
        # Setup
        simulator = ExecutionSimulator(
            initial_balance=10000,
            fixed_leverage=10.0,
            risk_per_trade=0.01,
            max_positions=5,
            close_profitable_auto=True,
            profitable_threshold_pct=5.0
        )

        # Create LONG signal
        signal = TradingSignal(
            symbol='BTCUSDT',
            signal_type=SignalType.LONG,
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            confidence=0.8,
            timestamp=datetime.now(timezone.utc)
        )

        # Execute entry
        result = simulator.execute_signal(signal)
        assert result.success, f"Entry failed: {result.error}"
        assert 'BTCUSDT' in simulator.positions

        # Verify position opened
        position = simulator.positions['BTCUSDT']
        assert position.entry_price == 100.0
        assert position.side == 'LONG'

        # Simulate price update to $110 (10% gain, 100% ROE with 10x leverage)
        # This should trigger auto-close since ROE (100%) > threshold (5%)
        simulator._check_auto_close_profitable('BTCUSDT', current_price=110.0)

        # Verify position closed
        assert 'BTCUSDT' not in simulator.positions, "Position should be closed"

        # Verify trade history
        assert len(simulator.closed_trades) == 1
        trade = simulator.closed_trades[0]
        assert trade.symbol == 'BTCUSDT'
        assert trade.exit_reason == 'AUTO_CLOSE_PROFITABLE'
        assert trade.exit_price == 110.0
        assert trade.pnl_usd > 0, "Trade should be profitable"

    def test_backtest_auto_close_end_to_end_short(self):
        """
        Test 7.1: BACKTEST auto-close end-to-end (SHORT position).

        Scenario:
        1. Open SHORT position at $100
        2. Price drops to $90 (10% gain for SHORT)
        3. With 10x leverage, ROE = 100%
        4. With threshold = 5%, position should close
        5. Exit reason should be "AUTO_CLOSE_PROFITABLE"
        """
        # Setup
        simulator = ExecutionSimulator(
            initial_balance=10000,
            fixed_leverage=10.0,
            risk_per_trade=0.01,
            max_positions=5,
            close_profitable_auto=True,
            profitable_threshold_pct=5.0
        )

        # Create SHORT signal
        signal = TradingSignal(
            symbol='ETHUSDT',
            signal_type=SignalType.SHORT,
            entry_price=100.0,
            stop_loss=105.0,
            take_profit=90.0,
            confidence=0.8,
            timestamp=datetime.now(timezone.utc)
        )

        # Execute entry
        result = simulator.execute_signal(signal)
        assert result.success, f"Entry failed: {result.error}"
        assert 'ETHUSDT' in simulator.positions

        # Verify position opened
        position = simulator.positions['ETHUSDT']
        assert position.entry_price == 100.0
        assert position.side == 'SHORT'

        # Simulate price update to $90 (10% gain for SHORT, 100% ROE with 10x leverage)
        simulator._check_auto_close_profitable('ETHUSDT', current_price=90.0)

        # Verify position closed
        assert 'ETHUSDT' not in simulator.positions, "Position should be closed"

        # Verify trade history
        assert len(simulator.closed_trades) == 1
        trade = simulator.closed_trades[0]
        assert trade.symbol == 'ETHUSDT'
        assert trade.exit_reason == 'AUTO_CLOSE_PROFITABLE'
        assert trade.exit_price == 90.0
        assert trade.pnl_usd > 0, "Trade should be profitable"

    def test_backtest_auto_close_not_triggered_below_threshold(self):
        """
        Test 7.1: Verify auto-close does NOT trigger when ROE < threshold.

        Scenario:
        1. Open LONG position at $100
        2. Price rises to $101 (1% gain)
        3. With 10x leverage, ROE = 10%
        4. With threshold = 15%, position should NOT close
        """
        # Setup with higher threshold
        simulator = ExecutionSimulator(
            initial_balance=10000,
            fixed_leverage=10.0,
            risk_per_trade=0.01,
            max_positions=5,
            close_profitable_auto=True,
            profitable_threshold_pct=15.0  # Higher threshold
        )

        # Create LONG signal
        signal = TradingSignal(
            symbol='BTCUSDT',
            signal_type=SignalType.LONG,
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            confidence=0.8,
            timestamp=datetime.now(timezone.utc)
        )

        # Execute entry
        result = simulator.execute_signal(signal)
        assert result.success

        # Simulate price update to $101 (1% gain, 10% ROE with 10x leverage)
        # ROE (10%) < threshold (15%), should NOT close
        simulator._check_auto_close_profitable('BTCUSDT', current_price=101.0)

        # Verify position still open
        assert 'BTCUSDT' in simulator.positions, "Position should still be open"
        assert len(simulator.closed_trades) == 0, "No trades should be closed"

    def test_backtest_auto_close_disabled(self):
        """
        Test 7.1: Verify auto-close does NOT trigger when feature is disabled.

        Scenario:
        1. Open LONG position at $100
        2. Price rises to $110 (10% gain, 100% ROE)
        3. Feature is disabled
        4. Position should NOT close
        """
        # Setup with feature disabled
        simulator = ExecutionSimulator(
            initial_balance=10000,
            fixed_leverage=10.0,
            risk_per_trade=0.01,
            max_positions=5,
            close_profitable_auto=False,  # Disabled
            profitable_threshold_pct=5.0
        )

        # Create LONG signal
        signal = TradingSignal(
            symbol='BTCUSDT',
            signal_type=SignalType.LONG,
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            confidence=0.8,
            timestamp=datetime.now(timezone.utc)
        )

        # Execute entry
        result = simulator.execute_signal(signal)
        assert result.success

        # Simulate price update to $110 (100% ROE)
        # Feature disabled, should NOT close
        simulator._check_auto_close_profitable('BTCUSDT', current_price=110.0)

        # Verify position still open
        assert 'BTCUSDT' in simulator.positions, "Position should still be open"
        assert len(simulator.closed_trades) == 0, "No trades should be closed"

    def test_backtest_auto_close_negative_pnl_never_closes(self):
        """
        Test 7.1: Verify auto-close NEVER triggers for losing positions.

        Scenario:
        1. Open LONG position at $100
        2. Price drops to $90 (10% loss)
        3. Even with high threshold, position should NOT close
        4. Only profitable positions should auto-close
        """
        # Setup
        simulator = ExecutionSimulator(
            initial_balance=10000,
            fixed_leverage=10.0,
            risk_per_trade=0.01,
            max_positions=5,
            close_profitable_auto=True,
            profitable_threshold_pct=1.0  # Very low threshold
        )

        # Create LONG signal
        signal = TradingSignal(
            symbol='BTCUSDT',
            signal_type=SignalType.LONG,
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            confidence=0.8,
            timestamp=datetime.now(timezone.utc)
        )

        # Execute entry
        result = simulator.execute_signal(signal)
        assert result.success

        # Simulate price update to $90 (10% loss)
        # Negative PnL, should NEVER close
        simulator._check_auto_close_profitable('BTCUSDT', current_price=90.0)

        # Verify position still open
        assert 'BTCUSDT' in simulator.positions, "Losing position should NOT auto-close"
        assert len(simulator.closed_trades) == 0, "No trades should be closed"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
