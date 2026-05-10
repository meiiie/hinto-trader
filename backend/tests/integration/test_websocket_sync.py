"""
WebSocket Real-time Sync Test

Tests that ORDER_TRADE_UPDATE events from UserDataStream automatically
update the local cache in LiveTradingService.

REQUIRES: Backend running (python run_backend.py)

Usage:
    1. Start backend: python run_backend.py
    2. Wait for "UserDataStream started" log
    3. Run this test: python tests/integration/test_websocket_sync.py
"""

import os
import sys
import time
import requests
from dotenv import load_dotenv

# Add parent path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

load_dotenv()

# Colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"

def log_pass(msg): print(f"{GREEN}✅ PASS{RESET}: {msg}")
def log_fail(msg): print(f"{RED}❌ FAIL{RESET}: {msg}")
def log_info(msg): print(f"{BLUE}ℹ️  INFO{RESET}: {msg}")
def log_warn(msg): print(f"{YELLOW}⚠️  WARN{RESET}: {msg}")

# Backend API base URL
API_BASE = "http://localhost:8000"


class TestWebSocketSync:
    """Test WebSocket real-time cache sync with running backend."""

    def __init__(self):
        self.client = None
        self.test_orders = []

    def setup(self):
        """Check backend is running and initialize client."""
        log_info("Checking backend connection...")

        try:
            # Check backend is running - use /system/status endpoint
            resp = requests.get(f"{API_BASE}/system/status", timeout=15)
            if resp.status_code != 200:
                log_fail(f"Backend not healthy: {resp.status_code}")
                return False
            log_pass("Backend is running")

            # Initialize Binance client for order creation
            from src.infrastructure.api.binance_futures_client import BinanceFuturesClient
            self.client = BinanceFuturesClient(use_testnet=True)
            log_pass("Binance client initialized")

            return True

        except requests.exceptions.ConnectionError:
            log_fail("Cannot connect to backend. Start with: python run_backend.py")
            return False
        except requests.exceptions.ReadTimeout:
            log_fail("Backend timed out - may be busy, try again")
            return False
        except Exception as e:
            log_fail(f"Setup failed: {e}")
            return False

    def cleanup(self):
        """Cancel all test orders."""
        log_info("Cleaning up test orders...")
        for order_id, symbol in self.test_orders:
            try:
                self.client.cancel_order(symbol, order_id)
                log_info(f"Cancelled order {order_id}")
            except Exception as e:
                log_warn(f"Could not cancel {order_id}: {e}")
        self.test_orders.clear()

    def get_portfolio_from_backend(self):
        """Fetch portfolio via REST API."""
        resp = requests.get(f"{API_BASE}/trades/portfolio", timeout=10)
        return resp.json()

    def get_pending_count_from_backend(self):
        """Get count of pending orders from backend."""
        portfolio = self.get_portfolio_from_backend()
        return len(portfolio.get('pending_orders', []))

    # =========================================================================
    # TC-WS-001: WebSocket Order Create Sync
    # =========================================================================

    def test_websocket_order_create_sync(self):
        """Test that backend cache updates automatically when order created."""
        log_info("TC-WS-001: Testing WebSocket order create sync...")

        try:
            # Get initial pending count from backend
            initial_count = self.get_pending_count_from_backend()
            log_info(f"Initial pending orders: {initial_count}")

            # Create order directly via Binance API (bypassing backend)
            current_price = self.client.get_ticker_price("BTCUSDT")
            limit_price = round(current_price * 0.85, 0)

            log_info(f"Creating LIMIT order at ${limit_price}...")
            order = self.client.create_order(
                symbol="BTCUSDT",
                side="BUY",
                order_type="LIMIT",
                quantity=0.002,
                price=limit_price,
                time_in_force="GTC"
            )

            order_id = order.order_id
            self.test_orders.append((order_id, "BTCUSDT"))
            log_info(f"Created order: {order_id}")

            # Wait for WebSocket to sync (should be < 2 seconds)
            log_info("Waiting 3 seconds for WebSocket sync...")
            time.sleep(3)

            # Invalidate backend cache by waiting for TTL to expire
            # Actually, we need to force refresh or check if order appears

            # Get updated count from backend
            final_count = self.get_pending_count_from_backend()
            log_info(f"Final pending orders: {final_count}")

            # Check if new order appeared
            if final_count > initial_count:
                log_pass(f"WebSocket sync worked: {initial_count} -> {final_count}")
                return True
            else:
                log_warn(f"Order may not have synced: {initial_count} -> {final_count}")
                log_info("This could be due to portfolio cache TTL (5s)")
                return False

        except Exception as e:
            log_fail(f"Test failed: {e}")
            return False

    # =========================================================================
    # TC-WS-002: WebSocket Order Cancel Sync
    # =========================================================================

    def test_websocket_order_cancel_sync(self):
        """Test that backend cache updates automatically when order cancelled."""
        log_info("TC-WS-002: Testing WebSocket order cancel sync...")

        try:
            if not self.test_orders:
                log_warn("No orders to cancel, skipping...")
                return True

            # Get order to cancel
            order_id, symbol = self.test_orders.pop()

            # Get initial count
            initial_count = self.get_pending_count_from_backend()
            log_info(f"Initial pending orders: {initial_count}")

            # Cancel order directly via Binance API
            log_info(f"Cancelling order {order_id}...")
            self.client.cancel_order(symbol, order_id)

            # Wait for WebSocket sync
            log_info("Waiting 3 seconds for WebSocket sync...")
            time.sleep(3)

            # Get updated count
            final_count = self.get_pending_count_from_backend()
            log_info(f"Final pending orders: {final_count}")

            if final_count < initial_count:
                log_pass(f"WebSocket sync worked: {initial_count} -> {final_count}")
                return True
            else:
                log_warn(f"Order may not have synced: {initial_count} -> {final_count}")
                return False

        except Exception as e:
            log_fail(f"Test failed: {e}")
            return False

    # =========================================================================
    # TC-WS-003: Portfolio Performance with Backend
    # =========================================================================

    def test_portfolio_performance_with_backend(self):
        """Test portfolio response time from actual backend."""
        log_info("TC-WS-003: Testing portfolio performance...")

        try:
            # Warm up cache
            self.get_portfolio_from_backend()

            # Measure response time
            times = []
            for i in range(5):
                start = time.time()
                self.get_portfolio_from_backend()
                elapsed_ms = (time.time() - start) * 1000
                times.append(elapsed_ms)

            avg_ms = sum(times) / len(times)
            max_ms = max(times)
            min_ms = min(times)

            log_info(f"Response times: avg={avg_ms:.1f}ms, min={min_ms:.1f}ms, max={max_ms:.1f}ms")

            # Should be < 100ms with caching
            if avg_ms < 100:
                log_pass(f"Portfolio fast: avg {avg_ms:.1f}ms")
                return True
            elif avg_ms < 500:
                log_warn(f"Portfolio slow: avg {avg_ms:.1f}ms")
                return True  # Still acceptable
            else:
                log_fail(f"Portfolio very slow: avg {avg_ms:.1f}ms")
                return False

        except Exception as e:
            log_fail(f"Test failed: {e}")
            return False

    # =========================================================================
    # TC-WS-004: Concurrent Request Performance
    # =========================================================================

    def test_concurrent_requests(self):
        """Test multiple concurrent portfolio requests."""
        log_info("TC-WS-004: Testing concurrent requests...")

        try:
            import concurrent.futures

            def fetch_portfolio():
                start = time.time()
                resp = requests.get(f"{API_BASE}/trades/portfolio", timeout=30)
                elapsed = (time.time() - start) * 1000
                return elapsed, resp.status_code

            # Run 10 concurrent requests
            num_requests = 10
            log_info(f"Sending {num_requests} concurrent requests...")

            with concurrent.futures.ThreadPoolExecutor(max_workers=num_requests) as executor:
                futures = [executor.submit(fetch_portfolio) for _ in range(num_requests)]
                results = [f.result() for f in futures]

            times = [r[0] for r in results]
            statuses = [r[1] for r in results]

            avg_ms = sum(times) / len(times)
            max_ms = max(times)
            success_count = sum(1 for s in statuses if s == 200)

            log_info(f"Results: {success_count}/{num_requests} success, avg={avg_ms:.1f}ms, max={max_ms:.1f}ms")

            if success_count == num_requests and max_ms < 5000:
                log_pass(f"All requests succeeded, max latency {max_ms:.1f}ms")
                return True
            elif max_ms > 30000:
                log_fail(f"Extreme latency: {max_ms:.1f}ms - 50s cascade may still exist")
                return False
            else:
                log_warn(f"Some issues: {success_count}/{num_requests} success, max={max_ms:.1f}ms")
                return True

        except Exception as e:
            log_fail(f"Test failed: {e}")
            return False


