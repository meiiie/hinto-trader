"""
Script to verify indicators against Binance data.

This script fetches real data from Binance and calculates indicators
to verify our implementation is correct.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.infrastructure.api.binance_rest_client import BinanceRestClient
from src.application.analysis.rsi_monitor import RSIMonitor
from src.infrastructure.indicators.talib_calculator import TALibCalculator
import pandas as pd


def main():
    print("=" * 60)
    print("INDICATOR VERIFICATION AGAINST BINANCE")
    print("=" * 60)

    # Initialize clients
    client = BinanceRestClient()
    rsi_monitor = RSIMonitor(period=6)
    talib_calc = TALibCalculator()

    # Fetch recent candles
    print("\n1. Fetching BTC/USDT 1m candles from Binance...")
    candles = client.get_klines(symbol='BTCUSDT', interval='1m', limit=100)

    if not candles:
        print("❌ Failed to fetch candles")
        return

    print(f"✅ Fetched {len(candles)} candles")

    # Latest candle
    latest = candles[-1]
    print(f"\n2. Latest Candle (1m):")
    print(f"   Time: {latest.timestamp}")
    print(f"   Open: ${latest.open:,.2f}")
    print(f"   High: ${latest.high:,.2f}")
    print(f"   Low: ${latest.low:,.2f}")
    print(f"   Close: ${latest.close:,.2f}")
    print(f"   Volume: {latest.volume:.2f} BTC")

    # Calculate 24h volume
    print(f"\n3. Volume Analysis:")
    print(f"   1m Volume (current candle): {latest.volume:.2f} BTC")

    # Get 24h data
    candles_24h = client.get_klines(symbol='BTCUSDT', interval='1m', limit=1440)  # 24h = 1440 minutes
    if candles_24h:
        volume_24h = sum(c.volume for c in candles_24h)
        print(f"   24h Volume (sum of 1440 candles): {volume_24h:,.2f} BTC")
        print(f"   ⚠️  Dashboard shows 1m volume, Binance shows 24h volume")

    # Calculate RSI(6) on 1m timeframe
    print(f"\n4. RSI(6) Analysis on 1m timeframe:")
    rsi_result = rsi_monitor.analyze(candles)
    if rsi_result:
        rsi_value = rsi_result['rsi']
        zone = rsi_result['zone']
        print(f"   RSI(6): {rsi_value:.2f}")
        print(f"   Zone: {zone.value}")
        print(f"   Is Oversold: {rsi_result['is_oversold']}")
        print(f"   Is Overbought: {rsi_result['is_overbought']}")
    else:
        print("   ❌ Failed to calculate RSI")

    # Compare with RSI(14) - Binance default
    print(f"\n5. RSI(14) Analysis (Binance default):")
    rsi_monitor_14 = RSIMonitor(period=14)
    rsi_result_14 = rsi_monitor_14.analyze(candles)
    if rsi_result_14:
        print(f"   RSI(14): {rsi_result_14['rsi']:.2f}")
        print(f"   Zone: {rsi_result_14['zone'].value}")

    # Calculate on different timeframes
    print(f"\n6. RSI(14) on different timeframes:")

    for interval, limit in [('5m', 100), ('15m', 100), ('1h', 100)]:
        candles_tf = client.get_klines(symbol='BTCUSDT', interval=interval, limit=limit)
        if candles_tf and len(candles_tf) >= 15:
            rsi_tf = rsi_monitor_14.analyze(candles_tf)
            if rsi_tf:
                print(f"   {interval}: RSI(14) = {rsi_tf['rsi']:.2f}")

    # EMA calculation
    print(f"\n7. EMA Analysis:")
    df = pd.DataFrame({
        'close': [c.close for c in candles],
        'open': [c.open for c in candles],
        'high': [c.high for c in candles],
        'low': [c.low for c in candles],
        'volume': [c.volume for c in candles]
    })

    result_df = talib_calc.calculate_all(df)

    if 'ema_7' in result_df.columns:
        ema_7 = result_df['ema_7'].iloc[-1]
        print(f"   EMA(7): ${ema_7:,.2f}")
    else:
        print("   ❌ EMA(7) not calculated")

    if 'ema_25' in result_df.columns:
        ema_25 = result_df['ema_25'].iloc[-1]
        print(f"   EMA(25): ${ema_25:,.2f}")
    else:
        print("   ❌ EMA(25) not calculated")

    if 'ema_99' in result_df.columns:
        ema_99 = result_df['ema_99'].iloc[-1]
        print(f"   EMA(99): ${ema_99:,.2f}")
    else:
        print("   ❌ EMA(99) not calculated")

    # Summary
    print(f"\n" + "=" * 60)
    print("SUMMARY - Differences from Binance:")
    print("=" * 60)
    print("1. Volume: Dashboard shows 1m candle volume, not 24h volume")
    print("2. RSI: Dashboard uses RSI(6) on 1m, Binance uses RSI(14) on various timeframes")
    print("3. EMA: Not implemented in dashboard yet")
    print("\nRecommendations:")
    print("- Add 24h volume calculation")
    print("- Add RSI(14) option or make period configurable")
    print("- Implement EMA display")
    print("- Add timeframe selector for indicators")
    print("=" * 60)


if __name__ == "__main__":
    main()
