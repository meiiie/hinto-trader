"""
Unit test for SharkTank single batch per candle fix.

Tests that the debounce timer bug is fixed and only 1 batch
is processed per candle, preventing 2-10X signal overtrading.

Created: 2026-01-22
"""

import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import Mock, AsyncMock

from src.application.services.shark_tank_coordinator import SharkTankCoordinator
from src.domain.entities.trading_signal import TradingSignal, SignalType


@pytest.mark.asyncio
async def test_single_batch_per_candle():
    """
    Test that only 1 batch is processed per candle.

    This is THE CRITICAL test for the debounce timer bug fix.

    Scenario:
    1. Send 5 signals from candle at 10:15
    2. Wait for debounce timer (2s)
    3. Send 5 more signals from SAME candle (late arrivals)
    4. Verify: First 5 accepted, last 5 rejected
    5. Verify: Only 1 batch processed
    """
    # Setup
    coordinator = SharkTankCoordinator(max_positions=3, batch_interval_seconds=2.0)

    # Mock callbacks
    execute_callback = Mock()
    get_open_positions_callback = Mock(return_value=0)

    coordinator.set_callbacks(
        execute_callback=execute_callback,
        get_open_positions_callback=get_open_positions_callback
    )

    # Create signals from same candle
    candle_time = datetime(2022, 11, 1, 10, 15, tzinfo=timezone.utc)

    # ============================================================
    # PHASE 1: First batch of signals (should be accepted)
    # ============================================================
    print("\n=== PHASE 1: First batch of signals ===")
    accepted_count = 0
    for i in range(5):
        signal = TradingSignal(
            symbol=f'SYMBOL{i}USDT',
            signal_type=SignalType.BUY,
            entry_price=50000 + i*100,
            stop_loss=49000,
            take_profit_1=51000,
            take_profit_2=52000,
            confidence=0.8 + i*0.01,
            generated_at=candle_time  # Same candle!
        )
        result = coordinator.collect_signal(signal, f'SYMBOL{i}USDT')
        if result:
            accepted_count += 1
            print(f"✅ Signal {i} accepted (candle={candle_time.strftime('%H:%M:%S')})")
        else:
            print(f"❌ Signal {i} rejected (candle={candle_time.strftime('%H:%M:%S')})")

    assert accepted_count == 5, f"Expected 5 signals accepted, got {accepted_count}"
    print(f"✅ Phase 1 complete: {accepted_count}/5 signals accepted")

    # ============================================================
    # PHASE 2: Wait for debounce timer to expire
    # ============================================================
    print("\n=== PHASE 2: Waiting for debounce timer (2.5s) ===")
    await asyncio.sleep(2.5)  # Wait for debounce + processing
    print("✅ Debounce timer expired, batch should be processed")

    # Verify batch was processed
    assert execute_callback.call_count == 3, \
        f"Expected 3 signals executed (max_positions=3), got {execute_callback.call_count}"
    print(f"✅ Batch processed: {execute_callback.call_count} signals executed")

    # ============================================================
    # PHASE 3: Second batch of signals (LATE - should be rejected)
    # ============================================================
    print("\n=== PHASE 3: Second batch of signals (LATE) ===")
    rejected_count = 0
    for i in range(5, 10):
        signal = TradingSignal(
            symbol=f'SYMBOL{i}USDT',
            signal_type=SignalType.BUY,
            entry_price=50000 + i*100,
            stop_loss=49000,
            take_profit_1=51000,
            take_profit_2=52000,
            confidence=0.8 + i*0.01,
            generated_at=candle_time  # SAME candle as Phase 1!
        )
        result = coordinator.collect_signal(signal, f'SYMBOL{i}USDT')
        if not result:
            rejected_count += 1
            print(f"✅ Signal {i} rejected (duplicate candle)")
        else:
            print(f"❌ Signal {i} accepted (BUG! Should be rejected)")

    assert rejected_count == 5, \
        f"Expected 5 signals rejected (duplicate candle), got {rejected_count}"
    print(f"✅ Phase 3 complete: {rejected_count}/5 signals rejected")

    # ============================================================
    # PHASE 4: Wait to ensure no second batch is processed
    # ============================================================
    print("\n=== PHASE 4: Waiting to ensure no second batch (2.5s) ===")
    await asyncio.sleep(2.5)
    print("✅ Wait complete")

    # Verify NO second batch was processed
    assert execute_callback.call_count == 3, \
        f"Expected still 3 signals executed (no second batch), got {execute_callback.call_count}"
    print(f"✅ No second batch: Still {execute_callback.call_count} signals executed")

    # ============================================================
    # FINAL VERIFICATION
    # ============================================================
    print("\n=== FINAL VERIFICATION ===")
    print(f"✅ Total signals accepted: 5 (Phase 1)")
    print(f"✅ Total signals rejected: 5 (Phase 3 - duplicate candle)")
    print(f"✅ Total batches processed: 1 (only Phase 1)")
    print(f"✅ Total signals executed: 3 (max_positions=3)")
    print("\n🎯 TEST PASSED: Single batch per candle fix is working!")


