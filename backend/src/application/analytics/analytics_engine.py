"""
AnalyticsEngine — Application Layer

Core metrics computation from Binance truth data.
All calculations use BinanceTrade entities from analytics DB.

Metrics: WR, PF, R:R, edge, Sharpe, Sortino, Calmar, rolling windows,
equity curve, Z-test p-value for statistical significance.

v6.3.0: Institutional Analytics System
"""

import math
import logging
import statistics
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from ...domain.entities.binance_trade import BinanceTrade
from ...infrastructure.persistence.analytics_repository import AnalyticsRepository

UTC7 = timezone(timedelta(hours=7))


class AnalyticsEngine:
    """
    Core analytics engine — computes all metrics from Binance truth.

    Passive/read-only. All data comes from AnalyticsRepository.
    """

    def __init__(self, analytics_repo: AnalyticsRepository):
        self.repo = analytics_repo
        self.logger = logging.getLogger(__name__)

    def get_full_report(self, version_tag: Optional[str] = None,
                        days: Optional[int] = None) -> Dict:
        """
        Generate comprehensive analytics report.

        Args:
            version_tag: Filter by version (e.g. "v6.2.0")
            days: Filter to last N days (None = all)
        """
        since_ms = None
        if days:
            since_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)

        trades = self.repo.get_all_trades(version_tag=version_tag, since_ms=since_ms)
        if not trades:
            return self._empty_report()

        core = self._compute_core_metrics(trades)
        risk = self._compute_risk_metrics(trades)
        equity = self._compute_equity_curve(trades)
        significance = self._compute_significance(trades)
        rolling = self._compute_rolling_metrics(trades, window=20)
        daily = self._compute_daily_breakdown(trades)

        return {
            "total_trades": core["total_trades"],
            "wins": core["wins"],
            "losses": core["losses"],
            "win_rate": core["win_rate"],
            "profit_factor": core["profit_factor"],
            "total_net_pnl": core["total_net_pnl"],
            "total_gross_pnl": core["total_gross_pnl"],
            "total_fees": core["total_fees"],
            "fee_drag_pct": core["fee_drag_pct"],
            "avg_win": core["avg_win"],
            "avg_loss": core["avg_loss"],
            "rr_ratio": core["rr_ratio"],
            "breakeven_wr": core["breakeven_wr"],
            "edge_pp": core["edge_pp"],
            "expectancy": core["expectancy"],
            "largest_win": core["largest_win"],
            "largest_loss": core["largest_loss"],
            "risk_metrics": risk,
            "equity_curve": equity,
            "significance": significance,
            "rolling": rolling,
            "daily_breakdown": daily,
            "version_tag": version_tag or "all",
            "days_filter": days,
            "generated_at": datetime.now(UTC7).isoformat(),
        }

    def _compute_core_metrics(self, trades: List[BinanceTrade]) -> Dict:
        """Compute core trading metrics."""
        total = len(trades)
        wins_list = [t for t in trades if t.is_win]
        losses_list = [t for t in trades if t.is_loss]
        wins = len(wins_list)
        losses = len(losses_list)

        win_rate = wins / total if total > 0 else 0.0

        gross_profit = sum(t.net_pnl for t in wins_list)
        gross_loss = abs(sum(t.net_pnl for t in losses_list))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (
            float('inf') if gross_profit > 0 else 0.0
        )

        total_net = sum(t.net_pnl for t in trades)
        total_gross = sum(t.gross_pnl for t in trades)
        total_fees = sum(t.commission for t in trades)
        fee_drag = (total_fees / total_gross * 100) if total_gross != 0 else 0.0

        avg_win = gross_profit / wins if wins > 0 else 0.0
        avg_loss = gross_loss / losses if losses > 0 else 0.0
        rr_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0
        breakeven_wr = (1 / (1 + rr_ratio) * 100) if rr_ratio > 0 else 100.0
        edge_pp = (win_rate * 100) - breakeven_wr

        loss_rate = losses / total if total > 0 else 0.0
        expectancy = (win_rate * avg_win) - (loss_rate * avg_loss)

        largest_win = max((t.net_pnl for t in wins_list), default=0.0)
        largest_loss = min((t.net_pnl for t in losses_list), default=0.0)

        return {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": _safe(win_rate * 100, 1),
            "profit_factor": _safe(profit_factor, 3),
            "total_net_pnl": _safe(total_net, 4),
            "total_gross_pnl": _safe(total_gross, 4),
            "total_fees": _safe(total_fees, 4),
            "fee_drag_pct": _safe(fee_drag, 1),
            "avg_win": _safe(avg_win, 4),
            "avg_loss": _safe(avg_loss, 4),
            "rr_ratio": _safe(rr_ratio, 3),
            "breakeven_wr": _safe(breakeven_wr, 1),
            "edge_pp": _safe(edge_pp, 1),
            "expectancy": _safe(expectancy, 4),
            "largest_win": _safe(largest_win, 4),
            "largest_loss": _safe(largest_loss, 4),
        }

    def _compute_risk_metrics(self, trades: List[BinanceTrade]) -> Dict:
        """Sharpe, Sortino, Calmar, max drawdown, streaks."""
        returns = [t.net_pnl for t in trades]

        if len(returns) < 2:
            return {
                "sharpe_per_trade": 0, "sortino_per_trade": 0,
                "calmar_ratio": 0, "max_drawdown": 0,
                "max_drawdown_trades": 0,
                "current_streak": 0, "max_win_streak": 0, "max_loss_streak": 0,
            }

        mean_ret = statistics.mean(returns)
        std_ret = statistics.stdev(returns)
        sharpe = mean_ret / std_ret if std_ret > 0 else 0.0

        neg_returns = [r for r in returns if r < 0]
        downside_dev = statistics.stdev(neg_returns) if len(neg_returns) > 1 else 0.0
        sortino = mean_ret / downside_dev if downside_dev > 0 else 0.0

        # Max drawdown (dollar-based)
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        dd_start = dd_end = 0
        current_dd_start = 0
        for i, r in enumerate(returns):
            equity += r
            if equity > peak:
                peak = equity
                current_dd_start = i
            dd = peak - equity
            if dd > max_dd:
                max_dd = dd
                dd_start = current_dd_start
                dd_end = i

        calmar = mean_ret * len(returns) / max_dd if max_dd > 0 else 0.0

        # Streaks
        current_streak = 0
        max_wins = max_losses = temp_wins = temp_losses = 0
        for t in trades:
            if t.is_win:
                temp_wins += 1
                temp_losses = 0
                max_wins = max(max_wins, temp_wins)
            elif t.is_loss:
                temp_losses += 1
                temp_wins = 0
                max_losses = max(max_losses, temp_losses)
            else:
                temp_wins = temp_losses = 0

        last = trades[-1] if trades else None
        if last:
            current_streak = temp_wins if last.is_win else (-temp_losses if last.is_loss else 0)

        return {
            "sharpe_per_trade": _safe(sharpe, 4),
            "sortino_per_trade": _safe(sortino, 4),
            "calmar_ratio": _safe(calmar, 4),
            "max_drawdown": _safe(max_dd, 4),
            "max_drawdown_trades": dd_end - dd_start if max_dd > 0 else 0,
            "current_streak": current_streak,
            "max_win_streak": max_wins,
            "max_loss_streak": max_losses,
        }

    def _compute_equity_curve(self, trades: List[BinanceTrade]) -> List[Dict]:
        """Build cumulative equity curve data points."""
        curve = []
        equity = 0.0
        for t in trades:
            equity += t.net_pnl
            curve.append({
                "trade_num": len(curve) + 1,
                "trade_time": t.trade_time,
                "symbol": t.symbol,
                "net_pnl": _safe(t.net_pnl, 4),
                "cumulative_pnl": _safe(equity, 4),
                "result": t.result,
            })
        return curve

    def _compute_significance(self, trades: List[BinanceTrade]) -> Dict:
        """
        Z-test for statistical significance of win rate edge.

        H0: True win rate = breakeven win rate (system has no edge)
        H1: True win rate > breakeven win rate (system has positive edge)
        """
        total = len(trades)
        if total < 10:
            return {
                "p_value": 1.0, "z_score": 0.0,
                "is_significant": False,
                "trades_needed": 200,
                "message": "Need at least 10 trades"
            }

        wins = sum(1 for t in trades if t.is_win)
        win_rate = wins / total

        # Compute breakeven WR from R:R
        wins_list = [t for t in trades if t.is_win]
        losses_list = [t for t in trades if t.is_loss]
        avg_win = sum(t.net_pnl for t in wins_list) / len(wins_list) if wins_list else 0
        avg_loss = abs(sum(t.net_pnl for t in losses_list) / len(losses_list)) if losses_list else 0
        rr = avg_win / avg_loss if avg_loss > 0 else 1.0
        p0 = 1 / (1 + rr)  # Breakeven WR

        # One-proportion Z-test
        se = math.sqrt(p0 * (1 - p0) / total) if p0 > 0 and p0 < 1 else 0.001
        z_score = (win_rate - p0) / se if se > 0 else 0.0

        # One-tailed p-value approximation
        p_value = self._normal_cdf(-z_score)

        # Estimate trades needed for significance at current edge
        edge = win_rate - p0
        if edge > 0:
            # n = (z_alpha * se / edge)^2 approximation
            trades_needed = int((1.645 ** 2 * p0 * (1 - p0)) / (edge ** 2)) if edge > 0.001 else 9999
        else:
            trades_needed = 9999

        return {
            "p_value": _safe(p_value, 4),
            "z_score": _safe(z_score, 3),
            "is_significant": p_value < 0.05,
            "observed_wr": _safe(win_rate * 100, 1),
            "breakeven_wr": _safe(p0 * 100, 1),
            "edge_pp": _safe(edge * 100, 1),
            "trades_needed": min(trades_needed, 9999),
            "message": (
                f"Edge {'IS' if p_value < 0.05 else 'NOT'} significant (p={p_value:.3f}). "
                f"Need ~{min(trades_needed, 9999)} trades at current edge."
            )
        }

    def _compute_rolling_metrics(self, trades: List[BinanceTrade],
                                  window: int = 20) -> Dict:
        """Rolling win rate and PnL over last N trades."""
        if len(trades) < window:
            return {"window": window, "points": []}

        points = []
        for i in range(window, len(trades) + 1):
            batch = trades[i - window:i]
            batch_wins = sum(1 for t in batch if t.is_win)
            batch_pnl = sum(t.net_pnl for t in batch)
            points.append({
                "trade_num": i,
                "rolling_wr": _safe(batch_wins / window * 100, 1),
                "rolling_pnl": _safe(batch_pnl, 4),
            })

        return {"window": window, "points": points}

    def _compute_daily_breakdown(self, trades: List[BinanceTrade]) -> List[Dict]:
        """PnL breakdown by day (UTC+7)."""
        daily = defaultdict(lambda: {"trades": 0, "wins": 0, "net_pnl": 0.0})

        for t in trades:
            dt = datetime.fromtimestamp(t.trade_time / 1000, tz=UTC7)
            day = dt.strftime('%Y-%m-%d')
            daily[day]["trades"] += 1
            if t.is_win:
                daily[day]["wins"] += 1
            daily[day]["net_pnl"] += t.net_pnl

        result = []
        for day in sorted(daily.keys()):
            d = daily[day]
            wr = d["wins"] / d["trades"] * 100 if d["trades"] > 0 else 0
            result.append({
                "date": day,
                "trades": d["trades"],
                "wins": d["wins"],
                "losses": d["trades"] - d["wins"],
                "win_rate": _safe(wr, 1),
                "net_pnl": _safe(d["net_pnl"], 4),
            })
        return result

    def get_today_metrics(self) -> Dict:
        """Quick metrics for today (UTC+7)."""
        today = datetime.now(UTC7).strftime('%Y-%m-%d')
        trades = self.repo.get_trades_for_day(today)

        if not trades:
            return {"date": today, "trades": 0, "wins": 0, "losses": 0,
                    "win_rate": 0, "net_pnl": 0}

        wins = sum(1 for t in trades if t.is_win)
        losses = sum(1 for t in trades if t.is_loss)
        net = sum(t.net_pnl for t in trades)

        return {
            "date": today,
            "trades": len(trades),
            "wins": wins,
            "losses": losses,
            "win_rate": _safe(wins / len(trades) * 100, 1),
            "net_pnl": _safe(net, 4),
        }

    def save_daily_snapshot(self, version_tag: str = "") -> Dict:
        """Compute and save today's snapshot."""
        all_trades = self.repo.get_all_trades()
        today_str = datetime.now(UTC7).strftime('%Y-%m-%d')
        today_trades = self.repo.get_trades_for_day(today_str)

        if not all_trades:
            return {}

        core = self._compute_core_metrics(all_trades)
        risk = self._compute_risk_metrics(all_trades)
        sig = self._compute_significance(all_trades)

        day_wins = sum(1 for t in today_trades if t.is_win) if today_trades else 0
        day_count = len(today_trades) if today_trades else 0
        day_pnl = sum(t.net_pnl for t in today_trades) if today_trades else 0
        day_wr = (day_wins / day_count * 100) if day_count > 0 else 0

        snapshot = {
            "snapshot_date": today_str,
            "total_trades": core["total_trades"],
            "win_rate": core["win_rate"],
            "profit_factor": core["profit_factor"],
            "total_net_pnl": core["total_net_pnl"],
            "rr_ratio": core["rr_ratio"],
            "edge_pp": core["edge_pp"],
            "sharpe_per_trade": risk["sharpe_per_trade"],
            "max_drawdown": risk["max_drawdown"],
            "day_trades": day_count,
            "day_net_pnl": _safe(day_pnl, 4),
            "day_win_rate": _safe(day_wr, 1),
            "p_value": sig["p_value"],
            "version_tag": version_tag,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        self.repo.save_snapshot(snapshot)
        self.logger.info(f"📊 Analytics snapshot saved for {today_str}")
        return snapshot

    def _empty_report(self) -> Dict:
        return {
            "total_trades": 0, "wins": 0, "losses": 0,
            "win_rate": 0, "profit_factor": 0,
            "total_net_pnl": 0, "total_gross_pnl": 0, "total_fees": 0,
            "fee_drag_pct": 0, "avg_win": 0, "avg_loss": 0,
            "rr_ratio": 0, "breakeven_wr": 0, "edge_pp": 0,
            "expectancy": 0, "largest_win": 0, "largest_loss": 0,
            "risk_metrics": {}, "equity_curve": [],
            "significance": {"p_value": 1.0, "is_significant": False},
            "rolling": {"window": 20, "points": []},
            "daily_breakdown": [],
            "version_tag": "all", "days_filter": None,
            "generated_at": datetime.now(UTC7).isoformat(),
        }

    @staticmethod
    def _normal_cdf(x: float) -> float:
        """Approximation of standard normal CDF (no scipy needed)."""
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _safe(val: float, decimals: int = 2) -> float:
    """Sanitize float for JSON (no Inf/NaN)."""
    if val is None or math.isinf(val) or math.isnan(val):
        return 0.0
    return round(val, decimals)
