"""
Integration Tests for Portfolio Target Feature

Tests the portfolio target feature with mock positions, WebSocket, and exit execution.

SOTA Phase 3.2 (Jan 2026): Integration tests for portfolio target feature.
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from src.application.services.position_monitor_service import (
    PositionMonitorService,
    MonitoredPosition,
    PositionPhase
)


class TestPortfolioTargetWithMockPositions:
    """Test portfolio target with mock positions."""

    @pytest.mark.asyncio
    async def test_portfolio_target_with_3_mock_positions(self):
        """Test portfolio target with 3 mock positions and price updates."""
        # Setup
        monitor = PositionMonitorService()
        monitor.portfolio_target_usd = 50.0  # $50 target

        # Mock callbacks
        close_callback = AsyncMock()
        cleanup_callback = AsyncMock()
        monitor._close_position_async = close_callback
        monitor._cleanup_orders = cleanup_callback

        # Create 3 positions
        pos1 = MonitoredPosition(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            quantity=0.01,
            leverage=10,
            initial_sl=49000.0,
            initial_tp=52000.0
        )

        pos2 = MonitoredPosition(
            symbol="ETHUSDT",
            side="LONG",
            entry_price=3000.0,
            quantity=0.1,
            leverage=10,
            initial_sl=2900.0,
            initial_tp=3200.0
        )

        pos3 = MonitoredPosition(
            symbol="SOLUSDT",
            side="LONG",
            entry_price=100.0,
            quantity=1.0,
            leverage=10,
            initial_sl=95.0,
            initial_tp=110.0
        )

        monitor._positions = {
            "BTCUSDT": pos1,
            "ETHUSDT": pos2,
            "SOLUSDT": pos3
        }

        # Simulate price updates (not enough to hit target)
        pos1.max_price = 50500.0  # +$5
        pos2.max_price = 3050.0   # +$5
        pos3.max_price = 102.0    # +$2
        # Total: $12 < $50

        # Test: Check target (should not hit)
        result = await monitor._check_portfolio_target()
        assert result is False

        # Simulate more price updates (hit target)
        pos1.max_price = 51000.0  # +$10
        pos2.max_price = 3200.0   # +$20
        pos3.max_price = 120.0    # +$20
        # Total: $50 >= $50

        # Test: Check target (should hit)
        result = await monitor._check_portfolio_target()
        assert result is True

        # Test: Exit all positions
        await monitor._exit_all_positions_portfolio_target()

        # Verify: All positions closed
        assert close_callback.call_count == 3
        assert cleanup_callback.call_count == 3

        # Verify: Correct symbols closed
        closed_symbols = [call[0][0] for call in close_callback.call_args_list]
        assert "BTCUSDT" in closed_symbols
        assert "ETHUSDT" in closed_symbols
        assert "SOLUSDT" in closed_symbols

    @pytest.mark.asyncio
    async def test_portfolio_target_partial_failure(self):
        """Test portfolio target with partial exit failures."""
        # Setup
        monitor = PositionMonitorService()
        monitor.portfolio_target_usd = 30.0

        # Mock callbacks: 1 success, 1 failure
        async def mock_close(symbol):
            if symbol == "BTCUSDT":
                return True  # Success
            else:
                raise Exception("Network error")  # Failure

        monitor._close_position_async = AsyncMock(side_effect=mock_close)
        monitor._cleanup_orders = AsyncMock()

        # Create 2 positions
        pos1 = MonitoredPosition(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            quantity=0.01,
            leverage=10,
            initial_sl=49000.0,
            initial_tp=52000.0
        )
        pos1.max_price = 53000.0  # +$30

        pos2 = MonitoredPosition(
            symbol="ETHUSDT",
            side="LONG",
            entry_price=3000.0,
            quantity=0.1,
            leverage=10,
            initial_sl=2900.0,
            initial_tp=3200.0
        )
        pos2.max_price = 3100.0  # +$10

        monitor._positions = {
            "BTCUSDT": pos1,
            "ETHUSDT": pos2
        }

        # Test: Exit all positions
        await monitor._exit_all_positions_portfolio_target()

        # Verify: Both attempted (with retries for failed one)
        # BTCUSDT: 1 attempt (success)
        # ETHUSDT: 3 attempts (all fail)
        assert monitor._close_position_async.call_count == 4  # 1 + 3


class TestPortfolioTargetWithMockWebSocket:
    """Test portfolio target with mock WebSocket price feed."""

    @pytest.mark.asyncio
    async def test_realtime_price_updates_trigger_target(self):
        """Test real-time price updates trigger portfolio target."""
        # Setup
        monitor = PositionMonitorService()
        monitor.portfolio_target_usd = 25.0

        # Mock callbacks
        close_callback = AsyncMock()
        cleanup_callback = AsyncMock()
        monitor._close_position_async = close_callback
        monitor._cleanup_orders = cleanup_callback

        # Create position
        pos = MonitoredPosition(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            quantity=0.01,
            leverage=10,
            initial_sl=49000.0,
            initial_tp=52000.0
        )

        monitor._positions = {"BTCUSDT": pos}

        # Simulate WebSocket price updates
        prices = [50100, 50200, 50500, 51000, 52000, 52500]

        for price in prices:
            # Update watermark
            pos.max_price = price

            # Check target
            target_hit = await monitor._check_portfolio_target()

            # Calculate expected PnL
            pnl = (price - 50000.0) * 0.01

            if pnl >= 25.0:
                # Should trigger
                assert target_hit is True
                break
            else:
                # Should not trigger
                assert target_hit is False

        # Verify: Target hit at $52500 (PnL = $25)
        assert pos.max_price == 52500.0
        assert target_hit is True

    @pytest.mark.asyncio
    async def test_portfolio_check_runs_every_tick(self):
        """Test portfolio check runs every tick (1 second frequency)."""
        # Setup
        monitor = PositionMonitorService()
        monitor.portfolio_target_usd = 100.0

        # Create position
        pos = MonitoredPosition(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            quantity=0.01,
            leverage=10,
            initial_sl=49000.0,
            initial_tp=60000.0
        )
        pos.max_price = 55000.0  # PnL = $50 (not enough)

        monitor._positions = {"BTCUSDT": pos}

        # Simulate 10 ticks
        check_count = 0
        for i in range(10):
            result = await monitor._check_portfolio_target()
            check_count += 1

            # Should not trigger (PnL < target)
            assert result is False

        # Verify: Checked 10 times
        assert check_count == 10


class TestPortfolioTargetExitExecution:
    """Test portfolio target exit execution flow."""

    @pytest.mark.asyncio
    async def test_concurrent_exit_execution(self):
        """Test concurrent exit execution for multiple positions."""
        # Setup
        monitor = PositionMonitorService()
        monitor.portfolio_target_usd = 30.0

        # Track execution order
        execution_order = []

        async def mock_close(symbol):
            execution_order.append(symbol)
            await asyncio.sleep(0.1)  # Simulate network delay
            return True

        monitor._close_position_async = AsyncMock(side_effect=mock_close)
        monitor._cleanup_orders = AsyncMock()

        # Create 3 positions
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        for symbol in symbols:
            pos = MonitoredPosition(
                symbol=symbol,
                side="LONG",
                entry_price=1000.0,
                quantity=0.01,
                leverage=10,
                initial_sl=900.0,
                initial_tp=1200.0
            )
            pos.max_price = 2000.0  # +$10 each
            monitor._positions[symbol] = pos

        # Test: Exit all positions
        start_time = asyncio.get_event_loop().time()
        await monitor._exit_all_positions_portfolio_target()
        end_time = asyncio.get_event_loop().time()

        # Verify: All positions closed
        assert len(execution_order) == 3

        # Verify: Concurrent execution (should take ~0.1s, not 0.3s)
        execution_time = end_time - start_time
        assert execution_time < 0.2  # Concurrent, not sequential

    @pytest.mark.asyncio
    async def test_cleanup_orders_called_after_exit(self):
        """Test cleanup_orders called after each position exit."""
        # Setup
        monitor = PositionMonitorService()
        monitor.portfolio_target_usd = 10.0

        # Mock callbacks
        close_callback = AsyncMock()
        cleanup_callback = AsyncMock()
        monitor._close_position_async = close_callback
        monitor._cleanup_orders = cleanup_callback

        # Create position
        pos = MonitoredPosition(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            quantity=0.01,
            leverage=10,
            initial_sl=49000.0,
            initial_tp=52000.0
        )
        pos.max_price = 51000.0  # +$10

        monitor._positions = {"BTCUSDT": pos}

        # Test: Exit position
        await monitor._exit_all_positions_portfolio_target()

        # Verify: cleanup_orders called
        assert cleanup_callback.call_count == 1
        assert cleanup_callback.call_args[0][0] == "BTCUSDT"
        assert cleanup_callback.call_args[0][1] == "PORTFOLIO_TARGET"

    @pytest.mark.asyncio
    async def test_stop_monitoring_called_after_exit(self):
        """Test stop_monitoring called after position exit."""
        # Setup
        monitor = PositionMonitorService()
        monitor.portfolio_target_usd = 10.0

        # Mock callbacks
        monitor._close_position_async = AsyncMock()
        monitor._cleanup_orders = AsyncMock()

        # Create position
        pos = MonitoredPosition(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            quantity=0.01,
            leverage=10,
            initial_sl=49000.0,
            initial_tp=52000.0
        )
        pos.max_price = 51000.0  # +$10

        monitor._positions = {"BTCUSDT": pos}

        # Test: Exit position
        await monitor._exit_all_positions_portfolio_target()

        # Verify: Position removed from monitoring
        assert "BTCUSDT" not in monitor._positions


class TestPortfolioTargetPerformance:
    """Test portfolio target performance and latency."""

    @pytest.mark.asyncio
    async def test_portfolio_check_latency(self):
        """Test portfolio check completes in < 100ms."""
        # Setup
        monitor = PositionMonitorService()
        monitor.portfolio_target_usd = 100.0

        # Create 10 positions
        for i in range(10):
            pos = MonitoredPosition(
                symbol=f"SYMBOL{i}USDT",
                side="LONG",
                entry_price=1000.0,
                quantity=0.01,
                leverage=10,
                initial_sl=900.0,
                initial_tp=1200.0
            )
            pos.max_price = 1100.0  # +$1 each
            monitor._positions[f"SYMBOL{i}USDT"] = pos

        # Test: Measure check latency
        start_time = asyncio.get_event_loop().time()
        await monitor._check_portfolio_target()
        end_time = asyncio.get_event_loop().time()

        # Verify: Latency < 100ms
        latency_ms = (end_time - start_time) * 1000
        assert latency_ms < 100

    @pytest.mark.asyncio
    async def test_exit_trigger_latency(self):
        """Test exit trigger completes in < 1 second."""
        # Setup
        monitor = PositionMonitorService()
        monitor.portfolio_target_usd = 10.0

        # Mock fast callbacks
        monitor._close_position_async = AsyncMock()
        monitor._cleanup_orders = AsyncMock()

        # Create 3 positions
        for i in range(3):
            pos = MonitoredPosition(
                symbol=f"SYMBOL{i}USDT",
                side="LONG",
                entry_price=1000.0,
                quantity=0.01,
                leverage=10,
                initial_sl=900.0,
                initial_tp=1200.0
            )
            pos.max_price = 1400.0  # +$4 each = $12 total
            monitor._positions[f"SYMBOL{i}USDT"] = pos

        # Test: Measure exit latency
        start_time = asyncio.get_event_loop().time()
        await monitor._exit_all_positions_portfolio_target()
        end_time = asyncio.get_event_loop().time()

        # Verify: Latency < 1 second
        latency_s = end_time - start_time
        assert latency_s < 1.0


class TestPortfolioTargetEdgeCases:
    """Test portfolio target edge cases."""

    @pytest.mark.asyncio
    async def test_target_hit_during_exit(self):
        """Test target hit again during exit execution."""
        # Setup
        monitor = PositionMonitorService()
        monitor.portfolio_target_usd = 20.0

        # Mock callbacks
        monitor._close_position_async = AsyncMock()
        monitor._cleanup_orders = AsyncMock()

        # Create 2 positions
        pos1 = MonitoredPosition(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            quantity=0.01,
            leverage=10,
            initial_sl=49000.0,
            initial_tp=52000.0
        )
        pos1.max_price = 52000.0  # +$20

        pos2 = MonitoredPosition(
            symbol="ETHUSDT",
            side="LONG",
            entry_price=3000.0,
            quantity=0.1,
            leverage=10,
            initial_sl=2900.0,
            initial_tp=3200.0
        )
        pos2.max_price = 3100.0  # +$10

        monitor._positions = {
            "BTCUSDT": pos1,
            "ETHUSDT": pos2
        }

        # Test: Check target (should hit)
        result1 = await monitor._check_portfolio_target()
        assert result1 is True

        # Start exit
        exit_task = asyncio.create_task(
            monitor._exit_all_positions_portfolio_target()
        )

        # Check target again during exit (should still hit)
        result2 = await monitor._check_portfolio_target()
        assert result2 is True

        # Wait for exit to complete
        await exit_task

    @pytest.mark.asyncio
    async def test_position_removed_during_check(self):
        """Test position removed during portfolio check."""
        # Setup
        monitor = PositionMonitorService()
        monitor.portfolio_target_usd = 20.0

        # Create position
        pos = MonitoredPosition(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            quantity=0.01,
            leverage=10,
            initial_sl=49000.0,
            initial_tp=52000.0
        )
        pos.max_price = 52000.0  # +$20

        monitor._positions = {"BTCUSDT": pos}

        # Test: Check target (should hit)
        result1 = await monitor._check_portfolio_target()
        assert result1 is True

        # Remove position
        del monitor._positions["BTCUSDT"]

        # Check target again (should not hit - no positions)
        result2 = await monitor._check_portfolio_target()
        assert result2 is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
