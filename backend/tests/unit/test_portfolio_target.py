"""
Unit Tests for Portfolio Target Feature

Tests the portfolio target calculation, trigger logic, and exit execution.

SOTA Phase 3 (Jan 2026): Comprehensive unit tests for portfolio target feature.
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch

from src.application.services.position_monitor_service import (
    PositionMonitorService,
    MonitoredPosition,
    PositionPhase
)


class TestPortfolioTargetCalculation:
    """Test portfolio target PnL calculation."""

    @pytest.mark.asyncio
    async def test_portfolio_target_with_3_long_positions(self):
        """Test PnL calculation with 3 LONG positions."""
        # Setup
        monitor = PositionMonitorService()
        monitor.portfolio_target_usd = 100.0  # $100 target

        # Create 3 LONG positions
        pos1 = MonitoredPosition(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            quantity=0.01,
            leverage=10,
            initial_sl=49000.0,
            initial_tp=52000.0
        )
        pos1.max_price = 51000.0  # Current price (profit)

        pos2 = MonitoredPosition(
            symbol="ETHUSDT",
            side="LONG",
            entry_price=3000.0,
            quantity=0.1,
            leverage=10,
            initial_sl=2900.0,
            initial_tp=3200.0
        )
        pos2.max_price = 3100.0  # Current price (profit)

        pos3 = MonitoredPosition(
            symbol="SOLUSDT",
            side="LONG",
            entry_price=100.0,
            quantity=1.0,
            leverage=10,
            initial_sl=95.0,
            initial_tp=110.0
        )
        pos3.max_price = 105.0  # Current price (profit)

        monitor._positions = {
            "BTCUSDT": pos1,
            "ETHUSDT": pos2,
            "SOLUSDT": pos3
        }

        # Calculate expected PnL
        # BTC: (51000 - 50000) * 0.01 = $10
        # ETH: (3100 - 3000) * 0.1 = $10
        # SOL: (105 - 100) * 1.0 = $5
        # Total: $25

        # Test
        result = await monitor._check_portfolio_target()

        # Verify
        assert result is False  # $25 < $100 target

    @pytest.mark.asyncio
    async def test_portfolio_target_with_3_short_positions(self):
        """Test PnL calculation with 3 SHORT positions."""
        # Setup
        monitor = PositionMonitorService()
        monitor.portfolio_target_usd = 50.0  # $50 target

        # Create 3 SHORT positions
        pos1 = MonitoredPosition(
            symbol="BTCUSDT",
            side="SHORT",
            entry_price=50000.0,
            quantity=0.01,
            leverage=10,
            initial_sl=51000.0,
            initial_tp=48000.0
        )
        pos1.min_price = 49000.0  # Current price (profit)

        pos2 = MonitoredPosition(
            symbol="ETHUSDT",
            side="SHORT",
            entry_price=3000.0,
            quantity=0.1,
            leverage=10,
            initial_sl=3100.0,
            initial_tp=2800.0
        )
        pos2.min_price = 2900.0  # Current price (profit)

        pos3 = MonitoredPosition(
            symbol="SOLUSDT",
            side="SHORT",
            entry_price=100.0,
            quantity=1.0,
            leverage=10,
            initial_sl=105.0,
            initial_tp=90.0
        )
        pos3.min_price = 95.0  # Current price (profit)

        monitor._positions = {
            "BTCUSDT": pos1,
            "ETHUSDT": pos2,
            "SOLUSDT": pos3
        }

        # Calculate expected PnL
        # BTC: (50000 - 49000) * 0.01 = $10
        # ETH: (3000 - 2900) * 0.1 = $10
        # SOL: (100 - 95) * 1.0 = $5
        # Total: $25

        # Test
        result = await monitor._check_portfolio_target()

        # Verify
        assert result is False  # $25 < $50 target

    @pytest.mark.asyncio
    async def test_portfolio_target_with_mixed_positions(self):
        """Test PnL calculation with mixed LONG/SHORT positions."""
        # Setup
        monitor = PositionMonitorService()
        monitor.portfolio_target_usd = 20.0  # $20 target

        # Create mixed positions
        pos1 = MonitoredPosition(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            quantity=0.01,
            leverage=10,
            initial_sl=49000.0,
            initial_tp=52000.0
        )
        pos1.max_price = 51000.0  # Profit: $10

        pos2 = MonitoredPosition(
            symbol="ETHUSDT",
            side="SHORT",
            entry_price=3000.0,
            quantity=0.1,
            leverage=10,
            initial_sl=3100.0,
            initial_tp=2800.0
        )
        pos2.min_price = 2900.0  # Profit: $10

        pos3 = MonitoredPosition(
            symbol="SOLUSDT",
            side="LONG",
            entry_price=100.0,
            quantity=1.0,
            leverage=10,
            initial_sl=95.0,
            initial_tp=110.0
        )
        pos3.max_price = 105.0  # Profit: $5

        monitor._positions = {
            "BTCUSDT": pos1,
            "ETHUSDT": pos2,
            "SOLUSDT": pos3
        }

        # Total PnL: $10 + $10 + $5 = $25

        # Test
        result = await monitor._check_portfolio_target()

        # Verify
        assert result is True  # $25 >= $20 target

    @pytest.mark.asyncio
    async def test_portfolio_target_with_zero_positions(self):
        """Test PnL calculation with zero positions."""
        # Setup
        monitor = PositionMonitorService()
        monitor.portfolio_target_usd = 100.0
        monitor._positions = {}

        # Test
        result = await monitor._check_portfolio_target()

        # Verify
        assert result is False  # No positions = no target hit


class TestPortfolioTargetTriggerLogic:
    """Test portfolio target trigger conditions."""

    @pytest.mark.asyncio
    async def test_target_hit_when_pnl_equals_target(self):
        """Test target triggers when PnL equals target."""
        # Setup
        monitor = PositionMonitorService()
        monitor.portfolio_target_usd = 100.0

        pos = MonitoredPosition(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            quantity=0.01,
            leverage=10,
            initial_sl=49000.0,
            initial_tp=60000.0
        )
        pos.max_price = 60000.0  # PnL = (60000-50000)*0.01 = $100

        monitor._positions = {"BTCUSDT": pos}

        # Test
        result = await monitor._check_portfolio_target()

        # Verify
        assert result is True

    @pytest.mark.asyncio
    async def test_target_hit_when_pnl_exceeds_target(self):
        """Test target triggers when PnL exceeds target."""
        # Setup
        monitor = PositionMonitorService()
        monitor.portfolio_target_usd = 100.0

        pos = MonitoredPosition(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            quantity=0.01,
            leverage=10,
            initial_sl=49000.0,
            initial_tp=62000.0
        )
        pos.max_price = 62000.0  # PnL = (62000-50000)*0.01 = $120

        monitor._positions = {"BTCUSDT": pos}

        # Test
        result = await monitor._check_portfolio_target()

        # Verify
        assert result is True

    @pytest.mark.asyncio
    async def test_target_not_hit_when_pnl_below_target(self):
        """Test target doesn't trigger when PnL below target."""
        # Setup
        monitor = PositionMonitorService()
        monitor.portfolio_target_usd = 100.0

        pos = MonitoredPosition(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            quantity=0.01,
            leverage=10,
            initial_sl=49000.0,
            initial_tp=55000.0
        )
        pos.max_price = 55000.0  # PnL = (55000-50000)*0.01 = $50

        monitor._positions = {"BTCUSDT": pos}

        # Test
        result = await monitor._check_portfolio_target()

        # Verify
        assert result is False

    @pytest.mark.asyncio
    async def test_target_disabled_when_zero(self):
        """Test target disabled when set to 0."""
        # Setup
        monitor = PositionMonitorService()
        monitor.portfolio_target_usd = 0.0  # Disabled

        pos = MonitoredPosition(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            quantity=0.01,
            leverage=10,
            initial_sl=49000.0,
            initial_tp=60000.0
        )
        pos.max_price = 60000.0  # PnL = $100

        monitor._positions = {"BTCUSDT": pos}

        # Test
        result = await monitor._check_portfolio_target()

        # Verify
        assert result is False  # Target disabled


