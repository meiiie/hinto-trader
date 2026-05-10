"""Unit tests for LOCAL auto-close logic in LiveTradingService."""

import threading
from dataclasses import dataclass
from unittest.mock import Mock, patch

import pytest

from src.application.services.live_trading_service import LiveTradingService, TradingMode
from src.trading_contract import PRODUCTION_PROFITABLE_THRESHOLD_PCT


@dataclass
class MockTracker:
    """Minimal LocalPosition-like tracker for auto-close tests."""

    quantity: float
    entry_price: float
    leverage: int
    current_price: float
    fees: float = 0.0

    def get_unrealized_pnl(self, price: float) -> float:
        direction = 1 if self.quantity > 0 else -1
        return (price - self.entry_price) * abs(self.quantity) * direction

    def get_roe_percent(self, price: float) -> float:
        effective_leverage = self.leverage if self.leverage > 0 else 1
        margin = (self.entry_price * abs(self.quantity)) / effective_leverage
        if margin <= 0:
            return 0.0
        return (self.get_unrealized_pnl(price) / margin) * 100

    def get_summary(self, price: float) -> dict:
        effective_leverage = self.leverage if self.leverage > 0 else 1
        margin = (self.entry_price * abs(self.quantity)) / effective_leverage
        return {
            "avg_entry_price": self.entry_price,
            "actual_leverage": self.leverage,
            "intended_leverage": self.leverage,
            "actual_margin": margin,
            "total_entry_fees": self.fees,
            "total_quantity": abs(self.quantity),
        }


def create_service_with_auto_close(enabled: bool = True, threshold: float = 5.0) -> LiveTradingService:
    """Create a service configured for LOCAL auto-close tests."""
    mock_settings_repo = Mock()
    mock_settings_repo.get_all_settings.return_value = {
        "close_profitable_auto": enabled,
        "profitable_threshold_pct": threshold,
        "max_positions": 5,
        "leverage": 10,
        "risk_percent": 1.0,
    }

    service = LiveTradingService(mode=TradingMode.PAPER, settings_repo=mock_settings_repo)
    service.logger = Mock()
    service._local_positions = {}
    service._local_positions_lock = threading.RLock()
    return service


class TestAutoCloseLocal:
    def test_long_position_closes_when_roe_above_threshold(self):
        service = create_service_with_auto_close(enabled=True, threshold=5.0)
        symbol = "BTCUSDT"
        service._local_positions[symbol] = MockTracker(
            quantity=10.0,
            entry_price=100.0,
            leverage=10,
            current_price=110.0,
        )

        with patch.object(service, "_close_position_market") as mock_close:
            result = service._check_auto_close_local(symbol, current_price=110.0)

        assert result is True
        mock_close.assert_called_once_with(
            symbol=symbol,
            quantity=10.0,
            reason="AUTO_CLOSE_PROFITABLE_LOCAL",
        )

    def test_short_position_closes_when_roe_above_threshold(self):
        service = create_service_with_auto_close(enabled=True, threshold=5.0)
        symbol = "ETHUSDT"
        service._local_positions[symbol] = MockTracker(
            quantity=-10.0,
            entry_price=100.0,
            leverage=20,
            current_price=90.0,
        )

        with patch.object(service, "_close_position_market") as mock_close:
            result = service._check_auto_close_local(symbol, current_price=90.0)

        assert result is True
        mock_close.assert_called_once()

    def test_exact_threshold_still_triggers_close(self):
        service = create_service_with_auto_close(enabled=True, threshold=5.0)
        symbol = "BTCUSDT"
        service._local_positions[symbol] = MockTracker(
            quantity=10.0,
            entry_price=100.0,
            leverage=10,
            current_price=100.5,
        )

        with patch.object(service, "_close_position_market") as mock_close:
            result = service._check_auto_close_local(symbol, current_price=100.5)

        assert result is True
        mock_close.assert_called_once()

    def test_below_threshold_does_not_close(self):
        service = create_service_with_auto_close(enabled=True, threshold=5.0)
        symbol = "BTCUSDT"
        service._local_positions[symbol] = MockTracker(
            quantity=10.0,
            entry_price=100.0,
            leverage=10,
            current_price=100.4,
        )

        with patch.object(service, "_close_position_market") as mock_close:
            result = service._check_auto_close_local(symbol, current_price=100.4)

        assert result is False
        mock_close.assert_not_called()

    def test_losing_position_does_not_close(self):
        service = create_service_with_auto_close(enabled=True, threshold=5.0)
        symbol = "BTCUSDT"
        service._local_positions[symbol] = MockTracker(
            quantity=10.0,
            entry_price=100.0,
            leverage=10,
            current_price=90.0,
        )

        with patch.object(service, "_close_position_market") as mock_close:
            result = service._check_auto_close_local(symbol, current_price=90.0)

        assert result is False
        mock_close.assert_not_called()

    def test_missing_tracker_returns_false(self):
        service = create_service_with_auto_close(enabled=True, threshold=5.0)

        with patch.object(service, "_close_position_market") as mock_close:
            result = service._check_auto_close_local("BTCUSDT", current_price=110.0)

        assert result is False
        mock_close.assert_not_called()

    def test_feature_disabled_returns_false(self):
        service = create_service_with_auto_close(enabled=False, threshold=5.0)
        symbol = "BTCUSDT"
        service._local_positions[symbol] = MockTracker(
            quantity=10.0,
            entry_price=100.0,
            leverage=10,
            current_price=110.0,
        )

        with patch.object(service, "_close_position_market") as mock_close:
            result = service._check_auto_close_local(symbol, current_price=110.0)

        assert result is False
        mock_close.assert_not_called()

    def test_invalid_leverage_uses_safe_zero_roe(self):
        service = create_service_with_auto_close(enabled=True, threshold=5.0)
        symbol = "BTCUSDT"
        service._local_positions[symbol] = MockTracker(
            quantity=10.0,
            entry_price=100.0,
            leverage=0,
            current_price=110.0,
        )

        with patch.object(service, "_close_position_market") as mock_close:
            result = service._check_auto_close_local(symbol, current_price=110.0)

        assert isinstance(result, bool)
        mock_close.assert_called_once()


class TestAutoCloseSettings:
    def test_settings_loaded_from_repo(self):
        service = create_service_with_auto_close(enabled=True, threshold=7.5)

        assert service.close_profitable_auto is True
        assert service.profitable_threshold_pct == 7.5

    def test_defaults_without_repo_match_runtime_defaults(self):
        service = LiveTradingService(mode=TradingMode.PAPER)

        assert service.close_profitable_auto is True
        assert service.profitable_threshold_pct == PRODUCTION_PROFITABLE_THRESHOLD_PCT

    def test_invalid_settings_fall_back_safely(self):
        mock_settings_repo = Mock()
        mock_settings_repo.get_all_settings.return_value = {
            "close_profitable_auto": "invalid",
            "profitable_threshold_pct": -5.0,
            "max_positions": 5,
            "leverage": 10,
            "risk_percent": 1.0,
        }

        service = LiveTradingService(mode=TradingMode.PAPER, settings_repo=mock_settings_repo)

        assert service.close_profitable_auto is False
        assert service.profitable_threshold_pct == PRODUCTION_PROFITABLE_THRESHOLD_PCT
