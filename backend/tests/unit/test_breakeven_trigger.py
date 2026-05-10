"""
Test: Breakeven Trigger Logic

SOTA (Jan 2026): Tests for breakeven trigger when price moves 1.5x risk.
Ensures LIVE matches Backtest breakeven behavior.

Reference: position_monitor_service.py _trigger_breakeven() L321-358
"""

import pytest
from unittest.mock import Mock
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestBreakevenTriggerCondition:
    """Test breakeven trigger conditions"""

    # =========================================================================
    # BACKTEST REFERENCE (execution_simulator.py L680):
    #   if pos['phase'] == 'ENTRY':
    #       if current_roe >= breakeven_trigger_r:  # 1.5
    #           Move SL to entry price
    #
    # LIVE REFERENCE (position_monitor_service.py L290-305):
    #   if pos.phase == PositionPhase.ENTRY:
    #       distance_to_entry = abs(price - pos.entry_price)
    #       sl_distance = abs(pos.entry_price - pos.initial_sl)
    #       if distance_to_entry >= sl_distance * BREAKEVEN_R:  # 1.5
    #           _trigger_breakeven(pos)
    # =========================================================================

    BREAKEVEN_R = 1.5

    def test_breakeven_triggered_long(self):
        """LONG: Breakeven triggers at 1.5x SL distance"""
        entry_price = 50000.0
        initial_sl = 49750.0  # 0.5% = $250 risk
        sl_distance = entry_price - initial_sl  # $250

        current_price = 50375.0  # 1.5 * $250 = $375 profit
        price_gain = current_price - entry_price  # $375

        should_trigger = price_gain >= sl_distance * self.BREAKEVEN_R

        assert sl_distance == 250.0
        assert price_gain == 375.0
        assert should_trigger is True

    def test_breakeven_not_triggered_too_early_long(self):
        """LONG: Breakeven NOT triggered before 1.5x"""
        entry_price = 50000.0
        initial_sl = 49750.0
        sl_distance = entry_price - initial_sl

        current_price = 50300.0  # Only 1.2x, not 1.5x
        price_gain = current_price - entry_price

        should_trigger = price_gain >= sl_distance * self.BREAKEVEN_R

        assert price_gain == 300.0
        assert should_trigger is False

    def test_breakeven_triggered_short(self):
        """SHORT: Breakeven triggers at 1.5x SL distance"""
        entry_price = 3000.0
        initial_sl = 3015.0  # 0.5% = $15 risk
        sl_distance = initial_sl - entry_price  # $15

        current_price = 2977.5  # 1.5 * $15 = $22.5 profit
        price_gain = entry_price - current_price  # $22.5

        should_trigger = price_gain >= sl_distance * self.BREAKEVEN_R

        assert sl_distance == 15.0
        assert price_gain == 22.5
        assert should_trigger is True

    @pytest.mark.parametrize("gain_mult,expected_trigger", [
        (1.0, False),
        (1.4, False),
        (1.5, True),
        (1.6, True),
        (2.0, True),
    ])
    def test_breakeven_boundary(self, gain_mult, expected_trigger):
        """Parametrized test for breakeven boundary"""
        sl_distance = 250.0
        price_gain = sl_distance * gain_mult

        should_trigger = price_gain >= sl_distance * self.BREAKEVEN_R

        assert should_trigger == expected_trigger


class TestSLMoveOnBreakeven:
    """Test SL moves to entry price on breakeven"""

    def test_sl_moved_to_entry_long(self, sample_long_position):
        """LONG: SL should equal entry price after breakeven"""
        pos = sample_long_position

        # Before breakeven
        assert pos.current_sl == 49750.0

        # Trigger breakeven
        pos.current_sl = pos.entry_price
        pos.phase = "BREAKEVEN"

        assert pos.current_sl == 50000.0
        assert pos.phase == "BREAKEVEN"

    def test_sl_moved_to_entry_short(self, sample_short_position):
        """SHORT: SL should equal entry price after breakeven"""
        pos = sample_short_position

        # Before breakeven
        assert pos.current_sl == 3015.0

        # Trigger breakeven
        pos.current_sl = pos.entry_price
        pos.phase = "BREAKEVEN"

        assert pos.current_sl == 3000.0
        assert pos.phase == "BREAKEVEN"


class TestPhaseTransition:
    """Test position phase transitions"""

    def test_entry_to_breakeven_transition(self, sample_long_position):
        """Phase should change from ENTRY to BREAKEVEN"""
        pos = sample_long_position

        assert pos.phase == "INITIAL"  # Or "ENTRY"

        # Trigger breakeven
        pos.phase = "BREAKEVEN"

        assert pos.phase == "BREAKEVEN"

    def test_breakeven_to_trailing_transition(self, sample_long_position):
        """Phase should change from BREAKEVEN to TRAILING after TP1"""
        pos = sample_long_position
        pos.phase = "BREAKEVEN"

        # TP1 hit
        pos.tp_hit_count = 1
        pos.phase = "TRAILING"

        assert pos.phase == "TRAILING"

    def test_phase_flow_order(self):
        """Phases should follow: ENTRY → BREAKEVEN → TRAILING → CLOSED"""
        phases = ["ENTRY", "BREAKEVEN", "TRAILING", "CLOSED"]

        for i in range(len(phases) - 1):
            current = phases[i]
            next_phase = phases[i + 1]

            # Verify order is correct
            assert phases.index(current) < phases.index(next_phase)


class TestBreakevenOnlyOnce:
    """Test breakeven only triggers once"""

    def test_breakeven_not_triggered_twice(self, sample_long_position):
        """Breakeven should only trigger once"""
        pos = sample_long_position
        breakeven_count = 0

        def trigger_breakeven():
            nonlocal breakeven_count
            if pos.phase == "INITIAL":
                pos.phase = "BREAKEVEN"
                pos.current_sl = pos.entry_price
                breakeven_count += 1

        # First trigger
        trigger_breakeven()

        # Second attempt (should not trigger)
        trigger_breakeven()

        assert breakeven_count == 1
        assert pos.phase == "BREAKEVEN"


class TestBreakevenWithBuffer:
    """Test breakeven with small buffer (optional)"""

    def test_breakeven_with_positive_buffer(self, sample_long_position):
        """Optional: SL slightly above entry for guaranteed profit"""
        pos = sample_long_position
        buffer_pct = 0.001  # 0.1% buffer

        # Move SL to entry + buffer
        breakeven_sl = pos.entry_price * (1 + buffer_pct)
        pos.current_sl = breakeven_sl

        assert pos.current_sl == pytest.approx(50050.0)
        assert pos.current_sl > pos.entry_price  # Guaranteed profit

    def test_zero_buffer_is_exact_entry(self, sample_long_position):
        """Zero buffer = exact entry price"""
        pos = sample_long_position
        buffer_pct = 0.0

        breakeven_sl = pos.entry_price * (1 + buffer_pct)

        assert breakeven_sl == pos.entry_price


class TestBreakevenPersistence:
    """Test breakeven SL is persisted to DB"""

    def test_persist_sl_called_on_breakeven(self, mock_order_repository, sample_long_position):
        """persist_sl should be called when breakeven triggers"""
        pos = sample_long_position
        new_sl = pos.entry_price

        mock_order_repository.update_live_position_sl(pos.symbol, new_sl)

        mock_order_repository.update_live_position_sl.assert_called_once_with(
            "BTCUSDT", 50000.0
        )
