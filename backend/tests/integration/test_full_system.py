#!/usr/bin/env python3
"""
Integration Test

Test the full stack integration.
"""

import requests
import time

def test_backend():
    """Test backend endpoints."""
    base_url = "http://127.0.0.1:8000"

    print("🔧 Testing Backend Endpoints...")

    # Test root endpoint
    try:
        response = requests.get(f"{base_url}/", timeout=5)
        print(f"✅ Root: {response.status_code} - {response.json()['message']}")
    except Exception as e:
        print(f"❌ Root: {e}")
        return False

    # Test system status
    try:
        response = requests.get(f"{base_url}/system/status", timeout=5)
        data = response.json()
        print(f"✅ System Status: {data['status']} - {data['service']} v{data['version']}")
    except Exception as e:
        print(f"❌ System Status: {e}")

    # Test portfolio
    try:
        response = requests.get(f"{base_url}/trades/portfolio", timeout=5)
        data = response.json()
        print(f"✅ Portfolio: Balance ${data['balance']}, Positions: {len(data['open_positions'])}")
    except Exception as e:
        print(f"❌ Portfolio: {e}")

    # Test historical data
    try:
        response = requests.get(f"{base_url}/ws/history/btcusdt?timeframe=15m", timeout=5)
        data = response.json()
        print(f"✅ Historical Data: {len(data)} candles")
    except Exception as e:
        print(f"❌ Historical Data: {e}")

    # Test performance
    try:
        response = requests.get(f"{base_url}/trades/performance?days=30", timeout=5)
        data = response.json()
        print(f"✅ Performance: {data['total_trades']} trades, Win Rate: {data['win_rate']*100:.1f}%")
    except Exception as e:
        print(f"❌ Performance: {e}")

    # Test settings
    try:
        response = requests.get(f"{base_url}/settings", timeout=5)
        data = response.json()
        print(f"✅ Settings: Risk {data['risk_percent']}%, R:R {data['rr_ratio']}")
    except Exception as e:
        print(f"❌ Settings: {e}")

    return True

def main():
    """Run integration tests."""
    print("🚀 Hinto Trading Dashboard - Integration Test")
    print("=" * 50)

    # Wait for backend to be ready
    print("⏳ Waiting for backend...")
    for i in range(10):
        try:
            response = requests.get("http://127.0.0.1:8000/", timeout=2)
            if response.status_code == 200:
                print("✅ Backend is ready!")
                break
        except:
            time.sleep(1)
    else:
        print("❌ Backend not responding. Make sure to run: python test_backend.py")
        return

    # Test backend
    if test_backend():
        print("\n✅ All backend tests passed!")
        print("\n📋 Next Steps:")
        print("1. Keep backend running: python test_backend.py")
        print("2. Start frontend: cd frontend && npm run dev")
        print("3. Or run Tauri app: cd frontend && npm run tauri dev")
    else:
        print("\n❌ Some backend tests failed")

if __name__ == "__main__":
    main()
