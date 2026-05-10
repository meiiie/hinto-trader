"""
Property-Based Tests for Unrealized PnL Calculation

**Feature: desktop-trading-dashboard, Property 3: Unrealized PnL Calculation**
**Validates: Requirements 4.4**

Tests that unrealized PnL is calculated correctly:
- LONG: PnL = (current_price - entry_price) * quantity
- SHORT: PnL = (entry_price - current_price) * quantity
"""

import pytest
from hypothesis import given, strategies as st, settings, Phase, HealthCheck
from datetime import datetime
import uuid

from src.domain.entities.paper_position import PaperPosition


# Strategies
price_strategy = st.floats(min_value=1000.0, max_value=100000.0, allow_nan=False, allow_infinity=False)
quantity_strategy = st.floats(min_value=0.001, max_value=10.0, allow_nan=False, allow_infinity=False)
side_strategy = st.sampled_from(['LONG', 'SHORT'])


def create_position(side: str, entry_price: float, quantity: float) -> PaperPosition:
    """Create a test position."""
    return PaperPosition(
        id=str(uuid.uuid4()),
        symbol="BTCUSDT",
        side=side,
        status="OPEN",
        entry_price=entry_price,
        quantity=quantity,
        leverage=1,
        margin=entry_price * quantity,
        liquidation_price=entry_price * 0.9 if side == 'LONG' else entry_price * 1.1,
        stop_loss=entry_price * 0.98 if side == 'LONG' else entry_price * 1.02,
        take_profit=entry_price * 1.02 if side == 'LONG' else entry_price * 0.98,
        open_time=datetime.now()
    )


