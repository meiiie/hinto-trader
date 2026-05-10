"""
Unit Tests for Real-Time Data Manager

Tests candle buffering logic and HTF bias calculation.
"""

import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from collections import deque
from unittest.mock import Mock, AsyncMock, patch

from src.domain.entities.candle import Candle
from src.application.analysis.trend_filter import TrendFilter

realtime_data_manager_module = pytest.importorskip(
    "src.application.backtest_live.core.realtime_data_manager",
    reason="legacy backtest_live realtime data manager module is not available in this codebase",
)
RealTimeDataManager = realtime_data_manager_module.RealTimeDataManager


@pytest.fixture
def mock_websocket_client():
    """Mock WebSocket client"""
    client = Mock()
    client.register_handler = Mock()
    client.connect = AsyncMock()
    return client


@pytest.fixture
def mock_data_loader():
    """Mock data loader"""
    loader = Mock()
    loader.load_candles = AsyncMock()
    return loader


@pytest.fixture
def mock_trend_filter():
    """Mock trend filter"""
    filter = Mock(spec=TrendFilter)
    filter.calculate_bias = Mock(return_value='BULLISH')
    return filter


@pytest.fixture
def sample_candles():
    """Generate sample candles"""
    now = datetime.now(timezone.utc)
    candles = []

    for i in range(250):
        candles.append(Candle(
            timestamp=now - timedelta(hours=4 * (250 - i)),
            open=100.0 + i * 0.1,
            high=101.0 + i * 0.1,
            low=99.0 + i * 0.1,
            close=100.5 + i * 0.1,
            volume=1000.0
        ))

    return candles


