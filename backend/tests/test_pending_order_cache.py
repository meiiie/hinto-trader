"""
Test Script: Pending Order Local Caching

Tests the local caching system for orders and positions that eliminates
50s lag in get_portfolio() by using local state instead of Binance API.

Usage:
    cd backend
    python -m pytest tests/test_pending_order_cache.py -v

Requirements:
    - ENV=testnet in .env
    - BINANCE_TESTNET_API_KEY and SECRET set
    - Backend NOT running (tests use their own instances)
"""

import os
import sys
import time
import asyncio
import threading
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

# Add parent path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.application.services.live_trading_service import LiveTradingService, TradingMode


class TestLocalCacheInitialization:
    """TC-001: Verify cache initializes on startup."""

    def test_cache_attributes_exist(self):
        """Verify cache attributes are created in __init__."""
        with patch.dict(os.environ, {'ENV': 'testnet'}):
            # Mock BinanceFuturesClient to avoid API credential check
            with patch('src.application.services.live_trading_service.BinanceFuturesClient') as MockClient:
                mock_client = Mock()
                mock_client.get_usdt_balance.return_value = 1000.0
                mock_client.get_open_orders.return_value = []
                mock_client.get_positions.return_value = []
                MockClient.return_value = mock_client

                service = LiveTradingService(mode=TradingMode.TESTNET)

                # Check cache attributes exist
                assert hasattr(service, '_cached_open_orders'), "Missing _cached_open_orders"
                assert hasattr(service, '_cached_positions_list'), "Missing _cached_positions_list"
                assert hasattr(service, '_local_cache_initialized'), "Missing _local_cache_initialized"

    def test_constructor_does_not_sync_local_cache(self):
        """Constructor should stay lazy and avoid cache sync I/O."""
        with patch.dict(os.environ, {'ENV': 'testnet'}):
            with patch('src.application.services.live_trading_service.BinanceFuturesClient') as MockClient:
                mock_client = Mock()
                mock_client.get_usdt_balance.return_value = 1000.0
                mock_client.get_open_orders.return_value = []
                mock_client.get_positions.return_value = []
                MockClient.return_value = mock_client

                with patch.object(LiveTradingService, '_sync_local_cache') as mock_sync:
                    service = LiveTradingService(mode=TradingMode.TESTNET)
                    mock_sync.assert_not_called()



class TestSyncLocalCache:
    """TC-002: Verify _sync_local_cache populates cache from Binance."""

    def test_sync_populates_orders_cache(self):
        """Verify orders are fetched and cached."""
        mock_orders = [
            {'orderId': 123, 'symbol': 'BTCUSDT', 'side': 'BUY', 'type': 'LIMIT', 'price': 95000},
            {'orderId': 456, 'symbol': 'ETHUSDT', 'side': 'SELL', 'type': 'LIMIT', 'price': 3500},
        ]

        with patch.dict(os.environ, {'ENV': 'testnet'}):
            service = LiveTradingService.__new__(LiveTradingService)
            service.logger = Mock()
            service.client = Mock()
            service.client.get_open_orders.return_value = mock_orders
            service.client.get_positions.return_value = []
            service._cached_open_orders = {}
            service._cached_positions_list = []
            service.active_positions = {}
            service._position_watermarks = {}
            service._local_cache_initialized = False
            service._refresh_positions = Mock()
            service._sync_position_states_from_exchange = Mock()

            service._sync_local_cache()

            assert len(service._cached_open_orders) == 2
            assert 123 in service._cached_open_orders
            assert 456 in service._cached_open_orders
            assert service._local_cache_initialized is True

    def test_sync_handles_empty_orders(self):
        """Verify cache handles no orders gracefully."""
        with patch.dict(os.environ, {'ENV': 'testnet'}):
            service = LiveTradingService.__new__(LiveTradingService)
            service.logger = Mock()
            service.client = Mock()
            service.client.get_open_orders.return_value = []
            service.client.get_positions.return_value = []
            service._cached_open_orders = {}
            service._cached_positions_list = []
            service.active_positions = {}
            service._position_watermarks = {}
            service._local_cache_initialized = False
            service._refresh_positions = Mock()
            service._sync_position_states_from_exchange = Mock()

            service._sync_local_cache()

            assert len(service._cached_open_orders) == 0
            assert service._local_cache_initialized is True


