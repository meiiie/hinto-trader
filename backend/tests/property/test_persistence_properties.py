"""
Property-Based Tests for Trade Persistence

**Feature: desktop-trading-dashboard, Property 2: Paper Trade Persistence Round-Trip**
**Validates: Requirements 4.3**

Tests that for any paper trade that is executed, serializing the trade to SQLite
and then deserializing it produces an equivalent trade object with all fields preserved.
"""

import os
import tempfile
import pytest
from datetime import datetime, timedelta
from hypothesis import given, strategies as st, settings, assume, Phase, HealthCheck

from src.domain.entities.paper_position import PaperPosition
from src.infrastructure.persistence.sqlite_order_repository import SQLiteOrderRepository


# Custom strategies for generating valid trade data
@st.composite
def paper_position_strategy(draw):
    """Generate random but valid PaperPosition objects"""

    # Generate valid ID (UUID-like string)
    position_id = draw(st.uuids().map(str))

    # Symbol - common crypto pairs
    symbol = draw(st.sampled_from(['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT']))

    # Side - LONG or SHORT
    side = draw(st.sampled_from(['LONG', 'SHORT']))

    # Status - for round-trip we test OPEN and CLOSED
    status = draw(st.sampled_from(['OPEN', 'CLOSED', 'PENDING']))

    # Prices - realistic crypto prices
    entry_price = draw(st.floats(min_value=100.0, max_value=100000.0, allow_nan=False, allow_infinity=False))

    # Quantity - reasonable position sizes
    quantity = draw(st.floats(min_value=0.001, max_value=10.0, allow_nan=False, allow_infinity=False))

    # Leverage - 1x to 20x
    leverage = draw(st.integers(min_value=1, max_value=20))

    # Margin - calculated from entry and quantity
    margin = (entry_price * quantity) / leverage

    # Liquidation price - depends on side
    if side == 'LONG':
        liquidation_price = entry_price - (margin / quantity) if quantity > 0 else 0.0
    else:
        liquidation_price = entry_price + (margin / quantity) if quantity > 0 else 0.0

    # Stop loss and take profit
    stop_loss = draw(st.floats(min_value=0.0, max_value=entry_price * 0.95, allow_nan=False, allow_infinity=False))
    take_profit = draw(st.floats(min_value=entry_price * 1.01, max_value=entry_price * 2.0, allow_nan=False, allow_infinity=False))

    # Times
    open_time = datetime.now() - timedelta(hours=draw(st.integers(min_value=0, max_value=168)))
    close_time = None
    if status == 'CLOSED':
        close_time = open_time + timedelta(minutes=draw(st.integers(min_value=1, max_value=1440)))

    # PnL
    realized_pnl = 0.0
    if status == 'CLOSED':
        realized_pnl = draw(st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False))

    # Exit reason
    exit_reason = None
    if status == 'CLOSED':
        exit_reason = draw(st.sampled_from(['STOP_LOSS', 'TAKE_PROFIT', 'MANUAL_CLOSE', 'LIQUIDATION', 'SIGNAL_REVERSAL']))

    # Trailing stop tracking
    highest_price = draw(st.floats(min_value=entry_price, max_value=entry_price * 1.5, allow_nan=False, allow_infinity=False))
    lowest_price = draw(st.floats(min_value=entry_price * 0.5, max_value=entry_price, allow_nan=False, allow_infinity=False))

    return PaperPosition(
        id=position_id,
        symbol=symbol,
        side=side,
        status=status,
        entry_price=entry_price,
        quantity=quantity,
        leverage=leverage,
        margin=margin,
        liquidation_price=liquidation_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        open_time=open_time,
        close_time=close_time,
        realized_pnl=realized_pnl,
        exit_reason=exit_reason,
        highest_price=highest_price,
        lowest_price=lowest_price
    )


