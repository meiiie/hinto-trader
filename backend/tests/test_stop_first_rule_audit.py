from pathlib import Path

from scripts.stop_first_rule_audit import audit_blocking_rules, load_aggregated_trades


def test_stop_first_rule_audit_aggregates_partial_exit_rows(tmp_path: Path):
    trade_csv = tmp_path / "portfolio_backtest_test.csv"
    trade_csv.write_text(
        "\n".join(
            [
                "Trade ID,Symbol,Side,Entry Time (UTC+7),PnL ($),Reason",
                "a,AAAUSDT,LONG,2026-05-01 09:00:00,$1.00,TAKE_PROFIT_1",
                "a,AAAUSDT,LONG,2026-05-01 09:00:00,$0.50,TRAILING_STOP",
                "b,BBBUSDT,LONG,2026-05-01 10:00:00,$-1.00,STOP_LOSS",
            ]
        ),
        encoding="utf-8",
    )

    trades = load_aggregated_trades(trade_csv)

    assert len(trades) == 2
    assert trades[0].trade_id == "a"
    assert trades[0].pnl == 1.5
    assert trades[0].reasons == ("TAKE_PROFIT_1", "TRAILING_STOP")


def test_stop_first_rule_audit_ranks_stable_harmful_groups(tmp_path: Path):
    trades_csv = tmp_path / "fixtures_stop_first_rules.csv"
    trades_csv.write_text(
        "\n".join(
            [
                "Trade ID,Symbol,Side,Entry Time (UTC+7),PnL ($),Reason",
                "a,BADUSDT,LONG,2026-05-01 09:00:00,$-1.00,STOP_LOSS",
                "b,GOODUSDT,LONG,2026-05-01 10:00:00,$1.20,TAKE_PROFIT_1",
                "c,BADUSDT,LONG,2026-05-02 09:00:00,$-0.80,STOP_LOSS",
                "d,GOODUSDT,LONG,2026-05-02 10:00:00,$1.00,TAKE_PROFIT_1",
            ]
        ),
        encoding="utf-8",
    )
    report = audit_blocking_rules(load_aggregated_trades(trades_csv), min_trades=2)

    top = report["top_harmful_groups"][0]
    assert top["feature"] == "symbol"
    assert top["value"] == "BADUSDT"
    assert top["net_improvement"] == 1.8
    assert top["stable_improvement"] is True
