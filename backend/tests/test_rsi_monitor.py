"""
Unit tests for RSIMonitor
"""

import pytest
from datetime import datetime, timedelta
from src.domain.entities.candle import Candle
from src.application.analysis import RSIMonitor, RSIZone
from src.infrastructure.indicators.talib_calculator import TALibCalculator


# Create shared calculator for tests
_calculator = TALibCalculator()


def create_candle(timestamp: datetime, close: float) -> Candle:
    """Helper to create test candles"""
    return Candle(
        timestamp=timestamp,
        open=close - 5,
        high=close + 10,
        low=close - 10,
        close=close,
        volume=10.0
    )


def test_rsi_monitor_initialization():
    """Test monitor initializes with correct defaults"""
    monitor = RSIMonitor(calculator=_calculator)

    assert monitor.period == 6
    assert monitor.oversold_threshold == 35.0
    assert monitor.overbought_threshold == 65.0
    assert monitor.strong_oversold_threshold == 20.0
    assert monitor.strong_overbought_threshold == 80.0


def test_rsi_monitor_custom_thresholds():
    """Test monitor with custom thresholds"""
    monitor = RSIMonitor(
        period=14,
        oversold_threshold=25.0,
        overbought_threshold=75.0,
        calculator=_calculator
    )

    assert monitor.period == 14
    assert monitor.oversold_threshold == 25.0
    assert monitor.overbought_threshold == 75.0


def test_insufficient_data():
    """Test handling of insufficient data"""
    monitor = RSIMonitor(period=6, calculator=_calculator)

    # Only 5 candles (need 7 for RSI(6))
    candles = [
        create_candle(datetime.now() + timedelta(minutes=i), 100.0 + i)
        for i in range(5)
    ]

    rsi = monitor.calculate_rsi(candles)
    assert rsi is None


def test_rsi_zone_detection():
    """Test RSI zone classification"""
    monitor = RSIMonitor(calculator=_calculator)

    # Strong oversold
    assert monitor.get_rsi_zone(15.0) == RSIZone.STRONG_OVERSOLD

    # Oversold
    assert monitor.get_rsi_zone(25.0) == RSIZone.OVERSOLD

    # Neutral
    assert monitor.get_rsi_zone(50.0) == RSIZone.NEUTRAL

    # Overbought
    assert monitor.get_rsi_zone(75.0) == RSIZone.OVERBOUGHT

    # Strong overbought
    assert monitor.get_rsi_zone(85.0) == RSIZone.STRONG_OVERBOUGHT


def test_alert_generation_overbought():
    """Test alert generation for overbought conditions"""
    monitor = RSIMonitor(calculator=_calculator)

    # Overbought
    alerts = monitor.generate_alerts(75.0)
    assert len(alerts) == 1
    assert alerts[0].zone == RSIZone.OVERBOUGHT
    assert alerts[0].severity == 'warning'
    assert "OVERBOUGHT" in alerts[0].message

    # Strong overbought
    alerts = monitor.generate_alerts(85.0)
    assert len(alerts) == 1
    assert alerts[0].zone == RSIZone.STRONG_OVERBOUGHT
    assert alerts[0].severity == 'critical'
    assert "STRONG OVERBOUGHT" in alerts[0].message


def test_alert_generation_oversold():
    """Test alert generation for oversold conditions"""
    monitor = RSIMonitor(calculator=_calculator)

    # Oversold
    alerts = monitor.generate_alerts(25.0)
    assert len(alerts) == 1
    assert alerts[0].zone == RSIZone.OVERSOLD
    assert alerts[0].severity == 'warning'
    assert "OVERSOLD" in alerts[0].message

    # Strong oversold
    alerts = monitor.generate_alerts(15.0)
    assert len(alerts) == 1
    assert alerts[0].zone == RSIZone.STRONG_OVERSOLD
    assert alerts[0].severity == 'critical'
    assert "STRONG OVERSOLD" in alerts[0].message