class TestTradePersistenceRoundTrip:
    """
    Property tests for trade persistence round-trip.

    **Feature: desktop-trading-dashboard, Property 2: Paper Trade Persistence Round-Trip**
    **Validates: Requirements 4.3**
    """

    @pytest.fixture(autouse=True)
    def setup_temp_db(self, tmp_path):
        """Create a temporary database for each test"""
        # Use pytest's tmp_path for unique temp directory per test
        db_path = str(tmp_path / "test_trading.db")
        self.repo = SQLiteOrderRepository(db_path=db_path)

        yield

        # Cleanup handled by pytest tmp_path

    @given(position=paper_position_strategy())
    @settings(max_examples=100, deadline=5000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_save_and_retrieve_preserves_all_fields(self, position: PaperPosition):
        """
        Property: For any paper trade, save → retrieve produces equivalent object.

        **Feature: desktop-trading-dashboard, Property 2: Paper Trade Persistence Round-Trip**
        **Validates: Requirements 4.3**
        """
        # Save to database
        self.repo.save_order(position)

        # Retrieve from database
        retrieved = self.repo.get_order(position.id)

        # Assert all fields are preserved
        assert retrieved is not None, "Retrieved position should not be None"
        assert retrieved.id == position.id, "ID should be preserved"
        assert retrieved.symbol == position.symbol, "Symbol should be preserved"
        assert retrieved.side == position.side, "Side should be preserved"
        assert retrieved.status == position.status, "Status should be preserved"

        # Float comparisons with tolerance
        assert abs(retrieved.entry_price - position.entry_price) < 0.01, "Entry price should be preserved"
        assert abs(retrieved.quantity - position.quantity) < 0.0001, "Quantity should be preserved"
        assert retrieved.leverage == position.leverage, "Leverage should be preserved"
        assert abs(retrieved.margin - position.margin) < 0.01, "Margin should be preserved"

        # Optional fields
        if position.liquidation_price:
            assert abs(retrieved.liquidation_price - position.liquidation_price) < 0.01, "Liquidation price should be preserved"

        assert abs(retrieved.stop_loss - position.stop_loss) < 0.01, "Stop loss should be preserved"
        assert abs(retrieved.take_profit - position.take_profit) < 0.01, "Take profit should be preserved"

        # Time comparisons (within 1 second tolerance due to serialization)
        assert abs((retrieved.open_time - position.open_time).total_seconds()) < 1, "Open time should be preserved"

        if position.close_time:
            assert retrieved.close_time is not None, "Close time should be preserved when set"
            assert abs((retrieved.close_time - position.close_time).total_seconds()) < 1, "Close time should be preserved"

        assert abs(retrieved.realized_pnl - position.realized_pnl) < 0.01, "Realized PnL should be preserved"
        assert retrieved.exit_reason == position.exit_reason, "Exit reason should be preserved"

    @given(position=paper_position_strategy())
    @settings(max_examples=50, deadline=5000, phases=[Phase.generate])
    def test_update_preserves_modified_fields(self, position: PaperPosition):
        """
        Property: For any trade, update → retrieve preserves modifications.

        **Feature: desktop-trading-dashboard, Property 2: Paper Trade Persistence Round-Trip**
        **Validates: Requirements 4.3**
        """
        # Save original
        self.repo.save_order(position)

        # Modify position
        position.status = 'CLOSED'
        position.close_time = datetime.now()
        position.realized_pnl = 123.45
        position.exit_reason = 'MANUAL_CLOSE'
        position.stop_loss = position.entry_price * 0.98

        # Update in database
        self.repo.update_order(position)

        # Retrieve and verify
        retrieved = self.repo.get_order(position.id)

        assert retrieved.status == 'CLOSED', "Updated status should be preserved"
        assert retrieved.close_time is not None, "Updated close_time should be preserved"
        assert abs(retrieved.realized_pnl - 123.45) < 0.01, "Updated realized_pnl should be preserved"
        assert retrieved.exit_reason == 'MANUAL_CLOSE', "Updated exit_reason should be preserved"
        assert abs(retrieved.stop_loss - position.stop_loss) < 0.01, "Updated stop_loss should be preserved"

    @given(positions=st.lists(paper_position_strategy(), min_size=1, max_size=10, unique_by=lambda p: p.id))
    @settings(max_examples=30, deadline=10000, phases=[Phase.generate])
    def test_multiple_trades_round_trip(self, positions: list):
        """
        Property: Multiple trades can be saved and retrieved correctly.

        **Feature: desktop-trading-dashboard, Property 2: Paper Trade Persistence Round-Trip**
        **Validates: Requirements 4.3**
        """
        # Save all positions
        for pos in positions:
            self.repo.save_order(pos)

        # Retrieve and verify each
        for original in positions:
            retrieved = self.repo.get_order(original.id)
            assert retrieved is not None, f"Position {original.id} should be retrievable"
            assert retrieved.id == original.id, "ID should match"
            assert retrieved.symbol == original.symbol, "Symbol should match"
            assert retrieved.side == original.side, "Side should match"

    @given(position=paper_position_strategy())
    @settings(max_examples=30, deadline=5000, phases=[Phase.generate])
    def test_active_orders_filter(self, position: PaperPosition):
        """
        Property: Active orders filter returns only OPEN positions.

        **Feature: desktop-trading-dashboard, Property 2: Paper Trade Persistence Round-Trip**
        **Validates: Requirements 4.3**
        """
        # Force status to OPEN for this test
        position.status = 'OPEN'
        self.repo.save_order(position)

        # Get active orders
        active = self.repo.get_active_orders()

        # Should contain our position
        assert any(p.id == position.id for p in active), "OPEN position should be in active orders"

        # All returned should be OPEN
        for p in active:
            assert p.status == 'OPEN', "All active orders should have OPEN status"

    @given(position=paper_position_strategy())
    @settings(max_examples=30, deadline=5000, phases=[Phase.generate])
    def test_pending_orders_filter(self, position: PaperPosition):
        """
        Property: Pending orders filter returns only PENDING positions.

        **Feature: desktop-trading-dashboard, Property 2: Paper Trade Persistence Round-Trip**
        **Validates: Requirements 4.3**
        """
        # Force status to PENDING for this test
        position.status = 'PENDING'
        self.repo.save_order(position)

        # Get pending orders
        pending = self.repo.get_pending_orders()

        # Should contain our position
        assert any(p.id == position.id for p in pending), "PENDING position should be in pending orders"

        # All returned should be PENDING
        for p in pending:
            assert p.status == 'PENDING', "All pending orders should have PENDING status"
