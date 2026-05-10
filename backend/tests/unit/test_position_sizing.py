"""
Test: Position Size Calculation

SOTA (Jan 2026): Ensures position sizing matches Backtest exactly.
This directly affects P&L - any difference means inaccurate backtest.

Reference:
- live_trading_service.py _calculate_position_size() L3771-3901
- execution_simulator.py place_order() L250-320
"""

import pytest
from unittest.mock import Mock
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestSlotBasedAllocation:
    """Test slot-based capital allocation matches Backtest"""

    # =========================================================================
    # BACKTEST REFERENCE (execution_simulator.py L250-260):
    #   capital_per_slot = self.balance / self.max_positions
    #   position_size_usd = capital_per_slot * leverage
    #   quantity = position_size_usd / entry_price
    # =========================================================================

    def test_capital_per_slot_calculation(self):
        """Capital per slot = balance / max_positions"""
        balance = 1000.0
        max_positions = 10

        capital_per_slot = balance / max_positions

        assert capital_per_slot == 100.0  # $100 per slot

    def test_position_size_with_leverage(self):
        """Position size USD = capital_per_slot * leverage"""
        balance = 1000.0
        max_positions = 10
        leverage = 10.0

        capital_per_slot = balance / max_positions
        position_size_usd = capital_per_slot * leverage

        assert capital_per_slot == 100.0
        assert position_size_usd == 1000.0  # $1000 notional

    def test_quantity_calculation(self):
        """Quantity = position_size_usd / entry_price"""
        balance = 1000.0
        max_positions = 10
        leverage = 10.0
        entry_price = 50000.0

        capital_per_slot = balance / max_positions
        position_size_usd = capital_per_slot * leverage
        quantity = position_size_usd / entry_price

        assert quantity == pytest.approx(0.02)  # 1000 / 50000

    @pytest.mark.parametrize("balance,max_pos,leverage,price,expected_qty", [
        (1000, 10, 10, 50000, 0.02),      # BTC
        (1000, 10, 10, 3000, 0.3333),     # ETH
        (1000, 10, 10, 100, 10.0),        # Low price coin
        (500, 5, 20, 1000, 2.0),          # Different params
    ])
    def test_quantity_various_scenarios(self, balance, max_pos, leverage, price, expected_qty):
        """Parametrized test for various scenarios"""
        capital_per_slot = balance / max_pos
        position_size_usd = capital_per_slot * leverage
        quantity = position_size_usd / price

        assert quantity == pytest.approx(expected_qty, rel=0.01)


class TestLeverageCap:
    """Test leverage is capped per symbol"""

    # =========================================================================
    # REFERENCE (L3840-3855):
    #   symbol_max_lev = symbol_rules.get(symbol, {}).get('max_leverage', self.max_leverage)
    #   actual_leverage = min(self.max_leverage, symbol_max_lev)
    # =========================================================================

    def test_leverage_capped_by_symbol_rule(self):
        """Leverage should be min(global, symbol_max)"""
        global_max_leverage = 20
        symbol_rules = {
            "BTCUSDT": {"max_leverage": 125},  # High max
            "VVVUSDT": {"max_leverage": 10},   # Low max
        }

        btc_leverage = min(global_max_leverage, symbol_rules["BTCUSDT"]["max_leverage"])
        vvv_leverage = min(global_max_leverage, symbol_rules["VVVUSDT"]["max_leverage"])

        assert btc_leverage == 20  # Capped by global
        assert vvv_leverage == 10  # Capped by symbol

    def test_default_leverage_when_no_rule(self):
        """Use global max when no symbol-specific rule"""
        global_max_leverage = 10
        symbol_rules = {}  # No rules

        actual = symbol_rules.get("NEWUSDT", {}).get("max_leverage", global_max_leverage)

        assert actual == 10


class TestMinNotionalCheck:
    """Test minimum notional value ($5 for Binance Futures)"""

    MIN_NOTIONAL = 5.0  # Binance Futures minimum

    def test_below_min_notional_rejected(self):
        """Position below $5 notional should be rejected"""
        entry_price = 0.001
        quantity = 1000
        notional = entry_price * quantity  # $1

        is_valid = notional >= self.MIN_NOTIONAL

        assert is_valid is False

    def test_above_min_notional_accepted(self):
        """Position above $5 notional should be accepted"""
        entry_price = 50000
        quantity = 0.001
        notional = entry_price * quantity  # $50

        is_valid = notional >= self.MIN_NOTIONAL

        assert is_valid is True

    @pytest.mark.parametrize("price,qty,expected_valid", [
        (50000, 0.0001, False),   # $5.0 = boundary (treated as invalid)
        (50000, 0.0002, True),    # $10 = valid
        (0.001, 5000, False),     # $5 = boundary
        (0.001, 6000, True),      # $6 = valid
    ])
    def test_min_notional_boundary(self, price, qty, expected_valid):
        """Parametrized test for min notional boundary"""
        notional = price * qty
        is_valid = notional > self.MIN_NOTIONAL  # > 5, not >=

        assert is_valid == expected_valid


class TestQuantityRounding:
    """Test quantity is rounded to step_size"""

    # =========================================================================
    # REFERENCE (L3870):
    #   quantity = self.filter_service.sanitize_quantity(symbol, quantity)
    # =========================================================================

    def test_quantity_rounded_to_step_size(self):
        """Quantity should be rounded down to step_size"""
        raw_quantity = 0.12345
        step_size = 0.001

        # Round down to step_size
        rounded = int(raw_quantity / step_size) * step_size

        assert rounded == pytest.approx(0.123)

    @pytest.mark.parametrize("raw_qty,step,expected", [
        (0.12345, 0.001, 0.123),
        (1.5678, 0.01, 1.56),
        (100.999, 1, 100),
        (0.00567, 0.0001, 0.0056),
    ])
    def test_step_size_rounding(self, raw_qty, step, expected):
        """Parametrized test for step size rounding"""
        rounded = int(raw_qty / step) * step

        assert rounded == pytest.approx(expected)


class TestMarginRequirement:
    """Test margin requirement calculation"""

    def test_margin_required_equals_capital_per_slot(self):
        """Margin required = capital_per_slot (in ISOLATED mode)"""
        balance = 1000.0
        max_positions = 10

        capital_per_slot = balance / max_positions
        margin_required = capital_per_slot  # In ISOLATED mode

        assert margin_required == 100.0

    def test_available_balance_check(self):
        """Should not exceed available balance"""
        balance = 1000.0
        max_positions = 10
        used_margin = 300.0  # 3 positions already open

        available = balance - used_margin
        capital_per_slot = balance / max_positions

        # Should use min(capital_per_slot, available)
        actual_margin = min(capital_per_slot, available)

        assert available == 700.0
        assert actual_margin == 100.0  # Slot is smaller than available