class TestRealTimeDataManager:
    """Test suite for RealTimeDataManager"""

    @pytest.mark.asyncio
    async def test_initialization(self, mock_websocket_client, mock_data_loader, mock_trend_filter):
        """Test manager initialization"""
        symbols = ['btcusdt', 'ethusdt']

        manager = RealTimeDataManager(
            symbols=symbols,
            websocket_client=mock_websocket_client,
            data_loader=mock_data_loader,
            trend_filter=mock_trend_filter
        )

        assert manager.symbols == ['btcusdt', 'ethusdt']
        assert len(manager.candles_15m) == 0
        assert len(manager.candles_4h) == 0
        assert manager._is_running is False

    @pytest.mark.asyncio
    async def test_buffer_sizes(self):
        """Test buffer sizes are optimized"""
        assert RealTimeDataManager.BUFFER_SIZES['1m'] == 100
        assert RealTimeDataManager.BUFFER_SIZES['15m'] == 150
        assert RealTimeDataManager.BUFFER_SIZES['4h'] == 250

    @pytest.mark.asyncio
    async def test_load_historical_data(
        self,
        mock_websocket_client,
        mock_data_loader,
        mock_trend_filter,
        sample_candles
    ):
        """Test historical data loading"""
        symbols = ['btcusdt']

        # Mock data loader to return sample candles
        mock_data_loader.load_candles = AsyncMock(return_value=sample_candles[:150])

        manager = RealTimeDataManager(
            symbols=symbols,
            websocket_client=mock_websocket_client,
            data_loader=mock_data_loader,
            trend_filter=mock_trend_filter
        )

        await manager._load_historical_data()

        # Verify buffers initialized
        assert 'btcusdt' in manager.candles_15m
        assert 'btcusdt' in manager.candles_4h

        # Verify data loaded
        assert len(manager.candles_15m['btcusdt']) == 150
        assert len(manager.candles_4h['btcusdt']) == 150

        # Verify data loader called correctly
        assert mock_data_loader.load_candles.call_count == 2  # 15m + 4h

    @pytest.mark.asyncio
    async def test_htf_bias_calculation(
        self,
        mock_websocket_client,
        mock_data_loader,
        mock_trend_filter,
        sample_candles
    ):
        """Test HTF bias calculation using TrendFilter"""
        symbols = ['btcusdt']

        # Mock data loader
        mock_data_loader.load_candles = AsyncMock(return_value=sample_candles)

        # Mock trend filter to return BULLISH
        mock_trend_filter.calculate_bias = Mock(return_value='BULLISH')

        manager = RealTimeDataManager(
            symbols=symbols,
            websocket_client=mock_websocket_client,
            data_loader=mock_data_loader,
            trend_filter=mock_trend_filter
        )

        await manager._load_historical_data()
        manager._calculate_initial_htf_bias()

        # Verify HTF bias calculated
        assert manager.htf_bias['btcusdt'] == 'BULLISH'

        # Verify TrendFilter called with 4h candles
        mock_trend_filter.calculate_bias.assert_called_once()
        call_args = mock_trend_filter.calculate_bias.call_args[0][0]
        assert len(call_args) == 250  # 4h candles

    @pytest.mark.asyncio
    async def test_htf_bias_insufficient_data(
        self,
        mock_websocket_client,
        mock_data_loader,
        mock_trend_filter
    ):
        """Test HTF bias defaults to NEUTRAL with insufficient data"""
        symbols = ['btcusdt']

        # Mock data loader to return only 100 candles (< 200 required)
        now = datetime.now(timezone.utc)
        insufficient_candles = [
            Candle(
                timestamp=now - timedelta(hours=4 * (100 - i)),
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                volume=1000.0
            )
            for i in range(100)
        ]

        mock_data_loader.load_candles = AsyncMock(return_value=insufficient_candles)

        manager = RealTimeDataManager(
            symbols=symbols,
            websocket_client=mock_websocket_client,
            data_loader=mock_data_loader,
            trend_filter=mock_trend_filter
        )

        await manager._load_historical_data()
        manager._calculate_initial_htf_bias()

        # Verify HTF bias defaults to NEUTRAL
        assert manager.htf_bias['btcusdt'] == 'NEUTRAL'

        # Verify TrendFilter NOT called
        mock_trend_filter.calculate_bias.assert_not_called()

    @pytest.mark.asyncio
    async def test_websocket_candle_closed_only(
        self,
        mock_websocket_client,
        mock_data_loader,
        mock_trend_filter
    ):
        """Test that only CLOSED candles are processed"""
        symbols = ['btcusdt']

        manager = RealTimeDataManager(
            symbols=symbols,
            websocket_client=mock_websocket_client,
            data_loader=mock_data_loader,
            trend_filter=mock_trend_filter
        )

        # Initialize buffers
        manager.candles_15m['btcusdt'] = deque(maxlen=150)
        manager.htf_bias['btcusdt'] = 'BULLISH'

        # Mock callback
        callback_called = False

        async def mock_callback(symbol, timeframe, candle, htf_bias):
            nonlocal callback_called
            callback_called = True

        manager.on_candle_close = mock_callback

        # Test 1: Open candle (should NOT process)
        open_candle = Candle(
            timestamp=datetime.now(timezone.utc),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=1000.0
        )

        await manager._on_websocket_candle(
            open_candle,
            {'symbol': 'btcusdt', 'interval': '15m', 'is_closed': False}
        )

        assert callback_called is False
        assert len(manager.candles_15m['btcusdt']) == 0

        # Test 2: Closed candle (should process)
        closed_candle = Candle(
            timestamp=datetime.now(timezone.utc),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=1000.0
        )

        await manager._on_websocket_candle(
            closed_candle,
            {'symbol': 'btcusdt', 'interval': '15m', 'is_closed': True}
        )

        assert callback_called is True
        assert len(manager.candles_15m['btcusdt']) == 1

    @pytest.mark.asyncio
    async def test_htf_bias_update_on_4h_candle(
        self,
        mock_websocket_client,
        mock_data_loader,
        mock_trend_filter,
        sample_candles
    ):
        """Test HTF bias updates when 4h candle closes"""
        symbols = ['btcusdt']

        manager = RealTimeDataManager(
            symbols=symbols,
            websocket_client=mock_websocket_client,
            data_loader=mock_data_loader,
            trend_filter=mock_trend_filter
        )

        # Initialize buffers with sufficient data
        manager.candles_4h['btcusdt'] = deque(sample_candles[:200], maxlen=250)
        manager.htf_bias['btcusdt'] = 'BULLISH'

        # Mock trend filter to return BEARISH (changed)
        mock_trend_filter.calculate_bias = Mock(return_value='BEARISH')

        # Simulate 4h candle close
        new_candle = Candle(
            timestamp=datetime.now(timezone.utc),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=1000.0
        )

        await manager._on_websocket_candle(
            new_candle,
            {'symbol': 'btcusdt', 'interval': '4h', 'is_closed': True}
        )

        # Verify HTF bias updated
        assert manager.htf_bias['btcusdt'] == 'BEARISH'

        # Verify TrendFilter called
        mock_trend_filter.calculate_bias.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_candles(
        self,
        mock_websocket_client,
        mock_data_loader,
        mock_trend_filter,
        sample_candles
    ):
        """Test get_candles method"""
        symbols = ['btcusdt']

        manager = RealTimeDataManager(
            symbols=symbols,
            websocket_client=mock_websocket_client,
            data_loader=mock_data_loader,
            trend_filter=mock_trend_filter
        )

        # Initialize buffers
        manager.candles_15m['btcusdt'] = deque(sample_candles[:150], maxlen=150)
        manager.candles_4h['btcusdt'] = deque(sample_candles[:250], maxlen=250)

        # Test 15m candles
        candles_15m = manager.get_candles('btcusdt', '15m')
        assert len(candles_15m) == 150

        # Test 4h candles
        candles_4h = manager.get_candles('btcusdt', '4h')
        assert len(candles_4h) == 250

        # Test invalid timeframe
        with pytest.raises(ValueError):
            manager.get_candles('btcusdt', '1h')

    @pytest.mark.asyncio
    async def test_get_htf_bias(
        self,
        mock_websocket_client,
        mock_data_loader,
        mock_trend_filter
    ):
        """Test get_htf_bias method"""
        symbols = ['btcusdt']

        manager = RealTimeDataManager(
            symbols=symbols,
            websocket_client=mock_websocket_client,
            data_loader=mock_data_loader,
            trend_filter=mock_trend_filter
        )

        # Set HTF bias
        manager.htf_bias['btcusdt'] = 'BULLISH'

        # Test get HTF bias
        assert manager.get_htf_bias('btcusdt') == 'BULLISH'
        assert manager.get_htf_bias('BTCUSDT') == 'BULLISH'  # Case insensitive

        # Test unknown symbol
        assert manager.get_htf_bias('unknown') == 'NEUTRAL'

    @pytest.mark.asyncio
    async def test_get_stats(
        self,
        mock_websocket_client,
        mock_data_loader,
        mock_trend_filter,
        sample_candles
    ):
        """Test get_stats method"""
        symbols = ['btcusdt', 'ethusdt']

        manager = RealTimeDataManager(
            symbols=symbols,
            websocket_client=mock_websocket_client,
            data_loader=mock_data_loader,
            trend_filter=mock_trend_filter
        )

        # Initialize buffers
        manager.candles_15m['btcusdt'] = deque(sample_candles[:150], maxlen=150)
        manager.candles_4h['btcusdt'] = deque(sample_candles[:250], maxlen=250)
        manager.candles_15m['ethusdt'] = deque(sample_candles[:100], maxlen=150)
        manager.candles_4h['ethusdt'] = deque(sample_candles[:200], maxlen=250)
        manager.htf_bias['btcusdt'] = 'BULLISH'
        manager.htf_bias['ethusdt'] = 'BEARISH'
        manager._candle_count = 1000

        # Get stats
        stats = manager.get_stats()

        assert stats['symbols'] == 2
        assert stats['candles_15m'] == 250  # 150 + 100
        assert stats['candles_4h'] == 450  # 250 + 200
        assert stats['total_candles_processed'] == 1000
        assert stats['htf_bias']['btcusdt'] == 'BULLISH'
        assert stats['htf_bias']['ethusdt'] == 'BEARISH'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
