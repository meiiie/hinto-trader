"""
Unit Tests for WebSocket Manager

**Feature: desktop-trading-dashboard**
**Validates: Requirements 5.2, 5.3**

Tests:
- Connection tracking
- Graceful disconnect handling
- Broadcast mechanism
- Statistics tracking
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from src.api.websocket_manager import (
    WebSocketManager,
    ClientConnection,
    ConnectionState,
    get_websocket_manager
)


class MockWebSocket:
    """Mock WebSocket for testing."""

    def __init__(self, should_fail: bool = False):
        self.accepted = False
        self.messages_sent = []
        self.should_fail = should_fail
        self.closed = False

    async def accept(self):
        self.accepted = True

    async def send_text(self, message: str):
        if self.should_fail:
            from fastapi import WebSocketDisconnect
            raise WebSocketDisconnect(code=1000)
        self.messages_sent.append(message)

    async def close(self):
        self.closed = True


@pytest.fixture
def manager():
    """Create a fresh WebSocketManager for each test."""
    return WebSocketManager()


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket."""
    return MockWebSocket()


class TestWebSocketManagerConnection:
    """Tests for connection management."""

    @pytest.mark.asyncio
    async def test_connect_accepts_websocket(self, manager, mock_websocket):
        """Test that connect() accepts the WebSocket."""
        connection = await manager.connect(mock_websocket, "btcusdt")

        assert mock_websocket.accepted is True
        assert connection.state == ConnectionState.CONNECTED
        assert connection.symbol == "btcusdt"

    @pytest.mark.asyncio
    async def test_connect_tracks_connection(self, manager, mock_websocket):
        """Test that connections are tracked."""
        await manager.connect(mock_websocket, "btcusdt")

        assert manager.get_connection_count() == 1
        assert manager.get_connection_count("btcusdt") == 1

    @pytest.mark.asyncio
    async def test_connect_multiple_clients(self, manager):
        """Test multiple client connections."""
        ws1 = MockWebSocket()
        ws2 = MockWebSocket()
        ws3 = MockWebSocket()

        await manager.connect(ws1, "btcusdt")
        await manager.connect(ws2, "btcusdt")
        await manager.connect(ws3, "ethusdt")

        assert manager.get_connection_count() == 3
        assert manager.get_connection_count("btcusdt") == 2
        assert manager.get_connection_count("ethusdt") == 1

    @pytest.mark.asyncio
    async def test_connect_generates_client_id(self, manager, mock_websocket):
        """Test that client_id is generated if not provided."""
        connection = await manager.connect(mock_websocket, "btcusdt")

        assert connection.client_id is not None
        assert "btcusdt" in connection.client_id

    @pytest.mark.asyncio
    async def test_connect_uses_provided_client_id(self, manager, mock_websocket):
        """Test that provided client_id is used."""
        connection = await manager.connect(mock_websocket, "btcusdt", client_id="my-client-123")

        assert connection.client_id == "my-client-123"


class TestWebSocketManagerDisconnect:
    """Tests for disconnect handling."""

    @pytest.mark.asyncio
    async def test_disconnect_removes_connection(self, manager, mock_websocket):
        """Test that disconnect removes the connection."""
        connection = await manager.connect(mock_websocket, "btcusdt")

        await manager.disconnect(connection)

        assert manager.get_connection_count() == 0
        assert connection.state == ConnectionState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_disconnect_by_websocket(self, manager, mock_websocket):
        """Test disconnect by WebSocket instance."""
        await manager.connect(mock_websocket, "btcusdt")

        await manager.disconnect_by_websocket(mock_websocket)

        assert manager.get_connection_count() == 0

    @pytest.mark.asyncio
    async def test_disconnect_idempotent(self, manager, mock_websocket):
        """Test that multiple disconnects don't cause errors."""
        connection = await manager.connect(mock_websocket, "btcusdt")

        await manager.disconnect(connection)
        await manager.disconnect(connection)  # Should not raise

        assert manager.get_connection_count() == 0

    @pytest.mark.asyncio
    async def test_disconnect_cleans_up_empty_symbol(self, manager):
        """Test that empty symbol sets are cleaned up."""
        ws = MockWebSocket()
        connection = await manager.connect(ws, "btcusdt")

        await manager.disconnect(connection)

        assert "btcusdt" not in manager._connections


