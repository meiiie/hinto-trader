"""
Test script for Confidence Calculator

Tests confidence score calculation based on indicator alignment.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.application.services.confidence_calculator import ConfidenceCalculator


def test_buy_excellent_confidence():
    """Test BUY signal with excellent confidence (all aligned)"""
    print("\n" + "="*60)
    print("TEST 1: BUY - Excellent Confidence")
    print("="*60)

    calculator = ConfidenceCalculator()

    result = calculator.calculate_confidence(
        direction='BUY',
        ema_crossover='bullish',  # Aligned
        volume_spike=True,  # Confirmed
        rsi_value=18.0  # Oversold
    )

    print(f"\nIndicators:")
    print(f"  EMA Crossover: bullish")
    print(f"  Volume Spike: True")
    print(f"  RSI: 18.0 (oversold)")

    print(f"\nResult:")
    print(f"  Confidence: {result.confidence_score:.0f}%")
    print(f"  Level: {calculator.get_confidence_level(result.confidence_score)}")
    print(f"  Alignment: {result.indicator_alignment}")

    assert result.confidence_score >= 80, "Should be excellent"
    print(f"\n✅ Excellent confidence PASSED")
    return True


def test_sell_excellent_confidence():
    """Test SELL signal with excellent confidence"""
    print("\n" + "="*60)
    print("TEST 2: SELL - Excellent Confidence")
    print("="*60)

    calculator = ConfidenceCalculator()

    result = calculator.calculate_confidence(
        direction='SELL',
        ema_crossover='bearish',
        volume_spike=True,
        rsi_value=85.0  # Overbought
    )

    print(f"\nIndicators:")
    print(f"  EMA Crossover: bearish")
    print(f"  Volume Spike: True")
    print(f"  RSI: 85.0 (overbought)")

    print(f"\nResult:")
    print(f"  Confidence: {result.confidence_score:.0f}%")
    print(f"  Level: {calculator.get_confidence_level(result.confidence_score)}")

    assert result.confidence_score >= 80, "Should be excellent"
    print(f"\n✅ Excellent confidence PASSED")
    return True


def test_fair_confidence():
    """Test signal with fair confidence (mixed indicators)"""
    print("\n" + "="*60)
    print("TEST 3: BUY - Fair Confidence")
    print("="*60)

    calculator = ConfidenceCalculator()

    result = calculator.calculate_confidence(
        direction='BUY',
        ema_crossover=None,  # No crossover
        volume_spike=False,  # No spike
        rsi_value=50.0  # Neutral
    )

    print(f"\nIndicators:")
    print(f"  EMA Crossover: None")
    print(f"  Volume Spike: False")
    print(f"  RSI: 50.0 (neutral)")

    print(f"\nResult:")
    print(f"  Confidence: {result.confidence_score:.0f}%")
    print(f"  Level: {calculator.get_confidence_level(result.confidence_score)}")

    assert 40 <= result.confidence_score < 60, "Should be fair"
    print(f"\n✅ Fair confidence PASSED")
    return True


def test_poor_confidence():
    """Test signal with poor confidence (opposite indicators)"""
    print("\n" + "="*60)
    print("TEST 4: BUY - Poor Confidence")
    print("="*60)

    calculator = ConfidenceCalculator()

    result = calculator.calculate_confidence(
        direction='BUY',
        ema_crossover='bearish',  # Opposite
        volume_spike=False,
        rsi_value=85.0  # Overbought (bad for BUY)
    )

    print(f"\nIndicators:")
    print(f"  EMA Crossover: bearish (opposite)")
    print(f"  Volume Spike: False")
    print(f"  RSI: 85.0 (overbought - bad for BUY)")

    print(f"\nResult:")
    print(f"  Confidence: {result.confidence_score:.0f}%")
    print(f"  Level: {calculator.get_confidence_level(result.confidence_score)}")

    assert result.confidence_score < 40, "Should be poor"
    print(f"\n✅ Poor confidence PASSED")
    return True


def test_weight_distribution():
    """Test weight distribution (40/30/30)"""
    print("\n" + "="*60)
    print("TEST 5: Weight Distribution")
    print("="*60)

    calculator = ConfidenceCalculator()

    # Test EMA weight (40%)
    result_ema = calculator.calculate_confidence(
        direction='BUY',
        ema_crossover='bullish',  # 100 points
        volume_spike=False,  # 50 points
        rsi_value=50.0  # 50 points
    )

    expected = 100 * 0.4 + 50 * 0.3 + 50 * 0.3

    print(f"\nTest: EMA=100, Volume=50, RSI=50")
    print(f"Expected: {expected:.0f}%")
    print(f"Actual: {result_ema.confidence_score:.0f}%")

    assert abs(result_ema.confidence_score - expected) < 1, "Weight calculation error"
    print(f"\n✅ Weight distribution PASSED")
    return True


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("CONFIDENCE CALCULATOR TEST SUITE")
    print("="*60)

    tests = [
        ("BUY Excellent Confidence", test_buy_excellent_confidence),
        ("SELL Excellent Confidence", test_sell_excellent_confidence),
        ("Fair Confidence", test_fair_confidence),
        ("Poor Confidence", test_poor_confidence),
        ("Weight Distribution", test_weight_distribution),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n❌ {test_name} FAILED: {e}")
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
