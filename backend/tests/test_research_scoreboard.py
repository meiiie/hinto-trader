import json
from datetime import datetime

from scripts.research_scoreboard import (
    build_scoreboard,
    render_scoreboard_markdown,
    score_case_result,
    summarize_experiment,
)


def _audit(
    decision="REJECT",
    *,
    trades=15,
    net=-6.5,
    profit_factor=0.5,
    expectancy=-0.43,
    bootstrap_positive=0.09,
):
    return {
        "trades": trades,
        "return_pct": net,
        "win_rate": 26.67,
        "profit_factor": profit_factor,
        "expectancy_per_trade": expectancy,
        "avg_r": expectancy,
        "median_r": -1.0,
        "max_drawdown_pct": abs(net),
        "longest_loss_streak": 5,
        "bootstrap": {
            "positive_expectancy_prob": bootstrap_positive,
            "return_p05_pct": -14.6,
        },
        "worst_symbols": [{"key": "FILUSDT", "trades": 3, "pnl": -3.75, "win_rate": 0.0}],
        "reason_breakdown": [{"key": "STOP_LOSS", "trades": 11, "pnl": -12.9, "win_rate": 0.0}],
        "decision": decision,
    }


def test_score_case_result_blocks_rejected_runtime_updates():
    row = score_case_result(
        {
            "case": "top50",
            "returncode": 0,
            "config_hash": "abc123",
            "summary": {"quality_filter_rejections": 23},
            "audit": _audit(),
        }
    )

    assert row["status"] == "FAIL"
    assert row["decision"] == "REJECT"
    assert row["metrics"]["quality_filter_rejections"] == 23
    assert "Do not update paper runtime" in row["recommendation"]
    assert {gate["name"] for gate in row["gates"]} == {
        "sample_size",
        "expectancy",
        "profit_factor",
        "bootstrap_positive_expectancy",
        "max_drawdown_pct",
    }


def test_build_scoreboard_and_markdown_render_matrix_summary():
    scoreboard = build_scoreboard(
        [
            {"case": "top50", "returncode": 0, "summary": {}, "audit": _audit()},
            {
                "case": "broken_case",
                "returncode": 1,
                "error_tail": "boom",
            },
        ]
    )

    assert scoreboard["summary"]["case_count"] == 2
    assert scoreboard["summary"]["decision_counts"]["REJECT"] == 1

    markdown = render_scoreboard_markdown(scoreboard)
    assert "| top50 | FAIL | REJECT |" in markdown
    assert "Worst symbols: FILUSDT" in markdown
    assert "broken_case" in markdown


def test_build_scoreboard_applies_selection_adjusted_bootstrap_haircut():
    scoreboard = build_scoreboard(
        [
            {
                "case": "strong_after_many_tests",
                "returncode": 0,
                "summary": {},
                "audit": _audit(
                    decision="PAPER_RESEARCH_CANDIDATE_NEEDS_OOS",
                    trades=220,
                    net=7.0,
                    profit_factor=1.35,
                    expectancy=0.0318,
                    bootstrap_positive=0.95,
                ),
            },
            {
                "case": "thin_after_many_tests",
                "returncode": 0,
                "summary": {},
                "audit": _audit(
                    decision="PAPER_ONLY_SMALL_SAMPLE",
                    trades=120,
                    net=4.0,
                    profit_factor=1.22,
                    expectancy=0.0333,
                    bootstrap_positive=0.80,
                ),
            },
        ]
    )

    strong_case = next(case for case in scoreboard["cases"] if case["case"] == "strong_after_many_tests")
    assert strong_case["metrics"]["selection_adjusted_bootstrap_positive_prob"] == 0.9
    assert "selection_adjusted_bootstrap" in {gate["name"] for gate in strong_case["gates"]}

    thin_case = next(case for case in scoreboard["cases"] if case["case"] == "thin_after_many_tests")
    assert thin_case["status"] == "WARN"


def test_no_trades_scoreboard_recommends_more_evidence():
    row = score_case_result(
        {
            "case": "quiet_window",
            "returncode": 0,
            "summary": {"total_trades": 0},
            "audit": {"trades": 0, "decision": "NO_TRADES"},
        }
    )

    assert row["status"] == "FAIL"
    assert row["decision"] == "NO_TRADES"
    assert "No evidence yet" in row["recommendation"]


def test_summarize_experiment_reads_metadata_and_trade_csv(tmp_path):
    trade_csv = tmp_path / "portfolio_backtest_test.csv"
    trade_csv.write_text(
        "\n".join(
            [
                "Symbol,Side,Entry Time (UTC+7),PnL ($),Reason,Account Balance",
                "AAAUSDT,LONG,2026-05-01 09:00:00,$2.00,TAKE_PROFIT_1,$102.00",
                "BBBUSDT,LONG,2026-05-01 10:00:00,$-0.50,STOP_LOSS,$101.50",
            ]
        ),
        encoding="utf-8",
    )
    metadata = {
        "config_hash": "hash123",
        "experiment_config": {
            "args": {"balance": 100.0, "risk": 0.01},
            "start_time_utc": datetime(2026, 5, 1).isoformat(),
        },
        "artifacts": {"trades_csv": trade_csv.name},
        "summary": {"total_trades": 2, "net_return_pct": 1.5},
    }
    metadata_path = tmp_path / "experiment_test.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    row = summarize_experiment(metadata_path, audit_runs=10)

    assert row["case"] == "experiment_test"
    assert row["config_hash"] == "hash123"
    assert row["metrics"]["trades"] == 2
    assert row["decision"] == "PAPER_ONLY_SMALL_SAMPLE"
