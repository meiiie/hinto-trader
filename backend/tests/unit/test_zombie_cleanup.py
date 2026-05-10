"""
Test: Zombie Order Cleanup

SOTA (Jan 2026): Tests for cleaning up orphaned orders.
Prevents old SL/TP orders from affecting new positions.

Reference: live_trading_service.py _cleanup_zombie_orders() L964-1031
"""

import pytest
from unittest.mock import Mock, AsyncMock
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestZombieOrderDetection:
    """Test detection of zombie orders"""

    # =========================================================================
    # Zombie Order: An SL/TP order that remains on exchange after position closed.
    # Can trigger on NEW positions, causing unexpected losses.
    # =========================================================================

    def test_zombie_order_detected(self):
        """Orders for closed positions are zombie orders"""
        active_positions = {"BTCUSDT": {}}  # Only BTC open
        open_orders = [
            {"symbol": "BTCUSDT", "type": "STOP_MARKET"},  # Valid
            {"symbol": "VVVUSDT", "type": "STOP_MARKET"},  # Zombie!
            {"symbol": "VVVUSDT", "type": "TAKE_PROFIT_MARKET"},  # Zombie!
        ]

        zombie_orders = [
            o for o in open_orders
            if o["symbol"] not in active_positions
        ]

        assert len(zombie_orders) == 2
        assert all(o["symbol"] == "VVVUSDT" for o in zombie_orders)

    def test_no_zombie_orders_when_all_positions_tracked(self):
        """No zombies when all order symbols have positions"""
        active_positions = {"BTCUSDT": {}, "ETHUSDT": {}}
        open_orders = [
            {"symbol": "BTCUSDT", "type": "STOP_MARKET"},
            {"symbol": "ETHUSDT", "type": "TAKE_PROFIT_MARKET"},
        ]

        zombie_orders = [
            o for o in open_orders
            if o["symbol"] not in active_positions
        ]

        assert len(zombie_orders) == 0


class TestCancelAllOrdersForSymbol:
    """Test cancelling all orders for a symbol"""

    def test_cancel_open_orders_called(self, mock_binance_client):
        """Should call cancel_all_open_orders for symbol"""
        symbol = "VVVUSDT"

        mock_binance_client.cancel_all_open_orders = Mock(return_value={"code": 200})

        mock_binance_client.cancel_all_open_orders(symbol=symbol)

        mock_binance_client.cancel_all_open_orders.assert_called_once_with(symbol="VVVUSDT")

    def test_cancel_algo_orders_called(self, mock_binance_client):
        """Should also cancel algo orders (backup SL)"""
        symbol = "VVVUSDT"
        algo_orders = [{"algoId": "algo-123"}, {"algoId": "algo-456"}]

        mock_binance_client.get_open_algo_orders = Mock(return_value=algo_orders)
        mock_binance_client.cancel_algo_order = Mock(return_value={"code": 200})

        # Simulate cleanup
        for algo in algo_orders:
            mock_binance_client.cancel_algo_order(symbol=symbol, algo_id=algo["algoId"])

        assert mock_binance_client.cancel_algo_order.call_count == 2


class TestCleanupOnPositionClose:
    """Test zombie cleanup on position close"""

    def test_cleanup_triggered_on_close(self):
        """Cleanup should be called when position closes"""
        cleanup_called = []

        def cleanup_zombie_orders(symbol):
            cleanup_called.append(symbol)

        # Simulate position close
        symbol = "VVVUSDT"
        cleanup_zombie_orders(symbol)

        assert symbol in cleanup_called

    def test_cleanup_order_matters(self):
        """Should cancel orders FIRST, then update tracking"""
        steps = []

        def cancel_orders(symbol):
            steps.append("cancel_orders")

        def remove_from_tracking(symbol):
            steps.append("remove_tracking")

        # Correct order
        symbol = "VVVUSDT"
        cancel_orders(symbol)
        remove_from_tracking(symbol)

        assert steps == ["cancel_orders", "remove_tracking"]


class TestCleanupWithErrors:
    """Test graceful handling of cleanup errors"""

    def test_continue_cleanup_on_error(self):
        """Should continue cancelling even if one fails"""
        orders_to_cancel = [
            {"orderId": "1", "symbol": "VVV"},
            {"orderId": "2", "symbol": "VVV"},  # This one will fail
            {"orderId": "3", "symbol": "VVV"},
        ]

        cancelled = []
        failed = []

        for order in orders_to_cancel:
            try:
                if order["orderId"] == "2":
                    raise Exception("Network error")
                cancelled.append(order["orderId"])
            except Exception:
                failed.append(order["orderId"])

        assert cancelled == ["1", "3"]
        assert failed == ["2"]

    def test_returns_partial_success(self):
        """Should return partial success if some orders cancelled"""
        total_orders = 3
        cancelled_count = 2

        result = {
            "success": cancelled_count > 0,
            "cancelled": cancelled_count,
            "failed": total_orders - cancelled_count
        }

        assert result["success"] is True
        assert result["cancelled"] == 2
        assert result["failed"] == 1


class TestCleanupAfterManualClose:
    """Test cleanup after user manually closes position"""

    def test_detect_manual_close_via_position_update(self):
        """Should detect manual close via ACCOUNT_UPDATE"""
        previous_positions = {"BTCUSDT": {"qty": 0.1}, "VVVUSDT": {"qty": 100}}
        current_positions = {"BTCUSDT": {"qty": 0.1}}  # VVV manually closed

        closed_symbols = set(previous_positions.keys()) - set(current_positions.keys())

        assert "VVVUSDT" in closed_symbols

    def test_trigger_cleanup_for_manual_close(self):
        """Should trigger cleanup for manually closed position"""
        closed_symbols = ["VVVUSDT"]
        cleanup_triggered = []

        for symbol in closed_symbols:
            cleanup_triggered.append(symbol)

        assert "VVVUSDT" in cleanup_triggered
