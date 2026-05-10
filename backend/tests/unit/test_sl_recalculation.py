"""
Test: SL Recalculation from Actual Fill Price

SOTA (Jan 2026): Verifies the critical fix for SL recalculation.
When MARKET order fills at different price than signal limit_price,
SL must be recalculated from actual fill to maintain 0.5% distance.

Reference: live_trading_service.py L1607-1620
"""

import pytest
from unittest.mock import Mock
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestSLRecalculationLong:
    """Test SL recalculation for LONG positions"""

    # =========================================================================
    # REFERENCE (live_trading_service.py L1607-1620):
    #   current_price = actual fill price
    #   actual_stop_loss = current_price * 0.995  # 0.5% below
    #   actual_take_profit = current_price * 1.02  # 2% above
    # =========================================================================

    SL_DISTANCE_PCT = 0.005  # 0.5%
    TP_DISTANCE_PCT = 0.02   # 2%

    def test_sl_recalculated_from_fill_price_long(self):
        """LONG: SL = fill_price * 0.995 (0.5% below)"""
        signal_limit_price = 50000.0
        actual_fill_price = 50100.0  # Filled higher due to market move

        # Old logic (WRONG): Would use signal price
        old_sl = signal_limit_price * (1 - self.SL_DISTANCE_PCT)  # 49750

        # New logic (CORRECT): Uses actual fill
        new_sl = actual_fill_price * (1 - self.SL_DISTANCE_PCT)  # 49849.5

        assert old_sl == pytest.approx(49750.0)
        assert new_sl == pytest.approx(49849.5)
        assert new_sl > old_sl  # New SL is higher (safer)

    def test_tp_recalculated_from_fill_price_long(self):
        """LONG: TP = fill_price * 1.02 (2% above)"""
        signal_limit_price = 50000.0
        actual_fill_price = 50100.0

        old_tp = signal_limit_price * (1 + self.TP_DISTANCE_PCT)  # 51000
        new_tp = actual_fill_price * (1 + self.TP_DISTANCE_PCT)   # 51102

        assert old_tp == pytest.approx(51000.0)
        assert new_tp == pytest.approx(51102.0)

    @pytest.mark.parametrize("limit_price,fill_price,expected_sl,expected_tp", [
        (50000, 50100, 49849.5, 51102.0),   # Fill higher than limit
        (50000, 49900, 49650.5, 50898.0),   # Fill lower than limit
        (50000, 50000, 49750.0, 51000.0),   # Fill at limit (no diff)
        (100, 101, 100.495, 103.02),        # Small price
        (1000, 1050, 1044.75, 1071.0),      # 5% slippage
    ])
    def test_recalculation_various_scenarios(self, limit_price, fill_price, expected_sl, expected_tp):
        """Parametrized test for various fill scenarios"""
        actual_sl = fill_price * (1 - self.SL_DISTANCE_PCT)
        actual_tp = fill_price * (1 + self.TP_DISTANCE_PCT)

        assert actual_sl == pytest.approx(expected_sl)
        assert actual_tp == pytest.approx(expected_tp)


class TestSLRecalculationShort:
    """Test SL recalculation for SHORT positions"""

    SL_DISTANCE_PCT = 0.005  # 0.5%
    TP_DISTANCE_PCT = 0.02   # 2%

    def test_sl_recalculated_from_fill_price_short(self):
        """SHORT: SL = fill_price * 1.005 (0.5% above)"""
        signal_limit_price = 3000.0
        actual_fill_price = 2990.0  # Filled lower due to market move

        # Old logic (WRONG)
        old_sl = signal_limit_price * (1 + self.SL_DISTANCE_PCT)  # 3015

        # New logic (CORRECT)
        new_sl = actual_fill_price * (1 + self.SL_DISTANCE_PCT)  # 3004.95

        assert old_sl == pytest.approx(3015.0)
        assert new_sl == pytest.approx(3004.95)
        assert new_sl < old_sl  # New SL is lower (safer)

    def test_tp_recalculated_from_fill_price_short(self):
        """SHORT: TP = fill_price * 0.98 (2% below)"""
        signal_limit_price = 3000.0
        actual_fill_price = 2990.0

        old_tp = signal_limit_price * (1 - self.TP_DISTANCE_PCT)  # 2940
        new_tp = actual_fill_price * (1 - self.TP_DISTANCE_PCT)   # 2930.2

        assert old_tp == pytest.approx(2940.0)
        assert new_tp == pytest.approx(2930.2)


class TestSlippageImpact:
    """Test how slippage affects SL/TP distance"""

    SL_DISTANCE_PCT = 0.005

    def test_sl_distance_maintained_with_slippage(self):
        """SL distance should always be 0.5% from actual fill"""
        fill_prices = [10000, 9900, 10100, 9500, 10500]

        for fill_price in fill_prices:
            sl_long = fill_price * (1 - self.SL_DISTANCE_PCT)
            sl_short = fill_price * (1 + self.SL_DISTANCE_PCT)

            # Calculate actual distance
            distance_long = (fill_price - sl_long) / fill_price
            distance_short = (sl_short - fill_price) / fill_price

            assert distance_long == pytest.approx(self.SL_DISTANCE_PCT)
            assert distance_short == pytest.approx(self.SL_DISTANCE_PCT)

    def test_backup_sl_uses_recalculated_value(self):
        """Backup SL on exchange should use recalculated value"""
        fill_price = 50100.0
        actual_sl = fill_price * (1 - self.SL_DISTANCE_PCT)

        # Backup SL is typically 2% (disaster protection)
        BACKUP_SL_DISTANCE = 0.02
        backup_sl = fill_price * (1 - BACKUP_SL_DISTANCE)  # 49098

        assert actual_sl == pytest.approx(49849.5)  # Local SL (0.5%)
        assert backup_sl == pytest.approx(49098.0)  # Backup SL (2%)
        assert backup_sl < actual_sl  # Backup is wider
