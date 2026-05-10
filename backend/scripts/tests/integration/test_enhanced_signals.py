"""
Test Enhanced Signal Generation with Volume Spike Integration

Tests the integration of VolumeSpikeDetector into SignalGenerator.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.domain.entities.candle import Candle
from src.application.signals.signal_generator import SignalGenerator
from src.application.analysis import VolumeAnalyzer, RSIMonitor
from src.infrastructure.indicators.volume_spike_detector import VolumeSpikeDetector


def create_test_candles(
    count: int = 50,
    base_price: float = 50000.0,
    base_volume: float = 100.0
) -> list:
    """Create test candles with varying prices and volumes"""
    candles = []
    timestamp = datetime.now() - timedelta(minutes=count)

    for i in range(count):
        # Simulate price movement
        price_change = (i % 10 - 5) * 100  # Oscillating price
        close_price = base_price + price_change

        # Simulate volume (spike at position 45)
        if i == 45:
            volume = base_volume * 3.0  # EXTREME spike
        elif i == 40:
            volume = base_volume * 2.2  # STRONG spike
        elif i == 35:
            volume = base_volume * 1.6  # MODERATE spike
        else:
            volume = base_volume

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


def test_volume_spike_integration():
    """Test that volume spike detector is properly integrated"""
    print("=" * 60)
    print("TEST: Volume Spike Integration")
    print("=" * 60)

    # Create signal generator with volume spike detector
    volume_spike_detector = VolumeSpikeDetector(threshold=2.0)
    signal_gen = SignalGenerator(
        volume_spike_detector=volume_spike_detector
    )

    # Create test candles with volume spike
    candles = create_test_candles(count=50, base_volume=100.0)

    # Generate signal
    signal = signal_gen.generate_signal(candles)

    if signal:
        print(f"\n✅ Signal Generated: {signal.signal_type.value.upper()}")
        print(f"   Confidence: {signal.confidence:.1%}")
        print(f"   Price: ${signal.price:,.2f}")

        # Check for volume spike indicators
        if 'volume_spike_intensity' in signal.indicators:
            intensity = signal.indicators['volume_spike_intensity']
            ratio = signal.indicators.get('volume_spike_ratio', 0)
            print(f"   Volume Spike: {intensity.upper()} ({ratio:.1f}x)")

        print(f"\n   Reasons:")
        for reason in signal.reasons:
            print(f"   - {reason}")
    else:
        print("\n⚠️  No signal generated")

    print()


def test_confidence_boost():
    """Test confidence boost from volume spikes"""
    print("=" * 60)
    print("TEST: Confidence Boost from Volume Spikes")
    print("=" * 60)

    volume_spike_detector = VolumeSpikeDetector(threshold=2.0)

    # Test different spike intensities
    test_cases = [
        (100, 100, "NONE", 0.0),
        (160, 100, "MODERATE", 10.0),
        (220, 100, "STRONG", 20.0),
        (320, 100, "EXTREME", 30.0),
    ]

    for current_vol, avg_vol, expected_intensity, expected_boost in test_cases:
        result = volume_spike_detector.detect_spike(current_vol, avg_vol)
        boost = volume_spike_detector.calculate_confidence_boost(result)

        print(f"\n📊 Volume: {current_vol} / {avg_vol} = {result.ratio:.1f}x")
        print(f"   Intensity: {result.intensity.value.upper()}")
        print(f"   Confidence Boost: +{boost:.0f}%")

        assert result.intensity.value == expected_intensity.lower(), \
            f"Expected {expected_intensity}, got {result.intensity.value}"
        assert boost == expected_boost, \
            f"Expected boost {expected_boost}%, got {boost}%"

    print("\n✅ All confidence boost tests passed!")
    print()


def test_signal_with_extreme_spike():
    """Test signal generation with extreme volume spike"""
    print("=" * 60)
    print("TEST: Signal with EXTREME Volume Spike")
    print("=" * 60)

    # Create candles with extreme spike and oversold RSI
    candles = []
    timestamp = datetime.now() - timedelta(minutes=50)

    for i in range(50):
        # Create downtrend for oversold RSI
        close_price = 50000 - (i * 50)

        # Extreme volume spike at the end
        if i == 49:
            volume = 500.0  # 5x average
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

    # Generate signal
    signal_gen = SignalGenerator(
        volume_spike_detector=VolumeSpikeDetector(threshold=2.0)
    )
    signal = signal_gen.generate_signal(candles)

    if signal:
        print(f"\n✅ Signal: {signal.signal_type.value.upper()}")
        print(f"   Confidence: {signal.confidence:.1%}")

        # With extreme spike, confidence should be high
        if signal.confidence >= 0.80:
            print(f"   ✅ High confidence achieved with EXTREME spike!")

        intensity = signal.indicators.get('volume_spike_intensity', 'none')
        print(f"   Volume Spike: {intensity.upper()}")
    else:
        print("\n⚠️  No signal generated")

    print()


def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("ENHANCED SIGNAL GENERATION TESTS")
    print("Testing Volume Spike Integration")
    print("=" * 60 + "\n")

    try:
        test_volume_spike_integration()
        test_confidence_boost()
        test_signal_with_extreme_spike()

        print("=" * 60)
        print("✅ ALL TESTS COMPLETED SUCCESSFULLY!")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
