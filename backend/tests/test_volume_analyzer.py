"""
Unit tests for VolumeAnalyzer
"""

import pytest
from datetime import datetime, timedelta
from src.domain.entities.candle import Candle
from src.application.analysis import VolumeAnalyzer, SpikeLevel


def create_candle(timestamp: datetime, volume: float) -> Candle:
    """Helper to create test candles"""
    return Candle(
        timestamp=timestamp,
        open=100.0,
        high=110.0,
        low=90.0,
        close=105.0,
        volume=volume
    )


def test_volume_analyzer_initialization():
    """Test analyzer initializes correctly"""
    analyzer = VolumeAnalyzer(ma_period=20)
    assert analyzer.ma_period == 20


def test_insufficient_data():
    """Test handling of insufficient data"""
    analyzer = VolumeAnalyzer(ma_period=20)

    # Only 10 candles (need 20)
    candles = [
        create_candle(datetime.now() + timedelta(minutes=i), 10.0)
        for i in range(10)
    ]

    result = analyzer.analyze(candles)
    assert result is None


def test_volume_ma_calculation():
    """Test volume moving average calculation"""
    analyzer = VolumeAnalyzer(ma_period=5)

    # Create candles with known volumes
    volumes = [10.0, 20.0, 30.0, 40.0, 50.0]
    candles = [
        create_candle(datetime.now() + timedelta(minutes=i), vol)
        for i, vol in enumerate(volumes)
    ]

    ma = analyzer.get_volume_ma(candles, period=5)
    expected = sum(volumes) / 5  # 30.0
    assert ma == expected


def test_spike_detection_normal():
    """Test normal volume detection"""
    analyzer = VolumeAnalyzer()

    spike_level = analyzer.detect_spike(
        current_volume=10.0,
        avg_volume=10.0
    )

    assert spike_level == SpikeLevel.NORMAL


def test_spike_detection_elevated():
    """Test elevated volume detection (1.5x - 2.0x)"""
    analyzer = VolumeAnalyzer()

    spike_level = analyzer.detect_spike(
        current_volume=18.0,
        avg_volume=10.0
    )

    assert spike_level == SpikeLevel.ELEVATED


def test_spike_detection_spike():
    """Test spike detection (2.0x - 2.5x)"""
    analyzer = VolumeAnalyzer()

    spike_level = analyzer.detect_spike(
        current_volume=22.0,
        avg_volume=10.0
    )

    assert spike_level == SpikeLevel.SPIKE


def test_spike_detection_strong():
    """Test strong spike detection (>= 2.5x)"""
    analyzer = VolumeAnalyzer()

    spike_level = analyzer.detect_spike(
        current_volume=30.0,
        avg_volume=10.0
    )

    assert spike_level == SpikeLevel.STRONG_SPIKE


def test_volume_analysis_complete():
    """Test complete volume analysis"""
    analyzer = VolumeAnalyzer(ma_period=20)

    # Create 25 candles with volume 10.0
    candles = [
        create_candle(datetime.now() + timedelta(minutes=i), 10.0)
        for i in range(25)
    ]

    # Last candle has spike (30.0 = 3x average of 10.0)
    candles[-1] = create_candle(datetime.now() + timedelta(minutes=24), 30.0)

    analysis = analyzer.analyze(candles)

    assert analysis is not None
    assert analysis.current_volume == 30.0
    # MA of last 20 candles: 19 * 10.0 + 1 * 30.0 = 220 / 20 = 11.0
    assert analysis.average_volume == pytest.approx(11.0, rel=0.01)
    assert analysis.ratio >= 2.5  # Should be strong spike
    assert analysis.spike_level == SpikeLevel.STRONG_SPIKE
    assert analysis.is_spike()


def test_alert_generation():
    """Test alert message generation"""
    analyzer = VolumeAnalyzer()

    from src.application.analysis.volume_analyzer import VolumeAnalysis

    # Strong spike
    analysis = VolumeAnalysis(
        current_volume=30.0,
        average_volume=10.0,
        spike_level=SpikeLevel.STRONG_SPIKE,
        ratio=3.0
    )

    alerts = analyzer.generate_alerts(analysis)
    assert len(alerts) == 1
    assert "STRONG VOLUME SPIKE" in alerts[0]
    assert "3.00x" in alerts[0]


def test_compare_volumes():
    """Test volume comparison with recent candles"""
    analyzer = VolumeAnalyzer()

    # Create candles with increasing volumes
    candles = [
        create_candle(datetime.now() + timedelta(minutes=i), 10.0 + i)
        for i in range(10)
    ]

    comparison = analyzer.compare_volumes(candles, lookback=5)

    assert comparison['current'] == 19.0  # Last candle
    assert comparison['is_highest'] == True
    assert comparison['vs_avg'] > 1.0


def test_volume_analysis_is_spike():
    """Test is_spike helper method"""
    from src.application.analysis.volume_analyzer import VolumeAnalysis

    # Spike level
    analysis = VolumeAnalysis(
        current_volume=20.0,
        average_volume=10.0,
        spike_level=SpikeLevel.SPIKE,
        ratio=2.0
    )
    assert analysis.is_spike() == True

    # Elevated (not spike)
    analysis = VolumeAnalysis(
        current_volume=15.0,
        average_volume=10.0,
        spike_level=SpikeLevel.ELEVATED,
        ratio=1.5
    )
    assert analysis.is_spike() == False


def test_volume_analysis_is_elevated():
    """Test is_elevated helper method"""
    from src.application.analysis.volume_analyzer import VolumeAnalysis

    # Elevated
    analysis = VolumeAnalysis(
        current_volume=15.0,
        average_volume=10.0,
        spike_level=SpikeLevel.ELEVATED,
        ratio=1.5
    )
    assert analysis.is_elevated() == True

    # Normal
    analysis = VolumeAnalysis(
        current_volume=10.0,
        average_volume=10.0,
        spike_level=SpikeLevel.NORMAL,
        ratio=1.0
    )
    assert analysis.is_elevated() == False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
