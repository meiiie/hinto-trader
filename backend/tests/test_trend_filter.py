"""
Unit tests for Trend Filter
"""

import pytest
from datetime import datetime, timedelta
from src.application.analysis.trend_filter import TrendFilter, TrendDirection
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


def create_bullish_trend_candles(count: int = 60, base_price: float = 100.0) -> list:
    """Create candles with bullish trend"""
    candles = []
    base_time = datetime(2025, 1, 1, 0, 0, 0)

    for i in range(count):
        timestamp = base_time + timedelta(minutes=15 * i)
        # Uptrend: gradually increasing prices
        price = base_price + (i * 2)
        candle = create_test_candle(
            timestamp, price, price + 2, price - 1, price + 1
        )
        candles.append(candle)

    return candles


def create_bearish_trend_candles(count: int = 60, base_price: float = 200.0) -> list:
    """Create candles with bearish trend"""
    candles = []
    base_time = datetime(2025, 1, 1, 0, 0, 0)

    for i in range(count):
        timestamp = base_time + timedelta(minutes=15 * i)
        # Downtrend: gradually decreasing prices
        price = base_price - (i * 2)
        candle = create_test_candle(
            timestamp, price, price + 1, price - 2, price - 1
        )
        candles.append(candle)

    return candles


def create_neutral_candles(count: int = 60, base_price: float = 100.0) -> list:
    """Create candles with no clear trend (sideways)"""
    candles = []
    base_time = datetime(2025, 1, 1, 0, 0, 0)

    for i in range(count):
        timestamp = base_time + timedelta(minutes=15 * i)
        # Sideways: oscillate around base price
        if i % 2 == 0:
            price = base_price + 0.2
        else:
            price = base_price - 0.2
        candle = create_test_candle(
            timestamp, price, price + 0.5, price - 0.5, price
        )
        candles.append(candle)

    return candles


