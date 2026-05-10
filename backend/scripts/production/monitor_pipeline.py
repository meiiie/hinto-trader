"""
Monitor pipeline status and display statistics.

Shows real-time statistics about data collection.
"""

import sys
import os
import time
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import DatabaseManager
from src.validator import DataValidator


def clear_screen():
    """Clear console screen."""
    os.system('cls' if os.name == 'nt' else 'clear')


def main():
    """Main monitoring loop."""
    db_manager = DatabaseManager()
    validator = DataValidator(db_manager)

    print("=" * 70)
    print("BINANCE DATA PIPELINE - MONITOR")
    print("=" * 70)
    print("\nPress Ctrl+C to stop monitoring\n")

    try:
        while True:
            clear_screen()

            print("=" * 70)
            print(f"PIPELINE MONITOR - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print("=" * 70)
            print()

            # Get status for both tables
            for table_name in ['btc_15m', 'btc_1h']:
                print(f"📊 {table_name.upper()}")
                print("-" * 70)

                try:
                    info = db_manager.get_table_info(table_name)

                    print(f"  Records: {info['record_count']}")
                    print(f"  Size: {info['size_mb']} MB")

                    if info['earliest_record']:
                        print(f"  Earliest: {info['earliest_record']}")
                        print(f"  Latest: {info['latest_record']}")

                    # Get latest record details
                    if info['record_count'] > 0:
                        latest = db_manager.get_latest_records(table_name, limit=1)
                        if not latest.empty:
                            row = latest.iloc[0]
                            print(f"\n  Latest Data:")
                            print(f"    Close: ${row['close']:,.2f}")
                            print(f"    Volume: {row['volume']:,.2f}")
                            if not pd.isna(row['rsi_6']):
                                print(f"    RSI(6): {row['rsi_6']:.2f}")
                            if not pd.isna(row['ema_7']):
                                print(f"    EMA(7): ${row['ema_7']:,.2f}")

                    print()

                except Exception as e:
                    print(f"  Error: {e}")
                    print()

            # Show update info
            print("=" * 70)
            print("Pipeline Info:")
            print(f"  Next update: Every 15 minutes")
            print(f"  Database: crypto_data.db")
            print(f"  Logs: documents/logs/pipeline_{datetime.now().strftime('%Y%m%d')}.log")
            print("=" * 70)
            print("\nRefreshing in 30 seconds... (Ctrl+C to stop)")

            time.sleep(30)

    except KeyboardInterrupt:
        print("\n\nMonitoring stopped by user")
        sys.exit(0)


if __name__ == "__main__":
    import pandas as pd
    main()
