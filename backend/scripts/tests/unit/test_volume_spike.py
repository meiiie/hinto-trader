"""
Test Volume Spike Detector with real Binance data.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.infrastructure.api.binance_rest_client import BinanceRestClient
from src.infrastructure.indicators.volume_spike_detector import VolumeSpikeDetector


def main():
    print("=" * 70)
    print("VOLUME SPIKE DETECTOR TEST")
    print("=" * 70)

    # Initialize
    client = BinanceRestClient()
    detector = VolumeSpikeDetector(threshold=2.0)

    print(f"\nDetector: {detector}")
    print(f"Threshold range: {detector.get_threshold_range()}")

    # Fetch candles
    print("\n1. Fetching BTC/USDT 15m candles...")
    candles = client.get_klines(symbol='BTCUSDT', interval='15m', limit=50)

    if not candles:
        print("❌ Failed to fetch candles")
        return

    print(f"✅ Fetched {len(candles)} candles")

    # Extract volumes
    volumes = [c.volume for c in candles]

    # Calculate volume MA
    ma_period = 20
    volume_ma = sum(volumes[-ma_period:]) / ma_period
    current_volume = volumes[-1]

    print(f"\n2. Volume Analysis:")
    print(f"   Current Volume: {current_volume:.2f} BTC")
    print(f"   Volume MA(20):  {volume_ma:.2f} BTC")
    print(f"   Ratio: {current_volume / volume_ma:.2f}x")

    # Detect spike
    print(f"\n3. Spike Detection:")
    result = detector.detect_spike(current_volume, volume_ma)

    print(f"   Is Spike: {result.is_spike}")
    print(f"   Intensity: {result.intensity.value}")
    print(f"   Ratio: {result.ratio:.2f}x")
    print(f"   Threshold: {result.threshold}x")

    if result.is_spike:
        print(f"   🚨 VOLUME SPIKE DETECTED!")
        confidence_boost = detector.calculate_confidence_boost(result)
        print(f"   Confidence Boost: +{confidence_boost:.0f}%")
    else:
        print(f"   ✅ Normal volume (no spike)")

    # Test with different thresholds
    print(f"\n4. Testing Different Thresholds:")
    for threshold in [1.5, 2.0, 2.5, 3.0]:
        detector.set_threshold(threshold)
        result = detector.detect_spike(current_volume, volume_ma)
        status = "🚨 SPIKE" if result.is_spike else "✅ Normal"
        print(f"   Threshold {threshold}x: {status} ({result.intensity.value})")

    # Find recent spikes
    print(f"\n5. Recent Spike History:")
    detector.set_threshold(2.0)  # Reset to default

    spike_count = 0
    for i in range(len(volumes) - ma_period, len(volumes)):
        if i < ma_period:
            continue

        vol_ma = sum(volumes[i-ma_period:i]) / ma_period
        vol_current = volumes[i]
        result = detector.detect_spike(vol_current, vol_ma)

        if result.is_spike:
            spike_count += 1
            candle_idx = i
            print(f"   Candle {candle_idx}: {result.ratio:.2f}x ({result.intensity.value})")

    if spike_count == 0:
        print(f"   No spikes detected in recent {len(volumes) - ma_period} candles")
    else:
        print(f"\n   Total spikes: {spike_count}")

    # Statistics
    print(f"\n6. Volume Statistics:")
    min_vol = min(volumes)
    max_vol = max(volumes)
    avg_vol = sum(volumes) / len(volumes)

    print(f"   Min:  {min_vol:.2f} BTC")
    print(f"   Max:  {max_vol:.2f} BTC")
    print(f"   Avg:  {avg_vol:.2f} BTC")
    print(f"   Range: {max_vol / min_vol:.2f}x")

    print(f"\n" + "=" * 70)
    print("✅ VOLUME SPIKE DETECTOR TEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