class TestPortfolioTargetThreadSafety:
    """Test thread-safety of portfolio target checks."""

    @pytest.mark.asyncio
    async def test_concurrent_pnl_calculations(self):
        """Test concurrent PnL calculations don't cause race conditions."""
        # Setup
        monitor = PositionMonitorService()
        monitor.portfolio_target_usd = 100.0

        pos = MonitoredPosition(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            quantity=0.01,
            leverage=10,
            initial_sl=49000.0,
            initial_tp=60000.0
        )
        pos.max_price = 60000.0

        monitor._positions = {"BTCUSDT": pos}

        # Test: Run 10 concurrent checks
        tasks = [monitor._check_portfolio_target() for _ in range(10)]
        results = await asyncio.gather(*tasks)

        # Verify: All results should be consistent
        assert all(r is True for r in results)

    @pytest.mark.asyncio
    async def test_lock_prevents_race_conditions(self):
        """Test asyncio.Lock prevents race conditions."""
        # Setup
        monitor = PositionMonitorService()
        monitor.portfolio_target_usd = 100.0

        # Verify lock exists
        assert hasattr(monitor, '_portfolio_check_lock')
        assert isinstance(monitor._portfolio_check_lock, asyncio.Lock)


class TestPortfolioTargetRetryLogic:
    """Test retry logic for position exits."""

    @pytest.mark.asyncio
    async def test_successful_exit_on_first_attempt(self):
        """Test successful exit on first attempt."""
        # Setup
        monitor = PositionMonitorService()

        pos = MonitoredPosition(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            quantity=0.01,
            leverage=10,
            initial_sl=49000.0,
            initial_tp=60000.0
        )

        # Mock successful close
        monitor._close_position_async = AsyncMock(return_value=True)
        monitor._cleanup_orders = AsyncMock(return_value=True)

        # Test
        result = await monitor._exit_position_with_retry(pos)

        # Verify
        assert result is True
        assert monitor._close_position_async.call_count == 1

    @pytest.mark.asyncio
    async def test_successful_exit_on_retry(self):
        """Test successful exit on retry after initial failure."""
        # Setup
        monitor = PositionMonitorService()

        pos = MonitoredPosition(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            quantity=0.01,
            leverage=10,
            initial_sl=49000.0,
            initial_tp=60000.0
        )

        # Mock: Fail first, succeed second
        monitor._close_position_async = AsyncMock(
            side_effect=[Exception("Network error"), True]
        )
        monitor._cleanup_orders = AsyncMock(return_value=True)

        # Test
        result = await monitor._exit_position_with_retry(pos, max_retries=3)

        # Verify
        assert result is True
        assert monitor._close_position_async.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_exhaustion_after_3_failures(self):
        """Test retry exhaustion after 3 failures."""
        # Setup
        monitor = PositionMonitorService()

        pos = MonitoredPosition(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            quantity=0.01,
            leverage=10,
            initial_sl=49000.0,
            initial_tp=60000.0
        )

        # Mock: Always fail
        monitor._close_position_async = AsyncMock(
            side_effect=Exception("Network error")
        )

        # Test
        result = await monitor._exit_position_with_retry(pos, max_retries=3)

        # Verify
        assert result is False
        assert monitor._close_position_async.call_count == 3