class TestUpdateCachedOrder:
    """TC-003, TC-004, TC-005: Verify update_cached_order handles WebSocket events."""

    def test_new_order_added_to_cache(self):
        """TC-003: New order (status=NEW) is added to cache."""
        service = LiveTradingService.__new__(LiveTradingService)
        service.logger = Mock()
        service._cached_open_orders = {}
        service._portfolio_cache = {'test': 'data'}

        order_data = {
            'orderId': 789,
            'symbol': 'BTCUSDT',
            'side': 'BUY',
            'type': 'LIMIT',
            'status': 'NEW',
            'price': 95000,
            '_is_closed': False
        }

        service.update_cached_order(order_data, is_closed=False)

        assert 789 in service._cached_open_orders
        assert service._cached_open_orders[789]['symbol'] == 'BTCUSDT'
        assert service._portfolio_cache is None  # Should invalidate

    def test_filled_order_removed_from_cache(self):
        """TC-004: Filled order is removed from cache."""
        service = LiveTradingService.__new__(LiveTradingService)
        service.logger = Mock()
        service._cached_open_orders = {
            789: {'orderId': 789, 'symbol': 'BTCUSDT', 'status': 'NEW'}
        }
        service._portfolio_cache = {'test': 'data'}

        order_data = {
            'orderId': 789,
            'status': 'FILLED',
            '_is_closed': True
        }

        service.update_cached_order(order_data, is_closed=True)

        assert 789 not in service._cached_open_orders
        assert service._portfolio_cache is None

    def test_canceled_order_removed_from_cache(self):
        """TC-005: Canceled order is removed from cache."""
        service = LiveTradingService.__new__(LiveTradingService)
        service.logger = Mock()
        service._cached_open_orders = {
            999: {'orderId': 999, 'symbol': 'ETHUSDT', 'status': 'NEW'}
        }
        service._portfolio_cache = None

        order_data = {
            'orderId': 999,
            'status': 'CANCELED',
            '_is_closed': True
        }

        service.update_cached_order(order_data, is_closed=True)

        assert 999 not in service._cached_open_orders


class TestGetPortfolioUsesCache:
    """TC-002: Verify get_portfolio reads from cache instead of API."""

    def test_portfolio_uses_cached_orders(self):
        """Verify get_portfolio uses _cached_open_orders, not API."""
        service = LiveTradingService.__new__(LiveTradingService)
        service.logger = Mock()
        service.mode = TradingMode.TESTNET
        service.client = Mock()
        service._local_cache_initialized = True
        service._portfolio_cache = None
        service._portfolio_cache_time = 0.0
        service.PORTFOLIO_CACHE_TTL = 5.0
        service._cached_balance = 1000.0
        service._cached_available = 900.0
        service.pending_orders = {}
        service._position_watermarks = {}
        service._signal_tracker = Mock()
        service._signal_tracker.get_all_pending.return_value = {}
        service._balance_lock = threading.RLock()

        # Pre-populate cache
        service._cached_open_orders = {
            123: {'orderId': 123, 'symbol': 'BTCUSDT', 'type': 'LIMIT', 'side': 'BUY', 'price': 95000, 'origQty': 0.001}
        }
        service._cached_positions_list = []

        # Mock account info (still needs balance)
        service.client.get_account_info.return_value = {
            'totalWalletBalance': 1000,
            'totalUnrealizedProfit': 0,
            'totalMarginBalance': 1000,
            'availableBalance': 900
        }

        result = service.get_portfolio()

        # Verify client.get_open_orders was NOT called
        service.client.get_open_orders.assert_not_called()

        # Verify pending_orders in result
        assert 'pending_orders' in result

    def test_portfolio_fallback_when_cache_not_initialized(self):
        """Verify fallback to API when cache not initialized."""
        service = LiveTradingService.__new__(LiveTradingService)
        service.logger = Mock()
        service.mode = TradingMode.TESTNET
        service.client = Mock()
        service._local_cache_initialized = False  # Not initialized
        service._portfolio_cache = None
        service._portfolio_cache_time = 0.0
        service.PORTFOLIO_CACHE_TTL = 5.0
        service._cached_balance = 1000.0
        service._cached_available = 900.0
        service.pending_orders = {}
        service._position_watermarks = {}
        service._cached_open_orders = {}
        service._cached_positions_list = []
        service.active_positions = {}
        service._signal_tracker = Mock()
        service._signal_tracker.get_all_pending.return_value = {}
        service._balance_lock = threading.RLock()
        service._refresh_positions = Mock()

        service.client.get_account_info.return_value = {
            'totalWalletBalance': 1000,
            'totalUnrealizedProfit': 0,
            'totalMarginBalance': 1000,
            'availableBalance': 900
        }
        service.client.get_open_orders.return_value = []
        service.client.get_positions.return_value = []
        service.client.get_open_algo_orders.return_value = []

        result = service.get_portfolio()

        # Verify client.get_open_orders WAS called as fallback
        service.client.get_open_orders.assert_called_once()


class TestRefreshCachedPositions:
    """Test position cache refresh functionality."""

    def test_refresh_updates_position_cache(self):
        """Verify refresh_cached_positions updates _cached_positions_list."""
        mock_position = Mock()
        mock_position.symbol = 'BTCUSDT'
        mock_position.position_amt = 0.001

        service = LiveTradingService.__new__(LiveTradingService)
        service.logger = Mock()
        service.client = Mock()
        service.client.get_positions.return_value = [mock_position]
        service.active_positions = {}
        service._cached_positions_list = []
        service._portfolio_cache = {'some': 'data'}

        service._refresh_positions = Mock(side_effect=lambda: service.active_positions.update({'BTCUSDT': mock_position}))

        service.refresh_cached_positions()

        assert len(service._cached_positions_list) == 1
        assert service._portfolio_cache is None  # Invalidated