def test_alert_generation_neutral():
    """Test no alerts for neutral zone"""
    monitor = RSIMonitor(calculator=_calculator)

    alerts = monitor.generate_alerts(50.0)
    assert len(alerts) == 0


def test_rsi_calculation_with_trend():
    """Test RSI calculation with trending prices"""
    monitor = RSIMonitor(period=6, calculator=_calculator)

    # Create uptrend (prices increasing)
    base_time = datetime.now()
    candles = [
        create_candle(base_time + timedelta(minutes=i), 100.0 + i * 2)
        for i in range(20)
    ]

    rsi = monitor.calculate_rsi(candles)

    # Uptrend should have high RSI
    assert rsi is not None
    assert rsi > 50.0  # Should be above neutral


def test_analyze_complete():
    """Test complete analysis"""
    monitor = RSIMonitor(period=6, calculator=_calculator)

    # Create candles with strong uptrend
    base_time = datetime.now()
    candles = [
        create_candle(base_time + timedelta(minutes=i), 100.0 + i * 3)
        for i in range(20)
    ]

    analysis = monitor.analyze(candles)

    assert analysis is not None
    assert 'rsi' in analysis
    assert 'zone' in analysis
    assert 'alerts' in analysis
    assert 'is_overbought' in analysis
    assert 'is_oversold' in analysis
    assert 'is_neutral' in analysis

    # Strong uptrend should be overbought
    assert analysis['rsi'] > 50.0


def test_analyze_insufficient_data():
    """Test analyze with insufficient data"""
    monitor = RSIMonitor(period=6)

    candles = [
        create_candle(datetime.now() + timedelta(minutes=i), 100.0)
        for i in range(5)
    ]

    analysis = monitor.analyze(candles)
    assert analysis is None


def test_get_zone_color():
    """Test zone color mapping"""
    monitor = RSIMonitor(calculator=_calculator)

    colors = {
        RSIZone.STRONG_OVERSOLD: '#26C6DA',
        RSIZone.OVERSOLD: '#66BB6A',
        RSIZone.NEUTRAL: '#FFC107',
        RSIZone.OVERBOUGHT: '#FF9800',
        RSIZone.STRONG_OVERBOUGHT: '#EF5350'
    }

    for zone, expected_color in colors.items():
        assert monitor.get_zone_color(zone) == expected_color


def test_get_zone_label():
    """Test zone label mapping"""
    monitor = RSIMonitor(calculator=_calculator)

    labels = {
        RSIZone.STRONG_OVERSOLD: 'Strong Oversold',
        RSIZone.OVERSOLD: 'Oversold',
        RSIZone.NEUTRAL: 'Neutral',
        RSIZone.OVERBOUGHT: 'Overbought',
        RSIZone.STRONG_OVERBOUGHT: 'Strong Overbought'
    }

    for zone, expected_label in labels.items():
        assert monitor.get_zone_label(zone) == expected_label


def test_boundary_conditions():
    """Test RSI zone boundaries"""
    monitor = RSIMonitor(calculator=_calculator)

    # Test exact boundaries
    assert monitor.get_rsi_zone(20.0) == RSIZone.OVERSOLD  # Exactly at threshold
    assert monitor.get_rsi_zone(19.99) == RSIZone.STRONG_OVERSOLD

    assert monitor.get_rsi_zone(35.0) == RSIZone.NEUTRAL
    assert monitor.get_rsi_zone(34.99) == RSIZone.OVERSOLD

    assert monitor.get_rsi_zone(65.0) == RSIZone.OVERBOUGHT
    assert monitor.get_rsi_zone(64.99) == RSIZone.NEUTRAL

    assert monitor.get_rsi_zone(80.0) == RSIZone.STRONG_OVERBOUGHT
    assert monitor.get_rsi_zone(79.99) == RSIZone.OVERBOUGHT


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
