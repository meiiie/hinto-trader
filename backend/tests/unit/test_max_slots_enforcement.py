"""
Test: Max Slots Enforcement Fix

CRITICAL BUG FIX (Jan 2026):
- Bug: max_positions=5 but system allowed 8 slots (3 positions + 5 pending)
- Root cause: LocalSignalTracker only counted pending, not positions
- Fix: Added get_total_slots_callback to count positions + pending

This test verifies the fix works correctly.
"""

import pytest
from backend.src.application.services.local_signal_tracker import (
    LocalSignalTracker,
    SignalDirection,
    PendingSignal
)


class TestMaxSlotsEnforcement:
    """Test that max_positions is enforced correctly (positions + pending)."""

    def test_block_signal_when_positions_plus_pending_equals_max(self):
        """
        CRITICAL TEST: If 3 positions + 2 pending = 5 (max), new signal should be blocked.

        This was the bug: LocalSignalTracker only checked pending count,
        allowing 5 pending even when 3 positions existed (total 8 slots).
        """
        # Simulate: 3 positions, 2 pending, max=5
        def get_total_slots():
            return (3, 2)  # 3 positions + 2 pending = 5 total

        tracker = LocalSignalTracker(
            max_pending=5,
            enable_recycling=False,
            get_total_slots_callback=get_total_slots
        )

        # Add 2 pending signals (to match the callback)
        tracker.pending_signals['BTCUSDT'] = PendingSignal(
            symbol='BTCUSDT', direction=SignalDirection.LONG,
            target_price=100, stop_loss=95, take_profit=110, quantity=1
        )
        tracker.pending_signals['ETHUSDT'] = PendingSignal(
            symbol='ETHUSDT', direction=SignalDirection.LONG,
            target_price=100, stop_loss=95, take_profit=110, quantity=1
        )

        # Try to add new signal - should be BLOCKED (3+2=5 >= max=5)
        result = tracker.add_signal(
            symbol='SOLUSDT',
            direction=SignalDirection.LONG,
            target_price=100,
            stop_loss=95,
            take_profit=110,
            quantity=1
        )

        assert result is None, "Signal should be blocked when positions + pending >= max"
        assert 'SOLUSDT' not in tracker.pending_signals
        assert tracker._signals_blocked_by_max_slots == 1

    def test_allow_signal_when_positions_plus_pending_below_max(self):
        """
        If 2 positions + 2 pending = 4 (< max=5), new signal should be allowed.
        """
        # Simulate: 2 positions, 2 pending, max=5
        def get_total_slots():
            return (2, 2)  # 2 positions + 2 pending = 4 total

        tracker = LocalSignalTracker(
            max_pending=5,
            enable_recycling=False,
            get_total_slots_callback=get_total_slots
        )

        # Add 2 pending signals (to match the callback)
        tracker.pending_signals['BTCUSDT'] = PendingSignal(
            symbol='BTCUSDT', direction=SignalDirection.LONG,
            target_price=100, stop_loss=95, take_profit=110, quantity=1
        )
        tracker.pending_signals['ETHUSDT'] = PendingSignal(
            symbol='ETHUSDT', direction=SignalDirection.LONG,
            target_price=100, stop_loss=95, take_profit=110, quantity=1
        )

        # Try to add new signal - should be ALLOWED (2+2=4 < max=5)
        result = tracker.add_signal(
            symbol='SOLUSDT',
            direction=SignalDirection.LONG,
            target_price=100,
            stop_loss=95,
            take_profit=110,
            quantity=1
        )

        assert result is not None, "Signal should be allowed when positions + pending < max"
        assert 'SOLUSDT' in tracker.pending_signals

    def test_block_signal_when_only_positions_at_max(self):
        """
        If 5 positions + 0 pending = 5 (max), new signal should be blocked.
        """
        # Simulate: 5 positions, 0 pending, max=5
        def get_total_slots():
            return (5, 0)  # 5 positions + 0 pending = 5 total

        tracker = LocalSignalTracker(
            max_pending=5,
            enable_recycling=False,
            get_total_slots_callback=get_total_slots
        )

        # Try to add new signal - should be BLOCKED (5+0=5 >= max=5)
        result = tracker.add_signal(
            symbol='BTCUSDT',
            direction=SignalDirection.LONG,
            target_price=100,
            stop_loss=95,
            take_profit=110,
            quantity=1
        )

        assert result is None, "Signal should be blocked when positions alone >= max"
        assert 'BTCUSDT' not in tracker.pending_signals

    def test_fallback_to_pending_count_without_callback(self):
        """
        Without callback, should fallback to counting only pending (legacy behavior).
        """
        tracker = LocalSignalTracker(
            max_pending=3,
            enable_recycling=False,
            get_total_slots_callback=None  # No callback
        )

        # Add 3 pending signals
        for i, symbol in enumerate(['BTCUSDT', 'ETHUSDT', 'SOLUSDT']):
            tracker.pending_signals[symbol] = PendingSignal(
                symbol=symbol, direction=SignalDirection.LONG,
                target_price=100, stop_loss=95, take_profit=110, quantity=1
            )

        # Try to add 4th signal - should be blocked (3 pending >= max=3)
        result = tracker.add_signal(
            symbol='XRPUSDT',
            direction=SignalDirection.LONG,
            target_price=100,
            stop_loss=95,
            take_profit=110,
            quantity=1
        )

        assert result is None, "Signal should be blocked when pending >= max (legacy)"

    def test_exact_scenario_from_bug_report(self):
        """
        Exact scenario from bug report:
        - max_positions = 5
        - 3 positions (BCH, DOGE, US)
        - 5 pending (市安人生, LIT, POL, PIPPIN, CLO)
        - Total = 8 slots (should have been blocked at 5!)

        With fix, after 3 positions + 2 pending = 5, no more should be allowed.
        """
        positions_count = 3  # BCH, DOGE, US
        pending_count = 0

        def get_total_slots():
            return (positions_count, pending_count)

        tracker = LocalSignalTracker(
            max_pending=5,
            enable_recycling=False,
            get_total_slots_callback=get_total_slots
        )

        # Add pending signals one by one
        symbols = ['市安人生USDT', 'LITUSDT', 'POLUSDT', 'PIPPINUSDT', 'CLOUSDT']
        added_count = 0

        for symbol in symbols:
            # Update pending count for callback
            pending_count = len(tracker.pending_signals)

            result = tracker.add_signal(
                symbol=symbol,
                direction=SignalDirection.SHORT,
                target_price=100,
                stop_loss=105,
                take_profit=90,
                quantity=1
            )

            if result is not None:
                added_count += 1

        # With 3 positions, only 2 pending should be allowed (3+2=5)
        assert added_count == 2, f"Only 2 pending should be allowed with 3 positions, got {added_count}"
        assert len(tracker.pending_signals) == 2

        # Total slots should be exactly 5
        total = positions_count + len(tracker.pending_signals)
        assert total == 5, f"Total slots should be 5, got {total}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