class TestCachePerformance:
    """TC-006: Performance benchmark tests."""

    def test_cache_hit_performance(self):
        """Verify cache hit returns in < 10ms."""
        service = LiveTradingService.__new__(LiveTradingService)
        service.logger = Mock()
        service.mode = TradingMode.TESTNET
        service.client = Mock()  # Add missing client attribute
        service._portfolio_cache = {
            'balance': 1000,
            'equity': 1000,
            'pending_orders': []
        }
        service._portfolio_cache_time = time.time()  # Fresh cache
        service.PORTFOLIO_CACHE_TTL = 5.0

        start = time.time()
        result = service.get_portfolio()
        elapsed_ms = (time.time() - start) * 1000

        assert elapsed_ms < 10, f"Cache hit took {elapsed_ms:.2f}ms, expected < 10ms"
        assert result == service._portfolio_cache


class TestUserDataStreamIntegration:
    """Test integration with UserDataStream callbacks."""

    def test_order_update_handler_normalized_format(self):
        """Verify WebSocket order data is normalized correctly."""
        from src.infrastructure.api.user_data_stream import UserDataStreamService

        # Create service with mock callback
        received_orders = []
        def on_order_update(order_data):
            received_orders.append(order_data)

        service = UserDataStreamService.__new__(UserDataStreamService)
        service.logger = Mock()
        service.on_order_update = on_order_update

        # Simulate WebSocket event
        ws_data = {
            'e': 'ORDER_TRADE_UPDATE',
            'o': {
                's': 'BTCUSDT',
                'S': 'BUY',
                'o': 'LIMIT',
                'X': 'NEW',
                'i': 123456,
                'p': '95000.0',
                'q': '0.001'
            }
        }

        # Call handler
        asyncio.get_event_loop().run_until_complete(
            service._handle_order_update(ws_data)
        )

        assert len(received_orders) == 1
        order = received_orders[0]
        assert order['orderId'] == 123456
        assert order['symbol'] == 'BTCUSDT'
        assert order['side'] == 'BUY'
        assert order['type'] == 'LIMIT'
        assert order['status'] == 'NEW'
        assert order['_is_closed'] is False

    def test_filled_order_marked_as_closed(self):
        """Verify FILLED status sets _is_closed = True."""
        from src.infrastructure.api.user_data_stream import UserDataStreamService

        received_orders = []
        def on_order_update(order_data):
            received_orders.append(order_data)

        service = UserDataStreamService.__new__(UserDataStreamService)
        service.logger = Mock()
        service.on_order_update = on_order_update

        ws_data = {
            'e': 'ORDER_TRADE_UPDATE',
            'o': {
                's': 'BTCUSDT',
                'S': 'BUY',
                'o': 'LIMIT',
                'X': 'FILLED',
                'i': 123456,
                'p': '95000.0',
                'q': '0.001'
            }
        }

        asyncio.get_event_loop().run_until_complete(
            service._handle_order_update(ws_data)
        )

        assert received_orders[0]['_is_closed'] is True


# =============================================================================
# Integration Test (Requires running Testnet - skip in CI)
# =============================================================================

# Helper to check if API keys are available
def _has_testnet_credentials():
    return bool(os.getenv('BINANCE_TESTNET_API_KEY') and os.getenv('BINANCE_TESTNET_API_SECRET'))


@pytest.mark.skipif(
    not _has_testnet_credentials(),
    reason="BINANCE_TESTNET_API_KEY and SECRET not set"
)
class TestLiveIntegration:
    """Integration tests with real Testnet (manual run only)."""

    def test_real_sync_local_cache(self):
        """Test actual sync with Binance Testnet."""
        with patch.dict(os.environ, {'ENV': 'testnet'}):
            service = LiveTradingService(mode=TradingMode.TESTNET)

            asyncio.run(service.initialize_async())
            assert service._local_cache_initialized is True
            print(f"\n📦 Cached orders: {len(service._cached_open_orders)}")
            print(f"📦 Cached positions: {len(service._cached_positions_list)}")

    def test_real_portfolio_performance(self):
        """Benchmark real portfolio call."""
        with patch.dict(os.environ, {'ENV': 'testnet'}):
            service = LiveTradingService(mode=TradingMode.TESTNET)

            asyncio.run(service.initialize_async())
            # First call (may hit API for balance)
            _ = service.get_portfolio()

            # Second call (should be cache hit)
            start = time.time()
            result = service.get_portfolio()
            elapsed_ms = (time.time() - start) * 1000

            print(f"\n📊 Portfolio cache hit: {elapsed_ms:.2f}ms")
            assert elapsed_ms < 100, f"Expected < 100ms, got {elapsed_ms:.2f}ms"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
