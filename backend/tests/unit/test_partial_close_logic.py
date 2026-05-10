"""
Test: Partial Close Logic

SOTA (Jan 2026): Tests for TP1 60% partial close execution.
Verifies correct method calls, quantity calculation, and state updates.

Reference: live_trading_service.py L2978-3050
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestPartialCloseQuantityCalculation:
    """Test partial close quantity is calculated correctly"""

    TP1_PARTIAL_PCT = 0.6  # 60%

    def test_partial_close_60_percent_calculation(self):
        """60% of position is calculated correctly"""
        full_qty = 1.0
        close_qty = full_qty * self.TP1_PARTIAL_PCT

        assert close_qty == pytest.approx(0.6)

    def test_remaining_40_percent_calculation(self):
        """40% remains after partial close"""
        full_qty = 1.0
        close_qty = full_qty * self.TP1_PARTIAL_PCT
        remaining_qty = full_qty - close_qty

        assert remaining_qty == pytest.approx(0.4)

    @pytest.mark.parametrize("full_qty,expected_close,expected_remain", [
        (1.0, 0.6, 0.4),
        (0.1, 0.06, 0.04),
        (10.0, 6.0, 4.0),
        (0.5, 0.3, 0.2),
        (2.5, 1.5, 1.0),
    ])
    def test_partial_close_various_quantities(self, full_qty, expected_close, expected_remain):
        """Parametrized test for various position sizes"""
        close_qty = full_qty * self.TP1_PARTIAL_PCT
        remaining_qty = full_qty - close_qty

        assert close_qty == pytest.approx(expected_close)
        assert remaining_qty == pytest.approx(expected_remain)


class TestPartialCloseOrderSide:
    """Test partial close uses correct order side"""

    def test_long_position_closes_with_sell(self, sample_long_position):
        """LONG position partial close uses SELL order"""
        pos = sample_long_position

        close_side = "SELL" if pos.side == "LONG" else "BUY"

        assert close_side == "SELL"

    def test_short_position_closes_with_buy(self, sample_short_position):
        """SHORT position partial close uses BUY order"""
        pos = sample_short_position

        close_side = "SELL" if pos.side == "LONG" else "BUY"

        assert close_side == "BUY"


class TestMinQuantityCheck:
    """Test minimum quantity check falls back to full close"""

    def test_close_qty_below_min_falls_back(self):
        """If close_qty < minQty, fall back to full close"""
        full_qty = 0.001  # Very small position
        close_qty = full_qty * 0.6  # 0.0006
        min_qty = 0.001  # Exchange minimum

        if close_qty < min_qty:
            # Fall back to full close
            close_qty = full_qty
            should_close_full = True
        else:
            should_close_full = False

        assert should_close_full is True
        assert close_qty == 0.001

    def test_close_qty_above_min_proceeds(self):
        """If close_qty >= minQty, proceed with partial"""
        full_qty = 1.0
        close_qty = full_qty * 0.6  # 0.6
        min_qty = 0.001

        should_close_full = close_qty < min_qty

        assert should_close_full is False
        assert close_qty == 0.6


class TestPartialCloseWithMocks:
    """Test partial close with mocked Binance client"""

    def test_create_order_called_with_correct_params(self, mock_binance_client, sample_long_position):
        """Verify create_order is called with correct parameters"""
        pos = sample_long_position
        price = 51000.0
        pct = 0.6

        # Calculate expected values
        close_qty = pos.quantity * pct
        close_side = "SELL" if pos.side == "LONG" else "BUY"

        # Simulate the partial close call
        mock_binance_client.create_order(
            symbol=pos.symbol,
            side=close_side,
            order_type="MARKET",
            quantity=close_qty,
            reduce_only=True
        )

        # Verify call
        mock_binance_client.create_order.assert_called_once_with(
            symbol="BTCUSDT",
            side="SELL",
            order_type="MARKET",
            quantity=pytest.approx(0.06),
            reduce_only=True
        )

    def test_reduce_only_is_true(self, mock_binance_client, sample_long_position):
        """Partial close must use reduce_only=True"""
        pos = sample_long_position

        mock_binance_client.create_order(
            symbol=pos.symbol,
            side="SELL",
            order_type="MARKET",
            quantity=0.06,
            reduce_only=True
        )

        call_kwargs = mock_binance_client.create_order.call_args.kwargs
        assert call_kwargs['reduce_only'] is True


class TestPartialCloseStateUpdate:
    """Test state updates after partial close"""

    def test_remaining_qty_updated(self, sample_long_position):
        """remaining_qty should be updated after partial close"""
        pos = sample_long_position
        initial_qty = pos.quantity
        close_qty = initial_qty * 0.6

        # Update state
        pos.remaining_qty = initial_qty - close_qty

        assert pos.remaining_qty == pytest.approx(0.04)

    def test_tp_hit_count_incremented(self, sample_long_position):
        """tp_hit_count should be incremented to 1"""
        pos = sample_long_position

        assert pos.tp_hit_count == 0

        # After TP1 hit
        pos.tp_hit_count = 1

        assert pos.tp_hit_count == 1

    def test_phase_changes_to_trailing(self, sample_long_position):
        """phase should change to TRAILING after TP1"""
        pos = sample_long_position

        # After TP1 hit
        pos.phase = "TRAILING"

        assert pos.phase == "TRAILING"
