"""
Shared fixtures for LIVE Trading Unit Tests

SOTA (Jan 2026): Follows best practices from major quant firms:
- Isolated tests with mocked dependencies
- Deterministic outcomes with static data
- Reusable fixtures for consistency
"""

import pytest
from unittest.mock import Mock, MagicMock, AsyncMock, patch
from datetime import datetime, timezone
from dataclasses import dataclass


# =============================================================================
# DOMAIN ENTITY MOCKS
# =============================================================================

@dataclass
class MockPosition:
    """Mock position for testing"""
    symbol: str
    side: str  # "LONG" or "SHORT"
    entry_price: float
    current_sl: float
    initial_tp: float
    quantity: float = 1.0
    atr: float = 0.01
    tp_hit_count: int = 0
    remaining_qty: float = 1.0
    phase: str = "INITIAL"


@pytest.fixture
def sample_long_position():
    """Sample LONG position for testing"""
    return MockPosition(
        symbol="BTCUSDT",
        side="LONG",
        entry_price=50000.0,
        current_sl=49750.0,   # 0.5% below entry
        initial_tp=51000.0,   # 2% above entry
        quantity=0.1,
        atr=500.0,  # $500 ATR
        remaining_qty=0.1
    )


@pytest.fixture
def sample_short_position():
    """Sample SHORT position for testing"""
    return MockPosition(
        symbol="ETHUSDT",
        side="SHORT",
        entry_price=3000.0,
        current_sl=3015.0,   # 0.5% above entry
        initial_tp=2940.0,   # 2% below entry
        quantity=1.0,
        atr=30.0,  # $30 ATR
        remaining_qty=1.0
    )


# =============================================================================
# SERVICE MOCKS
# =============================================================================

@pytest.fixture
def mock_binance_client():
    """Mock Binance client for isolated testing"""
    client = Mock()

    # Mock order creation - returns dict like real API
    client.create_order = Mock(return_value={
        'orderId': 12345,
        'clientOrderId': 'test-001',
        'symbol': 'BTCUSDT',
        'side': 'SELL',
        'type': 'MARKET',
        'status': 'FILLED',
        'executedQty': '0.06',
        'avgPrice': '50500.0'
    })

    # Mock algo order (backup SL)
    client.place_algo_order = Mock(return_value={
        'algoId': 'algo-001',
        'clientAlgoId': 'backup-sl-001'
    })

    # Mock cancel algo order
    client.cancel_algo_order = Mock(return_value={'code': 200})

    # Mock position fetch
    client.get_positions = Mock(return_value=[])

    # Mock set leverage
    client.set_leverage = Mock(return_value={'leverage': 10})

    return client


@pytest.fixture
def mock_websocket():
    """Mock WebSocket for subscription testing"""
    ws = AsyncMock()
    ws.send = AsyncMock()
    ws.recv = AsyncMock(return_value='{"result": null, "id": 1}')
    return ws


@pytest.fixture
def mock_shared_binance_client(mock_websocket):
    """Mock SharedBinanceClient for PositionMonitor testing"""
    client = Mock()
    client._symbols = ['btcusdt', 'ethusdt']
    client._handlers = {}
    client._client = Mock()
    client._client._websocket = mock_websocket
    client._client.is_connected = Mock(return_value=True)

    # Mock subscribe_symbol
    async def mock_subscribe(symbol):
        client._symbols.append(symbol.lower())
        return True

    client.subscribe_symbol = AsyncMock(side_effect=mock_subscribe)
    client.register_handler = Mock()

    return client


@pytest.fixture
def mock_order_repository():
    """Mock SQLite order repository"""
    repo = Mock()
    repo.save_live_position = Mock()
    repo.update_live_position_sl = Mock()
    repo.delete_live_position = Mock()
    repo.get_live_positions = Mock(return_value=[])
    return repo


# =============================================================================
# SIGNAL FIXTURES
# =============================================================================

@pytest.fixture
def sample_buy_signal():
    """Sample BUY signal for testing"""
    from src.domain.entities.trading_signal import TradingSignal, SignalType

    return TradingSignal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        entry_price=50000.0,
        stop_loss=49750.0,
        take_profit=51000.0,
        confidence=0.85,
        signal_id="test-buy-001",
        metadata={'atr': 500.0}
    )


@pytest.fixture
def sample_sell_signal():
    """Sample SELL signal for testing"""
    from src.domain.entities.trading_signal import TradingSignal, SignalType

    return TradingSignal(
        symbol="ETHUSDT",
        signal_type=SignalType.SELL,
        entry_price=3000.0,
        stop_loss=3015.0,
        take_profit=2940.0,
        confidence=0.80,
        signal_id="test-sell-001",
        metadata={'atr': 30.0}
    )


# =============================================================================
# CANDLE/PRICE FIXTURES
# =============================================================================

@pytest.fixture
def price_at_tp1_long():
    """Price that triggers TP1 for LONG (2% above entry)"""
    return 51000.0  # Exactly at TP


@pytest.fixture
def price_at_sl_long():
    """Price that triggers SL for LONG (0.5% below entry)"""
    return 49750.0  # Exactly at SL


@pytest.fixture
def price_at_tp1_short():
    """Price that triggers TP1 for SHORT (2% below entry)"""
    return 2940.0  # Exactly at TP


@pytest.fixture
def price_at_sl_short():
    """Price that triggers SL for SHORT (0.5% above entry)"""
    return 3015.0  # Exactly at SL


# =============================================================================
# UTILITY FIXTURES
# =============================================================================

@pytest.fixture
def frozen_time():
    """Freeze time for deterministic tests"""
    return datetime(2026, 1, 12, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def mock_logger():
    """Mock logger for testing log output"""
    return Mock()