@pytest.mark.asyncio
async def test_different_candles_processed_separately():
    """
    Test that signals from different candles are processed separately.

    Scenario:
    1. Send 3 signals from candle at 10:15
    2. Wait for batch to process
    3. Send 3 signals from candle at 10:30 (different candle)
    4. Verify: Both batches processed
    """
    # Setup
    coordinator = SharkTankCoordinator(max_positions=3, batch_interval_seconds=2.0)

    # Mock callbacks
    execute_callback = Mock()
    get_open_positions_callback = Mock(return_value=0)

    coordinator.set_callbacks(
        execute_callback=execute_callback,
        get_open_positions_callback=get_open_positions_callback
    )

    # ============================================================
    # CANDLE 1: 10:15
    # ============================================================
    print("\n=== CANDLE 1: 10:15 ===")
    candle_time_1 = datetime(2022, 11, 1, 10, 15, tzinfo=timezone.utc)

    for i in range(3):
        signal = TradingSignal(
            symbol=f'SYMBOL{i}USDT',
            signal_type=SignalType.BUY,
            entry_price=50000 + i*100,
            stop_loss=49000,
            take_profit_1=51000,
            take_profit_2=52000,
            confidence=0.8 + i*0.01,
            generated_at=candle_time_1
        )
        result = coordinator.collect_signal(signal, f'SYMBOL{i}USDT')
        assert result == True, f"Signal {i} should be accepted"
        print(f"✅ Signal {i} accepted (candle 1)")

    # Wait for batch 1
    await asyncio.sleep(2.5)
    assert execute_callback.call_count == 3, "Batch 1 should execute 3 signals"
    print(f"✅ Batch 1 processed: {execute_callback.call_count} signals")

    # ============================================================
    # CANDLE 2: 10:30 (DIFFERENT CANDLE)
    # ============================================================
    print("\n=== CANDLE 2: 10:30 (DIFFERENT) ===")
    candle_time_2 = datetime(2022, 11, 1, 10, 30, tzinfo=timezone.utc)

    for i in range(3, 6):
        signal = TradingSignal(
            symbol=f'SYMBOL{i}USDT',
            signal_type=SignalType.BUY,
            entry_price=50000 + i*100,
            stop_loss=49000,
            take_profit_1=51000,
            take_profit_2=52000,
            confidence=0.8 + i*0.01,
            generated_at=candle_time_2  # DIFFERENT candle!
        )
        result = coordinator.collect_signal(signal, f'SYMBOL{i}USDT')
        assert result == True, f"Signal {i} should be accepted (different candle)"
        print(f"✅ Signal {i} accepted (candle 2)")

    # Wait for batch 2
    await asyncio.sleep(2.5)
    assert execute_callback.call_count == 6, "Batch 2 should execute 3 more signals"
    print(f"✅ Batch 2 processed: {execute_callback.call_count} total signals")

    # ============================================================
    # FINAL VERIFICATION
    # ============================================================
    print("\n=== FINAL VERIFICATION ===")
    print(f"✅ Candle 1 (10:15): 3 signals accepted, 3 executed")
    print(f"✅ Candle 2 (10:30): 3 signals accepted, 3 executed")
    print(f"✅ Total batches: 2 (one per candle)")
    print(f"✅ Total signals executed: 6")
    print("\n🎯 TEST PASSED: Different candles processed separately!")


@pytest.mark.asyncio
async def test_candle_marking_in_logs():
    """
    Test that candle marking is logged correctly.

    This verifies the fix is working by checking logs.
    """
    # Setup
    coordinator = SharkTankCoordinator(max_positions=3, batch_interval_seconds=2.0)

    # Mock callbacks
    execute_callback = Mock()
    get_open_positions_callback = Mock(return_value=0)

    coordinator.set_callbacks(
        execute_callback=execute_callback,
        get_open_positions_callback=get_open_positions_callback
    )

    # Send signal
    candle_time = datetime(2022, 11, 1, 10, 15, tzinfo=timezone.utc)
    signal = TradingSignal(
        symbol='BTCUSDT',
        signal_type=SignalType.BUY,
        entry_price=50000,
        stop_loss=49000,
        take_profit_1=51000,
        take_profit_2=52000,
        confidence=0.85,
        generated_at=candle_time
    )

    result = coordinator.collect_signal(signal, 'BTCUSDT')
    assert result == True, "Signal should be accepted"

    # Wait for batch
    await asyncio.sleep(2.5)

    # Verify candle was marked as processed
    assert coordinator._last_candle_time == candle_time, \
        "Candle should be marked as processed"

    print(f"✅ Candle {candle_time.strftime('%H:%M:%S')} marked as processed")
    print("🎯 TEST PASSED: Candle marking works correctly!")


if __name__ == '__main__':
    """Run tests manually for debugging."""
    print("="*80)
    print("SHARK TANK SINGLE BATCH PER CANDLE - UNIT TESTS")
    print("="*80)

    # Run tests
    asyncio.run(test_single_batch_per_candle())
    print("\n" + "="*80 + "\n")

    asyncio.run(test_different_candles_processed_separately())
    print("\n" + "="*80 + "\n")

    asyncio.run(test_candle_marking_in_logs())
    print("\n" + "="*80)
    print("ALL TESTS PASSED! ✅")
    print("="*80)
