"""
Property-Based Tests for Trading Engine Stability Under Connection Churn

**Feature: desktop-trading-dashboard, Property 4: Trading Engine Stability Under Connection Churn**
**Validates: Requirements 5.2**

Tests that for any sequence of WebSocket client connect/disconnect events
(up to 100 events), the Trading Engine SHALL remain in running state and
continue processing market data without interruption.
"""

import pytest
import asyncio
from hypothesis import given, strategies as st, settings, Phase, HealthCheck
from typing import List, Tuple
from enum import Enum

from src.api.websocket_manager import WebSocketManager, ConnectionState


class ConnectionEvent(Enum):
    """Types of connection events."""
    CONNECT = "connect"
    DISCONNECT = "disconnect"
    BROADCAST = "broadcast"


class MockWebSocket:
    """Mock WebSocket for property testing."""

    def __init__(self, should_fail: bool = False, fail_after: int = -1):
        self.accepted = False
        self.messages_sent = []
        self.should_fail = should_fail
        self.fail_after = fail_after
        self.send_count = 0
        self.closed = False

    async def accept(self):
        self.accepted = True

    async def send_text(self, message: str):
        self.send_count += 1
        if self.should_fail:
            from fastapi import WebSocketDisconnect
            raise WebSocketDisconnect(code=1000)
        if self.fail_after > 0 and self.send_count >= self.fail_after:
            from fastapi import WebSocketDisconnect
            raise WebSocketDisconnect(code=1000)
        self.messages_sent.append(message)

    async def close(self):
        self.closed = True


# Strategies for generating connection events
event_type_strategy = st.sampled_from([
    ConnectionEvent.CONNECT,
    ConnectionEvent.DISCONNECT,
    ConnectionEvent.BROADCAST
])

symbol_strategy = st.sampled_from(['btcusdt', 'ethusdt', 'bnbusdt'])

# Generate sequences of events (up to 100 as per Property 4)
event_sequence_strategy = st.lists(
    st.tuples(event_type_strategy, symbol_strategy),
    min_size=1,
    max_size=100
)


