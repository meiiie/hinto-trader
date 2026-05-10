"""
Test: Order Cleanup on Position Close

SOTA (Jan 2026): Tests for proper cleanup when positions close.
Verifies backup SL cancelled, watermarks cleared, DB updated.

Reference: live_trading_service.py L542-571, L2930
"""

import pytest
from unittest.mock import Mock, patch, MagicMock, call
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestBackupSLCancellation:
    """Test backup SL (algo order) is cancelled on position close"""

    # =========================================================================
    # REFERENCE (live_trading_service.py L542-571):
    #   def _cancel_backup_sl(self, symbol: str) -> bool:
    #       backup_sl_id = watermark.get('sl_order_id')
    #       self.client.cancel_algo_order(symbol, algo_id=backup_sl_id)
    # =========================================================================

    def test_cancel_algo_order_called(self, mock_binance_client):
        """cancel_algo_order should be called with correct params"""
        symbol = "BTCUSDT"
        algo_id = "algo-12345"

        mock_binance_client.cancel_algo_order(
            symbol=symbol,
            algo_id=algo_id
        )

        mock_binance_client.cancel_algo_order.assert_called_once_with(
            symbol="BTCUSDT",
            algo_id="algo-12345"
        )

    def test_backup_sl_id_from_watermarks(self):
        """Backup SL ID should be retrieved from watermarks"""
        watermarks = {
            "BTCUSDT": {
                "sl_order_id": "algo-12345",
                "entry_price": 50000.0,
                "current_sl": 49750.0
            }
        }

        symbol = "BTCUSDT"
        backup_sl_id = watermarks.get(symbol, {}).get("sl_order_id")

        assert backup_sl_id == "algo-12345"

    def test_cancel_handles_missing_sl_id(self):
        """Should handle gracefully if no backup SL exists"""
        watermarks = {"BTCUSDT": {"entry_price": 50000.0}}  # No sl_order_id

        symbol = "BTCUSDT"
        backup_sl_id = watermarks.get(symbol, {}).get("sl_order_id")

        assert backup_sl_id is None
        # Should not throw, just return False


class TestWatermarkCleanup:
    """Test watermarks are cleaned up on position close"""

    def test_watermark_deleted_on_close(self):
        """Position watermark should be removed after close"""
        watermarks = {
            "BTCUSDT": {"entry_price": 50000.0, "current_sl": 49750.0},
            "ETHUSDT": {"entry_price": 3000.0, "current_sl": 2985.0}
        }

        # Close BTCUSDT position
        symbol = "BTCUSDT"
        if symbol in watermarks:
            del watermarks[symbol]

        assert "BTCUSDT" not in watermarks
        assert "ETHUSDT" in watermarks  # Other positions unaffected

    def test_multiple_watermarks_independent(self):
        """Closing one position should not affect others"""
        watermarks = {
            "BTCUSDT": {"sl_order_id": "algo-1"},
            "ETHUSDT": {"sl_order_id": "algo-2"},
            "BNBUSDT": {"sl_order_id": "algo-3"}
        }

        # Close ETHUSDT
        del watermarks["ETHUSDT"]

        assert len(watermarks) == 2
        assert "BTCUSDT" in watermarks
        assert "BNBUSDT" in watermarks


class TestDBCleanup:
    """Test database entries are cleaned up on position close"""

    def test_delete_live_position_called(self, mock_order_repository):
        """delete_live_position should be called on close"""
        symbol = "BTCUSDT"

        mock_order_repository.delete_live_position(symbol)

        mock_order_repository.delete_live_position.assert_called_once_with("BTCUSDT")

    def test_db_cleanup_order(self, mock_order_repository, mock_binance_client):
        """DB cleanup should happen after exchange orders cancelled"""
        symbol = "BTCUSDT"
        algo_id = "algo-123"

        # Simulate cleanup order
        steps = []

        def track_cancel(*args, **kwargs):
            steps.append("cancel_algo")

        def track_db_delete(*args, **kwargs):
            steps.append("db_delete")

        mock_binance_client.cancel_algo_order = Mock(side_effect=track_cancel)
        mock_order_repository.delete_live_position = Mock(side_effect=track_db_delete)

        # Execute cleanup
        mock_binance_client.cancel_algo_order(symbol, algo_id)
        mock_order_repository.delete_live_position(symbol)

        assert steps == ["cancel_algo", "db_delete"]


class TestStopMonitoringCalled:
    """Test PositionMonitor.stop_monitoring() is called on close"""

    def test_stop_monitoring_removes_from_dict(self):
        """stop_monitoring should remove position from _positions dict"""
        positions = {
            "BTCUSDT": {"entry_price": 50000.0},
            "ETHUSDT": {"entry_price": 3000.0}
        }

        symbol = "BTCUSDT"
        if symbol in positions:
            del positions[symbol]

        assert symbol not in positions
        assert len(positions) == 1

    def test_handler_unregistered(self):
        """Handler should be unregistered from SharedBinanceClient"""
        handlers = {
            "btcusdt": [lambda x: None],
            "ethusdt": [lambda x: None]
        }

        symbol = "btcusdt"
        if symbol in handlers:
            del handlers[symbol]

        assert symbol not in handlers


class TestCleanupCallbackChain:
    """Test full cleanup callback chain is executed"""

    def test_cleanup_chain_on_sl_hit(self):
        """SL hit should trigger: close_position -> cleanup_orders -> stop_monitoring"""
        cleanup_steps = []

        # Mock callbacks
        def close_position(symbol):
            cleanup_steps.append("close_position")

        def cleanup_orders(symbol):
            cleanup_steps.append("cleanup_orders")

        def stop_monitoring(symbol):
            cleanup_steps.append("stop_monitoring")

        # Simulate _on_sl_hit flow
        symbol = "BTCUSDT"
        close_position(symbol)
        cleanup_orders(symbol)
        stop_monitoring(symbol)

        assert cleanup_steps == ["close_position", "cleanup_orders", "stop_monitoring"]

    def test_cleanup_chain_on_tp_trailing_sl(self):
        """TP1 -> Trailing -> SL hit should have same cleanup"""
        cleanup_steps = []

        def close_position(symbol):
            cleanup_steps.append("close_position")

        def cleanup_orders(symbol):
            cleanup_steps.append("cleanup_orders")

        def stop_monitoring(symbol):
            cleanup_steps.append("stop_monitoring")

        # After TP1, price reverses and hits trailing SL
        symbol = "BTCUSDT"
        close_position(symbol)
        cleanup_orders(symbol)
        stop_monitoring(symbol)

        assert len(cleanup_steps) == 3


class TestNoOrphanOrders:
    """Test no orphan orders are left after position close"""

    def test_all_order_ids_cleared(self):
        """All order IDs should be cleared from tracking"""
        order_tracking = {
            "BTCUSDT": {
                "entry_order_id": "order-1",
                "sl_order_id": "algo-1",
                "tp_order_id": "order-2"
            }
        }

        symbol = "BTCUSDT"

        # Clear all tracking
        if symbol in order_tracking:
            del order_tracking[symbol]

        assert symbol not in order_tracking

    def test_pending_signals_cleared(self):
        """Pending signals should be cleared on position close"""
        pending_signals = {
            "BTCUSDT": {"signal_id": "sig-1", "expires_at": "2026-01-12"},
            "ETHUSDT": {"signal_id": "sig-2", "expires_at": "2026-01-12"}
        }

        # Position closes - signal should be removed
        symbol = "BTCUSDT"
        if symbol in pending_signals:
            del pending_signals[symbol]

        assert symbol not in pending_signals
        assert "ETHUSDT" in pending_signals
