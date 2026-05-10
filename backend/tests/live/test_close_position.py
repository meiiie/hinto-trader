"""
Test script to verify close position functionality on Testnet.

Run from backend directory: python tests/live/test_close_position.py
"""

import os
import sys

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from dotenv import load_dotenv
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

def main():
    print("=" * 60)
    print("🔴 Close Position Test (Testnet)")
    print("=" * 60)

    # 1. Get current positions
    print("\n1️⃣ Checking current positions...")
    try:
        from src.infrastructure.api.binance_futures_client import BinanceFuturesClient

        client = BinanceFuturesClient(use_testnet=True)
        positions = client.get_positions()

        if not positions:
            print("   ⚠️ No open positions found!")
            return

        print(f"   ✅ Found {len(positions)} positions:")
        for p in positions:
            side = "LONG" if p.position_amt > 0 else "SHORT"
            print(f"      - {p.symbol}: {side} {abs(p.position_amt)} @ ${p.entry_price:.2f}")
            print(f"        PnL: ${p.unrealized_pnl:.2f}")

    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return

    # 2. Ask user before closing
    print("\n2️⃣ Close confirmation:")
    position = positions[0]
    side = "LONG" if position.position_amt > 0 else "SHORT"
    quantity = abs(position.position_amt)

    print(f"   Will close: {position.symbol} {side} {quantity}")
    confirm = input("   Type 'yes' to close: ")

    if confirm.lower() != 'yes':
        print("   ❌ Cancelled")
        return

    # 3. Execute close
    print("\n3️⃣ Closing position...")
    try:
        order = client.close_position(position.symbol, quantity, side)
        print(f"   ✅ Position closed!")
        print(f"      Order ID: {order.order_id}")
        print(f"      Status: {order.status}")
        print(f"      Executed: {order.executed_qty}")

    except Exception as e:
        print(f"   ❌ Failed: {e}")
        import traceback
        traceback.print_exc()

    # 4. Verify position closed
    print("\n4️⃣ Verifying position closed...")
    try:
        verify_positions = client.get_positions(position.symbol)
        if not verify_positions:
            print("   ✅ Position fully closed!")
        else:
            for p in verify_positions:
                if abs(p.position_amt) > 0:
                    print(f"   ⚠️ Position still open: {p.position_amt}")
                else:
                    print("   ✅ Position fully closed!")

    except Exception as e:
        print(f"   ❌ Failed: {e}")

    print("\n" + "=" * 60)
    print("Test complete!")
    print("=" * 60)

if __name__ == "__main__":
    main()
