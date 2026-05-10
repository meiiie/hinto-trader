"""
Unit Tests for Graceful Shutdown - Phase 5 Task 5.2

Tests the graceful shutdown functionality of the live trading system.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

run_live_trading = pytest.importorskip(
    "run_live_trading",
    reason="legacy backtest_live runner module is not available in this codebase",
)
LiveTradingRunner = run_live_trading.LiveTradingRunner


class TestGracefulShutdown:
    """Test graceful shutdown functionality"""

    @pytest.fixture
    def config(self):
        """Test configuration"""
        return {
            'balance': 34.0,
            'leverage': 10,
            'max_positions': 5,
            'risk_percent': 1.0,
            'ttl_minutes': 50,
            'zombie_killer': False,
            'full_tp': False,
            'dry_run': True,
            'emergency_stop': False
        }

    @pytest.fixture
    def runner(self, config):
        """Create LiveTradingRunner instance"""
        return LiveTradingRunner(config)

    @pytest.mark.asyncio
    async def test_stop_saves_state(self, runner):
        """Test that stop() saves state before exiting"""
        # Mock components
        runner.data_manager = AsyncMock()
        runner.position_monitor = AsyncMock()
        runner.binance_client = AsyncMock()
        runner.trade_repository = Mock()
        runner.trade_repository.export_to_csv = Mock()
        runner.trade_repository.close = Mock()
        runner.execution_adapter = Mock()
        runner.execution_adapter.balance = 35.5
        runner.execution_adapter.get_positions = Mock(return_value={})
        runner.order_manager = Mock()
        runner.order_manager.pending_orders = {}

        # Mock _save_state
        runner._save_state = AsyncMock()

        # Set running state
        runner._is_running = True

        # Execute stop
        await runner.stop(emergency_close_positions=False)

        # Verify state was saved
        runner._save_state.assert_called_once()

        # Verify database was closed
        runner.trade_repository.close.assert_called_once()

        # Verify CSV was exported
        runner.trade_repository.export_to_csv.assert_called_once()

        # Verify WebSocket was disconnected
        runner.binance_client.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_closes_websocket(self, runner):
        """Test that stop() closes WebSocket connections"""
        # Mock components
        runner.data_manager = AsyncMock()
        runner.position_monitor = AsyncMock()
        runner.binance_client = AsyncMock()
        runner.trade_repository = Mock()
        runner.trade_repository.export_to_csv = Mock()
        runner.trade_repository.close = Mock()
        runner.execution_adapter = Mock()
        runner.execution_adapter.balance = 34.0
        runner.execution_adapter.get_positions = Mock(return_value={})
        runner.order_manager = Mock()
        runner.order_manager.pending_orders = {}
        runner._save_state = AsyncMock()

        runner._is_running = True

        # Execute stop
        await runner.stop()

        # Verify WebSocket disconnect was called
        runner.binance_client.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_emergency_stop_closes_positions(self, runner):
        """Test that emergency stop closes all positions"""
        # Mock components
        runner.data_manager = AsyncMock()
        runner.position_monitor = AsyncMock()
        runner.binance_client = AsyncMock()
        runner.trade_repository = Mock()
        runner.trade_repository.export_to_csv = Mock()
        runner.trade_repository.close = Mock()
        runner.order_manager = Mock()
        runner.order_manager.pending_orders = {}
        runner._save_state = AsyncMock()

        # Mock execution adapter with positions
        runner.execution_adapter = Mock()
        runner.execution_adapter.balance = 34.0
        runner.execution_adapter.positions = {
            'btcusdt': {
                'side': 'LONG',
                'remaining_size': 0.1,
                'entry_price': 50000
            },
            'ethusdt': {
                'side': 'SHORT',
                'remaining_size': 1.0,
                'entry_price': 3000
            }
        }
        runner.execution_adapter.get_positions = Mock(return_value=runner.execution_adapter.positions)

        # Mock emergency close method
        runner._emergency_close_all_positions = AsyncMock()

        runner._is_running = True

        # Execute emergency stop
        await runner.stop(emergency_close_positions=True)

        # Verify emergency close was called
        runner._emergency_close_all_positions.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_cancels_pending_orders(self, runner):
        """Test that stop() cancels all pending orders"""
        # Mock components
        runner.data_manager = AsyncMock()
        runner.position_monitor = AsyncMock()
        runner.binance_client = AsyncMock()
        runner.trade_repository = Mock()
        runner.trade_repository.export_to_csv = Mock()
        runner.trade_repository.close = Mock()
        runner.execution_adapter = Mock()
        runner.execution_adapter.balance = 34.0
        runner.execution_adapter.get_positions = Mock(return_value={})
        runner._save_state = AsyncMock()

        # Mock order manager with pending orders
        runner.order_manager = Mock()
        runner.order_manager.pending_orders = {
            'btcusdt': Mock(),
            'ethusdt': Mock()
        }

        # Mock cancel method
        runner._cancel_all_pending_orders = AsyncMock()

        runner._is_running = True

        # Execute stop
        await runner.stop()

        # Verify cancel was called
        runner._cancel_all_pending_orders.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_handles_errors_gracefully(self, runner):
        """Test that stop() continues even if steps fail"""
        # Mock components with some failing
        runner.data_manager = AsyncMock()
        runner.data_manager.stop = AsyncMock(side_effect=Exception("Data manager error"))

        runner.position_monitor = AsyncMock()
        runner.binance_client = AsyncMock()
        runner.trade_repository = Mock()
        runner.trade_repository.export_to_csv = Mock()
        runner.trade_repository.close = Mock()
        runner.execution_adapter = Mock()
        runner.execution_adapter.balance = 34.0
        runner.execution_adapter.get_positions = Mock(return_value={})
        runner.order_manager = Mock()
        runner.order_manager.pending_orders = {}
        runner._save_state = AsyncMock()

        runner._is_running = True

        # Execute stop - should not raise exception
        await runner.stop()

        # Verify other steps still executed
        runner._save_state.assert_called_once()
        runner.binance_client.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_idempotent(self, runner):
        """Test that calling stop() multiple times is safe"""
        # Mock components
        runner.data_manager = AsyncMock()
        runner.position_monitor = AsyncMock()
        runner.binance_client = AsyncMock()
        runner.trade_repository = Mock()
        runner.trade_repository.export_to_csv = Mock()
        runner.trade_repository.close = Mock()
        runner.execution_adapter = Mock()
        runner.execution_adapter.balance = 34.0
        runner.execution_adapter.get_positions = Mock(return_value={})
        runner.order_manager = Mock()
        runner.order_manager.pending_orders = {}
        runner._save_state = AsyncMock()

        runner._is_running = True

        # Call stop twice
        await runner.stop()
        await runner.stop()

        # Should only execute once (second call returns early)
        assert runner._save_state.call_count == 1

    @pytest.mark.asyncio
    async def test_emergency_close_respects_dry_run(self, runner):
        """Test that emergency close respects dry-run mode"""
        # Set dry-run mode
        runner.config['dry_run'] = True

        # Mock components
        runner.binance_client = Mock()
        runner.binance_client.futures_create_order = Mock()

        runner.execution_adapter = Mock()
        runner.execution_adapter.positions = {
            'btcusdt': Mock(side='LONG', remaining_size=0.1)
        }

        # Execute emergency close
        await runner._emergency_close_all_positions()

        # Verify no real orders were placed
        runner.binance_client.futures_create_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_cancel_all_pending_orders(self, runner):
        """Test cancelling all pending orders"""
        # Mock order manager
        runner.order_manager = Mock()
        runner.order_manager.pending_orders = {
            'btcusdt': Mock(),
            'ethusdt': Mock(),
            'bnbusdt': Mock()
        }
        runner.order_manager.cancel_order = AsyncMock()

        # Execute cancel
        await runner._cancel_all_pending_orders()

        # Verify all orders were cancelled
        assert runner.order_manager.cancel_order.call_count == 3

        # Verify correct symbols were passed
        calls = runner.order_manager.cancel_order.call_args_list
        symbols = [call[0][0] for call in calls]
        assert 'btcusdt' in symbols
        assert 'ethusdt' in symbols
        assert 'bnbusdt' in symbols


class TestLiveTradeRepositoryClose:
    """Test LiveTradeRepository.close() method"""

    def test_close_flushes_wal(self):
        """Test that close() flushes WAL checkpoint"""
        from src.infrastructure.persistence.live_trade_repository import LiveTradeRepository

        # Create repository
        repo = LiveTradeRepository(db_path='data/test_shutdown.db')

        # Mock connection
        with patch.object(repo, '_get_connection') as mock_conn:
            mock_context = MagicMock()
            mock_conn.return_value.__enter__ = Mock(return_value=mock_context)
            mock_conn.return_value.__exit__ = Mock(return_value=False)

            # Call close
            repo.close()

            # Verify WAL checkpoint was executed
            mock_context.execute.assert_called_once_with('PRAGMA wal_checkpoint(FULL);')
            mock_context.commit.assert_called_once()

    def test_close_handles_errors(self):
        """Test that close() handles errors gracefully"""
        from src.infrastructure.persistence.live_trade_repository import LiveTradeRepository

        # Create repository
        repo = LiveTradeRepository(db_path='data/test_shutdown.db')

        # Mock connection to raise error
        with patch.object(repo, '_get_connection') as mock_conn:
            mock_conn.return_value.__enter__ = Mock(side_effect=Exception("DB error"))

            # Call close - should not raise
            repo.close()  # Should log warning but not raise


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
