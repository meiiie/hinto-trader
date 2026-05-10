"""
Property-Based Tests for Trade History Pagination

**Feature: desktop-trading-dashboard, Property 7: Trade History Pagination Correctness**
**Validates: Requirements 7.1**

Tests that for any page number N and page size L, the paginated results SHALL:
- Return at most L items
- Return items sorted by entry_time descending
- Not overlap with results from page N-1 or N+1
"""

import pytest
from hypothesis import given, strategies as st, settings, Phase, HealthCheck
from typing import List
from datetime import datetime, timedelta
import uuid
import tempfile
import os

from src.infrastructure.persistence.sqlite_order_repository import SQLiteOrderRepository
from src.application.services.paper_trading_service import PaperTradingService
from src.domain.entities.paper_position import PaperPosition


# Strategies
page_strategy = st.integers(min_value=1, max_value=10)
limit_strategy = st.integers(min_value=1, max_value=50)
num_trades_strategy = st.integers(min_value=0, max_value=100)


def create_closed_trade(index: int, base_time: datetime) -> PaperPosition:
    """Create a closed trade for testing."""
    return PaperPosition(
        id=str(uuid.uuid4()),
        symbol="BTCUSDT",
        side="LONG" if index % 2 == 0 else "SHORT",
        status="CLOSED",
        entry_price=50000.0 + index * 100,
        quantity=0.01,
        leverage=1,
        margin=500.0,
        liquidation_price=45000.0,
        stop_loss=49000.0,
        take_profit=52000.0,
        open_time=base_time - timedelta(hours=index + 1),
        close_time=base_time - timedelta(hours=index),
        realized_pnl=100.0 if index % 3 == 0 else -50.0,
        exit_reason="TAKE_PROFIT" if index % 3 == 0 else "STOP_LOSS"
    )


def create_fresh_service():
    """Create a fresh service with a new temporary database."""
    # Create unique temp file for each test run
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