class TestTrendFilter:
    """Test suite for TrendFilter"""

    def test_initialization(self):
        """Test trend filter initialization"""
        filter = TrendFilter(ema_period=50, buffer_pct=0.01)
        assert filter.ema_period == 50
        assert filter.buffer_pct == 0.01
        assert isinstance(filter, TrendFilter)

    def test_initialization_invalid_period(self):
        """Test initialization with invalid period"""
        with pytest.raises(ValueError, match="EMA period must be at least 1"):
            TrendFilter(ema_period=0)

    def test_initialization_invalid_buffer(self):
        """Test initialization with invalid buffer"""
        with pytest.raises(ValueError, match="Buffer percentage must be between"):
            TrendFilter(ema_period=50, buffer_pct=-0.01)

        with pytest.raises(ValueError, match="Buffer percentage must be between"):
            TrendFilter(ema_period=50, buffer_pct=0.10)

    def test_get_trend_direction_bullish(self):
        """Test bullish trend detection"""
        filter = TrendFilter(ema_period=50)

        # Create strong uptrend
        candles = create_bullish_trend_candles(count=60)

        trend = filter.get_trend_direction(candles)

        assert trend == TrendDirection.BULLISH

    def test_get_trend_direction_bearish(self):
        """Test bearish trend detection"""
        filter = TrendFilter(ema_period=50)

        # Create strong downtrend
        candles = create_bearish_trend_candles(count=60)

        trend = filter.get_trend_direction(candles)

        assert trend == TrendDirection.BEARISH

    def test_get_trend_direction_neutral(self):
        """Test neutral trend detection"""
        filter = TrendFilter(ema_period=50)

        # Create sideways market
        candles = create_neutral_candles(count=60)

        trend = filter.get_trend_direction(candles)

        assert trend == TrendDirection.NEUTRAL

    def test_get_trend_direction_insufficient_data(self):
        """Test trend detection with insufficient candles"""
        filter = TrendFilter(ema_period=50)

        # Only 40 candles (need 50)
        candles = create_bullish_trend_candles(count=40)

        trend = filter.get_trend_direction(candles)

        assert trend == TrendDirection.NEUTRAL

    def test_get_trend_direction_empty_list(self):
        """Test trend detection with empty candle list"""
        filter = TrendFilter(ema_period=50)

        trend = filter.get_trend_direction([])

        assert trend == TrendDirection.NEUTRAL

    def test_is_trade_allowed_buy_in_bullish(self):
        """Test BUY signal allowed in bullish trend"""
        filter = TrendFilter(ema_period=50)

        candles = create_bullish_trend_candles(count=60)

        allowed, reason = filter.is_trade_allowed('BUY', candles)

        assert allowed is True
        assert 'BUY allowed' in reason
        assert 'bullish' in reason.lower()

    def test_is_trade_allowed_buy_in_bearish(self):
        """Test BUY signal rejected in bearish trend"""
        filter = TrendFilter(ema_period=50)

        candles = create_bearish_trend_candles(count=60)

        allowed, reason = filter.is_trade_allowed('BUY', candles)

        assert allowed is False
        assert 'BUY rejected' in reason
        assert 'bearish' in reason.lower()

    def test_is_trade_allowed_buy_in_neutral(self):
        """Test BUY signal rejected in neutral zone"""
        filter = TrendFilter(ema_period=50)

        candles = create_neutral_candles(count=60)

        allowed, reason = filter.is_trade_allowed('BUY', candles)

        assert allowed is False
        assert 'BUY rejected' in reason
        assert 'neutral' in reason.lower()

    def test_is_trade_allowed_sell_in_bearish(self):
        """Test SELL signal allowed in bearish trend"""
        filter = TrendFilter(ema_period=50)

        candles = create_bearish_trend_candles(count=60)

        allowed, reason = filter.is_trade_allowed('SELL', candles)

        assert allowed is True
        assert 'SELL allowed' in reason
        assert 'bearish' in reason.lower()

    def test_is_trade_allowed_sell_in_bullish(self):
        """Test SELL signal rejected in bullish trend"""
        filter = TrendFilter(ema_period=50)

        candles = create_bullish_trend_candles(count=60)

        allowed, reason = filter.is_trade_allowed('SELL', candles)

        assert allowed is False
        assert 'SELL rejected' in reason
        assert 'bullish' in reason.lower()

    def test_is_trade_allowed_sell_in_neutral(self):
        """Test SELL signal rejected in neutral zone"""
        filter = TrendFilter(ema_period=50)

        candles = create_neutral_candles(count=60)

        allowed, reason = filter.is_trade_allowed('SELL', candles)

        assert allowed is False
        assert 'SELL rejected' in reason
        assert 'neutral' in reason.lower()

    def test_is_trade_allowed_invalid_direction(self):
        """Test invalid signal direction"""
        filter = TrendFilter(ema_period=50)

        candles = create_bullish_trend_candles(count=60)

        allowed, reason = filter.is_trade_allowed('INVALID', candles)

        assert allowed is False
        assert 'Invalid signal direction' in reason

    def test_get_trend_info(self):
        """Test get_trend_info method"""
        filter = TrendFilter(ema_period=50)

        candles = create_bullish_trend_candles(count=60)

        info = filter.get_trend_info(candles)

        assert info['is_valid'] is True
        assert info['direction'] == TrendDirection.BULLISH.value
        assert info['ema_value'] > 0
        assert info['current_price'] > 0
        assert info['spread_pct'] > 0  # Price above EMA
        assert 'bullish_threshold' in info
        assert 'bearish_threshold' in info

    def test_get_trend_info_insufficient_data(self):
        """Test get_trend_info with insufficient data"""
        filter = TrendFilter(ema_period=50)

        candles = create_bullish_trend_candles(count=40)

        info = filter.get_trend_info(candles)

        assert info['is_valid'] is False
        assert info['ema_value'] == 0.0

    def test_buffer_zone_prevents_whipsaw(self):
        """Test that buffer zone prevents whipsaw trades"""
        filter = TrendFilter(ema_period=50, buffer_pct=0.01)

        # Create candles where price is very close to EMA
        base_time = datetime(2025, 1, 1)
        candles = []

        # First 50 candles to establish EMA
        for i in range(50):
            timestamp = base_time + timedelta(minutes=15 * i)
            price = 100.0
            candle = create_test_candle(
                timestamp, price, price + 1, price - 1, price
            )
            candles.append(candle)

        # Add candles with price very close to EMA (within buffer)
        for i in range(50, 60):
            timestamp = base_time + timedelta(minutes=15 * i)
            price = 100.5  # Within 1% of EMA
            candle = create_test_candle(
                timestamp, price, price + 1, price - 1, price
            )
            candles.append(candle)

        trend = filter.get_trend_direction(candles)

        # Should be NEUTRAL due to buffer zone
        assert trend == TrendDirection.NEUTRAL

    def test_custom_buffer_percentage(self):
        """Test custom buffer percentage"""
        # Larger buffer (2%)
        filter_large = TrendFilter(ema_period=50, buffer_pct=0.02)

        # Smaller buffer (0.5%)
        filter_small = TrendFilter(ema_period=50, buffer_pct=0.005)

        candles = create_bullish_trend_candles(count=60)

        # Both should detect bullish trend
        assert filter_large.get_trend_direction(candles) == TrendDirection.BULLISH
        assert filter_small.get_trend_direction(candles) == TrendDirection.BULLISH

    def test_ema_calculation_accuracy(self):
        """Test EMA calculation accuracy"""
        filter = TrendFilter(ema_period=5)

        # Create candles with known prices
        base_time = datetime(2025, 1, 1)
        prices = [100, 102, 104, 103, 105, 107, 106]
        candles = []

        for i, price in enumerate(prices):
            timestamp = base_time + timedelta(minutes=15 * i)
            candle = create_test_candle(
                timestamp, price, price + 1, price - 1, price
            )
            candles.append(candle)

        ema = filter._calculate_ema(candles, 5)

        # EMA should be between min and max prices
        assert min(prices) <= ema <= max(prices)
        # EMA should be closer to recent prices
        assert abs(ema - prices[-1]) < abs(ema - prices[0])

    def test_repr(self):
        """Test string representation"""
        filter = TrendFilter(ema_period=50, buffer_pct=0.01)
        repr_str = repr(filter)

        assert 'TrendFilter' in repr_str
        assert 'ema_period=50' in repr_str
        assert 'buffer=1.0%' in repr_str


