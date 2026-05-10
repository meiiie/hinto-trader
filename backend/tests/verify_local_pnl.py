"""
Script to verify LOCAL PnL Tracking logic (LocalPositionTracker).
Simulates the exact BTRUSDT loss scenario to confirm fix.

Scenario:
- Symbol: BTRUSDT
- Side: LONG
- Intended Leverage: 20x
- Actual Leverage: 10x
- Entry: 9 partial fills
- Fees: ~$0.52 total
- Exit Check: Price moves up slightly
"""
import sys
import os
from datetime import datetime

# Add project root to path
# Assuming script is run from backend/ directory or root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from domain.entities.local_position_tracker import LocalPosition, FillRecord

def test_btrusdt_scenario():
    print("🧪 TEST: BTRUSDT Loss Scenario (Binance vs LOCAL)\n")

    # 1. Create Position (Intended 20x)
    pos = LocalPosition(symbol="BTRUSDT", side="LONG", intended_leverage=20)
    print(f"1. Position Created: {pos.symbol} {pos.side} (Intended Lev: {pos.intended_leverage}x)")

    # 2. Simulate 9 Partial Fills (from logs)
    # Total Qty: 4952.0
    # Avg Price: 0.1292755 (approx)
    # Total Fees: ~$0.26 (0.04% taker fee standard)

    # Simulating data close to the real event
    fills = [
        (0.1292100, 500.0, 0.0258),
        (0.1292200, 500.0, 0.0258),
        (0.1292500, 1000.0, 0.0517),
        (0.1292800, 1000.0, 0.0517),
        (0.1293000, 1000.0, 0.0517),
        (0.1293500, 952.0, 0.0492),
    ]

    print("\n2. Simulating Entry Fills...")
    for p, q, f in fills:
        fill = FillRecord(
            timestamp=datetime.now(),
            order_id="123",
            price=p,
            quantity=q,
            fee=f
        )
        pos.add_entry_fill(fill)

    summary = pos.get_summary(0.1293000)
    print(f"   Avg Entry: ${summary['avg_entry_price']:.7f}")
    print(f"   Total Qty: {summary['total_quantity']:.1f}")
    print(f"   Total Fees: ${summary['total_entry_fees']:.4f}")

    # 3. Set ACTUAL Leverage (10x)
    print("\n3. Setting ACTUAL Leverage (10x)...")
    pos.set_actual_leverage(10)
    if pos._actual_margin_used:
        print(f"   Actual Margin: ${pos._actual_margin_used:.2f}")

    # 4. Check PnL at Trigger Price (Binance showed $2.19 here)
    # Price where Binance showed 6.83% ROE
    # 6.83% of $32 margin = $2.19
    # $2.19 / 4952 qty = $0.00044 price diff
    # Trigger Price ≈ 0.1292755 + 0.00044 = 0.1297155
    trigger_price = 0.12972

    print(f"\n4. Checking PnL at Trigger Price: ${trigger_price:.6f}")

    # BINANCE PnL (Approx: No fees, Mark Price, Wrong Lev)
    binance_pnl = (trigger_price - 0.1292755) * 4952.0
    binance_roe_wrong = (binance_pnl / 32.0) * 100  # 20x margin ($32)

    print(f"   [BINANCE SIMULATION]")
    print(f"   PnL (No Fees): ${binance_pnl:.2f}")
    print(f"   ROE (Wrong 20x): {binance_roe_wrong:.2f}%")
    print(f"   Decision: CLOSE ✅ (>{5.0}%)")

    # LOCAL PnL (Correct: Fees, Fill Price, Actual Lev)
    local_pnl = pos.get_unrealized_pnl(trigger_price)
    local_roe = pos.get_roe_percent(trigger_price)

    print(f"\n   [LOCAL REALITY]")
    if pos._avg_entry_price:
        print(f"   Gross PnL: ${(trigger_price - pos._avg_entry_price) * pos._total_entry_qty:.2f}")
    print(f"   Fees: -${pos._total_entry_fees:.2f}")
    print(f"   Net PnL: ${local_pnl:.2f}")
    print(f"   ROE (Actual 10x): {local_roe:.2f}%")

    print(f"\n5. Decision Check")
    if local_roe >= 17.0:
        print("   AUTO_CLOSE: TRIGGERED ❌ (Should not happen)")
    else:
        print("   AUTO_CLOSE: WAIT ✅ (Correct)")

if __name__ == "__main__":
    test_btrusdt_scenario()
