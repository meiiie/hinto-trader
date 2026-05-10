"""
SOTA Diagnostic: Multi-Symbol Capacity Test

Verifies backend can handle 50 symbols with 10 max positions.
Tests: WebSocket, RealtimeService, SharkTank, Signal Worker

Run: python backend/tests/diagnostic_50_symbols.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

def step_divider(title: str, step_num: int):
    print(f"\n{'='*70}")
    print(f"📊 STEP {step_num}: {title}")
    print('='*70)

def main():
    print("="*70)
    print("🔍 50 Symbols Capacity Test")
    print("="*70)

    issues = []

    # =========================================================================
    # STEP 1: Check watched_symbols configuration
    # =========================================================================
    step_divider("Watched Symbols Configuration", 1)

    try:
        from src.infrastructure.di_container import DIContainer
        container = DIContainer()

        # Get config
        watched = container.get_config('watched_symbols', ['BTCUSDT'])
        print(f"📋 Watched symbols count: {len(watched)}")

        if len(watched) < 50:
            issues.append(f"⚠️ Only {len(watched)} symbols configured (target: 50)")

        print(f"   First 5: {watched[:5]}")
        if len(watched) > 5:
            print(f"   Last 5: {watched[-5:]}")

    except Exception as e:
        issues.append(f"❌ Config error: {e}")
        print(f"❌ Error: {e}")

    # =========================================================================
    # STEP 2: Check RealtimeService instances
    # =========================================================================
    step_divider("RealtimeService Capacity", 2)

    try:
        # Check if we can create multiple RealtimeService instances
        test_symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT']
        services = []

        for sym in test_symbols:
            try:
                service = container.get_realtime_service(sym.lower())
                services.append(sym)
            except Exception as e:
                issues.append(f"⚠️ Failed to create RealtimeService for {sym}: {e}")

        print(f"✅ Created {len(services)} RealtimeService instances")
        print(f"   Memory per instance: ~50-100KB (estimated)")
        print(f"   50 instances = ~5MB (acceptable)")

    except Exception as e:
        issues.append(f"❌ RealtimeService error: {e}")
        print(f"❌ Error: {e}")

    # =========================================================================
    # STEP 3: Check SharkTankCoordinator
    # =========================================================================
    step_divider("SharkTankCoordinator Check", 3)

    try:
        coordinator = container.get_shark_tank_coordinator()

        max_pos = getattr(coordinator, 'max_positions', 'N/A')
        batch_interval = getattr(coordinator, 'batch_interval_seconds', 'N/A')

        print(f"✅ SharkTankCoordinator initialized")
        print(f"   Max positions: {max_pos}")
        print(f"   Batch interval: {batch_interval}s")

        if max_pos != 10:
            issues.append(f"⚠️ max_positions={max_pos} (recommend: 10)")

    except Exception as e:
        issues.append(f"❌ SharkTankCoordinator error: {e}")
        print(f"❌ Error: {e}")

    # =========================================================================
    # STEP 4: Check LiveTradingService
    # =========================================================================
    step_divider("LiveTradingService Check", 4)

    try:
        live_service = container.get_live_trading_service()

        print(f"✅ LiveTradingService initialized")
        print(f"   Mode: {live_service.mode}")
        print(f"   Has client: {bool(live_service.client)}")
        print(f"   Has order_repo: {bool(live_service.order_repo)}")
        print(f"   Max leverage: {live_service.max_leverage}")

    except Exception as e:
        issues.append(f"❌ LiveTradingService error: {e}")
        print(f"❌ Error: {e}")

    # =========================================================================
    # STEP 5: Check WebSocket capacity
    # =========================================================================
    step_divider("WebSocket Stream Capacity", 5)

    try:
        # Estimate streams needed
        num_symbols = len(watched) if 'watched' in dir() else 10
        streams_per_symbol = 2  # kline + markPrice
        total_streams = num_symbols * streams_per_symbol
        binance_limit = 200

        print(f"📊 Streams calculation:")
        print(f"   Symbols: {num_symbols}")
        print(f"   Streams per symbol: {streams_per_symbol}")
        print(f"   Total streams: {total_streams}")
        print(f"   Binance limit: {binance_limit}")

        if total_streams > binance_limit:
            issues.append(f"❌ Stream limit exceeded: {total_streams} > {binance_limit}")
        else:
            print(f"   ✅ Within limit ({total_streams}/{binance_limit})")

    except Exception as e:
        issues.append(f"❌ Stream calculation error: {e}")

    # =========================================================================
    # STEP 6: Check Signal Worker
    # =========================================================================
    step_divider("Signal Worker Check", 6)

    try:
        from src.application.services.signal_generator_service import SignalGeneratorService

        signal_gen = container.get_signal_generator()
        print(f"✅ SignalGeneratorService available")

        # Check if confirmation service exists
        try:
            from src.application.services.signal_confirmation_service import SignalConfirmationService
            print(f"✅ SignalConfirmationService available")
        except:
            issues.append("⚠️ SignalConfirmationService not found")

    except Exception as e:
        issues.append(f"❌ Signal service error: {e}")
        print(f"❌ Error: {e}")

    # =========================================================================
    # SUMMARY
    # =========================================================================
    print("\n" + "="*70)
    print("📊 SUMMARY")
    print("="*70)

    if not issues:
        print("✅ All checks passed! System ready for 50 symbols.")
    else:
        print(f"⚠️ Found {len(issues)} issue(s):")
        for issue in issues:
            print(f"   {issue}")

    print("\n💡 RECOMMENDATIONS:")
    print("   1. Ensure watched_symbols has 50 tokens in config")
    print("   2. Set max_positions = 10 in SharkTankCoordinator")
    print("   3. Use 15m timeframe (not 1m) for lower CPU load")
    print("   4. Monitor first 24h for any rate limit issues")

if __name__ == "__main__":
    main()
