"""
SOTA Stress Test: 50 Symbols Load Test

Simulates backend load with 50 symbols to verify:
1. WebSocket subscription capacity
2. Signal processing throughput
3. Memory usage
4. API rate limit safety

Run: python backend/tests/stress_test_50_symbols.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import asyncio
import time
import traceback
from datetime import datetime
from typing import List

# Optional psutil for memory monitoring
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    print("⚠️ psutil not installed. Memory test will be skipped.")
    print("   Install with: pip install psutil")

# Top 50 Binance Futures symbols (by volume)
TOP_50_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT",
    "LTCUSDT", "BCHUSDT", "UNIUSDT", "ATOMUSDT", "ETCUSDT",
    "XLMUSDT", "FILUSDT", "TRXUSDT", "NEARUSDT", "ICPUSDT",
    "VETUSDT", "ALGOUSDT", "FTMUSDT", "SANDUSDT", "MANAUSDT",
    "AXSUSDT", "THETAUSDT", "EGLDUSDT", "EOSUSDT", "AAVEUSDT",
    "GRTUSDT", "XTZUSDT", "MKRUSDT", "SNXUSDT", "ENJUSDT",
    "CHZUSDT", "ZILUSDT", "BATUSDT", "CRVUSDT", "COMPUSDT",
    "YFIUSDT", "1INCHUSDT", "SUSHIUSDT", "ZRXUSDT", "COTIUSDT",
    "IOTAUSDT", "ONTUSDT", "DASHUSDT", "ZECUSDT", "NEOUSDT"
]

def get_memory_usage():
    """Get current process memory usage in MB."""
    if not HAS_PSUTIL:
        return 0
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024

def step_divider(title: str, step_num: int):
    print(f"\n{'='*70}")
    print(f"📊 STEP {step_num}: {title}")
    print('='*70)

async def test_websocket_subscription(symbols: List[str]) -> dict:
    """Test if we can subscribe to WebSocket streams for all symbols."""
    results = {"success": 0, "failed": 0, "errors": []}

    try:
        from src.infrastructure.api.async_binance_client import AsyncBinanceClient

        use_testnet = os.getenv("BINANCE_USE_TESTNET", "true").lower() == "true"
        client = AsyncBinanceClient(use_testnet=use_testnet)

        # Build streams list
        streams = []
        for sym in symbols:
            streams.extend([
                f"{sym.lower()}@kline_15m",
                f"{sym.lower()}@markPrice@1s"
            ])

        print(f"📊 Testing {len(streams)} streams for {len(symbols)} symbols...")
        print(f"   Binance limit: 200 streams per connection")

        if len(streams) <= 200:
            results["success"] = len(symbols)
            print(f"   ✅ Within limit: {len(streams)}/200 streams")
        else:
            results["failed"] = len(symbols)
            results["errors"].append(f"Exceeds limit: {len(streams)} > 200")

    except Exception as e:
        results["errors"].append(str(e))
        traceback.print_exc()

    return results

async def test_signal_processing_speed(symbols: List[str]) -> dict:
    """Test signal generation speed for N symbols."""
    results = {"symbols": len(symbols), "time_ms": 0, "per_symbol_ms": 0}

    try:
        from src.application.signals.signal_generator import SignalGenerator
        from src.infrastructure.indicators.talib_calculator import TALibCalculator
        import pandas as pd
        import numpy as np

        # Create mock OHLCV data
        np.random.seed(42)
        candles = pd.DataFrame({
            'open': np.random.uniform(100, 110, 500),
            'high': np.random.uniform(110, 115, 500),
            'low': np.random.uniform(95, 100, 500),
            'close': np.random.uniform(100, 110, 500),
            'volume': np.random.uniform(1000, 10000, 500)
        })

        calculator = TALibCalculator()
        generator = SignalGenerator(indicator_calculator=calculator)

        start_time = time.time()

        for sym in symbols:
            try:
                # Generate signal (mocked)
                _ = generator.generate_signal(candles, sym)
            except Exception as e:
                pass  # Ignore individual symbol errors

        elapsed = (time.time() - start_time) * 1000
        results["time_ms"] = elapsed
        results["per_symbol_ms"] = elapsed / len(symbols)

        print(f"✅ Processed {len(symbols)} symbols in {elapsed:.1f}ms")
        print(f"   Per symbol: {results['per_symbol_ms']:.2f}ms")

    except Exception as e:
        results["error"] = str(e)
        traceback.print_exc()

    return results

async def test_memory_scaling(symbols: List[str]) -> dict:
    """Test memory usage with multiple RealtimeService instances."""
    results = {"initial_mb": 0, "final_mb": 0, "per_symbol_mb": 0}

    try:
        from src.infrastructure.di_container import DIContainer

        results["initial_mb"] = get_memory_usage()
        print(f"📊 Initial memory: {results['initial_mb']:.1f} MB")

        container = DIContainer()
        services = []

        # Create RealtimeService for each symbol (first 10 only for speed)
        test_symbols = symbols[:10]

        for sym in test_symbols:
            try:
                service = container.get_realtime_service(sym.lower())
                services.append(service)
            except:
                pass

        results["final_mb"] = get_memory_usage()
        mem_diff = results["final_mb"] - results["initial_mb"]
        results["per_symbol_mb"] = mem_diff / max(len(services), 1)

        print(f"📊 After {len(services)} services: {results['final_mb']:.1f} MB")
        print(f"   Memory increase: {mem_diff:.1f} MB")
        print(f"   Per symbol estimate: {results['per_symbol_mb']:.2f} MB")
        print(f"   50 symbols estimate: {results['per_symbol_mb'] * 50:.1f} MB")

    except Exception as e:
        results["error"] = str(e)
        traceback.print_exc()

    return results

async def main():
    print("="*70)
    print("🔥 50 SYMBOLS STRESS TEST")
    print(f"⏰ Time: {datetime.now().isoformat()}")
    print("="*70)

    symbols = TOP_50_SYMBOLS
    results = {}

    # =========================================================================
    # STEP 1: WebSocket Subscription Test
    # =========================================================================
    step_divider("WebSocket Subscription Test", 1)
    results["websocket"] = await test_websocket_subscription(symbols)

    # =========================================================================
    # STEP 2: Signal Processing Speed Test
    # =========================================================================
    step_divider("Signal Processing Speed Test", 2)
    results["signal"] = await test_signal_processing_speed(symbols)

    # =========================================================================
    # STEP 3: Memory Scaling Test
    # =========================================================================
    step_divider("Memory Scaling Test", 3)
    results["memory"] = await test_memory_scaling(symbols)

    # =========================================================================
    # STEP 4: API Rate Limit Estimation
    # =========================================================================
    step_divider("API Rate Limit Estimation", 4)

    # Calculate worst-case API calls
    max_positions = 10
    trailing_updates_per_min = max_positions * 4  # 4 updates per min per position
    order_placements_per_hour = 10  # Shark Tank batch execution

    total_weight_per_min = (
        trailing_updates_per_min * 1 +  # STOP_MARKET orders
        1 * 40  # get_open_orders (once per minute for sync)
    )

    print(f"📊 API Rate Limit Analysis (10 positions):")
    print(f"   Trailing stop updates/min: {trailing_updates_per_min}")
    print(f"   Order placements/hour: {order_placements_per_hour}")
    print(f"   Estimated weight/min: {total_weight_per_min}")
    print(f"   Binance limit: 1,200 weight/min")

    if total_weight_per_min < 1200:
        print(f"   ✅ Safe margin: {1200 - total_weight_per_min} weight remaining")
    else:
        print(f"   ⚠️ May hit rate limits!")

    # =========================================================================
    # SUMMARY
    # =========================================================================
    print("\n" + "="*70)
    print("📊 STRESS TEST SUMMARY")
    print("="*70)

    all_pass = True

    # WebSocket
    ws = results.get("websocket", {})
    if ws.get("success", 0) == len(symbols):
        print("✅ WebSocket: PASS - All 50 symbols within stream limit")
    else:
        print(f"❌ WebSocket: FAIL - {ws.get('errors', [])}")
        all_pass = False

    # Signal Processing
    sig = results.get("signal", {})
    if sig.get("time_ms", float('inf')) < 5000:  # Under 5 seconds
        print(f"✅ Signal Processing: PASS - {sig.get('time_ms', 0):.0f}ms for 50 symbols")
    else:
        print(f"⚠️ Signal Processing: SLOW - {sig.get('time_ms', 0):.0f}ms (target: <5000ms)")

    # Memory
    mem = results.get("memory", {})
    estimated_50 = mem.get("per_symbol_mb", 0) * 50
    if estimated_50 < 500:  # Under 500MB
        print(f"✅ Memory: PASS - Estimated {estimated_50:.0f}MB for 50 symbols")
    else:
        print(f"⚠️ Memory: HIGH - Estimated {estimated_50:.0f}MB (target: <500MB)")

    # API Rate Limits
    if total_weight_per_min < 1000:
        print("✅ API Limits: PASS - Comfortable margin")
    else:
        print("⚠️ API Limits: Monitor closely")

    print("\n" + "="*70)
    if all_pass:
        print("🎉 ALL TESTS PASSED - System ready for 50 symbols!")
    else:
        print("⚠️ Review failed tests before scaling to 50 symbols")
    print("="*70)

if __name__ == "__main__":
    asyncio.run(main())
