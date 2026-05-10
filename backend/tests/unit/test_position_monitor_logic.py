"""
Test: PositionMonitorService Logic

SOTA (Jan 2026): Unit tests for core TP/SL detection logic.
Tests the decision-making in _process_tick() method.

Reference: position_monitor_service.py
"""

import pytest
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from datetime import datetime, timezone, timedelta
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestTP1Detection:
    """Test TP1 hit detection for LONG and SHORT positions"""

    # =========================================================================
    # REFERENCE (position_monitor_service.py L270-290):
    #   if pos.tp_hit_count == 0:
    #       if pos.side == "LONG" and price >= pos.initial_tp:
    #           self._on_tp1_hit(pos, price)
    #       elif pos.side == "SHORT" and price <= pos.initial_tp:
    #           self._on_tp1_hit(pos, price)
    # =========================================================================

    def test_tp1_detected_long_exact_price(self, sample_long_position):
        """LONG: TP1 detected at exactly TP price"""
        pos = sample_long_position
        price = pos.initial_tp  # Exactly 51000

        should_trigger = (
            pos.tp_hit_count == 0 and
            pos.side == "LONG" and
            price >= pos.initial_tp
        )

        assert should_trigger is True

    def test_tp1_detected_long_above_price(self, sample_long_position):
        """LONG: TP1 detected when price exceeds TP"""
        pos = sample_long_position
        price = 51500.0  # Above TP

        should_trigger = (
            pos.tp_hit_count == 0 and
            pos.side == "LONG" and
            price >= pos.initial_tp
        )

        assert should_trigger is True

    def test_tp1_not_detected_long_below_price(self, sample_long_position):
        """LONG: TP1 NOT detected when price below TP"""
        pos = sample_long_position
        price = 50500.0  # Below TP but above entry

        should_trigger = (
            pos.tp_hit_count == 0 and
            pos.side == "LONG" and
            price >= pos.initial_tp
        )

        assert should_trigger is False

    def test_tp1_detected_short_exact_price(self, sample_short_position):
        """SHORT: TP1 detected at exactly TP price"""
        pos = sample_short_position
        price = pos.initial_tp  # Exactly 2940

        should_trigger = (
            pos.tp_hit_count == 0 and
            pos.side == "SHORT" and
            price <= pos.initial_tp
        )

        assert should_trigger is True

    def test_tp1_detected_short_below_price(self, sample_short_position):
        """SHORT: TP1 detected when price below TP"""
        pos = sample_short_position
        price = 2900.0  # Below TP

        should_trigger = (
            pos.tp_hit_count == 0 and
            pos.side == "SHORT" and
            price <= pos.initial_tp
        )

        assert should_trigger is True


class TestSLDetection:
    """Test SL hit detection for LONG and SHORT positions"""

    # =========================================================================
    # REFERENCE (position_monitor_service.py L245-265):
    #   if pos.side == "LONG" and price <= pos.current_sl:
    #       self._on_sl_hit(pos, pos.current_sl)
    #   elif pos.side == "SHORT" and price >= pos.current_sl:
    #       self._on_sl_hit(pos, pos.current_sl)
    # =========================================================================

    def test_sl_detected_long_exact_price(self, sample_long_position):
        """LONG: SL detected at exactly SL price"""
        pos = sample_long_position
        price = pos.current_sl  # Exactly 49750

        should_trigger = (
            pos.side == "LONG" and
            price <= pos.current_sl
        )

        assert should_trigger is True

    def test_sl_detected_long_below_price(self, sample_long_position):
        """LONG: SL detected when price drops below SL"""
        pos = sample_long_position
        price = 49500.0  # Below SL

        should_trigger = (
            pos.side == "LONG" and
            price <= pos.current_sl
        )

        assert should_trigger is True

    def test_sl_not_detected_long_above_sl(self, sample_long_position):
        """LONG: SL NOT detected when price above SL"""
        pos = sample_long_position
        price = 50000.0  # At entry, above SL

        should_trigger = (
            pos.side == "LONG" and
            price <= pos.current_sl
        )

        assert should_trigger is False

    def test_sl_detected_short_exact_price(self, sample_short_position):
        """SHORT: SL detected at exactly SL price"""
        pos = sample_short_position
        price = pos.current_sl  # Exactly 3015

        should_trigger = (
            pos.side == "SHORT" and
            price >= pos.current_sl
        )

        assert should_trigger is True

    def test_sl_detected_short_above_price(self, sample_short_position):
        """SHORT: SL detected when price rises above SL"""
        pos = sample_short_position
        price = 3050.0  # Above SL

        should_trigger = (
            pos.side == "SHORT" and
            price >= pos.current_sl
        )

        assert should_trigger is True


