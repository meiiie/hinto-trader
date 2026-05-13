from datetime import datetime

import pytest

from scripts.run_symbol_quality_walk_forward import (
    TrainTestWindow,
    _metrics,
    parse_train_test_windows,
    score_symbols,
    select_symbols,
)
from scripts.stop_first_rule_audit import AggregatedTrade


def _trade(symbol: str, pnl: float, reason: str) -> AggregatedTrade:
    return AggregatedTrade(
        trade_id=f"{symbol}-{pnl}-{reason}",
        symbol=symbol,
        side="LONG",
        entry_time=datetime(2026, 5, 1, 9),
        pnl=pnl,
        reasons=(reason,),
    )


def test_parse_train_test_windows_accepts_four_part_windows():
    windows = parse_train_test_windows(["2025-01-01:2025-02-01:2025-02-01:2025-03-01"])

    assert windows == [
        TrainTestWindow(
            train_start="2025-01-01",
            train_end="2025-02-01",
            test_start="2025-02-01",
            test_end="2025-03-01",
        )
    ]


def test_parse_train_test_windows_rejects_invalid_shape():
    with pytest.raises(ValueError):
        parse_train_test_windows(["2025-01-01:2025-02-01"])


def test_score_symbols_penalizes_stop_heavy_training_symbols():
    rows = score_symbols(
        [
            _trade("GOODUSDT", 1.0, "TAKE_PROFIT_1"),
            _trade("GOODUSDT", 0.8, "TAKE_PROFIT_1"),
            _trade("GOODUSDT", -0.2, "TRAILING_STOP"),
            _trade("BADUSDT", 2.0, "TAKE_PROFIT_1"),
            _trade("BADUSDT", -1.0, "STOP_LOSS"),
            _trade("BADUSDT", -1.0, "STOP_LOSS"),
        ],
        ["GOODUSDT", "BADUSDT"],
        min_trades=3,
    )

    assert rows[0]["symbol"] == "GOODUSDT"
    assert rows[0]["eligible_for_selection"] is True
    assert rows[0]["stop_rate"] < rows[1]["stop_rate"]


def test_select_symbols_fills_from_ranked_rows_when_evidence_is_sparse():
    selected = select_symbols(
        [
            {"symbol": "AAAUSDT", "score": 1.0, "eligible_for_selection": True},
            {"symbol": "BBBUSDT", "score": -0.5, "eligible_for_selection": False},
            {"symbol": "CCCUSDT", "score": -2.0, "eligible_for_selection": True},
        ],
        count=2,
    )

    assert selected == ["AAAUSDT", "BBBUSDT"]


def test_metrics_falls_back_to_summary_for_no_trade_runs():
    metrics = _metrics(
        {
            "audit": {"trades": 0, "decision": "NO_TRADES"},
            "summary": {"net_return_pct": 0.0, "max_drawdown_pct": 0.0},
        }
    )

    assert metrics["return_pct"] == 0.0
    assert metrics["max_drawdown_pct"] == 0.0
