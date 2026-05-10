"""
Integration Tests - Live Trading Flow

Tests the complete flow from candle close to order execution.

Core Principle: "If it works in backtest, it should work in live"
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch

pytest.importorskip(
    "src.application.backtest_live.core.realtime_data_manager",
    reason="legacy backtest_live integration flow is not available in this codebase",
)
pytest.importorskip(
    "src.application.backtest_live.core.execution_adapter",
    reason="legacy backtest_live integration flow is not available in this codebase",
)
pytest.importorskip(
    "src.application.backtest_live.core.position_monitor",
    reason="legacy backtest_live integration flow is not available in this codebase",
)
pytest.importorskip(
    "src.application.backtest_live.core.shark_tank_coordinator",
    reason="legacy backtest_live integration flow is not available in this codebase",
)
pytest.importorskip(
    "src.application.backtest_live.core.order_manager",
    reason="legacy backtest_live integration flow is not available in this codebase",
)

from src.application.backtest_live.core.realtime_data_manager import RealTimeDataManager
from src.application.backtest_live.core.execution_adapter import ExecutionAdapter
from src.application.backtest_live.core.position_monitor import PositionMonitor
from src.application.backtest_live.core.shark_tank_coordinator import SharkTankCoordinator
from src.application.backtest_live.core.order_manager import OrderManager
from src.application.signals.signal_generator import SignalGenerator
from src.domain.entities.trading_signal import TradingSignal, SignalType
from src.domain.entities.candle import Candle


@pytest.fixture
def mock_binance_client():
    """Mock Binance client"""
    client = Mock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.create_order = AsyncMock(return_value={'orderId': '12345'})
    client.cancel_order = AsyncMock(return_value={'status': 'CANCELED'})
    client.get_position = AsyncMock(return_value=None)
    return client


@pytest.fixture
def config():
    """Test configuration"""
    return {
        'balance': 34.0,
        'leverage': 10,
        'max_positions': 5,
        'risk_percent': 1.0,
        'ttl_minutes': 50,
        'zombie_killer': True,
        'full_tp': False
    }


@pytest.fixture
async def components(mock_binance_client, config):
    """Initialize all components"""
    # Order Manager
    order_manager = OrderManager(
        binance_client=mock_binance_client,
        default_ttl_minutes=config['ttl_minutes']
    )

    # Execution Adapter
    execution_adapter = ExecutionAdapter(
        binance_client=mock_binance_client,
        order_manager=order_manager,
        balance=config['balance'],
        leverage=config['leverage'],
        max_positions=config['max_positions'],
        risk_per_trade=config['risk_percent'] / 100.0
    )

    # Position Monitor
    position_monitor = PositionMonitor(
        binance_client=mock_binance_client,
        execution_adapter=execution_adapter,
        full_tp_at_tp1=config['full_tp']
    )

    # Shark Tank
    shark_tank = SharkTankCoordinator(
        max_positions=config['max_positions'],
        enable_smart_recycling=config['zombie_killer']
    )

    # Signal Generator
    signal_generator = SignalGenerator()

    return {
        'order_manager': order_manager,
        'execution_adapter': execution_adapter,
        'position_monitor': position_monitor,
        'shark_tank': shark_tank,
        'signal_generator': signal_generator
    }


@pytest.mark.asyncio
async def test_end_to_end_signal_to_order(components, mock_binance_client):
    """
    Test complete flow: Signal → Shark Tank → Execution → Order Placement
    """
    # Create a LONG signal
    signal = TradingSignal(
        symbol='btcusdt',
        signal_type=SignalType.LONG,
        confidence=0.85,
        entry_price=50000.0,
        stop_loss=49500.0,
        take_profit_1=50250.0,
        take_profit_2=50500.0,
        atr=100.0,
        timestamp=datetime.utcnow()
    )

    # Add signal to Shark Tank
    components['shark_tank'].add_signal(signal)

    # Process signals
    signals_to_execute = components['shark_tank'].process_signals(
        current_positions={},
        pending_orders={},
        current_time=datetime.utcnow()
    )

    # Should have 1 signal to execute
    assert len(signals_to_execute) == 1
    assert signals_to_execute[0].symbol == 'btcusdt'

    # Execute signal
    result = await components['execution_adapter'].execute_signal(signals_to_execute[0])

    # Verify order was placed
    assert result is not None
    assert result['success'] is True
    assert 'entry_price' in result

    # Verify Binance API was called
    mock_binance_client.create_order.assert_called_once()


@pytest.mark.asyncio
async def test_shark_tank_batching(components):
    """
    Test Shark Tank batches signals and ranks by confidence
    """
    # Create 3 signals with different confidence
    signals = [
        TradingSignal(
            symbol='btcusdt',
            signal_type=SignalType.LONG,
            confidence=0.70,
            entry_price=50000.0,
            stop_loss=49500.0,
            take_profit_1=50250.0,
            take_profit_2=50500.0,
            atr=100.0,
            timestamp=datetime.utcnow()
        ),
        TradingSignal(
            symbol='ethusdt',
            signal_type=SignalType.LONG,
            confidence=0.90,  # Highest
            entry_price=3000.0,
            stop_loss=2970.0,
            take_profit_1=3015.0,
            take_profit_2=3030.0,
            atr=10.0,
            timestamp=datetime.utcnow()
        ),
        TradingSignal(
            symbol='bnbusdt',
            signal_type=SignalType.LONG,
            confidence=0.80,
            entry_price=400.0,
            stop_loss=396.0,
            take_profit_1=402.0,
            take_profit_2=404.0,
            atr=2.0,
            timestamp=datetime.utcnow()
        )
    ]

    # Add all signals
    for signal in signals:
        components['shark_tank'].add_signal(signal)

    # Process with max_positions=2
    components['shark_tank'].max_positions = 2

    signals_to_execute = components['shark_tank'].process_signals(
        current_positions={},
        pending_orders={},
        current_time=datetime.utcnow()
    )

    # Should execute top 2 by confidence
    assert len(signals_to_execute) == 2
    assert signals_to_execute[0].symbol == 'ethusdt'  # 0.90 confidence
    assert signals_to_execute[1].symbol == 'bnbusdt'  # 0.80 confidence


@pytest.mark.asyncio
async def test_smart_recycling(components, mock_binance_client):
    """
    Test Smart Recycling replaces worst pending with best new signal
    """
    # Fill all slots with pending orders
    for i, symbol in enumerate(['btcusdt', 'ethusdt', 'bnbusdt', 'solusdt', 'adausdt']):
        signal = TradingSignal(
            symbol=symbol,
            signal_type=SignalType.LONG,
            confidence=0.60 + i * 0.05,  # 0.60, 0.65, 0.70, 0.75, 0.80
            entry_price=100.0,
            stop_loss=99.0,
            take_profit_1=100.5,
            take_profit_2=101.0,
            atr=1.0,
            timestamp=datetime.utcnow()
        )
        await components['execution_adapter'].execute_signal(signal)

    # Now tank is full (5/5 slots)
    assert len(components['order_manager'].pending_orders) == 5

    # New signal with HIGHER confidence than worst pending
    new_signal = TradingSignal(
        symbol='dogeusdt',
        signal_type=SignalType.LONG,
        confidence=0.85,  # Better than all existing
        entry_price=0.10,
        stop_loss=0.099,
        take_profit_1=0.1005,
        take_profit_2=0.101,
        atr=0.001,
        timestamp=datetime.utcnow()
    )

    components['shark_tank'].add_signal(new_signal)

    # Process with Smart Recycling enabled
    signals_to_execute = components['shark_tank'].process_signals(
        current_positions={},
        pending_orders=components['order_manager'].pending_orders,
        current_time=datetime.utcnow()
    )

    # Should recycle: cancel worst (btcusdt 0.60), execute best (dogeusdt 0.85)
    assert len(signals_to_execute) == 1
    assert signals_to_execute[0].symbol == 'dogeusdt'


@pytest.mark.asyncio
async def test_position_monitoring_tp_hit(components, mock_binance_client):
    """
    Test Position Monitor detects TP1 hit and closes partial position
    """
    # Create and execute a signal
    signal = TradingSignal(
        symbol='btcusdt',
        signal_type=SignalType.LONG,
        confidence=0.85,
        entry_price=50000.0,
        stop_loss=49500.0,
        take_profit_1=50250.0,  # +0.5%
        take_profit_2=50500.0,
        atr=100.0,
        timestamp=datetime.utcnow()
    )

    result = await components['execution_adapter'].execute_signal(signal)

    # Simulate order fill
    position = {
        'symbol': 'btcusdt',
        'side': 'LONG',
        'entry_price': 50000.0,
        'quantity': 0.01,
        'stop_loss': 49500.0,
        'take_profit_1': 50250.0,
        'remaining_size': 0.01,
        'entry_time': datetime.utcnow()
    }

    # Start monitoring
    await components['position_monitor'].start_monitoring(position)

    # Simulate price reaching TP1
    await components['position_monitor'].on_price_update('btcusdt', 50250.0)

    # Verify TP1 was hit (60% closed)
    # TODO: Add assertions once PositionMonitor implements TP logic


@pytest.mark.asyncio
async def test_order_ttl_expiration(components, mock_binance_client):
    """
    Test Order Manager cancels orders after TTL expires
    """
    # Place order with short TTL
    order = await components['order_manager'].place_limit_order(
        symbol='btcusdt',
        side='LONG',
        target_price=50000.0,
        quantity=0.01,
        stop_loss=49500.0,
        confidence=0.85,
        ttl_minutes=1  # 1 minute TTL
    )

    assert order is not None
    assert order.symbol == 'btcusdt'

    # Simulate time passing (61 seconds)
    await asyncio.sleep(0.1)  # Short sleep for test

    # Manually expire order
    order.expires_at = datetime.utcnow()

    # Check TTL
    expired_orders = await components['order_manager'].check_ttl_expiration()

    # Verify order was cancelled
    # TODO: Implement check_ttl_expiration in OrderManager


@pytest.mark.asyncio
async def test_error_handling_order_rejection(components, mock_binance_client):
    """
    Test system handles order rejection gracefully
    """
    # Mock Binance to reject order
    mock_binance_client.create_order = AsyncMock(
        side_effect=Exception("Insufficient margin")
    )

    signal = TradingSignal(
        symbol='btcusdt',
        signal_type=SignalType.LONG,
        confidence=0.85,
        entry_price=50000.0,
        stop_loss=49500.0,
        take_profit_1=50250.0,
        take_profit_2=50500.0,
        atr=100.0,
        timestamp=datetime.utcnow()
    )

    # Execute signal (should handle error gracefully)
    result = await components['execution_adapter'].execute_signal(signal)

    # System should not crash, should return error result
    assert result is None or result.get('success') is False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
