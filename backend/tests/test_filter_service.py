"""
Test Script: Exchange Filter Service & Order Sanitization
Author: SOTA Architect
Date: 2026-01-06

Tests:
1. Filter loading from API (Testnet)
2. split_quantity - splits large orders into chunks
3. sanitize_quantity - rounds to proper precision
4. sanitize_price - rounds to proper tick size
5. End-to-end batch payload sanitization
"""

import os
import sys
from decimal import Decimal

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.infrastructure.exchange.exchange_filter_service import ExchangeFilterService


def test_filter_loading():
    """Test filter loading from cache file."""
    print("\n" + "="*60)
    print("TEST 1: Filter Loading from Cache")
    print("="*60)

    service = ExchangeFilterService(use_testnet=True)
    loaded = service.load_from_file()

    print(f"Loaded from file: {loaded}")
    print(f"Symbols loaded: {len(service._filters)}")

    # Check specific symbols
    test_symbols = ['BTCUSDT', 'ETHUSDT', 'XRPUSDT', 'TAOUSDT', 'SOLUSDT']
    for sym in test_symbols:
        filters = service.get_filters(sym)
        if filters.symbol == sym:
            print(f"  ✅ {sym}: maxQty={filters.max_qty}, step={filters.step_size}, qty_precision={filters.qty_precision}")
        else:
            print(f"  ⚠️ {sym}: Using DEFAULT filters (not in cache)")

    return loaded


def test_split_quantity():
    """Test quantity splitting for large orders."""
    print("\n" + "="*60)
    print("TEST 2: split_quantity (Order Splitting)")
    print("="*60)

    service = ExchangeFilterService(use_testnet=True)
    service.load_from_file()

    # Test cases
    test_cases = [
        ('TAOUSDT', 56.61),   # Should split if maxQty=50 (but cache has 5000)
        ('BTCUSDT', 0.5),    # Should NOT split (below max)
        ('XRPUSDT', 1265.4), # May or may not split
        ('ETHUSDT', 200.0),  # Test large ETH quantity
        ('TAOUSDT', 15000.0), # MEGA ORDER: Should split (3 chunks of 5000)
    ]

    for symbol, qty in test_cases:
        filters = service.get_filters(symbol)
        chunks = service.split_quantity(symbol, qty)

        status = "✅ SPLIT" if len(chunks) > 1 else "➖ NO SPLIT"
        print(f"  {status} {symbol}: {qty} → {chunks} (maxQty={filters.max_qty})")

        # Verify total matches
        total = sum(chunks)
        if abs(total - qty) < 0.0001:
            print(f"       ✅ Total matches: {total}")
        else:
            print(f"       ❌ Total mismatch: {total} vs {qty}")


def test_sanitize_quantity():
    """Test quantity sanitization (precision rounding)."""
    print("\n" + "="*60)
    print("TEST 3: sanitize_quantity (Precision Rounding)")
    print("="*60)

    service = ExchangeFilterService(use_testnet=True)
    service.load_from_file()

    # Test cases with intentionally "bad" precision
    test_cases = [
        ('XRPUSDT', 1265.4),      # XRP has qty_precision=1 → 1265.0
        ('XRPUSDT', 1265.789),    # Should round to 1265.0
        ('BTCUSDT', 0.00345678),  # BTC has qty_precision=3 → 0.003
        ('DOGEUSDT', 123.456789), # DOGE has higher precision
    ]

    for symbol, qty in test_cases:
        filters = service.get_filters(symbol)
        sanitized = service.sanitize_quantity(symbol, qty)

        print(f"  {symbol}: {qty} → {sanitized}")
        print(f"       step={filters.step_size}, precision={filters.qty_precision}")

        # Verify no precision error would occur
        qty_str = f"{sanitized:f}" # Use format to avoid scientific notation and get full string
        if '.' in qty_str:
            decimal_part = qty_str.split('.')[-1].rstrip('0')
            decimal_places = len(decimal_part)
        else:
            decimal_places = 0

        if decimal_places <= filters.qty_precision:
            print(f"       ✅ Valid precision: {decimal_places} <= {filters.qty_precision}")
        else:
            print(f"       ❌ PRECISION ERROR: {decimal_places} > {filters.qty_precision}")