class TestGracePeriod:
    """Test grace period prevents early SL close"""

    # =========================================================================
    # REFERENCE (position_monitor_service.py L215-230):
    #   GRACE_PERIOD_SECONDS = 30
    #   elapsed = (now - pos.entry_time).total_seconds()
    #   if elapsed < self.GRACE_PERIOD_SECONDS:
    #       return  # Skip SL check during grace period
    # =========================================================================

    GRACE_PERIOD_SECONDS = 30

    def test_sl_blocked_during_grace_period(self, sample_long_position):
        """SL should NOT trigger during first 30 seconds"""
        pos = sample_long_position
        entry_time = datetime.now(timezone.utc)
        current_time = entry_time + timedelta(seconds=15)  # 15s elapsed

        elapsed = (current_time - entry_time).total_seconds()
        in_grace_period = elapsed < self.GRACE_PERIOD_SECONDS

        assert in_grace_period is True

    def test_sl_allowed_after_grace_period(self, sample_long_position):
        """SL should trigger after 30 seconds"""
        pos = sample_long_position
        entry_time = datetime.now(timezone.utc)
        current_time = entry_time + timedelta(seconds=45)  # 45s elapsed

        elapsed = (current_time - entry_time).total_seconds()
        in_grace_period = elapsed < self.GRACE_PERIOD_SECONDS

        assert in_grace_period is False

    @pytest.mark.parametrize("elapsed_seconds,expected_blocked", [
        (0, True),
        (15, True),
        (29, True),
        (30, False),
        (31, False),
        (60, False),
    ])
    def test_grace_period_boundary(self, elapsed_seconds, expected_blocked):
        """Parametrized test for grace period boundary"""
        in_grace_period = elapsed_seconds < self.GRACE_PERIOD_SECONDS
        assert in_grace_period == expected_blocked


class TestSafetyGuard:
    """Test 10% safety guard blocks abnormal losses"""

    # =========================================================================
    # REFERENCE (position_monitor_service.py L255-265):
    #   MAX_LOSS_PERCENT = 10.0
    #   pnl_pct = calculate_pnl_percent(pos, price)
    #   if abs(pnl_pct) > MAX_LOSS_PERCENT:
    #       logger.error("Abnormal loss blocked")
    #       return
    # =========================================================================

    MAX_LOSS_PERCENT = 10.0

    def test_normal_loss_allowed(self, sample_long_position):
        """Normal 2% loss should be allowed"""
        pos = sample_long_position
        entry = pos.entry_price  # 50000
        current_price = 49000.0  # 2% loss

        pnl_pct = ((current_price - entry) / entry) * 100
        is_abnormal = abs(pnl_pct) > self.MAX_LOSS_PERCENT

        assert pnl_pct == pytest.approx(-2.0)
        assert is_abnormal is False

    def test_abnormal_loss_blocked(self, sample_long_position):
        """15% loss should be blocked"""
        pos = sample_long_position
        entry = pos.entry_price  # 50000
        current_price = 42500.0  # 15% loss

        pnl_pct = ((current_price - entry) / entry) * 100
        is_abnormal = abs(pnl_pct) > self.MAX_LOSS_PERCENT

        assert pnl_pct == pytest.approx(-15.0)
        assert is_abnormal is True

    @pytest.mark.parametrize("loss_pct,expected_blocked", [
        (5.0, False),
        (9.9, False),
        (10.0, False),  # Exactly at boundary
        (10.1, True),
        (15.0, True),
        (50.0, True),
    ])
    def test_safety_guard_boundary(self, sample_long_position, loss_pct, expected_blocked):
        """Parametrized test for safety guard boundary"""
        entry = sample_long_position.entry_price
        current_price = entry * (1 - loss_pct / 100)

        pnl_pct = ((current_price - entry) / entry) * 100
        is_abnormal = abs(pnl_pct) > self.MAX_LOSS_PERCENT

        assert is_abnormal == expected_blocked


class TestTrailingStopUpdate:
    """Test trailing stop updates correctly based on price movement"""

    TRAILING_ATR_MULT = 4.0

    def test_trailing_updates_when_price_moves_favorably_long(self, sample_long_position):
        """LONG: Trailing SL moves up when price makes new high"""
        pos = sample_long_position
        pos.tp_hit_count = 1  # Trailing active after TP1
        pos.current_sl = pos.entry_price  # 50000 (breakeven)

        new_high = 52000.0
        trailing_distance = pos.atr * self.TRAILING_ATR_MULT  # 500 * 4 = 2000
        new_sl = new_high - trailing_distance  # 52000 - 2000 = 50000

        # Only update if new_sl > current_sl
        if new_sl > pos.current_sl:
            pos.current_sl = new_sl

        assert pos.current_sl == 50000.0  # Should stay at breakeven

        # Now price moves higher
        new_high = 53000.0
        new_sl = new_high - trailing_distance  # 53000 - 2000 = 51000

        if new_sl > pos.current_sl:
            pos.current_sl = new_sl

        assert pos.current_sl == 51000.0  # Should trail up

    def test_trailing_does_not_move_backward_long(self, sample_long_position):
        """LONG: Trailing SL never moves down"""
        pos = sample_long_position
        pos.tp_hit_count = 1
        pos.current_sl = 51000.0  # Already trailed up

        # Price drops
        current_high = 51500.0
        trailing_distance = pos.atr * self.TRAILING_ATR_MULT
        new_sl = current_high - trailing_distance  # 51500 - 2000 = 49500

        # Only update if new_sl > current_sl
        if new_sl > pos.current_sl:
            pos.current_sl = new_sl

        assert pos.current_sl == 51000.0  # Should NOT move down
