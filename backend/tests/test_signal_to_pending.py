"""
Test Script: Check Current Pending Orders
Shows what's actually in the CORRECT database (ENV-aware).
"""
import sys
import os

# Set ENV before importing
os.environ['ENV'] = 'paper'

sys.path.insert(0, 'e:\\Sach\\DuAn\\Hinto_Stock\\backend')

from src.infrastructure.persistence.sqlite_order_repository import SQLiteOrderRepository

def check_pending_orders():
    print("=" * 60)
    print("CHECK: Current Database State (ENV=paper)")
    print("=" * 60)

    # Use correct path: data/paper/trading_system.db
    db_path = "data/paper/trading_system.db"
    print(f"📁 Database: {db_path}")

    repo = SQLiteOrderRepository(db_path=db_path)

    # Get all pending orders
    pending = repo.get_pending_orders()

    print(f"\n📊 Found {len(pending)} PENDING orders:")

    for i, order in enumerate(pending, 1):
        print(f"\n   [{i}] {order.symbol}")
        print(f"       ID: {order.id[:8]}...")
        print(f"       Side: {order.side}")
        print(f"       Status: {order.status}")
        print(f"       Entry: ${order.entry_price:,.2f}")
        print(f"       SL: ${order.stop_loss or 0:,.2f}")
        print(f"       TP: ${order.take_profit or 0:,.2f}")
        print(f"       Quantity: {order.quantity}")
        print(f"       Open Time: {order.open_time}")

    print("\n" + "=" * 60)

    # Now check the OLD database that has the 3 orders
    print("\n📊 Checking OLD database (data/trading_system.db):")
    old_repo = SQLiteOrderRepository(db_path="data/trading_system.db")
    old_pending = old_repo.get_pending_orders()
    print(f"   Found {len(old_pending)} PENDING orders in OLD database")

    if len(old_pending) > 0 and len(pending) == 0:
        print("\n⚠️  FOUND THE ISSUE!")
        print("   Old database has pending orders, but API uses new ENV-aware path.")
        print("   Options:")
        print("   1. Copy data from old DB to new: data/paper/trading_system.db")
        print("   2. Stay with new DB (fresh start)")

if __name__ == "__main__":
    check_pending_orders()