class TestEngineStabilityUnderConnectionChurn:
    """
    Property tests for Trading Engine stability under connection churn.

    **Feature: desktop-trading-dashboard, Property 4: Trading Engine Stability Under Connection Churn**
    **Validates: Requirements 5.2**
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        """Create fresh WebSocketManager for each test."""
        self.manager = WebSocketManager()
        self.active_connections = {}  # Track connections by symbol for disconnect
        yield

    @given(events=event_sequence_strategy)
    @settings(
        max_examples=50,
        deadline=10000,
        phases=[Phase.generate],
        suppress_health_check=[HealthCheck.too_slow]
    )
    async def test_manager_remains_stable_under_connection_churn(
        self,
        events: List[Tuple[ConnectionEvent, str]]
    ):
        """
        Property: For any sequence of connect/disconnect events (up to 100),
        the WebSocketManager SHALL remain operational without crashing.

        **Feature: desktop-trading-dashboard, Property 4: Trading Engine Stability Under Connection Churn**
        **Validates: Requirements 5.2**
        """
        manager = WebSocketManager()
        active_connections = {}

        for event_type, symbol in events:
            try:
                if event_type == ConnectionEvent.CONNECT:
                    # Create new connection
                    ws = MockWebSocket()
                    connection = await manager.connect(ws, symbol)

                    # Track for later disconnect
                    if symbol not in active_connections:
                        active_connections[symbol] = []
                    active_connections[symbol].append(connection)

                elif event_type == ConnectionEvent.DISCONNECT:
                    # Disconnect a random existing connection for this symbol
                    if symbol in active_connections and active_connections[symbol]:
                        connection = active_connections[symbol].pop()
                        await manager.disconnect(connection)

                elif event_type == ConnectionEvent.BROADCAST:
                    # Broadcast to symbol
                    await manager.broadcast({"type": "test", "symbol": symbol}, symbol=symbol)

            except Exception as e:
                # Manager should NEVER crash - any exception is a failure
                pytest.fail(f"Manager crashed on event {event_type.value} for {symbol}: {e}")

        # After all events, manager should still be operational
        stats = manager.get_statistics()
        assert 'active_connections' in stats
        assert 'total_connections' in stats
        assert 'total_disconnections' in stats

    @given(
        num_connects=st.integers(min_value=1, max_value=50),
        num_disconnects=st.integers(min_value=0, max_value=50)
    )
    @settings(
        max_examples=30,
        deadline=10000,
        phases=[Phase.generate],
        suppress_health_check=[HealthCheck.too_slow]
    )
    async def test_connection_count_invariant(
        self,
        num_connects: int,
        num_disconnects: int
    ):
        """
        Property: After N connects and M disconnects, active connections = N - min(M, N).

        **Feature: desktop-trading-dashboard, Property 4: Trading Engine Stability Under Connection Churn**
        **Validates: Requirements 5.2**
        """
        manager = WebSocketManager()
        connections = []

        # Connect N clients
        for i in range(num_connects):
            ws = MockWebSocket()
            conn = await manager.connect(ws, "btcusdt", client_id=f"client_{i}")
            connections.append(conn)

        # Disconnect M clients (or as many as we have)
        actual_disconnects = min(num_disconnects, len(connections))
        for i in range(actual_disconnects):
            await manager.disconnect(connections[i])

        # Verify invariant
        expected_active = num_connects - actual_disconnects
        actual_active = manager.get_connection_count()

        assert actual_active == expected_active, \
            f"Expected {expected_active} active connections, got {actual_active}"

    @given(num_clients=st.integers(min_value=1, max_value=20))
    @settings(
        max_examples=30,
        deadline=10000,
        phases=[Phase.generate],
        suppress_health_check=[HealthCheck.too_slow]
    )
    async def test_broadcast_reaches_all_healthy_clients(
        self,
        num_clients: int
    ):
        """
        Property: Broadcast reaches all connected healthy clients.

        **Feature: desktop-trading-dashboard, Property 4: Trading Engine Stability Under Connection Churn**
        **Validates: Requirements 5.2**
        """
        manager = WebSocketManager()
        websockets = []

        # Connect clients
        for i in range(num_clients):
            ws = MockWebSocket()
            await manager.connect(ws, "btcusdt", client_id=f"client_{i}")
            websockets.append(ws)

        # Broadcast
        sent = await manager.broadcast({"type": "test"}, symbol="btcusdt")

        # All clients should receive
        assert sent == num_clients
        for ws in websockets:
            assert len(ws.messages_sent) == 1

    @given(
        healthy_count=st.integers(min_value=1, max_value=10),
        failing_count=st.integers(min_value=1, max_value=10)
    )
    @settings(
        max_examples=30,
        deadline=10000,
        phases=[Phase.generate],
        suppress_health_check=[HealthCheck.too_slow]
    )
    async def test_failing_connections_cleaned_up_on_broadcast(
        self,
        healthy_count: int,
        failing_count: int
    ):
        """
        Property: Failing connections are cleaned up during broadcast,
        but healthy connections continue to receive messages.

        **Feature: desktop-trading-dashboard, Property 4: Trading Engine Stability Under Connection Churn**
        **Validates: Requirements 5.2, 5.3**
        """
        manager = WebSocketManager()
        healthy_websockets = []

        # Connect healthy clients
        for i in range(healthy_count):
            ws = MockWebSocket(should_fail=False)
            await manager.connect(ws, "btcusdt", client_id=f"healthy_{i}")
            healthy_websockets.append(ws)

        # Connect failing clients
        for i in range(failing_count):
            ws = MockWebSocket(should_fail=True)
            await manager.connect(ws, "btcusdt", client_id=f"failing_{i}")

        # Initial count
        initial_count = manager.get_connection_count()
        assert initial_count == healthy_count + failing_count

        # Broadcast - failing connections should be cleaned up
        sent = await manager.broadcast({"type": "test"}, symbol="btcusdt")

        # Only healthy clients received
        assert sent == healthy_count

        # Failing connections should be removed
        final_count = manager.get_connection_count()
        assert final_count == healthy_count

        # Healthy clients got the message
        for ws in healthy_websockets:
            assert len(ws.messages_sent) == 1

    @given(num_broadcasts=st.integers(min_value=1, max_value=50))
    @settings(
        max_examples=30,
        deadline=10000,
        phases=[Phase.generate],
        suppress_health_check=[HealthCheck.too_slow]
    )
    async def test_multiple_broadcasts_accumulate(
        self,
        num_broadcasts: int
    ):
        """
        Property: Multiple broadcasts accumulate correctly in message count.

        **Feature: desktop-trading-dashboard, Property 4: Trading Engine Stability Under Connection Churn**
        **Validates: Requirements 5.2**
        """
        manager = WebSocketManager()
        ws = MockWebSocket()
        connection = await manager.connect(ws, "btcusdt")

        # Send multiple broadcasts
        for i in range(num_broadcasts):
            await manager.broadcast({"type": "test", "index": i}, symbol="btcusdt")

        # Verify message count
        assert connection.message_count == num_broadcasts
        assert len(ws.messages_sent) == num_broadcasts

        # Verify statistics
        stats = manager.get_statistics()
        assert stats['total_messages_sent'] == num_broadcasts

    @given(
        symbols=st.lists(symbol_strategy, min_size=1, max_size=5),
        clients_per_symbol=st.integers(min_value=1, max_value=5)
    )
    @settings(
        max_examples=30,
        deadline=10000,
        phases=[Phase.generate],
        suppress_health_check=[HealthCheck.too_slow]
    )
    async def test_symbol_isolation(
        self,
        symbols: List[str],
        clients_per_symbol: int
    ):
        """
        Property: Broadcast to one symbol does not affect other symbols.

        **Feature: desktop-trading-dashboard, Property 4: Trading Engine Stability Under Connection Churn**
        **Validates: Requirements 5.2**
        """
        manager = WebSocketManager()
        websockets_by_symbol = {}

        # Connect clients to each symbol
        unique_symbols = list(set(symbols))
        for symbol in unique_symbols:
            websockets_by_symbol[symbol] = []
            for i in range(clients_per_symbol):
                ws = MockWebSocket()
                await manager.connect(ws, symbol, client_id=f"{symbol}_{i}")
                websockets_by_symbol[symbol].append(ws)

        # Broadcast to first symbol only
        target_symbol = unique_symbols[0]
        await manager.broadcast({"type": "test"}, symbol=target_symbol)

        # Only target symbol clients should receive
        for symbol, websockets in websockets_by_symbol.items():
            for ws in websockets:
                if symbol == target_symbol:
                    assert len(ws.messages_sent) == 1, \
                        f"Client for {symbol} should have received message"
                else:
                    assert len(ws.messages_sent) == 0, \
                        f"Client for {symbol} should NOT have received message"

    @given(disconnect_indices=st.lists(st.integers(min_value=0, max_value=9), min_size=0, max_size=10))
    @settings(
        max_examples=30,
        deadline=10000,
        phases=[Phase.generate],
        suppress_health_check=[HealthCheck.too_slow]
    )
    async def test_disconnect_idempotent(
        self,
        disconnect_indices: List[int]
    ):
        """
        Property: Disconnecting the same connection multiple times is safe.

        **Feature: desktop-trading-dashboard, Property 4: Trading Engine Stability Under Connection Churn**
        **Validates: Requirements 5.3**
        """
        manager = WebSocketManager()

        # Connect 10 clients
        connections = []
        for i in range(10):
            ws = MockWebSocket()
            conn = await manager.connect(ws, "btcusdt", client_id=f"client_{i}")
            connections.append(conn)

        # Disconnect based on indices (may have duplicates)
        disconnected = set()
        for idx in disconnect_indices:
            if idx < len(connections):
                conn = connections[idx]
                # This should not raise even if already disconnected
                await manager.disconnect(conn)
                disconnected.add(idx)

        # Verify final count
        expected_active = 10 - len(disconnected)
        actual_active = manager.get_connection_count()

        assert actual_active == expected_active
