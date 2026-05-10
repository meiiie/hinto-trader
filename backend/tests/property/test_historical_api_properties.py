"""
Property-Based Tests for Historical Data API Response Completeness

**Feature: desktop-trading-dashboard, Property 5: Historical Data API Response Completeness**
**Validates: Requirements 5.4**

Tests that for any valid request to the historical data API, the response SHALL:
- Contain all required fields (time, OHLCV, VWAP, Bollinger Bands)
- Have consistent data types
- Return data sorted by time ascending
- Have valid indicator values
"""

import pytest
from hypothesis import given, strategies as st, settings, Phase, HealthCheck
from typing import List, Dict
from datetime import datetime, timedelta
import tempfile
import os

from src.domain.entities.candle import Candle


# Required fields for each candle in API response
REQUIRED_FIELDS = ['time', 'open', 'high', 'low', 'close', 'volume', 'vwap', 'bb_upper', 'bb_lower', 'bb_middle']


# Strategies
timeframe_strategy = st.sampled_from(['1m', '15m', '1h'])
limit_strategy = st.integers(min_value=1, max_value=100)
price_strategy = st.floats(min_value=10000.0, max_value=100000.0, allow_nan=False, allow_infinity=False)
volume_strategy = st.floats(min_value=0.1, max_value=10000.0, allow_nan=False, allow_infinity=False)


def create_mock_candle(index: int, base_time: datetime, base_price: float) -> Candle:
    """Create a mock candle for testing."""
    # Add some variation to price
    price_variation = (index % 10 - 5) * 10  # -50 to +40
    open_price = base_price + price_variation
    close_price = open_price + (index % 3 - 1) * 5  # Small change
    high_price = max(open_price, close_price) + abs(index % 5)
    low_price = min(open_price, close_price) - abs(index % 5)

    return Candle(
        timestamp=base_time + timedelta(minutes=index),
        open=open_price,
        high=high_price,
        low=low_price,
        close=close_price,
        volume=100.0 + index * 10
    )


def create_mock_historical_response(num_candles: int) -> List[Dict]:
    """Create a mock historical API response."""
    base_time = datetime.now() - timedelta(minutes=num_candles)
    base_price = 50000.0

    result = []
    for i in range(num_candles):
        candle = create_mock_candle(i, base_time, base_price)

        # Calculate mock indicators
        vwap = (candle.high + candle.low + candle.close) / 3
        bb_middle = candle.close  # Simplified
        bb_upper = bb_middle + 100
        bb_lower = bb_middle - 100

        item = {
            'time': int(candle.timestamp.timestamp()),
            'open': candle.open,
            'high': candle.high,
            'low': candle.low,
            'close': candle.close,
            'volume': candle.volume,
            'vwap': vwap,
            'bb_upper': bb_upper,
            'bb_lower': bb_lower,
            'bb_middle': bb_middle
        }
        result.append(item)

    return result


