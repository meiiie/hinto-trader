from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from src.config.runtime import (
    get_execution_mode,
    is_exchange_ordering_enabled,
    is_paper_real_enabled,
    is_real_ordering_enabled,
)
from src.application.services.local_signal_tracker import PendingSignal, SignalDirection
from src.application.services.live_trading_service import LiveTradingService, TradingMode
from src.application.services.paper_trading_service import PaperTradingService
from src.domain.entities.trading_signal import TradingSignal, SignalType
from src.infrastructure.persistence.sqlite_order_repository import SQLiteOrderRepository


def test_paper_real_is_default_safe_execution_profile(monkeypatch):
    monkeypatch.setenv("ENV", "paper")
    monkeypatch.delenv("HINTO_PAPER_REAL", raising=False)

    assert get_execution_mode() == "paper_real"
    assert is_paper_real_enabled() is True
    assert is_exchange_ordering_enabled() is False
    assert is_real_ordering_enabled() is False


def test_paper_real_can_be_disabled_for_plain_paper(monkeypatch):
    monkeypatch.setenv("ENV", "paper")
    monkeypatch.setenv("HINTO_PAPER_REAL", "false")

    assert get_execution_mode() == "paper"
    assert is_paper_real_enabled() is False
    assert is_exchange_ordering_enabled() is False
    assert is_real_ordering_enabled() is False


def test_live_service_rejects_paper_mode_execution():
    service = LiveTradingService(mode=TradingMode.PAPER)
    signal = TradingSignal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        confidence=0.8,
        price=100.0,
        entry_price=100.0,
        stop_loss=98.8,
        tp_levels={"tp1": 102.0},
    )

    assert service.execute_signal(signal) is False
    assert service.client is None


def test_triggered_signal_guard_blocks_paper_even_if_bypassed(monkeypatch):
    monkeypatch.setenv("ENV", "paper")

    service = LiveTradingService(mode=TradingMode.PAPER, enable_trading=True)
    service.client = Mock()
    signal = PendingSignal(
        symbol="BTCUSDT",
        direction=SignalDirection.LONG,
        target_price=100.0,
        stop_loss=98.8,
        take_profit=102.0,
        quantity=0.01,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )

    assert service.exchange_ordering_enabled is False
    assert service._execute_triggered_signal(signal, current_price=100.0) is False
    service.client.create_order.assert_not_called()


def test_paper_order_size_is_capped_by_risk_percent(tmp_path):
    repo = SQLiteOrderRepository(db_path=str(tmp_path / "paper-risk.db"))
    repo.update_account_balance(100.0)

    service = PaperTradingService(repository=repo)
    service.update_settings({
        "risk_percent": 1.0,
        "max_positions": 4,
        "leverage": 20,
    })

    signal = TradingSignal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        confidence=0.9,
        price=100.0,
        entry_price=100.0,
        stop_loss=99.0,
        tp_levels={"tp1": 102.0},
    )

    service.on_signal_received(signal, "BTCUSDT")

    pending_orders = repo.get_pending_orders()
    assert len(pending_orders) == 1

    order = pending_orders[0]
    intended_loss_at_stop = abs(order.entry_price - order.stop_loss) * order.quantity

    assert order.notional_value == 100.0
    assert order.margin == 5.0
    assert intended_loss_at_stop <= 1.0


def test_paper_realized_pnl_includes_entry_and_exit_fees(tmp_path):
    repo = SQLiteOrderRepository(db_path=str(tmp_path / "paper-fees.db"))
    repo.update_account_balance(100.0)

    service = PaperTradingService(repository=repo)
    service.update_settings({
        "risk_percent": 1.0,
        "max_positions": 4,
        "leverage": 20,
    })

    signal = TradingSignal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        confidence=0.9,
        price=100.0,
        entry_price=100.0,
        stop_loss=99.0,
        tp_levels={"tp1": 102.0},
    )

    service.on_signal_received(signal, "BTCUSDT")
    service.process_market_data(current_price=100.0, high=100.0, low=100.0, symbol="BTCUSDT")

    open_position = repo.get_active_orders()[0]
    assert open_position.realized_pnl == pytest.approx(-0.02)
    assert repo.get_account_balance() == pytest.approx(99.98)

    service.process_market_data(current_price=99.0, high=100.0, low=99.0, symbol="BTCUSDT")

    closed = repo.get_closed_orders(limit=10)[0]
    expected_exit_fee = 99.0 * 1.0 * service.TAKER_FEE_PCT
    expected_realized = -0.02 - 1.0 - expected_exit_fee

    assert closed.realized_pnl == pytest.approx(expected_realized)
    assert repo.get_account_balance() == pytest.approx(100.0 + expected_realized)


def test_paper_partial_tp_tracks_fee_margin_and_realized_pnl(tmp_path):
    repo = SQLiteOrderRepository(db_path=str(tmp_path / "paper-partial-tp.db"))
    repo.update_account_balance(100.0)

    service = PaperTradingService(repository=repo)
    service.update_settings({
        "risk_percent": 1.0,
        "max_positions": 4,
        "leverage": 20,
    })

    signal = TradingSignal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        confidence=0.9,
        price=100.0,
        entry_price=100.0,
        stop_loss=99.0,
        tp_levels={"tp1": 102.0},
    )

    service.on_signal_received(signal, "BTCUSDT")
    service.process_market_data(current_price=100.0, high=100.0, low=100.0, symbol="BTCUSDT")
    service.process_market_data(current_price=102.0, high=102.0, low=100.1, symbol="BTCUSDT")

    open_position = repo.get_active_orders()[0]
    partial_exit_fee = 102.0 * 0.6 * service.TAKER_FEE_PCT
    expected_partial_pnl = ((102.0 - 100.0) * 0.6) - partial_exit_fee
    expected_realized = -0.02 + expected_partial_pnl

    assert open_position.quantity == pytest.approx(0.4)
    assert open_position.margin == pytest.approx(2.0)
    assert open_position.realized_pnl == pytest.approx(expected_realized)
    assert repo.get_account_balance() == pytest.approx(100.0 + expected_realized)
