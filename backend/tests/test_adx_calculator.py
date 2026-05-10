"""
Unit tests for ADX Calculator
"""

import pytest
from datetime import datetime, timedelta
from src.infrastructure.indicators.adx_calculator import ADXCalculator, ADXResult
from src.domain.entities.candle import Candle


def create_test_candle(
    timestamp: datetime,
    open_price: float,
    high: float,
    low: float,
    close: float,
    volume: float = 1000.0
) -> Candle:
    """Helper to create test candle"""
    return Candle(
        timestamp=timestamp,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume
    )


def create_trending_candles(count: int = 40, trend: str = 'up') -> list:
    """Create candles with clear trend"""
    candles = []
    base_time = datetime(2025, 1, 1, 0, 0, 0)
    base_price = 100.0

    for i in range(count):
        timestamp = base_time + timedelta(minutes=15 * i)

        if trend == 'up':
            # Uptrend: higher highs and higher lows
            open_price = base_price + (i * 2)
            high = open_price + 3
            low = open_price - 1
            close = open_price + 2
        else:  # downtrend
            # Downtrend: lower highs and lower lows
            open_price = base_price - (i * 2)
            high = open_price + 1
            low = open_price - 3
            close = open_price - 2

        candle = create_test_candle(timestamp, open_price, high, low, close)
        candles.append(candle)

    return candles


def create_choppy_candles(count: int = 40) -> list:
    """Create candles with no clear trend (choppy market)"""
    candles = []
    base_time = datetime(2025, 1, 1, 0, 0, 0)
    base_price = 100.0

    for i in range(count):
        timestamp = base_time + timedelta(minutes=15 * i)

        # Oscillate around base price
        if i % 2 == 0:
            open_price = base_price + 1
            high = base_price + 2
            low = base_price
            close = base_price + 0.5
        else:
            open_price = base_price - 1
            high = base_price
            low = base_price - 2
            close = base_price - 0.5

        candle = create_test_candle(timestamp, open_price, high, low, close)
        candles.append(candle)

    return candles


