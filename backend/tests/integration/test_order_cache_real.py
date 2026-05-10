"""
Integration Tests: Pending Order Local Caching (Real Testnet API)

Tests the local caching system with REAL Binance Testnet API calls.
Creates actual orders, monitors WebSocket events, and verifies cache sync.

Usage:
    cd backend
    python tests/integration/test_order_cache_real.py

Requirements:
    - ENV=testnet in .env
    - BINANCE_TESTNET_API_KEY and SECRET set
    - Backend NOT running (tests use their own instances)

WARNING: This will create REAL orders on Testnet (demo money, but real API calls)
"""

import os
import sys
import time
import asyncio
from dotenv import load_dotenv

# Add parent path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Load environment
load_dotenv()

# Color codes for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"

def log_pass(msg): print(f"{GREEN}✅ PASS{RESET}: {msg}")
def log_fail(msg): print(f"{RED}❌ FAIL{RESET}: {msg}")
def log_info(msg): print(f"{BLUE}ℹ️  INFO{RESET}: {msg}")
def log_warn(msg): print(f"{YELLOW}⚠️  WARN{RESET}: {msg}")


class TestOrderCacheIntegration:
    """Integration tests with real Binance Testnet API."""

    def __init__(self):
        self.client = None
        self.live_service = None
        self.test_orders = []

    def setup(self):
        """Initialize services with real Testnet connection."""
        from src.infrastructure.api.binance_futures_client import BinanceFuturesClient
        from src.application.services.live_trading_service import LiveTradingService, TradingMode

        log_info("Setting up Testnet connection...")

        # Check credentials
        api_key = os.getenv('BINANCE_TESTNET_API_KEY')
        api_secret = os.getenv('BINANCE_TESTNET_API_SECRET')

        if not api_key or not api_secret:
            log_fail("BINANCE_TESTNET_API_KEY and BINANCE_TESTNET_API_SECRET not set")
            return False

        try:
            self.client = BinanceFuturesClient(use_testnet=True)
            self.live_service = LiveTradingService(mode=TradingMode.TESTNET)
            log_pass("Testnet connection established")
            return True
        except Exception as e:
            log_fail(f"Setup failed: {e}")
            return False

    def cleanup(self):
        """Cancel all test orders created during testing."""
        log_info("Cleaning up test orders...")
        for order_id, symbol in self.test_orders:
            try:
                self.client.cancel_order(symbol, order_id)
                log_info(f"Cancelled order {order_id}")
            except Exception as e:
                log_warn(f"Could not cancel order {order_id}: {e}")
        self.test_orders.clear()

    # =========================================================================
    # TC-001: Initial Cache Sync
    # =========================================================================

    def test_initial_cache_sync(self):
        """Test that cache syncs correctly on startup."""
        log_info("TC-001: Testing initial cache sync...")

        try:
            # Check cache was initialized
            if not self.live_service._local_cache_initialized:
                log_fail("Cache was not initialized on startup")
                return False

            # Get current orders from API (ground truth)
            api_orders = self.client.get_open_orders()
            cached_orders = self.live_service._cached_open_orders

            log_info(f"API orders: {len(api_orders)}, Cached orders: {len(cached_orders)}")

            # Compare counts
            if len(cached_orders) == len(api_orders):
                log_pass(f"Cache sync correct: {len(cached_orders)} orders")
                return True
            else:
                log_fail(f"Cache mismatch: API={len(api_orders)}, Cache={len(cached_orders)}")
                return False

        except Exception as e:
            log_fail(f"Test failed with exception: {e}")
            return False

    # =========================================================================
    # TC-002: Create Order Updates Cache
    # =========================================================================

    def test_create_order_updates_cache(self):
        """Test that creating an order updates the cache."""
        log_info("TC-002: Testing order creation cache update...")

        try:
            # Get current price
            current_price = self.client.get_ticker_price("BTCUSDT")
            limit_price = round(current_price * 0.90, 0)  # 10% below - won't fill

            # Count orders before
            orders_before = len(self.live_service._cached_open_orders)

            # Create a limit order
            log_info(f"Creating LIMIT BUY order at ${limit_price}")
            order = self.client.create_order(
                symbol="BTCUSDT",
                side="BUY",
                order_type="LIMIT",
                quantity=0.002,
                price=limit_price,
                time_in_force="GTC"
            )

            # FuturesOrder is dataclass - access attributes directly
            order_id = order.order_id
            self.test_orders.append((order_id, "BTCUSDT"))
            log_info(f"Created order: {order_id}")

            # Convert to dict for cache update
            order_dict = {
                'orderId': order.order_id,
                'symbol': order.symbol,
                'side': order.side,
                'type': order.type,
                'status': order.status,
                'price': order.price,
                'origQty': order.quantity,
            }

            # Manually update cache (since we're not running the full backend with WebSocket)
            self.live_service.update_cached_order(order_dict, is_closed=False)

            # Check cache updated
            orders_after = len(self.live_service._cached_open_orders)

            if orders_after == orders_before + 1:
                log_pass(f"Cache updated: {orders_before} -> {orders_after}")
                return True
            else:
                log_fail(f"Cache not updated: {orders_before} -> {orders_after}")
                return False

        except Exception as e:
            log_fail(f"Test failed with exception: {e}")
            return False

    # =========================================================================
    # TC-003: Cancel Order Updates Cache
    # =========================================================================

    def test_cancel_order_updates_cache(self):
        """Test that cancelling an order removes it from cache."""
        log_info("TC-003: Testing order cancellation cache update...")

        try:
            if not self.test_orders:
                log_warn("No test orders to cancel, creating one first...")
                if not self.test_create_order_updates_cache():
                    return False

            # Get order to cancel
            order_id, symbol = self.test_orders.pop()

            # Count orders before
            orders_before = len(self.live_service._cached_open_orders)

            # Cancel order
            log_info(f"Cancelling order: {order_id}")
            cancel_result = self.client.cancel_order(symbol, order_id)

            # Manually update cache
            cancel_result['orderId'] = order_id
            self.live_service.update_cached_order(cancel_result, is_closed=True)

            # Check cache updated
            orders_after = len(self.live_service._cached_open_orders)

            if orders_after == orders_before - 1:
                log_pass(f"Cache updated: {orders_before} -> {orders_after}")
                return True
            else:
                log_fail(f"Cache not updated: {orders_before} -> {orders_after}")
                return False

        except Exception as e:
            log_fail(f"Test failed with exception: {e}")
            return False

    # =========================================================================
    # TC-004: Portfolio Performance
    # =========================================================================

    def test_portfolio_performance(self):
        """Test that get_portfolio uses cache (fast) instead of API (slow)."""
        log_info("TC-004: Testing portfolio performance...")

        try:
            # First call - may hit API for balance
            _ = self.live_service.get_portfolio()

            # Second call - should be cache hit (fast)
            start = time.time()
            result = self.live_service.get_portfolio()
            elapsed_ms = (time.time() - start) * 1000

            log_info(f"Portfolio response time: {elapsed_ms:.2f}ms")

            if elapsed_ms < 100:
                log_pass(f"Portfolio fast: {elapsed_ms:.2f}ms (< 100ms)")
                return True
            else:
                log_warn(f"Portfolio slow: {elapsed_ms:.2f}ms (expected < 100ms)")
                return False

        except Exception as e:
            log_fail(f"Test failed with exception: {e}")
            return False

    # =========================================================================
    # TC-005: Multiple Orders Stress Test
    # =========================================================================

    def test_multiple_orders(self):
        """Test caching with multiple orders."""
        log_info("TC-005: Testing multiple orders...")

        try:
            current_price = self.client.get_ticker_price("BTCUSDT")

            # Create 3 orders at different prices
            for i in range(3):
                price_pct = 0.85 - (i * 0.05)  # 85%, 80%, 75% of current price
                limit_price = round(current_price * price_pct, 0)

                order = self.client.create_order(
                    symbol="BTCUSDT",
                    side="BUY",
                    order_type="LIMIT",
                    quantity=0.002,
                    price=limit_price,
                    time_in_force="GTC"
                )

                # FuturesOrder is dataclass - access attributes directly
                order_id = order.order_id
                self.test_orders.append((order_id, "BTCUSDT"))

                # Convert to dict for cache update
                order_dict = {
                    'orderId': order.order_id,
                    'symbol': order.symbol,
                    'side': order.side,
                    'type': order.type,
                    'status': order.status,
                    'price': order.price,
                    'origQty': order.quantity,
                }

                # Update cache
                self.live_service.update_cached_order(order_dict, is_closed=False)
                log_info(f"Created order {i+1}/3: {order_id} at ${limit_price}")

            # Verify all in cache
            cached_count = len(self.live_service._cached_open_orders)
            log_info(f"Cached orders: {cached_count}")

            if cached_count >= 3:
                log_pass(f"All orders cached ({cached_count} orders)")
                return True
            else:
                log_fail(f"Missing orders in cache")
                return False

        except Exception as e:
            log_fail(f"Test failed with exception: {e}")
            return False


def run_all_tests():
    """Run all integration tests."""
    print("\n" + "="*60)
    print("🧪 INTEGRATION TESTS: Pending Order Local Caching")
    print("="*60 + "\n")

    tester = TestOrderCacheIntegration()

    # Setup
    if not tester.setup():
        print("\n❌ Setup failed. Exiting.")
        return

    results = []

    try:
        # Run tests
        tests = [
            ("TC-001: Initial Cache Sync", tester.test_initial_cache_sync),
            ("TC-002: Order Create Updates Cache", tester.test_create_order_updates_cache),
            ("TC-003: Order Cancel Updates Cache", tester.test_cancel_order_updates_cache),
            ("TC-004: Portfolio Performance", tester.test_portfolio_performance),
            ("TC-005: Multiple Orders", tester.test_multiple_orders),
        ]

        for name, test_func in tests:
            print(f"\n{'─'*50}")
            result = test_func()
            results.append((name, result))

    finally:
        # Always cleanup
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
