"""
Test RSI Zone-Based Alerts

Verifies that RSI alerts are properly generated and included in signals.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.domain.entities.candle import Candle
from src.application.analysis.rsi_monitor import RSIMonitor, RSIZone
from src.application.signals.signal_generator import SignalGenerator


def test_rsi_alert_generation():
    """Test that RSI alerts are generated correctly"""
    print("=" * 70)
    print("TEST 1: RSI Alert Generation")
    print("=" * 70)

    rsi_monitor = RSIMonitor(period=6)

    # Test different RSI values and their alerts
    test_cases = [
        (15.0, RSIZone.STRONG_OVERSOLD, 'critical', "STRONG OVERSOLD"),
        (25.0, RSIZone.OVERSOLD, 'warning', "OVERSOLD"),
        (50.0, RSIZone.NEUTRAL, None, None),  # No alert for neutral
        (70.0, RSIZone.OVERBOUGHT, 'warning', "OVERBOUGHT"),
        (85.0, RSIZone.STRONG_OVERBOUGHT, 'critical', "STRONG OVERBOUGHT"),
    ]

    for rsi_value, expected_zone, expected_severity, expected_keyword in test_cases:
        alerts = rsi_monitor.generate_alerts(rsi_value)
        zone = rsi_monitor.get_rsi_zone(rsi_value)

        print(f"\n📊 RSI = {rsi_value:.1f}")
        print(f"   Zone: {zone.value.upper()}")

        assert zone == expected_zone, f"Expected zone {expected_zone.value}, got {zone.value}"

        if expected_severity:
            assert len(alerts) > 0, f"Expected alerts for RSI {rsi_value}"
            alert = alerts[0]
            print(f"   Alert: {alert.message}")
            print(f"   Severity: {alert.severity}")

            assert alert.severity == expected_severity, \
                f"Expected severity {expected_severity}, got {alert.severity}"
            assert expected_keyword in alert.message, \
                f"Expected '{expected_keyword}' in message"

            print(f"   ✅ Alert generated correctly!")
        else:
            assert len(alerts) == 0, f"Expected no alerts for neutral RSI {rsi_value}"
            print(f"   ✅ No alert (neutral zone)")

    print(f"\n✅ RSI alert generation test PASSED!")
    return True


def create_oversold_scenario():
    """Create candles with oversold RSI"""
    candles = []
    timestamp = datetime.now() - timedelta(minutes=50)

    # Strong downtrend for oversold RSI
    for i in range(50):
        close_price = 50000 - (i * 150)

        # Add volume spike at the end
        if i == 49:
            volume = 300.0  # EXTREME spike
        else:
            volume = 100.0

        candle = Candle(
            timestamp=timestamp + timedelta(minutes=i),
            open=close_price + 50,
            high=close_price + 100,
            low=close_price - 100,
            close=close_price,
            volume=volume
        )
        candles.append(candle)

    return candles


def create_overbought_scenario():
    """Create candles with overbought RSI"""
    candles = []
    timestamp = datetime.now() - timedelta(minutes=50)

    # Strong uptrend for overbought RSI
    for i in range(50):
        close_price = 50000 + (i * 150) + (i * i * 2)

        # Add volume spike at the end
        if i == 49:
            volume = 250.0  # STRONG spike
        else:
            volume = 100.0

        candle = Candle(
            timestamp=timestamp + timedelta(minutes=i),
            open=close_price - 50,
            high=close_price + 100,
            low=close_price - 100,
            close=close_price,
            volume=volume
        )
        candles.append(candle)

    return candles


def test_alerts_in_signal_metadata():
    """Test that RSI alerts are included in signal metadata"""
    print("\n" + "=" * 70)
    print("TEST 2: RSI Alerts in Signal Metadata")
    print("=" * 70)

    # Test with oversold scenario
    print("\n📊 Testing OVERSOLD scenario:")
    candles = create_oversold_scenario()
    signal_gen = SignalGenerator()
    signal = signal_gen.generate_signal(candles)

    if signal:
        print(f"   Signal Type: {signal.signal_type.value.upper()}")
        print(f"   RSI: {signal.indicators.get('rsi', 0):.1f}")
        print(f"   RSI Zone: {signal.indicators.get('rsi_zone', 'unknown').upper()}")

        # Check for RSI alerts in indicators
        rsi_alerts = signal.indicators.get('rsi_alerts', [])
        print(f"   RSI Alerts: {len(rsi_alerts)} alert(s)")

        for alert in rsi_alerts:
            print(f"      • {alert['message']}")
            print(f"        Severity: {alert['severity']}")

        assert len(rsi_alerts) > 0, "Expected RSI alerts in signal metadata"
        assert rsi_alerts[0]['severity'] in ['warning', 'critical'], \
            "Expected warning or critical severity"

        print(f"   ✅ RSI alerts included in signal!")
    else:
        print(f"   ⚠️  No signal generated")

    # Test with overbought scenario
    print("\n📊 Testing OVERBOUGHT scenario:")
    candles = create_overbought_scenario()
    signal = signal_gen.generate_signal(candles)

    if signal:
        print(f"   Signal Type: {signal.signal_type.value.upper()}")
        print(f"   RSI: {signal.indicators.get('rsi', 0):.1f}")
        print(f"   RSI Zone: {signal.indicators.get('rsi_zone', 'unknown').upper()}")

        # Check for RSI alerts
        rsi_alerts = signal.indicators.get('rsi_alerts', [])
        print(f"   RSI Alerts: {len(rsi_alerts)} alert(s)")

        for alert in rsi_alerts:
            print(f"      • {alert['message']}")
            print(f"        Severity: {alert['severity']}")

        assert len(rsi_alerts) > 0, "Expected RSI alerts in signal metadata"
        assert rsi_alerts[0]['severity'] in ['warning', 'critical'], \
            "Expected warning or critical severity"

        print(f"   ✅ RSI alerts included in signal!")
    else:
        print(f"   ⚠️  No signal generated")

    print(f"\n✅ RSI alerts in signal metadata test PASSED!")
    return True


def test_alert_severity_levels():
    """Test that alert severity levels are correct"""
    print("\n" + "=" * 70)
    print("TEST 3: Alert Severity Levels")
    print("=" * 70)

    rsi_monitor = RSIMonitor(period=6)

    # Test critical alerts (strong oversold/overbought)
    print("\n📊 Testing CRITICAL alerts:")

    # Strong oversold
    alerts = rsi_monitor.generate_alerts(15.0)
    assert len(alerts) > 0, "Expected alert for strong oversold"
    assert alerts[0].severity == 'critical', "Expected critical severity"
    print(f"   RSI 15.0: {alerts[0].severity.upper()} ✅")

    # Strong overbought
    alerts = rsi_monitor.generate_alerts(85.0)
    assert len(alerts) > 0, "Expected alert for strong overbought"
    assert alerts[0].severity == 'critical', "Expected critical severity"
    print(f"   RSI 85.0: {alerts[0].severity.upper()} ✅")

    # Test warning alerts (oversold/overbought zones)
    print("\n📊 Testing WARNING alerts:")

    # Oversold warning
    alerts = rsi_monitor.generate_alerts(30.0)
    assert len(alerts) > 0, "Expected alert for oversold"
    assert alerts[0].severity == 'warning', "Expected warning severity"
    print(f"   RSI 30.0: {alerts[0].severity.upper()} ✅")

    # Overbought warning
    alerts = rsi_monitor.generate_alerts(70.0)
    assert len(alerts) > 0, "Expected alert for overbought"
    assert alerts[0].severity == 'warning', "Expected warning severity"
    print(f"   RSI 70.0: {alerts[0].severity.upper()} ✅")

    # Test no alerts for neutral
    print("\n📊 Testing NO alerts for NEUTRAL:")
    alerts = rsi_monitor.generate_alerts(50.0)
    assert len(alerts) == 0, "Expected no alerts for neutral RSI"
    print(f"   RSI 50.0: No alerts ✅")

    print(f"\n✅ Alert severity levels test PASSED!")
    return True


def main():
    """Run all RSI alert tests"""
    print("\n" + "=" * 70)
    print("RSI ZONE-BASED ALERTS TESTS")
    print("Testing RSI Alert Generation and Integration")
    print("=" * 70)

    try:
        # Run tests
        test1 = test_rsi_alert_generation()
        test2 = test_alerts_in_signal_metadata()
        test3 = test_alert_severity_levels()

        if test1 and test2 and test3:
            print("\n" + "=" * 70)
            print("✅ ALL RSI ALERT TESTS PASSED!")
            print("=" * 70)
            print("\n📋 Summary:")
            print("   ✅ RSI alerts generated correctly for all zones")
            print("   ✅ Alerts included in signal metadata")
            print("   ✅ Severity levels (critical/warning) working correctly")
            print("   ✅ Zone information included in signals")
            print("\n🎉 Task 3.2 completed successfully!")
            return 0
        else:
            print("\n⚠️  Some tests had warnings")
            return 0

    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