def test_sanitize_price():
    """Test price sanitization (tick size rounding)."""
    print("\n" + "="*60)
    print("TEST 4: sanitize_price (Tick Size Rounding)")
    print("="*60)

    service = ExchangeFilterService(use_testnet=True)
    service.load_from_file()

    test_cases = [
        ('BTCUSDT', 97523.456789),
        ('ETHUSDT', 3456.789),
        ('XRPUSDT', 2.123456),
        ('TAOUSDT', 264.12775),
    ]

    for symbol, price in test_cases:
        filters = service.get_filters(symbol)
        sanitized = service.sanitize_price(symbol, price)

        print(f"  {symbol}: {price} → {sanitized}")
        print(f"       tick={filters.tick_size}, precision={filters.price_precision}")


def test_end_to_end_batch():
    """Test full batch payload generation with sanitization."""
    print("\n" + "="*60)
    print("TEST 5: End-to-End Batch Payload Generation")
    print("="*60)

    service = ExchangeFilterService(use_testnet=True)
    service.load_from_file()

    # Simulate what execute_signal does
    symbol = 'XRPUSDT'
    raw_quantity = 1265.4
    raw_price = 2.123456

    print(f"\n  Input: {symbol} qty={raw_quantity}, price={raw_price}")

    # Split quantity
    qty_chunks = service.split_quantity(symbol, raw_quantity)
    print(f"  Split: {qty_chunks}")

    # Build batch payload (like execute_signal)
    batch_payload = []
    for chunk in qty_chunks:
        sanitized_qty = service.sanitize_quantity(symbol, chunk)
        sanitized_price = service.sanitize_price(symbol, raw_price)

        params = {
            "symbol": symbol.upper(),
            "side": "BUY",
            "type": "LIMIT",
            "quantity": str(sanitized_qty),
            "price": str(sanitized_price),
            "timeInForce": "GTC"
        }
        batch_payload.append(params)
        print(f"  Order: qty={sanitized_qty}, price={sanitized_price}")

    print(f"\n  Batch payload ({len(batch_payload)} orders):")
    for i, p in enumerate(batch_payload):
        print(f"    {i+1}. {p}")

    # Validate
    for p in batch_payload:
        qty_str = p['quantity']
        price_str = p['price']

        # Check for excessive decimals
        qty_decimals = len(qty_str.split('.')[-1]) if '.' in qty_str else 0
        price_decimals = len(price_str.split('.')[-1]) if '.' in price_str else 0

        filters = service.get_filters(symbol)
        if qty_decimals <= filters.qty_precision and price_decimals <= filters.price_precision:
            print(f"  ✅ VALID: qty has {qty_decimals} decimals, price has {price_decimals} decimals")
        else:
            print(f"  ❌ INVALID: Would cause -1111 error")


def test_api_loading():
    """Test loading filters directly from Binance API (Testnet)."""
    print("\n" + "="*60)
    print("TEST 6: API Filter Loading (Testnet)")
    print("="*60)

    try:
        from src.infrastructure.api.binance_futures_client import BinanceFuturesClient

        client = BinanceFuturesClient(use_testnet=True)
        service = ExchangeFilterService(use_testnet=True)

        loaded = service.load_filters(client)
        print(f"Loaded from API: {loaded}")
        print(f"Symbols loaded: {len(service._filters)}")

        # Check TAOUSDT specifically
        filters = service.get_filters('TAOUSDT')
        if filters.symbol == 'TAOUSDT':
            print(f"  ✅ TAOUSDT from API: maxQty={filters.max_qty}, step={filters.step_size}")
        else:
            print(f"  ⚠️ TAOUSDT using DEFAULT: maxQty={filters.max_qty}")

    except Exception as e:
        print(f"  ❌ API test failed: {e}")
        print("     (This is expected if no API keys or network issues)")


if __name__ == '__main__':
    print("="*60)
    print(" SOTA TEST SUITE: Exchange Filter Service")
    print(" Date: 2026-01-06")
    print("="*60)

    try:
        test_filter_loading()
        test_split_quantity()
        test_sanitize_quantity()
        test_sanitize_price()
        test_end_to_end_batch()
        test_api_loading()

        print("\n" + "="*60)
        print(" ALL TESTS COMPLETED")
        print("="*60)

    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
