"""
Unit tests for domain entities.

Tests the Candle, Indicator, and MarketData entities.
"""

import pytest
from datetime import datetime

from src.domain.entities.candle import Candle
from src.domain.entities.indicator import Indicator
from src.domain.entities.market_data import MarketData


class TestCandle:
    """Tests for Candle entity"""

    def test_create_valid_candle(self):
        """Test creating a valid candle"""
        candle = Candle(
            timestamp=datetime(2025, 11, 18, 10, 0),
            open=90000.0,
            high=91000.0,
            low=89500.0,
            close=90500.0,
            volume=100.5
        )

        assert candle.timestamp == datetime(2025, 11, 18, 10, 0)
        assert candle.open == 90000.0
        assert candle.high == 91000.0
        assert candle.low == 89500.0
        assert candle.close == 90500.0
        assert candle.volume == 100.5

    def test_candle_high_less_than_low_raises_error(self):
        """Test that high < low raises ValueError"""
        with pytest.raises(ValueError, match="High price.*must be >= Low price"):
            Candle(
                timestamp=datetime(2025, 11, 18, 10, 0),
                open=90000.0,
                high=89000.0,  # High < Low
                low=90000.0,
                close=89500.0,
                volume=100.0
            )

    def test_candle_negative_price_raises_error(self):
        """Test that negative prices raise ValueError"""
        with pytest.raises(ValueError, match="must be positive"):
            Candle(
                timestamp=datetime(2025, 11, 18, 10, 0),
                open=-90000.0,  # Negative
                high=91000.0,
                low=89500.0,
                close=90500.0,
                volume=100.0
            )

    def test_candle_negative_volume_raises_error(self):
        """Test that negative volume raises ValueError"""
        with pytest.raises(ValueError, match="Volume must be non-negative"):
            Candle(
                timestamp=datetime(2025, 11, 18, 10, 0),
                open=90000.0,
                high=91000.0,
                low=89500.0,
                close=90500.0,
                volume=-100.0  # Negative
            )

    def test_candle_is_bullish(self):
        """Test bullish candle detection"""
        candle = Candle(
            timestamp=datetime(2025, 11, 18, 10, 0),
            open=90000.0,
            high=91000.0,
            low=89500.0,
            close=90500.0,  # Close > Open
            volume=100.0
        )

        assert candle.is_bullish is True
        assert candle.is_bearish is False

    def test_candle_is_bearish(self):
        """Test bearish candle detection"""
        candle = Candle(
            timestamp=datetime(2025, 11, 18, 10, 0),
            open=90500.0,
            high=91000.0,
            low=89500.0,
            close=90000.0,  # Close < Open
            volume=100.0
        )

        assert candle.is_bearish is True
        assert candle.is_bullish is False

    def test_candle_is_doji(self):
        """Test doji candle detection"""
        candle = Candle(
            timestamp=datetime(2025, 11, 18, 10, 0),
            open=90000.0,
            high=91000.0,
            low=89000.0,
            close=90000.0,  # Close == Open
            volume=100.0
        )

        assert candle.is_doji is True

    def test_candle_properties(self):
        """Test candle calculated properties"""
        candle = Candle(
            timestamp=datetime(2025, 11, 18, 10, 0),
            open=90000.0,
            high=91000.0,
            low=89000.0,
            close=90500.0,
            volume=100.0
        )

        assert candle.body_size == 500.0
        assert candle.upper_shadow == 500.0
        assert candle.lower_shadow == 1000.0
        assert candle.price_range == 2000.0
        assert candle.typical_price == pytest.approx(90166.67, abs=0.01)

    def test_candle_immutability(self):
        """Test that candle is immutable"""
        candle = Candle(
            timestamp=datetime(2025, 11, 18, 10, 0),
            open=90000.0,
            high=91000.0,
            low=89000.0,
            close=90500.0,
            volume=100.0
        )

        with pytest.raises(AttributeError):
            candle.close = 91000.0  # Should raise error


