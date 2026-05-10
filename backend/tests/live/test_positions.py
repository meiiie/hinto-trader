"""
Test script to verify Binance Futures API positions endpoint directly.

This bypasses all application logic to isolate the issue.
Run from backend directory: python tests/live/test_positions.py
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
    print("🔍 Binance Futures Positions Test")
    print("=" * 60)

    # 1. Check ENV variable
    env = os.getenv("ENV", "NOT_SET")
    print(f"\n1️⃣ ENV Variable: '{env}'")

    # 2. Check API keys
    testnet_key = os.getenv("BINANCE_TESTNET_API_KEY", "")
    testnet_secret = os.getenv("BINANCE_TESTNET_API_SECRET", "")
    print(f"\n2️⃣ API Keys:")
    print(f"   BINANCE_TESTNET_API_KEY: {'✅ Set' if testnet_key else '❌ Missing'} ({len(testnet_key)} chars)")
    print(f"   BINANCE_TESTNET_API_SECRET: {'✅ Set' if testnet_secret else '❌ Missing'} ({len(testnet_secret)} chars)")

    if not testnet_key or not testnet_secret:
        print("\n❌ API keys missing! Check .env file.")
        return

    # 3. Test BinanceFuturesClient directly
    print("\n3️⃣ Testing BinanceFuturesClient...")
    try:
        from src.infrastructure.api.binance_futures_client import BinanceFuturesClient

        client = BinanceFuturesClient(use_testnet=True)
        print("   ✅ Client created successfully")

        # 4. Test balance
        print("\n4️⃣ Testing get_usdt_balance()...")
        try:
            balance = client.get_usdt_balance()
            print(f"   ✅ USDT Balance: ${balance:.2f}")
        except Exception as e:
            print(f"   ❌ Failed: {e}")

        # 5. Test positions
        print("\n5️⃣ Testing get_positions()...")
        try:
            positions = client.get_positions()
            print(f"   ✅ Found {len(positions)} positions with non-zero amount")

            if positions:
                for p in positions:
                    print(f"\n   📈 {p.symbol}:")
                    print(f"      Amount: {p.position_amt}")
                    print(f"      Entry Price: ${p.entry_price:.2f}")
                    print(f"      Mark Price: ${p.mark_price:.2f}")
                    print(f"      Unrealized PnL: ${p.unrealized_pnl:.2f}")
                    print(f"      Leverage: {p.leverage}x")
            else:
                print("   ⚠️ No open positions found!")
                print("\n   💡 This could mean:")
                print("      - No active positions on Binance Testnet")
                print("      - Positions were closed")
                print("      - Different account")

        except Exception as e:
            print(f"   ❌ Failed: {e}")
            import traceback
            traceback.print_exc()

        # 6. Raw API call test
        print("\n6️⃣ Raw API call to /fapi/v2/positionRisk...")
        try:
            raw_positions = client._send_signed_request("GET", "/fapi/v2/positionRisk", {})
            non_zero = [p for p in raw_positions if float(p.get("positionAmt", 0)) != 0]
            print(f"   ✅ API returned {len(raw_positions)} total, {len(non_zero)} non-zero")

            if non_zero:
                for p in non_zero[:3]:  # Show first 3
                    print(f"\n   Raw: {p.get('symbol')}")
                    print(f"      positionAmt: {p.get('positionAmt')}")
                    print(f"      entryPrice: {p.get('entryPrice')}")
                    print(f"      unRealizedProfit: {p.get('unRealizedProfit')}")
        except Exception as e:
            print(f"   ❌ Failed: {e}")

    except Exception as e:
        print(f"   ❌ Failed to create client: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 60)
    print("Test complete!")
    print("=" * 60)

if __name__ == "__main__":
    main()
