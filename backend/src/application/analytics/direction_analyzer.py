"""
DirectionAnalyzer — Application Layer

Analyzes LONG vs SHORT performance split.
Identifies directional bias and recommends adjustments.

v6.3.0: Institutional Analytics System
"""

import logging
from typing import List, Dict, Optional

from ...domain.entities.binance_trade import BinanceTrade
from ...infrastructure.persistence.analytics_repository import AnalyticsRepository


class DirectionAnalyzer:
    """
    LONG vs SHORT performance analyzer.

    Computes WR, PnL, R:R split by direction.
    """

    def __init__(self, analytics_repo: AnalyticsRepository):
        self.repo = analytics_repo
        self.logger = logging.getLogger(__name__)

    def get_direction_split(self, version_tag: Optional[str] = None) -> Dict:
        """Full LONG vs SHORT analysis."""
        trades = self.repo.get_all_trades(version_tag=version_tag)
        if not trades:
            return {"long": self._empty_direction(), "short": self._empty_direction(),
                    "recommendation": "Insufficient data"}

        longs = [t for t in trades if t.direction == "LONG"]
        shorts = [t for t in trades if t.direction == "SHORT"]

        long_stats = self._compute_direction_stats(longs, "LONG")
        short_stats = self._compute_direction_stats(shorts, "SHORT")

        # Recommendation
        rec = self._generate_recommendation(long_stats, short_stats)

        return {
            "long": long_stats,
            "short": short_stats,
            "total_trades": len(trades),
            "long_pct": round(len(longs) / len(trades) * 100, 1) if trades else 0,
            "short_pct": round(len(shorts) / len(trades) * 100, 1) if trades else 0,
            "recommendation": rec,
        }

    def _compute_direction_stats(self, trades: List[BinanceTrade], direction: str) -> Dict:
        if not trades:
            return self._empty_direction(direction)

        count = len(trades)
        wins = sum(1 for t in trades if t.is_win)
        losses = count - wins
        wr = wins / count * 100 if count > 0 else 0
        net_pnl = sum(t.net_pnl for t in trades)

        wins_list = [t for t in trades if t.is_win]
        losses_list = [t for t in trades if t.is_loss]
        avg_win = sum(t.net_pnl for t in wins_list) / len(wins_list) if wins_list else 0
        avg_loss = abs(sum(t.net_pnl for t in losses_list) / len(losses_list)) if losses_list else 0
        rr = avg_win / avg_loss if avg_loss > 0 else 0

        return {
            "direction": direction,
            "trades": count,
            "wins": wins,
            "losses": losses,
            "win_rate": round(wr, 1),
            "net_pnl": round(net_pnl, 4),
            "avg_win": round(avg_win, 4),
            "avg_loss": round(avg_loss, 4),
            "rr_ratio": round(rr, 3),
        }

    def _generate_recommendation(self, long_stats: Dict, short_stats: Dict) -> str:
        long_wr = long_stats["win_rate"]
        short_wr = short_stats["win_rate"]
        long_pnl = long_stats["net_pnl"]
        short_pnl = short_stats["net_pnl"]

        if long_stats["trades"] < 5 or short_stats["trades"] < 5:
            return "Insufficient data for directional recommendation"

        if long_wr > short_wr + 10 and long_pnl > short_pnl + 0.5:
            return f"LONG bias dominant (+{long_wr - short_wr:.0f}pp WR edge). Consider reducing SHORT exposure."
        elif short_wr > long_wr + 10 and short_pnl > long_pnl + 0.5:
            return f"SHORT bias dominant (+{short_wr - long_wr:.0f}pp WR edge). Consider reducing LONG exposure."
        elif abs(long_wr - short_wr) < 5:
            return "Balanced directional performance. No adjustment needed."
        else:
            better = "LONG" if long_pnl > short_pnl else "SHORT"
            return f"Slight {better} edge. Monitor with more data."

    @staticmethod
    def _empty_direction(direction: str = "") -> Dict:
        return {
            "direction": direction, "trades": 0, "wins": 0, "losses": 0,
            "win_rate": 0, "net_pnl": 0, "avg_win": 0, "avg_loss": 0,
            "rr_ratio": 0,
        }
