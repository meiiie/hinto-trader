"""
Unit tests for ATR-based Stop Loss Calculator
"""

import pytest
from src.application.services.stop_loss_calculator import StopLossCalculator, StopLossResult


class TestATRBasedStopLoss:
    """Test ATR-based stop loss calculation"""

    def test_calculate_stop_loss_atr_based_buy(self):
        """Test ATR-based stop loss for BUY trade"""
        calculator = StopLossCalculator()

        result = calculator.calculate_stop_loss_atr_based(
            entry_price=50000.0,
            direction='BUY',
            atr_value=500.0,
            atr_multiplier=3.0
        )

        # Stop should be entry - (ATR × multiplier)
        # 50000 - (500 × 3) = 50000 - 1500 = 48500
        assert result.stop_loss == 48500.0
        assert result.stop_type == 'atr_based'
        assert result.is_valid is True
        assert result.distance_from_entry_pct == pytest.approx(0.03, rel=0.01)  # 3%

    def test_calculate_stop_loss_atr_based_sell(self):
        """Test ATR-based stop loss for SELL trade"""
        calculator = StopLossCalculator()

        result = calculator.calculate_stop_loss_atr_based(
            entry_price=50000.0,
            direction='SELL',
            atr_value=500.0,
            atr_multiplier=3.0
        )

        # Stop should be entry + (ATR × multiplier)
        # 50000 + (500 × 3) = 50000 + 1500 = 51500
        assert result.stop_loss == 51500.0
        assert result.stop_type == 'atr_based'
        assert result.is_valid is True

    def test_calculate_stop_loss_atr_minimum_distance(self):
        """Test minimum distance enforcement"""
        calculator = StopLossCalculator()

        # Very small ATR that would result in stop < 1.5%
        result = calculator.calculate_stop_loss_atr_based(
            entry_price=50000.0,
            direction='BUY',
            atr_value=100.0,  # Small ATR
            atr_multiplier=2.0,
            min_distance_pct=0.015  # 1.5% minimum
        )

        # Should use minimum distance instead of ATR
        # 50000 × 1.5% = 750
        # Stop = 50000 - 750 = 49250
        expected_stop = 50000.0 - (50000.0 * 0.015)
        assert result.stop_loss == expected_stop
        assert result.distance_from_entry_pct >= 0.015

    def test_calculate_stop_loss_atr_invalid_direction(self):
        """Test invalid direction raises error"""
        calculator = StopLossCalculator()

        with pytest.raises(ValueError, match="Invalid direction"):
            calculator.calculate_stop_loss_atr_based(
                entry_price=50000.0,
                direction='INVALID',
                atr_value=500.0
            )

    def test_calculate_stop_loss_atr_invalid_entry_price(self):
        """Test invalid entry price raises error"""
        calculator = StopLossCalculator()

        with pytest.raises(ValueError, match="Entry price must be positive"):
            calculator.calculate_stop_loss_atr_based(
                entry_price=-50000.0,
                direction='BUY',
                atr_value=500.0
            )

    def test_calculate_stop_loss_atr_negative_atr(self):
        """Test negative ATR raises error"""
        calculator = StopLossCalculator()

        with pytest.raises(ValueError, match="ATR value must be non-negative"):
            calculator.calculate_stop_loss_atr_based(
                entry_price=50000.0,
                direction='BUY',
                atr_value=-500.0
            )

    def test_calculate_stop_loss_atr_different_multipliers(self):
        """Test different ATR multipliers"""
        calculator = StopLossCalculator()

        # 15m timeframe (3.0x)
        result_15m = calculator.calculate_stop_loss_atr_based(
            entry_price=50000.0,
            direction='BUY',
            atr_value=500.0,
            atr_multiplier=3.0
        )

        # 1h timeframe (2.5x)
        result_1h = calculator.calculate_stop_loss_atr_based(
            entry_price=50000.0,
            direction='BUY',
            atr_value=500.0,
            atr_multiplier=2.5
        )

        # 15m should have wider stop (lower price for BUY)
        assert result_15m.stop_loss < result_1h.stop_loss

    def test_calculate_position_size_with_risk(self):
        """Test position size calculation with 1% risk rule"""
        calculator = StopLossCalculator()

        position = calculator.calculate_position_size_with_risk(
            entry_price=50000.0,
            stop_loss=49000.0,
            account_balance=10000.0,
            risk_pct=0.01
        )

        # Risk amount = 10000 × 1% = 100
        # Stop distance = 50000 - 49000 = 1000
        # Position = 100 / 1000 = 0.1 BTC
        assert position == pytest.approx(0.1, rel=0.001)

        # Verify: if SL hit, loss = 0.1 × 1000 = $100 (1% of $10,000)
        actual_loss = position * 1000
        assert actual_loss == pytest.approx(100.0, rel=0.01)

    def test_calculate_position_size_different_risk_levels(self):
        """Test position sizing with different risk percentages"""
        calculator = StopLossCalculator()

        # 1% risk
        position_1pct = calculator.calculate_position_size_with_risk(
            entry_price=50000.0,
            stop_loss=49500.0,
            account_balance=10000.0,
            risk_pct=0.01
        )

        # 2% risk
        position_2pct = calculator.calculate_position_size_with_risk(
            entry_price=50000.0,
            stop_loss=49500.0,
            account_balance=10000.0,
            risk_pct=0.02
        )

        # 2% risk should have 2x position size
        assert position_2pct == pytest.approx(position_1pct * 2, rel=0.01)

    def test_calculate_position_size_invalid_inputs(self):
        """Test position size calculation with invalid inputs"""
        calculator = StopLossCalculator()

        # Negative entry price
        with pytest.raises(ValueError, match="Entry price must be positive"):
            calculator.calculate_position_size_with_risk(
                entry_price=-50000.0,
                stop_loss=49000.0,
                account_balance=10000.0
            )

        # Negative account balance
        with pytest.raises(ValueError, match="Account balance must be positive"):
            calculator.calculate_position_size_with_risk(
                entry_price=50000.0,
                stop_loss=49000.0,
                account_balance=-10000.0
            )

        # Risk too high
        with pytest.raises(ValueError, match="Risk percentage must be between"):
            calculator.calculate_position_size_with_risk(
                entry_price=50000.0,
                stop_loss=49000.0,
                account_balance=10000.0,
                risk_pct=0.10  # 10% is too high
            )

    def test_calculate_position_size_zero_stop_distance(self):
        """Test position size when stop distance is zero"""
        calculator = StopLossCalculator()

        position = calculator.calculate_position_size_with_risk(
            entry_price=50000.0,
            stop_loss=50000.0,  # Same as entry
            account_balance=10000.0
        )

        # Should return 0 when stop distance is zero
        assert position == 0.0

    def test_calculate_position_size_precision(self):
        """Test position size has 8 decimal precision (BTC standard)"""
        calculator = StopLossCalculator()

        position = calculator.calculate_position_size_with_risk(
            entry_price=50000.0,
            stop_loss=49999.0,
            account_balance=10000.0
        )

        # Check precision
        position_str = f"{position:.8f}"
        decimal_places = len(position_str.split('.')[-1])
        assert decimal_places == 8

    def test_atr_based_stop_with_position_sizing(self):
        """Test complete flow: ATR stop + position sizing"""
        calculator = StopLossCalculator()

        # Step 1: Calculate ATR-based stop
        stop_result = calculator.calculate_stop_loss_atr_based(
            entry_price=50000.0,
            direction='BUY',
            atr_value=500.0,
            atr_multiplier=3.0
        )

        # Step 2: Calculate position size
        position = calculator.calculate_position_size_with_risk(
            entry_price=50000.0,
            stop_loss=stop_result.stop_loss,
            account_balance=10000.0,
            risk_pct=0.01
        )

        # Verify risk is exactly 1%
        stop_distance = 50000.0 - stop_result.stop_loss
        actual_risk = position * stop_distance
        risk_pct = (actual_risk / 10000.0) * 100

        assert risk_pct == pytest.approx(1.0, rel=0.01)

    def test_atr_based_stop_very_low_atr(self):
        """Test ATR-based stop with very low ATR value"""
        calculator = StopLossCalculator()

        result = calculator.calculate_stop_loss_atr_based(
            entry_price=50000.0,
            direction='BUY',
            atr_value=50.0,  # Very low ATR
            atr_multiplier=3.0,
            min_distance_pct=0.015
        )

        # Should enforce minimum distance
        assert result.distance_from_entry_pct >= 0.015

    def test_atr_based_stop_very_high_atr(self):
        """Test ATR-based stop with very high ATR value"""
        calculator = StopLossCalculator()

        result = calculator.calculate_stop_loss_atr_based(
            entry_price=50000.0,
            direction='BUY',
            atr_value=2000.0,  # Very high ATR
            atr_multiplier=3.0
        )

        # Stop distance should be 6000 (2000 × 3)
        expected_stop = 50000.0 - 6000.0
        assert result.stop_loss == expected_stop
        assert result.distance_from_entry_pct == pytest.approx(0.12, rel=0.01)  # 12%


