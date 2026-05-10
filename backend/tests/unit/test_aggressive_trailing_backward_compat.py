"""
Unit Tests: Aggressive Trailing Buffer - Backward Compatibility

Tests aggressive trailing logic and backward compatibility with standard mode.

SOTA (Jan 2026): Comprehensive test coverage for aggressive trailing feature.
"""

import pytest
from unittest.mock import Mock, MagicMock
from datetime import datetime, timezone

# Import the classes we need to test
from src.application.services.position_monitor_service import (
    PositionMonitorService,
    MonitoredPosition,
    PositionPhase
)


class TestAggressiveTrailing:
    """Test aggressive trailing buffer functionality."""

    def setup_method(self):
        """Setup test fixtures."""
        # Create mock callbacks
        self.mock_close = Mock(return_value=True)
        self.mock_partial_close = Mock(return_value=True)
        self.mock_cleanup = Mock(return_value=1)
        self.mock_persist_sl = Mock(return_value=True)
        self.mock_persist_tp_hit = Mock(return_value=True)
        self.mock_persist_phase = Mock(return_value=True)
        self.mock_persist_watermarks = Mock(return_value=True)

        # Create monitor with aggressive trailing ENABLED
        self.monitor_aggressive = PositionMonitorService(
            close_position_callback=self.mock_close,
            partial_close_callback=self.mock_partial_close,
            cleanup_orders_callback=self.mock_cleanup,
            persist_sl_callback=self.mock_persist_sl,
            persist_tp_hit_callback=self.mock_persist_tp_hit,
            persist_phase_callback=self.mock_persist_phase,
            persist_watermarks_callback=self.mock_persist_watermarks,
            aggressive_trailing_buffer=True,  # ENABLED
            tp1_sl_buffer_pct=0.001  # 0.1%
        )

        # Create monitor with aggressive trailing DISABLED (standard mode)
        self.monitor_standard = PositionMonitorService(
            close_position_callback=self.mock_close,
            partial_close_callback=self.mock_partial_close,
            cleanup_orders_callback=self.mock_cleanup,
            persist_sl_callback=self.mock_persist_sl,
            persist_tp_hit_callback=self.mock_persist_tp_hit,
            persist_phase_callback=self.mock_persist_phase,
            persist_watermarks_callback=self.mock_persist_watermarks,
            aggressive_trailing_buffer=False,  # DISABLED
            tp1_sl_buffer_pct=0.001
        )

    def create_test_position(
        self,
        symbol='BTCUSDT',
        side='LONG',
        entry=100.0,
        quantity=1.0,
        tp1=110.0,
        sl=95.0
    ) -> MonitoredPosition:
        """Helper to create test position."""
        return MonitoredPosition(
            symbol=symbol,
            side=side,
            entry_price=entry,
            quantity=quantity,
            leverage=10,
            initial_sl=sl,
            initial_tp=tp1,
            atr=2.0
        )

    # ═══════════════════════════════════════════════════════════════════════
    # Test 4.1: Aggressive Trailing SL Calculation (LONG/SHORT)
    # ═══════════════════════════════════════════════════════════════════════

    def test_aggressive_trailing_sl_calculation_long(self):
        """Test SL calculation for LONG position in aggressive mode."""
        pos = self.create_test_position(
            side='LONG',
            entry=100.0,
            tp1=110.0,
            sl=95.0
        )

        # Trigger TP1
        self.monitor_aggressive._on_tp1_hit(pos, price=110.0)

        # Expected SL = TP1 - (TP1 × buffer_pct)
        # = 110.0 - (110.0 × 0.001)
        # = 110.0 - 0.11
        # = 109.89
        expected_sl = 110.0 - (110.0 * 0.001)

        assert abs(pos.current_sl - expected_sl) < 0.01, \
            f"Expected SL {expected_sl}, got {pos.current_sl}"

        # Verify SL is above entry (profit protection)
        assert pos.current_sl > pos.entry_price, \
            f"SL {pos.current_sl} should be above entry {pos.entry_price}"

    def test_aggressive_trailing_sl_calculation_short(self):
        """Test SL calculation for SHORT position in aggressive mode."""
        pos = self.create_test_position(
            side='SHORT',
            entry=100.0,
            tp1=90.0,
            sl=105.0
        )

        # Trigger TP1
        self.monitor_aggressive._on_tp1_hit(pos, price=90.0)

        # Expected SL = TP1 + (TP1 × buffer_pct)
        # = 90.0 + (90.0 × 0.001)
        # = 90.0 + 0.09
        # = 90.09
        expected_sl = 90.0 + (90.0 * 0.001)

        assert abs(pos.current_sl - expected_sl) < 0.01, \
            f"Expected SL {expected_sl}, got {pos.current_sl}"

        # Verify SL is below entry (profit protection)
        assert pos.current_sl < pos.entry_price, \
            f"SL {pos.current_sl} should be below entry {pos.entry_price}"

    # ═══════════════════════════════════════════════════════════════════════
    # Test 4.2: Aggressive Trailing Keeps 100% Position
    # ═══════════════════════════════════════════════════════════════════════

    def test_aggressive_trailing_keeps_100_percent(self):
        """Test that aggressive mode keeps 100% position at TP1."""
        pos = self.create_test_position(quantity=1.0)

        # Trigger TP1
        self.monitor_aggressive._on_tp1_hit(pos, price=110.0)

        # Verify quantity unchanged
        assert pos.quantity == 1.0, \
            f"Expected quantity 1.0, got {pos.quantity}"

        # Verify partial close NOT called
        self.mock_partial_close.assert_not_called()

        # Verify full close NOT called
        self.mock_close.assert_not_called()

    # ═══════════════════════════════════════════════════════════════════════
    # Test 4.3: Aggressive Trailing Profit Protection
    # ═══════════════════════════════════════════════════════════════════════

    def test_aggressive_trailing_profit_protection_long(self):
        """Test profit protection for LONG (SL above entry)."""
        pos = self.create_test_position(
            side='LONG',
            entry=100.0,
            tp1=110.0
        )

        self.monitor_aggressive._on_tp1_hit(pos, price=110.0)

        # SL must be above entry
        assert pos.current_sl > pos.entry_price, \
            f"SL {pos.current_sl} must be above entry {pos.entry_price}"

        # Calculate profit if SL hit
        profit = pos.current_sl - pos.entry_price
        assert profit > 0, f"Profit {profit} must be positive"

    def test_aggressive_trailing_profit_protection_short(self):
        """Test profit protection for SHORT (SL below entry)."""
        pos = self.create_test_position(
            side='SHORT',
            entry=100.0,
            tp1=90.0
        )

        self.monitor_aggressive._on_tp1_hit(pos, price=90.0)

        # SL must be below entry
        assert pos.current_sl < pos.entry_price, \
            f"SL {pos.current_sl} must be below entry {pos.entry_price}"

        # Calculate profit if SL hit
        profit = pos.entry_price - pos.current_sl
        assert profit > 0, f"Profit {profit} must be positive"

    # ═══════════════════════════════════════════════════════════════════════
    # Test 4.4: Backward Compatibility (Standard Mode with 60% Partial Close)
    # ═══════════════════════════════════════════════════════════════════════

    def test_standard_mode_partial_close_60_percent(self):
        """Test standard mode closes 60% at TP1."""
        pos = self.create_test_position(quantity=1.0)

        # Trigger TP1 in standard mode
        self.monitor_standard._on_tp1_hit(pos, price=110.0)

        # Verify partial close called with 60%
        self.mock_partial_close.assert_called_once()
        call_args = self.mock_partial_close.call_args

        # Check symbol
        assert call_args[0][0] == 'BTCUSDT'

        # Check price
        assert abs(call_args[0][1] - 110.0) < 0.01

        # Check percentage (60% = 0.6)
        assert abs(call_args[0][2] - 0.6) < 0.01

    def test_standard_mode_sl_to_breakeven(self):
        """Test standard mode moves SL to breakeven at TP1."""
        pos = self.create_test_position(
            entry=100.0,
            tp1=110.0
        )

        # Trigger TP1 in standard mode
        self.monitor_standard._on_tp1_hit(pos, price=110.0)

        # Expected breakeven SL = entry + (entry × buffer)
        # Note: Implementation uses BREAKEVEN_BUFFER_PCT = 0.0005 (0.05%)
        # = 100.0 + (100.0 × 0.0005)
        # = 100.05
        expected_sl = 100.0 + (100.0 * 0.0005)

        assert abs(pos.current_sl - expected_sl) < 0.01, \
            f"Expected breakeven SL {expected_sl}, got {pos.current_sl}"

    # ═══════════════════════════════════════════════════════════════════════
    # Test 4.5: Settings Loading from Repository
    # ═══════════════════════════════════════════════════════════════════════

    def test_aggressive_trailing_enabled_by_default(self):
        """Test aggressive trailing defaults to TRUE (ON)."""
        monitor = PositionMonitorService()

        assert monitor._aggressive_trailing_buffer is True, \
            "Aggressive trailing should default to TRUE"

    def test_buffer_percentage_default(self):
        """Test buffer percentage defaults to 0.1%."""
        monitor = PositionMonitorService()

        assert monitor._tp1_sl_buffer_pct == 0.001, \
            f"Buffer should default to 0.001 (0.1%), got {monitor._tp1_sl_buffer_pct}"

    def test_custom_buffer_percentage(self):
        """Test custom buffer percentage."""
        monitor = PositionMonitorService(
            aggressive_trailing_buffer=True,
            tp1_sl_buffer_pct=0.005  # 0.5%
        )

        pos = self.create_test_position(entry=100.0, tp1=110.0)
        monitor._persist_sl = Mock(return_value=True)
        monitor._persist_tp_hit = Mock(return_value=True)
        monitor._persist_phase = Mock(return_value=True)

        monitor._on_tp1_hit(pos, price=110.0)

        # Expected SL = 110.0 - (110.0 × 0.005) = 109.45
        expected_sl = 110.0 - (110.0 * 0.005)

        assert abs(pos.current_sl - expected_sl) < 0.01, \
            f"Expected SL {expected_sl}, got {pos.current_sl}"

    # ═══════════════════════════════════════════════════════════════════════
    # Test: State Persistence
    # ═══════════════════════════════════════════════════════════════════════

    def test_state_persisted_to_db(self):
        """Test state is persisted to DB."""
        pos = self.create_test_position()

        self.monitor_aggressive._on_tp1_hit(pos, price=110.0)

        # Verify tp_hit_count persisted
        self.mock_persist_tp_hit.assert_called_once_with('BTCUSDT', 1)

        # Verify phase persisted
        self.mock_persist_phase.assert_called_once_with('BTCUSDT', 'TRAILING', True)

        # Verify SL persisted
        assert self.mock_persist_sl.called
        call_args = self.mock_persist_sl.call_args[0]
        assert call_args[0] == 'BTCUSDT'
        assert call_args[2] == 100.0  # entry_price
        assert call_args[3] == 'LONG'  # side

    def test_phase_transition(self):
        """Test phase transitions correctly."""
        pos = self.create_test_position()

        assert pos.phase == PositionPhase.ENTRY

        self.monitor_aggressive._on_tp1_hit(pos, price=110.0)

        assert pos.phase == PositionPhase.TRAILING
        assert pos.is_breakeven is True
        assert pos.tp_hit_count == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
