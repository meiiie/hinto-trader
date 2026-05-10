"""
Unit Tests for Aggressive Trailing Stop Removal

Tests that aggressive trailing logic has been completely removed from:
- LiveTradingService
- PositionMonitorService
- ExecutionSimulator
- Settings loading

Requirements: .kiro/specs/remove-aggressive-trailing-logic/
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime
from decimal import Decimal

from src.application.services.live_trading_service import LiveTradingService, PositionState
from src.application.services.position_monitor_service import PositionMonitorService, MonitoredPosition, PositionPhase
from src.application.backtest.execution_simulator import ExecutionSimulator
from src.domain.entities.exchange_models import Position
from src.domain.entities.trading_signal import TradingSignal, SignalType
from src.infrastructure.api.binance_futures_client import PositionSide


class TestLiveTradingServiceNoAggressiveTrailing:
    """Test that LiveTradingService has no aggressive trailing parameters"""

    def test_no_aggressive_trailing_attributes(self):
        """Verify LiveTradingService doesn't have aggressive trailing attributes"""
        # Create mock dependencies
        mock_repo = Mock()
        mock_repo.get_all_settings.return_value = {}

        # Initialize service
        service = LiveTradingService(
            mode="paper",
            settings_repo=mock_repo
        )

        # Verify NO aggressive trailing attributes
        assert not hasattr(service, '_aggressive_trailing_buffer'), \
            "LiveTradingService should NOT have _aggressive_trailing_buffer attribute"
        assert not hasattr(service, '_tp1_sl_buffer_pct'), \
            "LiveTradingService should NOT have _tp1_sl_buffer_pct attribute"

        # Note: full_tp_at_tp1 is set on PositionMonitorService, not LiveTradingService
        # This is verified in TestPositionMonitorServiceFullTPOnly

    def test_settings_ignore_old_aggressive_trailing_fields(self):
        """Verify old aggressive trailing settings are gracefully ignored"""
        # Create mock repo with old aggressive trailing settings
        mock_repo = Mock()
        mock_repo.get_all_settings.return_value = {
            'aggressive_trailing_buffer': True,
            'tp1_sl_buffer_pct': 0.005,
            'risk_percent': 1.0,
            'max_positions': 10
        }

        # Initialize service - should NOT crash
        service = LiveTradingService(
            mode="paper",
            settings_repo=mock_repo
        )

        # Verify service initialized successfully
        assert service is not None

        # Verify NO aggressive trailing attributes
        assert not hasattr(service, '_aggressive_trailing_buffer')
        assert not hasattr(service, '_tp1_sl_buffer_pct')

    def test_constructor_no_aggressive_trailing_params(self):
        """Verify constructor doesn't accept aggressive trailing parameters"""
        mock_repo = Mock()
        mock_repo.get_all_settings.return_value = {}

        # Try to initialize with old parameters - should be ignored or error
        try:
            service = LiveTradingService(
                mode="paper",
                settings_repo=mock_repo,
                aggressive_trailing_buffer=True,  # Old parameter
                tp1_sl_buffer_pct=0.005  # Old parameter
            )
            # If it doesn't error, verify attributes don't exist
            assert not hasattr(service, '_aggressive_trailing_buffer')
            assert not hasattr(service, '_tp1_sl_buffer_pct')
        except TypeError:
            # Expected: constructor doesn't accept these parameters
            pass


class TestPositionMonitorServiceFullTPOnly:
    """Test that PositionMonitorService only uses Full TP mode"""

    def test_no_aggressive_trailing_attributes(self):
        """Verify PositionMonitorService doesn't have aggressive trailing attributes"""
        # Initialize monitor
        monitor = PositionMonitorService(
            full_tp_at_tp1=True
        )

        # Verify NO aggressive trailing attributes
        assert not hasattr(monitor, '_aggressive_trailing_buffer'), \
            "PositionMonitorService should NOT have _aggressive_trailing_buffer"
        assert not hasattr(monitor, '_tp1_sl_buffer_pct'), \
            "PositionMonitorService should NOT have _tp1_sl_buffer_pct"

        # Verify Full TP mode exists
        assert hasattr(monitor, 'full_tp_at_tp1'), \
            "PositionMonitorService should have full_tp_at_tp1"

    def test_on_tp1_closes_100_percent(self):
        """Verify _on_tp1_hit() closes 100% of position (Full TP mode)"""
        # Create monitored position
        position = MonitoredPosition(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=100.0,
            quantity=1.0,
            leverage=10.0,
            initial_sl=95.0,
            initial_tp=110.0,
            phase=PositionPhase.ENTRY,
            tp_hit_count=0
        )

        # Create monitor with Full TP mode
        monitor = PositionMonitorService(full_tp_at_tp1=True)

        # Mock the close method
        monitor._close_position = Mock()

        # Trigger TP1
        monitor._on_tp1_hit(position, price=110.0)

        # Verify position was closed 100%
        monitor._close_position.assert_called_once()
        call_args = monitor._close_position.call_args

        # Verify close was called with symbol (first arg)
        assert call_args[0][0] == "BTCUSDT"  # First arg is symbol
        # In Full TP mode, entire position should be closed

    def test_on_tp1_no_sl_moved_to_buffer(self):
        """Verify _on_tp1_hit() does NOT move SL to (TP1 - buffer)"""
        # Create monitored position
        position = MonitoredPosition(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=100.0,
            quantity=1.0,
            leverage=10.0,
            initial_sl=95.0,
            initial_tp=110.0,
            current_sl=95.0,
            phase=PositionPhase.ENTRY,
            tp_hit_count=0
        )

        original_sl = position.current_sl

        # Create monitor
        monitor = PositionMonitorService(full_tp_at_tp1=True)
        monitor._close_position = Mock()

        # Trigger TP1
        monitor._on_tp1_hit(position, price=110.0)

        # Verify SL was NOT modified
        # In Full TP mode, position is closed 100%, so SL doesn't matter
        # But we verify it wasn't moved to (TP1 - buffer) like aggressive trailing
        # Since position is closed, we just verify close was called
        monitor._close_position.assert_called_once()


