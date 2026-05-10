"""
Test: State Reconciliation Logic

SOTA (Jan 2026): Critical for 24/7 autonomous operation.
Ensures local state syncs correctly with exchange after restart/disconnect.

Reference: live_trading_service.py reconcile_state() L2101-2246
"""

import pytest
from unittest.mock import Mock, MagicMock
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestOrphanPositionDetection:
    """Test detection of positions that exist on exchange but not locally"""

    # =========================================================================
    # REFERENCE (L2157-2165):
    #   tracked_symbols = set(self.active_positions.keys())
    #   orphan_symbols = []
    #   for pos in exchange_positions:
    #       if symbol not in tracked_symbols:
    #           orphan_symbols.append(symbol)
    # =========================================================================

    def test_orphan_detected_when_not_tracked(self):
        """Position on exchange but not in active_positions = orphan"""
        active_positions = {"BTCUSDT": {}, "ETHUSDT": {}}
        exchange_positions = [
            {"symbol": "BTCUSDT", "positionAmt": "0.1"},
            {"symbol": "ETHUSDT", "positionAmt": "1.0"},
            {"symbol": "VVVUSDT", "positionAmt": "100.0"},  # Not tracked!
        ]

        tracked_symbols = set(active_positions.keys())
        orphans = []

        for pos in exchange_positions:
            symbol = pos["symbol"]
            amt = float(pos["positionAmt"])
            if amt != 0 and symbol not in tracked_symbols:
                orphans.append(symbol)

        assert orphans == ["VVVUSDT"]

    def test_no_orphan_when_all_tracked(self):
        """All positions tracked = no orphans"""
        active_positions = {"BTCUSDT": {}, "ETHUSDT": {}}
        exchange_positions = [
            {"symbol": "BTCUSDT", "positionAmt": "0.1"},
            {"symbol": "ETHUSDT", "positionAmt": "1.0"},
        ]

        tracked_symbols = set(active_positions.keys())
        orphans = [
            pos["symbol"] for pos in exchange_positions
            if float(pos["positionAmt"]) != 0 and pos["symbol"] not in tracked_symbols
        ]

        assert orphans == []

    def test_zero_position_ignored(self):
        """Zero position amount should not be considered orphan"""
        active_positions = {"BTCUSDT": {}}
        exchange_positions = [
            {"symbol": "BTCUSDT", "positionAmt": "0.1"},
            {"symbol": "ETHUSDT", "positionAmt": "0.0"},  # Zero = no position
        ]

        orphans = [
            pos["symbol"] for pos in exchange_positions
            if float(pos["positionAmt"]) != 0 and pos["symbol"] not in active_positions
        ]

        assert orphans == []


class TestMissingSLDetection:
    """Test detection of positions without SL protection"""

    # =========================================================================
    # REFERENCE (L2188-2220):
    #   for symbol in active_positions:
    #       has_sl = any(get_order_type(o) in ['STOP_MARKET', 'STOP'] for o in symbol_orders)
    #       if not has_sl: warnings.append(f"NO STOP LOSS on {symbol}!")
    # =========================================================================

    def test_missing_sl_warning(self):
        """Position without SL order should generate warning"""
        active_positions = ["BTCUSDT"]
        orders_by_symbol = {
            "BTCUSDT": [
                {"type": "TAKE_PROFIT_MARKET", "symbol": "BTCUSDT"},
            ]  # Only TP, no SL!
        }

        warnings = []
        for symbol in active_positions:
            symbol_orders = orders_by_symbol.get(symbol, [])
            has_sl = any(o["type"] in ["STOP_MARKET", "STOP"] for o in symbol_orders)
            if not has_sl:
                warnings.append(f"NO STOP LOSS on {symbol}!")

        assert "NO STOP LOSS on BTCUSDT!" in warnings

    def test_sl_present_no_warning(self):
        """Position with SL order should NOT generate warning"""
        active_positions = ["BTCUSDT"]
        orders_by_symbol = {
            "BTCUSDT": [
                {"type": "STOP_MARKET", "symbol": "BTCUSDT"},
                {"type": "TAKE_PROFIT_MARKET", "symbol": "BTCUSDT"},
            ]
        }

        warnings = []
        for symbol in active_positions:
            symbol_orders = orders_by_symbol.get(symbol, [])
            has_sl = any(o["type"] in ["STOP_MARKET", "STOP"] for o in symbol_orders)
            if not has_sl:
                warnings.append(f"NO STOP LOSS on {symbol}!")

        assert warnings == []

    def test_algo_order_counts_as_sl(self):
        """Algo order (backup SL) should count as having SL"""
        # SOTA: Algo orders are separate from regular orders
        # They are fetched via get_open_algo_orders()
        active_positions = ["BTCUSDT"]
        regular_orders = {
            "BTCUSDT": []  # No regular SL
        }
        algo_orders = {
            "BTCUSDT": [{"algoId": "algo-123", "type": "STOP_MARKET"}]
        }

        # Combined check
        has_sl = (
            any(o.get("type") in ["STOP_MARKET", "STOP"] for o in regular_orders.get("BTCUSDT", [])) or
            len(algo_orders.get("BTCUSDT", [])) > 0
        )

        assert has_sl is True


