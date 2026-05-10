"""
Unit tests for ATR-based Take Profit Calculator
"""

import pytest
from src.application.services.tp_calculator import TPCalculator, TPCalculationResult


class TestATRBasedTakeProfit:
    """Test ATR-based take profit calculation"""

    def test_calculate_tp_levels_atr_based_buy(self):
        """Test ATR-based TP levels for BUY trade"""
        calculator = TPCalculator()

        result = calculator.calculate_tp_levels_atr_based(
            entry_price=50000.0,
            direction='BUY',
            atr_value=500.0
        )

        # TP1 = entry + (1 × ATR) = 50000 + 500 = 50500
        # TP2 = entry + (2 × ATR) = 50000 + 1000 = 51000
        # TP3 = entry + (3 × ATR) = 50000 + 1500 = 51500
        assert result.tp_levels.tp1 == 50500.0
        assert result.tp_levels.tp2 == 51000.0
        assert result.tp_levels.tp3 == 51500.0
        assert result.is_valid is True

    def test_calculate_tp_levels_atr_based_sell(self):
        """Test ATR-based TP levels for SELL trade"""
        calculator = TPCalculator()

        result = calculator.calculate_tp_levels_atr_based(
            entry_price=50000.0,
            direction='SELL',
            atr_value=500.0
        )

        # TP1 = entry - (1 × ATR) = 50000 - 500 = 49500
        # TP2 = entry - (2 × ATR) = 50000 - 1000 = 49000
        # TP3 = entry - (3 × ATR) = 50000 - 1500 = 48500
        assert result.tp_levels.tp1 == 49500.0
        assert result.tp_levels.tp2 == 49000.0
        assert result.tp_levels.tp3 == 48500.0
        assert result.is_valid is True

    def test_tp_levels_position_sizes(self):
        """Test TP levels have correct position sizes"""
        calculator = TPCalculator()

        result = calculator.calculate_tp_levels_atr_based(
            entry_price=50000.0,
            direction='BUY',
            atr_value=500.0
        )

        # Position sizes should be 50%, 30%, 20%
        assert result.tp_levels.sizes == [0.5, 0.3, 0.2]
        assert sum(result.tp_levels.sizes) == 1.0  # Total 100%

    def test_tp_levels_risk_reward_ratio(self):
        """Test R:R ratio calculation"""
        calculator = TPCalculator()

        result = calculator.calculate_tp_levels_atr_based(
            entry_price=50000.0,
            direction='BUY',
            atr_value=500.0
        )

        # Assuming stop at entry - (3 × ATR) = 50000 - 1500 = 48500
        # Risk = 50000 - 48500 = 1500
        # Reward (TP1) = 50500 - 50000 = 500
        # R:R = 500 / 1500 = 0.333 (1:3 ratio, or 1:1 if we consider TP1 is 1x ATR)
        assert result.risk_reward_ratio > 0

    def test_calculate_tp_levels_atr_invalid_direction(self):
        """Test invalid direction raises error"""
        calculator = TPCalculator()

        with pytest.raises(ValueError, match="Invalid direction"):
            calculator.calculate_tp_levels_atr_based(
                entry_price=50000.0,
                direction='INVALID',
                atr_value=500.0
            )

    def test_calculate_tp_levels_atr_invalid_entry_price(self):
        """Test invalid entry price raises error"""
        calculator = TPCalculator()

        with pytest.raises(ValueError, match="Entry price must be positive"):
            calculator.calculate_tp_levels_atr_based(
                entry_price=-50000.0,
                direction='BUY',
                atr_value=500.0
            )

    def test_calculate_tp_levels_atr_negative_atr(self):
        """Test negative ATR raises error"""
        calculator = TPCalculator()

        with pytest.raises(ValueError, match="ATR value must be non-negative"):
            calculator.calculate_tp_levels_atr_based(
                entry_price=50000.0,
                direction='BUY',
                atr_value=-500.0
            )

    def test_tp_levels_ordering_buy(self):
        """Test TP levels are correctly ordered for BUY"""
        calculator = TPCalculator()

        result = calculator.calculate_tp_levels_atr_based(
            entry_price=50000.0,
            direction='BUY',
            atr_value=500.0
        )

        # For BUY: entry < TP1 < TP2 < TP3
        assert 50000.0 < result.tp_levels.tp1
        assert result.tp_levels.tp1 < result.tp_levels.tp2
        assert result.tp_levels.tp2 < result.tp_levels.tp3

    def test_tp_levels_ordering_sell(self):
        """Test TP levels are correctly ordered for SELL"""
        calculator = TPCalculator()

        result = calculator.calculate_tp_levels_atr_based(
            entry_price=50000.0,
            direction='SELL',
            atr_value=500.0
        )

        # For SELL: entry > TP1 > TP2 > TP3
        assert 50000.0 > result.tp_levels.tp1
        assert result.tp_levels.tp1 > result.tp_levels.tp2
        assert result.tp_levels.tp2 > result.tp_levels.tp3

    def test_tp_levels_different_atr_values(self):
        """Test TP levels with different ATR values"""
        calculator = TPCalculator()

        # Low volatility (small ATR)
        result_low = calculator.calculate_tp_levels_atr_based(
            entry_price=50000.0,
            direction='BUY',
            atr_value=200.0
        )

        # High volatility (large ATR)
        result_high = calculator.calculate_tp_levels_atr_based(
            entry_price=50000.0,
            direction='BUY',
            atr_value=1000.0
        )

        # Higher ATR should result in wider TP levels
        assert result_high.tp_levels.tp1 > result_low.tp_levels.tp1
        assert result_high.tp_levels.tp2 > result_low.tp_levels.tp2
        assert result_high.tp_levels.tp3 > result_low.tp_levels.tp3

    def test_tp_levels_zero_atr(self):
        """Test TP levels with zero ATR"""
        calculator = TPCalculator()

        result = calculator.calculate_tp_levels_atr_based(
            entry_price=50000.0,
            direction='BUY',
            atr_value=0.0
        )

        # With zero ATR, TP levels should equal entry price
        assert result.tp_levels.tp1 == 50000.0
        assert result.tp_levels.tp2 == 50000.0
        assert result.tp_levels.tp3 == 50000.0

    def test_tp_levels_very_small_atr(self):
        """Test TP levels with very small ATR"""
        calculator = TPCalculator()

        result = calculator.calculate_tp_levels_atr_based(
            entry_price=50000.0,
            direction='BUY',
            atr_value=10.0  # Very small ATR
        )

        # TP levels should be close to entry
        assert result.tp_levels.tp1 == 50010.0
        assert result.tp_levels.tp2 == 50020.0
        assert result.tp_levels.tp3 == 50030.0

    def test_tp_levels_very_large_atr(self):
        """Test TP levels with very large ATR"""
        calculator = TPCalculator()

        result = calculator.calculate_tp_levels_atr_based(
            entry_price=50000.0,
            direction='BUY',
            atr_value=5000.0  # Very large ATR
        )

        # TP levels should be far from entry
        assert result.tp_levels.tp1 == 55000.0
        assert result.tp_levels.tp2 == 60000.0
        assert result.tp_levels.tp3 == 65000.0


