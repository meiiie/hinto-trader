import sys
import os
import time
import logging

# Add backend root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.infrastructure.api.binance_futures_client import BinanceFuturesClient, OrderSide, OrderType
from src.application.services.market_intelligence_service import MarketIntelligenceService

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger("DeepTest")

def print_step(msg):
    print(f"\n🔹 {msg}")

def run_deep_test():
    client = BinanceFuturesClient(use_testnet=True)
    intel = MarketIntelligenceService()
    SYMBOL = "DOGEUSDT"

    print(f"🚀 STARTING DEEP TRADING TEST ON {SYMBOL}")
    print(f"   Balance: ${client.get_usdt_balance():.2f}")

    # 1. CLEANUP
    print_step("STEP 1: CLEANUP")
    client.cancel_all_orders(SYMBOL)
    client.close_position(SYMBOL)
    time.sleep(1)

    # 2. ENTRY
    print_step("STEP 2: MARKET ENTRY (LONG 50 DOGE)")
    qty = 50
    # Sanitize
    _, qty = intel.sanitize_order(SYMBOL, 0, qty)

    entry = client.create_order(SYMBOL, OrderSide.BUY, OrderType.MARKET, qty)
    print(f"   ⏳ Placed Market Order ID: {entry.order_id}. Waiting for fill...")

    # Wait loop for fill
    entry_price = 0.0
    for _ in range(5):
        time.sleep(1)
        updated_order = client.get_order(SYMBOL, entry.order_id)
        if updated_order.get('status') == 'FILLED':
            entry_price = float(updated_order.get('avgPrice', 0))
            print(f"   ✅ FILLED! Entry Price: {entry_price}")
            break

    if entry_price == 0:
        # Fallback: Get mark price if order fetch fails (rare)
        print("   ⚠️ Warning: Could not get fill price from order. Fetching ticker...")
        entry_price = client.get_ticker_price(SYMBOL)

    # 3. INITIAL BRACKET
    print_step("STEP 3: PLACING INITIAL SL/TP")
    sl_price_1 = round(entry_price * 0.95, 5) # -5%
    tp_price_1 = round(entry_price * 1.05, 5) # +5%

    # Sanitize Prices
    sl_price_1, _ = intel.sanitize_order(SYMBOL, sl_price_1, 0)
    tp_price_1, _ = intel.sanitize_order(SYMBOL, tp_price_1, 0)

    print(f"   🎯 Target SL: {sl_price_1} | TP: {tp_price_1}")

    # Place SL
    sl_order_1 = client.create_order(
        SYMBOL, OrderSide.SELL, OrderType.STOP_MARKET, qty,
        stop_price=sl_price_1, reduce_only=True
    )
    # Place TP
    tp_order_1 = client.create_order(
        SYMBOL, OrderSide.SELL, OrderType.TAKE_PROFIT_MARKET, qty,
        stop_price=tp_price_1, reduce_only=True
    )

    print(f"   ✅ Initial SL ID: {sl_order_1.order_id}")
    print(f"   ✅ Initial TP ID: {tp_order_1.order_id}")

    # Verify Open Orders
    open_orders = client.get_open_orders(SYMBOL)
    if len(open_orders) == 2:
        print("   ✅ VERIFIED: 2 Orders active on Exchange.")
    else:
        print(f"   ❌ WARNING: Found {len(open_orders)} orders (Expected 2).")

    time.sleep(2)

    # 4. TEST TRAILING STOP (Simulate Move Up)
    print_step("STEP 4: SIMULATING TRAILING STOP (Move SL UP)")
    # Logic: Cancel Old SL -> Place New SL Higher

    new_sl_price = round(entry_price * 0.98, 5) # Move from -5% to -2%
    new_sl_price, _ = intel.sanitize_order(SYMBOL, new_sl_price, 0)

    print(f"   🔄 Moving SL from {sl_price_1} -> {new_sl_price}...")

    # A. Cancel Old
    client.cancel_order(SYMBOL, sl_order_1.order_id)
    print(f"   Note: Cancelled Old SL {sl_order_1.order_id}")

    # B. Place New
    sl_order_2 = client.create_order(
        SYMBOL, OrderSide.SELL, OrderType.STOP_MARKET, qty,
        stop_price=new_sl_price, reduce_only=True
    )
    print(f"   ✅ New SL Placed: ID {sl_order_2.order_id} @ {new_sl_price}")

    # 5. FINAL VERIFICATION
    print_step("STEP 5: INTEGRITY CHECK")
    final_orders = client.get_open_orders(SYMBOL)

    sl_exists = any(str(o['orderId']) == str(sl_order_2.order_id) for o in final_orders)
    tp_exists = any(str(o['orderId']) == str(tp_order_1.order_id) for o in final_orders)

    if sl_exists and tp_exists:
        print("   ✅ SUCCESS: New SL is active AND Old TP is still active.")
        print("   🚀 TRAILING LOGIC CONFIRMED WORKING.")
    else:
        print("   ❌ FAIL: Orders missing.")
        print(f"   Active IDs: {[o['orderId'] for o in final_orders]}")

    # 6. CLEANUP
    print_step("STEP 6: CLEANUP")
    client.cancel_all_orders(SYMBOL)
    client.close_position(SYMBOL)
    print("   ✅ All clear.")

if __name__ == "__main__":
    try:
        run_deep_test()
    except Exception as e:
        print(f"\n❌ TEST CRASHED: {e}")
        import traceback
        traceback.print_exc()
