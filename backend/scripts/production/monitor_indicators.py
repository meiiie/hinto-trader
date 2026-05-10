#!/usr/bin/env python3
"""
Indicator Progression Monitor
Track the progression of technical indicators as data is collected
"""

import sys
import os
import time
from datetime import datetime

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.database import DatabaseManager


def monitor_indicator_progression():
    """Monitor indicator progression over time"""

    print("=" * 70)
    print("INDICATOR PROGRESSION MONITOR")
    print("=" * 70)
    print("\nMonitoring indicators as pipeline collects data...")
    print("Press Ctrl+C to stop\n")

    db = DatabaseManager()
    check_count = 0

    try:
        while True:
            check_count += 1
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            print(f"\n[Check #{check_count}] {timestamp}")
            print("-" * 70)

            # Get latest records
            df = db.get_latest_records('btc_15m', limit=30)
            total_records = len(df)

            if total_records == 0:
                print("No data in database yet. Waiting...")
                time.sleep(300)
                continue

            # Analyze each indicator
            print(f"\nTotal Records: {total_records}")
            print(f"Latest Price: ${df['close'].iloc[0]:,.2f}")

            # EMA(7) Analysis
            ema_valid = df['ema_7'].notna().sum()
            ema_pct = (ema_valid / total_records) * 100
            ema_status = "OK" if ema_pct > 50 else "Warmup"
            print(f"\nEMA(7):")
            print(f"  Valid: {ema_valid}/{total_records} ({ema_pct:.1f}%)")
            print(f"  Status: {ema_status}")
            if ema_valid > 0:
                latest_ema = df['ema_7'].dropna().iloc[0]
                print(f"  Latest: ${latest_ema:,.2f}")

            # RSI(6) Analysis
            rsi_valid = df['rsi_6'].notna().sum()
            rsi_pct = (rsi_valid / total_records) * 100
            rsi_status = "OK" if rsi_pct > 50 else "Warmup"
            print(f"\nRSI(6):")
            print(f"  Valid: {rsi_valid}/{total_records} ({rsi_pct:.1f}%)")
            print(f"  Status: {rsi_status}")
            if rsi_valid > 0:
                latest_rsi = df['rsi_6'].dropna().iloc[0]
                print(f"  Latest: {latest_rsi:.2f}")
                if latest_rsi < 30:
                    print(f"  Signal: OVERSOLD")
                elif latest_rsi > 70:
                    print(f"  Signal: OVERBOUGHT")

            # Volume MA(20) Analysis
            vma_valid = df['volume_ma_20'].notna().sum()
            vma_pct = (vma_valid / total_records) * 100
            vma_status = "OK" if vma_pct > 50 else "Warmup" if total_records < 20 else "Check"
            print(f"\nVolume MA(20):")
            print(f"  Valid: {vma_valid}/{total_records} ({vma_pct:.1f}%)")
            print(f"  Status: {vma_status}")
            if vma_valid > 0:
                latest_vma = df['volume_ma_20'].dropna().iloc[0]
                print(f"  Latest: {latest_vma:,.2f}")

            # Overall Status
            print(f"\n{'=' * 70}")
            if total_records >= 20 and rsi_valid > 10 and vma_valid > 10:
                print("STATUS: All indicators operational!")
                print("\nRecommendation: System is ready for analysis")
                break
            elif total_records >= 10 and rsi_valid > 5:
                print("STATUS: Core indicators working (RSI, EMA)")
                print(f"\nWaiting for Volume MA... Need {20 - total_records} more records")
            else:
                print("STATUS: Warmup period - collecting data")
                print(f"\nNeed ~{10 - total_records} more records for RSI")

            print(f"\nNext check in 5 minutes...")
            time.sleep(300)  # Check every 5 minutes

    except KeyboardInterrupt:
        print("\n\nMonitoring stopped by user")
    except Exception as e:
        print(f"\nError during monitoring: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 70)
    print("Monitor session ended")
    print("=" * 70)


if __name__ == "__main__":
    monitor_indicator_progression()