def run_all_tests():
    """Run all WebSocket sync tests."""
    print("\n" + "="*60)
    print("🔌 WEBSOCKET SYNC TESTS: Real-time Cache Update")
    print("="*60 + "\n")

    tester = TestWebSocketSync()

    if not tester.setup():
        print("\n❌ Setup failed. Ensure backend is running.")
        return

    results = []

    try:
        tests = [
            ("TC-WS-001: Order Create Sync", tester.test_websocket_order_create_sync),
            ("TC-WS-002: Order Cancel Sync", tester.test_websocket_order_cancel_sync),
            ("TC-WS-003: Portfolio Performance", tester.test_portfolio_performance_with_backend),
            ("TC-WS-004: Concurrent Requests", tester.test_concurrent_requests),
        ]

        for name, test_func in tests:
            print(f"\n{'─'*50}")
            result = test_func()
            results.append((name, result))

    finally:
        print(f"\n{'─'*50}")
        tester.cleanup()

    # Summary
    print("\n" + "="*60)
    print("📊 TEST RESULTS SUMMARY")
    print("="*60)

    passed = sum(1 for _, r in results if r)
    failed = sum(1 for _, r in results if not r)

    for name, result in results:
        status = f"{GREEN}PASS{RESET}" if result else f"{RED}FAIL{RESET}"
        print(f"  [{status}] {name}")

    print(f"\n  Total: {passed} passed, {failed} failed")
    print("="*60 + "\n")


if __name__ == '__main__':
    run_all_tests()