class TestWebSocketManagerBroadcast:
    """Tests for broadcast functionality."""

    @pytest.mark.asyncio
    async def test_broadcast_to_all(self, manager):
        """Test broadcast to all connected clients."""
        ws1 = MockWebSocket()
        ws2 = MockWebSocket()

        await manager.connect(ws1, "btcusdt")
        await manager.connect(ws2, "ethusdt")

        sent = await manager.broadcast({"type": "test", "data": "hello"})

        assert sent == 2
        assert len(ws1.messages_sent) == 1
        assert len(ws2.messages_sent) == 1

    @pytest.mark.asyncio
    async def test_broadcast_to_symbol(self, manager):
        """Test broadcast to specific symbol subscribers."""
        ws1 = MockWebSocket()
        ws2 = MockWebSocket()
        ws3 = MockWebSocket()

        await manager.connect(ws1, "btcusdt")
        await manager.connect(ws2, "btcusdt")
        await manager.connect(ws3, "ethusdt")

        sent = await manager.broadcast({"type": "test"}, symbol="btcusdt")

        assert sent == 2
        assert len(ws1.messages_sent) == 1
        assert len(ws2.messages_sent) == 1
        assert len(ws3.messages_sent) == 0

    @pytest.mark.asyncio
    async def test_broadcast_handles_failed_connection(self, manager):
        """Test that broadcast handles failed connections gracefully."""
        ws1 = MockWebSocket()
        ws2 = MockWebSocket(should_fail=True)  # This one will fail

        await manager.connect(ws1, "btcusdt")
        await manager.connect(ws2, "btcusdt")

        # Should not raise, should clean up failed connection
        sent = await manager.broadcast({"type": "test"})

        assert sent == 1  # Only ws1 succeeded
        assert manager.get_connection_count() == 1  # ws2 was removed

    @pytest.mark.asyncio
    async def test_broadcast_updates_statistics(self, manager, mock_websocket):
        """Test that broadcast updates message statistics."""
        connection = await manager.connect(mock_websocket, "btcusdt")

        await manager.broadcast({"type": "test1"})
        await manager.broadcast({"type": "test2"})

        assert connection.message_count == 2
        assert connection.last_message_at is not None


class TestWebSocketManagerSendToClient:
    """Tests for sending to specific clients."""

    @pytest.mark.asyncio
    async def test_send_to_client(self, manager, mock_websocket):
        """Test sending to a specific client."""
        connection = await manager.connect(mock_websocket, "btcusdt", client_id="client-1")

        result = await manager.send_to_client("client-1", {"type": "direct"})

        assert result is True
        assert len(mock_websocket.messages_sent) == 1

    @pytest.mark.asyncio
    async def test_send_to_nonexistent_client(self, manager):
        """Test sending to a client that doesn't exist."""
        result = await manager.send_to_client("nonexistent", {"type": "test"})

        assert result is False


class TestWebSocketManagerStatistics:
    """Tests for statistics tracking."""

    @pytest.mark.asyncio
    async def test_statistics_tracking(self, manager):
        """Test that statistics are tracked correctly."""
        ws1 = MockWebSocket()
        ws2 = MockWebSocket()

        await manager.connect(ws1, "btcusdt")
        conn2 = await manager.connect(ws2, "btcusdt")

        await manager.broadcast({"type": "test"})
        await manager.disconnect(conn2)

        stats = manager.get_statistics()

        assert stats['active_connections'] == 1
        assert stats['total_connections'] == 2
        assert stats['total_disconnections'] == 1
        assert stats['total_messages_sent'] == 2  # 2 clients received 1 message each

    @pytest.mark.asyncio
    async def test_get_subscribed_symbols(self, manager):
        """Test getting list of subscribed symbols."""
        ws1 = MockWebSocket()
        ws2 = MockWebSocket()

        await manager.connect(ws1, "btcusdt")
        await manager.connect(ws2, "ethusdt")

        symbols = manager.get_subscribed_symbols()

        assert "btcusdt" in symbols
        assert "ethusdt" in symbols

    @pytest.mark.asyncio
    async def test_get_all_connections_info(self, manager):
        """Test getting info about all connections."""
        ws = MockWebSocket()
        await manager.connect(ws, "btcusdt", client_id="test-client")

        info = manager.get_all_connections_info()

        assert len(info) == 1
        assert info[0]['client_id'] == "test-client"
        assert info[0]['symbol'] == "btcusdt"
        assert info[0]['state'] == "connected"


class TestWebSocketManagerCallbacks:
    """Tests for connection/disconnection callbacks."""

    @pytest.mark.asyncio
    async def test_on_connect_callback(self, manager, mock_websocket):
        """Test that connect callbacks are called."""
        callback_called = []

        def on_connect(conn):
            callback_called.append(conn)

        manager.on_connect(on_connect)
        connection = await manager.connect(mock_websocket, "btcusdt")

        assert len(callback_called) == 1
        assert callback_called[0] is connection

    @pytest.mark.asyncio
    async def test_on_disconnect_callback(self, manager, mock_websocket):
        """Test that disconnect callbacks are called."""
        callback_called = []

        def on_disconnect(conn):
            callback_called.append(conn)

        manager.on_disconnect(on_disconnect)
        connection = await manager.connect(mock_websocket, "btcusdt")
        await manager.disconnect(connection)

        assert len(callback_called) == 1
        assert callback_called[0] is connection

    @pytest.mark.asyncio
    async def test_async_callbacks(self, manager, mock_websocket):
        """Test that async callbacks work."""
        callback_called = []

        async def async_on_connect(conn):
            callback_called.append(conn)

        manager.on_connect(async_on_connect)
        await manager.connect(mock_websocket, "btcusdt")

        assert len(callback_called) == 1


class TestClientConnection:
    """Tests for ClientConnection dataclass."""

    def test_to_dict(self):
        """Test ClientConnection.to_dict()."""
        ws = MockWebSocket()
        conn = ClientConnection(
            websocket=ws,
            client_id="test-123",
            symbol="btcusdt",
            state=ConnectionState.CONNECTED
        )

        data = conn.to_dict()

        assert data['client_id'] == "test-123"
        assert data['symbol'] == "btcusdt"
        assert data['state'] == "connected"
        assert 'connected_at' in data
