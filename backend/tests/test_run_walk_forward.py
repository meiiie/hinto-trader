from scripts.run_walk_forward import (
    build_walk_forward_report,
    parse_windows,
    render_walk_forward_markdown,
)


def _case(name, decision, return_pct, trades=40, pf=1.2, boot=0.8, status="FAIL"):
    return {
        "case": name,
        "status": status,
        "decision": decision,
        "metrics": {
            "return_pct": return_pct,
            "trades": trades,
            "profit_factor": pf,
            "expectancy_per_trade": return_pct / max(trades, 1),
            "max_drawdown_pct": 5.0,
            "bootstrap_positive_expectancy_prob": boot,
        },
        "worst_symbols": [],
        "recommendation": "test",
    }


def test_parse_windows_requires_start_end_pairs():
    windows = parse_windows(["2026-01-01:2026-02-01", "2026-02-01:2026-03-01"])

    assert windows[0].label == "2026-01-01->2026-02-01"
    assert windows[1].start == "2026-02-01"


def test_walk_forward_report_rejects_case_with_any_rejected_window():
    report = build_walk_forward_report(
        [
            {
                "window": {"start": "2026-01-01", "end": "2026-02-01"},
                "scoreboard": {
                    "cases": [
                        _case("bounce_daily2", "PAPER_ONLY_SMALL_SAMPLE", 5.0, boot=0.91),
                        _case("baseline_contract", "REJECT", -3.0, boot=0.2),
                    ]
                },
            },
            {
                "window": {"start": "2026-02-01", "end": "2026-03-01"},
                "scoreboard": {
                    "cases": [
                        _case("bounce_daily2", "REJECT", -2.0, boot=0.4),
                        _case("baseline_contract", "REJECT", -5.0, boot=0.1),
                    ]
                },
            },
        ]
    )

    bounce = next(case for case in report["case_summaries"] if case["case"] == "bounce_daily2")
    baseline = next(case for case in report["case_summaries"] if case["case"] == "baseline_contract")

    assert bounce["positive_windows"] == 1
    assert bounce["rejected_windows"] == 1
    assert bounce["stability_decision"] == "REJECT"
    assert baseline["stability_decision"] == "REJECT"


def test_walk_forward_markdown_renders_summary_table():
    report = build_walk_forward_report(
        [
            {
                "window": {"start": "2026-01-01", "end": "2026-02-01"},
                "scoreboard": {"cases": [_case("bounce_daily2", "PAPER_ONLY_SMALL_SAMPLE", 5.0)]},
            }
        ]
    )

    markdown = render_walk_forward_markdown(report)

    assert "# Hinto Walk-Forward Report" in markdown
    assert "| bounce_daily2 |" in markdown
    assert "Window Details" in markdown
