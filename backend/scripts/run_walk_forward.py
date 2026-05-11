"""Run Hinto research matrices across multiple time windows.

This script codifies the walk-forward checks we were doing manually. It reuses
the event-driven matrix runner, then writes one aggregate JSON and Markdown
report so a strategy/universe must survive multiple windows before it can be
considered for paper runtime changes.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from run_research_matrix import PRODUCTION_LEVERAGE, ROOT, run_matrix
except ModuleNotFoundError:
    from .run_research_matrix import PRODUCTION_LEVERAGE, ROOT, run_matrix


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


@dataclass(frozen=True)
class WalkForwardWindow:
    start: str
    end: str

    @property
    def label(self) -> str:
        return f"{self.start}->{self.end}"


def parse_windows(values: list[str]) -> list[WalkForwardWindow]:
    windows: list[WalkForwardWindow] = []
    for value in values:
        if ":" not in value:
            raise ValueError(f"Invalid window '{value}'. Expected START:END.")
        start, end = [part.strip() for part in value.split(":", 1)]
        if not start or not end:
            raise ValueError(f"Invalid window '{value}'. Expected START:END.")
        windows.append(WalkForwardWindow(start=start, end=end))
    return windows


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _case_row(window: WalkForwardWindow, case: dict[str, Any]) -> dict[str, Any]:
    metrics = case.get("metrics", {})
    return {
        "window": window.label,
        "case": case.get("case"),
        "status": case.get("status"),
        "decision": case.get("decision"),
        "return_pct": _as_float(metrics.get("return_pct")),
        "trades": int(metrics.get("trades", 0) or 0),
        "profit_factor": _as_float(metrics.get("profit_factor")),
        "expectancy_per_trade": _as_float(metrics.get("expectancy_per_trade")),
        "max_drawdown_pct": _as_float(metrics.get("max_drawdown_pct")),
        "bootstrap_positive_expectancy_prob": _as_float(
            metrics.get("bootstrap_positive_expectancy_prob")
        ),
        "worst_symbols": case.get("worst_symbols", [])[:5],
        "recommendation": case.get("recommendation"),
    }


def _stability_decision(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "NO_DATA"
    if any(row["status"] == "ERROR" for row in rows):
        return "ERROR"
    if any(row["decision"] == "REJECT" for row in rows):
        return "REJECT"
    if min(row["return_pct"] for row in rows) <= 0:
        return "REJECT"
    if min(row["bootstrap_positive_expectancy_prob"] for row in rows) < 0.75:
        return "FRAGILE"
    if sum(row["trades"] for row in rows) < 200:
        return "PAPER_ONLY_SMALL_SAMPLE"
    return "PAPER_RESEARCH_CANDIDATE_NEEDS_OOS"


def build_walk_forward_report(window_reports: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for window_report in window_reports:
        window = WalkForwardWindow(
            start=window_report["window"]["start"],
            end=window_report["window"]["end"],
        )
        for case in window_report.get("scoreboard", {}).get("cases", []):
            rows.append(_case_row(window, case))

    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_case[str(row["case"])].append(row)

    case_summaries = []
    for case_name, case_rows in sorted(by_case.items()):
        returns = [row["return_pct"] for row in case_rows]
        drawdowns = [row["max_drawdown_pct"] for row in case_rows]
        boots = [row["bootstrap_positive_expectancy_prob"] for row in case_rows]
        statuses = Counter(row["status"] for row in case_rows)
        decisions = Counter(row["decision"] for row in case_rows)
        case_summaries.append(
            {
                "case": case_name,
                "windows": len(case_rows),
                "positive_windows": sum(1 for value in returns if value > 0),
                "rejected_windows": decisions.get("REJECT", 0),
                "error_windows": statuses.get("ERROR", 0),
                "average_return_pct": round(sum(returns) / len(returns), 2) if returns else 0.0,
                "min_return_pct": round(min(returns), 2) if returns else 0.0,
                "max_drawdown_pct": round(max(drawdowns), 2) if drawdowns else 0.0,
                "min_bootstrap_positive_expectancy_prob": round(min(boots), 4) if boots else 0.0,
                "total_trades": sum(row["trades"] for row in case_rows),
                "stability_decision": _stability_decision(case_rows),
            }
        )

    ranked = sorted(
        case_summaries,
        key=lambda row: (
            row["stability_decision"] not in {"ERROR", "REJECT"},
            row["positive_windows"],
            row["average_return_pct"],
        ),
        reverse=True,
    )

    return {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "window_count": len(window_reports),
            "case_count": len(case_summaries),
            "best_case_by_stability": ranked[0]["case"] if ranked else None,
        },
        "case_summaries": ranked,
        "rows": rows,
        "window_reports": window_reports,
    }


def render_walk_forward_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Hinto Walk-Forward Report",
        "",
        f"Created: `{report.get('created_at_utc')}`",
        "",
        "## Case Summary",
        "",
        "| Case | Decision | Positive Windows | Avg Return | Min Return | Max DD | Min Boot+ | Trades |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for case in report.get("case_summaries", []):
        lines.append(
            "| {case} | {decision} | {positive}/{windows} | {avg:.2f}% | {min_ret:.2f}% | "
            "{dd:.2f}% | {boot:.2f}% | {trades} |".format(
                case=case["case"],
                decision=case["stability_decision"],
                positive=case["positive_windows"],
                windows=case["windows"],
                avg=case["average_return_pct"],
                min_ret=case["min_return_pct"],
                dd=case["max_drawdown_pct"],
                boot=case["min_bootstrap_positive_expectancy_prob"] * 100,
                trades=case["total_trades"],
            )
        )

    lines.extend(
        [
            "",
            "## Window Details",
            "",
            "| Window | Case | Status | Decision | Return | Trades | PF | Exp/Trade | DD | Boot+ |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report.get("rows", []):
        lines.append(
            "| {window} | {case} | {status} | {decision} | {ret:.2f}% | {trades} | "
            "{pf:.2f} | {exp:.4f} | {dd:.2f}% | {boot:.2f}% |".format(
                window=row["window"],
                case=row["case"],
                status=row["status"],
                decision=row["decision"],
                ret=row["return_pct"],
                trades=row["trades"],
                pf=row["profit_factor"],
                exp=row["expectancy_per_trade"],
                dd=row["max_drawdown_pct"],
                boot=row["bootstrap_positive_expectancy_prob"] * 100,
            )
        )

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Hinto walk-forward research.")
    parser.add_argument("--window", action="append", required=True, help="Window as START:END, repeatable.")
    parser.add_argument("--symbols", help="Comma-separated symbol universe. Defaults to dynamic top-N.")
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--balance", type=float, default=100.0)
    parser.add_argument("--risk", type=float, default=0.01)
    parser.add_argument("--leverage", type=float, default=float(PRODUCTION_LEVERAGE))
    parser.add_argument("--max-pos", type=int, default=4)
    parser.add_argument("--audit-runs", type=int, default=1000)
    parser.add_argument("--case", action="append", help="Only run named matrix case. Repeatable.")
    args = parser.parse_args()

    try:
        windows = parse_windows(args.window)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    window_reports = []
    for window in windows:
        matrix_report = run_matrix(
            days=None,
            start=window.start,
            end=window.end,
            symbols=args.symbols,
            top=args.top,
            balance=args.balance,
            risk=args.risk,
            leverage=args.leverage,
            max_pos=args.max_pos,
            audit_runs=args.audit_runs,
            case_names=args.case,
        )
        scoreboard_path = ROOT / matrix_report["scoreboard_json"]
        scoreboard = json.loads(scoreboard_path.read_text(encoding="utf-8"))
        window_reports.append(
            {
                "window": {"start": window.start, "end": window.end},
                "matrix_output": matrix_report["output"],
                "scoreboard_json": matrix_report["scoreboard_json"],
                "scoreboard_markdown": matrix_report["scoreboard_markdown"],
                "scoreboard": scoreboard,
            }
        )

    report = build_walk_forward_report(window_reports)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    output_json = ROOT / f"walk_forward_{stamp}.json"
    output_md = ROOT / f"walk_forward_{stamp}.md"
    output_json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    output_md.write_text(render_walk_forward_markdown(report), encoding="utf-8")

    print(
        json.dumps(
            {
                "output_json": output_json.name,
                "output_markdown": output_md.name,
                "summary": report["summary"],
                "case_summaries": report["case_summaries"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
