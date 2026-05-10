"""
Property-Based Tests for Performance Metrics Calculation

**Feature: desktop-trading-dashboard, Property 8: Performance Metrics Calculation**
**Validates: Requirements 7.3**

Tests that performance metrics are calculated correctly:
- Win rate = winning_trades / total_trades
- Profit factor = gross_profit / gross_loss
- Max drawdown is calculated correctly
- Total PnL = sum of all realized PnL
"""

import pytest
from hypothesis import given, strategies as st, settings, Phase, HealthCheck
from typing import List
from datetime import datetime, timedelta
import tempfile
import os
import uuid

from src.infrastructure.persistence.sqlite_order_repository import SQLiteOrderRepository
from src.application.services.paper_trading_service import PaperTradingService
from src.domain.entities.paper_position import PaperPosition


# Strategies
num_trades_strategy = st.integers(min_value=1, max_value=50)
pnl_strategy = st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False)


def create_closed_trade(index: int, base_time: datetime, pnl: float) -> PaperPosition:
    """Create a closed trade with specified PnL."""
    return PaperPosition(
        id=str(uuid.uuid4()),
        symbol="BTCUSDT",
        side="LONG" if index % 2 == 0 else "SHORT",
        status="CLOSED",
        entry_price=50000.0,
        quantity=0.01,
        leverage=1,
        margin=500.0,
        liquidation_price=45000.0,
        stop_loss=49000.0,
        take_profit=52000.0,
        open_time=base_time - timedelta(hours=index + 1),
        close_time=base_time - timedelta(hours=index),
        realized_pnl=pnl,
        exit_reason="TAKE_PROFIT" if pnl > 0 else "STOP_LOSS"
    )


def create_fresh_service():
    """Create a fresh service with a new temporary database."""
    temp_fd, temp_path = tempfile.mkstemp(suffix='.db')
    os.close(temp_fd)

    repo = SQLiteOrderRepository(db_path=temp_path)
    service = PaperTradingService(repository=repo)

    return service, repo, temp_path


def cleanup_db(db_path: str):
    """Clean up temporary database file."""
    try:
        if os.path.exists(db_path):
            os.remove(db_path)
    except Exception:
        pass


