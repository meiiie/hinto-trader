"""
Test script to verify LiveTradingService.get_portfolio() flow.

This tests the exact same code path as the /trades/portfolio endpoint.
Run from backend directory: python tests/live/test_portfolio_endpoint.py
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
    print("🔍 LiveTradingService.get_portfolio() Test")
    print("=" * 60)

    # 1. Test DI Container directly
    print("\n1️⃣ Testing DI Container...")
    try:
        from src.api.dependencies import get_container
        container = get_container()
        print(f"   ✅ Container created, env={container._env}")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return

    # 2. Get LiveTradingService
    print("\n2️⃣ Getting LiveTradingService...")
    try:
        live_service = container.get_live_trading_service()
        print(f"   ✅ LiveTradingService obtained")
        print(f"   Mode: {live_service.mode}")
        print(f"   Has client: {bool(live_service.client)}")
        print(f"   Enable trading: {live_service.enable_trading}")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return

    # 3. Call get_portfolio
    print("\n3️⃣ Calling get_portfolio()...")
    try:
        portfolio = live_service.get_portfolio()
        print(f"   ✅ Portfolio returned:")
        print(f"   Balance: ${portfolio.get('balance', 0):.2f}")
        print(f"   Equity: ${portfolio.get('equity', 0):.2f}")
        print(f"   Unrealized PnL: ${portfolio.get('unrealized_pnl', 0):.2f}")
        print(f"   Open positions count: {portfolio.get('open_positions_count', 0)}")

        positions = portfolio.get('open_positions', [])
        if positions:
            print(f"\n   📈 Positions ({len(positions)}):")
            for p in positions:
                print(f"      - {p.get('symbol')}: {p.get('side')} {p.get('size')} @ ${p.get('entry_price', 0):.2f}")
                print(f"        PnL: ${p.get('pnl', 0):.2f}, ROE: {p.get('roe', 0):.2f}%")
        else:
            print("\n   ⚠️ No positions in portfolio response!")
            print("   Checking active_positions cache...")
            print(f"   Cache count: {len(live_service.active_positions)}")
            for sym, pos in live_service.active_positions.items():
                print(f"      - {sym}: {pos.position_amt}")

    except Exception as e:
        print(f"   ❌ Failed: {e}")
        import traceback
        traceback.print_exc()

    # 4. Test _refresh_positions directly
    print("\n4️⃣ Testing _refresh_positions() directly...")
    try:
        live_service._refresh_positions()
        print(f"   ✅ Refreshed, {len(live_service.active_positions)} positions in cache")
        for sym, pos in live_service.active_positions.items():
            print(f"      - {sym}: amt={pos.position_amt}, PnL=${pos.unrealized_pnl:.2f}")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 60)
    print("Test complete!")
    print("=" * 60)

if __name__ == "__main__":
    main()
