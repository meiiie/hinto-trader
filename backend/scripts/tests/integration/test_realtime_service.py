"""
Test Real-time Service

Integration test for the complete real-time trading system.
"""

import asyncio
import sys
import os
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.application.services.realtime_service import RealtimeService
from src.utils.logging_config import configure_logging


def on_signal_generated(signal):
    """Callback for trading signals"""
    print(f"\n{'='*60}")
    print(f"🚨 TRADING SIGNAL GENERATED")
    print(f"{'='*60}")
    print(f"{signal}")
    print(f"Reasons:")
    for reason in signal.reasons:
        print(f"  - {reason}")
    print(f"{'='*60}\n")


async def main():
    """Main test function"""
    # Configure logging
    configure_logging(level=20)  # INFO level

    print("=" * 60)
    print("🚀 Real-time Trading Service Test")
    print("=" * 60)
    print()
    print("This will run the complete real-time trading system:")
    print("  - WebSocket data streaming")
    print("  - Data aggregation (1m → 15m/1h)")
    print("  - Volume analysis")
    print("  - RSI monitoring")
    print("  - Signal generation")
    print()
    print("Press Ctrl+C to stop")
    print()

    # Create service
    service = RealtimeService(symbol='btcusdt', interval='1m')

    # Subscribe to signals
    service.subscribe_signals(on_signal_generated)

    try:
        # Start service
        await service.start()

        print("✅ Service started! Monitoring market...")
        print()

        # Run for 5 minutes
        for i in range(300):
            await asyncio.sleep(1)

            # Display status every 30 seconds
            if i % 30 == 0 and i > 0:
                status = service.get_status()
                print(f"\n📊 Status Update ({i}s):")
                print(f"  Connection: {status['connection']['state']}")
                print(f"  Latency: {status['connection']['latency_ms']}ms")
                print(f"  1m candles: {status['data']['1m_candles']}")
                print(f"  15m candles: {status['data']['15m_candles']}")
                print(f"  1h candles: {status['data']['1h_candles']}")

                # Show latest data
                latest_1m = service.get_latest_data('1m')
                if latest_1m:
                    print(f"  Latest price: ${latest_1m.close:,.2f}")
                print()

    except KeyboardInterrupt:
        print("\n\n⏹️  Stopping...")
    except Exception as e:
        print(f"\n❌ Error: {e}")
    finally:
        # Stop service
        await service.stop()
        print("✅ Service stopped")
        print()

        # Show final status
        status = service.get_status()
        print("Final Status:")
        print(f"  Total 1m candles: {status['data']['1m_candles']}")
        print(f"  Total 15m candles: {status['data']['15m_candles']}")
        print(f"  Total 1h candles: {status['data']['1h_candles']}")
        print(f"  Reconnections: {status['connection']['reconnect_count']}")


if __name__ == "__main__":
    asyncio.run(main())
