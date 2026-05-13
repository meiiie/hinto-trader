"""Audit simple stop-first blocking rules from Hinto trade logs.

This is a research diagnostic, not a runtime optimizer. It aggregates partial
exit rows by Trade ID, then asks which simple categorical groups would have
improved or worsened the run if blocked. The intent is to identify future
pre-registered hypotheses, not to promote hindsight filters.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STOP_REASONS = {"STOP_LOSS", "HARD_CAP"}


@dataclass(frozen=True)
class AggregatedTrade:
    trade_id: str
    symbol: str
    side: str
    entry_time: datetime
    pnl: float
    reasons: tuple[str, ...]


def _parse_money(value: str | None) -> float:
    cleaned = (value or "0").replace("$", "").replace(",", "").replace("%", "").replace("x", "")
    return float(cleaned.strip() or 0.0)


def _parse_entry_time(row: dict[str, str]) -> datetime:
    raw = row.get("Entry Time (UTC+7)") or row.get("Entry Time") or ""
    return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")


def load_aggregated_trades(path: str | Path) -> list[AggregatedTrade]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for index, row in enumerate(reader):
            trade_id = (row.get("Trade ID") or f"row-{index}").strip() or f"row-{index}"
            grouped[trade_id].append(row)

    trades: list[AggregatedTrade] = []
    for trade_id, rows in grouped.items():
        first = rows[0]
        reasons = tuple(sorted({(row.get("Reason") or "").upper() for row in rows if row.get("Reason")}))
        trades.append(
            AggregatedTrade(
                trade_id=trade_id,
                symbol=(first.get("Symbol") or "").upper(),
                side=(first.get("Side") or "").upper(),
                entry_time=_parse_entry_time(first),
                pnl=sum(_parse_money(row.get("PnL ($)")) for row in rows),
                reasons=reasons,
            )
        )

    return sorted(trades, key=lambda trade: (trade.entry_time, trade.trade_id))


def _sum(values: Iterable[float]) -> float:
    return float(sum(values))


def _max_drawdown_from_pnls(initial_balance: float, pnls: Iterable[float]) -> float:
    balance = initial_balance
    peak = initial_balance
    max_drawdown = 0.0
    for pnl in pnls:
        balance += pnl
        peak = max(peak, balance)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - balance) / peak)
    return max_drawdown * 100


def _trade_summary(trades: list[AggregatedTrade], *, initial_balance: float) -> dict[str, Any]:
    wins = [trade for trade in trades if trade.pnl > 0]
    losses = [trade for trade in trades if trade.pnl < 0]
    gross_win = _sum(trade.pnl for trade in wins)
    gross_loss = abs(_sum(trade.pnl for trade in losses))
    stop_count = sum(1 for trade in trades if any(reason in STOP_REASONS for reason in trade.reasons))
    total = _sum(trade.pnl for trade in trades)
    return {
        "trades": len(trades),
        "pnl": round(total, 4),
        "return_pct": round(total / initial_balance * 100, 2) if initial_balance else 0.0,
        "win_rate": round(len(wins) / len(trades) * 100, 2) if trades else 0.0,
        "stop_rate": round(stop_count / len(trades) * 100, 2) if trades else 0.0,
        "profit_factor": round(gross_win / gross_loss, 4) if gross_loss else "inf",
        "max_drawdown_pct": round(_max_drawdown_from_pnls(initial_balance, [t.pnl for t in trades]), 2),
    }


def _feature_values(trade: AggregatedTrade) -> dict[str, str]:
    hour = f"{trade.entry_time.hour:02d}:00"
    return {
        "symbol": trade.symbol,
        "side": trade.side,
        "entry_hour": hour,
        "symbol_side": f"{trade.symbol}:{trade.side}",
        "side_hour": f"{trade.side}@{hour}",
    }


def audit_blocking_rules(
    trades: list[AggregatedTrade],
    *,
    initial_balance: float = 100.0,
    min_trades: int = 8,
) -> dict[str, Any]:
    base = _trade_summary(trades, initial_balance=initial_balance)
    midpoint = len(trades) // 2
    first_half_ids = {trade.trade_id for trade in trades[:midpoint]}
    second_half_ids = {trade.trade_id for trade in trades[midpoint:]}

    groups: dict[tuple[str, str], list[AggregatedTrade]] = defaultdict(list)
    for trade in trades:
        for feature, value in _feature_values(trade).items():
            groups[(feature, value)].append(trade)

    rows = []
    for (feature, value), group in groups.items():
        if len(group) < min_trades:
            continue
        remaining = [trade for trade in trades if trade not in group]
        removed_pnl = _sum(trade.pnl for trade in group)
        first_half_removed = _sum(trade.pnl for trade in group if trade.trade_id in first_half_ids)
        second_half_removed = _sum(trade.pnl for trade in group if trade.trade_id in second_half_ids)
        improvement = -removed_pnl
        rows.append(
            {
                "feature": feature,
                "value": value,
                "blocked_trades": len(group),
                "blocked_pnl": round(removed_pnl, 4),
                "net_improvement": round(improvement, 4),
                "first_half_improvement": round(-first_half_removed, 4),
                "second_half_improvement": round(-second_half_removed, 4),
                "stable_improvement": first_half_removed < 0 and second_half_removed < 0,
                "blocked_stop_rate": _trade_summary(group, initial_balance=initial_balance)["stop_rate"],
                "remaining": _trade_summary(remaining, initial_balance=initial_balance),
            }
        )

    rows.sort(
        key=lambda row: (
            row["stable_improvement"],
            row["net_improvement"],
            -row["remaining"]["max_drawdown_pct"],
        ),
        reverse=True,
    )

    harmful = [row for row in rows if row["net_improvement"] > 0]
    protective = sorted(rows, key=lambda row: row["net_improvement"])[:10]
    return {
        "base": base,
        "min_trades": min_trades,
        "rules": rows,
        "top_harmful_groups": harmful[:20],
        "top_protective_groups": protective,
        "notes": (
            "Rules are hindsight diagnostics. Use them only to define future "
            "pre-registered tests; do not apply them directly to Paper."
        ),
    }


def render_markdown(report: dict[str, Any]) -> str:
    base = report["base"]
    lines = [
        "# Stop-First Rule Audit",
        "",
        "This is a hindsight diagnostic. It is not a promotion signal.",
        "",
        (
            f"Base: `{base['trades']}` aggregated trades, `{base['return_pct']:.2f}%`, "
            f"PF `{base['profit_factor']}`, max DD `{base['max_drawdown_pct']:.2f}%`, "
            f"stop rate `{base['stop_rate']:.2f}%`."
        ),
        "",
        "## Top Harmful Groups",
        "",
        "| Feature | Value | Blocked Trades | Blocked PnL | Net Improvement | Stable | Remaining Return | Remaining DD | Stop Rate |",
        "| --- | --- | ---: | ---: | ---: | --- | ---: | ---: | ---: |",
    ]
    for row in report["top_harmful_groups"]:
        remaining = row["remaining"]
        lines.append(
            f"| {row['feature']} | {row['value']} | {row['blocked_trades']} | "
            f"{row['blocked_pnl']:+.2f} | {row['net_improvement']:+.2f} | "
            f"{'yes' if row['stable_improvement'] else 'no'} | "
            f"{remaining['return_pct']:+.2f}% | {remaining['max_drawdown_pct']:.2f}% | "
            f"{row['blocked_stop_rate']:.2f}% |"
        )

    lines.extend(
        [
            "",
            "## Protective Groups",
            "",
            "| Feature | Value | Blocked Trades | Blocked PnL | Damage If Blocked |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    for row in report["top_protective_groups"]:
        lines.append(
            f"| {row['feature']} | {row['value']} | {row['blocked_trades']} | "
            f"{row['blocked_pnl']:+.2f} | {row['net_improvement']:+.2f} |"
        )
    lines.append("")
    lines.append(report["notes"])
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit stop-first blocking rules from a trade CSV.")
    parser.add_argument("trade_csv", help="portfolio_backtest_*.csv")
    parser.add_argument("--balance", type=float, default=100.0)
    parser.add_argument("--min-trades", type=int, default=8)
    parser.add_argument("--output-json")
    parser.add_argument("--output-md")
    args = parser.parse_args()

    trades = load_aggregated_trades(args.trade_csv)
    report = audit_blocking_rules(trades, initial_balance=args.balance, min_trades=args.min_trades)

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.output_md:
        Path(args.output_md).write_text(render_markdown(report), encoding="utf-8")

    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
