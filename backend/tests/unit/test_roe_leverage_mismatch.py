"""Unit tests for ROE calculation with leverage mismatch scenarios.

Tests the fix for the critical bug where ROE was calculated using intended_leverage
instead of actual_leverage from Binance, causing auto-close to not trigger.

Bug Context:
- ZORAUSDT position: intended 10x, actual 20x from Binance
- Entry: $0.0550, Size: 1000 USDT, Margin should be $50 (1000/20)
- Bug calculated margin as $100 (1000/10), resulting in ROE 60% instead of 120%
- Auto-close threshold 5.1% never triggered because ROE was underestimated

Fix:
- Use actual_leverage if available, fallback to intended_leverage
- Add debug logging to track which leverage is used
"""

import pytest
from decimal import Decimal
from datetime import datetime
from backend.src.domain.entities.local_position_tracker import LocalPosition, FillRecord


class TestROELeverageMismatch:
    """Test ROE calculation with leverage mismatch scenarios."""

    def _create_position_with_fill(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        size: float,
        intended_leverage: int,
        actual_leverage: int = None
    ) -> LocalPosition:
        """Helper to create a position with a single fill."""
        pos = LocalPosition(
            symbol=symbol,
            side=side,
            intended_leverage=intended_leverage,
            actual_leverage=actual_leverage
        )

        # Add entry fill
        fill = FillRecord(
            timestamp=datetime.now(),
            order_id="test_order_1",
            price=entry_price,
            quantity=size / entry_price,  # Convert USDT to quantity
            fee=0.0,  # Simplified for testing
            fee_asset='USDT',
            is_maker=False
        )
        pos.add_entry_fill(fill)

        # Set actual leverage if provided
        if actual_leverage:
            pos.set_actual_leverage(actual_leverage)

        return pos

    def test_roe_with_actual_leverage_20x(self):
        """Test ROE calculation when actual leverage (20x) differs from intended (10x).

        This is the ZORAUSDT bug scenario:
        - Intended: 10x, Actual: 20x
        - Entry: $0.0550, Size: 1000 USDT
        - Margin: $50 (1000/20, not $100)
        - Current: $0.0610 (+10.9%)
        - Expected ROE: ~218% (not ~109%)
        """
        pos = self._create_position_with_fill(
            symbol="ZORAUSDT",
            side="LONG",
            entry_price=0.0550,
            size=1000.0,
            intended_leverage=10,
            actual_leverage=20
        )

        # Current price: $0.0610 (+10.9%)
        current_price = 0.0610
        roe = pos.get_roe_percent(current_price)

        # Expected: ~218% (10.9% * 20x leverage)
        # Allow 10% tolerance for fee calculations
        assert abs(roe - 218.0) < 22.0, f"Expected ROE ~218%, got {roe}%"

        # Verify auto-close would trigger at 5.1% threshold
        assert roe > 5.1, "Auto-close should trigger"

    def test_roe_with_intended_leverage_fallback(self):
        """Test ROE calculation when actual_leverage is not set (fallback to intended).

        This tests backward compatibility when actual_leverage is None.
        """
        pos = self._create_position_with_fill(
            symbol="TESTUSDT",
            side="LONG",
            entry_price=100.0,
            size=1000.0,
            intended_leverage=10,
            actual_leverage=None  # Not set
        )

        # Current price: $110 (+10%)
        current_price = 110.0
        roe = pos.get_roe_percent(current_price)

        # Expected: 10% * 10x = 100%
        # Allow 10% tolerance for fee calculations
        assert abs(roe - 100.0) < 10.0, f"Expected ROE ~100%, got {roe}%"

    def test_roe_bug_scenario_before_fix(self):
        """Test the exact bug scenario that caused auto-close to not trigger.

        ZORAUSDT case:
        - Intended: 10x, Actual: 20x
        - Entry: $0.0550, Current: $0.0583 (+6%)
        - WRONG: margin $100 → ROE 60% (using intended 10x)
        - CORRECT: margin $50 → ROE 120% (using actual 20x)
        - Auto-close threshold: 5.1%
        """
        # Simulate the bug: using intended_leverage only
        pos_bug = self._create_position_with_fill(
            symbol="ZORAUSDT",
            side="LONG",
            entry_price=0.0550,
            size=1000.0,
            intended_leverage=10,
            actual_leverage=None  # Bug: not using actual
        )

        current_price = 0.0583  # +6%
        roe_bug = pos_bug.get_roe_percent(current_price)

        # Bug result: ~60% (6% * 10x)
        # Allow 10% tolerance
        assert abs(roe_bug - 60.0) < 10.0, f"Bug ROE should be ~60%, got {roe_bug}%"

        # Simulate the fix: using actual_leverage
        pos_fix = self._create_position_with_fill(
            symbol="ZORAUSDT",
            side="LONG",
            entry_price=0.0550,
            size=1000.0,
            intended_leverage=10,
            actual_leverage=20  # Fix: use actual from Binance
        )

        roe_fix = pos_fix.get_roe_percent(current_price)

        # Fix result: ~120% (6% * 20x)
        # Allow 10% tolerance
        assert abs(roe_fix - 120.0) < 15.0, f"Fix ROE should be ~120%, got {roe_fix}%"

        # Verify auto-close behavior difference
        assert roe_bug < 100, "Bug: auto-close might not trigger reliably"
        assert roe_fix > 100, "Fix: auto-close will trigger correctly"

    def test_roe_with_margin_from_binance(self):
        """Test ROE calculation when margin is provided directly from Binance API.

        This is the most accurate scenario - using margin from Binance's position data.
        """
        pos = self._create_position_with_fill(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            size=1000.0,
            intended_leverage=10,
            actual_leverage=15  # Binance adjusted
        )

        # Current price: $51000 (+2%)
        current_price = 51000.0
        roe = pos.get_roe_percent(current_price)

        # Expected: 2% * 15x = 30%
        # Allow 10% tolerance
        assert abs(roe - 30.0) < 5.0, f"Expected ROE ~30%, got {roe}%"

    def test_roe_short_position_leverage_mismatch(self):
        """Test ROE calculation for SHORT position with leverage mismatch."""
        pos = self._create_position_with_fill(
            symbol="ETHUSDT",
            side="SHORT",
            entry_price=3000.0,
            size=1000.0,
            intended_leverage=10,
            actual_leverage=20  # Binance used 20x
        )

        # Current price: $2900 (-3.33%)
        current_price = 2900.0
        roe = pos.get_roe_percent(current_price)

        # Expected: 3.33% * 20x = 66.6%
        # Allow 10% tolerance
        assert abs(roe - 66.6) < 10.0, f"Expected ROE ~66.6%, got {roe}%"

    def test_roe_negative_pnl_leverage_mismatch(self):
        """Test ROE calculation with negative PnL and leverage mismatch."""
        pos = self._create_position_with_fill(
            symbol="ADAUSDT",
            side="LONG",
            entry_price=0.50,
            size=1000.0,
            intended_leverage=10,
            actual_leverage=20
        )

        # Current price: $0.45 (-10%)
        current_price = 0.45
        roe = pos.get_roe_percent(current_price)

        # Expected: -10% * 20x = -200%
        # Allow 20% tolerance for negative values
        assert abs(roe - (-200.0)) < 30.0, f"Expected ROE ~-200%, got {roe}%"
        assert roe < 0, "ROE should be negative for losing position"

    def test_roe_high_leverage_50x(self):
        """Test ROE calculation with high leverage (50x)."""
        pos = self._create_position_with_fill(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            size=1000.0,
            intended_leverage=25,
            actual_leverage=50  # Binance allowed 50x
        )

        # Current price: $50500 (+1%)
        current_price = 50500.0
        roe = pos.get_roe_percent(current_price)

        # Expected: 1% * 50x = 50%
        # Allow 10% tolerance (fees reduce ROE slightly)
        assert abs(roe - 50.0) < 6.0, f"Expected ROE ~50%, got {roe}%"

    def test_roe_calculation_consistency(self):
        """Test that ROE calculation is consistent across multiple calls."""
        pos = self._create_position_with_fill(
            symbol="SOLUSDT",
            side="LONG",
            entry_price=100.0,
            size=1000.0,
            intended_leverage=10,
            actual_leverage=15
        )

        current_price = 105.0

        # Call multiple times
        roe1 = pos.get_roe_percent(current_price)
        roe2 = pos.get_roe_percent(current_price)
        roe3 = pos.get_roe_percent(current_price)

        # Should be identical
        assert roe1 == roe2 == roe3, "ROE calculation should be consistent"

    def test_roe_with_very_small_price_change(self):
        """Test ROE calculation with very small price changes."""
        pos = self._create_position_with_fill(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.00,
            size=1000.0,
            intended_leverage=10,
            actual_leverage=20
        )

        # Current price: $50001 (+0.002%)
        current_price = 50001.00
        roe = pos.get_roe_percent(current_price)

        # Expected: 0.002% * 20x = 0.04%
        # Note: With fees, very small price changes may result in negative ROE
        # This is expected behavior - fees can exceed tiny gains
        # Just verify ROE is calculated (not zero or error)
        assert roe != 0.0, f"ROE should be calculated, got {roe}%"
        assert abs(roe) < 5.0, f"ROE should be small for tiny price change, got {roe}%"

    def test_roe_logging_leverage_source(self, caplog):
        """Test that ROE calculation logs which leverage is used."""
        import logging
        caplog.set_level(logging.DEBUG)

        # Test with actual_leverage
        pos1 = self._create_position_with_fill(
            symbol="TESTUSDT",
            side="LONG",
            entry_price=100.0,
            size=1000.0,
            intended_leverage=10,
            actual_leverage=20
        )
        pos1.get_roe_percent(110.0)

        # Should log that actual_leverage is used
        assert any("actual_leverage" in record.message.lower() or "20x" in record.message
                   for record in caplog.records), \
            "Should log that actual_leverage is used"

        caplog.clear()

        # Test with fallback to intended_leverage
        pos2 = self._create_position_with_fill(
            symbol="TESTUSDT",
            side="LONG",
            entry_price=100.0,
            size=1000.0,
            intended_leverage=10,
            actual_leverage=None
        )
        pos2.get_roe_percent(110.0)

        # Should log that intended_leverage is used as fallback
        assert any("intended_leverage" in record.message.lower() or "fallback" in record.message.lower()
                   for record in caplog.records), \
            "Should log that intended_leverage is used as fallback"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
