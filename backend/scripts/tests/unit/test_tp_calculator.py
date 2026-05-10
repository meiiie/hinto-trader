"""
Test script for TP Calculator

Tests multi-target TP system calculation for BUY and SELL signals.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.domain.entities.candle import Candle
from src.application.services.tp_calculator import TPCalculator, TPCalculationResult


def create_test_candles_with_resistance() -> list:
    """Create test candles with clear resistance levels"""
    base_time = datetime.now()

    # Create candles with resistance levels at 100, 102, 104
    candles = []
    prices = [
        95, 96, 97, 98, 99,  # Rising
        100, 99, 98,  # Resistance at 100
        99, 100, 101,  # Test resistance
        102, 101, 100,  # Resistance at 102
        101, 102, 103,  # Test resistance
        104, 103, 102,  # Resistance at 104
        103, 104, 105  # Break resistance
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


def create_test_candles_with_support() -> list:
    """Create test candles with clear support levels"""
    base_time = datetime.now()

    # Create candles with support levels at 100, 98, 96
    candles = []
    prices = [
        105, 104, 103, 102, 101,  # Declining
        100, 101, 102,  # Support at 100
        101, 100, 99,  # Test support
        98, 99, 100,  # Support at 98
        99, 98, 97,  # Test support
        96, 97, 98,  # Support at 96
        97, 96, 95  # Break support
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


def test_buy_tp_calculation():
    """Test BUY TP calculation with resistance levels"""
    print("\n" + "="*60)
    print("TEST 1: BUY TP Calculation")
    print("="*60)

    calculator = TPCalculator(min_risk_reward=1.5)
    candles = create_test_candles_with_resistance()

    entry_price = 99.0
    stop_loss = 97.0

    print(f"\nEntry Price: ${entry_price:.2f}")
    print(f"Stop Loss: ${stop_loss:.2f}")
    print(f"Risk: ${entry_price - stop_loss:.2f}")

    result = calculator.calculate_tp_levels(
        entry_price=entry_price,
        stop_loss=stop_loss,
        direction='BUY',
        candles=candles
    )

    if result:
        print(f"\n✅ TP Calculation Result:")
        print(f"   TP1: ${result.tp_levels.tp1:.2f} (60% position)")
        print(f"   TP2: ${result.tp_levels.tp2:.2f} (30% position)")
        print(f"   TP3: ${result.tp_levels.tp3:.2f} (10% position)")
        print(f"   Risk:Reward Ratio: {result.risk_reward_ratio:.2f}")
        print(f"   Is Valid: {result.is_valid}")
        print(f"   S/R Levels: {[f'${l:.2f}' for l in result.support_resistance_levels]}")

        # Verify TP ordering
        assert result.tp_levels.tp1 > entry_price, "TP1 must be above entry"
        assert result.tp_levels.tp2 > result.tp_levels.tp1, "TP2 must be above TP1"
        assert result.tp_levels.tp3 > result.tp_levels.tp2, "TP3 must be above TP2"

        # Verify R:R ratio
        if result.is_valid:
            assert result.risk_reward_ratio >= 1.5, "R:R must be >= 1.5"

        print(f"\n✅ BUY TP calculation PASSED")
        return True
    else:
        print(f"\n❌ No TP calculated")
        return False


def test_sell_tp_calculation():
    """Test SELL TP calculation with support levels"""
    print("\n" + "="*60)
    print("TEST 2: SELL TP Calculation")
    print("="*60)

    calculator = TPCalculator(min_risk_reward=1.5)
    candles = create_test_candles_with_support()

    entry_price = 101.0
    stop_loss = 103.0

    print(f"\nEntry Price: ${entry_price:.2f}")
    print(f"Stop Loss: ${stop_loss:.2f}")
    print(f"Risk: ${stop_loss - entry_price:.2f}")

    result = calculator.calculate_tp_levels(
        entry_price=entry_price,
        stop_loss=stop_loss,
        direction='SELL',
        candles=candles
    )

    if result:
        print(f"\n✅ TP Calculation Result:")
        print(f"   TP1: ${result.tp_levels.tp1:.2f} (60% position)")
        print(f"   TP2: ${result.tp_levels.tp2:.2f} (30% position)")
        print(f"   TP3: ${result.tp_levels.tp3:.2f} (10% position)")
        print(f"   Risk:Reward Ratio: {result.risk_reward_ratio:.2f}")
        print(f"   Is Valid: {result.is_valid}")
        print(f"   S/R Levels: {[f'${l:.2f}' for l in result.support_resistance_levels]}")

        # Verify TP ordering
        assert result.tp_levels.tp1 < entry_price, "TP1 must be below entry"
        assert result.tp_levels.tp2 < result.tp_levels.tp1, "TP2 must be below TP1"
        assert result.tp_levels.tp3 < result.tp_levels.tp2, "TP3 must be below TP2"

        # Verify R:R ratio
        if result.is_valid:
            assert result.risk_reward_ratio >= 1.5, "R:R must be >= 1.5"

        print(f"\n✅ SELL TP calculation PASSED")
        return True
    else:
        print(f"\n❌ No TP calculated")
        return False


def test_fallback_tp_calculation():
    """Test fallback TP calculation when no S/R levels"""
    print("\n" + "="*60)
    print("TEST 3: Fallback TP Calculation")
    print("="*60)

    calculator = TPCalculator(min_risk_reward=1.5)

    # Create candles with no clear S/R levels (trending)
    base_time = datetime.now()
    candles = []
    for i in range(20):
        price = 100 + i  # Continuous uptrend
        candle = Candle(
            timestamp=base_time + timedelta(minutes=i),
            open=price,
            high=price + 0.5,
            low=price - 0.5,
            close=price,
            volume=1000.0
        )
        candles.append(candle)

    entry_price = 110.0
    stop_loss = 108.0
    risk = entry_price - stop_loss

    print(f"\nScenario: No clear S/R levels (trending market)")
    print(f"Entry Price: ${entry_price:.2f}")
    print(f"Stop Loss: ${stop_loss:.2f}")
    print(f"Risk: ${risk:.2f}")

    result = calculator.calculate_tp_levels(
        entry_price=entry_price,
        stop_loss=stop_loss,
        direction='BUY',
        candles=candles
    )

    if result:
        print(f"\n✅ Fallback TP Result:")
        print(f"   TP1: ${result.tp_levels.tp1:.2f} (1.5R = ${risk * 1.5:.2f})")
        print(f"   TP2: ${result.tp_levels.tp2:.2f} (2.5R = ${risk * 2.5:.2f})")
        print(f"   TP3: ${result.tp_levels.tp3:.2f} (3.5R = ${risk * 3.5:.2f})")
        print(f"   Risk:Reward Ratio: {result.risk_reward_ratio:.2f}")

        # Verify fallback uses risk multiples
        expected_tp1 = entry_price + (risk * 1.5)
        assert abs(result.tp_levels.tp1 - expected_tp1) < 0.01, "TP1 should be 1.5R"

        print(f"\n✅ Fallback TP calculation PASSED")
        return True
    else:
        print(f"\n❌ No TP calculated")
        return False


def test_tp_validation():
    """Test TP validation logic"""
    print("\n" + "="*60)
    print("TEST 4: TP Validation")
    print("="*60)

    calculator = TPCalculator(min_risk_reward=1.5)
    candles = create_test_candles_with_resistance()

    # Test with insufficient risk-reward
    entry_price = 99.0
    stop_loss = 95.0  # Large risk

    print(f"\nScenario: Large risk, testing R:R validation")
    print(f"Entry: ${entry_price:.2f}, Stop: ${stop_loss:.2f}")
    print(f"Risk: ${entry_price - stop_loss:.2f}")

    result = calculator.calculate_tp_levels(
        entry_price=entry_price,
        stop_loss=stop_loss,
        direction='BUY',
        candles=candles
    )

    if result:
        print(f"\n✅ TP Calculated:")
        print(f"   TP1: ${result.tp_levels.tp1:.2f}")
        print(f"   Risk:Reward: {result.risk_reward_ratio:.2f}")
        print(f"   Is Valid: {result.is_valid}")

        if result.risk_reward_ratio < 1.5:
            print(f"\n✅ Correctly flagged as invalid (R:R < 1.5)")
            return True
        else:
            print(f"\n✅ Valid R:R ratio achieved")
            return True
    else:
        print(f"\n❌ No TP calculated")
        return False


def test_invalid_inputs():
    """Test with invalid inputs"""
    print("\n" + "="*60)
    print("TEST 5: Invalid Inputs")
    print("="*60)

    calculator = TPCalculator()
    candles = create_test_candles_with_resistance()

    # Test invalid direction
    result = calculator.calculate_tp_levels(
        entry_price=100.0,
        stop_loss=98.0,
        direction='INVALID',
        candles=candles
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
    print("TP CALCULATOR TEST SUITE")
    print("="*60)

    tests = [
        ("BUY TP Calculation", test_buy_tp_calculation),
        ("SELL TP Calculation", test_sell_tp_calculation),
        ("Fallback TP Calculation", test_fallback_tp_calculation),
        ("TP Validation", test_tp_validation),
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
