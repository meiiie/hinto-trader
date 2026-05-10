"""
Integration test for Entry Price Calculator with realistic scenarios

Tests entry price calculation with realistic market data patterns.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.domain.entities.candle import Candle
from src.application.services.entry_price_calculator import EntryPriceCalculator


def create_realistic_bullish_breakout() -> tuple:
    """
    Create realistic bullish breakout scenario.

    Scenario: Price consolidates, forms swing high, pulls back, ready to break out
    """
    base_time = datetime.now()

    # Realistic BTC/USDT 15m candles
    candles = []
    prices = [
        49800, 49850, 49900, 49950, 50000,  # Rising to resistance
        50100,  # Swing high - resistance level
        50050, 50000, 49980, 50020, 50050,  # Pullback and consolidation
        50080  # Ready to break resistance
    ]

    for i, price in enumerate(prices):
        candle = Candle(
            timestamp=base_time + timedelta(minutes=15*i),
            open=price,
            high=price + 50,
            low=price - 50,
            close=price,
            volume=1000000.0 + (i * 10000)
        )
        candles.append(candle)

    ema7 = 50050.0  # EMA(7) near current price

    return candles, ema7


def create_realistic_bearish_breakdown() -> tuple:
    """
    Create realistic bearish breakdown scenario.

    Scenario: Price declines, forms swing low, bounces, ready to break down
    """
    base_time = datetime.now()

    # Realistic BTC/USDT 15m candles
    candles = []
    prices = [
        50200, 50150, 50100, 50050, 50000,  # Declining to support
        49900,  # Swing low - support level
        49950, 50000, 50020, 49980, 49950,  # Bounce and consolidation
        49920  # Ready to break support
    ]

    for i, price in enumerate(prices):
        candle = Candle(
            timestamp=base_time + timedelta(minutes=15*i),
            open=price,
            high=price + 50,
            low=price - 50,
            close=price,
            volume=1000000.0 + (i * 10000)
        )
        candles.append(candle)

    ema7 = 49950.0  # EMA(7) near current price

    return candles, ema7


def test_realistic_buy_entry():
    """Test BUY entry with realistic bullish breakout"""
    print("\n" + "="*70)
    print("INTEGRATION TEST 1: Realistic BUY Entry (Bullish Breakout)")
    print("="*70)

    calculator = EntryPriceCalculator()
    candles, ema7 = create_realistic_bullish_breakout()

    print(f"\nScenario: BTC/USDT 15m - Bullish breakout from consolidation")
    print(f"Price action: {[c.close for c in candles]}")
    print(f"EMA(7): ${ema7:,.2f}")

    result = calculator.calculate_entry_price(
        direction='BUY',
        candles=candles,
        ema7=ema7
    )

    if result and result.is_valid:
        print(f"\n✅ Valid BUY Entry Found:")
        print(f"   Entry Price: ${result.entry_price:,.2f}")
        print(f"   Swing High: ${result.swing_price:,.2f}")
        print(f"   Entry Offset: +{result.offset_pct:.3%} above swing high")
        print(f"   Distance from EMA(7): {result.ema7_distance_pct:.3%}")
        print(f"\n   Trading Plan:")
        print(f"   - Place BUY limit order at ${result.entry_price:,.2f}")
        print(f"   - Entry triggers when price breaks above ${result.swing_price:,.2f}")
        print(f"   - Confirms bullish momentum")

        return True
    elif result and not result.is_valid:
        print(f"\n⚠️  Entry calculated but INVALID:")
        print(f"   Entry Price: ${result.entry_price:,.2f}")
        print(f"   Distance from EMA(7): {result.ema7_distance_pct:.3%} (max: 0.5%)")
        print(f"   Reason: Entry too far from trend (EMA7)")
        return False
    else:
        print(f"\n❌ No valid entry found")
        return False


def test_realistic_sell_entry():
    """Test SELL entry with realistic bearish breakdown"""
    print("\n" + "="*70)
    print("INTEGRATION TEST 2: Realistic SELL Entry (Bearish Breakdown)")
    print("="*70)

    calculator = EntryPriceCalculator()
    candles, ema7 = create_realistic_bearish_breakdown()

    print(f"\nScenario: BTC/USDT 15m - Bearish breakdown from consolidation")
    print(f"Price action: {[c.close for c in candles]}")
    print(f"EMA(7): ${ema7:,.2f}")

    result = calculator.calculate_entry_price(
        direction='SELL',
        candles=candles,
        ema7=ema7
    )

    if result and result.is_valid:
        print(f"\n✅ Valid SELL Entry Found:")
        print(f"   Entry Price: ${result.entry_price:,.2f}")
        print(f"   Swing Low: ${result.swing_price:,.2f}")
        print(f"   Entry Offset: -{result.offset_pct:.3%} below swing low")
        print(f"   Distance from EMA(7): {result.ema7_distance_pct:.3%}")
        print(f"\n   Trading Plan:")
        print(f"   - Place SELL limit order at ${result.entry_price:,.2f}")
        print(f"   - Entry triggers when price breaks below ${result.swing_price:,.2f}")
        print(f"   - Confirms bearish momentum")

        return True
    elif result and not result.is_valid:
        print(f"\n⚠️  Entry calculated but INVALID:")
        print(f"   Entry Price: ${result.entry_price:,.2f}")
        print(f"   Distance from EMA(7): {result.ema7_distance_pct:.3%} (max: 0.5%)")
        print(f"   Reason: Entry too far from trend (EMA7)")
        return False
    else:
        print(f"\n❌ No valid entry found")
        return False


def test_entry_validation_logic():
    """Test entry validation with various EMA distances"""
    print("\n" + "="*70)
    print("INTEGRATION TEST 3: Entry Validation Logic")
    print("="*70)

    calculator = EntryPriceCalculator()
    candles, _ = create_realistic_bullish_breakout()

    test_cases = [
        (50100.0, "Very close to entry", True),
        (50150.0, "Close to entry (0.5%)", True),
        (50500.0, "Too far from entry (>0.5%)", False),
    ]

    print(f"\nTesting entry validation with different EMA(7) values:")

    passed = 0
    for ema7, description, expected_valid in test_cases:
        result = calculator.calculate_entry_price('BUY', candles, ema7)

        if result:
            actual_valid = result.is_valid
            status = "✅" if actual_valid == expected_valid else "❌"

            print(f"\n{status} EMA(7) = ${ema7:,.2f} ({description})")
            print(f"   Entry: ${result.entry_price:,.2f}")
            print(f"   Distance: {result.ema7_distance_pct:.3%}")
            print(f"   Valid: {actual_valid} (expected: {expected_valid})")

            if actual_valid == expected_valid:
                passed += 1
        else:
            print(f"\n❌ EMA(7) = ${ema7:,.2f} - No entry calculated")

    print(f"\nValidation tests: {passed}/{len(test_cases)} passed")
    return passed == len(test_cases)


def main():
    """Run integration tests"""
    print("\n" + "="*70)
    print("ENTRY PRICE CALCULATOR - INTEGRATION TEST SUITE")
    print("="*70)
    print("\nTesting with realistic market scenarios...")

    tests = [
        ("Realistic BUY Entry", test_realistic_buy_entry),
        ("Realistic SELL Entry", test_realistic_sell_entry),
        ("Entry Validation Logic", test_entry_validation_logic),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n❌ {test_name} FAILED with exception: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))

    # Summary
    print("\n" + "="*70)
    print("INTEGRATION TEST SUMMARY")
    print("="*70)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")

    print(f"\nTotal: {passed}/{total} integration tests passed")

    if passed == total:
        print("\n🎉 All integration tests PASSED!")
        print("\n✅ Entry Price Calculator is ready for production use!")
        return 0
    else:
        print(f"\n❌ {total - passed} integration test(s) FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