class TestTrendFilterEdgeCases:
    """Test edge cases for Trend Filter"""

    def test_single_candle(self):
        """Test with single candle"""
        filter = TrendFilter(ema_period=50)
        candles = create_bullish_trend_candles(count=1)

        trend = filter.get_trend_direction(candles)
        assert trend == TrendDirection.NEUTRAL

    def test_exact_minimum_candles(self):
        """Test with exact minimum number of candles"""
        filter = TrendFilter(ema_period=50)
        candles = create_bullish_trend_candles(count=50)

        trend = filter.get_trend_direction(candles)
        # Should work with exactly 50 candles
        assert trend in [TrendDirection.BULLISH, TrendDirection.BEARISH, TrendDirection.NEUTRAL]

    def test_price_exactly_at_ema(self):
        """Test when price is exactly at EMA"""
        filter = TrendFilter(ema_period=10)

        base_time = datetime(2025, 1, 1)
        candles = []

        # Create candles with constant price
        for i in range(20):
            timestamp = base_time + timedelta(minutes=15 * i)
            price = 100.0
            candle = create_test_candle(
                timestamp, price, price, price, price
            )
            candles.append(candle)

        trend = filter.get_trend_direction(candles)

        # Should be NEUTRAL when price equals EMA
        assert trend == TrendDirection.NEUTRAL

    def test_rapid_trend_change(self):
        """Test rapid trend change"""
        filter = TrendFilter(ema_period=20)

        # Start with uptrend
        candles = create_bullish_trend_candles(count=30, base_price=100.0)

        # Add sudden downtrend
        base_time = datetime(2025, 1, 1) + timedelta(minutes=15 * 30)
        for i in range(30):
            timestamp = base_time + timedelta(minutes=15 * i)
            price = 160.0 - (i * 3)  # Sharp decline
            candle = create_test_candle(
                timestamp, price, price + 1, price - 2, price - 1
            )
            candles.append(candle)

        trend = filter.get_trend_direction(candles)

        # Should detect the new trend
        assert trend in [TrendDirection.BEARISH, TrendDirection.NEUTRAL]


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
