"""
Unit tests for ATR Calculator
"""

import pytest
from datetime import datetime, timedelta
from src.infrastructure.indicators.atr_calculator import ATRCalculator, ATRResult
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


def create_test_candles(count: int = 20, base_price: float = 100.0) -> list:
    """Create list of test candles with realistic price movements"""
    candles = []
    base_time = datetime(2025, 1, 1, 0, 0, 0)

    for i in range(count):
        timestamp = base_time + timedelta(minutes=15 * i)
        # Simulate price movement
        open_price = base_price + (i * 0.5)
        high = open_price + 2.0
        low = open_price - 1.5
        close = open_price + 0.5

        candle = create_test_candle(timestamp, open_price, high, low, close)
        candles.append(candle)

    return candles


class TestATRCalculator:
    """Test suite for ATRCalculator"""

    def test_initialization(self):
        """Test ATR calculator initialization"""
        calculator = ATRCalculator(period=14)
        assert calculator.period == 14
        assert isinstance(calculator, ATRCalculator)

    def test_initialization_invalid_period(self):
        """Test initialization with invalid period"""
        with pytest.raises(ValueError, match="ATR period must be at least 1"):
            ATRCalculator(period=0)

    def test_calculate_true_range_basic(self):
        """Test basic true range calculation"""
        calculator = ATRCalculator()

        # Create test candles
        previous = create_test_candle(
            datetime(2025, 1, 1), 100, 102, 98, 101
        )
        current = create_test_candle(
            datetime(2025, 1, 1, 0, 15), 101, 105, 99, 103
        )

        tr = calculator.calculate_true_range(current, previous)

        # TR should be max of:
        # 1. High - Low = 105 - 99 = 6
        # 2. |High - Prev Close| = |105 - 101| = 4
        # 3. |Low - Prev Close| = |99 - 101| = 2
        # Expected: 6
        assert tr == 6.0

    def test_calculate_true_range_gap_up(self):
        """Test true range with gap up"""
        calculator = ATRCalculator()

        previous = create_test_candle(
            datetime(2025, 1, 1), 100, 102, 98, 100
        )
        current = create_test_candle(
            datetime(2025, 1, 1, 0, 15), 105, 107, 104, 106
        )

        tr = calculator.calculate_true_range(current, previous)

        # TR should be max of:
        # 1. High - Low = 107 - 104 = 3
        # 2. |High - Prev Close| = |107 - 100| = 7
        # 3. |Low - Prev Close| = |104 - 100| = 4
        # Expected: 7
        assert tr == 7.0

    def test_calculate_true_range_gap_down(self):
        """Test true range with gap down"""
        calculator = ATRCalculator()

        previous = create_test_candle(
            datetime(2025, 1, 1), 100, 102, 98, 100
        )
        current = create_test_candle(
            datetime(2025, 1, 1, 0, 15), 95, 97, 93, 94
        )

        tr = calculator.calculate_true_range(current, previous)

        # TR should be max of:
        # 1. High - Low = 97 - 93 = 4
        # 2. |High - Prev Close| = |97 - 100| = 3
        # 3. |Low - Prev Close| = |93 - 100| = 7
        # Expected: 7
        assert tr == 7.0

    def test_calculate_atr_insufficient_data(self):
        """Test ATR calculation with insufficient candles"""
        calculator = ATRCalculator(period=14)

        # Create only 10 candles (need 15 for period=14)
        candles = create_test_candles(count=10)

        result = calculator.calculate_atr(candles)

        assert result.atr_value == 0.0
        assert result.period == 14
        assert result.num_candles == 10

    def test_calculate_atr_empty_list(self):
        """Test ATR calculation with empty candle list"""
        calculator = ATRCalculator(period=14)

        result = calculator.calculate_atr([])

        assert result.atr_value == 0.0
        assert result.num_candles == 0

    def test_calculate_atr_basic(self):
        """Test basic ATR calculation with sufficient data"""
        calculator = ATRCalculator(period=14)

        # Create 20 candles (enough for period=14)
        candles = create_test_candles(count=20, base_price=100.0)

        result = calculator.calculate_atr(candles)

        # ATR should be positive
        assert result.atr_value > 0
        assert result.period == 14
        assert result.num_candles == 20
        assert result.timeframe == '15m'

    def test_calculate_atr_with_known_values(self):
        """Test ATR calculation with known values"""
        calculator = ATRCalculator(period=3)

        # Create candles with known true ranges
        base_time = datetime(2025, 1, 1)
        candles = [
            create_test_candle(base_time, 100, 105, 95, 102),  # TR will be calculated from next
            create_test_candle(base_time + timedelta(minutes=15), 102, 108, 100, 105),  # TR = 8
            create_test_candle(base_time + timedelta(minutes=30), 105, 110, 103, 107),  # TR = 7
            create_test_candle(base_time + timedelta(minutes=45), 107, 112, 105, 109),  # TR = 7
            create_test_candle(base_time + timedelta(minutes=60), 109, 114, 107, 111),  # TR = 7
        ]

        result = calculator.calculate_atr(candles)

        # Initial ATR = (8 + 7 + 7) / 3 = 7.33
        # Next ATR = ((7.33 * 2) + 7) / 3 = 7.22
        # ATR should be around 7.22
        assert 7.0 <= result.atr_value <= 7.5

    def test_calculate_atr_custom_period(self):
        """Test ATR calculation with custom period"""
        calculator = ATRCalculator(period=14)

        candles = create_test_candles(count=25)

        # Override period to 10
        result = calculator.calculate_atr(candles, period=10)

        assert result.period == 10
        assert result.atr_value > 0

    def test_calculate_atr_custom_timeframe(self):
        """Test ATR calculation with custom timeframe"""
        calculator = ATRCalculator(period=14)

        candles = create_test_candles(count=20)

        result = calculator.calculate_atr(candles, timeframe='1h')

        assert result.timeframe == '1h'

    def test_atr_result_get_stop_distance(self):
        """Test ATRResult get_stop_distance method"""
        result = ATRResult(
            atr_value=500.0,
            period=14,
            timeframe='15m',
            num_candles=20
        )

        # Default multiplier 3.0
        stop_distance = result.get_stop_distance()
        assert stop_distance == 1500.0

        # Custom multiplier
        stop_distance = result.get_stop_distance(multiplier=2.5)
        assert stop_distance == 1250.0

    def test_atr_result_get_tp_distance(self):
        """Test ATRResult get_tp_distance method"""
        result = ATRResult(
            atr_value=500.0,
            period=14,
            timeframe='15m',
            num_candles=20
        )

        # Default multiplier 2.0
        tp_distance = result.get_tp_distance()
        assert tp_distance == 1000.0

        # Custom multiplier
        tp_distance = result.get_tp_distance(multiplier=3.0)
        assert tp_distance == 1500.0

    def test_get_atr_multiplier_for_timeframe(self):
        """Test ATR multiplier recommendations for different timeframes"""
        calculator = ATRCalculator()

        assert calculator.get_atr_multiplier_for_timeframe('15m') == 3.0
        assert calculator.get_atr_multiplier_for_timeframe('1h') == 2.5
        assert calculator.get_atr_multiplier_for_timeframe('4h') == 2.0
        assert calculator.get_atr_multiplier_for_timeframe('1d') == 1.5

        # Unknown timeframe should return default
        assert calculator.get_atr_multiplier_for_timeframe('unknown') == 3.0

    def test_wilders_smoothing_accuracy(self):
        """Test Wilder's smoothing calculation accuracy"""
        calculator = ATRCalculator(period=3)

        # Create candles with predictable true ranges
        base_time = datetime(2025, 1, 1)
        candles = [
            create_test_candle(base_time, 100, 110, 90, 105),
            create_test_candle(base_time + timedelta(minutes=15), 105, 115, 95, 110),  # TR = 20
            create_test_candle(base_time + timedelta(minutes=30), 110, 120, 100, 115),  # TR = 20
            create_test_candle(base_time + timedelta(minutes=45), 115, 125, 105, 120),  # TR = 20
        ]

        result = calculator.calculate_atr(candles)

        # All TRs are 20, so ATR should be 20
        assert result.atr_value == 20.0

    def test_repr(self):
        """Test string representation"""
        calculator = ATRCalculator(period=14)
        repr_str = repr(calculator)

        assert 'ATRCalculator' in repr_str
        assert 'period=14' in repr_str