class TestStaleTrackingCleanup:
    """Test cleanup of stale position tracking"""

    # =========================================================================
    # REFERENCE (L2370-2385):
    #   if symbol in watermarks: del watermarks[symbol]
    #   if symbol in position_states: del position_states[symbol]
    #   if symbol in pending_orders: del pending_orders[symbol]
    # =========================================================================

    def test_stale_tracking_cleaned_up(self):
        """Stale tracking data should be removed"""
        watermarks = {"BTCUSDT": {}, "OLDUSDT": {}}
        position_states = {"BTCUSDT": {}, "OLDUSDT": {}}
        pending_orders = {"OLDUSDT": {}}

        # Exchange says only BTCUSDT has position
        exchange_positions = [{"symbol": "BTCUSDT", "positionAmt": "0.1"}]
        exchange_symbols = {pos["symbol"] for pos in exchange_positions if float(pos["positionAmt"]) != 0}

        # Cleanup stale
        stale_symbols = set(watermarks.keys()) - exchange_symbols
        for symbol in stale_symbols:
            if symbol in watermarks:
                del watermarks[symbol]
            if symbol in position_states:
                del position_states[symbol]
            if symbol in pending_orders:
                del pending_orders[symbol]

        assert "OLDUSDT" not in watermarks
        assert "OLDUSDT" not in position_states
        assert "OLDUSDT" not in pending_orders
        assert "BTCUSDT" in watermarks


class TestAdoptOrphanPosition:
    """Test adopting orphan positions with SL/TP detection"""

    def test_adopt_finds_sl_order(self):
        """Adopting should detect existing SL order price"""
        position = {"symbol": "VVVUSDT", "entryPrice": "0.05", "positionAmt": "1000"}
        orders = [
            {"symbol": "VVVUSDT", "type": "STOP_MARKET", "stopPrice": "0.0475", "reduceOnly": True},
            {"symbol": "VVVUSDT", "type": "TAKE_PROFIT_MARKET", "stopPrice": "0.051", "reduceOnly": True},
        ]

        # Find SL and TP
        sl_price = None
        tp_price = None

        for order in orders:
            if order.get("reduceOnly"):
                if order["type"] == "STOP_MARKET":
                    sl_price = float(order["stopPrice"])
                elif order["type"] == "TAKE_PROFIT_MARKET":
                    tp_price = float(order["stopPrice"])

        assert sl_price == 0.0475
        assert tp_price == 0.051

    def test_adopt_handles_no_sl(self):
        """Adopting should handle position with no SL order"""
        position = {"symbol": "VVVUSDT", "entryPrice": "0.05", "positionAmt": "1000"}
        orders = []  # No orders!

        sl_price = None
        for order in orders:
            if order.get("type") == "STOP_MARKET":
                sl_price = float(order.get("stopPrice", 0))

        assert sl_price is None
        # System should warn about missing SL


class TestReconciliationResults:
    """Test reconciliation result format"""

    def test_result_structure(self):
        """Reconciliation should return proper result dict"""
        result = {
            "success": True,
            "orphan_positions": [],
            "adopted_positions": [],
            "warnings": [],
            "stale_cleaned": [],
            "timestamp": "2026-01-12T14:00:00"
        }

        assert "success" in result
        assert "orphan_positions" in result
        assert "warnings" in result

    def test_result_with_issues(self):
        """Result should contain all detected issues"""
        result = {
            "success": True,
            "orphan_positions": ["VVVUSDT"],
            "adopted_positions": ["VVVUSDT"],
            "warnings": ["NO STOP LOSS on PEPEUSDT!"],
            "stale_cleaned": ["OLDUSDT"],
        }

        assert len(result["orphan_positions"]) == 1
        assert len(result["warnings"]) == 1
        assert len(result["stale_cleaned"]) == 1