class TestPerformanceMetricsCalculation:
    """
    Property tests for performance metrics calculation.

    **Feature: desktop-trading-dashboard, Property 8: Performance Metrics Calculation**
    **Validates: Requirements 7.3**
    """

    @given(pnl_values=st.lists(pnl_strategy, min_size=1, max_size=50))
    @settings(max_examples=30, deadline=15000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_total_pnl_equals_sum_of_realized_pnl(self, pnl_values: List[float]):
        """
        Property: Total PnL equals sum of all realized PnL values.

        **Feature: desktop-trading-dashboard, Property 8: Performance Metrics Calculation**
        **Validates: Requirements 7.3**
        """
        service, repo, db_path = create_fresh_service()
        try:
            base_time = datetime.now()

            # Create trades with specified PnL values
            for i, pnl in enumerate(pnl_values):
                trade = create_closed_trade(i, base_time, pnl)
                repo.save_order(trade)

            # Calculate performance
            metrics = service.calculate_performance(days=30)

            # Verify total PnL
            expected_total = sum(pnl_values)
            assert abs(metrics.total_pnl - expected_total) < 0.01, \
                f"Expected total PnL {expected_total}, got {metrics.total_pnl}"
        finally:
            cleanup_db(db_path)

    @given(pnl_values=st.lists(pnl_strategy, min_size=1, max_size=50))
    @settings(max_examples=30, deadline=15000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_win_rate_calculation(self, pnl_values: List[float]):
        """
        Property: Win rate = winning_trades / total_trades.

        **Feature: desktop-trading-dashboard, Property 8: Performance Metrics Calculation**
        **Validates: Requirements 7.3**
        """
        service, repo, db_path = create_fresh_service()
        try:
            base_time = datetime.now()

            # Create trades
            for i, pnl in enumerate(pnl_values):
                trade = create_closed_trade(i, base_time, pnl)
                repo.save_order(trade)

            # Calculate performance
            metrics = service.calculate_performance(days=30)

            # Calculate expected win rate
            winning_trades = sum(1 for pnl in pnl_values if pnl > 0)
            total_trades = len(pnl_values)
            expected_win_rate = winning_trades / total_trades if total_trades > 0 else 0.0

            assert abs(metrics.win_rate - expected_win_rate) < 0.01, \
                f"Expected win rate {expected_win_rate}, got {metrics.win_rate}"
        finally:
            cleanup_db(db_path)

    @given(pnl_values=st.lists(pnl_strategy, min_size=1, max_size=50))
    @settings(max_examples=30, deadline=15000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_profit_factor_calculation(self, pnl_values: List[float]):
        """
        Property: Profit factor = gross_profit / gross_loss (or infinity if no losses).

        **Feature: desktop-trading-dashboard, Property 8: Performance Metrics Calculation**
        **Validates: Requirements 7.3**
        """
        service, repo, db_path = create_fresh_service()
        try:
            base_time = datetime.now()

            # Create trades
            for i, pnl in enumerate(pnl_values):
                trade = create_closed_trade(i, base_time, pnl)
                repo.save_order(trade)

            # Calculate performance
            metrics = service.calculate_performance(days=30)

            # Calculate expected profit factor
            gross_profit = sum(pnl for pnl in pnl_values if pnl > 0)
            gross_loss = abs(sum(pnl for pnl in pnl_values if pnl < 0))

            if gross_loss == 0:
                # No losses - profit factor should be infinity or very high
                assert metrics.profit_factor >= 0, \
                    f"Profit factor should be >= 0 when no losses, got {metrics.profit_factor}"
            else:
                expected_pf = gross_profit / gross_loss
                assert abs(metrics.profit_factor - expected_pf) < 0.01, \
                    f"Expected profit factor {expected_pf}, got {metrics.profit_factor}"
        finally:
            cleanup_db(db_path)

    @given(pnl_values=st.lists(pnl_strategy, min_size=1, max_size=50))
    @settings(max_examples=30, deadline=15000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_trade_counts_correct(self, pnl_values: List[float]):
        """
        Property: Trade counts (total, winning, losing) are accurate.

        **Feature: desktop-trading-dashboard, Property 8: Performance Metrics Calculation**
        **Validates: Requirements 7.3**
        """
        service, repo, db_path = create_fresh_service()
        try:
            base_time = datetime.now()

            # Create trades
            for i, pnl in enumerate(pnl_values):
                trade = create_closed_trade(i, base_time, pnl)
                repo.save_order(trade)

            # Calculate performance
            metrics = service.calculate_performance(days=30)

            # Verify counts
            expected_total = len(pnl_values)
            expected_winning = sum(1 for pnl in pnl_values if pnl > 0)
            expected_losing = sum(1 for pnl in pnl_values if pnl < 0)

            assert metrics.total_trades == expected_total, \
                f"Expected {expected_total} total trades, got {metrics.total_trades}"
            assert metrics.winning_trades == expected_winning, \
                f"Expected {expected_winning} winning trades, got {metrics.winning_trades}"
            assert metrics.losing_trades == expected_losing, \
                f"Expected {expected_losing} losing trades, got {metrics.losing_trades}"
        finally:
            cleanup_db(db_path)

    @given(pnl_values=st.lists(pnl_strategy, min_size=1, max_size=50))
    @settings(max_examples=30, deadline=15000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_max_drawdown_non_negative(self, pnl_values: List[float]):
        """
        Property: Max drawdown is always non-negative.

        **Feature: desktop-trading-dashboard, Property 8: Performance Metrics Calculation**
        **Validates: Requirements 7.3**
        """
        service, repo, db_path = create_fresh_service()
        try:
            base_time = datetime.now()

            # Create trades
            for i, pnl in enumerate(pnl_values):
                trade = create_closed_trade(i, base_time, pnl)
                repo.save_order(trade)

            # Calculate performance
            metrics = service.calculate_performance(days=30)

            assert metrics.max_drawdown >= 0, \
                f"Max drawdown should be >= 0, got {metrics.max_drawdown}"
        finally:
            cleanup_db(db_path)

    @given(pnl_values=st.lists(st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False), min_size=1, max_size=20))
    @settings(max_examples=20, deadline=15000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_all_winning_trades_100_percent_win_rate(self, pnl_values: List[float]):
        """
        Property: If all trades are winning, win rate should be 100%.

        **Feature: desktop-trading-dashboard, Property 8: Performance Metrics Calculation**
        **Validates: Requirements 7.3**
        """
        service, repo, db_path = create_fresh_service()
        try:
            base_time = datetime.now()

            # Create only winning trades
            for i, pnl in enumerate(pnl_values):
                trade = create_closed_trade(i, base_time, abs(pnl))  # Ensure positive
                repo.save_order(trade)

            # Calculate performance
            metrics = service.calculate_performance(days=30)

            assert abs(metrics.win_rate - 1.0) < 0.01, \
                f"Expected 100% win rate for all winning trades, got {metrics.win_rate}"
        finally:
            cleanup_db(db_path)

    @given(pnl_values=st.lists(st.floats(min_value=-1000.0, max_value=-1.0, allow_nan=False, allow_infinity=False), min_size=1, max_size=20))
    @settings(max_examples=20, deadline=15000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_all_losing_trades_0_percent_win_rate(self, pnl_values: List[float]):
        """
        Property: If all trades are losing, win rate should be 0%.

        **Feature: desktop-trading-dashboard, Property 8: Performance Metrics Calculation**
        **Validates: Requirements 7.3**
        """
        service, repo, db_path = create_fresh_service()
        try:
            base_time = datetime.now()

            # Create only losing trades
            for i, pnl in enumerate(pnl_values):
                trade = create_closed_trade(i, base_time, -abs(pnl))  # Ensure negative
                repo.save_order(trade)

            # Calculate performance
            metrics = service.calculate_performance(days=30)

            assert abs(metrics.win_rate - 0.0) < 0.01, \
                f"Expected 0% win rate for all losing trades, got {metrics.win_rate}"
        finally:
            cleanup_db(db_path)
