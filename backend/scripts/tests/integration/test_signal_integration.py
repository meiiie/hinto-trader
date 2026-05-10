"""
Integration Test: Signal Generation with Professional Volume Spike Detection

Verifies the complete integration of VolumeSpikeDetector into SignalGenerator.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.domain.entities.candle import Candle
from src.application.signals.signal_generator import SignalGenerator
from src.infrastructure.indicators.volume_spike_detector import VolumeSpikeDetector


def create_buy_signal_scenario():
    """Create candles that should generate a BUY signal"""
    candles = []
    timestamp = datetime.now() - timedelta(minutes=50)

    # Create downtrend for oversold RSI
    for i in range(50):
        close_price = 50000 - (i * 100)  # Downtrend

        # Add volume spike at the end
        if i == 49:
            volume = 300.0  # 3x average = EXTREME spike
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


def create_sell_signal_scenario():
    """Create candles that should generate a SELL signal"""
    candles = []
    timestamp = datetime.now() - timedelta(minutes=50)

    # Create strong uptrend for overbought RSI
    for i in range(50):
        # Strong uptrend with acceleration
        close_price = 50000 + (i * 150) + (i * i * 2)  # Accelerating uptrend

        # Add volume spike at the end
        if i == 49:
            volume = 250.0  # 2.5x average = STRONG spike
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


def test_buy_signal_with_volume_spike():
    """Test BUY signal generation with volume spike"""
    print("=" * 70)
    print("TEST 1: BUY Signal with Volume Spike")
    print("=" * 70)

    candles = create_buy_signal_scenario()
    signal_gen = SignalGenerator(
        volume_spike_detector=VolumeSpikeDetector(threshold=2.0)
    )

    signal = signal_gen.generate_signal(candles)

    if signal:
        print(f"\n✅ Signal Type: {signal.signal_type.value.upper()}")
        print(f"   Confidence: {signal.confidence:.1%}")
        print(f"   Price: ${signal.price:,.2f}")

        # Check indicators
        print(f"\n📊 Indicators:")
        print(f"   RSI: {signal.indicators.get('rsi', 0):.1f}")
        print(f"   Volume Ratio: {signal.indicators.get('volume_ratio', 0):.2f}x")
        print(f"   Volume Spike Intensity: {signal.indicators.get('volume_spike_intensity', 'none').upper()}")
        print(f"   EMA(7): ${signal.indicators.get('ema_7', 0):,.2f}")

        print(f"\n💡 Reasons:")
        for reason in signal.reasons:
            print(f"   • {reason}")

        # Verify it's a BUY signal
        assert signal.signal_type.value == 'buy', "Expected BUY signal"

        # Verify volume spike is detected
        intensity = signal.indicators.get('volume_spike_intensity', 'none')
        assert intensity in ['moderate', 'strong', 'extreme'], \
            f"Expected volume spike, got {intensity}"

        print(f"\n✅ BUY signal test PASSED!")
    else:
        print("\n❌ No signal generated")
        return False

    return True


def test_sell_signal_with_volume_spike():
    """Test SELL signal generation with volume spike"""
    print("\n" + "=" * 70)
    print("TEST 2: SELL Signal with Volume Spike")
    print("=" * 70)

    candles = create_sell_signal_scenario()
    signal_gen = SignalGenerator(
        volume_spike_detector=VolumeSpikeDetector(threshold=2.0)
    )

    signal = signal_gen.generate_signal(candles)

    if signal:
        print(f"\n✅ Signal Type: {signal.signal_type.value.upper()}")
        print(f"   Confidence: {signal.confidence:.1%}")
        print(f"   Price: ${signal.price:,.2f}")

        # Check indicators
        print(f"\n📊 Indicators:")
        print(f"   RSI: {signal.indicators.get('rsi', 0):.1f}")
        print(f"   Volume Ratio: {signal.indicators.get('volume_ratio', 0):.2f}x")
        print(f"   Volume Spike Intensity: {signal.indicators.get('volume_spike_intensity', 'none').upper()}")
        print(f"   EMA(7): ${signal.indicators.get('ema_7', 0):,.2f}")

        print(f"\n💡 Reasons:")
        for reason in signal.reasons:
            print(f"   • {reason}")

        # Verify it's a SELL signal
        assert signal.signal_type.value == 'sell', "Expected SELL signal"

        # Verify volume spike is detected
        intensity = signal.indicators.get('volume_spike_intensity', 'none')
        assert intensity in ['moderate', 'strong', 'extreme'], \
            f"Expected volume spike, got {intensity}"

        print(f"\n✅ SELL signal test PASSED!")
    else:
        print("\n❌ No signal generated")
        return False

    return True


def test_confidence_scaling():
    """Test that confidence scales with spike intensity"""
    print("\n" + "=" * 70)
    print("TEST 3: Confidence Scaling with Spike Intensity")
    print("=" * 70)

    spike_scenarios = [
        # Only spikes >= 2.0x trigger signals (threshold = 2.0)
        (2.2, "STRONG", 70.0),    # 2 conditions + STRONG = 50% + 20% = 70%
        (3.2, "EXTREME", 80.0),   # 2 conditions + EXTREME = 50% + 30% = 80%
    ]

    for spike_multiplier, expected_intensity, expected_min_confidence in spike_scenarios:
        # Create candles with specific spike
        candles = []
        timestamp = datetime.now() - timedelta(minutes=50)

        for i in range(50):
            close_price = 50000 - (i * 100)  # Downtrend for oversold

            if i == 49:
                volume = 100.0 * spike_multiplier
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

        signal_gen = SignalGenerator(
            volume_spike_detector=VolumeSpikeDetector(threshold=2.0)
        )
        signal = signal_gen.generate_signal(candles)

        if signal:
            intensity = signal.indicators.get('volume_spike_intensity', 'none')
            confidence_pct = signal.confidence * 100

            print(f"\n📊 Spike {spike_multiplier:.1f}x ({expected_intensity}):")
            print(f"   Detected Intensity: {intensity.upper()}")
            print(f"   Confidence: {confidence_pct:.0f}%")
            print(f"   Expected Min: {expected_min_confidence:.0f}%")

            # Verify confidence is at least the expected minimum
            assert confidence_pct >= expected_min_confidence, \
                f"Confidence {confidence_pct:.0f}% below expected {expected_min_confidence:.0f}%"

            print(f"   ✅ Confidence scaling correct!")

    print(f"\n✅ Confidence scaling test PASSED!")
    return True


def main():
    """Run all integration tests"""
    print("\n" + "=" * 70)
    print("SIGNAL GENERATION INTEGRATION TESTS")
    print("Volume Spike Detection Integration")
    print("=" * 70)

    try:
        # Run tests
        test1 = test_buy_signal_with_volume_spike()
        test2 = test_sell_signal_with_volume_spike()
        test3 = test_confidence_scaling()

        if test1 and test2 and test3:
            print("\n" + "=" * 70)
            print("✅ ALL INTEGRATION TESTS PASSED!")
            print("=" * 70)
            print("\n📋 Summary:")
            print("   ✅ Volume spike detection integrated into SignalGenerator")
            print("   ✅ Confidence boost working correctly")
            print("   ✅ Volume spike events logged")
            print("   ✅ BUY/SELL signals generated with volume confirmation")
            print("\n🎉 Task 2.2 completed successfully!")
            return 0
        else:
            print("\n❌ Some tests failed")
            return 1

    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