class TestATRCalculatorEdgeCases:
    """Test edge cases for ATR Calculator"""

    def test_single_candle(self):
        """Test with single candle"""
        calculator = ATRCalculator(period=14)
        candles = create_test_candles(count=1)

        result = calculator.calculate_atr(candles)
        assert result.atr_value == 0.0

    def test_exact_minimum_candles(self):
        """Test with exact minimum number of candles"""
        calculator = ATRCalculator(period=14)
        candles = create_test_candles(count=15)  # Exactly period + 1

        result = calculator.calculate_atr(candles)
        assert result.atr_value > 0

    def test_very_small_price_movements(self):
        """Test with very small price movements"""
        calculator = ATRCalculator(period=5)

        base_time = datetime(2025, 1, 1)
        candles = []
        for i in range(10):
            timestamp = base_time + timedelta(minutes=15 * i)
            price = 100.0 + (i * 0.01)  # Very small movements
            candle = create_test_candle(
                timestamp, price, price + 0.01, price - 0.01, price
            )
            candles.append(candle)

        result = calculator.calculate_atr(candles)

        # ATR should be very small but positive
        assert 0 < result.atr_value < 0.1

    def test_very_large_price_movements(self):
        """Test with very large price movements"""
        calculator = ATRCalculator(period=5)

        base_time = datetime(2025, 1, 1)
        candles = []
        for i in range(10):
            timestamp = base_time + timedelta(minutes=15 * i)
            price = 100.0 + (i * 100)  # Large movements
            candle = create_test_candle(
                timestamp, price, price + 50, price - 50, price
            )
            candles.append(candle)

        result = calculator.calculate_atr(candles)

        # ATR should be large
        assert result.atr_value > 50


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
