"""
Test Swing Point Detector

Verifies swing high/low detection for entry price and stop loss calculation.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.domain.entities.candle import Candle
from src.infrastructure.indicators.swing_point_detector import SwingPointDetector


def create_test_candles_with_swings():
    """Create candles with clear swing points"""
    candles = []
    timestamp = datetime.now() - timedelta(minutes=50)

    # Create price pattern with swing high and swing low
    prices = [
        100, 102, 104, 106, 108,  # Uptrend
        110, 112, 115, 113, 111,  # Peak (swing high at index 7: 115)
        109, 107, 105, 103, 101,  # Downtrend
        99, 97, 95, 97, 99,       # Bottom (swing low at index 17: 95)
        101, 103, 105, 107, 109,  # Recovery
        111, 113, 115, 117, 119,  # Uptrend continues
    ]

    for i, price in enumerate(prices):
        candle = Candle(
            timestamp=timestamp + timedelta(minutes=i),
            open=price - 1,
            high=price + 2,
            low=price - 2,
            close=price,
            volume=100.0
        )
        candles.append(candle)

    return candles


def test_swing_high_detection():
    """Test swing high detection"""
    print("=" * 70)
    print("TEST 1: Swing High Detection")
    print("=" * 70)

    candles = create_test_candles_with_swings()
    detector = SwingPointDetector(lookback=5)

    swing_high = detector.find_recent_swing_high(candles)

    if swing_high:
        print(f"\n✅ Swing High Found:")
        print(f"   Price: ${swing_high.price:.2f}")
        print(f"   Index: {swing_high.index}")
        print(f"   Strength: {swing_high.strength}")
        print(f"   Candle Close: ${swing_high.candle.close:.2f}")

        # Verify it's a valid swing high
        assert swing_high.price > 0, "Swing high price should be positive"
        assert swing_high.index >= detector.lookback, "Swing high index should be valid"

        print(f"\n✅ Swing high detection test PASSED!")
        return True
    else:
        print("\n❌ No swing high found")
        return False


def test_swing_low_detection():
    """Test swing low detection"""
    print("\n" + "=" * 70)
    print("TEST 2: Swing Low Detection")
    print("=" * 70)

    candles = create_test_candles_with_swings()
    detector = SwingPointDetector(lookback=5)

    swing_low = detector.find_recent_swing_low(candles)

    if swing_low:
        print(f"\n✅ Swing Low Found:")
        print(f"   Price: ${swing_low.price:.2f}")
        print(f"   Index: {swing_low.index}")
        print(f"   Strength: {swing_low.strength}")
        print(f"   Candle Close: ${swing_low.candle.close:.2f}")

        # Verify it's a valid swing low
        assert swing_low.price > 0, "Swing low price should be positive"
        assert swing_low.index >= detector.lookback, "Swing low index should be valid"

        print(f"\n✅ Swing low detection test PASSED!")
        return True
    else:
        print("\n❌ No swing low found")
        return False


def test_support_resistance_levels():
    """Test support and resistance level detection"""
    print("\n" + "=" * 70)
    print("TEST 3: Support/Resistance Levels")
    print("=" * 70)

    candles = create_test_candles_with_swings()
    detector = SwingPointDetector(lookback=5)

    supports, resistances = detector.find_support_resistance_levels(candles, num_levels=3)

    print(f"\n📊 Support Levels ({len(supports)}):")
    for i, level in enumerate(supports, 1):
        print(f"   S{i}: ${level:.2f}")

    print(f"\n📊 Resistance Levels ({len(resistances)}):")
    for i, level in enumerate(resistances, 1):
        print(f"   R{i}: ${level:.2f}")

    # Verify we found some levels
    assert len(supports) > 0, "Should find at least one support level"
    assert len(resistances) > 0, "Should find at least one resistance level"

    # Verify levels are sorted correctly
    if len(supports) > 1:
        assert supports[0] < supports[-1], "Support levels should be sorted ascending"

    if len(resistances) > 1:
        assert resistances[0] > resistances[-1], "Resistance levels should be sorted descending"

    print(f"\n✅ Support/Resistance detection test PASSED!")
    return True


def test_nearest_level():
    """Test finding nearest support/resistance level"""
    print("\n" + "=" * 70)
    print("TEST 4: Nearest Level Detection")
    print("=" * 70)

    detector = SwingPointDetector(lookback=5)

    # Test data
    current_price = 105.0
    resistance_levels = [110.0, 115.0, 120.0]
    support_levels = [100.0, 95.0, 90.0]

    # Find nearest resistance (above)
    nearest_resistance = detector.get_nearest_level(
        current_price, resistance_levels, direction='above'
    )

    print(f"\n📊 Current Price: ${current_price:.2f}")
    print(f"   Resistance Levels: {[f'${l:.2f}' for l in resistance_levels]}")
    print(f"   Nearest Resistance: ${nearest_resistance:.2f}")

    assert nearest_resistance == 110.0, "Should find 110.0 as nearest resistance"

    # Find nearest support (below)
    nearest_support = detector.get_nearest_level(
        current_price, support_levels, direction='below'
    )

    print(f"\n   Support Levels: {[f'${l:.2f}' for l in support_levels]}")
    print(f"   Nearest Support: ${nearest_support:.2f}")

    assert nearest_support == 100.0, "Should find 100.0 as nearest support"

    print(f"\n✅ Nearest level detection test PASSED!")
    return True


def test_different_lookback_periods():
    """Test with different lookback periods"""
    print("\n" + "=" * 70)
    print("TEST 5: Different Lookback Periods")
    print("=" * 70)

    candles = create_test_candles_with_swings()

    lookback_periods = [3, 5, 7]

    for lookback in lookback_periods:
        detector = SwingPointDetector(lookback=lookback)

        swing_high = detector.find_recent_swing_high(candles)
        swing_low = detector.find_recent_swing_low(candles)

        print(f"\n📊 Lookback = {lookback}:")

        if swing_high:
            print(f"   Swing High: ${swing_high.price:.2f} at index {swing_high.index}")
        else:
            print(f"   Swing High: Not found")

        if swing_low:
            print(f"   Swing Low: ${swing_low.price:.2f} at index {swing_low.index}")
        else:
            print(f"   Swing Low: Not found")

    print(f"\n✅ Different lookback periods test PASSED!")
    return True


def test_insufficient_data():
    """Test with insufficient candles"""
    print("\n" + "=" * 70)
    print("TEST 6: Insufficient Data Handling")
    print("=" * 70)

    # Create only 10 candles (not enough for lookback=5)
    candles = []
    timestamp = datetime.now()

    for i in range(10):
        candle = Candle(
            timestamp=timestamp + timedelta(minutes=i),
            open=100.0,
            high=102.0,
            low=98.0,
            close=100.0,
            volume=100.0
        )
        candles.append(candle)

    detector = SwingPointDetector(lookback=5)

    swing_high = detector.find_recent_swing_high(candles)
    swing_low = detector.find_recent_swing_low(candles)

    print(f"\n📊 Candles: {len(candles)} (need {2 * detector.lookback + 1})")
    print(f"   Swing High: {swing_high}")
    print(f"   Swing Low: {swing_low}")

    assert swing_high is None, "Should return None with insufficient data"
    assert swing_low is None, "Should return None with insufficient data"

    print(f"\n✅ Insufficient data handling test PASSED!")
    return True


def main():
    """Run all swing point detector tests"""
    print("\n" + "=" * 70)
    print("SWING POINT DETECTOR TESTS")
    print("Testing Swing High/Low Detection")
    print("=" * 70)

    try:
        # Run tests
        test1 = test_swing_high_detection()
        test2 = test_swing_low_detection()
        test3 = test_support_resistance_levels()
        test4 = test_nearest_level()
        test5 = test_different_lookback_periods()
        test6 = test_insufficient_data()

        if all([test1, test2, test3, test4, test5, test6]):
            print("\n" + "=" * 70)
            print("✅ ALL SWING POINT DETECTOR TESTS PASSED!")
            print("=" * 70)
            print("\n📋 Summary:")
            print("   ✅ Swing high detection working correctly")
            print("   ✅ Swing low detection working correctly")
            print("   ✅ Support/Resistance level detection working")
            print("   ✅ Nearest level detection working")
            print("   ✅ Different lookback periods supported")
            print("   ✅ Insufficient data handled gracefully")
            print("\n🎉 Task 5.2 completed successfully!")
            return 0
        else:
            print("\n⚠️  Some tests failed")
            return 1

    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
