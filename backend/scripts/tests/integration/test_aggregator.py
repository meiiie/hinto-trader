"""
Test Data Aggregator

Test script to verify 1m → 15m/1h aggregation logic.
"""

import asyncio
import sys
import os
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.infrastructure.websocket import BinanceWebSocketClient
from src.infrastructure.aggregation import DataAggregator
from src.utils.logging_config import configure_logging


# Global counters
candle_count_1m = 0
candle_count_15m = 0
candle_count_1h = 0


def on_15m_complete(candle):
    """Callback for completed 15m candle"""
    global candle_count_15m
    candle_count_15m += 1
    print(f"\n{'='*60}")
    print(f"🟢 15-MINUTE CANDLE COMPLETED #{candle_count_15m}")
    print(f"{'='*60}")
    print(f"Timestamp: {candle.timestamp.strftime('%Y-%m-%d %H:%M')}")
    print(f"Open:      ${candle.open:,.2f}")
    print(f"High:      ${candle.high:,.2f}")
    print(f"Low:       ${candle.low:,.2f}")
    print(f"Close:     ${candle.close:,.2f}")
    print(f"Volume:    {candle.volume:,.2f} BTC")
    print(f"Change:    ${candle.close - candle.open:+,.2f} ({((candle.close - candle.open) / candle.open * 100):+.2f}%)")
    print(f"{'='*60}\n")


def on_1h_complete(candle):
    """Callback for completed 1h candle"""
    global candle_count_1h
    candle_count_1h += 1
    print(f"\n{'='*60}")
    print(f"🔵 1-HOUR CANDLE COMPLETED #{candle_count_1h}")
    print(f"{'='*60}")
    print(f"Timestamp: {candle.timestamp.strftime('%Y-%m-%d %H:%M')}")
    print(f"Open:      ${candle.open:,.2f}")
    print(f"High:      ${candle.high:,.2f}")
    print(f"Low:       ${candle.low:,.2f}")
    print(f"Close:     ${candle.close:,.2f}")
    print(f"Volume:    {candle.volume:,.2f} BTC")
    print(f"Change:    ${candle.close - candle.open:+,.2f} ({((candle.close - candle.open) / candle.open * 100):+.2f}%)")
    print(f"{'='*60}\n")


def on_candle_1m(candle, metadata):
    """Callback for 1m candle from WebSocket"""
    global candle_count_1m, aggregator

    is_closed = metadata['is_closed']

    # Show ALL updates (both updating and closed)
    if is_closed:
        candle_count_1m += 1
        print(f"\n✅ CLOSED #{candle_count_1m}: {candle.timestamp.strftime('%H:%M:%S')} | "
              f"O:{candle.open:.2f} H:{candle.high:.2f} L:{candle.low:.2f} C:{candle.close:.2f} V:{candle.volume:.2f}")

        # Show buffer status when closed
        status = aggregator.get_buffer_status()
        print(f"   Buffer: 1m={status['1m_total']}, "
              f"15m_pending={status['15m_pending']}/15, "
              f"1h_pending={status['1h_pending']}/60\n")
    else:
        # Show real-time updates (overwrite same line)
        print(f"\r⏳ UPDATING: {candle.timestamp.strftime('%H:%M:%S')} | "
              f"O:{candle.open:.2f} H:{candle.high:.2f} L:{candle.low:.2f} C:{candle.close:.2f} V:{candle.volume:.2f}",
              end='', flush=True)

    # Add to aggregator (only closed candles)
    aggregator.add_candle_1m(candle, is_closed=is_closed)


async def main():
    """Main test function"""
    global aggregator

    # Configure logging
    configure_logging(level=20)  # INFO level

    print("=" * 60)
    print("🚀 Data Aggregator Test")
    print("=" * 60)
    print()
    print("Testing 1m → 15m/1h aggregation...")
    print("This will run until you see a 15m candle complete")
    print("(may take up to 15 minutes)")
    print()
    print("Press Ctrl+C to stop")
    print()

    # Create aggregator
    aggregator = DataAggregator()

    # Register callbacks
    aggregator.on_15m_complete(on_15m_complete)
    aggregator.on_1h_complete(on_1h_complete)

    # Create WebSocket client
    client = BinanceWebSocketClient()
    client.subscribe_candle(on_candle_1m)

    try:
        # Connect
        await client.connect(symbol='btcusdt', interval='1m')
        print("✅ Connected! Collecting 1m candles...\n")

        # Run for 2 minutes (to see buffer filling up)
        await asyncio.sleep(120)

    except KeyboardInterrupt:
        print("\n\n⏹️  Stopping...")
    except Exception as e:
        print(f"\n❌ Error: {e}")
    finally:
        await client.disconnect()
        print("\n✅ Disconnected")
        print()
        print("Summary:")
        print(f"  1m candles processed: {candle_count_1m}")
        print(f"  15m candles completed: {candle_count_15m}")
        print(f"  1h candles completed: {candle_count_1h}")
        print()
        print(f"  Final buffer status: {aggregator.get_buffer_status()}")


if __name__ == "__main__":
    asyncio.run(main())