class TestPaginationCorrectness:
    """
    Property tests for trade history pagination.

    **Feature: desktop-trading-dashboard, Property 7: Trade History Pagination Correctness**
    **Validates: Requirements 7.1**
    """

    @given(limit=limit_strategy, num_trades=num_trades_strategy)
    @settings(max_examples=30, deadline=10000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_returns_at_most_limit_items(self, limit: int, num_trades: int):
        """
        Property: Pagination returns at most L items per page.

        **Feature: desktop-trading-dashboard, Property 7: Trade History Pagination Correctness**
        **Validates: Requirements 7.1**
        """
        service, repo, db_path = create_fresh_service()
        try:
            # Create trades
            base_time = datetime.now()
            for i in range(num_trades):
                trade = create_closed_trade(i, base_time)
                repo.save_order(trade)

            # Get first page
            result = service.get_trade_history(page=1, limit=limit)

            # Should return at most limit items
            assert len(result.trades) <= limit, \
                f"Expected at most {limit} items, got {len(result.trades)}"
        finally:
            cleanup_db(db_path)

    @given(num_trades=st.integers(min_value=5, max_value=50))
    @settings(max_examples=30, deadline=10000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_items_sorted_by_entry_time_descending(self, num_trades: int):
        """
        Property: Items are sorted by entry_time descending (newest first).

        **Feature: desktop-trading-dashboard, Property 7: Trade History Pagination Correctness**
        **Validates: Requirements 7.1**
        """
        service, repo, db_path = create_fresh_service()
        try:
            # Create trades with different times
            base_time = datetime.now()
            for i in range(num_trades):
                trade = create_closed_trade(i, base_time)
                repo.save_order(trade)

            # Get trades
            result = service.get_trade_history(page=1, limit=num_trades)

            # Verify descending order by close_time
            for i in range(len(result.trades) - 1):
                current = result.trades[i]
                next_trade = result.trades[i + 1]

                if current.close_time and next_trade.close_time:
                    assert current.close_time >= next_trade.close_time, \
                        f"Trades not sorted: {current.close_time} should be >= {next_trade.close_time}"
        finally:
            cleanup_db(db_path)

    @given(
        page=st.integers(min_value=1, max_value=5),
        limit=st.integers(min_value=5, max_value=20)
    )
    @settings(max_examples=30, deadline=10000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_pages_do_not_overlap(self, page: int, limit: int):
        """
        Property: Results from page N do not overlap with page N-1 or N+1.

        **Feature: desktop-trading-dashboard, Property 7: Trade History Pagination Correctness**
        **Validates: Requirements 7.1**
        """
        service, repo, db_path = create_fresh_service()
        try:
            # Create enough trades for multiple pages
            num_trades = limit * 6  # 6 pages worth
            base_time = datetime.now()
            for i in range(num_trades):
                trade = create_closed_trade(i, base_time)
                repo.save_order(trade)

            # Get current page
            current_result = service.get_trade_history(page=page, limit=limit)
            current_ids = {t.id for t in current_result.trades}

            # Get previous page if exists
            if page > 1:
                prev_result = service.get_trade_history(page=page - 1, limit=limit)
                prev_ids = {t.id for t in prev_result.trades}

                overlap = current_ids & prev_ids
                assert len(overlap) == 0, \
                    f"Page {page} overlaps with page {page - 1}: {overlap}"

            # Get next page
            next_result = service.get_trade_history(page=page + 1, limit=limit)
            next_ids = {t.id for t in next_result.trades}

            overlap = current_ids & next_ids
            assert len(overlap) == 0, \
                f"Page {page} overlaps with page {page + 1}: {overlap}"
        finally:
            cleanup_db(db_path)

    @given(limit=limit_strategy, num_trades=num_trades_strategy)
    @settings(max_examples=30, deadline=10000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_total_count_is_accurate(self, limit: int, num_trades: int):
        """
        Property: Total count in pagination matches actual number of trades.

        **Feature: desktop-trading-dashboard, Property 7: Trade History Pagination Correctness**
        **Validates: Requirements 7.1**
        """
        service, repo, db_path = create_fresh_service()
        try:
            # Create trades
            base_time = datetime.now()
            for i in range(num_trades):
                trade = create_closed_trade(i, base_time)
                repo.save_order(trade)

            # Get first page
            result = service.get_trade_history(page=1, limit=limit)

            assert result.total == num_trades, \
                f"Expected total {num_trades}, got {result.total}"
        finally:
            cleanup_db(db_path)

    @given(limit=st.integers(min_value=5, max_value=20))
    @settings(max_examples=20, deadline=10000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_total_pages_calculation(self, limit: int):
        """
        Property: Total pages is correctly calculated as ceiling(total/limit).

        **Feature: desktop-trading-dashboard, Property 7: Trade History Pagination Correctness**
        **Validates: Requirements 7.1**
        """
        service, repo, db_path = create_fresh_service()
        try:
            # Create specific number of trades
            num_trades = 47  # Not evenly divisible by most limits
            base_time = datetime.now()
            for i in range(num_trades):
                trade = create_closed_trade(i, base_time)
                repo.save_order(trade)

            result = service.get_trade_history(page=1, limit=limit)

            expected_pages = (num_trades + limit - 1) // limit
            assert result.total_pages == expected_pages, \
                f"Expected {expected_pages} pages, got {result.total_pages}"
        finally:
            cleanup_db(db_path)

    @given(limit=limit_strategy)
    @settings(max_examples=20, deadline=10000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_empty_result_for_out_of_range_page(self, limit: int):
        """
        Property: Requesting a page beyond total_pages returns empty list.

        **Feature: desktop-trading-dashboard, Property 7: Trade History Pagination Correctness**
        **Validates: Requirements 7.1**
        """
        service, repo, db_path = create_fresh_service()
        try:
            # Create some trades
            num_trades = 10
            base_time = datetime.now()
            for i in range(num_trades):
                trade = create_closed_trade(i, base_time)
                repo.save_order(trade)

            # Request page way beyond
            result = service.get_trade_history(page=100, limit=limit)

            assert len(result.trades) == 0, \
                f"Expected empty list for out-of-range page, got {len(result.trades)} items"
        finally:
            cleanup_db(db_path)