class TestTPLevelsIntegration:
    """Test integration scenarios"""

    def test_complete_trade_setup(self):
        """Test complete trade setup with ATR-based TP"""
        calculator = TPCalculator()

        entry_price = 50000.0
        atr_value = 500.0

        # Calculate TP levels
        result = calculator.calculate_tp_levels_atr_based(
            entry_price=entry_price,
            direction='BUY',
            atr_value=atr_value
        )

        # Verify complete setup
        assert result.tp_levels.tp1 > entry_price
        assert result.tp_levels.tp2 > result.tp_levels.tp1
        assert result.tp_levels.tp3 > result.tp_levels.tp2
        assert len(result.tp_levels.sizes) == 3
        assert sum(result.tp_levels.sizes) == 1.0

    def test_partial_exit_simulation(self):
        """Test partial exit simulation"""
        calculator = TPCalculator()

        result = calculator.calculate_tp_levels_atr_based(
            entry_price=50000.0,
            direction='BUY',
            atr_value=500.0
        )

        # Simulate partial exits
        initial_position = 1.0  # 1 BTC

        # TP1 hit: exit 50%
        remaining_after_tp1 = initial_position * (1 - result.tp_levels.sizes[0])
        assert remaining_after_tp1 == 0.5

        # TP2 hit: exit 30% of original
        remaining_after_tp2 = remaining_after_tp1 - (initial_position * result.tp_levels.sizes[1])
        assert remaining_after_tp2 == pytest.approx(0.2, rel=0.01)

        # TP3 hit: exit remaining 20%
        remaining_after_tp3 = remaining_after_tp2 - (initial_position * result.tp_levels.sizes[2])
        assert remaining_after_tp3 == pytest.approx(0.0, abs=0.01)

    def test_profit_calculation(self):
        """Test profit calculation at each TP level"""
        calculator = TPCalculator()

        entry_price = 50000.0
        position_size = 1.0  # 1 BTC

        result = calculator.calculate_tp_levels_atr_based(
            entry_price=entry_price,
            direction='BUY',
            atr_value=500.0
        )

        # Calculate profits
        profit_tp1 = (result.tp_levels.tp1 - entry_price) * position_size * result.tp_levels.sizes[0]
        profit_tp2 = (result.tp_levels.tp2 - entry_price) * position_size * result.tp_levels.sizes[1]
        profit_tp3 = (result.tp_levels.tp3 - entry_price) * position_size * result.tp_levels.sizes[2]

        total_profit = profit_tp1 + profit_tp2 + profit_tp3

        # Verify profits are positive
        assert profit_tp1 > 0
        assert profit_tp2 > 0
        assert profit_tp3 > 0
        assert total_profit > 0

        # TP3 should have highest profit per unit (but smallest position)
        assert (result.tp_levels.tp3 - entry_price) > (result.tp_levels.tp2 - entry_price)
        assert (result.tp_levels.tp2 - entry_price) > (result.tp_levels.tp1 - entry_price)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
