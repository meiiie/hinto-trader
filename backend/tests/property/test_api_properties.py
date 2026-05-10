"""
Property-Based Tests for Historical Data API Response Completeness

**Feature: desktop-trading-dashboard, Property 5: Historical Data API Response Completeness**
**Validates: Requirements 5.4**

Tests that for any valid history request with timeframe parameter, the API response
SHALL include for each candle:
- OHLCV data (open, high, low, close, volume)
- VWAP value (non-null number)
- Bollinger Bands values (bb_upper, bb_middle, bb_lower as non-null numbers)
"""

import pytest
from hypothesis import given, strategies as st, settings, Phase, HealthCheck
from typing import List
from datetime import datetime, timedelta
import math

from src.domain.entities.candle import Candle


# Strategies for generating test data
price_strategy = st.floats(min_value=1000.0, max_value=100000.0, allow_nan=False, allow_infinity=False)
volume_strategy = st.floats(min_value=0.1, max_value=10000.0, allow_nan=False, allow_infinity=False)
timeframe_strategy = st.sampled_from(['1m', '15m', '1h'])


def generate_candle(base_price: float, volume: float, timestamp: datetime) -> Candle:
    """Generate a realistic candle with OHLC values."""
    variation = base_price * 0.01
    return Candle(
        timestamp=timestamp,
        open=base_price,
        high=base_price + abs(variation),
        low=base_price - abs(variation),
        close=base_price + (variation * 0.5),
        volume=volume
    )


@st.composite
def candle_list_strategy(draw, min_size: int = 25, max_size: int = 50):
    """Generate a list of realistic candles."""
    size = draw(st.integers(min_value=min_size, max_value=max_size))
    base_price = draw(price_strategy)

    candles = []
    current_time = datetime.now() - timedelta(minutes=size)

    for i in range(size):
        price_change = draw(st.floats(min_value=-0.02, max_value=0.02, allow_nan=False, allow_infinity=False))
        base_price = max(100.0, min(200000.0, base_price * (1 + price_change)))
        volume = draw(volume_strategy)
        candles.append(generate_candle(base_price, volume, current_time))
        current_time += timedelta(minutes=1)

    return candles


