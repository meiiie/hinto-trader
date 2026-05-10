"""
Unit tests for DataAggregator
"""

import pytest
from datetime import datetime, timedelta
from src.domain.entities.candle import Candle
from src.infrastructure.aggregation import DataAggregator


def create_test_candle(timestamp: datetime, open_price: float, close_price: float) -> Candle:
    """Helper to create test candles"""
    return Candle(
        timestamp=timestamp,
        open=open_price,
        high=max(open_price, close_price) + 10,
        low=min(open_price, close_price) - 10,
        close=close_price,
        volume=1.5
    )


def test_aggregator_initialization():
    """Test aggregator initializes correctly"""
    aggregator = DataAggregator()

    assert aggregator.get_current_15m() is None
    assert aggregator.get_current_1h() is None

    status = aggregator.get_buffer_status()
    assert status['1m_total'] == 0
    assert status['15m_pending'] == 0
    assert status['1h_pending'] == 0


def test_add_single_candle():
    """Test adding a single 1m candle"""
    aggregator = DataAggregator()

    candle = create_test_candle(
        datetime(2025, 11, 18, 17, 0),
        91000.0,
        91100.0
    )

    aggregator.add_candle_1m(candle, is_closed=True)

    status = aggregator.get_buffer_status()
    assert status['1m_total'] == 1
    assert status['15m_pending'] == 1


def test_15m_aggregation():
    """Test 15-minute candle aggregation"""
    aggregator = DataAggregator()
    completed_candles = []

    # Register callback
    aggregator.on_15m_complete(lambda c: completed_candles.append(c))

    # Create 15 candles (17:00 to 17:14)
    base_time = datetime(2025, 11, 18, 17, 0)

    for i in range(15):
        timestamp = base_time + timedelta(minutes=i)
        candle = create_test_candle(
            timestamp,
            91000.0 + i * 10,
            91000.0 + i * 10 + 50
        )
        aggregator.add_candle_1m(candle, is_closed=True)

    # Should have completed one 15m candle
    assert len(completed_candles) == 1

    candle_15m = completed_candles[0]
    assert candle_15m.timestamp == base_time
    assert candle_15m.open == 91000.0  # First candle's open
    assert candle_15m.close == 91000.0 + 14 * 10 + 50  # Last candle's close
    assert candle_15m.volume == 1.5 * 15  # Sum of volumes


def test_1h_aggregation():
    """Test 1-hour candle aggregation"""
    aggregator = DataAggregator()
    completed_candles = []

    # Register callback
    aggregator.on_1h_complete(lambda c: completed_candles.append(c))

    # Create 60 candles (17:00 to 17:59)
    base_time = datetime(2025, 11, 18, 17, 0)

    for i in range(60):
        timestamp = base_time + timedelta(minutes=i)
        candle = create_test_candle(
            timestamp,
            91000.0 + i * 5,
            91000.0 + i * 5 + 20
        )
        aggregator.add_candle_1m(candle, is_closed=True)

    # Should have completed one 1h candle
    assert len(completed_candles) == 1

    candle_1h = completed_candles[0]
    assert candle_1h.timestamp == base_time
    assert candle_1h.open == 91000.0  # First candle's open
    assert candle_1h.close == 91000.0 + 59 * 5 + 20  # Last candle's close
    assert candle_1h.volume == 1.5 * 60  # Sum of volumes


def test_ohlcv_aggregation_logic():
    """Test OHLCV aggregation calculations"""
    aggregator = DataAggregator()
    completed_candles = []

    aggregator.on_15m_complete(lambda c: completed_candles.append(c))

    base_time = datetime(2025, 11, 18, 17, 0)

    # Create candles with specific OHLCV values
    test_data = [
        # (timestamp, open, high, low, close, volume)
        (0, 100, 110, 95, 105, 1.0),
        (1, 105, 115, 100, 110, 2.0),
        (2, 110, 120, 105, 115, 1.5),
    ]

    for i in range(15):
        if i < len(test_data):
            _, o, h, l, c, v = test_data[i]
        else:
            o, h, l, c, v = 115, 120, 110, 115, 1.0

        timestamp = base_time + timedelta(minutes=i)
        candle = Candle(
            timestamp=timestamp,
            open=o,
            high=h,
            low=l,
            close=c,
            volume=v
        )
        aggregator.add_candle_1m(candle, is_closed=True)

    assert len(completed_candles) == 1

    candle_15m = completed_candles[0]
    assert candle_15m.open == 100  # First open
    assert candle_15m.high == 120  # Max high
    assert candle_15m.low == 95    # Min low
    assert candle_15m.close == 115 # Last close
    assert candle_15m.volume == pytest.approx(16.5)  # Sum


def test_buffer_management():
    """Test buffer size limits"""
    aggregator = DataAggregator(buffer_size=10)

    base_time = datetime(2025, 11, 18, 17, 0)

    # Add 20 candles (more than buffer size)
    for i in range(20):
        timestamp = base_time + timedelta(minutes=i)
        candle = create_test_candle(timestamp, 91000.0, 91100.0)
        aggregator.add_candle_1m(candle, is_closed=True)

    # Buffer should only keep last 10
    status = aggregator.get_buffer_status()
    assert status['1m_total'] == 10


def test_get_latest_candles():
    """Test retrieving latest 1m candles"""
    aggregator = DataAggregator()

    base_time = datetime(2025, 11, 18, 17, 0)

    for i in range(5):
        timestamp = base_time + timedelta(minutes=i)
        candle = create_test_candle(timestamp, 91000.0 + i, 91100.0 + i)
        aggregator.add_candle_1m(candle, is_closed=True)

    latest = aggregator.get_latest_1m_candles(count=3)
    assert len(latest) == 3
    assert latest[-1].open == 91004.0  # Most recent


def test_clear_buffers():
    """Test clearing all buffers"""
    aggregator = DataAggregator()

    base_time = datetime(2025, 11, 18, 17, 0)

    for i in range(5):
        timestamp = base_time + timedelta(minutes=i)
        candle = create_test_candle(timestamp, 91000.0, 91100.0)
        aggregator.add_candle_1m(candle, is_closed=True)

    aggregator.clear_buffers()

    status = aggregator.get_buffer_status()
    assert status['1m_total'] == 0
    assert status['15m_pending'] == 0
    assert status['1h_pending'] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
