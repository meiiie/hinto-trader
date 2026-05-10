"""
SOTA Diagnostic: TP/SL Display Data Flow Trace

This script traces the COMPLETE data flow for TP/SL display:
1. Binance API raw response (open orders)
2. FuturesOrder object parsed
3. LiveTradingService watermarks state
4. Portfolio endpoint final response

Run: python backend/tests/diagnostic_tpsl_flow.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import json
import asyncio
from datetime import datetime

def step_divider(title: str, step_num: int):
    print(f"\n{'='*70}")
    print(f"📊 STEP {step_num}: {title}")
    print('='*70)

def main():
    print("="*70)
    print("🔍 SOTA Diagnostic: TP/SL Display Data Flow Trace")
    print(f"⏰ Time: {datetime.now().isoformat()}")
    print("="*70)

    # =========================================================================
    # STEP 1: Raw Binance API Response
    # =========================================================================
    step_divider("Raw Binance API Response", 1)

    try:
        from src.infrastructure.api.binance_futures_client import BinanceFuturesClient

        use_testnet = os.getenv("BINANCE_USE_TESTNET", "true").lower() == "true"
        print(f"🔧 Using Testnet: {use_testnet}")

        client = BinanceFuturesClient(use_testnet=use_testnet)

        # Get RAW open orders (before parsing to FuturesOrder)
        raw_orders = client._send_signed_request("GET", "/fapi/v1/openOrders", {})

        print(f"📦 Raw Orders Count: {len(raw_orders)}")
        for o in raw_orders[:3]:  # Show first 3
            print(f"\n  📝 {o.get('symbol')} - {o.get('type')}")
            print(f"     time: {o.get('time')} ({datetime.fromtimestamp(o.get('time', 0)/1000) if o.get('time') else 'N/A'})")
            print(f"     side: {o.get('side')}")
            print(f"     price: {o.get('price')}")
            print(f"     stopPrice: {o.get('stopPrice')}")
            print(f"     orderId: {o.get('orderId')}")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

    # =========================================================================
    # STEP 2: FuturesOrder Objects (parsed)
    # =========================================================================
    step_divider("FuturesOrder Objects (parsed)", 2)

    try:
        orders = client.get_open_orders()

        print(f"📦 Parsed Orders Count: {len(orders)}")
        for o in orders[:3]:
            print(f"\n  📝 {o.symbol} - {o.type}")
            print(f"     time: {o.time} ({datetime.fromtimestamp(o.time/1000) if o.time else 'N/A'})")
            print(f"     side: {o.side}")
            print(f"     stop_price: {o.stop_price}")
            print(f"     Has time field: {hasattr(o, 'time')}")
            print(f"     Has stop_price field: {hasattr(o, 'stop_price')}")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

    # =========================================================================
    # STEP 3: LiveTradingService State
    # =========================================================================
    step_divider("LiveTradingService State", 3)

    try:
        from src.infrastructure.di_container import DIContainer

        container = DIContainer()
        live_service = container.get_live_trading_service()

        print(f"📊 Mode: {live_service.mode}")
        print(f"📊 Cache Initialized: {live_service._local_cache_initialized}")
        print(f"📊 Active Positions: {len(live_service.active_positions)}")

        # Position Watermarks
        print(f"\n🎯 _position_watermarks:")
        for sym, wm in live_service._position_watermarks.items():
            sl = wm.get('current_sl', 0)
            tp = wm.get('tp_target', 0)
            print(f"   {sym}: SL=${sl:.2f}, TP=${tp:.2f}")

        # Pending Orders
        print(f"\n📋 pending_orders: {len(live_service.pending_orders)}")
        for sym, pi in live_service.pending_orders.items():
            print(f"   {sym}: SL=${pi.stop_loss:.2f}, TP=${pi.take_profit:.2f}")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

    # =========================================================================
    # STEP 4: Database State
    # =========================================================================
    step_divider("Database State (live_positions table)", 4)

    try:
        from src.infrastructure.persistence.sqlite_order_repository import SQLiteOrderRepository

        db_path = "data/testnet/trading_system.db"
        repo = SQLiteOrderRepository(db_path=db_path)

        positions = repo.get_open_live_positions()

        print(f"📦 DB Positions Count: {len(positions)}")
        for p in positions:
            sl = p.get('stop_loss', 0)
            tp = p.get('take_profit', 0)
            print(f"   {p.get('symbol')}: SL=${sl:.2f}, TP=${tp:.2f}")
            print(f"      open_time: {p.get('open_time')}")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

    # =========================================================================
    # STEP 5: get_portfolio() Output
    # =========================================================================
    step_divider("get_portfolio() Output", 5)

    try:
        portfolio = live_service.get_portfolio()

        print(f"📊 Balance: ${portfolio.get('balance', 0):.2f}")
        print(f"📊 Positions Count: {len(portfolio.get('open_positions', []))}")

        for pos in portfolio.get('open_positions', []):
            sym = pos.get('symbol', '')
            sl = pos.get('stop_loss')
            tp = pos.get('take_profit')
            sl_str = f"${sl:.2f}" if sl else "--"
            tp_str = f"${tp:.2f}" if tp else "--"
            print(f"\n   📈 {sym}")
            print(f"      stop_loss: {sl_str}")
            print(f"      take_profit: {tp_str}")

        # Pending Orders
        print(f"\n📋 Pending Orders:")
        for order in portfolio.get('pending_orders', []):
            print(f"   {order.get('symbol')}: open_time={order.get('open_time', '--')}")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

    # =========================================================================
    # SUMMARY
    # =========================================================================
    print("\n" + "="*70)
    print("📊 DATA FLOW SUMMARY")
    print("="*70)

    print("""
    Binance API (/fapi/v1/openOrders)
        ↓ (raw JSON includes 'time', 'stopPrice')
    FuturesOrder parsing (binance_futures_client.py)
        ↓ (should include time, stop_price fields)
    LiveTradingService._cached_open_orders
        ↓ (cache for fast access)
    get_portfolio() → sl_tp_map → _position_watermarks
        ↓ (correlate SL/TP to positions)
    Frontend Portfolio.tsx
        ↓ (display in TP/SL column)
    UI
    """)

    print("\n💡 CHECK:")
    print("   1. Raw API has 'time'? → FuturesOrder.time should be non-zero")
    print("   2. _position_watermarks populated? → SL/TP should show values")
    print("   3. DB has positions? → Should survive restart")
    print("   4. get_portfolio has SL/TP? → Frontend should display")

if __name__ == "__main__":
    main()