class TestUnrealizedPnLCalculation:
    """
    Property tests for unrealized PnL calculation.

    **Feature: desktop-trading-dashboard, Property 3: Unrealized PnL Calculation**
    **Validates: Requirements 4.4**
    """

    @given(
        entry_price=price_strategy,
        current_price=price_strategy,
        quantity=quantity_strategy
    )
    @settings(max_examples=100, deadline=5000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_long_pnl_formula(self, entry_price: float, current_price: float, quantity: float):
        """
        Property: LONG PnL = (current_price - entry_price) * quantity.

        **Feature: desktop-trading-dashboard, Property 3: Unrealized PnL Calculation**
        **Validates: Requirements 4.4**
        """
        position = create_position('LONG', entry_price, quantity)

        calculated_pnl = position.calculate_unrealized_pnl(current_price)
        expected_pnl = (current_price - entry_price) * quantity

        assert abs(calculated_pnl - expected_pnl) < 0.0001, \
            f"LONG PnL mismatch: expected {expected_pnl}, got {calculated_pnl}"

    @given(
        entry_price=price_strategy,
        current_price=price_strategy,
        quantity=quantity_strategy
    )
    @settings(max_examples=100, deadline=5000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_short_pnl_formula(self, entry_price: float, current_price: float, quantity: float):
        """
        Property: SHORT PnL = (entry_price - current_price) * quantity.

        **Feature: desktop-trading-dashboard, Property 3: Unrealized PnL Calculation**
        **Validates: Requirements 4.4**
        """
        position = create_position('SHORT', entry_price, quantity)

        calculated_pnl = position.calculate_unrealized_pnl(current_price)
        expected_pnl = (entry_price - current_price) * quantity

        assert abs(calculated_pnl - expected_pnl) < 0.0001, \
            f"SHORT PnL mismatch: expected {expected_pnl}, got {calculated_pnl}"

    @given(
        entry_price=price_strategy,
        quantity=quantity_strategy,
        side=side_strategy
    )
    @settings(max_examples=50, deadline=5000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_pnl_zero_at_entry_price(self, entry_price: float, quantity: float, side: str):
        """
        Property: PnL is zero when current_price equals entry_price.

        **Feature: desktop-trading-dashboard, Property 3: Unrealized PnL Calculation**
        **Validates: Requirements 4.4**
        """
        position = create_position(side, entry_price, quantity)

        pnl = position.calculate_unrealized_pnl(entry_price)

        assert abs(pnl) < 0.0001, \
            f"PnL should be 0 at entry price, got {pnl}"

    @given(
        entry_price=price_strategy,
        price_increase=st.floats(min_value=1.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
        quantity=quantity_strategy
    )
    @settings(max_examples=50, deadline=5000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_long_profit_when_price_increases(self, entry_price: float, price_increase: float, quantity: float):
        """
        Property: LONG position has positive PnL when price increases.

        **Feature: desktop-trading-dashboard, Property 3: Unrealized PnL Calculation**
        **Validates: Requirements 4.4**
        """
        position = create_position('LONG', entry_price, quantity)
        current_price = entry_price + price_increase

        pnl = position.calculate_unrealized_pnl(current_price)

        assert pnl > 0, \
            f"LONG should profit when price increases: entry={entry_price}, current={current_price}, pnl={pnl}"

    @given(
        entry_price=price_strategy,
        price_decrease=st.floats(min_value=1.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
        quantity=quantity_strategy
    )
    @settings(max_examples=50, deadline=5000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_short_profit_when_price_decreases(self, entry_price: float, price_decrease: float, quantity: float):
        """
        Property: SHORT position has positive PnL when price decreases.

        **Feature: desktop-trading-dashboard, Property 3: Unrealized PnL Calculation**
        **Validates: Requirements 4.4**
        """
        position = create_position('SHORT', entry_price, quantity)
        current_price = max(1.0, entry_price - price_decrease)  # Ensure positive price

        pnl = position.calculate_unrealized_pnl(current_price)

        # Only assert if price actually decreased
        if current_price < entry_price:
            assert pnl > 0, \
                f"SHORT should profit when price decreases: entry={entry_price}, current={current_price}, pnl={pnl}"

    @given(
        entry_price=price_strategy,
        current_price=price_strategy,
        quantity=quantity_strategy
    )
    @settings(max_examples=50, deadline=5000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_long_short_pnl_opposite(self, entry_price: float, current_price: float, quantity: float):
        """
        Property: LONG and SHORT PnL are opposite for same price movement.

        **Feature: desktop-trading-dashboard, Property 3: Unrealized PnL Calculation**
        **Validates: Requirements 4.4**
        """
        long_position = create_position('LONG', entry_price, quantity)
        short_position = create_position('SHORT', entry_price, quantity)

        long_pnl = long_position.calculate_unrealized_pnl(current_price)
        short_pnl = short_position.calculate_unrealized_pnl(current_price)

        assert abs(long_pnl + short_pnl) < 0.0001, \
            f"LONG and SHORT PnL should be opposite: long={long_pnl}, short={short_pnl}"

    @given(
        entry_price=price_strategy,
        current_price=price_strategy,
        quantity=quantity_strategy
    )
    @settings(max_examples=50, deadline=5000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_pnl_scales_with_quantity(self, entry_price: float, current_price: float, quantity: float):
        """
        Property: PnL scales linearly with quantity.

        **Feature: desktop-trading-dashboard, Property 3: Unrealized PnL Calculation**
        **Validates: Requirements 4.4**
        """
        position1 = create_position('LONG', entry_price, quantity)
        position2 = create_position('LONG', entry_price, quantity * 2)

        pnl1 = position1.calculate_unrealized_pnl(current_price)
        pnl2 = position2.calculate_unrealized_pnl(current_price)

        assert abs(pnl2 - pnl1 * 2) < 0.0001, \
            f"PnL should scale with quantity: pnl1={pnl1}, pnl2={pnl2}"

    @given(
        entry_price=price_strategy,
        quantity=quantity_strategy,
        side=side_strategy
    )
    @settings(max_examples=50, deadline=5000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_roe_calculation(self, entry_price: float, quantity: float, side: str):
        """
        Property: ROE = (PnL / margin) * 100.

        **Feature: desktop-trading-dashboard, Property 3: Unrealized PnL Calculation**
        **Validates: Requirements 4.4**
        """
        position = create_position(side, entry_price, quantity)

        # Use a different current price
        current_price = entry_price * 1.05  # 5% change

        pnl = position.calculate_unrealized_pnl(current_price)
        roe = position.calculate_roe(current_price)

        expected_roe = (pnl / position.margin) * 100 if position.margin > 0 else 0.0

        assert abs(roe - expected_roe) < 0.01, \
            f"ROE mismatch: expected {expected_roe}, got {roe}"
