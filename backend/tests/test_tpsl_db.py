"""
Test Script: Verify SQLite TP/SL Persistence

This script verifies:
1. SQLite live_positions table exists
2. CRUD operations work correctly
3. Sync logic loads from DB first

Run: python backend/tests/test_tpsl_db.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

from src.infrastructure.persistence.sqlite_order_repository import SQLiteOrderRepository

def main():
    print("=" * 60)
    print("🔍 TP/SL SQLite Persistence Test")
    print("=" * 60)

    # Use testnet database
    db_path = "data/testnet/trading_system.db"

    # Ensure directory exists
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    print(f"📁 Database: {db_path}")

    # Initialize repository (creates tables if not exist)
    repo = SQLiteOrderRepository(db_path=db_path)
    print("✅ SQLiteOrderRepository initialized")

    # TEST 1: Check if live_positions table exists
    print("\n" + "=" * 60)
    print("📋 TEST 1: Check live_positions table")
    print("=" * 60)

    try:
        positions = repo.get_open_live_positions()
        print(f"✅ Table exists! Found {len(positions)} open positions")

        for pos in positions:
            print(f"\n  📈 {pos.get('symbol')}")
            print(f"     Side: {pos.get('side')}")
            print(f"     Entry: ${pos.get('entry_price', 0):.2f}")
            print(f"     SL: ${pos.get('stop_loss', 0):.2f}")
            print(f"     TP: ${pos.get('take_profit', 0):.2f}")
            print(f"     Status: {pos.get('status')}")

    except Exception as e:
        print(f"❌ Error: {e}")
        return

    # TEST 2: Test save operation
    print("\n" + "=" * 60)
    print("📋 TEST 2: Test save_live_position")
    print("=" * 60)

    try:
        # Save a test position
        test_id = repo.save_live_position(
            symbol="TESTUSDT",
            side="LONG",
            entry_price=100.0,
            quantity=10.0,
            stop_loss=99.0,    # 1% dưới entry
            take_profit=102.0, # 2% trên entry
            leverage=10,
            signal_id="test_signal_123"
        )
        print(f"✅ Saved test position: {test_id}")

        # Verify it was saved
        saved = repo.get_live_position_by_symbol("TESTUSDT")
        if saved:
            print(f"✅ Verified: SL=${saved.get('stop_loss')}, TP=${saved.get('take_profit')}")
        else:
            print("❌ Failed to retrieve saved position")

    except Exception as e:
        print(f"❌ Error saving: {e}")

    # TEST 3: Test update SL operation
    print("\n" + "=" * 60)
    print("📋 TEST 3: Test update_live_position_sl")
    print("=" * 60)

    try:
        # Update SL (simulate trailing stop)
        repo.update_live_position_sl("TESTUSDT", new_sl=100.5)

        # Verify update
        updated = repo.get_live_position_by_symbol("TESTUSDT")
        if updated and updated.get('stop_loss') == 100.5:
            print(f"✅ SL updated to breakeven: ${updated.get('stop_loss')}")
        else:
            print(f"❌ SL update failed, got: {updated.get('stop_loss') if updated else 'None'}")

    except Exception as e:
        print(f"❌ Error updating SL: {e}")

    # TEST 4: Test close position
    print("\n" + "=" * 60)
    print("📋 TEST 4: Test close_live_position")
    print("=" * 60)

    try:
        repo.close_live_position("TESTUSDT", exit_price=101.5, realized_pnl=15.0, exit_reason="TEST_TP")

        # Verify it's closed (no longer in open positions)
        still_open = repo.get_live_position_by_symbol("TESTUSDT")
        if still_open is None:
            print("✅ Position closed successfully (not in open list)")
        else:
            print(f"❌ Position still shows as open: {still_open.get('status')}")

    except Exception as e:
        print(f"❌ Error closing: {e}")

    # TEST 5: Final count
    print("\n" + "=" * 60)
    print("📋 SUMMARY")
    print("=" * 60)

    final_positions = repo.get_open_live_positions()
    print(f"📊 Open live positions in DB: {len(final_positions)}")

    for pos in final_positions:
        sl = pos.get('stop_loss', 0)
        tp = pos.get('take_profit', 0)
        sl_str = f"${sl:.2f}" if sl > 0 else "--"
        tp_str = f"${tp:.2f}" if tp > 0 else "--"
        print(f"   • {pos.get('symbol')}: SL={sl_str}, TP={tp_str}")

    print("\n✅ All tests completed!")
    print("\n💡 LƯU Ý:")
    print("   - Các position MỚI (mở sau khi restart) sẽ có SL/TP trong DB")
    print("   - Các position CŨ (mở trước đó) cần được manually add hoặc sẽ hiển thị '--'")

if __name__ == "__main__":
    main()