class TestADXCalculator:
    """Test suite for ADXCalculator"""

    def test_initialization(self):
        """Test ADX calculator initialization"""
        calculator = ADXCalculator(period=14)
        assert calculator.period == 14
        assert isinstance(calculator, ADXCalculator)

    def test_initialization_invalid_period(self):
        """Test initialization with invalid period"""
        with pytest.raises(ValueError, match="ADX period must be at least 1"):
            ADXCalculator(period=0)

    def test_calculate_directional_movement_upward(self):
        """Test directional movement calculation with upward move"""
        calculator = ADXCalculator()

        previous = create_test_candle(
            datetime(2025, 1, 1), 100, 102, 98, 101
        )
        current = create_test_candle(
            datetime(2025, 1, 1, 0, 15), 101, 106, 99, 104
        )

        plus_dm, minus_dm = calculator.calculate_directional_movement(current, previous)

        # Up move = 106 - 102 = 4
        # Down move = 98 - 99 = -1 (negative, so 0)
        # +DM should be 4, -DM should be 0
        assert plus_dm == 4.0
        assert minus_dm == 0.0

    def test_calculate_directional_movement_downward(self):
        """Test directional movement calculation with downward move"""
        calculator = ADXCalculator()

        previous = create_test_candle(
            datetime(2025, 1, 1), 100, 102, 98, 101
        )
        current = create_test_candle(
            datetime(2025, 1, 1, 0, 15), 99, 101, 94, 96
        )

        plus_dm, minus_dm = calculator.calculate_directional_movement(current, previous)

        # Up move = 101 - 102 = -1 (negative, so 0)
        # Down move = 98 - 94 = 4
        # +DM should be 0, -DM should be 4
        assert plus_dm == 0.0
        assert minus_dm == 4.0

    def test_calculate_directional_movement_no_movement(self):
        """Test directional movement with no significant movement"""
        calculator = ADXCalculator()

        previous = create_test_candle(
            datetime(2025, 1, 1), 100, 102, 98, 101
        )
        current = create_test_candle(
            datetime(2025, 1, 1, 0, 15), 100, 101, 99, 100
        )

        plus_dm, minus_dm = calculator.calculate_directional_movement(current, previous)

        # Both movements are negative or zero
        assert plus_dm == 0.0
        assert minus_dm == 0.0

    def test_calculate_adx_insufficient_data(self):
        """Test ADX calculation with insufficient candles"""
        calculator = ADXCalculator(period=14)

        # Create only 20 candles (need 28 for period=14)
        candles = create_trending_candles(count=20)

        result = calculator.calculate_adx(candles)

        assert result.adx_value == 0.0
        assert result.period == 14
        assert result.num_candles == 20

    def test_calculate_adx_empty_list(self):
        """Test ADX calculation with empty candle list"""
        calculator = ADXCalculator(period=14)

        result = calculator.calculate_adx([])

        assert result.adx_value == 0.0
        assert result.num_candles == 0

    def test_calculate_adx_trending_market(self):
        """Test ADX calculation in trending market"""
        calculator = ADXCalculator(period=14)

        # Create strong uptrend
        candles = create_trending_candles(count=40, trend='up')

        result = calculator.calculate_adx(candles)

        # ADX should be > 25 in trending market
        assert result.adx_value > 25
        assert result.is_trending
        assert result.trend_strength in ['STRONG', 'VERY_STRONG']
        assert result.num_candles == 40

    def test_calculate_adx_choppy_market(self):
        """Test ADX calculation in choppy market"""
        calculator = ADXCalculator(period=14)

        # Create choppy market
        candles = create_choppy_candles(count=40)

        result = calculator.calculate_adx(candles)

        # ADX should be < 25 in choppy market
        assert result.adx_value < 25
        assert not result.is_trending
        assert result.trend_strength in ['WEAK', 'NO_TREND']

    def test_calculate_adx_custom_period(self):
        """Test ADX calculation with custom period"""
        calculator = ADXCalculator(period=14)

        candles = create_trending_candles(count=50)

        # Override period to 10
        result = calculator.calculate_adx(candles, period=10)

        assert result.period == 10
        assert result.adx_value > 0

    def test_adx_result_is_trending_property(self):
        """Test ADXResult is_trending property"""
        # Trending market
        result_trending = ADXResult(
            adx_value=30.0,
            plus_di=25.0,
            minus_di=15.0,
            period=14,
            num_candles=40
        )
        assert result_trending.is_trending is True

        # Choppy market
        result_choppy = ADXResult(
            adx_value=20.0,
            plus_di=15.0,
            minus_di=12.0,
            period=14,
            num_candles=40
        )
        assert result_choppy.is_trending is False

    def test_adx_result_trend_strength_property(self):
        """Test ADXResult trend_strength property"""
        # Very strong trend
        result_very_strong = ADXResult(
            adx_value=55.0, plus_di=30.0, minus_di=10.0, period=14, num_candles=40
        )
        assert result_very_strong.trend_strength == "VERY_STRONG"

        # Strong trend
        result_strong = ADXResult(
            adx_value=30.0, plus_di=25.0, minus_di=15.0, period=14, num_candles=40
        )
        assert result_strong.trend_strength == "STRONG"

        # Weak trend
        result_weak = ADXResult(
            adx_value=22.0, plus_di=18.0, minus_di=14.0, period=14, num_candles=40
        )
        assert result_weak.trend_strength == "WEAK"

        # No trend
        result_no_trend = ADXResult(
            adx_value=15.0, plus_di=12.0, minus_di=10.0, period=14, num_candles=40
        )
        assert result_no_trend.trend_strength == "NO_TREND"

    def test_adx_result_trend_direction_property(self):
        """Test ADXResult trend_direction property"""
        # Bullish (+DI > -DI)
        result_bullish = ADXResult(
            adx_value=30.0, plus_di=25.0, minus_di=15.0, period=14, num_candles=40
        )
        assert result_bullish.trend_direction == "BULLISH"

        # Bearish (-DI > +DI)
        result_bearish = ADXResult(
            adx_value=30.0, plus_di=15.0, minus_di=25.0, period=14, num_candles=40
        )
        assert result_bearish.trend_direction == "BEARISH"

        # Neutral (+DI == -DI)
        result_neutral = ADXResult(
            adx_value=20.0, plus_di=15.0, minus_di=15.0, period=14, num_candles=40
        )
        assert result_neutral.trend_direction == "NEUTRAL"

    def test_calculate_adx_uptrend_direction(self):
        """Test ADX correctly identifies uptrend direction"""
        calculator = ADXCalculator(period=14)

        candles = create_trending_candles(count=40, trend='up')
        result = calculator.calculate_adx(candles)

        # In uptrend, +DI should be > -DI
        assert result.plus_di > result.minus_di
        assert result.trend_direction == "BULLISH"

    def test_calculate_adx_downtrend_direction(self):
        """Test ADX correctly identifies downtrend direction"""
        calculator = ADXCalculator(period=14)

        candles = create_trending_candles(count=40, trend='down')
        result = calculator.calculate_adx(candles)

        # In downtrend, -DI should be > +DI
        assert result.minus_di > result.plus_di
        assert result.trend_direction == "BEARISH"

    def test_repr(self):
        """Test string representation"""
        calculator = ADXCalculator(period=14)
        repr_str = repr(calculator)

        assert 'ADXCalculator' in repr_str
        assert 'period=14' in repr_str


