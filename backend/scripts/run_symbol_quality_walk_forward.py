"""Run pre-registered symbol-quality walk-forward research.

The script uses only a training window to rank symbols, then tests the selected
symbols on a later window. It is a research diagnostic, not a Paper runtime
optimizer.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from research_audit import audit_trades, load_trades
    from stop_first_rule_audit import AggregatedTrade, load_aggregated_trades
except ModuleNotFoundError:
    from .research_audit import audit_trades, load_trades
    from .stop_first_rule_audit import AggregatedTrade, load_aggregated_trades


DEFAULT_UNIVERSE = (
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "LTCUSDT",
    "BCHUSDT",
    "SUIUSDT",
)
STOP_REASONS = {"STOP_LOSS", "HARD_CAP"}


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


@dataclass(frozen=True)
class TrainTestWindow:
    train_start: str
    train_end: str
    test_start: str
    test_end: str

    @property
    def label(self) -> str:
        return f"{self.train_start}->{self.train_end} / {self.test_start}->{self.test_end}"


def parse_train_test_windows(values: list[str]) -> list[TrainTestWindow]:
    windows: list[TrainTestWindow] = []
    for value in values:
        parts = [part.strip() for part in value.split(":")]
        if len(parts) != 4 or any(not part for part in parts):
            raise ValueError(f"Invalid window '{value}'. Expected TRAIN_START:TRAIN_END:TEST_START:TEST_END.")
        windows.append(
            TrainTestWindow(
                train_start=parts[0],
                train_end=parts[1],
                test_start=parts[2],
                test_end=parts[3],
            )
        )
    return windows


def _is_stop(trade: AggregatedTrade) -> bool:
    return any(reason in STOP_REASONS for reason in trade.reasons)


def _profit_factor(pnls: list[float]) -> float | str:
    gross_win = sum(pnl for pnl in pnls if pnl > 0)
    gross_loss = abs(sum(pnl for pnl in pnls if pnl < 0))
    if gross_loss == 0:
        return "inf"
    return round(gross_win / gross_loss, 4)


def score_symbols(
    trades: list[AggregatedTrade],
    universe: list[str],
    *,
    balance: float = 100.0,
    risk: float = 0.01,
    min_trades: int = 3,
) -> list[dict[str, Any]]:
    """Score symbols from the training window only.

    Score = net PnL minus excess stop-rate penalty minus a small uncertainty
    penalty. It intentionally favors symbols that made money with fewer
    stop-first failures, not symbols that had one lucky winner.
    """

    risk_budget = balance * risk
    base_stop_rate = sum(1 for trade in trades if _is_stop(trade)) / len(trades) if trades else 0.0
    by_symbol = {symbol: [] for symbol in universe}
    for trade in trades:
        by_symbol.setdefault(trade.symbol, []).append(trade)

    rows: list[dict[str, Any]] = []
    for symbol in universe:
        group = by_symbol.get(symbol, [])
        pnls = [trade.pnl for trade in group]
        trade_count = len(group)
        total_pnl = sum(pnls)
        stop_rate = sum(1 for trade in group if _is_stop(trade)) / trade_count if trade_count else 1.0
        excess_stop_penalty = max(0.0, stop_rate - base_stop_rate) * trade_count * risk_budget
        uncertainty_penalty = 0.0
        if trade_count >= 2:
            mean = total_pnl / trade_count
            variance = sum((pnl - mean) ** 2 for pnl in pnls) / (trade_count - 1)
            uncertainty_penalty = math.sqrt(variance / trade_count)
        evidence_penalty = 0.0 if trade_count >= min_trades else risk_budget
        score = total_pnl - excess_stop_penalty - uncertainty_penalty - evidence_penalty
        rows.append(
            {
                "symbol": symbol,
                "score": round(score, 4),
                "trades": trade_count,
                "pnl": round(total_pnl, 4),
                "stop_rate": round(stop_rate * 100, 2) if trade_count else 100.0,
                "profit_factor": _profit_factor(pnls),
                "eligible_for_selection": trade_count >= min_trades,
            }
        )

    return sorted(
        rows,
        key=lambda row: (
            row["score"],
            row["eligible_for_selection"],
            row["pnl"],
            row["trades"],
            -row["stop_rate"],
        ),
        reverse=True,
    )


def select_symbols(rows: list[dict[str, Any]], *, count: int) -> list[str]:
    selected = [
        row["symbol"]
        for row in rows
        if row.get("eligible_for_selection") and float(row.get("score", 0.0)) > 0
    ][:count]
    if len(selected) < count:
        for row in rows:
            symbol = row["symbol"]
            if symbol not in selected:
                selected.append(symbol)
            if len(selected) >= count:
                break
    return selected


def _newest_metadata(before: set[Path]) -> Path:
    created = sorted(set(ROOT.glob("experiment_*.json")) - before, key=lambda path: path.stat().st_mtime, reverse=True)
    if not created:
        raise RuntimeError("backtest finished without creating experiment_*.json metadata")
    return created[0]


def _base_backtest_args(
    symbols: list[str],
    *,
    start: str,
    end: str,
    balance: float,
    risk: float,
    leverage: float,
    max_pos: int,
    breadth_min_symbols: int,
) -> list[str]:
    return [
        "--symbols",
        ",".join(symbols),
        "--start",
        start,
        "--end",
        end,
        "--balance",
        str(balance),
        "--risk",
        str(risk),
        "--leverage",
        str(leverage),
        "--max-pos",
        str(max_pos),
        "--no-compound",
        "--maker-orders",
        "--bounce-confirm",
        "--daily-symbol-loss-limit",
        "2",
        "--breadth-risk-gate",
        "--breadth-ema-bars",
        "96",
        "--breadth-momentum-bars",
        "24",
        "--breadth-long-threshold",
        "0.60",
        "--breadth-short-threshold",
        "0.60",
        "--breadth-min-symbols",
        str(breadth_min_symbols),
        "--1m-monitoring",
        "--volume-slippage",
        "--adversarial-path",
        "--btc-regime-filter",
        "--max-sl-validation",
        "--max-sl-pct",
        "1.4",
        "--symbol-side-loss-limit",
        "2",
        "--symbol-side-loss-window",
        "72",
        "--symbol-side-cooldown",
        "72",
        "--direction-block",
        "--direction-block-threshold",
        "3",
        "--direction-block-window",
        "4",
        "--direction-block-cooldown",
        "12",
        "--max-same-direction",
        "2",
        "--cb",
        "--max-losses",
        "4",
        "--cooldown",
        "12",
        "--drawdown",
        "0.08",
        "--no-close-profitable-auto",
        "--trailing-atr",
        "2.6",
        "--breakeven-r",
        "1.2",
    ]


def _run_backtest(case: str, args: list[str], *, balance: float, risk: float, audit_runs: int) -> dict[str, Any]:
    before = set(ROOT.glob("experiment_*.json"))
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, "run_backtest.py", *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    elapsed = time.perf_counter() - started
    if completed.returncode != 0:
        return {
            "case": case,
            "returncode": completed.returncode,
            "elapsed_seconds": round(elapsed, 2),
            "error_tail": completed.stdout[-4000:],
        }

    try:
        metadata_path = _newest_metadata(before)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        trade_path = ROOT / metadata["artifacts"]["trades_csv"]
        audit = audit_trades(
            load_trades(trade_path),
            initial_balance=balance,
            risk_percent=risk,
            monte_carlo_runs=audit_runs,
        )
    except Exception as exc:  # pragma: no cover - subprocess artifact guard
        return {
            "case": case,
            "returncode": completed.returncode,
            "elapsed_seconds": round(elapsed, 2),
            "error": str(exc),
            "output_tail": completed.stdout[-4000:],
        }

    return {
        "case": case,
        "returncode": completed.returncode,
        "elapsed_seconds": round(elapsed, 2),
        "metadata_file": metadata_path.name,
        "trade_file": trade_path.name,
        "config_hash": metadata.get("config_hash"),
        "summary": metadata.get("summary", {}),
        "audit": audit,
    }


def _metrics(run: dict[str, Any]) -> dict[str, Any]:
    audit = run.get("audit") or {}
    summary = run.get("summary") or {}
    return {
        "decision": audit.get("decision", "ERROR"),
        "return_pct": audit.get("return_pct", summary.get("net_return_pct")),
        "trades": audit.get("trades"),
        "profit_factor": audit.get("profit_factor"),
        "expectancy_per_trade": audit.get("expectancy_per_trade"),
        "max_drawdown_pct": audit.get("max_drawdown_pct", summary.get("max_drawdown_pct")),
        "bootstrap_positive_expectancy_prob": (audit.get("bootstrap") or {}).get("positive_expectancy_prob"),
    }


def run_symbol_quality_walk_forward(
    windows: list[TrainTestWindow],
    *,
    universe: list[str],
    select_count: int,
    min_train_trades: int,
    balance: float,
    risk: float,
    leverage: float,
    max_pos: int,
    audit_runs: int,
) -> dict[str, Any]:
    rows = []
    for window in windows:
        train_args = _base_backtest_args(
            universe,
            start=window.train_start,
            end=window.train_end,
            balance=balance,
            risk=risk,
            leverage=leverage,
            max_pos=max_pos,
            breadth_min_symbols=min(6, len(universe)),
        )
        train_run = _run_backtest("train_universe", train_args, balance=balance, risk=risk, audit_runs=audit_runs)
        if "trade_file" not in train_run:
            rows.append({"window": window.__dict__, "train_run": train_run, "status": "ERROR"})
            continue

        train_trades = load_aggregated_trades(ROOT / train_run["trade_file"])
        symbol_scores = score_symbols(
            train_trades,
            universe,
            balance=balance,
            risk=risk,
            min_trades=min_train_trades,
        )
        selected = select_symbols(symbol_scores, count=select_count)
        test_breadth_min_symbols = max(3, min(5, len(selected)))

        baseline_args = _base_backtest_args(
            universe,
            start=window.test_start,
            end=window.test_end,
            balance=balance,
            risk=risk,
            leverage=leverage,
            max_pos=max_pos,
            breadth_min_symbols=min(6, len(universe)),
        )
        selected_args = _base_backtest_args(
            selected,
            start=window.test_start,
            end=window.test_end,
            balance=balance,
            risk=risk,
            leverage=leverage,
            max_pos=max_pos,
            breadth_min_symbols=test_breadth_min_symbols,
        )

        baseline_run = _run_backtest(
            "test_universe_baseline",
            baseline_args,
            balance=balance,
            risk=risk,
            audit_runs=audit_runs,
        )
        selected_run = _run_backtest(
            "test_selected_symbols",
            selected_args,
            balance=balance,
            risk=risk,
            audit_runs=audit_runs,
        )
        rows.append(
            {
                "window": window.__dict__,
                "selected_symbols": selected,
                "top_symbol_scores": symbol_scores[: min(12, len(symbol_scores))],
                "train_run": train_run,
                "baseline_run": baseline_run,
                "selected_run": selected_run,
                "baseline_metrics": _metrics(baseline_run),
                "selected_metrics": _metrics(selected_run),
            }
        )

    selected_returns = [
        float(row["selected_metrics"]["return_pct"])
        for row in rows
        if row.get("selected_metrics", {}).get("return_pct") is not None
    ]
    baseline_returns = [
        float(row["baseline_metrics"]["return_pct"])
        for row in rows
        if row.get("baseline_metrics", {}).get("return_pct") is not None
    ]
    summary = {
        "window_count": len(rows),
        "selected_positive_windows": sum(1 for value in selected_returns if value > 0),
        "baseline_positive_windows": sum(1 for value in baseline_returns if value > 0),
        "selected_average_return_pct": round(sum(selected_returns) / len(selected_returns), 2)
        if selected_returns
        else 0.0,
        "baseline_average_return_pct": round(sum(baseline_returns) / len(baseline_returns), 2)
        if baseline_returns
        else 0.0,
        "decision": "REJECT",
    }
    if (
        rows
        and selected_returns
        and len(selected_returns) == len(rows)
        and min(selected_returns) > 0
        and summary["selected_average_return_pct"] > summary["baseline_average_return_pct"]
    ):
        summary["decision"] = "RESEARCH_LEAD_NEEDS_SCOREBOARD"

    return {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "universe": universe,
        "select_count": select_count,
        "min_train_trades": min_train_trades,
        "summary": summary,
        "rows": rows,
        "notes": "Selected symbols are chosen from training-window trade outcomes only. Do not apply to Paper without separate OOS gates.",
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Symbol-Quality Walk-Forward",
        "",
        f"Created: `{report.get('created_at_utc')}`",
        "",
        (
            f"Summary: decision `{summary['decision']}`, selected positive windows "
            f"`{summary['selected_positive_windows']}/{summary['window_count']}`, "
            f"selected avg return `{summary['selected_average_return_pct']:.2f}%`, "
            f"baseline avg return `{summary['baseline_average_return_pct']:.2f}%`."
        ),
        "",
        "| Train Window | Test Window | Selected | Baseline Return | Selected Return | Selected PF | Selected Trades | Decision |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in report.get("rows", []):
        window = row["window"]
        selected = ", ".join(row.get("selected_symbols", []))
        baseline = row.get("baseline_metrics", {})
        selected_metrics = row.get("selected_metrics", {})
        lines.append(
            "| {train_start}->{train_end} | {test_start}->{test_end} | {symbols} | "
            "{base_ret:.2f}% | {sel_ret:.2f}% | {pf} | {trades} | {decision} |".format(
                train_start=window["train_start"],
                train_end=window["train_end"],
                test_start=window["test_start"],
                test_end=window["test_end"],
                symbols=selected,
                base_ret=float(baseline.get("return_pct") or 0.0),
                sel_ret=float(selected_metrics.get("return_pct") or 0.0),
                pf=selected_metrics.get("profit_factor"),
                trades=selected_metrics.get("trades"),
                decision=selected_metrics.get("decision"),
            )
        )
    lines.append("")
    lines.append(report["notes"])
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run pre-registered symbol-quality walk-forward research.")
    parser.add_argument(
        "--window",
        action="append",
        required=True,
        help="TRAIN_START:TRAIN_END:TEST_START:TEST_END, repeatable.",
    )
    parser.add_argument("--symbols", default=",".join(DEFAULT_UNIVERSE))
    parser.add_argument("--select-count", type=int, default=6)
    parser.add_argument("--min-train-trades", type=int, default=3)
    parser.add_argument("--balance", type=float, default=100.0)
    parser.add_argument("--risk", type=float, default=0.01)
    parser.add_argument("--leverage", type=float, default=2.0)
    parser.add_argument("--max-pos", type=int, default=4)
    parser.add_argument("--audit-runs", type=int, default=1000)
    parser.add_argument("--output-json")
    parser.add_argument("--output-md")
    args = parser.parse_args()

    try:
        windows = parse_train_test_windows(args.window)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    universe = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()]
    report = run_symbol_quality_walk_forward(
        windows,
        universe=universe,
        select_count=args.select_count,
        min_train_trades=args.min_train_trades,
        balance=args.balance,
        risk=args.risk,
        leverage=args.leverage,
        max_pos=args.max_pos,
        audit_runs=args.audit_runs,
    )
    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.output_md:
        Path(args.output_md).write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
