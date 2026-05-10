import sys
import os
import time
import logging

# Add backend root to sys.path
# backend/tests/live -> backend
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.infrastructure.api.binance_futures_client import BinanceFuturesClient, OrderSide, OrderType
from src.application.services.market_intelligence_service import MarketIntelligenceService

# Setup
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("LiveTest")

def print_section(title):
    print(f"\n{'='*60}\n {title}\n{'='*60}")

def run_test():
    # 1. Init
    client = BinanceFuturesClient(use_testnet=True) # FORCE TESTNET
    intel = MarketIntelligenceService()

    SYMBOL = "DOGEUSDT"

    # 2. Pre-check Balance
    print_section("PRE-CHECK")
    balance = client.get_usdt_balance()
    print(f"💰 Wallet Balance: ${balance:.2f}")
    if balance < 10:
        print("❌ Error: Balance too low (<$10). Please faucet testnet.")
        return

    # 3. Clean Slate
    print("🧹 Cleaning up open orders...")
    client.cancel_all_orders(SYMBOL)
    pos = client.get_position(SYMBOL)
    if pos and pos.position_amt != 0:
        print(f"⚠️ Found open position: {pos.position_amt}. Closing...")
        client.close_position(SYMBOL)
        time.sleep(1)

    # =================================================================
    # PHASE 1: ORDER TYPES
    # =================================================================
    print_section("PHASE 1: TEST INDIVIDUAL ORDERS")

    # A. LIMIT ORDER
    print("👉 1. Testing LIMIT Order...")
    price = client.get_ticker_price(SYMBOL)
    target_price = price * 0.9 # -10% price to avoid fill
    qty = 50 # > $5 Notional

    # Rounding
    target_price, qty = intel.sanitize_order(SYMBOL, target_price, qty)

    try:
        order = client.create_order(SYMBOL, OrderSide.BUY, OrderType.LIMIT, qty, price=target_price)
        print(f"✅ LIMIT PASS: ID {order.order_id} @ {order.price}")

        # Cancel it
        client.cancel_order(SYMBOL, order.order_id)
        print("   -> Cancelled OK")
    except Exception as e:
        print(f"❌ LIMIT FAIL: {e}")

    # =================================================================
    # PHASE 2: FULL TRADE CYCLE
    # =================================================================
    print_section("PHASE 2: FULL TRADE CYCLE (SCALPING)")

    # B. MARKET ENTRY
    print("👉 2. Entering Market (LONG)...")
    qty = 50 # Safe size
    qty = intel.sanitize_order(SYMBOL, 0, qty)[1] # Only sanitize qty

    try:
        entry_order = client.create_order(SYMBOL, OrderSide.BUY, OrderType.MARKET, qty)
        print(f"✅ ENTRY PASS: Filled {entry_order.executed_qty} @ ~{entry_order.avg_price}")

        # Wait for position update
        time.sleep(2)
        pos = client.get_position(SYMBOL)
        if pos and pos.position_amt > 0:
            print(f"✅ POSITION VERIFIED: {pos.position_amt} DOGE | Entry: {pos.entry_price}")

            # C. STOP LOSS & TAKE PROFIT
            entry_price = float(pos.entry_price)
            sl_price = entry_price * 0.99 # -1%
            tp_price = entry_price * 1.02 # +2%

            # Rounding
            sl_price, _ = intel.sanitize_order(SYMBOL, sl_price, 0)
            tp_price, _ = intel.sanitize_order(SYMBOL, tp_price, 0)

            print(f"👉 3. Placing Brackets (SL: {sl_price}, TP: {tp_price})...")

            # SL
            sl_order = client.create_order(
                SYMBOL, OrderSide.SELL, OrderType.STOP_MARKET,
                quantity=abs(float(pos.position_amt)),
                stop_price=sl_price,
                reduce_only=True
            )
            print(f"✅ STOP_MARKET PASS: ID {sl_order.order_id}")

            # TP
            tp_order = client.create_order(
                SYMBOL, OrderSide.SELL, OrderType.TAKE_PROFIT_MARKET,
                quantity=abs(float(pos.position_amt)),
                stop_price=tp_price,
                reduce_only=True
            )
            print(f"✅ TAKE_PROFIT PASS: ID {tp_order.order_id}")

            # D. FINAL CLEANUP
            print("👉 4. Closing Position & Cleaning up...")
            client.cancel_all_orders(SYMBOL)
            client.close_position(SYMBOL)
            print("✅ CLEANUP DONE")

        else:
            print("❌ POSITION FAIL: Not found after entry")

    except Exception as e:
        print(f"❌ CYCLE FAIL: {e}")
        # Emergency cleanup
        client.cancel_all_orders(SYMBOL)
        client.close_position(SYMBOL)

if __name__ == "__main__":
    run_test()