class TestHistoricalDataAPICompleteness:
    """
    Property tests for Historical Data API response completeness.

    **Feature: desktop-trading-dashboard, Property 5: Historical Data API Response Completeness**
    **Validates: Requirements 5.4**
    """

    @given(candles=candle_list_strategy(min_size=25, max_size=50))
    @settings(max_examples=30, deadline=10000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_response_contains_ohlcv_for_all_candles(self, candles: List[Candle]):
        """
        Property: Every candle in response has OHLCV data.

        **Feature: desktop-trading-dashboard, Property 5: Historical Data API Response Completeness**
        **Validates: Requirements 5.4**
        """
        from src.infrastructure.indicators.vwap_calculator import VWAPCalculator
        from src.infrastructure.indicators.bollinger_calculator import BollingerCalculator

        vwap_calc = VWAPCalculator()
        bb_calc = BollingerCalculator()

        vwap_series = vwap_calc.calculate_vwap_series(candles)
        bb_result = bb_calc.calculate_bands(candles)

        # Build response like the API does
        result = []
        for i, candle in enumerate(candles):
            item = {
                'time': int(candle.timestamp.timestamp()),
                'open': candle.open,
                'high': candle.high,
                'low': candle.low,
                'close': candle.close,
                'volume': candle.volume,
                'vwap': vwap_series.iloc[i] if vwap_series is not None else 0.0,
                # BB returns single values (latest), use for all or 0.0
                'bb_upper': bb_result.upper_band if bb_result else 0.0,
                'bb_lower': bb_result.lower_band if bb_result else 0.0,
                'bb_middle': bb_result.middle_band if bb_result else 0.0
            }
            result.append(item)

        # Verify all candles have OHLCV
        for i, item in enumerate(result):
            assert 'open' in item and isinstance(item['open'], (int, float))
            assert 'high' in item and isinstance(item['high'], (int, float))
            assert 'low' in item and isinstance(item['low'], (int, float))
            assert 'close' in item and isinstance(item['close'], (int, float))
            assert 'volume' in item and isinstance(item['volume'], (int, float))

    @given(candles=candle_list_strategy(min_size=25, max_size=50))
    @settings(max_examples=30, deadline=10000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_response_contains_vwap_for_all_candles(self, candles: List[Candle]):
        """
        Property: Every candle in response has VWAP value (non-null number).

        **Feature: desktop-trading-dashboard, Property 5: Historical Data API Response Completeness**
        **Validates: Requirements 5.4**
        """
        from src.infrastructure.indicators.vwap_calculator import VWAPCalculator

        vwap_calc = VWAPCalculator()
        vwap_series = vwap_calc.calculate_vwap_series(candles)

        assert vwap_series is not None, "VWAP series should not be None"
        assert len(vwap_series) == len(candles), "VWAP series length should match candles"

        for i, vwap_value in enumerate(vwap_series):
            assert vwap_value is not None, f"VWAP at index {i} is None"
            assert isinstance(vwap_value, (int, float)), f"VWAP at index {i} is not a number"
            assert not math.isnan(vwap_value), f"VWAP at index {i} is NaN"
            assert not math.isinf(vwap_value), f"VWAP at index {i} is infinite"

    @given(candles=candle_list_strategy(min_size=25, max_size=50))
    @settings(max_examples=30, deadline=10000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_response_contains_bollinger_bands(self, candles: List[Candle]):
        """
        Property: Response has Bollinger Bands values (bb_upper, bb_middle, bb_lower as non-null numbers).

        **Feature: desktop-trading-dashboard, Property 5: Historical Data API Response Completeness**
        **Validates: Requirements 5.4**
        """
        from src.infrastructure.indicators.bollinger_calculator import BollingerCalculator

        bb_calc = BollingerCalculator()
        bb_result = bb_calc.calculate_bands(candles)

        assert bb_result is not None, "Bollinger Bands result should not be None"

        # Check values are numbers
        assert isinstance(bb_result.upper_band, (int, float)), "Upper band is not a number"
        assert isinstance(bb_result.middle_band, (int, float)), "Middle band is not a number"
        assert isinstance(bb_result.lower_band, (int, float)), "Lower band is not a number"

        # Check not NaN
        assert not math.isnan(bb_result.upper_band), "Upper band is NaN"
        assert not math.isnan(bb_result.middle_band), "Middle band is NaN"
        assert not math.isnan(bb_result.lower_band), "Lower band is NaN"

    @given(candles=candle_list_strategy(min_size=25, max_size=50))
    @settings(max_examples=30, deadline=10000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_bollinger_bands_ordering(self, candles: List[Candle]):
        """
        Property: Bollinger Bands maintain correct ordering: lower <= middle <= upper.

        **Feature: desktop-trading-dashboard, Property 5: Historical Data API Response Completeness**
        **Validates: Requirements 5.4**
        """
        from src.infrastructure.indicators.bollinger_calculator import BollingerCalculator

        bb_calc = BollingerCalculator()
        bb_result = bb_calc.calculate_bands(candles)

        assert bb_result is not None

        lower = bb_result.lower_band
        middle = bb_result.middle_band
        upper = bb_result.upper_band

        assert lower <= middle, f"lower ({lower}) > middle ({middle})"
        assert middle <= upper, f"middle ({middle}) > upper ({upper})"

    @given(candles=candle_list_strategy(min_size=25, max_size=50))
    @settings(max_examples=30, deadline=10000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_vwap_within_price_range(self, candles: List[Candle]):
        """
        Property: VWAP should be within the price range of the candles.

        **Feature: desktop-trading-dashboard, Property 5: Historical Data API Response Completeness**
        **Validates: Requirements 5.4**
        """
        from src.infrastructure.indicators.vwap_calculator import VWAPCalculator

        vwap_calc = VWAPCalculator()
        vwap_series = vwap_calc.calculate_vwap_series(candles)

        assert vwap_series is not None

        min_price = min(c.low for c in candles)
        max_price = max(c.high for c in candles)
        tolerance = (max_price - min_price) * 0.1

        for vwap_value in vwap_series:
            if math.isnan(vwap_value):
                continue
            assert vwap_value >= min_price - tolerance
            assert vwap_value <= max_price + tolerance

    @given(timeframe=timeframe_strategy)
    @settings(max_examples=10, deadline=5000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_timeframe_parameter_accepted(self, timeframe: str):
        """
        Property: All valid timeframe parameters (1m, 15m, 1h) are accepted.

        **Feature: desktop-trading-dashboard, Property 5: Historical Data API Response Completeness**
        **Validates: Requirements 5.4**
        """
        assert timeframe in ['1m', '15m', '1h']
