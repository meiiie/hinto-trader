
import pytest
from datetime import datetime
from src.domain.entities.local_position_tracker import LocalPosition, FillRecord

class TestLocalPosition:
    def test_calculate_pnl_long_with_fees(self):
        """Test LONG PnL calculation with fees."""
        # Arrange
        pos = LocalPosition(symbol="BTCUSDT", side="LONG", intended_leverage=20)

        # Add fill: Buy 1 BTC @ $100, Fee $0.10
        fill = FillRecord(
            timestamp=datetime.now(),
            order_id="1",
            price=100.0,
            quantity=1.0,
            fee=0.10,
            fee_asset="USDT"
        )
        pos.add_entry_fill(fill)

        # Act
        # Current price $110 (+10% gain)
        # Gross PnL: (110 - 100) * 1 = $10
        # Net PnL: $10 - $0.10 = $9.90
        net_pnl = pos.get_unrealized_pnl(current_price=110.0)

        # Assert
        assert net_pnl == pytest.approx(9.90)

    def test_calculate_pnl_short_with_fees(self):
        """Test SHORT PnL calculation with fees."""
        # Arrange
        pos = LocalPosition(symbol="BTCUSDT", side="SHORT", intended_leverage=20)

        # Add fill: Sell 1 BTC @ $100, Fee $0.10
        fill = FillRecord(
            timestamp=datetime.now(),
            order_id="1",
            price=100.0,
            quantity=1.0,
            fee=0.10,
            fee_asset="USDT"
        )
        pos.add_entry_fill(fill)

        # Act
        # Current price $90 (Price dropped $10)
        # Gross PnL: (100 - 90) * 1 = $10
        # Net PnL: $10 - $0.10 = $9.90
        net_pnl = pos.get_unrealized_pnl(current_price=90.0)

        # Assert
        assert net_pnl == pytest.approx(9.90)

    def test_roe_with_actual_leverage(self):
        """Test ROE calculation uses ACTUAL leverage, not intended."""
        # Arrange
        pos = LocalPosition(symbol="BTCUSDT", side="LONG", intended_leverage=50) # Intended 50x

        # Add fill: Buy 1 BTC @ $100
        fill = FillRecord(
            timestamp=datetime.now(),
            order_id="1",
            price=100.0,
            quantity=1.0,
            fee=0.0, # Simplify fee for ROE check
            fee_asset="USDT"
        )
        pos.add_entry_fill(fill)

        # Confirm ACTUAL leverage is only 10x (Exchange limit)
        pos.set_actual_leverage(10)

        # Act
        # Margin Used: $100 / 10x = $10 (NOT $2 like intended)
        # Price moves to $110 (+$10 PnL)
        # ROE = ($10 PnL / $10 Margin) * 100 = 100%
        roe = pos.get_roe_percent(current_price=110.0)

        # Assert
        assert roe == pytest.approx(100.0)

        # Verify it ignores intended leverage
        # If it used 50x: Margin $2 -> ROE 500% (WRONG)
        assert roe != 500.0

    def test_auto_close_threshold(self):
        """Test if PnL correctly triggers 17% threshold."""
        # Arrange
        pos = LocalPosition(symbol="BTCUSDT", side="LONG", intended_leverage=20)
        pos.add_entry_fill(FillRecord(datetime.now(), "1", 100.0, 1.0, 0.0))
        pos.set_actual_leverage(20) # 20x confirmed

        # Act
        # Margin: $5.0
        # Target ROE: 17% -> PnL needed: $5.0 * 0.17 = $0.85
        # Target Price: $100 + $0.85 = $100.85

        roe_at_target = pos.get_roe_percent(current_price=100.85)

        # Assert
        assert roe_at_target == pytest.approx(17.0)
