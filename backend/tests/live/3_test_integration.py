"""
Full Integration Test - Signal to Order Execution on Testnet
Connects real-time signals to LiveTradingService for testnet order execution.

Flow:
1. Connect to Binance WebSocket for real-time candles
2. Run Signal Generator on each candle update
3. When signal detected → Execute via LiveTradingService
4. LiveTradingService places Entry + SL + TP on Testnet
"""

import asyncio
import sys
import os
import logging
from datetime import datetime

# Add project root to python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.application.services.realtime_service import RealtimeService
from src.application.services.live_trading_service import LiveTradingService, TradingMode
from src.domain.entities.trading_signal import TradingSignal

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)


class IntegrationTest:
    """Full integration test: Signal → Testnet Order Execution."""

    def __init__(self, symbol: str = "btcusdt"):
        self.symbol = symbol
        self.realtime_service = RealtimeService(symbol=symbol, interval='15m')

        # Initialize LiveTradingService in TESTNET mode
        self.trading_service = LiveTradingService(
            mode=TradingMode.TESTNET,
            risk_per_trade=0.01,  # 1% risk
            max_positions=3,
            max_leverage=10,
            enable_trading=True
        )

        self.signals_received = 0
        self.orders_executed = 0
        self.last_signal: TradingSignal = None

    async def start(self):
        """Start the integration test."""
        print("\n" + "=" * 70)
        print("🚀 FULL INTEGRATION TEST - Signal → Testnet Execution")
        print("=" * 70)
        print(f"📊 Symbol: {self.symbol.upper()}")
        print(f"🧪 Mode: TESTNET (Demo money)")
        print(f"💰 Balance: ${self.trading_service.initial_balance:,.2f}")
        print(f"⚙️ Risk: {self.trading_service.risk_per_trade*100}% per trade")
        print(f"📈 Max Positions: {self.trading_service.max_positions}")
        print("=" * 70)

        # Subscribe to signals - this is where execution happens
        self.realtime_service.subscribe_signals(self.on_signal)

        # Subscribe to updates for status display
        self.realtime_service.subscribe_updates(self.on_update)

        # Start realtime service
        print("\n⏳ Connecting to Binance WebSocket...")
        await self.realtime_service.start()

        # Wait for warmup
        print("⏳ Warming up indicators (loading 50+ candles)...")
        while True:
            candle_count = len(self.realtime_service.get_candles('15m'))
            if candle_count >= 50:
                print(f"✅ Data Ready! ({candle_count} candles)")
                break
            print(f"\r   Loading... {candle_count}/50 candles", end="", flush=True)
            await asyncio.sleep(1)

        print("\n" + "-" * 70)
        print("📡 LIVE MONITORING STARTED")
        print("   Waiting for signals... (Ctrl+C to stop)")
        print("-" * 70)

        # Keep running
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            await self.stop()

    async def stop(self):
        """Stop the test."""
        print("\n\n⏹️ Stopping integration test...")
        await self.realtime_service.stop()
        self.print_summary()

    def on_signal(self, signal: TradingSignal):
        """Handle signal - EXECUTE ON TESTNET."""
        self.signals_received += 1
        self.last_signal = signal

        timestamp = datetime.now().strftime("%H:%M:%S")
        signal_type = signal.signal_type.value.upper()

        print("\n" + "=" * 70)
        print(f"🚨 SIGNAL DETECTED at {timestamp}")
        print("=" * 70)
        print(f"   Type: {signal_type}")
        print(f"   Symbol: {signal.symbol}")
        print(f"   Price: ${signal.price:,.2f}")
        print(f"   Entry: ${signal.entry_price:,.2f}")
        print(f"   SL: ${signal.stop_loss:,.2f}")
        if signal.tp_levels:
            print(f"   TP1: ${signal.tp_levels.get('tp1', 0):,.2f}")
        print(f"   Confidence: {signal.confidence*100:.1f}%")

        # Execute on Testnet
        print("\n📤 EXECUTING ON TESTNET...")

        try:
            result = self.trading_service.execute_signal(signal)

            if result.success:
                self.orders_executed += 1
                print(f"✅ ORDER EXECUTED!")
                print(f"   Order ID: {result.order.order_id if result.order else 'N/A'}")
                print(f"   Status: {result.order.status if result.order else 'N/A'}")
            else:
                print(f"❌ ORDER FAILED: {result.error}")

        except Exception as e:
            logger.error(f"Execution error: {e}")
            print(f"❌ EXCEPTION: {e}")

        print("=" * 70 + "\n")

    def on_update(self):
        """Handle data updates (for status display)."""
        # Rate limit to every 30 seconds
        pass

    def print_summary(self):
        """Print test summary."""
        print("\n" + "=" * 70)
        print("📊 INTEGRATION TEST SUMMARY")
        print("=" * 70)
        print(f"   Signals Received: {self.signals_received}")
        print(f"   Orders Executed: {self.orders_executed}")

        if self.trading_service.client:
            # Get final balance
            final_balance = self.trading_service.client.get_usdt_balance()
            pnl = final_balance - self.trading_service.initial_balance
            pnl_pct = (pnl / self.trading_service.initial_balance) * 100 if self.trading_service.initial_balance > 0 else 0

            print(f"   Initial Balance: ${self.trading_service.initial_balance:,.2f}")
            print(f"   Final Balance: ${final_balance:,.2f}")
            print(f"   PnL: ${pnl:+,.2f} ({pnl_pct:+.2f}%)")

            # Open positions
            positions = self.trading_service.client.get_positions()
            active = [p for p in positions if abs(p.position_amt) > 0]
            if active:
                print(f"\n   Open Positions:")
                for p in active:
                    print(f"      {p.symbol}: {p.position_amt} @ ${p.entry_price:,.2f}")

        print("=" * 70)


async def main():
    """Main entry point."""
    # Get symbol from args or default
    symbol = sys.argv[1] if len(sys.argv) > 1 else "btcusdt"

    test = IntegrationTest(symbol=symbol)

    try:
        await test.start()
    except KeyboardInterrupt:
        pass
    finally:
        await test.stop()


if __name__ == "__main__":
    print("\n⚠️ TESTNET INTEGRATION TEST")
    print("This will execute REAL orders on Binance Testnet.")
    print("No real money involved.\n")

    confirm = input("Start test? (yes/no): ").strip().lower()
    if confirm == "yes":
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            pass
    else:
        print("Cancelled.")
