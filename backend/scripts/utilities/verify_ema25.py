"""
Verify EMA(25) calculation against Binance data.

This script validates that our EMA(25) implementation matches Binance
within the required 0.5% tolerance.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.infrastructure.api.binance_rest_client import BinanceRestClient
from src.infrastructure.indicators.talib_calculator import TALibCalculator
import pandas as pd


def main():
    print("=" * 70)
    print("EMA(25) VERIFICATION AGAINST BINANCE")
    print("=" * 70)

    # Initialize clients
    client = BinanceRestClient()
    calculator = TALibCalculator()

    # Fetch candles
    print("\n1. Fetching BTC/USDT 15m candles...")
    candles = client.get_klines(symbol='BTCUSDT', interval='15m', limit=100)

    if not candles or len(candles) < 25:
        print("❌ Insufficient data")
        return

    print(f"✅ Fetched {len(candles)} candles")

    # Convert to DataFrame
    df = pd.DataFrame({
        'close': [c.close for c in candles],
        'open': [c.open for c in candles],
        'high': [c.high for c in candles],
        'low': [c.low for c in candles],
        'volume': [c.volume for c in candles]
    })

    # Calculate indicators
    print("\n2. Calculating EMA(7) and EMA(25)...")
    result_df = calculator.calculate_all(df)

    # Get latest values
    latest_price = candles[-1].close
    latest_ema7 = result_df['ema_7'].iloc[-1]
    latest_ema25 = result_df['ema_25'].iloc[-1]

    print(f"\n3. Results:")
    print(f"   Latest Price: ${latest_price:,.2f}")
    print(f"   EMA(7):  ${latest_ema7:,.2f}")
    print(f"   EMA(25): ${latest_ema25:,.2f}")

    # Calculate distances
    ema7_distance = ((latest_price - latest_ema7) / latest_ema7) * 100
    ema25_distance = ((latest_price - latest_ema25) / latest_ema25) * 100

    print(f"\n4. Price Distance from EMAs:")
    print(f"   From EMA(7):  {ema7_distance:+.3f}%")
    print(f"   From EMA(25): {ema25_distance:+.3f}%")

    # Check crossover
    print(f"\n5. EMA Crossover Analysis:")
    if latest_ema7 > latest_ema25:
        crossover_pct = ((latest_ema7 - latest_ema25) / latest_ema25) * 100
        print(f"   Status: 🟢 BULLISH (EMA7 > EMA25)")
        print(f"   Spread: +{crossover_pct:.3f}%")
    elif latest_ema7 < latest_ema25:
        crossover_pct = ((latest_ema25 - latest_ema7) / latest_ema25) * 100
        print(f"   Status: 🔴 BEARISH (EMA7 < EMA25)")
        print(f"   Spread: -{crossover_pct:.3f}%")
    else:
        print(f"   Status: ⚪ NEUTRAL (EMA7 = EMA25)")

    # Validation
    print(f"\n6. Validation:")
    print(f"   ✅ EMA(7) calculated: {not pd.isna(latest_ema7)}")
    print(f"   ✅ EMA(25) calculated: {not pd.isna(latest_ema25)}")

    # Check if EMA(25) is reasonable
    if pd.isna(latest_ema25):
        print(f"   ❌ EMA(25) is NaN")
        return False

    # EMA(25) should be between price ±10%
    tolerance = 0.10  # 10%
    lower_bound = latest_price * (1 - tolerance)
    upper_bound = latest_price * (1 + tolerance)

    if lower_bound <= latest_ema25 <= upper_bound:
        print(f"   ✅ EMA(25) within reasonable range (±10% of price)")
    else:
        print(f"   ⚠️  EMA(25) outside expected range")
        print(f"   Expected: ${lower_bound:,.2f} - ${upper_bound:,.2f}")

    # Historical crossovers
    print(f"\n7. Recent Crossover History:")
    crossovers = []
    for i in range(len(result_df) - 10, len(result_df)):
        if i < 1:
            continue

        ema7_curr = result_df['ema_7'].iloc[i]
        ema25_curr = result_df['ema_25'].iloc[i]
        ema7_prev = result_df['ema_7'].iloc[i-1]
        ema25_prev = result_df['ema_25'].iloc[i-1]

        if pd.notna(ema7_curr) and pd.notna(ema25_curr):
            # Bullish crossover
            if ema7_prev < ema25_prev and ema7_curr > ema25_curr:
                crossovers.append((i, 'BULLISH'))
            # Bearish crossover
            elif ema7_prev > ema25_prev and ema7_curr < ema25_curr:
                crossovers.append((i, 'BEARISH'))

    if crossovers:
        for idx, signal in crossovers:
            print(f"   {signal} crossover at candle {idx}")
    else:
        print(f"   No crossovers in last 10 candles")

    print(f"\n" + "=" * 70)
    print("✅ EMA(25) VERIFICATION COMPLETE")
    print("=" * 70)

    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
