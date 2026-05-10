"""
Integration test for TP Calculator with realistic scenarios

Tests TP calculation with realistic market data patterns.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.domain.entities.candle import Candle
from src.application.services.tp_calculator import TPCalculator


def create_realistic_btc_bullish() -> tuple:
    """
    Create realistic BTC/USDT bullish scenario with resistance levels.

    Scenario: BTC consolidating, ready to break resistance
    """
    base_time = datetime.now()

    # Realistic BTC/USDT 15m candles with resistance at 50500, 51000
    candles = []
    prices = [
        49500, 49600, 49700, 49800, 49900,  # Rising
        50000, 50100, 50200, 50300, 50400,  # Approaching resistance
        50500, 50400, 50300,  # Test resistance at 50500
        50400, 50500, 50600,  # Break resistance
        50700, 50800, 50900,  # Approaching next resistance
        51000, 50900, 50800,  # Test resistance at 51000
        50900, 51000, 51100  # Ready to break
    ]

    for i, price in enumerate(prices):
        candle = Candle(
            timestamp=base_time + timedelta(minutes=15*i),
            open=price,
            high=price + 100,
            low=price - 100,
            close=price,
            volume=1000000.0
        )
        candles.append(candle)

    entry_price = 50200.0  # Entry after breakout confirmation
    stop_loss = 49700.0    # Stop below recent swing low

    return candles, entry_price, stop_loss


def create_realistic_btc_bearish() -> tuple:
    """
    Create realistic BTC/USDT bearish scenario with support levels.

    Scenario: BTC declining, ready to break support
    """
    base_time = datetime.now()

    # Realistic BTC/USDT 15m candles with support at 49500, 49000
    candles = []
    prices = [
        50500, 50400, 50300, 50200, 50100,  # Declining
        50000, 49900, 49800, 49700, 49600,  # Approaching support
        49500, 49600, 49700,  # Test support at 49500
        49600, 49500, 49400,  # Break support
        49300, 49200, 49100,  # Approaching next support
        49000, 49100, 49200,  # Test support at 49000
        49100, 49000, 48900  # Ready to break
    ]

    for i, price in enumerate(prices):
        candle = Candle(
            timestamp=base_time + timedelta(minutes=15*i),
            open=price,
            high=price + 100,
            low=price - 100,
            close=price,
            volume=1000000.0
        )
        candles.append(candle)

    entry_price = 49800.0  # Entry after breakdown confirmation
    stop_loss = 50300.0    # Stop above recent swing high

    return candles, entry_price, stop_loss


def test_realistic_buy_tp():
    """Test BUY TP with realistic BTC scenario"""
    print("\n" + "="*70)
    print("INTEGRATION TEST 1: Realistic BUY TP (BTC Bullish Breakout)")
    print("="*70)

    calculator = TPCalculator(min_risk_reward=1.5)
    candles, entry_price, stop_loss = create_realistic_btc_bullish()

    risk = entry_price - stop_loss

    print(f"\nScenario: BTC/USDT 15m - Bullish breakout")
    print(f"Entry Price: ${entry_price:,.2f}")
    print(f"Stop Loss: ${stop_loss:,.2f}")
    print(f"Risk: ${risk:,.2f}")

    result = calculator.calculate_tp_levels(
        entry_price=entry_price,
        stop_loss=stop_loss,
        direction='BUY',
        candles=candles
    )

    if result and result.is_valid:
        print(f"\n✅ Valid TP Levels:")
        print(f"   TP1: ${result.tp_levels.tp1:,.2f} (60% position)")
        print(f"   TP2: ${result.tp_levels.tp2:,.2f} (30% position)")
        print(f"   TP3: ${result.tp_levels.tp3:,.2f} (10% position)")
        print(f"   Risk:Reward Ratio: {result.risk_reward_ratio:.2f}:1")

        # Calculate potential profits
        reward1 = result.tp_levels.tp1 - entry_price
        reward2 = result.tp_levels.tp2 - entry_price
        reward3 = result.tp_levels.tp3 - entry_price

        print(f"\n   Potential Rewards:")
        print(f"   TP1: ${reward1:,.2f} ({reward1/risk:.2f}R)")
        print(f"   TP2: ${reward2:,.2f} ({reward2/risk:.2f}R)")
        print(f"   TP3: ${reward3:,.2f} ({reward3/risk:.2f}R)")

        print(f"\n   Trading Plan:")
        print(f"   - Enter BUY at ${entry_price:,.2f}")
        print(f"   - Take 60% profit at ${result.tp_levels.tp1:,.2f}")
        print(f"   - Take 30% profit at ${result.tp_levels.tp2:,.2f}")
        print(f"   - Take 10% profit at ${result.tp_levels.tp3:,.2f}")
        print(f"   - Stop loss at ${stop_loss:,.2f}")

        return True
    else:
        print(f"\n❌ No valid TP found")
        return False


def test_realistic_sell_tp():
    """Test SELL TP with realistic BTC scenario"""
    print("\n" + "="*70)
    print("INTEGRATION TEST 2: Realistic SELL TP (BTC Bearish Breakdown)")
    print("="*70)

    calculator = TPCalculator(min_risk_reward=1.5)
    candles, entry_price, stop_loss = create_realistic_btc_bearish()

    risk = stop_loss - entry_price

    print(f"\nScenario: BTC/USDT 15m - Bearish breakdown")
    print(f"Entry Price: ${entry_price:,.2f}")
    print(f"Stop Loss: ${stop_loss:,.2f}")
    print(f"Risk: ${risk:,.2f}")

    result = calculator.calculate_tp_levels(
        entry_price=entry_price,
        stop_loss=stop_loss,
        direction='SELL',
        candles=candles
    )

    if result and result.is_valid:
        print(f"\n✅ Valid TP Levels:")
        print(f"   TP1: ${result.tp_levels.tp1:,.2f} (60% position)")
        print(f"   TP2: ${result.tp_levels.tp2:,.2f} (30% position)")
        print(f"   TP3: ${result.tp_levels.tp3:,.2f} (10% position)")
        print(f"   Risk:Reward Ratio: {result.risk_reward_ratio:.2f}:1")

        # Calculate potential profits
        reward1 = entry_price - result.tp_levels.tp1
        reward2 = entry_price - result.tp_levels.tp2
        reward3 = entry_price - result.tp_levels.tp3

        print(f"\n   Potential Rewards:")
        print(f"   TP1: ${reward1:,.2f} ({reward1/risk:.2f}R)")
        print(f"   TP2: ${reward2:,.2f} ({reward2/risk:.2f}R)")
        print(f"   TP3: ${reward3:,.2f} ({reward3/risk:.2f}R)")

        print(f"\n   Trading Plan:")
        print(f"   - Enter SELL at ${entry_price:,.2f}")
        print(f"   - Take 60% profit at ${result.tp_levels.tp1:,.2f}")
        print(f"   - Take 30% profit at ${result.tp_levels.tp2:,.2f}")
        print(f"   - Take 10% profit at ${result.tp_levels.tp3:,.2f}")
        print(f"   - Stop loss at ${stop_loss:,.2f}")

        return True
    else:
        print(f"\n❌ No valid TP found")
        return False


def test_position_sizing_with_tp():
    """Test position sizing calculation with TP levels"""
    print("\n" + "="*70)
    print("INTEGRATION TEST 3: Position Sizing with TP Levels")
    print("="*70)

    calculator = TPCalculator(min_risk_reward=1.5)
    candles, entry_price, stop_loss = create_realistic_btc_bullish()

    account_size = 10000.0  # $10,000 account
    risk_pct = 0.01  # 1% risk
    max_risk = account_size * risk_pct

    print(f"\nAccount Size: ${account_size:,.2f}")
    print(f"Max Risk: ${max_risk:,.2f} (1%)")

    result = calculator.calculate_tp_levels(
        entry_price=entry_price,
        stop_loss=stop_loss,
        direction='BUY',
        candles=candles
    )

    if result:
        risk_per_unit = entry_price - stop_loss
        position_size = max_risk / risk_per_unit

        print(f"\nEntry: ${entry_price:,.2f}")
        print(f"Stop: ${stop_loss:,.2f}")
        print(f"Risk per unit: ${risk_per_unit:,.2f}")
        print(f"Position size: {position_size:.6f} BTC")

        # Calculate profit at each TP
        profit_tp1 = (result.tp_levels.tp1 - entry_price) * position_size * 0.6
        profit_tp2 = (result.tp_levels.tp2 - entry_price) * position_size * 0.3
        profit_tp3 = (result.tp_levels.tp3 - entry_price) * position_size * 0.1
        total_profit = profit_tp1 + profit_tp2 + profit_tp3

        print(f"\n✅ Profit Potential:")
        print(f"   TP1 (60%): ${profit_tp1:,.2f}")
        print(f"   TP2 (30%): ${profit_tp2:,.2f}")
        print(f"   TP3 (10%): ${profit_tp3:,.2f}")
        print(f"   Total: ${total_profit:,.2f}")
        print(f"   Total R:R: {total_profit/max_risk:.2f}:1")

        return True
    else:
        print(f"\n❌ No TP calculated")
        return False


def main():
    """Run integration tests"""
    print("\n" + "="*70)
    print("TP CALCULATOR - INTEGRATION TEST SUITE")
    print("="*70)
    print("\nTesting with realistic BTC/USDT scenarios...")

    tests = [
        ("Realistic BUY TP", test_realistic_buy_tp),
        ("Realistic SELL TP", test_realistic_sell_tp),
        ("Position Sizing with TP", test_position_sizing_with_tp),
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
        print("\n✅ TP Calculator is ready for production use!")
        return 0
    else:
        print(f"\n❌ {total - passed} integration test(s) FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
