from datetime import datetime

from scripts.research_audit import TradeRow, audit_trades


def test_research_audit_reports_expectancy_and_rejects_flat_sample():
    trades = [
        TradeRow("AAAUSDT", "LONG", datetime(2026, 5, 1, 9), 2.0, "TAKE_PROFIT_1", 102.0),
        TradeRow("BBBUSDT", "LONG", datetime(2026, 5, 1, 10), -1.0, "STOP_LOSS", 101.0),
        TradeRow("AAAUSDT", "LONG", datetime(2026, 5, 1, 10), -1.0, "STOP_LOSS", 100.0),
    ]

    report = audit_trades(trades, initial_balance=100.0, risk_percent=0.01, monte_carlo_runs=10)

    assert report["trades"] == 3
    assert report["net_pnl"] == 0.0
    assert report["profit_factor"] == 1.0
    assert report["payoff"] == 2.0
    assert report["longest_loss_streak"] == 2
    assert report["decision"] == "REJECT"


def test_research_audit_allows_positive_small_sample_as_paper_only():
    trades = [
        TradeRow("AAAUSDT", "LONG", datetime(2026, 5, 1, 9), 2.0, "TAKE_PROFIT_1", 102.0),
        TradeRow("BBBUSDT", "LONG", datetime(2026, 5, 1, 10), -0.5, "STOP_LOSS", 101.5),
    ]

    report = audit_trades(trades, initial_balance=100.0, risk_percent=0.01, monte_carlo_runs=10)

    assert report["decision"] == "PAPER_ONLY_SMALL_SAMPLE"


def test_research_audit_handles_no_trades():
    assert audit_trades([]) == {"trades": 0, "decision": "NO_TRADES"}
