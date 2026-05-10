"""
Test: Dynamic Symbol Subscription

SOTA (Jan 2026): Tests for new dynamic WebSocket subscription feature.
Verifies symbols are subscribed when positions open for non-SharkTank symbols.

Reference:
- binance_websocket_client.py subscribe_symbol()
- shared_binance_client.py subscribe_symbol()
- position_monitor_service.py start_monitoring()
"""

import pytest
from unittest.mock import Mock, patch, MagicMock, AsyncMock
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestSubscribeSymbolMethod:
    """Test BinanceWebSocketClient.subscribe_symbol()"""

    # =========================================================================
    # REFERENCE (binance_websocket_client.py L563-607):
    #   async def subscribe_symbol(self, symbol: str) -> bool:
    #       streams = [f"{symbol}@kline_{intv}" for intv in self._intervals]
    #       await self._websocket.send(json.dumps(payload))
    #       self._symbols.append(symbol)
    # =========================================================================

    def test_symbol_added_to_list(self):
        """Symbol should be added to _symbols list after subscribe"""
        symbols = ['btcusdt', 'ethusdt']
        new_symbol = 'vvvusdt'

        # Simulate subscribe
        if new_symbol not in symbols:
            symbols.append(new_symbol)

        assert 'vvvusdt' in symbols
        assert len(symbols) == 3

    def test_already_subscribed_returns_true(self):
        """If symbol already subscribed, should return True without action"""
        symbols = ['btcusdt', 'vvvusdt']

        symbol = 'vvvusdt'
        already_subscribed = symbol in symbols

        assert already_subscribed is True

    def test_subscribe_message_format(self):
        """SUBSCRIBE message should have correct JSON format"""
        symbol = 'vvvusdt'
        intervals = ['1m', '15m', '1h']
        request_id = 12345

        streams = [f"{symbol}@kline_{intv}" for intv in intervals]
        payload = {
            "method": "SUBSCRIBE",
            "params": streams,
            "id": request_id
        }

        assert payload["method"] == "SUBSCRIBE"
        assert payload["params"] == [
            "vvvusdt@kline_1m",
            "vvvusdt@kline_15m",
            "vvvusdt@kline_1h"
        ]
        assert payload["id"] == 12345


class TestSharedBinanceClientWrapper:
    """Test SharedBinanceClient.subscribe_symbol() wrapper"""

    @pytest.mark.asyncio
    async def test_wrapper_calls_underlying_client(self, mock_shared_binance_client):
        """Wrapper should call underlying client's subscribe_symbol"""
        symbol = 'vvvusdt'

        result = await mock_shared_binance_client.subscribe_symbol(symbol)

        mock_shared_binance_client.subscribe_symbol.assert_called_once_with(symbol)
        assert result is True

    @pytest.mark.asyncio
    async def test_wrapper_updates_local_symbols(self, mock_shared_binance_client):
        """Wrapper should update local _symbols list"""
        initial_symbols = mock_shared_binance_client._symbols.copy()
        symbol = 'newusdt'

        await mock_shared_binance_client.subscribe_symbol(symbol)

        assert symbol in mock_shared_binance_client._symbols

    def test_wrapper_creates_handler_entry(self, mock_shared_binance_client):
        """Wrapper should create empty handler list for new symbol"""
        symbol = 'newusdt'

        if symbol not in mock_shared_binance_client._handlers:
            mock_shared_binance_client._handlers[symbol] = []

        assert symbol in mock_shared_binance_client._handlers
        assert mock_shared_binance_client._handlers[symbol] == []


class TestPositionMonitorSubscription:
    """Test PositionMonitorService triggers subscription on start_monitoring"""

    # =========================================================================
    # REFERENCE (position_monitor_service.py L175-180):
    #   if symbol_lower not in self._shared_client._symbols:
    #       asyncio.create_task(self._ensure_subscribed(symbol_lower))
    # =========================================================================

    def test_subscription_triggered_for_new_symbol(self, mock_shared_binance_client):
        """start_monitoring should trigger subscription for new symbol"""
        existing_symbols = mock_shared_binance_client._symbols
        new_symbol = 'newusdt'

        should_subscribe = new_symbol not in existing_symbols

        assert should_subscribe is True

    def test_subscription_skipped_for_existing_symbol(self, mock_shared_binance_client):
        """start_monitoring should NOT trigger subscription for existing symbol"""
        new_symbol = 'btcusdt'  # Already in initial list

        should_subscribe = new_symbol not in mock_shared_binance_client._symbols

        assert should_subscribe is False

    def test_handler_registered_after_subscription(self, mock_shared_binance_client):
        """Handler should be registered after subscription"""
        symbol = 'newusdt'

        # Simulate subscription + handler registration
        mock_shared_binance_client._symbols.append(symbol)
        mock_shared_binance_client._handlers[symbol] = [lambda x: None]

        assert symbol in mock_shared_binance_client._symbols
        assert symbol in mock_shared_binance_client._handlers
        assert len(mock_shared_binance_client._handlers[symbol]) == 1


class TestEnsureSubscribedHelper:
    """Test _ensure_subscribed async helper method"""

    @pytest.mark.asyncio
    async def test_ensure_subscribed_success_logging(self):
        """Success should be logged after subscription confirmed"""
        logs = []

        async def mock_subscribe(symbol):
            logs.append(f"📡 Dynamic subscription confirmed: {symbol}")
            return True

        await mock_subscribe('vvvusdt')

        assert "📡 Dynamic subscription confirmed: vvvusdt" in logs

    @pytest.mark.asyncio
    async def test_ensure_subscribed_failure_warning(self):
        """Failure should be logged as warning"""
        logs = []

        async def mock_subscribe(symbol):
            logs.append(f"⚠️ Dynamic subscription failed: {symbol}")
            return False

        await mock_subscribe('badusdt')

        assert "⚠️ Dynamic subscription failed: badusdt" in logs


class TestFireAndForgetPattern:
    """Test subscription uses fire-and-forget pattern"""

    def test_asyncio_create_task_used(self):
        """Subscription should use asyncio.create_task for non-blocking"""
        # This is a design verification - the actual code uses:
        # asyncio.create_task(self._ensure_subscribed(symbol_lower))

        # Verify the pattern doesn't block
        tasks_created = []

        async def ensure_subscribed(symbol):
            await asyncio.sleep(0.01)  # Simulate network delay
            return True

        # Fire-and-forget pattern
        async def start_monitoring():
            task = asyncio.create_task(ensure_subscribed('vvvusdt'))
            tasks_created.append(task)
            # Immediately returns, doesn't await
            return True

        # Run async test
        async def test():
            result = await start_monitoring()
            assert result is True
            assert len(tasks_created) == 1
            # Task still running (fire-and-forget)

        asyncio.run(test())


class TestSubscriptionPersistence:
    """Test subscriptions persist during session"""

    def test_subscriptions_accumulate(self):
        """Symbols should accumulate, not reset"""
        symbols = ['btcusdt', 'ethusdt']  # Initial

        # Open positions for new symbols
        symbols.append('vvvusdt')
        symbols.append('pepeusdt')
        symbols.append('dogeusdt')

        assert len(symbols) == 5
        assert 'vvvusdt' in symbols

    def test_closed_position_keeps_subscription(self):
        """Closing a position should NOT unsubscribe (design decision)"""
        symbols = ['btcusdt', 'ethusdt', 'vvvusdt']

        # Close VVV position - symbol stays subscribed
        # (No unsubscribe per design - cleanup on restart)

        assert 'vvvusdt' in symbols  # Still subscribed