class TestADXCalculatorEdgeCases:
    """Test edge cases for ADX Calculator"""

    def test_single_candle(self):
        """Test with single candle"""
        calculator = ADXCalculator(period=14)
        candles = create_trending_candles(count=1)

        result = calculator.calculate_adx(candles)
        assert result.adx_value == 0.0

    def test_exact_minimum_candles(self):
        """Test with exact minimum number of candles"""
        calculator = ADXCalculator(period=14)
        candles = create_trending_candles(count=28)  # Exactly period * 2

        result = calculator.calculate_adx(candles)
        assert result.adx_value >= 0

    def test_very_small_movements(self):
        """Test with very small price movements"""
        calculator = ADXCalculator(period=10)

        base_time = datetime(2025, 1, 1)
        candles = []
        for i in range(30):
            timestamp = base_time + timedelta(minutes=15 * i)
            # Random small movements (choppy)
            if i % 2 == 0:
                price = 100.0 + 0.01
            else:
                price = 100.0 - 0.01
            candle = create_test_candle(
                timestamp, price, price + 0.01, price - 0.01, price
            )
            candles.append(candle)

        result = calculator.calculate_adx(candles)

        # ADX can vary, just check it's calculated
        assert 0 <= result.adx_value <= 100

    def test_very_large_movements(self):
        """Test with very large price movements"""
        calculator = ADXCalculator(period=10)

        base_time = datetime(2025, 1, 1)
        candles = []
        for i in range(30):
            timestamp = base_time + timedelta(minutes=15 * i)
            price = 100.0 + (i * 50)  # Large movements
            candle = create_test_candle(
                timestamp, price, price + 25, price - 10, price + 20
            )
            candles.append(candle)

        result = calculator.calculate_adx(candles)

        # ADX should be high (strong trend)
        assert result.adx_value > 25

    def test_alternating_trend(self):
        """Test with alternating up/down movements"""
        calculator = ADXCalculator(period=10)

        base_time = datetime(2025, 1, 1)
        candles = []
        for i in range(30):
            timestamp = base_time + timedelta(minutes=15 * i)

            if i % 4 < 2:
                # Up movement
                price = 100.0 + (i * 2)
                candle = create_test_candle(
                    timestamp, price, price + 3, price - 1, price + 2
                )
            else:
                # Down movement
                price = 100.0 + (i * 2)
                candle = create_test_candle(
                    timestamp, price, price + 1, price - 3, price - 2
                )

            candles.append(candle)

        result = calculator.calculate_adx(candles)

        # ADX should be moderate (mixed signals)
        assert 0 <= result.adx_value <= 100


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
