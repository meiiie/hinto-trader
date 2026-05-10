from src.config import get_execution_mode, is_paper_real_enabled, is_real_ordering_enabled
from src.application.services.live_trading_service import LiveTradingService, TradingMode
from src.domain.entities.trading_signal import TradingSignal, SignalType


def test_paper_real_is_default_safe_execution_profile(monkeypatch):
    monkeypatch.setenv("ENV", "paper")
    monkeypatch.delenv("HINTO_PAPER_REAL", raising=False)

    assert get_execution_mode() == "paper_real"
    assert is_paper_real_enabled() is True
    assert is_real_ordering_enabled() is False


def test_paper_real_can_be_disabled_for_plain_paper(monkeypatch):
    monkeypatch.setenv("ENV", "paper")
    monkeypatch.setenv("HINTO_PAPER_REAL", "false")

    assert get_execution_mode() == "paper"
    assert is_paper_real_enabled() is False
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
