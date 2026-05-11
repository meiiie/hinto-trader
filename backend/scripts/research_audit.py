"""Research audit utilities for Hinto backtest trade logs.

The goal is to judge strategy quality by expectancy, payoff, R-multiples, and
drawdown robustness instead of headline win rate.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class TradeRow:
    symbol: str
    side: str
    entry_time: datetime
    pnl: float
    reason: str
    account_balance: float


def _parse_money(value: str) -> float:
    cleaned = (value or "0").replace("$", "").replace(",", "").replace("%", "").replace("x", "")
    return float(cleaned.strip() or 0.0)


def load_trades(path: str | Path) -> list[TradeRow]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        trades: list[TradeRow] = []
        for row in reader:
            trades.append(
                TradeRow(
                    symbol=(row.get("Symbol") or "").upper(),
                    side=(row.get("Side") or "").upper(),
                    entry_time=datetime.strptime(row["Entry Time (UTC+7)"], "%Y-%m-%d %H:%M:%S"),
                    pnl=_parse_money(row.get("PnL ($)", "0")),
                    reason=(row.get("Reason") or "").upper(),
                    account_balance=_parse_money(row.get("Account Balance", "0")),
                )
            )
    return trades


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
    return max_drawdown


def _longest_loss_streak(trades: list[TradeRow]) -> int:
    longest = 0
    current = 0
    for trade in trades:
        if trade.pnl < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _group_breakdown(trades: list[TradeRow], key_fn) -> list[dict]:
    groups: dict[str, list[TradeRow]] = defaultdict(list)
    for trade in trades:
        groups[str(key_fn(trade))].append(trade)

    rows = []
    for key, group in groups.items():
        wins = [t for t in group if t.pnl > 0]
        rows.append(
            {
                "key": key,
                "trades": len(group),
                "pnl": round(_sum(t.pnl for t in group), 4),
                "win_rate": round(len(wins) / len(group) * 100, 2) if group else 0.0,
            }
        )
    return sorted(rows, key=lambda item: item["pnl"])


def _monte_carlo_drawdown(
    trades: list[TradeRow],
    initial_balance: float,
    runs: int,
    seed: int,
) -> dict:
    if not trades or runs <= 0:
        return {"runs": 0}

    rng = random.Random(seed)
    pnls = [t.pnl for t in trades]
    drawdowns = []
    ending_balances = []
    for _ in range(runs):
        sample = pnls[:]
        rng.shuffle(sample)
        drawdowns.append(_max_drawdown_from_pnls(initial_balance, sample) * 100)
        ending_balances.append(initial_balance + sum(sample))

    drawdowns.sort()
    ending_balances.sort()

    def percentile(values: list[float], pct: float) -> float:
        if not values:
            return 0.0
        index = min(len(values) - 1, max(0, round((pct / 100) * (len(values) - 1))))
        return values[index]

    return {
        "runs": runs,
        "max_dd_p50": round(percentile(drawdowns, 50), 2),
        "max_dd_p95": round(percentile(drawdowns, 95), 2),
        "ending_balance_p05": round(percentile(ending_balances, 5), 2),
        "ending_balance_p50": round(percentile(ending_balances, 50), 2),
    }


def audit_trades(
    trades: list[TradeRow],
    *,
    initial_balance: float = 100.0,
    risk_percent: float = 0.01,
    monte_carlo_runs: int = 1000,
    seed: int = 1337,
) -> dict:
    if not trades:
        return {"trades": 0, "decision": "NO_TRADES"}

    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl < 0]
    gross_win = _sum(t.pnl for t in wins)
    gross_loss = abs(_sum(t.pnl for t in losses))
    total_pnl = _sum(t.pnl for t in trades)
    avg_win = gross_win / len(wins) if wins else 0.0
    avg_loss = -gross_loss / len(losses) if losses else 0.0
    risk_budget = initial_balance * risk_percent
    r_values = [t.pnl / risk_budget for t in trades] if risk_budget > 0 else []

    expectancy = total_pnl / len(trades)
    profit_factor = gross_win / gross_loss if gross_loss else float("inf")
    payoff = avg_win / abs(avg_loss) if avg_loss else float("inf")
    win_rate = len(wins) / len(trades)
    max_dd = _max_drawdown_from_pnls(initial_balance, [t.pnl for t in trades]) * 100

    decision = "REJECT"
    if expectancy > 0 and profit_factor >= 1.0 and len(trades) < 100:
        decision = "PAPER_ONLY_SMALL_SAMPLE"
    elif profit_factor >= 1.2 and expectancy > 0 and payoff >= 1.2:
        decision = "CANDIDATE"

    return {
        "trades": len(trades),
        "net_pnl": round(total_pnl, 4),
        "return_pct": round(total_pnl / initial_balance * 100, 2) if initial_balance else 0.0,
        "win_rate": round(win_rate * 100, 2),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else "inf",
        "payoff": round(payoff, 4) if payoff != float("inf") else "inf",
        "expectancy_per_trade": round(expectancy, 4),
        "avg_win": round(avg_win, 4),
        "avg_loss": round(avg_loss, 4),
        "avg_r": round(statistics.mean(r_values), 4) if r_values else 0.0,
        "median_r": round(statistics.median(r_values), 4) if r_values else 0.0,
        "max_drawdown_pct": round(max_dd, 2),
        "longest_loss_streak": _longest_loss_streak(trades),
        "reason_breakdown": _group_breakdown(trades, lambda t: t.reason),
        "worst_symbols": _group_breakdown(trades, lambda t: t.symbol)[:8],
        "worst_entry_hours": _group_breakdown(trades, lambda t: f"{t.entry_time.hour:02d}:00")[:8],
        "monte_carlo": _monte_carlo_drawdown(trades, initial_balance, monte_carlo_runs, seed),
        "decision": decision,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit Hinto backtest trade CSVs.")
    parser.add_argument("csv_path", help="Path to portfolio_backtest_*.csv")
    parser.add_argument("--balance", type=float, default=100.0)
    parser.add_argument("--risk", type=float, default=0.01)
    parser.add_argument("--mc-runs", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=1337)
    args = parser.parse_args()

    report = audit_trades(
        load_trades(args.csv_path),
        initial_balance=args.balance,
        risk_percent=args.risk,
        monte_carlo_runs=args.mc_runs,
        seed=args.seed,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
