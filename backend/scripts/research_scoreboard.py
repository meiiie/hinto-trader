"""Build concise scoreboards from Hinto research artifacts.

The scoreboard is intentionally derived from the same trade CSV and experiment
metadata used by checkpoints. It gives each run a small set of promotion gates
so a profitable-looking backtest cannot hide a weak sample, poor expectancy, or
fragile bootstrap result.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from research_audit import audit_trades, load_trades
except ModuleNotFoundError:
    from .research_audit import audit_trades, load_trades


ROOT = Path(__file__).resolve().parents[1]


def _as_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if value == "inf":
        return float("inf")
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _gate(name: str, status: str, actual: Any, target: str, note: str) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "actual": actual,
        "target": target,
        "note": note,
    }


def _sample_gate(trades: int) -> dict[str, Any]:
    if trades >= 200:
        return _gate("sample_size", "PASS", trades, ">= 200", "enough for a paper research read")
    if trades >= 100:
        return _gate("sample_size", "WARN", trades, ">= 200", "usable but still thin")
    return _gate("sample_size", "FAIL", trades, ">= 200", "too few trades to trust")


def _expectancy_gate(expectancy: float) -> dict[str, Any]:
    if expectancy > 0:
        return _gate("expectancy", "PASS", round(expectancy, 4), "> 0", "average trade is positive")
    return _gate("expectancy", "FAIL", round(expectancy, 4), "> 0", "average trade is not positive")


def _profit_factor_gate(profit_factor: float) -> dict[str, Any]:
    if profit_factor >= 1.2:
        return _gate("profit_factor", "PASS", round(profit_factor, 4), ">= 1.20", "clears paper candidate floor")
    if profit_factor >= 1.0:
        return _gate("profit_factor", "WARN", round(profit_factor, 4), ">= 1.20", "thin edge")
    return _gate("profit_factor", "FAIL", round(profit_factor, 4), ">= 1.20", "gross losses dominate")


def _bootstrap_gate(probability: float) -> dict[str, Any]:
    if probability >= 0.90:
        return _gate(
            "bootstrap_positive_expectancy",
            "PASS",
            round(probability, 4),
            ">= 0.90",
            "robust enough for paper research",
        )
    if probability >= 0.75:
        return _gate(
            "bootstrap_positive_expectancy",
            "WARN",
            round(probability, 4),
            ">= 0.90",
            "promising but fragile",
        )
    return _gate(
        "bootstrap_positive_expectancy",
        "FAIL",
        round(probability, 4),
        ">= 0.90",
        "bootstrap usually fails",
    )


def _drawdown_gate(max_drawdown_pct: float) -> dict[str, Any]:
    if max_drawdown_pct <= 10.0:
        return _gate("max_drawdown_pct", "PASS", round(max_drawdown_pct, 2), "<= 10", "paper risk is contained")
    if max_drawdown_pct <= 20.0:
        return _gate("max_drawdown_pct", "WARN", round(max_drawdown_pct, 2), "<= 10", "drawdown needs review")
    return _gate("max_drawdown_pct", "FAIL", round(max_drawdown_pct, 2), "<= 10", "drawdown is too high")


def _selection_adjusted_bootstrap_gate(probability: float, case_count: int) -> dict[str, Any]:
    if probability >= 0.75:
        return _gate(
            "selection_adjusted_bootstrap",
            "PASS",
            round(probability, 4),
            ">= 0.75 after matrix haircut",
            f"accounts for selecting from {case_count} tested cases",
        )
    if probability >= 0.50:
        return _gate(
            "selection_adjusted_bootstrap",
            "WARN",
            round(probability, 4),
            ">= 0.75 after matrix haircut",
            f"edge weakens after {case_count} tested cases",
        )
    return _gate(
        "selection_adjusted_bootstrap",
        "FAIL",
        round(probability, 4),
        ">= 0.75 after matrix haircut",
        f"likely data-snooping after {case_count} tested cases",
    )


def _status_from_gates(gates: list[dict[str, Any]]) -> str:
    fail_count = sum(1 for gate in gates if gate["status"] == "FAIL")
    warn_count = sum(1 for gate in gates if gate["status"] == "WARN")
    if fail_count:
        return "FAIL"
    if warn_count:
        return "WARN"
    return "PASS"


def _recommendation(decision: str, gates: list[dict[str, Any]]) -> str:
    fail_count = sum(1 for gate in gates if gate["status"] == "FAIL")
    if decision == "REJECT":
        return "Do not update paper runtime from this run."
    if decision == "NO_TRADES":
        return "No evidence yet; widen the window or inspect filters."
    if fail_count:
        return "Gate failures remain; do not update paper runtime without manual review."
    if decision == "PAPER_ONLY_SMALL_SAMPLE":
        return "Paper observation only; collect more comparable trades."
    if decision == "PAPER_RESEARCH_CANDIDATE_NEEDS_OOS":
        return "Run out-of-sample, stress, and walk-forward checks before paper changes."
    if decision == "PROMOTION_CANDIDATE_REVIEW_REQUIRED":
        return "Review manually; this is still not automatic live approval."
    return "Review manually before changing runtime settings."


def score_case_result(result: dict[str, Any]) -> dict[str, Any]:
    """Convert one matrix result into a compact scoreboard row."""
    case_name = str(result.get("case") or result.get("metadata_file") or "unknown")
    if int(result.get("returncode", 0) or 0) != 0 or "audit" not in result:
        return {
            "case": case_name,
            "status": "ERROR",
            "decision": "ERROR",
            "config_hash": result.get("config_hash"),
            "metrics": {},
            "gates": [_gate("backtest_completed", "FAIL", result.get("returncode"), "0", "case did not complete")],
            "recommendation": "Fix the run error before judging the strategy.",
            "error_tail": result.get("error_tail") or result.get("output_tail") or result.get("error"),
        }

    audit = result.get("audit", {})
    summary = result.get("summary", {})
    bootstrap = audit.get("bootstrap", {})
    trades = int(audit.get("trades", summary.get("total_trades", 0)) or 0)
    profit_factor = _as_float(audit.get("profit_factor"))
    expectancy = _as_float(audit.get("expectancy_per_trade"))
    max_drawdown_pct = _as_float(audit.get("max_drawdown_pct", summary.get("max_drawdown_pct")))
    bootstrap_positive = _as_float(bootstrap.get("positive_expectancy_prob"))
    decision = str(audit.get("decision") or "UNKNOWN")

    gates = [
        _sample_gate(trades),
        _expectancy_gate(expectancy),
        _profit_factor_gate(profit_factor),
        _bootstrap_gate(bootstrap_positive),
        _drawdown_gate(max_drawdown_pct),
    ]

    metrics = {
        "return_pct": _as_float(audit.get("return_pct", summary.get("net_return_pct"))),
        "trades": trades,
        "win_rate": _as_float(audit.get("win_rate", summary.get("win_rate"))),
        "profit_factor": profit_factor,
        "expectancy_per_trade": expectancy,
        "avg_r": _as_float(audit.get("avg_r")),
        "median_r": _as_float(audit.get("median_r")),
        "max_drawdown_pct": max_drawdown_pct,
        "longest_loss_streak": int(audit.get("longest_loss_streak", 0) or 0),
        "bootstrap_positive_expectancy_prob": bootstrap_positive,
        "bootstrap_return_p05_pct": _as_float(bootstrap.get("return_p05_pct")),
        "quality_filter_rejections": int(summary.get("quality_filter_rejections", 0) or 0),
    }

    return {
        "case": case_name,
        "status": _status_from_gates(gates),
        "decision": decision,
        "config_hash": result.get("config_hash"),
        "metadata_file": result.get("metadata_file"),
        "trade_file": result.get("trade_file"),
        "elapsed_seconds": result.get("elapsed_seconds"),
        "metrics": metrics,
        "gates": gates,
        "recommendation": _recommendation(decision, gates),
        "worst_symbols": audit.get("worst_symbols", []),
        "reason_breakdown": audit.get("reason_breakdown", []),
    }


def _apply_selection_haircut(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    completed_cases = [case for case in cases if case.get("metrics")]
    case_count = len(completed_cases)
    if case_count <= 1:
        return cases

    for case in completed_cases:
        metrics = case["metrics"]
        bootstrap_positive = _as_float(metrics.get("bootstrap_positive_expectancy_prob"))
        false_edge_risk = min(1.0, (1.0 - bootstrap_positive) * case_count)
        adjusted_probability = round(max(0.0, 1.0 - false_edge_risk), 6)
        metrics["selection_adjusted_bootstrap_positive_prob"] = adjusted_probability

        gates = [gate for gate in case.get("gates", []) if gate["name"] != "selection_adjusted_bootstrap"]
        gates.append(_selection_adjusted_bootstrap_gate(adjusted_probability, case_count))
        case["gates"] = gates
        case["status"] = _status_from_gates(gates)
        case["recommendation"] = _recommendation(str(case.get("decision") or "UNKNOWN"), gates)

    return cases


def _rank_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        cases,
        key=lambda case: (
            case["status"] == "PASS",
            case["status"] == "WARN",
            _as_float(case.get("metrics", {}).get("return_pct")),
        ),
        reverse=True,
    )


def build_scoreboard(results: list[dict[str, Any]]) -> dict[str, Any]:
    cases = [score_case_result(result) for result in results]
    _apply_selection_haircut(cases)
    decisions = Counter(case["decision"] for case in cases)
    statuses = Counter(case["status"] for case in cases)

    ranked = _rank_cases(cases)
    best_case = ranked[0]["case"] if ranked else None

    return {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "case_count": len(cases),
            "status_counts": dict(statuses),
            "decision_counts": dict(decisions),
            "best_case_by_status_then_return": best_case,
        },
        "cases": cases,
    }


def summarize_experiment(
    metadata_path: str | Path,
    *,
    audit_runs: int = 1000,
    seed: int = 1337,
) -> dict[str, Any]:
    metadata_path = Path(metadata_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    args = metadata.get("experiment_config", {}).get("args", {})
    artifacts = metadata.get("artifacts", {})
    trade_path = metadata_path.parent / artifacts["trades_csv"]
    audit = audit_trades(
        load_trades(trade_path),
        initial_balance=float(args.get("balance", 100.0) or 100.0),
        risk_percent=float(args.get("risk", 0.01) or 0.01),
        monte_carlo_runs=audit_runs,
        seed=seed,
    )
    result = {
        "case": metadata_path.stem,
        "returncode": 0,
        "metadata_file": metadata_path.name,
        "config_hash": metadata.get("config_hash"),
        "trade_file": trade_path.name,
        "summary": metadata.get("summary", {}),
        "audit": audit,
    }
    return score_case_result(result)


def render_scoreboard_markdown(scoreboard: dict[str, Any]) -> str:
    lines = [
        "# Hinto Research Scoreboard",
        "",
        f"Created: `{scoreboard.get('created_at_utc')}`",
        "",
        "| Case | Status | Decision | Return | Trades | PF | Exp/Trade | Max DD | Boot+ | Adj Boot+ |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for case in scoreboard.get("cases", []):
        metrics = case.get("metrics", {})
        adjusted_bootstrap = metrics.get("selection_adjusted_bootstrap_positive_prob")
        adjusted_text = "-" if adjusted_bootstrap is None else f"{_as_float(adjusted_bootstrap) * 100:.2f}%"
        lines.append(
            f"| {case.get('case', '')} | {case.get('status', '')} | {case.get('decision', '')} | "
            f"{_as_float(metrics.get('return_pct')):.2f}% | {int(metrics.get('trades', 0) or 0)} | "
            f"{_as_float(metrics.get('profit_factor')):.2f} | "
            f"{_as_float(metrics.get('expectancy_per_trade')):.4f} | "
            f"{_as_float(metrics.get('max_drawdown_pct')):.2f}% | "
            f"{_as_float(metrics.get('bootstrap_positive_expectancy_prob')) * 100:.2f}% | {adjusted_text} |"
        )

    for case in scoreboard.get("cases", []):
        lines.extend(["", f"## {case.get('case')}", "", f"Recommendation: {case.get('recommendation')}"])
        lines.append("")
        lines.append("| Gate | Status | Actual | Target | Note |")
        lines.append("| --- | --- | ---: | --- | --- |")
        for gate in case.get("gates", []):
            lines.append(
                f"| {gate['name']} | {gate['status']} | `{gate['actual']}` | `{gate['target']}` | {gate['note']} |"
            )

        worst_symbols = case.get("worst_symbols", [])[:5]
        if worst_symbols:
            rendered = ", ".join(
                f"{row['key']} ({row['pnl']:+.2f}, {row['trades']} trades)" for row in worst_symbols
            )
            lines.extend(["", f"Worst symbols: {rendered}"])

        reasons = case.get("reason_breakdown", [])[:5]
        if reasons:
            rendered = ", ".join(
                f"{row['key']} ({row['pnl']:+.2f}, {row['trades']} trades)" for row in reasons
            )
            lines.append(f"Exit reasons: {rendered}")

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Hinto research scoreboards.")
    parser.add_argument("experiment", nargs="*", help="experiment_*.json files to score")
    parser.add_argument("--audit-runs", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--output-json", help="Optional JSON output path")
    parser.add_argument("--output-md", help="Optional Markdown output path")
    args = parser.parse_args()

    if not args.experiment:
        raise SystemExit("Provide at least one experiment_*.json file")

    cases = [
        summarize_experiment(path, audit_runs=args.audit_runs, seed=args.seed)
        for path in args.experiment
    ]
    _apply_selection_haircut(cases)
    ranked = _rank_cases(cases)
    scoreboard = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "case_count": len(cases),
            "status_counts": dict(Counter(case["status"] for case in cases)),
            "decision_counts": dict(Counter(case["decision"] for case in cases)),
            "best_case_by_status_then_return": ranked[0]["case"] if ranked else None,
        },
        "cases": cases,
    }

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(scoreboard, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.output_md:
        Path(args.output_md).write_text(render_scoreboard_markdown(scoreboard), encoding="utf-8")

    print(json.dumps(scoreboard, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