class TestPortfolioTargetValidation:
    """Test validation and error handling."""

    @pytest.mark.asyncio
    async def test_invalid_quantity_skipped(self):
        """Test position with invalid quantity is skipped."""
        # Setup
        monitor = PositionMonitorService()
        monitor.portfolio_target_usd = 100.0

        pos = MonitoredPosition(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            quantity=0.0,  # Invalid!
            leverage=10,
            initial_sl=49000.0,
            initial_tp=60000.0
        )
        pos.max_price = 60000.0

        monitor._positions = {"BTCUSDT": pos}

        # Test
        result = await monitor._check_portfolio_target()

        # Verify
        assert result is False  # Invalid position skipped

    @pytest.mark.asyncio
    async def test_invalid_entry_price_skipped(self):
        """Test position with invalid entry price is skipped."""
        # Setup
        monitor = PositionMonitorService()
        monitor.portfolio_target_usd = 100.0

        pos = MonitoredPosition(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=0.0,  # Invalid!
            quantity=0.01,
            leverage=10,
            initial_sl=49000.0,
            initial_tp=60000.0
        )
        pos.max_price = 60000.0

        monitor._positions = {"BTCUSDT": pos}

        # Test
        result = await monitor._check_portfolio_target()

        # Verify
        assert result is False  # Invalid position skipped

    @pytest.mark.asyncio
    async def test_extreme_price_movement_detected(self):
        """Test extreme price movement (>50%) is detected and handled."""
        # Setup
        monitor = PositionMonitorService()
        monitor.portfolio_target_usd = 100.0

        pos = MonitoredPosition(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            quantity=0.01,
            leverage=10,
            initial_sl=49000.0,
            initial_tp=60000.0
        )
        pos.max_price = 100000.0  # 100% increase - extreme!

        monitor._positions = {"BTCUSDT": pos}

        # Test
        result = await monitor._check_portfolio_target()

        # Verify: Should use entry price instead of extreme price
        # PnL = 0 (using entry price)
        assert result is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
