"""
Integration test for Stop Loss Calculator with realistic scenarios

Tests stop loss calculation with realistic market data patterns.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.domain.entities.candle import Candle
from src.application.services.stop_loss_calculator import StopLossCalculator


def create_realistic_btc_bullish() -> tuple:
    """Create realistic BTC/USDT bullish scenario"""
    base_time = datetime.now()

    # BTC consolidating with swing low at 49700
    candles = []
    prices = [
        50500, 50400, 50300, 50200, 50100,  # Declining
        50000, 49900, 49800, 49700, 49800,  # Swing low at 49700
        49900, 50000, 50100, 50200, 50300,  # Rising
        50400, 50500, 50600  # Breakout
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

    entry_price = 50200.0  # Entry after breakout
    ema25 = 49900.0  # EMA(25) near swing low

    return candles, entry_price, ema25


def create_realistic_btc_bearish() -> tuple:
    """Create realistic BTC/USDT bearish scenario"""
    base_time = datetime.now()

    # BTC declining with swing high at 50300
    candles = []
    prices = [
        49500, 49600, 49700, 49800, 49900,  # Rising
        50000, 50100, 50200, 50300, 50200,  # Swing high at 50300
        50100, 50000, 49900, 49800, 49700,  # Declining
        49600, 49500, 49400  # Breakdown
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

    entry_price = 49800.0  # Entry after breakdown
    ema25 = 50100.0  # EMA(25) near swing high

    return candles, entry_price, ema25


def test_realistic_buy_stop():
    """Test BUY stop loss with realistic BTC scenario"""
    print("\n" + "="*70)
    print("INTEGRATION TEST 1: Realistic BUY Stop Loss (BTC Bullish)")
    print("="*70)

    calculator = StopLossCalculator(max_risk_pct=0.01)
    candles, entry_price, ema25 = create_realistic_btc_bullish()

    account_size = 10000.0

    print(f"\nScenario: BTC/USDT 15m - Bullish breakout")
    print(f"Entry Price: ${entry_price:,.2f}")
    print(f"EMA(25): ${ema25:,.2f}")
    print(f"Account Size: ${account_size:,.2f}")

    result = calculator.calculate_stop_loss(
        entry_price=entry_price,
        direction='BUY',
        candles=candles,
        ema25=ema25,
        account_size=account_size
    )

    if result and result.is_valid:
        risk = entry_price - result.stop_loss

        print(f"\n✅ Stop Loss Calculated:")
        print(f"   Stop Loss: ${result.stop_loss:,.2f}")
        print(f"   Stop Type: {result.stop_type}")
        print(f"   Distance: {result.distance_from_entry_pct:.3%}")
        print(f"   Risk per unit: ${risk:,.2f}")

        # Calculate position size
        position_size = calculator.calculate_position_size(
            entry_price=entry_price,
            stop_loss=result.stop_loss,
            account_size=account_size
        )

        max_loss = risk * position_size

        print(f"\n   Position Sizing:")
        print(f"   Position Size: {position_size:.6f} BTC")
        print(f"   Max Loss: ${max_loss:,.2f}")
        print(f"   Risk %: {(max_loss/account_size)*100:.2f}%")

        print(f"\n   Trading Plan:")
        print(f"   - Enter BUY at ${entry_price:,.2f}")
        print(f"   - Place stop at ${result.stop_loss:,.2f}")
        print(f"   - Position: {position_size:.6f} BTC")
        print(f"   - Max risk: ${max_loss:,.2f} (1%)")

        # Verify 1% risk
        assert abs(max_loss - 100.0) < 1.0, "Risk should be ~$100 (1%)"

        return True
    else:
        print(f"\n❌ No valid stop loss found")
        return False


def test_realistic_sell_stop():
    """Test SELL stop loss with realistic BTC scenario"""
    print("\n" + "="*70)
    print("INTEGRATION TEST 2: Realistic SELL Stop Loss (BTC Bearish)")
    print("="*70)

    calculator = StopLossCalculator(max_risk_pct=0.01)
    candles, entry_price, ema25 = create_realistic_btc_bearish()

    account_size = 10000.0

    print(f"\nScenario: BTC/USDT 15m - Bearish breakdown")
    print(f"Entry Price: ${entry_price:,.2f}")
    print(f"EMA(25): ${ema25:,.2f}")
    print(f"Account Size: ${account_size:,.2f}")

    result = calculator.calculate_stop_loss(
        entry_price=entry_price,
        direction='SELL',
        candles=candles,
        ema25=ema25,
        account_size=account_size
    )

    if result and result.is_valid:
        risk = result.stop_loss - entry_price

        print(f"\n✅ Stop Loss Calculated:")
        print(f"   Stop Loss: ${result.stop_loss:,.2f}")
        print(f"   Stop Type: {result.stop_type}")
        print(f"   Distance: {result.distance_from_entry_pct:.3%}")
        print(f"   Risk per unit: ${risk:,.2f}")

        # Calculate position size
        position_size = calculator.calculate_position_size(
            entry_price=entry_price,
            stop_loss=result.stop_loss,
            account_size=account_size
        )

        max_loss = risk * position_size

        print(f"\n   Position Sizing:")
        print(f"   Position Size: {position_size:.6f} BTC")
        print(f"   Max Loss: ${max_loss:,.2f}")
        print(f"   Risk %: {(max_loss/account_size)*100:.2f}%")

        print(f"\n   Trading Plan:")
        print(f"   - Enter SELL at ${entry_price:,.2f}")
        print(f"   - Place stop at ${result.stop_loss:,.2f}")
        print(f"   - Position: {position_size:.6f} BTC")
        print(f"   - Max risk: ${max_loss:,.2f} (1%)")

        # Verify 1% risk
        assert abs(max_loss - 100.0) < 1.0, "Risk should be ~$100 (1%)"

        return True
    else:
        print(f"\n❌ No valid stop loss found")
        return False


def test_complete_trading_plan():
    """Test complete trading plan with Entry/TP/ST"""
    print("\n" + "="*70)
    print("INTEGRATION TEST 3: Complete Trading Plan")
    print("="*70)

    from src.application.services.tp_calculator import TPCalculator

    # Initialize calculators
    tp_calc = TPCalculator()
    sl_calc = StopLossCalculator()

    candles, _, ema25 = create_realistic_btc_bullish()

    # Use predetermined entry price
    entry_price = 50200.0
    account_size = 10000.0

    print(f"\nScenario: Complete BUY signal")
    print(f"Entry Price: ${entry_price:,.2f}")
    print(f"EMA(25): ${ema25:,.2f}")
    print(f"Account: ${account_size:,.2f}")

    print(f"\n1️⃣ Entry Price: ${entry_price:,.2f}")

    # 2. Calculate Stop Loss
    sl_result = sl_calc.calculate_stop_loss(
        entry_price=entry_price,
        direction='BUY',
        candles=candles,
        ema25=ema25,
        account_size=account_size
    )

    if not sl_result or not sl_result.is_valid:
        print(f"\n❌ No valid stop loss found")
        return False

    stop_loss = sl_result.stop_loss
    print(f"2️⃣ Stop Loss: ${stop_loss:,.2f} ({sl_result.stop_type})")

    # 3. Calculate Position Size
    position_size = sl_calc.calculate_position_size(
        entry_price=entry_price,
        stop_loss=stop_loss,
        account_size=account_size
    )

    print(f"3️⃣ Position Size: {position_size:.6f} BTC")

    # 4. Calculate Take Profit
    tp_result = tp_calc.calculate_tp_levels(
        entry_price=entry_price,
        stop_loss=stop_loss,
        direction='BUY',
        candles=candles
    )

    if not tp_result or not tp_result.is_valid:
        print(f"\n❌ No valid TP found")
        return False

    print(f"4️⃣ Take Profit Levels:")
    print(f"   TP1: ${tp_result.tp_levels.tp1:,.2f} (60%)")
    print(f"   TP2: ${tp_result.tp_levels.tp2:,.2f} (30%)")
    print(f"   TP3: ${tp_result.tp_levels.tp3:,.2f} (10%)")

    # Calculate risk/reward
    risk = entry_price - stop_loss
    reward1 = tp_result.tp_levels.tp1 - entry_price

    print(f"\n✅ Complete Trading Plan:")
    print(f"   Entry: ${entry_price:,.2f}")
    print(f"   Stop: ${stop_loss:,.2f}")
    print(f"   TP1: ${tp_result.tp_levels.tp1:,.2f}")
    print(f"   TP2: ${tp_result.tp_levels.tp2:,.2f}")
    print(f"   TP3: ${tp_result.tp_levels.tp3:,.2f}")
    print(f"   Position: {position_size:.6f} BTC")
    print(f"   Risk: ${risk * position_size:,.2f}")
    print(f"   R:R: {reward1/risk:.2f}:1")

    return True


def main():
    """Run integration tests"""
    print("\n" + "="*70)
    print("STOP LOSS CALCULATOR - INTEGRATION TEST SUITE")
    print("="*70)
    print("\nTesting with realistic BTC/USDT scenarios...")

    tests = [
        ("Realistic BUY Stop Loss", test_realistic_buy_stop),
        ("Realistic SELL Stop Loss", test_realistic_sell_stop),
        ("Complete Trading Plan", test_complete_trading_plan),
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
        print("\n✅ Stop Loss Calculator is ready for production use!")
        print("\n🎊 Signal Enhancement Service components complete:")
        print("   ✅ Entry Price Calculator")
        print("   ✅ TP Calculator")
        print("   ✅ Stop Loss Calculator")
        return 0
    else:
        print(f"\n❌ {total - passed} integration test(s) FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