class TestPositionSizingEdgeCases:
    """Test edge cases for position sizing"""

    def test_position_size_small_account(self):
        """Test position sizing with small account"""
        calculator = StopLossCalculator()

        position = calculator.calculate_position_size_with_risk(
            entry_price=50000.0,
            stop_loss=49000.0,
            account_balance=100.0,  # Small account
            risk_pct=0.01
        )

        # Risk = $1, Stop distance = $1000
        # Position = 1 / 1000 = 0.001 BTC
        assert position == pytest.approx(0.001, rel=0.001)

    def test_position_size_large_account(self):
        """Test position sizing with large account"""
        calculator = StopLossCalculator()

        position = calculator.calculate_position_size_with_risk(
            entry_price=50000.0,
            stop_loss=49000.0,
            account_balance=1000000.0,  # Large account
            risk_pct=0.01
        )

        # Risk = $10,000, Stop distance = $1000
        # Position = 10000 / 1000 = 10 BTC
        assert position == pytest.approx(10.0, rel=0.001)

    def test_position_size_tight_stop(self):
        """Test position sizing with tight stop"""
        calculator = StopLossCalculator()

        position = calculator.calculate_position_size_with_risk(
            entry_price=50000.0,
            stop_loss=49900.0,  # Tight stop (100 distance)
            account_balance=10000.0,
            risk_pct=0.01
        )

        # Risk = $100, Stop distance = $100
        # Position = 100 / 100 = 1.0 BTC
        assert position == pytest.approx(1.0, rel=0.001)

    def test_position_size_wide_stop(self):
        """Test position sizing with wide stop"""
        calculator = StopLossCalculator()

        position = calculator.calculate_position_size_with_risk(
            entry_price=50000.0,
            stop_loss=45000.0,  # Wide stop (5000 distance)
            account_balance=10000.0,
            risk_pct=0.01
        )

        # Risk = $100, Stop distance = $5000
        # Position = 100 / 5000 = 0.02 BTC
        assert position == pytest.approx(0.02, rel=0.001)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
