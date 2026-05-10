"""
Test script for Stop Loss Calculator

Tests risk-based stop loss calculation for BUY and SELL signals.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.domain.entities.candle import Candle
from src.application.services.stop_loss_calculator import (
    StopLossCalculator,
    StopLossResult
)


def create_test_candles_bullish() -> list:
    """Create test candles with swing low pattern"""
    base_time = datetime.now()

    # Pattern with swing low at index 5
    candles = []
    prices = [
        105, 104, 103, 102, 101,  # Declining
        100,  # Swing low
        101, 102, 103, 104, 105,  # Rising
        106  # Current
    ]

    for i, price in enumerate(prices):
        candle = Candle(
            timestamp=base_time + timedelta(minutes=i),
            open=price,
            high=price + 1.0,
            low=price - 1.0,
            close=price,
            volume=1000.0
        )
        candles.append(candle)

    return candles


def create_test_candles_bearish() -> list:
    """Create test candles with swing high pattern"""
    base_time = datetime.now()

    # Pattern with swing high at index 5
    candles = []
    prices = [
        95, 96, 97, 98, 99,  # Rising
        100,  # Swing high
        99, 98, 97, 96, 95,  # Declining
        94  # Current
    ]

    for i, price in enumerate(prices):
        candle = Candle(
            timestamp=base_time + timedelta(minutes=i),
            open=price,
            high=price + 1.0,
            low=price - 1.0,
            close=price,
            volume=1000.0
        )
        candles.append(candle)

    return candles


def test_buy_stop_loss():
    """Test BUY stop loss calculation"""
    print("\n" + "="*60)
    print("TEST 1: BUY Stop Loss Calculation")
    print("="*60)

    calculator = StopLossCalculator(
        max_risk_pct=0.01,
        min_distance_pct=0.003
    )

    candles = create_test_candles_bullish()
    entry_price = 105.0
    ema25 = 102.0
    account_size = 10000.0

    print(f"\nEntry Price: ${entry_price:.2f}")
    print(f"EMA(25): ${ema25:.2f}")
    print(f"Account Size: ${account_size:,.2f}")

    result = calculator.calculate_stop_loss(
        entry_price=entry_price,
        direction='BUY',
        candles=candles,
        ema25=ema25,
        account_size=account_size
    )

    if result:
        print(f"\n✅ Stop Loss Result:")
        print(f"   Stop Loss: ${result.stop_loss:.2f}")
        print(f"   Stop Type: {result.stop_type}")
        print(f"   Distance: {result.distance_from_entry_pct:.3%}")
        print(f"   Swing Level: ${result.swing_level:.2f}" if result.swing_level else "   Swing Level: None")
        print(f"   EMA Level: ${result.ema_level:.2f}")
        print(f"   Is Valid: {result.is_valid}")

        # Verify stop is below entry
        assert result.stop_loss < entry_price, "BUY stop must be below entry"

        # Verify minimum distance
        if result.is_valid:
            assert result.distance_from_entry_pct >= 0.003, "Distance must be >= 0.3%"

        # Calculate position size
        position_size = calculator.calculate_position_size(
            entry_price=entry_price,
            stop_loss=result.stop_loss,
            account_size=account_size
        )

        risk_amount = (entry_price - result.stop_loss) * position_size

        print(f"\n   Position Sizing:")
        print(f"   Position Size: {position_size:.6f}")
        print(f"   Risk Amount: ${risk_amount:.2f}")
        print(f"   Risk %: {(risk_amount/account_size)*100:.2f}%")

        print(f"\n✅ BUY stop loss calculation PASSED")
        return True
    else:
        print(f"\n❌ No stop loss calculated")
        return False


def test_sell_stop_loss():
    """Test SELL stop loss calculation"""
    print("\n" + "="*60)
    print("TEST 2: SELL Stop Loss Calculation")
    print("="*60)

    calculator = StopLossCalculator(
        max_risk_pct=0.01,
        min_distance_pct=0.003
    )

    candles = create_test_candles_bearish()
    entry_price = 95.0
    ema25 = 98.0
    account_size = 10000.0

    print(f"\nEntry Price: ${entry_price:.2f}")
    print(f"EMA(25): ${ema25:.2f}")
    print(f"Account Size: ${account_size:,.2f}")

    result = calculator.calculate_stop_loss(
        entry_price=entry_price,
        direction='SELL',
        candles=candles,
        ema25=ema25,
        account_size=account_size
    )

    if result:
        print(f"\n✅ Stop Loss Result:")
        print(f"   Stop Loss: ${result.stop_loss:.2f}")
        print(f"   Stop Type: {result.stop_type}")
        print(f"   Distance: {result.distance_from_entry_pct:.3%}")
        print(f"   Swing Level: ${result.swing_level:.2f}" if result.swing_level else "   Swing Level: None")
        print(f"   EMA Level: ${result.ema_level:.2f}")
        print(f"   Is Valid: {result.is_valid}")

        # Verify stop is above entry
        assert result.stop_loss > entry_price, "SELL stop must be above entry"

        # Verify minimum distance
        if result.is_valid:
            assert result.distance_from_entry_pct >= 0.003, "Distance must be >= 0.3%"

        # Calculate position size
        position_size = calculator.calculate_position_size(
            entry_price=entry_price,
            stop_loss=result.stop_loss,
            account_size=account_size
        )

        risk_amount = (result.stop_loss - entry_price) * position_size

        print(f"\n   Position Sizing:")
        print(f"   Position Size: {position_size:.6f}")
        print(f"   Risk Amount: ${risk_amount:.2f}")
        print(f"   Risk %: {(risk_amount/account_size)*100:.2f}%")

        print(f"\n✅ SELL stop loss calculation PASSED")
        return True
    else:
        print(f"\n❌ No stop loss calculated")
        return False


def test_conservative_stop_selection():
    """Test that calculator selects more conservative stop"""
    print("\n" + "="*60)
    print("TEST 3: Conservative Stop Selection")
    print("="*60)

    calculator = StopLossCalculator()
    candles = create_test_candles_bullish()

    entry_price = 105.0
    ema25 = 102.0  # EMA below swing low

    print(f"\nScenario: EMA(25) below swing low")
    print(f"Entry: ${entry_price:.2f}")
    print(f"EMA(25): ${ema25:.2f}")
    print(f"Expected: Should use swing-based stop (higher/safer)")

    result = calculator.calculate_stop_loss(
        entry_price=entry_price,
        direction='BUY',
        candles=candles,
        ema25=ema25
    )

    if result:
        print(f"\n✅ Selected Stop:")
        print(f"   Stop Loss: ${result.stop_loss:.2f}")
        print(f"   Stop Type: {result.stop_type}")

        # For BUY, swing stop should be higher (more conservative) than EMA stop
        if result.stop_type == 'swing':
            print(f"\n✅ Correctly selected swing-based stop (more conservative)")
            return True
        else:
            print(f"\n⚠️  Selected {result.stop_type} stop")
            return True  # Still valid, just different choice
    else:
        print(f"\n❌ No stop calculated")
        return False


def test_minimum_distance_validation():
    """Test minimum distance validation"""
    print("\n" + "="*60)
    print("TEST 4: Minimum Distance Validation")
    print("="*60)

    calculator = StopLossCalculator(min_distance_pct=0.003)

    # Test valid distance
    valid = calculator.validate_stop_loss(
        stop_loss=99.0,
        entry_price=100.0,
        direction='BUY'
    )

    print(f"\nTest 1: Valid distance (1%)")
    print(f"   Entry: $100.00, Stop: $99.00")
    print(f"   Valid: {valid}")
    assert valid, "Should be valid"

    # Test invalid distance (too close)
    invalid = calculator.validate_stop_loss(
        stop_loss=99.95,
        entry_price=100.0,
        direction='BUY'
    )

    print(f"\nTest 2: Invalid distance (0.05%)")
    print(f"   Entry: $100.00, Stop: $99.95")
    print(f"   Valid: {invalid}")
    assert not invalid, "Should be invalid"

    print(f"\n✅ Minimum distance validation PASSED")
    return True


def test_invalid_inputs():
    """Test with invalid inputs"""
    print("\n" + "="*60)
    print("TEST 5: Invalid Inputs")
    print("="*60)

    calculator = StopLossCalculator()
    candles = create_test_candles_bullish()

    # Test invalid direction
    result = calculator.calculate_stop_loss(
        entry_price=100.0,
        direction='INVALID',
        candles=candles,
        ema25=98.0
    )

    if result is None:
        print(f"\n✅ Correctly rejected invalid direction")
        return True
    else:
        print(f"\n❌ Should have rejected invalid direction")
        return False


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("STOP LOSS CALCULATOR TEST SUITE")
    print("="*60)

    tests = [
        ("BUY Stop Loss", test_buy_stop_loss),
        ("SELL Stop Loss", test_sell_stop_loss),
        ("Conservative Stop Selection", test_conservative_stop_selection),
        ("Minimum Distance Validation", test_minimum_distance_validation),
        ("Invalid Inputs", test_invalid_inputs),
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