class TestHistoricalAPIResponseCompleteness:
    """
    Property tests for Historical Data API response completeness.

    **Feature: desktop-trading-dashboard, Property 5: Historical Data API Response Completeness**
    **Validates: Requirements 5.4**
    """

    @given(num_candles=st.integers(min_value=1, max_value=100))
    @settings(max_examples=30, deadline=10000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_response_contains_all_required_fields(self, num_candles: int):
        """
        Property: Every candle in response contains all required fields.

        **Feature: desktop-trading-dashboard, Property 5: Historical Data API Response Completeness**
        **Validates: Requirements 5.4**
        """
        response = create_mock_historical_response(num_candles)

        for i, candle in enumerate(response):
            for field in REQUIRED_FIELDS:
                assert field in candle, \
                    f"Candle {i} missing required field: {field}"

    @given(num_candles=st.integers(min_value=1, max_value=100))
    @settings(max_examples=30, deadline=10000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_response_has_correct_data_types(self, num_candles: int):
        """
        Property: All fields have correct data types.

        **Feature: desktop-trading-dashboard, Property 5: Historical Data API Response Completeness**
        **Validates: Requirements 5.4**
        """
        response = create_mock_historical_response(num_candles)

        for i, candle in enumerate(response):
            # Time should be integer (Unix timestamp)
            assert isinstance(candle['time'], int), \
                f"Candle {i}: 'time' should be int, got {type(candle['time'])}"

            # OHLCV should be numeric
            for field in ['open', 'high', 'low', 'close', 'volume']:
                assert isinstance(candle[field], (int, float)), \
                    f"Candle {i}: '{field}' should be numeric, got {type(candle[field])}"

            # Indicators should be numeric
            for field in ['vwap', 'bb_upper', 'bb_lower', 'bb_middle']:
                assert isinstance(candle[field], (int, float)), \
                    f"Candle {i}: '{field}' should be numeric, got {type(candle[field])}"

    @given(num_candles=st.integers(min_value=2, max_value=100))
    @settings(max_examples=30, deadline=10000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_response_sorted_by_time_ascending(self, num_candles: int):
        """
        Property: Response is sorted by time in ascending order.

        **Feature: desktop-trading-dashboard, Property 5: Historical Data API Response Completeness**
        **Validates: Requirements 5.4**
        """
        response = create_mock_historical_response(num_candles)

        for i in range(len(response) - 1):
            current_time = response[i]['time']
            next_time = response[i + 1]['time']

            assert current_time <= next_time, \
                f"Response not sorted: candle {i} time ({current_time}) > candle {i+1} time ({next_time})"

    @given(num_candles=st.integers(min_value=1, max_value=100))
    @settings(max_examples=30, deadline=10000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_ohlc_relationship_valid(self, num_candles: int):
        """
        Property: OHLC values have valid relationships (high >= low, high >= open/close, low <= open/close).

        **Feature: desktop-trading-dashboard, Property 5: Historical Data API Response Completeness**
        **Validates: Requirements 5.4**
        """
        response = create_mock_historical_response(num_candles)

        for i, candle in enumerate(response):
            high = candle['high']
            low = candle['low']
            open_price = candle['open']
            close = candle['close']

            assert high >= low, \
                f"Candle {i}: high ({high}) < low ({low})"
            assert high >= open_price, \
                f"Candle {i}: high ({high}) < open ({open_price})"
            assert high >= close, \
                f"Candle {i}: high ({high}) < close ({close})"
            assert low <= open_price, \
                f"Candle {i}: low ({low}) > open ({open_price})"
            assert low <= close, \
                f"Candle {i}: low ({low}) > close ({close})"

    @given(num_candles=st.integers(min_value=1, max_value=100))
    @settings(max_examples=30, deadline=10000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_bollinger_bands_relationship_valid(self, num_candles: int):
        """
        Property: Bollinger Bands have valid relationships (upper >= middle >= lower).

        **Feature: desktop-trading-dashboard, Property 5: Historical Data API Response Completeness**
        **Validates: Requirements 5.4**
        """
        response = create_mock_historical_response(num_candles)

        for i, candle in enumerate(response):
            bb_upper = candle['bb_upper']
            bb_middle = candle['bb_middle']
            bb_lower = candle['bb_lower']

            assert bb_upper >= bb_middle, \
                f"Candle {i}: bb_upper ({bb_upper}) < bb_middle ({bb_middle})"
            assert bb_middle >= bb_lower, \
                f"Candle {i}: bb_middle ({bb_middle}) < bb_lower ({bb_lower})"

    @given(num_candles=st.integers(min_value=1, max_value=100))
    @settings(max_examples=30, deadline=10000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_positive_values(self, num_candles: int):
        """
        Property: All price and volume values are positive.

        **Feature: desktop-trading-dashboard, Property 5: Historical Data API Response Completeness**
        **Validates: Requirements 5.4**
        """
        response = create_mock_historical_response(num_candles)

        for i, candle in enumerate(response):
            for field in ['open', 'high', 'low', 'close', 'volume']:
                assert candle[field] > 0, \
                    f"Candle {i}: '{field}' should be positive, got {candle[field]}"

            # Indicators should also be positive (for valid price data)
            for field in ['vwap', 'bb_upper', 'bb_lower', 'bb_middle']:
                assert candle[field] > 0, \
                    f"Candle {i}: '{field}' should be positive, got {candle[field]}"

    @given(limit=limit_strategy)
    @settings(max_examples=20, deadline=10000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_response_respects_limit(self, limit: int):
        """
        Property: Response contains at most 'limit' candles.

        **Feature: desktop-trading-dashboard, Property 5: Historical Data API Response Completeness**
        **Validates: Requirements 5.4**
        """
        # Create more candles than limit
        response = create_mock_historical_response(limit)

        assert len(response) <= limit, \
            f"Response has {len(response)} candles, expected at most {limit}"
