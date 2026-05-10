"""
Signal Generator Test Script

Tests the SignalGenerator with historical data to verify signal detection.
Run:
  python tests/test_signal_generator.py --symbol BTCUSDT --days 3
  python tests/test_signal_generator.py --top 10 --days 3
"""

import asyncio
import argparse
import logging
import httpx
import pytest
from datetime import datetime, timedelta
from typing import List

# Setup path
import sys
sys.path.insert(0, '.')

pytestmark = pytest.mark.skip(reason="diagnostic CLI script, not part of automated pytest suite")

from src.infrastructure.di_container import DIContainer
from src.infrastructure.data.historical_data_loader import HistoricalDataLoader
from src.domain.entities.candle import Candle

# Configure logging
logging.basicConfig(
    level=logging.WARNING,  # Reduce noise
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("SignalTest")


async def fetch_top_symbols(count: int = 10) -> List[str]:
    """Fetch top N trading pairs by volume from Binance."""
    print(f"\n🔍 Fetching top {count} volume pairs from Binance...")

    async with httpx.AsyncClient() as client:
        resp = await client.get("https://fapi.binance.com/fapi/v1/ticker/24hr")
        tickers = resp.json()

    # Filter USDT pairs and sort by volume
    usdt_pairs = [t for t in tickers if t['symbol'].endswith('USDT')]
    sorted_pairs = sorted(usdt_pairs, key=lambda x: float(x['quoteVolume']), reverse=True)

    top_symbols = [p['symbol'] for p in sorted_pairs[:count]]
    print(f"✅ Top {count}: {', '.join(top_symbols)}")
    return top_symbols


async def test_single_symbol(signal_generator, loader, symbol: str, days: int) -> dict:
    """Test signal generation for a single symbol."""

    # Fetch historical data
    from datetime import timezone
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)

    candles = await loader.load_candles(
        symbol=symbol,
        interval="1m",
        start_time=start_date,
        end_time=end_date
    )

    if not candles or len(candles) < 50:
        return {'symbol': symbol, 'candles': 0, 'signals': 0, 'error': 'Not enough candles'}

    # Simulate live signal generation
    signals_generated = []
    window_size = 100

    for i in range(50, len(candles)):
        start_idx = max(0, i - window_size)
        window = candles[start_idx:i+1]

        signal = signal_generator.generate_signal(
            candles=window,
            symbol=symbol,
            htf_bias='NEUTRAL'
        )

        if signal:
            signals_generated.append({
                'time': window[-1].timestamp,
                'type': signal.signal_type.value,
                'entry': signal.entry_price,
                'confidence': signal.confidence
            })

    buy_count = len([s for s in signals_generated if s['type'] == 'buy'])
    sell_count = len([s for s in signals_generated if s['type'] == 'sell'])

    return {
        'symbol': symbol,
        'candles': len(candles),
        'signals': len(signals_generated),
        'buy': buy_count,
        'sell': sell_count,
        'rate': len(signals_generated) / (len(candles) - 50) * 100 if len(candles) > 50 else 0
    }


async def test_signal_generator(symbols: List[str], days: int):
    """Test signal generator with historical data for multiple symbols."""
    print("=" * 70)
    print(f"🔬 SIGNAL GENERATOR TEST - {len(symbols)} SYMBOLS")
    print(f"Period: {days} days")
    print("=" * 70)

    # Initialize
    container = DIContainer()
    signal_generator = container.get_signal_generator()
    loader = HistoricalDataLoader()

    results = []
    total_signals = 0

    for i, symbol in enumerate(symbols):
        print(f"\n[{i+1}/{len(symbols)}] Testing {symbol}...", end=" ", flush=True)

        try:
            result = await test_single_symbol(signal_generator, loader, symbol, days)
            results.append(result)
            total_signals += result['signals']

            if result['signals'] > 0:
                print(f"✅ {result['signals']} signals ({result['buy']} BUY, {result['sell']} SELL)")
            else:
                print(f"❌ No signals")
        except Exception as e:
            print(f"❌ Error: {e}")
            results.append({'symbol': symbol, 'candles': 0, 'signals': 0, 'error': str(e)})

    # Summary
    print("\n" + "=" * 70)
    print("📊 SIGNAL GENERATION SUMMARY")
    print("=" * 70)
    print(f"{'Symbol':<15} {'Candles':>10} {'Signals':>10} {'BUY':>8} {'SELL':>8} {'Rate':>10}")
    print("-" * 70)

    for r in sorted(results, key=lambda x: x.get('signals', 0), reverse=True):
        if 'error' in r and r.get('candles', 0) == 0:
            print(f"{r['symbol']:<15} {'ERROR':>10}")
        else:
            print(f"{r['symbol']:<15} {r['candles']:>10} {r['signals']:>10} {r.get('buy', 0):>8} {r.get('sell', 0):>8} {r.get('rate', 0):>9.2f}%")

    print("-" * 70)
    print(f"{'TOTAL':<15} {'':<10} {total_signals:>10}")

    symbols_with_signals = len([r for r in results if r.get('signals', 0) > 0])
    print(f"\nSymbols with signals: {symbols_with_signals}/{len(symbols)}")

    if total_signals == 0:
        print("\n⚠️ NO SIGNALS GENERATED!")
        print("Possible reasons:")
        print("  1. Price not close enough to Swing Points (need < 1.5% distance)")
        print("  2. Market in ranging phase with no clear swing points")
        print("  3. Strategy is very selective (Liquidity Sniper)")

    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test Signal Generator")
    parser.add_argument("--symbol", type=str, help="Single symbol to test")
    parser.add_argument("--top", type=int, help="Test top N symbols by volume")
    parser.add_argument("--days", type=int, default=3, help="Days of history to test")

    args = parser.parse_args()

    async def main():
        if args.top:
            symbols = await fetch_top_symbols(args.top)
        elif args.symbol:
            symbols = [args.symbol.upper()]
        else:
            symbols = ["BTCUSDT"]  # Default

        await test_signal_generator(symbols, args.days)

    asyncio.run(main())