class TestIndicator:
    """Tests for Indicator entity"""

    def test_create_valid_indicator(self):
        """Test creating a valid indicator"""
        indicator = Indicator(
            ema_7=90500.0,
            rsi_6=45.5,
            volume_ma_20=1000.0
        )

        assert indicator.ema_7 == 90500.0
        assert indicator.rsi_6 == 45.5
        assert indicator.volume_ma_20 == 1000.0

    def test_create_indicator_with_none_values(self):
        """Test creating indicator with None values (warmup period)"""
        indicator = Indicator(
            ema_7=None,
            rsi_6=None,
            volume_ma_20=None
        )

        assert indicator.ema_7 is None
        assert indicator.rsi_6 is None
        assert indicator.volume_ma_20 is None

    def test_indicator_rsi_out_of_range_raises_error(self):
        """Test that RSI > 100 raises ValueError"""
        with pytest.raises(ValueError, match="RSI must be in range"):
            Indicator(
                ema_7=90500.0,
                rsi_6=150.0,  # > 100
                volume_ma_20=1000.0
            )

    def test_indicator_negative_ema_raises_error(self):
        """Test that negative EMA raises ValueError"""
        with pytest.raises(ValueError, match="EMA must be positive"):
            Indicator(
                ema_7=-90500.0,  # Negative
                rsi_6=45.5,
                volume_ma_20=1000.0
            )

    def test_indicator_negative_volume_ma_raises_error(self):
        """Test that negative Volume MA raises ValueError"""
        with pytest.raises(ValueError, match="Volume MA must be non-negative"):
            Indicator(
                ema_7=90500.0,
                rsi_6=45.5,
                volume_ma_20=-1000.0  # Negative
            )

    def test_indicator_is_complete(self):
        """Test indicator completeness check"""
        complete = Indicator(ema_7=90500.0, rsi_6=45.5, volume_ma_20=1000.0)
        incomplete = Indicator(ema_7=90500.0, rsi_6=None, volume_ma_20=1000.0)

        assert complete.is_complete() is True
        assert incomplete.is_complete() is False

    def test_indicator_validate_rsi(self):
        """Test RSI validation"""
        valid = Indicator(ema_7=90500.0, rsi_6=45.5, volume_ma_20=1000.0)
        none_rsi = Indicator(ema_7=90500.0, rsi_6=None, volume_ma_20=1000.0)

        assert valid.validate_rsi() is True
        assert none_rsi.validate_rsi() is True  # None is valid

    def test_indicator_oversold(self):
        """Test oversold detection"""
        oversold = Indicator(ema_7=90500.0, rsi_6=25.0, volume_ma_20=1000.0)
        not_oversold = Indicator(ema_7=90500.0, rsi_6=50.0, volume_ma_20=1000.0)

        assert oversold.is_oversold is True
        assert not_oversold.is_oversold is False

    def test_indicator_overbought(self):
        """Test overbought detection"""
        overbought = Indicator(ema_7=90500.0, rsi_6=75.0, volume_ma_20=1000.0)
        not_overbought = Indicator(ema_7=90500.0, rsi_6=50.0, volume_ma_20=1000.0)

        assert overbought.is_overbought is True
        assert not_overbought.is_overbought is False

    def test_indicator_rsi_signal(self):
        """Test RSI signal generation"""
        oversold = Indicator(ema_7=90500.0, rsi_6=25.0, volume_ma_20=1000.0)
        overbought = Indicator(ema_7=90500.0, rsi_6=75.0, volume_ma_20=1000.0)
        neutral = Indicator(ema_7=90500.0, rsi_6=50.0, volume_ma_20=1000.0)
        none_rsi = Indicator(ema_7=90500.0, rsi_6=None, volume_ma_20=1000.0)

        assert oversold.rsi_signal == 'OVERSOLD'
        assert overbought.rsi_signal == 'OVERBOUGHT'
        assert neutral.rsi_signal == 'NEUTRAL'
        assert none_rsi.rsi_signal == 'N/A'

    def test_indicator_get_missing_indicators(self):
        """Test getting missing indicators"""
        complete = Indicator(ema_7=90500.0, rsi_6=45.5, volume_ma_20=1000.0)
        partial = Indicator(ema_7=90500.0, rsi_6=None, volume_ma_20=None)

        assert complete.get_missing_indicators() == []
        assert partial.get_missing_indicators() == ['rsi_6', 'volume_ma_20']

    def test_indicator_completion_percentage(self):
        """Test completion percentage calculation"""
        complete = Indicator(ema_7=90500.0, rsi_6=45.5, volume_ma_20=1000.0)
        partial = Indicator(ema_7=90500.0, rsi_6=None, volume_ma_20=None)
        empty = Indicator(ema_7=None, rsi_6=None, volume_ma_20=None)

        assert complete.get_completion_percentage() == 100.0
        assert partial.get_completion_percentage() == pytest.approx(33.33, rel=0.01)
        assert empty.get_completion_percentage() == 0.0


