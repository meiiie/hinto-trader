"""
Test SharkTank Recycling Disabled by Default

SOTA FIX (Jan 2026): Verify that Smart Recycling is disabled by default
to match backtest behavior and prevent over-trading.

Created: 2026-01-19
Purpose: Ensure LIVE doesn't over-trade due to recycling
"""

import pytest
from datetime import datetime
from src.application.services.shark_tank_coordinator import SharkTankCoordinator, BatchedSignal
from src.domain.entities.trading_signal import TradingSignal, SignalType


class TestSharkTankRecyclingDisabled:
    """Test that recycling is disabled by default."""

    def test_recycling_disabled_by_default(self):
        """Verify recycling is OFF when not explicitly enabled."""
        shark_tank = SharkTankCoordinator(max_positions=3)

        # Check flag
        assert shark_tank.enable_recycling is False, "Recycling should be disabled by default"

    def test_recycling_can_be_enabled(self):
        """Verify recycling can be explicitly enabled."""
        shark_tank = SharkTankCoordinator(max_positions=3, enable_recycling=True)

        # Check flag
        assert shark_tank.enable_recycling is True, "Recycling should be enabled when specified"

    def test_no_recycling_when_slots_full(self):
        """
        When slots are full and recycling is disabled,
        new signals should be DISCARDED (not swapped).
        """
        executed_signals = []
        cancelled_symbols = []

        def mock_execute(signal: TradingSignal):
            executed_signals.append(signal.symbol)

        def mock_get_positions():
            return 3  # All slots full

        def mock_cancel(symbol: str):
            cancelled_symbols.append(symbol)
            return True

        def mock_get_pending():
            # Return 3 pending orders with low confidence
            return [
                {'symbol': 'BTCUSDT', 'confidence': 0.70},
                {'symbol': 'ETHUSDT', 'confidence': 0.65},
                {'symbol': 'SOLUSDT', 'confidence': 0.60}
            ]

        # Create SharkTank with recycling DISABLED (default)
        shark_tank = SharkTankCoordinator(max_positions=3)
        shark_tank.set_callbacks(
            execute_callback=mock_execute,
            get_open_positions_callback=mock_get_positions,
            get_pending_orders_callback=mock_get_pending,
            cancel_order_callback=mock_cancel
        )

        # Queue high-confidence signal (better than all pending)
        signal = TradingSignal(
            symbol='BNBUSDT',
            signal_type=SignalType.BUY,
            price=100.0,
            entry_price=100.0,
            stop_loss=95.0,
            tp_levels={'tp1': 105.0, 'tp2': 110.0},
            confidence=0.95,  # Much better than pending (0.60-0.70)
            generated_at=datetime.now()
        )

        # Manually add to batch (bypass async timer)
        shark_tank._pending_signals['BNBUSDT'] = BatchedSignal(
            signal=signal,
            symbol='BNBUSDT',
            received_at=datetime.now(),
            confidence=0.95
        )

        # Force process batch (synchronous)
        shark_tank.force_process()

        # Verify: NO execution (recycling disabled)
        assert len(executed_signals) == 0, "Should not execute when slots full and recycling disabled"

        # Verify: NO cancellation (recycling disabled)
        assert len(cancelled_symbols) == 0, "Should not cancel when recycling disabled"

    def test_recycling_works_when_enabled(self):
        """
        When slots are full and recycling is ENABLED,
        worst pending should be swapped with best new signal.
        """
        executed_signals = []
        cancelled_symbols = []

        def mock_execute(signal: TradingSignal):
            executed_signals.append(signal.symbol)

        def mock_get_positions():
            return 3  # All slots full

        def mock_cancel(symbol: str):
            cancelled_symbols.append(symbol)
            return True

        def mock_get_pending():
            # Return 3 pending orders with low confidence
            return [
                {'symbol': 'BTCUSDT', 'confidence': 0.70},
                {'symbol': 'ETHUSDT', 'confidence': 0.65},
                {'symbol': 'SOLUSDT', 'confidence': 0.60}  # Worst
            ]

        def mock_get_prices():
            return {
                'BTCUSDT': 50000.0,
                'ETHUSDT': 3000.0,
                'SOLUSDT': 100.0,
                'BNBUSDT': 400.0
            }

        # Create SharkTank with recycling ENABLED
        shark_tank = SharkTankCoordinator(max_positions=3, enable_recycling=True)
        shark_tank.set_callbacks(
            execute_callback=mock_execute,
            get_open_positions_callback=mock_get_positions,
            get_pending_orders_callback=mock_get_pending,
            cancel_order_callback=mock_cancel,
            get_current_prices_callback=mock_get_prices
        )

        # Queue high-confidence signal (better than worst pending)
        signal = TradingSignal(
            symbol='BNBUSDT',
            signal_type=SignalType.BUY,
            price=400.0,
            entry_price=400.0,
            stop_loss=380.0,
            tp_levels={'tp1': 420.0, 'tp2': 440.0},
            confidence=0.95,  # Much better than worst (0.60)
            generated_at=datetime.now()
        )

        # Manually add to batch (bypass async timer)
        shark_tank._pending_signals['BNBUSDT'] = BatchedSignal(
            signal=signal,
            symbol='BNBUSDT',
            received_at=datetime.now(),
            confidence=0.95
        )

        # Force process batch (synchronous)
        shark_tank.force_process()

        # Verify: Worst pending was cancelled
        assert 'SOLUSDT' in cancelled_symbols, "Should cancel worst pending when recycling enabled"

        # Verify: Best new signal was executed
        assert 'BNBUSDT' in executed_signals, "Should execute best new signal when recycling enabled"

    def test_batch_discards_when_slots_full_no_recycling(self):
        """
        Verify that when slots are full and recycling is disabled,
        ALL new signals are discarded (matches backtest behavior).
        """
        executed_signals = []

        def mock_execute(signal: TradingSignal):
            executed_signals.append(signal.symbol)

        def mock_get_positions():
            return 3  # All slots full

        # Create SharkTank with recycling DISABLED
        shark_tank = SharkTankCoordinator(max_positions=3, enable_recycling=False)
        shark_tank.set_callbacks(
            execute_callback=mock_execute,
            get_open_positions_callback=mock_get_positions
        )

        # Queue 5 high-confidence signals
        symbols = ['BNBUSDT', 'ADAUSDT', 'DOGEUSDT', 'MATICUSDT', 'AVAXUSDT']
        for i, symbol in enumerate(symbols):
            signal = TradingSignal(
                symbol=symbol,
                signal_type=SignalType.BUY,
                price=100.0,
                entry_price=100.0,
                stop_loss=95.0,
                tp_levels={'tp1': 105.0, 'tp2': 110.0},
                confidence=0.90 + i * 0.01,  # All high confidence
                generated_at=datetime.now()
            )
            # Manually add to batch (bypass async timer)
            shark_tank._pending_signals[symbol] = BatchedSignal(
                signal=signal,
                symbol=symbol,
                received_at=datetime.now(),
                confidence=0.90 + i * 0.01
            )

        # Force process batch (synchronous)
        shark_tank.force_process()

        # Verify: NO signals executed (all discarded)
        assert len(executed_signals) == 0, "Should discard all signals when slots full and recycling disabled"

        # Verify: Batch was cleared
        assert shark_tank.get_pending_count() == 0, "Batch should be cleared after processing"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
