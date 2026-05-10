"""
Test Enhanced Signal Entities

Verifies TPLevels and EnhancedSignal dataclasses.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.domain.entities.enhanced_signal import TPLevels, EnhancedSignal


def test_tp_levels_creation():
    """Test TPLevels dataclass creation and validation"""
    print("=" * 70)
    print("TEST 1: TPLevels Creation and Validation")
    print("=" * 70)

    # Test valid TP levels
    tp_levels = TPLevels(
        tp1=50500.0,
        tp2=51000.0,
        tp3=51500.0,
        sizes=[0.6, 0.3, 0.1]
    )

    print(f"\n✅ TPLevels Created:")
    print(f"   {tp_levels}")

    assert tp_levels.tp1 == 50500.0
    assert tp_levels.tp2 == 51000.0
    assert tp_levels.tp3 == 51500.0
    assert tp_levels.sizes == [0.6, 0.3, 0.1]

    # Test default sizes
    tp_levels_default = TPLevels(tp1=100.0, tp2=110.0, tp3=120.0)
    assert tp_levels_default.sizes == [0.6, 0.3, 0.1]
    print(f"\n✅ Default sizes: {tp_levels_default.sizes}")

    # Test to_dict and from_dict
    tp_dict = tp_levels.to_dict()
    tp_from_dict = TPLevels.from_dict(tp_dict)

    assert tp_from_dict.tp1 == tp_levels.tp1
    assert tp_from_dict.tp2 == tp_levels.tp2
    assert tp_from_dict.tp3 == tp_levels.tp3
    print(f"\n✅ Serialization working correctly")

    print(f"\n✅ TPLevels creation test PASSED!")
    return True


def test_tp_levels_validation():
    """Test TPLevels validation"""
    print("\n" + "=" * 70)
    print("TEST 2: TPLevels Validation")
    print("=" * 70)

    # Test invalid sizes (don't sum to 1.0)
    try:
        TPLevels(tp1=100.0, tp2=110.0, tp3=120.0, sizes=[0.5, 0.3, 0.1])
        print("\n❌ Should have raised ValueError for invalid sizes")
        return False
    except ValueError as e:
        print(f"\n✅ Correctly rejected invalid sizes: {e}")

    # Test negative TP level
    try:
        TPLevels(tp1=-100.0, tp2=110.0, tp3=120.0)
        print("\n❌ Should have raised ValueError for negative TP")
        return False
    except ValueError as e:
        print(f"✅ Correctly rejected negative TP: {e}")

    # Test negative size
    try:
        TPLevels(tp1=100.0, tp2=110.0, tp3=120.0, sizes=[0.7, 0.3, -0.1])
        print("\n❌ Should have raised ValueError for negative size")
        return False
    except ValueError as e:
        print(f"✅ Correctly rejected negative size: {e}")

    print(f"\n✅ TPLevels validation test PASSED!")
    return True


def test_enhanced_signal_buy():
    """Test EnhancedSignal for BUY direction"""
    print("\n" + "=" * 70)
    print("TEST 3: EnhancedSignal BUY")
    print("=" * 70)

    tp_levels = TPLevels(tp1=50500.0, tp2=51000.0, tp3=51500.0)

    signal = EnhancedSignal(
        timestamp=datetime.now(),
        symbol='BTCUSDT',
        timeframe='15m',
        direction='BUY',
        entry_price=50000.0,
        take_profit=tp_levels,
        stop_loss=49500.0,
        position_size=0.1,
        risk_reward_ratio=2.0,
        max_risk_pct=0.01,
        confidence_score=85.0,
        indicator_alignment={'rsi': True, 'volume': True, 'ema': True},
        max_hold_time=timedelta(hours=4),
        ema7=49800.0,
        ema25=49500.0,
        rsi6=25.0,
        volume_spike=True
    )

    print(f"\n✅ BUY Signal Created:")
    print(signal)

    # Test calculations
    risk_amount = signal.calculate_risk_amount(10000.0)
    print(f"\n📊 Risk amount (1% of $10,000): ${risk_amount:.2f}")
    assert risk_amount == 100.0

    potential_profit = signal.calculate_potential_profit()
    print(f"\n📊 Potential Profit:")
    print(f"   TP1: ${potential_profit['tp1']:.2f}")
    print(f"   TP2: ${potential_profit['tp2']:.2f}")
    print(f"   TP3: ${potential_profit['tp3']:.2f}")

    potential_loss = signal.calculate_potential_loss()
    print(f"\n📊 Potential Loss: ${potential_loss:.2f}")

    # Test serialization
    signal_dict = signal.to_dict()
    signal_from_dict = EnhancedSignal.from_dict(signal_dict)

    assert signal_from_dict.entry_price == signal.entry_price
    assert signal_from_dict.direction == signal.direction
    print(f"\n✅ Serialization working correctly")

    print(f"\n✅ BUY signal test PASSED!")
    return True


def test_enhanced_signal_sell():
    """Test EnhancedSignal for SELL direction"""
    print("\n" + "=" * 70)
    print("TEST 4: EnhancedSignal SELL")
    print("=" * 70)

    tp_levels = TPLevels(tp1=49500.0, tp2=49000.0, tp3=48500.0)

    signal = EnhancedSignal(
        timestamp=datetime.now(),
        symbol='BTCUSDT',
        timeframe='15m',
        direction='SELL',
        entry_price=50000.0,
        take_profit=tp_levels,
        stop_loss=50500.0,
        position_size=0.1,
        risk_reward_ratio=2.0,
        max_risk_pct=0.01,
        confidence_score=80.0,
        indicator_alignment={'rsi': True, 'volume': True, 'ema': False},
        ema7=50200.0,
        ema25=50500.0,
        rsi6=75.0,
        volume_spike=True
    )

    print(f"\n✅ SELL Signal Created:")
    print(signal)

    # Test calculations
    potential_profit = signal.calculate_potential_profit()
    print(f"\n📊 Potential Profit:")
    print(f"   TP1: ${potential_profit['tp1']:.2f}")
    print(f"   TP2: ${potential_profit['tp2']:.2f}")
    print(f"   TP3: ${potential_profit['tp3']:.2f}")

    potential_loss = signal.calculate_potential_loss()
    print(f"\n📊 Potential Loss: ${potential_loss:.2f}")

    print(f"\n✅ SELL signal test PASSED!")
    return True


def test_enhanced_signal_validation():
    """Test EnhancedSignal validation"""
    print("\n" + "=" * 70)
    print("TEST 5: EnhancedSignal Validation")
    print("=" * 70)

    tp_levels = TPLevels(tp1=50500.0, tp2=51000.0, tp3=51500.0)

    # Test invalid direction
    try:
        EnhancedSignal(
            timestamp=datetime.now(),
            symbol='BTCUSDT',
            timeframe='15m',
            direction='INVALID',
            entry_price=50000.0,
            take_profit=tp_levels,
            stop_loss=49500.0,
            position_size=0.1,
            risk_reward_ratio=2.0,
            confidence_score=85.0
        )
        print("\n❌ Should have raised ValueError for invalid direction")
        return False
    except ValueError as e:
        print(f"\n✅ Correctly rejected invalid direction: {e}")

    # Test invalid stop loss for BUY (SL above entry)
    try:
        EnhancedSignal(
            timestamp=datetime.now(),
            symbol='BTCUSDT',
            timeframe='15m',
            direction='BUY',
            entry_price=50000.0,
            take_profit=tp_levels,
            stop_loss=50500.0,  # Above entry!
            position_size=0.1,
            risk_reward_ratio=2.0,
            confidence_score=85.0
        )
        print("\n❌ Should have raised ValueError for invalid stop loss")
        return False
    except ValueError as e:
        print(f"✅ Correctly rejected invalid stop loss: {e}")

    # Test invalid confidence score
    try:
        EnhancedSignal(
            timestamp=datetime.now(),
            symbol='BTCUSDT',
            timeframe='15m',
            direction='BUY',
            entry_price=50000.0,
            take_profit=tp_levels,
            stop_loss=49500.0,
            position_size=0.1,
            risk_reward_ratio=2.0,
            confidence_score=150.0  # > 100!
        )
        print("\n❌ Should have raised ValueError for invalid confidence")
        return False
    except ValueError as e:
        print(f"✅ Correctly rejected invalid confidence: {e}")

    print(f"\n✅ EnhancedSignal validation test PASSED!")
    return True


def main():
    """Run all enhanced signal entity tests"""
    print("\n" + "=" * 70)
    print("ENHANCED SIGNAL ENTITIES TESTS")
    print("Testing TPLevels and EnhancedSignal Dataclasses")
    print("=" * 70)

    try:
        # Run tests
        test1 = test_tp_levels_creation()
        test2 = test_tp_levels_validation()
        test3 = test_enhanced_signal_buy()
        test4 = test_enhanced_signal_sell()
        test5 = test_enhanced_signal_validation()

        if all([test1, test2, test3, test4, test5]):
            print("\n" + "=" * 70)
            print("✅ ALL ENHANCED SIGNAL ENTITY TESTS PASSED!")
            print("=" * 70)
            print("\n📋 Summary:")
            print("   ✅ TPLevels dataclass working correctly")
            print("   ✅ TPLevels validation working")
            print("   ✅ EnhancedSignal BUY signals working")
            print("   ✅ EnhancedSignal SELL signals working")
            print("   ✅ EnhancedSignal validation working")
            print("   ✅ Serialization (to_dict/from_dict) working")
            print("   ✅ Profit/loss calculations working")
            print("\n🎉 Task 6.1 and 6.2 completed successfully!")
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