class TestMarketData:
    """Tests for MarketData aggregate"""

    @pytest.fixture
    def sample_candle(self):
        """Create a sample candle for testing"""
        return Candle(
            timestamp=datetime(2025, 11, 18, 10, 0),
            open=90000.0,
            high=91000.0,
            low=89500.0,
            close=90500.0,
            volume=100.5
        )

    @pytest.fixture
    def sample_indicator(self):
        """Create a sample indicator for testing"""
        return Indicator(
            ema_7=90500.0,
            rsi_6=45.5,
            volume_ma_20=1000.0
        )

    def test_create_valid_market_data(self, sample_candle, sample_indicator):
        """Test creating valid market data"""
        market_data = MarketData(
            candle=sample_candle,
            indicator=sample_indicator,
            timeframe='15m'
        )

        assert market_data.candle == sample_candle
        assert market_data.indicator == sample_indicator
        assert market_data.timeframe == '15m'

    def test_market_data_invalid_timeframe_raises_error(self, sample_candle, sample_indicator):
        """Test that invalid timeframe raises ValueError"""
        with pytest.raises(ValueError, match="Timeframe must be one of"):
            MarketData(
                candle=sample_candle,
                indicator=sample_indicator,
                timeframe='invalid'
            )

    def test_market_data_properties(self, sample_candle, sample_indicator):
        """Test market data properties"""
        market_data = MarketData(
            candle=sample_candle,
            indicator=sample_indicator,
            timeframe='15m'
        )

        assert market_data.timestamp == sample_candle.timestamp
        assert market_data.close_price == sample_candle.close
        assert market_data.volume == sample_candle.volume

    def test_market_data_is_complete(self, sample_candle):
        """Test market data completeness"""
        complete_indicator = Indicator(ema_7=90500.0, rsi_6=45.5, volume_ma_20=1000.0)
        incomplete_indicator = Indicator(ema_7=90500.0, rsi_6=None, volume_ma_20=None)

        complete_data = MarketData(sample_candle, complete_indicator, '15m')
        incomplete_data = MarketData(sample_candle, incomplete_indicator, '15m')

        assert complete_data.is_complete is True
        assert incomplete_data.is_complete is False

    def test_market_data_quality_score(self, sample_candle):
        """Test data quality score calculation"""
        complete_indicator = Indicator(ema_7=90500.0, rsi_6=45.5, volume_ma_20=1000.0)
        partial_indicator = Indicator(ema_7=90500.0, rsi_6=None, volume_ma_20=None)

        complete_data = MarketData(sample_candle, complete_indicator, '15m')
        partial_data = MarketData(sample_candle, partial_indicator, '15m')

        assert complete_data.data_quality_score == 100.0
        assert partial_data.data_quality_score == pytest.approx(66.67, rel=0.01)

    def test_market_data_validate(self, sample_candle, sample_indicator):
        """Test market data validation"""
        market_data = MarketData(sample_candle, sample_indicator, '15m')
        is_valid, issues = market_data.validate()

        assert is_valid is True
        assert len(issues) == 0

    def test_market_data_validate_with_missing_indicators(self, sample_candle):
        """Test validation with missing indicators"""
        incomplete_indicator = Indicator(ema_7=90500.0, rsi_6=None, volume_ma_20=None)
        market_data = MarketData(sample_candle, incomplete_indicator, '15m')

        is_valid, issues = market_data.validate()

        # Should still be valid (missing indicators are warnings, not errors)
        assert is_valid is True
        assert any('Missing indicators' in issue for issue in issues)

    def test_market_data_get_trading_signal(self, sample_candle):
        """Test trading signal generation"""
        # Oversold + Uptrend = BUY
        oversold_indicator = Indicator(ema_7=90000.0, rsi_6=25.0, volume_ma_20=1000.0)
        market_data = MarketData(sample_candle, oversold_indicator, '15m')
        signal = market_data.get_trading_signal()

        assert signal['recommendation'] == 'BUY'
        assert signal['trend'] == 'UPTREND'
        assert signal['rsi_signal'] == 'OVERSOLD'

    def test_market_data_to_dict(self, sample_candle, sample_indicator):
        """Test conversion to dictionary"""
        market_data = MarketData(sample_candle, sample_indicator, '15m')
        data_dict = market_data.to_dict()

        assert data_dict['timeframe'] == '15m'
        assert data_dict['close'] == 90500.0
        assert data_dict['ema_7'] == 90500.0
        assert data_dict['rsi_6'] == 45.5
        assert data_dict['is_complete'] is True

    def test_market_data_immutability(self, sample_candle, sample_indicator):
        """Test that market data is immutable"""
        market_data = MarketData(sample_candle, sample_indicator, '15m')

        with pytest.raises(AttributeError):
            market_data.timeframe = '1h'  # Should raise error


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