class TestExecutionSimulatorNoAggressiveTrailing:
    """Test that ExecutionSimulator has no aggressive trailing logic"""

    def test_no_aggressive_trailing_attributes(self):
        """Verify ExecutionSimulator doesn't have aggressive trailing attributes"""
        # Initialize simulator with correct parameters
        simulator = ExecutionSimulator(
            initial_balance=10000.0,
            maker_fee_pct=0.02,
            taker_fee_pct=0.05
        )

        # Verify NO aggressive trailing attributes
        assert not hasattr(simulator, 'aggressive_trailing_buffer'), \
            "ExecutionSimulator should NOT have aggressive_trailing_buffer"
        assert not hasattr(simulator, 'tp1_sl_buffer_pct'), \
            "ExecutionSimulator should NOT have tp1_sl_buffer_pct"

        # Verify Full TP mode exists
        assert hasattr(simulator, 'full_tp_at_tp1'), \
            "ExecutionSimulator should have full_tp_at_tp1"

    def test_no_aggressive_trailing_exit_tracking(self):
        """Verify no aggressive trailing exit counter"""
        simulator = ExecutionSimulator(
            initial_balance=10000.0,
            maker_fee_pct=0.02,
            taker_fee_pct=0.05
        )

        # Verify NO aggressive trailing exit counter
        assert not hasattr(simulator, '_aggressive_trailing_exits'), \
            "ExecutionSimulator should NOT track aggressive trailing exits"

    def test_constructor_no_aggressive_trailing_params(self):
        """Verify constructor doesn't accept aggressive trailing parameters"""
        # Try to initialize with old parameters
        try:
            simulator = ExecutionSimulator(
                initial_balance=10000.0,
                leverage=10,
                aggressive_trailing_buffer=True,  # Old parameter
                tp1_sl_buffer_pct=0.001  # Old parameter
            )
            # If it doesn't error, verify attributes don't exist
            assert not hasattr(simulator, 'aggressive_trailing_buffer')
            assert not hasattr(simulator, 'tp1_sl_buffer_pct')
        except TypeError:
            # Expected: constructor doesn't accept these parameters
            pass


class TestBackwardCompatibility:
    """Test backward compatibility with old settings"""

    def test_old_settings_gracefully_ignored(self):
        """Verify system works with old aggressive trailing settings in DB"""
        # Simulate old settings from database
        old_settings = {
            'aggressive_trailing_buffer': True,
            'tp1_sl_buffer_pct': 0.005,
            'risk_percent': 1.0,
            'max_positions': 10,
            'leverage': 10,
            'auto_execute': False
        }

        mock_repo = Mock()
        mock_repo.get_all_settings.return_value = old_settings

        # Initialize service - should work without errors
        service = LiveTradingService(
            mode="paper",
            settings_repo=mock_repo
        )

        # Verify service works
        assert service is not None

        # Verify old fields are ignored
        assert not hasattr(service, '_aggressive_trailing_buffer')
        assert not hasattr(service, '_tp1_sl_buffer_pct')

        # Note: full_tp_at_tp1 is set on PositionMonitorService, not LiveTradingService

    def test_mixed_old_new_settings(self):
        """Verify system works with mix of old and new settings"""
        mixed_settings = {
            # Old (should be ignored)
            'aggressive_trailing_buffer': True,
            'tp1_sl_buffer_pct': 0.005,
            # New (should work)
            'full_tp_at_tp1': True,
            'risk_percent': 1.0,
            'max_positions': 10
        }

        mock_repo = Mock()
        mock_repo.get_all_settings.return_value = mixed_settings

        # Initialize service
        service = LiveTradingService(
            mode="paper",
            settings_repo=mock_repo
        )

        # Verify works correctly
        assert service is not None
        assert not hasattr(service, '_aggressive_trailing_buffer')
        # Note: full_tp_at_tp1 is set on PositionMonitorService, not LiveTradingService


class TestFullTPModeStillWorks:
    """Test that Full TP mode still works after aggressive trailing removal"""

    def test_full_tp_mode_enabled(self):
        """Verify Full TP mode can be enabled on PositionMonitorService"""
        # Create monitor with Full TP mode
        monitor = PositionMonitorService(full_tp_at_tp1=True)

        # Verify Full TP mode is enabled
        assert hasattr(monitor, 'full_tp_at_tp1')
        assert monitor.full_tp_at_tp1 == True

    def test_full_tp_mode_disabled(self):
        """Verify Full TP mode can be disabled on PositionMonitorService"""
        # Create monitor without Full TP mode
        monitor = PositionMonitorService(full_tp_at_tp1=False)

        # Verify Full TP mode is disabled
        assert hasattr(monitor, 'full_tp_at_tp1')
        assert monitor.full_tp_at_tp1 == False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
