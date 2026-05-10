"""
Test script for Entry Price Calculator

Tests entry price calculation for BUY and SELL signals.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.domain.entities.candle import Candle
from src.application.services.entry_price_calculator import (
    EntryPriceCalculator,
    EntryPriceResult
)


def create_test_candles_bullish() -> list:
    """Create test candles with bullish swing pattern"""
    base_time = datetime.now()

    # Create candles with a clear swing HIGH pattern for BUY entry
    # Pattern: rising to swing high, then pullback, then ready to break out
    candles = []
    prices = [
        95, 96, 97, 98, 99,  # Rising
        100,  # Swing high (index 5)
        99, 98, 99, 99.5, 99.8,  # Pullback then consolidation near swing high
        99.9  # Ready to break out
    ]

    for i, price in enumerate(prices):
        candle = Candle(
            timestamp=base_time + timedelta(minutes=i),
            open=price,
            high=price + 0.5,
            low=price - 0.5,
            close=price,
            volume=1000.0
        )
        candles.append(candle)

    return candles


def create_test_candles_bearish() -> list:
    """Create test candles with bearish swing pattern"""
    base_time = datetime.now()

    # Create candles with a clear swing LOW pattern for SELL entry
    # Pattern: declining to swing low, then bounce, then ready to break down
    candles = []
    prices = [
        105, 104, 103, 102, 101,  # Declining
        100,  # Swing low (index 5)
        101, 102, 101, 100.5, 100.2,  # Bounce then consolidation near swing low
        100.1  # Ready to break down
    ]

    for i, price in enumerate(prices):
        candle = Candle(
            timestamp=base_time + timedelta(minutes=i),
            open=price,
            high=price + 0.5,
            low=price - 0.5,
            close=price,
            volume=1000.0
        )
        candles.append(candle)

    return candles


def test_buy_entry_calculation():
    """Test BUY entry price calculation"""
    print("\n" + "="*60)
    print("TEST 1: BUY Entry Price Calculation")
    print("="*60)

    calculator = EntryPriceCalculator(
        offset_pct=0.001,  # 0.1%
        max_ema_distance_pct=0.005,  # 0.5%
        swing_lookback=5
    )

    candles = create_test_candles_bullish()
    ema7 = 100.0  # Close to swing high at 100

    print(f"\nCandle prices: {[c.close for c in candles]}")
    print(f"EMA(7): ${ema7:.2f}")

    result = calculator.calculate_entry_price(
        direction='BUY',
        candles=candles,
        ema7=ema7
    )

    if result:
        print(f"\n✅ Entry Price Result:")
        print(f"   Entry Price: ${result.entry_price:.2f}")
        print(f"   Swing Price: ${result.swing_price:.2f}")
        print(f"   Offset: {result.offset_pct:.3%}")
        print(f"   EMA(7) Distance: {result.ema7_distance_pct:.3%}")
        print(f"   Is Valid: {result.is_valid}")

        # Verify calculations
        expected_entry = result.swing_price * (1 + 0.001)
        assert abs(result.entry_price - expected_entry) < 0.01, "Entry calculation error"

        print(f"\n✅ BUY entry calculation PASSED")
        return True
    else:
        print(f"\n❌ No valid BUY entry found")
        return False


def test_sell_entry_calculation():
    """Test SELL entry price calculation"""
    print("\n" + "="*60)
    print("TEST 2: SELL Entry Price Calculation")
    print("="*60)

    calculator = EntryPriceCalculator(
        offset_pct=0.001,  # 0.1%
        max_ema_distance_pct=0.005,  # 0.5%
        swing_lookback=5
    )

    candles = create_test_candles_bearish()
    ema7 = 100.0  # Close to swing low at 100

    print(f"\nCandle prices: {[c.close for c in candles]}")
    print(f"EMA(7): ${ema7:.2f}")

    result = calculator.calculate_entry_price(
        direction='SELL',
        candles=candles,
        ema7=ema7
    )

    if result:
        print(f"\n✅ Entry Price Result:")
        print(f"   Entry Price: ${result.entry_price:.2f}")
        print(f"   Swing Price: ${result.swing_price:.2f}")
        print(f"   Offset: {result.offset_pct:.3%}")
        print(f"   EMA(7) Distance: {result.ema7_distance_pct:.3%}")
        print(f"   Is Valid: {result.is_valid}")

        # Verify calculations
        expected_entry = result.swing_price * (1 - 0.001)
        assert abs(result.entry_price - expected_entry) < 0.01, "Entry calculation error"

        print(f"\n✅ SELL entry calculation PASSED")
        return True
    else:
        print(f"\n❌ No valid SELL entry found")
        return False


def test_ema_validation():
    """Test EMA(7) distance validation"""
    print("\n" + "="*60)
    print("TEST 3: EMA(7) Distance Validation")
    print("="*60)

    calculator = EntryPriceCalculator(
        offset_pct=0.001,
        max_ema_distance_pct=0.005,
        swing_lookback=5
    )

    candles = create_test_candles_bullish()

    # Test with EMA far from swing point (should be invalid)
    ema7_far = 110.0  # Far from swing high at 100

    print(f"\nCandle prices: {[c.close for c in candles]}")
    print(f"EMA(7) (far): ${ema7_far:.2f}")

    result = calculator.calculate_entry_price(
        direction='BUY',
        candles=candles,
        ema7=ema7_far
    )

    if result:
        print(f"\n✅ Entry Price Result:")
        print(f"   Entry Price: ${result.entry_price:.2f}")
        print(f"   Swing Price: ${result.swing_price:.2f}")
        print(f"   EMA(7) Distance: {result.ema7_distance_pct:.3%}")
        print(f"   Is Valid: {result.is_valid}")

        if not result.is_valid:
            print(f"\n✅ Correctly rejected entry too far from EMA(7)")
            return True
        else:
            print(f"\n❌ Should have rejected entry far from EMA(7)")
            return False
    else:
        print(f"\n❌ No entry calculated")
        return False


def test_insufficient_candles():
    """Test with insufficient candles"""
    print("\n" + "="*60)
    print("TEST 4: Insufficient Candles")
    print("="*60)

    calculator = EntryPriceCalculator()

    # Only 5 candles (need at least 11)
    candles = create_test_candles_bullish()[:5]
    ema7 = 100.0

    print(f"\nNumber of candles: {len(candles)} (need 11)")

    result = calculator.calculate_entry_price(
        direction='BUY',
        candles=candles,
        ema7=ema7
    )

    if result is None:
        print(f"\n✅ Correctly returned None for insufficient candles")
        return True
    else:
        print(f"\n❌ Should have returned None")
        return False


def test_invalid_direction():
    """Test with invalid direction"""
    print("\n" + "="*60)
    print("TEST 5: Invalid Direction")
    print("="*60)

    calculator = EntryPriceCalculator()
    candles = create_test_candles_bullish()
    ema7 = 96.5

    print(f"\nDirection: 'INVALID'")

    result = calculator.calculate_entry_price(
        direction='INVALID',
        candles=candles,
        ema7=ema7
    )

    if result is None:
        print(f"\n✅ Correctly returned None for invalid direction")
        return True
    else:
        print(f"\n❌ Should have returned None")
        return False


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("ENTRY PRICE CALCULATOR TEST SUITE")
    print("="*60)

    tests = [
        ("BUY Entry Calculation", test_buy_entry_calculation),
        ("SELL Entry Calculation", test_sell_entry_calculation),
        ("EMA Validation", test_ema_validation),
        ("Insufficient Candles", test_insufficient_candles),
        ("Invalid Direction", test_invalid_direction)
    ]

    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n❌ {test_name} FAILED with exception: {e}")
            results.append((test_name, False))

    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All tests PASSED!")
        return 0
    else:
        print(f"\n❌ {total - passed} test(s) FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
