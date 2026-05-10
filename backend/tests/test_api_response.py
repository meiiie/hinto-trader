"""
Test: API Response for Portfolio
"""
import requests

def check_api():
    print("=" * 60)
    print("CHECK: API Response")
    print("=" * 60)

    resp = requests.get("http://localhost:8000/trades/portfolio")
    data = resp.json()

    print(f"\n📊 API Response:")
    print(f"   Balance: ${data.get('balance', 0):,.2f}")
    print(f"   Open Positions: {len(data.get('open_positions', []))}")
    print(f"   Pending Orders: {len(data.get('pending_orders', []))}")

    pending = data.get('pending_orders', [])
    if pending:
        print(f"\n   📋 Pending Orders in API:")
        for order in pending:
            print(f"      - {order.get('symbol')}: {order.get('side')} @ ${order.get('entry_price'):,.2f}")
    else:
        print(f"\n   ❌ pending_orders is EMPTY in API response!")
        print(f"   Keys in response: {list(data.keys())}")

if __name__ == "__main__":
    check_api()
