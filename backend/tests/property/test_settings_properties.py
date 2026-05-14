"""
Property-Based Tests for Settings Persistence

**Feature: desktop-trading-dashboard, Property 6: Settings Persistence and Application**
**Validates: Requirements 6.3**

Tests that for any settings update, the new values are:
1. Persisted to SQLite database
2. Applied to all subsequent signal generations
"""

import os
import tempfile
import pytest
from hypothesis import given, strategies as st, settings, Phase, HealthCheck

from src.infrastructure.persistence.sqlite_order_repository import SQLiteOrderRepository
from src.application.services.paper_trading_service import PaperTradingService


# Strategies for generating valid settings values
risk_percent_strategy = st.floats(min_value=0.1, max_value=10.0, allow_nan=False, allow_infinity=False)
rr_ratio_strategy = st.just(1.0)
max_positions_strategy = st.integers(min_value=1, max_value=10)
leverage_strategy = st.integers(min_value=1, max_value=2)
auto_execute_strategy = st.booleans()


class TestSettingsPersistence:
    """
    Property tests for settings persistence.

    **Feature: desktop-trading-dashboard, Property 6: Settings Persistence and Application**
    **Validates: Requirements 6.3**
    """

    @pytest.fixture(autouse=True)
    def setup_temp_db(self, tmp_path):
        """Create a temporary database for each test"""
        db_path = str(tmp_path / "test_settings.db")
        self.repo = SQLiteOrderRepository(db_path=db_path)
        self.paper_service = PaperTradingService(repository=self.repo)

        yield

    @given(risk_percent=risk_percent_strategy)
    @settings(max_examples=50, deadline=5000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_risk_percent_persistence_round_trip(self, risk_percent: float):
        """
        Property: For any risk_percent value, update → retrieve produces same value.

        **Feature: desktop-trading-dashboard, Property 6: Settings Persistence and Application**
        **Validates: Requirements 6.3**
        """
        # Update setting
        self.paper_service.update_settings({'risk_percent': risk_percent})

        # Retrieve and verify
        retrieved = self.paper_service.get_settings()

        assert abs(retrieved['risk_percent'] - risk_percent) < 0.01, \
            f"risk_percent should be preserved: expected {risk_percent}, got {retrieved['risk_percent']}"

    @pytest.mark.skip(reason="rr_ratio setting was removed from the runtime contract")
    @given(rr_ratio=rr_ratio_strategy)
    @settings(max_examples=50, deadline=5000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_rr_ratio_persistence_round_trip(self, rr_ratio: float):
        """
        Property: For any rr_ratio value, update → retrieve produces same value.

        **Feature: desktop-trading-dashboard, Property 6: Settings Persistence and Application**
        **Validates: Requirements 6.3**
        """
        # Update setting
        self.paper_service.update_settings({'rr_ratio': rr_ratio})

        # Retrieve and verify
        retrieved = self.paper_service.get_settings()

        assert abs(retrieved['rr_ratio'] - rr_ratio) < 0.01, \
            f"rr_ratio should be preserved: expected {rr_ratio}, got {retrieved['rr_ratio']}"

    @given(max_positions=max_positions_strategy)
    @settings(max_examples=50, deadline=5000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_max_positions_persistence_round_trip(self, max_positions: int):
        """
        Property: For any max_positions value, update → retrieve produces same value.

        **Feature: desktop-trading-dashboard, Property 6: Settings Persistence and Application**
        **Validates: Requirements 6.3**
        """
        # Update setting
        self.paper_service.update_settings({'max_positions': max_positions})

        # Retrieve and verify
        retrieved = self.paper_service.get_settings()

        assert retrieved['max_positions'] == max_positions, \
            f"max_positions should be preserved: expected {max_positions}, got {retrieved['max_positions']}"

    @given(leverage=leverage_strategy)
    @settings(max_examples=50, deadline=5000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_leverage_persistence_round_trip(self, leverage: int):
        """
        Property: For any leverage value, update → retrieve produces same value.

        **Feature: desktop-trading-dashboard, Property 6: Settings Persistence and Application**
        **Validates: Requirements 6.3**
        """
        # Update setting
        self.paper_service.update_settings({'leverage': leverage})

        # Retrieve and verify
        retrieved = self.paper_service.get_settings()

        assert retrieved['leverage'] == leverage, \
            f"leverage should be preserved: expected {leverage}, got {retrieved['leverage']}"

    @given(auto_execute=auto_execute_strategy)
    @settings(max_examples=20, deadline=5000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_auto_execute_persistence_round_trip(self, auto_execute: bool):
        """
        Property: For any auto_execute value, update → retrieve produces same value.

        **Feature: desktop-trading-dashboard, Property 6: Settings Persistence and Application**
        **Validates: Requirements 6.3**
        """
        # Update setting
        self.paper_service.update_settings({'auto_execute': auto_execute})

        # Retrieve and verify
        retrieved = self.paper_service.get_settings()

        assert retrieved['auto_execute'] == auto_execute, \
            f"auto_execute should be preserved: expected {auto_execute}, got {retrieved['auto_execute']}"

    @given(
        risk_percent=risk_percent_strategy,
        max_positions=max_positions_strategy,
        leverage=leverage_strategy
    )
    @settings(max_examples=30, deadline=5000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_multiple_settings_persistence(
        self,
        risk_percent: float,
        max_positions: int,
        leverage: int
    ):
        """
        Property: Multiple settings updated together are all preserved.

        **Feature: desktop-trading-dashboard, Property 6: Settings Persistence and Application**
        **Validates: Requirements 6.3**
        """
        # Update all settings at once
        self.paper_service.update_settings({
            'risk_percent': risk_percent,
            'max_positions': max_positions,
            'leverage': leverage
        })

        # Retrieve and verify all
        retrieved = self.paper_service.get_settings()

        assert abs(retrieved['risk_percent'] - risk_percent) < 0.01
        assert retrieved['max_positions'] == max_positions
        assert retrieved['leverage'] == leverage

    @given(risk_percent=risk_percent_strategy)
    @settings(max_examples=30, deadline=5000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_settings_applied_to_service(self, risk_percent: float):
        """
        Property: Updated settings are applied to the service immediately.

        **Feature: desktop-trading-dashboard, Property 6: Settings Persistence and Application**
        **Validates: Requirements 6.3**
        """
        # Update setting
        self.paper_service.update_settings({'risk_percent': risk_percent})

        # Verify service attribute is updated
        expected_risk_per_trade = risk_percent / 100
        assert abs(self.paper_service.RISK_PER_TRADE - expected_risk_per_trade) < 0.0001, \
            f"RISK_PER_TRADE should be updated: expected {expected_risk_per_trade}, got {self.paper_service.RISK_PER_TRADE}"

    @given(max_positions=max_positions_strategy)
    @settings(max_examples=30, deadline=5000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_max_positions_applied_to_service(self, max_positions: int):
        """
        Property: Updated max_positions is applied to the service immediately.

        **Feature: desktop-trading-dashboard, Property 6: Settings Persistence and Application**
        **Validates: Requirements 6.3**
        """
        # Update setting
        self.paper_service.update_settings({'max_positions': max_positions})

        # Verify service attribute is updated
        assert self.paper_service.MAX_POSITIONS == max_positions, \
            f"MAX_POSITIONS should be updated: expected {max_positions}, got {self.paper_service.MAX_POSITIONS}"

    @given(leverage=leverage_strategy)
    @settings(max_examples=30, deadline=5000, phases=[Phase.generate], suppress_health_check=[HealthCheck.too_slow])
    def test_leverage_applied_to_service(self, leverage: int):
        """
        Property: Updated leverage is applied to the service immediately.

        **Feature: desktop-trading-dashboard, Property 6: Settings Persistence and Application**
        **Validates: Requirements 6.3**
        """
        # Update setting
        self.paper_service.update_settings({'leverage': leverage})

        # Verify service attribute is updated
        assert self.paper_service.LEVERAGE == leverage, \
            f"LEVERAGE should be updated: expected {leverage}, got {self.paper_service.LEVERAGE}"
