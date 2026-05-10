#!/usr/bin/env python3
"""
Quick status check for Binance Data Pipeline
Shows database stats and latest records
"""

import sys
import os
from datetime import datetime

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.database import DatabaseManager


def main():
    """Check pipeline status"""
    print("=" * 60)
    print("Pipeline Status Check")
    print("=" * 60)

    db = DatabaseManager()

    # Check btc_15m
    print("\n[BTC/USDT 15m]")
    info_15m = db.get_table_info('btc_15m')
    print(f"  Records: {info_15m['record_count']}")
    print(f"  Size: {info_15m['size_mb']:.2f} MB")
    if info_15m['latest_record']:
        print(f"  Latest: {info_15m['latest_record']}")

    # Check btc_1h
    print("\n[BTC/USDT 1h]")
    info_1h = db.get_table_info('btc_1h')
    print(f"  Records: {info_1h['record_count']}")
    print(f"  Size: {info_1h['size_mb']:.2f} MB")
    if info_1h['latest_record']:
        print(f"  Latest: {info_1h['latest_record']}")

    # Show latest price
    if info_15m['record_count'] > 0:
        latest = db.get_latest_records('btc_15m', limit=1)
        if not latest.empty:
            print("\n[Latest Price]")
            print(f"  Close: ${latest['close'].iloc[0]:,.2f}")
            print(f"  Volume: {latest['volume'].iloc[0]:,.2f}")
            if not pd.isna(latest['ema_7'].iloc[0]):
                print(f"  EMA(7): ${latest['ema_7'].iloc[0]:,.2f}")
            if not pd.isna(latest['rsi_6'].iloc[0]):
                print(f"  RSI(6): {latest['rsi_6'].iloc[0]:.2f}")

    print("\n" + "=" * 60)
    print(f"Checked at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)


if __name__ == "__main__":
    import pandas as pd
    main()
