"""Run a small, reproducible Hinto backtest matrix.

This script intentionally wraps the existing event-driven backtester instead of
reimplementing execution logic. It records runtime, experiment metadata, and
research-audit output for each case so strategy comparisons are traceable.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    from research_audit import audit_trades, load_trades
    from research_scoreboard import build_scoreboard, render_scoreboard_markdown
except ModuleNotFoundError:
    from .research_audit import audit_trades, load_trades
    from .research_scoreboard import build_scoreboard, render_scoreboard_markdown


ROOT = Path(__file__).resolve().parents[1]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


@dataclass(frozen=True)
class ResearchCase:
    name: str
    args: tuple[str, ...]


def _base_args(
    days: int | None,
    start: str | None,
    end: str | None,
    symbols: str | None,
    *,
    top: int,
    balance: float,
    risk: float,
    leverage: float,
    max_pos: int,
) -> list[str]:
    args = [
        "--balance",
        str(balance),
        "--risk",
        str(risk),
        "--leverage",
        str(leverage),
        "--max-pos",
        str(max_pos),
        "--no-compound",
        "--full-tp",
        "--maker-orders",
    ]
    if start or end:
        if not start or not end:
            raise ValueError("--start and --end must be provided together")
        args = ["--start", start, "--end", end, *args]
    else:
        args = ["--days", str(days or 30), *args]
    if symbols:
        args = ["--symbols", symbols, *args]
    else:
        args = ["--top", str(top), *args]
    return args


def _cases(
    days: int | None,
    start: str | None,
    end: str | None,
    symbols: str | None,
    *,
    top: int,
    balance: float,
    risk: float,
    leverage: float,
    max_pos: int,
) -> list[ResearchCase]:
    base = _base_args(
        days,
        start,
        end,
        symbols,
        top=top,
        balance=balance,
        risk=risk,
        leverage=leverage,
        max_pos=max_pos,
    )
    return [
        ResearchCase("baseline_contract", tuple(base)),
        ResearchCase(
            "bounce_daily2",
            tuple([*base, "--bounce-confirm", "--daily-symbol-loss-limit", "2"]),
        ),
        ResearchCase(
            "trend_runner",
            tuple([*base, "--strategy-id", "liquidity_reclaim_trend_runner"]),
        ),
        ResearchCase(
            "bounce_no_mtf",
            tuple(
                [
                    *base,
                    "--bounce-confirm",
                    "--daily-symbol-loss-limit",
                    "2",
                    "--no-mtf-trend",
                ]
            ),
        ),
        ResearchCase(
            "bounce_no_delta",
            tuple(
                [
                    *base,
                    "--bounce-confirm",
                    "--daily-symbol-loss-limit",
                    "2",
                    "--no-delta-divergence",
                ]
            ),
        ),
        ResearchCase(
            "bounce_taker_fee_stress",
            tuple([*base, "--bounce-confirm", "--daily-symbol-loss-limit", "2"]),
        ),
        ResearchCase(
            "bounce_fill_buffer_stress",
            tuple(
                [
                    *base,
                    "--maker-orders",
                    "--fill-buffer",
                    "0.02",
                    "--bounce-confirm",
                    "--daily-symbol-loss-limit",
                    "2",
                ]
            ),
        ),
    ]


def _newest_metadata(before: set[Path]) -> Path:
    after = set(ROOT.glob("experiment_*.json"))
    created = sorted(after - before, key=lambda path: path.stat().st_mtime, reverse=True)
    if not created:
        raise RuntimeError("backtest finished without creating experiment_*.json metadata")
    return created[0]


def _run_case(case: ResearchCase, audit_runs: int) -> dict:
    before = set(ROOT.glob("experiment_*.json"))
    cmd = [sys.executable, "run_backtest.py", *case.args]
    started = time.perf_counter()
    completed = subprocess.run(
        cmd,
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
            "case": case.name,
            "returncode": completed.returncode,
            "elapsed_seconds": round(elapsed, 2),
            "error_tail": completed.stdout[-4000:],
        }

    try:
        metadata_path = _newest_metadata(before)
    except RuntimeError as exc:
        return {
            "case": case.name,
            "returncode": completed.returncode,
            "elapsed_seconds": round(elapsed, 2),
            "error": str(exc),
            "output_tail": completed.stdout[-4000:],
        }
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    trade_path = ROOT / metadata["artifacts"]["trades_csv"]
    audit = audit_trades(
        load_trades(trade_path),
        initial_balance=100.0,
        risk_percent=0.01,
        monte_carlo_runs=audit_runs,
    )
    return {
        "case": case.name,
        "returncode": completed.returncode,
        "elapsed_seconds": round(elapsed, 2),
        "metadata_file": metadata_path.name,
        "config_hash": metadata["config_hash"],
        "trade_file": trade_path.name,
        "summary": metadata["summary"],
        "audit": audit,
    }


def run_matrix(
    *,
    days: int | None,
    start: str | None,
    end: str | None,
    symbols: str | None,
    top: int,
    balance: float,
    risk: float,
    leverage: float,
    max_pos: int,
    audit_runs: int,
    case_names: list[str] | None = None,
) -> dict:
    cases = _cases(
        days,
        start,
        end,
        symbols,
        top=top,
        balance=balance,
        risk=risk,
        leverage=leverage,
        max_pos=max_pos,
    )
    if case_names:
        wanted = set(case_names)
        cases = [case for case in cases if case.name in wanted]
        missing = wanted - {case.name for case in cases}
        if missing:
            raise ValueError(f"Unknown case(s): {', '.join(sorted(missing))}")

    results = [_run_case(case, audit_runs) for case in cases]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output = ROOT / f"research_matrix_{stamp}.json"
    scoreboard = build_scoreboard(results)
    scoreboard_json = ROOT / f"research_scoreboard_{stamp}.json"
    scoreboard_md = ROOT / f"research_scoreboard_{stamp}.md"

    output.write_text(
        json.dumps(
            {
                "results": results,
                "scoreboard_json": scoreboard_json.name,
                "scoreboard_markdown": scoreboard_md.name,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    scoreboard_json.write_text(json.dumps(scoreboard, indent=2, ensure_ascii=False), encoding="utf-8")
    scoreboard_md.write_text(render_scoreboard_markdown(scoreboard), encoding="utf-8")
    return {
        "output": output.name,
        "scoreboard_json": scoreboard_json.name,
        "scoreboard_markdown": scoreboard_md.name,
        "scoreboard_summary": scoreboard["summary"],
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Hinto research matrix.")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--start", help="Start date YYYY-MM-DD. Must be paired with --end.")
    parser.add_argument("--end", help="End date YYYY-MM-DD. Must be paired with --start.")
    parser.add_argument("--symbols", help="Comma-separated symbol universe. Defaults to a dynamic top-N universe.")
    parser.add_argument("--top", type=int, default=30, help="Dynamic top-N universe when --symbols is not provided.")
    parser.add_argument("--balance", type=float, default=100.0)
    parser.add_argument("--risk", type=float, default=0.01)
    parser.add_argument("--leverage", type=float, default=20.0)
    parser.add_argument("--max-pos", type=int, default=4)
    parser.add_argument("--audit-runs", type=int, default=1000)
    parser.add_argument("--case", action="append", help="Only run named case. Repeatable.")
    args = parser.parse_args()

    try:
        report = run_matrix(
            days=args.days,
            start=args.start,
            end=args.end,
            symbols=args.symbols,
            top=args.top,
            balance=args.balance,
            risk=args.risk,
            leverage=args.leverage,
            max_pos=args.max_pos,
            audit_runs=args.audit_runs,
            case_names=args.case,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    print(
        json.dumps(report, indent=2, ensure_ascii=False)
    )


if __name__ == "__main__":
    main()
