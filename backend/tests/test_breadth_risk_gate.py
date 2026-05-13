from datetime import datetime, timedelta
from types import SimpleNamespace

from src.application.backtest.backtest_engine import BacktestEngine
from src.domain.entities.candle import Candle


def _history(symbol_offset: int, closes: list[float]) -> list[Candle]:
    return [
        Candle(
            timestamp=datetime(2026, 1, 1) + timedelta(minutes=15 * (idx + symbol_offset)),
            open=close,
            high=close * 1.001,
            low=close * 0.999,
            close=close,
            volume=1_000.0,
        )
        for idx, close in enumerate(closes)
    ]


def _engine(*, min_symbols: int = 4) -> BacktestEngine:
    return BacktestEngine(
        signal_generator=SimpleNamespace(mtf_ema_period=20),
        loader=SimpleNamespace(),
        use_breadth_risk_gate=True,
        breadth_ema_bars=4,
        breadth_momentum_bars=2,
        breadth_long_threshold=0.50,
        breadth_short_threshold=0.50,
        breadth_min_symbols=min_symbols,
    )


def test_breadth_state_uses_current_universe_without_future_data():
    engine = _engine()
    histories = {
        "AUSDT": _history(0, [10, 11, 12, 13, 14]),
        "BUSDT": _history(10, [20, 21, 22, 23, 24]),
        "CUSDT": _history(20, [30, 31, 32, 33, 34]),
        "DUSDT": _history(30, [40, 39, 38, 37, 36]),
    }

    state = engine._calculate_breadth_state(histories, list(histories))

    assert state["evaluated"] == 4.0
    assert state["bullish_ratio"] == 0.75
    assert state["bearish_ratio"] == 0.25
    assert engine._is_blocked_by_breadth("LONG", state) is False
    assert engine._is_blocked_by_breadth("SHORT", state) is True


def test_breadth_gate_fails_closed_when_coverage_is_too_low():
    engine = _engine(min_symbols=2)
    histories = {
        "AUSDT": _history(0, [10, 11, 12, 13, 14]),
        "BUSDT": _history(10, [20, 21, 22]),
    }

    state = engine._calculate_breadth_state(histories, list(histories))

    assert state["evaluated"] == 1.0
    assert engine._is_blocked_by_breadth("LONG", state) is True
    assert engine._is_blocked_by_breadth("SHORT", state) is True
