"""
Test Script: Debug TP/SL Display Issues

This script diagnoses why TP/SL columns show "--" in Portfolio.
It checks:
1. Exchange open orders (STOP_MARKET, TAKE_PROFIT_MARKET)
2. Position data from positionRisk
3. Local _position_watermarks state
4. What get_portfolio() returns

Run: python backend/tests/test_tpsl_debug.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

from src.infrastructure.api.binance_futures_client import BinanceFuturesClient
import json

def main():
    print("=" * 60)
    print("🔍 TP/SL DEBUG SCRIPT")
    print("=" * 60)

    # Initialize client (Testnet)
    client = BinanceFuturesClient(use_testnet=True)
    print(f"✅ Connected to: {client.base_url}")

    # 1. Get all open orders
    print("\n" + "=" * 60)
    print("📋 STEP 1: Open Orders on Exchange")
    print("=" * 60)

    try:
        open_orders = client.get_open_orders()
        print(f"Total open orders: {len(open_orders)}")

        if not open_orders:
            print("⚠️ NO OPEN ORDERS FOUND!")
            print("   This explains why TP/SL shows '--'")
            print("   Testnet may not have STOP_MARKET orders placed.")
        else:
            for o in open_orders:
                if isinstance(o, dict):
                    print(f"\n  📝 Order ID: {o.get('orderId')}")
                    print(f"     Symbol: {o.get('symbol')}")
                    print(f"     Type: {o.get('type')}")
                    print(f"     Side: {o.get('side')}")
                    print(f"     Status: {o.get('status')}")
                    print(f"     Stop Price: {o.get('stopPrice')}")
                else:
                    print(f"\n  📝 Order: {o.symbol} {o.type} @ {getattr(o, 'stop_price', 'N/A')}")

        # 2. Count SL/TP orders
        sl_orders = [o for o in open_orders if (o.get('type') if isinstance(o, dict) else o.type) == 'STOP_MARKET']
        tp_orders = [o for o in open_orders if (o.get('type') if isinstance(o, dict) else o.type) == 'TAKE_PROFIT_MARKET']

        print(f"\n📊 Summary:")
        print(f"   STOP_MARKET (SL): {len(sl_orders)}")
        print(f"   TAKE_PROFIT_MARKET (TP): {len(tp_orders)}")

    except Exception as e:
        print(f"❌ Error fetching orders: {e}")

    # 2. Get positions from positionRisk
    print("\n" + "=" * 60)
    print("📋 STEP 2: Positions from /fapi/v2/positionRisk")
    print("=" * 60)

    try:
        positions = client.get_positions()
        print(f"Total non-zero positions: {len(positions)}")

        for p in positions:
            print(f"\n  📈 {p.symbol}")
            print(f"     Side: {'LONG' if p.position_amt > 0 else 'SHORT'}")
            print(f"     Size: {abs(p.position_amt)}")
            print(f"     Entry Price: ${p.entry_price:.2f}")
            print(f"     Mark Price: ${p.mark_price:.2f}")
            print(f"     Unrealized PnL: ${p.unrealized_pnl:.2f}")
            print(f"     Margin: ${p.margin:.2f}")
            print(f"     Leverage: {p.leverage}x")

    except Exception as e:
        print(f"❌ Error fetching positions: {e}")

    # 3. TEST: What would get_portfolio return?
    print("\n" + "=" * 60)
    print("📋 STEP 3: Simulating get_portfolio() SL/TP mapping")
    print("=" * 60)

    try:
        # Build sl_tp_map like get_portfolio does
        sl_tp_map = {}
        for o in open_orders:
            if isinstance(o, dict):
                sym = o.get('symbol')
                order_type = o.get('type')
                stop_price = float(o.get('stopPrice', 0))
            else:
                sym = o.symbol
                order_type = o.type.value if hasattr(o.type, 'value') else o.type
                stop_price = getattr(o, 'stop_price', 0) or 0

            if sym not in sl_tp_map:
                sl_tp_map[sym] = {'stop_loss': None, 'take_profit': None}

            if order_type == 'STOP_MARKET':
                sl_tp_map[sym]['stop_loss'] = stop_price
            elif order_type == 'TAKE_PROFIT_MARKET':
                sl_tp_map[sym]['take_profit'] = stop_price

        if sl_tp_map:
            print("✅ SL/TP Map from exchange orders:")
            for sym, vals in sl_tp_map.items():
                print(f"   {sym}: SL=${vals['stop_loss'] or '--'}, TP=${vals['take_profit'] or '--'}")
        else:
            print("⚠️ SL/TP Map is EMPTY - no STOP_MARKET or TAKE_PROFIT_MARKET orders on exchange")
            print("\n💡 SOLUTION OPTIONS:")
            print("   1. Place STOP_MARKET orders manually or verify bot logic")
            print("   2. Use local-only TP/SL tracking (current implementation)")
            print("   3. Display TP/SL from signal (pending_orders) instead of exchange")

    except Exception as e:
        print(f"❌ Error building sl_tp_map: {e}")

    print("\n" + "=" * 60)
    print("🏁 DEBUG COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    main()
