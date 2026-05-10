"""
Performance Profiler: Testnet API Latency Analysis

This script measures the latency of each Binance Testnet API call
to identify which calls are causing slowness.

Expected findings:
- Testnet is hosted in different region = higher latency
- Multiple sequential calls add up
- Some endpoints are slower than others
"""

import time
import os
import sys
from typing import Dict, List
from dataclasses import dataclass
from statistics import mean, stdev

# Add backend to path
backend_path = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, backend_path)

# Load .env
from dotenv import load_dotenv
env_paths = [
    os.path.join(backend_path, '.env'),
    os.path.join(backend_path, '..', '.env'),
]
for p in env_paths:
    if os.path.exists(p):
        load_dotenv(p)
        break

os.environ['BINANCE_USE_TESTNET'] = 'true'
os.environ['ENV'] = 'testnet'


@dataclass
class APICallResult:
    name: str
    latency_ms: float
    success: bool
    error: str = ""


def measure_call(name: str, func, *args, **kwargs) -> APICallResult:
    """Measure latency of a single API call."""
    start = time.perf_counter()
    try:
        result = func(*args, **kwargs)
        elapsed = (time.perf_counter() - start) * 1000
        return APICallResult(name, elapsed, True)
    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000
        return APICallResult(name, elapsed, False, str(e))


def run_benchmark():
    """Run comprehensive API latency benchmark."""
    print("\n" + "="*70)
    print("TESTNET API LATENCY PROFILER")
    print("="*70)

    from src.infrastructure.api.binance_futures_client import BinanceFuturesClient

    print("\nInitializing Testnet client...")
    start = time.perf_counter()
    client = BinanceFuturesClient(use_testnet=True)
    init_time = (time.perf_counter() - start) * 1000
    print(f"Client init: {init_time:.0f}ms")

    results: List[APICallResult] = []

    # Test each API call 3 times
    tests = [
        ("1. ping()", lambda: client.ping()),
        ("2. get_server_time()", lambda: client.get_server_time()),
        ("3. get_account_balance()", lambda: client.get_account_balance()),
        ("4. get_usdt_balance()", lambda: client.get_usdt_balance()),
        ("5. get_positions()", lambda: client.get_positions()),
        ("6. get_open_orders()", lambda: client.get_open_orders()),
        ("7. get_ticker_price('BTCUSDT')", lambda: client.get_ticker_price("BTCUSDT")),
        ("8. get_exchange_info()", lambda: client.get_exchange_info()),
    ]

    print("\n" + "-"*70)
    print(f"{'API Call':<40} {'Run 1':>8} {'Run 2':>8} {'Run 3':>8} {'Avg':>8}")
    print("-"*70)

    for name, func in tests:
        runs = []
        for _ in range(3):
            r = measure_call(name, func)
            runs.append(r)
            results.append(r)
            time.sleep(0.1)  # Small delay between calls

        latencies = [r.latency_ms for r in runs]
        avg = mean(latencies)

        status = "✅" if all(r.success for r in runs) else "❌"
        print(f"{status} {name:<38} {latencies[0]:>7.0f}ms {latencies[1]:>7.0f}ms {latencies[2]:>7.0f}ms {avg:>7.0f}ms")

    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)

    all_latencies = [r.latency_ms for r in results]
    print(f"Total API calls: {len(results)}")
    print(f"Average latency: {mean(all_latencies):.0f}ms")
    print(f"Min latency: {min(all_latencies):.0f}ms")
    print(f"Max latency: {max(all_latencies):.0f}ms")
    print(f"Std deviation: {stdev(all_latencies):.0f}ms")

    # Identify slowest
    print("\n🐌 SLOWEST CALLS (potential bottlenecks):")
    for r in sorted(results, key=lambda x: x.latency_ms, reverse=True)[:5]:
        print(f"   {r.latency_ms:>7.0f}ms - {r.name}")

    # Simulate portfolio load
    print("\n" + "="*70)
    print("SIMULATING PORTFOLIO LOAD (like /trades/portfolio)")
    print("="*70)

    start = time.perf_counter()

    t1 = time.perf_counter()
    client.get_account_balance()
    t2 = time.perf_counter()
    client.get_positions()
    t3 = time.perf_counter()
    client.get_open_orders()
    t4 = time.perf_counter()

    print(f"get_account_balance(): {(t2-t1)*1000:.0f}ms")
    print(f"get_positions():       {(t3-t2)*1000:.0f}ms")
    print(f"get_open_orders():     {(t4-t3)*1000:.0f}ms")
    print(f"─────────────────────────────")
    print(f"TOTAL SEQUENTIAL:      {(t4-start)*1000:.0f}ms")

    # Parallel simulation (what async could achieve)
    print("\n💡 OPTIMIZATION SUGGESTION:")
    max_single = max((t2-t1), (t3-t2), (t4-t3)) * 1000
    print(f"If parallel: ~{max_single:.0f}ms (instead of {(t4-start)*1000:.0f}ms)")
    print(f"Potential speedup: {((t4-start)*1000) / max_single:.1f}x")


if __name__ == "__main__":
    run_benchmark()
