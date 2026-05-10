"""
Test Script: Close TAOUSDT Position with MARKET_LOT_SIZE Split

This script tests the fix for the -4005 "Quantity greater than max quantity" error.
It directly calls LiveTradingService.close_position() which uses split_quantity_market().

TAOUSDT on Testnet:
- LOT_SIZE maxQty = 300 (for LIMIT orders)
- MARKET_LOT_SIZE maxQty = 50 (for MARKET/STOP_MARKET orders)

Expected: 56.984 should be split into [50.0, 6.984]
"""

import asyncio
import os
import sys

# Add backend to path
backend_path = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, backend_path)

# Load environment variables from .env (try multiple paths)
from dotenv import load_dotenv
env_paths = [
    os.path.join(backend_path, '.env'),
    os.path.join(backend_path, '..', '.env'),
    '.env'
]
for env_path in env_paths:
    if os.path.exists(env_path):
        load_dotenv(env_path)
        print(f"✅ Loaded .env from: {env_path}")
        break

# Set testnet mode explicitly
os.environ['BINANCE_USE_TESTNET'] = 'true'
os.environ['ENV'] = 'testnet'

from src.application.services.live_trading_service import LiveTradingService, TradingMode
from src.infrastructure.exchange.exchange_filter_service import ExchangeFilterService


def test_split_quantity_market():
    """Test the split_quantity_market function directly."""
    print("\n" + "="*60)
    print("TEST 1: split_quantity_market() for TAOUSDT")
    print("="*60)

    # Initialize filter service
    filter_service = ExchangeFilterService(use_testnet=True)

    # Load filters from API
    from src.infrastructure.api.binance_futures_client import BinanceFuturesClient
    client = BinanceFuturesClient(use_testnet=True)
    filter_service.load_filters(client)

    # Get TAOUSDT filters
    filters = filter_service.get_filters("TAOUSDT")
    if filters:
        print(f"LOT_SIZE maxQty: {filters.max_qty}")
        print(f"MARKET_LOT_SIZE maxQty: {filters.market_max_qty}")
    else:
        print("❌ No filters loaded for TAOUSDT!")
        return False

    # Test split_quantity_market
    test_qty = 56.984
    chunks = filter_service.split_quantity_market("TAOUSDT", test_qty)

    print(f"\nQuantity: {test_qty}")
    print(f"Split result: {chunks}")
    print(f"Sum of chunks: {sum(chunks)}")

    # Verify
    if len(chunks) > 1:
        print("✅ PASS: Quantity was split correctly!")
        return True
    else:
        print("❌ FAIL: Quantity was NOT split!")
        return False


def test_close_position():
    """Test closing TAOUSDT position via LiveTradingService."""
    print("\n" + "="*60)
    print("TEST 2: LiveTradingService.close_position('TAOUSDT')")
    print("="*60)

    # Initialize service
    service = LiveTradingService(
        mode=TradingMode.TESTNET,
        max_positions=10,
        max_leverage=10,
        risk_per_trade=0.01
    )

    # Check if position exists
    positions = service.client.get_positions("TAOUSDT")
    if not positions:
        print("⚠️ No TAOUSDT position to close")
        return None

    pos = positions[0]
    if pos.position_amt == 0:
        print("⚠️ TAOUSDT position already closed (qty=0)")
        return None

    print(f"Found position: {pos.position_amt} TAOUSDT @ {pos.entry_price}")

    # Close position using the FIXED method
    print("\n🚀 Calling service.close_position('TAOUSDT')...")
    result = service.close_position("TAOUSDT")

    if result.success:
        print(f"✅ SUCCESS: {result}")
        return True
    else:
        print(f"❌ FAILED: {result.error}")
        return False


if __name__ == "__main__":
    print("\n" + "#"*60)
    print("# TESTNET CLOSE POSITION TEST")
    print("# Testing MARKET_LOT_SIZE split fix for -4005 error")
    print("#"*60)

    # Test 1: Split function
    split_ok = test_split_quantity_market()

    # Test 2: Actually close position (only if split works)
    if split_ok:
        close_result = test_close_position()

        if close_result is True:
            print("\n" + "="*60)
            print("🎉 ALL TESTS PASSED!")
            print("="*60)
        elif close_result is None:
            print("\n⚠️ No position to close, but split logic verified.")
        else:
            print("\n❌ CLOSE TEST FAILED - Check logs above")
    else:
        print("\n❌ SPLIT TEST FAILED - Fix required before closing")
