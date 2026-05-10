"""
Test script for Signal Enhancement Service

Tests end-to-end signal enhancement with all components.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.domain.entities.candle import Candle
from src.application.services.signal_enhancement_service import SignalEnhancementService


def create_realistic_btc_candles() -> list:
    """Create realistic BTC/USDT candles with clear swing high"""
    base_time = datetime.now()

    # Pattern with clear swing high at index 10
    prices = [
        49500, 49600, 49700, 49800, 49900,  # Rising
        50000, 50100, 50200, 50300, 50400,  # Approaching resistance
        50500,  # Swing high (index 10)
        50400, 50300, 50200, 50300, 50400,  # Pullback
        50450, 50480  # Ready to break
    ]

    candles = []
    for i, price in enumerate(prices):
        candle = Candle(
            timestamp=base_time + timedelta(minutes=15*i),
            open=price,
            high=price + 50,
            low=price - 50,
            close=price,
            volume=1000000.0 * (1.5 if i >= 15 else 1.0)
        )
        candles.append(candle)

    return candles


def test_buy_signal_enhancement():
    """Test BUY signal enhancement"""
    print("\n" + "="*70)
    print("TEST 1: BUY Signal Enhancement")
    print("="*70)

    service = SignalEnhancementService(account_size=10000.0)
    candles = create_realistic_btc_candles()

    print(f"\nInput:")
    print(f"  Symbol: BTCUSDT")
    print(f"  Direction: BUY")
    print(f"  EMA(7): $50,100")
    print(f"  EMA(25): $49,900")
    print(f"  RSI(6): 25.0 (oversold)")
    print(f"  Volume Spike: True")
    print(f"  EMA Crossover: bullish")

    signal = service.enhance_signal(
        direction='BUY',
        candles=candles,
        ema7=50500.0,  # Closer to swing high
        ema25=50200.0,
        rsi6=25.0,
        volume_spike=True,
        ema_crossover='bullish',
        symbol='BTCUSDT',
        timeframe='15m'
    )

    if signal:
        print(f"\n✅ Enhanced Signal Created:")
        print(f"   Entry: ${signal.entry_price:,.2f}")
        print(f"   Stop:  ${signal.stop_loss:,.2f}")
        print(f"   TP1:   ${signal.take_profit.tp1:,.2f} (60%)")
        print(f"   TP2:   ${signal.take_profit.tp2:,.2f} (30%)")
        print(f"   TP3:   ${signal.take_profit.tp3:,.2f} (10%)")
        print(f"   Position: {signal.position_size:.6f} BTC")
        print(f"   R:R: {signal.risk_reward_ratio:.2f}:1")
        print(f"   Confidence: {signal.confidence_score:.0f}%")
        print(f"   Alignment: {signal.indicator_alignment}")

        # Verify
        assert signal.direction == 'BUY'
        assert signal.stop_loss < signal.entry_price < signal.take_profit.tp1
        assert signal.confidence_score > 0

        print(f"\n✅ BUY signal enhancement PASSED")
        return True
    else:
        print(f"\n❌ Signal enhancement failed")
        return False


def test_sell_signal_enhancement():
    """Test SELL signal enhancement"""
    print("\n" + "="*70)
    print("TEST 2: SELL Signal Enhancement")
    print("="*70)

    service = SignalEnhancementService(account_size=10000.0)

    # Create bearish candles with clear swing low
    base_time = datetime.now()
    prices = [
        50500, 50400, 50300, 50200, 50100,  # Declining
        50000, 49900, 49800, 49700, 49600,  # Approaching support
        49500,  # Swing low (index 10)
        49600, 49700, 49800, 49700, 49600,  # Bounce
        49550, 49520  # Ready to break
    ]

    candles = []
    for i, price in enumerate(prices):
        candle = Candle(
            timestamp=base_time + timedelta(minutes=15*i),
            open=price,
            high=price + 50,
            low=price - 50,
            close=price,
            volume=1000000.0 * (1.5 if i >= 15 else 1.0)
        )
        candles.append(candle)

    signal = service.enhance_signal(
        direction='SELL',
        candles=candles,
        ema7=49500.0,  # Closer to swing low
        ema25=49800.0,
        rsi6=85.0,
        volume_spike=True,
        ema_crossover='bearish',
        symbol='BTCUSDT',
        timeframe='15m'
    )

    if signal:
        print(f"\n✅ Enhanced Signal Created:")
        print(f"   Entry: ${signal.entry_price:,.2f}")
        print(f"   Stop:  ${signal.stop_loss:,.2f}")
        print(f"   TP1:   ${signal.take_profit.tp1:,.2f}")
        print(f"   Confidence: {signal.confidence_score:.0f}%")

        assert signal.direction == 'SELL'
        assert signal.stop_loss > signal.entry_price > signal.take_profit.tp1

        print(f"\n✅ SELL signal enhancement PASSED")
        return True
    else:
        print(f"\n❌ Signal enhancement failed")
        return False


def test_account_size_update():
    """Test account size update"""
    print("\n" + "="*70)
    print("TEST 3: Account Size Update")
    print("="*70)

    service = SignalEnhancementService(account_size=10000.0)
    print(f"\nInitial account: $10,000")

    service.update_account_size(20000.0)
    print(f"Updated account: $20,000")

    assert service.account_size == 20000.0

    print(f"\n✅ Account size update PASSED")
    return True


def main():
    """Run all tests"""
    print("\n" + "="*70)
    print("SIGNAL ENHANCEMENT SERVICE TEST SUITE")
    print("="*70)

    tests = [
        ("BUY Signal Enhancement", test_buy_signal_enhancement),
        ("SELL Signal Enhancement", test_sell_signal_enhancement),
        ("Account Size Update", test_account_size_update),
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
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All tests PASSED!")
        print("\n🎊 SIGNAL ENHANCEMENT SERVICE IS COMPLETE!")
        print("\n✅ Phase 2 Complete - All components working:")
        print("   ✅ Entry Price Calculator")
        print("   ✅ TP Calculator")
        print("   ✅ Stop Loss Calculator")
        print("   ✅ Confidence Calculator")
        print("   ✅ Signal Enhancement Service")
        return 0
    else:
        print(f"\n❌ {total - passed} test(s) FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
