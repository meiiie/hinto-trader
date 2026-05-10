
import unittest
from datetime import datetime
from src.domain.entities.local_position_tracker import LocalPosition, FillRecord

class TestLocalPosition(unittest.TestCase):
    def test_net_quantity_logic(self):
        # 1. Init
        pos = LocalPosition(symbol="BTCUSDT", side="LONG", intended_leverage=20)

        # 2. Buy 100 @ $10
        fill1 = FillRecord(
            timestamp=datetime.now(), order_id="1", price=10.0, quantity=100.0,
            fee=0.1, fee_asset="USDT"
        )
        pos.add_entry_fill(fill1)

        self.assertEqual(pos.quantity, 100.0)
        self.assertEqual(pos.avg_entry_price, 10.0)

        # 3. Buy 100 @ $20
        fill2 = FillRecord(
            timestamp=datetime.now(), order_id="2", price=20.0, quantity=100.0,
            fee=0.2, fee_asset="USDT"
        )
        pos.add_entry_fill(fill2)

        self.assertEqual(pos.quantity, 200.0)
        self.assertEqual(pos.avg_entry_price, 15.0) # (100*10 + 100*20)/200 = 15

        # 4. Sell 50 @ $18 (Partial Exit)
        fill_exit = FillRecord(
            timestamp=datetime.now(), order_id="3", price=18.0, quantity=50.0,
            fee=0.1, fee_asset="USDT"
        )
        pos.add_exit_fill(fill_exit)

        # VERIFY NET QUANTITY
        self.assertEqual(pos.quantity, 150.0) # 200 - 50

        # 5. Check PnL on REMAINING 150
        # Current Price = $25
        # Avg Entry = $15
        # Expected Gross PnL = (25 - 15) * 150 = $1500
        pnl = pos.get_unrealized_pnl(current_price=25.0)

        # Fees are deducted (Pro-rated entry + Estimated exit)
        # Total Entry Fees = 0.3. Pro-rated for 150/200 = 0.225.
        # Exit Fee (Est) = 25 * 150 * 0.0006 = 2.25
        # Expected Net PnL = 1500 - 0.225 - 2.25 = 1497.525

        print(f"PnL: {pnl}")
        self.assertTrue(pnl > 1490 and pnl < 1510)

    def test_attribute_access(self):
        """Verify the specific bug that caused the crash is gone."""
        pos = LocalPosition(symbol="BTCUSDT", side="LONG", intended_leverage=20)
        # Should not raise AttributeError
        price = pos.avg_entry_price
        self.assertEqual(price, 0.0)

if __name__ == '__main__':
    unittest.main()
