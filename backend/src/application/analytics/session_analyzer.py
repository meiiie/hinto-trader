"""
SessionAnalyzer — Application Layer

Analyzes trading performance by time session (UTC+7).
Generates 30-min heatmap, dead zone effectiveness, and DZ recommendations.

v6.3.0: Institutional Analytics System
"""

import logging
from typing import List, Dict, Optional
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from ...domain.entities.binance_trade import BinanceTrade
from ...infrastructure.persistence.analytics_repository import AnalyticsRepository

UTC7 = timezone(timedelta(hours=7))

# Current dead zones (UTC+7)
DEAD_ZONES = [
    (9, 0, 13, 0),      # 09:00-13:00
    (19, 0, 21, 30),     # 19:00-21:30
    (22, 0, 23, 30),     # 22:00-23:30
]


class SessionAnalyzer:
    """
    Session performance analyzer.

    Produces:
    - 30-min slot heatmap (WR, PnL, count)
    - Hourly breakdown
    - Dead zone effectiveness (blocked vs would-have-traded)
    - DZ recommendations based on data
    """

    def __init__(self, analytics_repo: AnalyticsRepository):
        self.repo = analytics_repo
        self.logger = logging.getLogger(__name__)

    def get_session_heatmap(self, version_tag: Optional[str] = None) -> Dict:
        """
        Generate 30-min session heatmap.

        Returns dict with slots, hourly summary, and DZ analysis.
        """
        trades = self.repo.get_all_trades(version_tag=version_tag)
        if not trades:
            return {"slots": [], "hourly": [], "dead_zone_analysis": {}}

        # 30-min slot aggregation
        slots = defaultdict(lambda: {"count": 0, "wins": 0, "net_pnl": 0.0})
        hourly = defaultdict(lambda: {"count": 0, "wins": 0, "net_pnl": 0.0})

        for t in trades:
            slot = t.session_slot or self._compute_slot(t.trade_time)
            hour = t.session_hour

            slots[slot]["count"] += 1
            if t.is_win:
                slots[slot]["wins"] += 1
            slots[slot]["net_pnl"] += t.net_pnl

            hourly[hour]["count"] += 1
            if t.is_win:
                hourly[hour]["wins"] += 1
            hourly[hour]["net_pnl"] += t.net_pnl

        # Format slots
        slot_list = []
        for slot_key in sorted(slots.keys()):
            s = slots[slot_key]
            wr = s["wins"] / s["count"] * 100 if s["count"] > 0 else 0
            slot_list.append({
                "slot": slot_key,
                "trades": s["count"],
                "wins": s["wins"],
                "losses": s["count"] - s["wins"],
                "win_rate": round(wr, 1),
                "net_pnl": round(s["net_pnl"], 4),
            })

        # Format hourly
        hourly_list = []
        for h in range(24):
            d = hourly.get(h, {"count": 0, "wins": 0, "net_pnl": 0.0})
            wr = d["wins"] / d["count"] * 100 if d["count"] > 0 else 0
            in_dz = self._is_in_dead_zone(h, 0)
            hourly_list.append({
                "hour": h,
                "label": f"{h:02d}:00",
                "trades": d["count"],
                "wins": d["wins"],
                "losses": d["count"] - d["wins"],
                "win_rate": round(wr, 1),
                "net_pnl": round(d["net_pnl"], 4),
                "in_dead_zone": in_dz,
            })

        # DZ effectiveness
        dz_analysis = self._analyze_dead_zones(trades, hourly)

        return {
            "slots": slot_list,
            "hourly": hourly_list,
            "dead_zone_analysis": dz_analysis,
            "total_trades": len(trades),
        }

    def _analyze_dead_zones(self, trades: List[BinanceTrade], hourly: Dict) -> Dict:
        """Analyze effectiveness of current dead zones."""
        # Separate trades into DZ vs non-DZ
        dz_trades = []
        non_dz_trades = []

        for t in trades:
            dt = datetime.fromtimestamp(t.trade_time / 1000, tz=UTC7)
            if self._is_in_dead_zone(dt.hour, dt.minute):
                dz_trades.append(t)
            else:
                non_dz_trades.append(t)

        # Non-DZ metrics
        non_dz_wins = sum(1 for t in non_dz_trades if t.is_win)
        non_dz_wr = non_dz_wins / len(non_dz_trades) * 100 if non_dz_trades else 0
        non_dz_pnl = sum(t.net_pnl for t in non_dz_trades)

        # DZ trades (would-have-been-blocked if DZ was active at trade time)
        dz_wins = sum(1 for t in dz_trades if t.is_win)
        dz_wr = dz_wins / len(dz_trades) * 100 if dz_trades else 0
        dz_pnl = sum(t.net_pnl for t in dz_trades)

        # Find toxic hours (negative PnL, low WR)
        toxic_hours = []
        gold_hours = []
        for h in range(24):
            d = hourly.get(h, {"count": 0, "wins": 0, "net_pnl": 0.0})
            if d["count"] >= 3:  # Minimum sample
                wr = d["wins"] / d["count"] * 100
                if wr < 45 and d["net_pnl"] < 0:
                    toxic_hours.append({
                        "hour": h, "trades": d["count"],
                        "win_rate": round(wr, 1), "net_pnl": round(d["net_pnl"], 4),
                    })
                elif wr > 65 and d["net_pnl"] > 0:
                    gold_hours.append({
                        "hour": h, "trades": d["count"],
                        "win_rate": round(wr, 1), "net_pnl": round(d["net_pnl"], 4),
                    })

        return {
            "current_dead_zones": [
                f"{dz[0]:02d}:{dz[1]:02d}-{dz[2]:02d}:{dz[3]:02d}" for dz in DEAD_ZONES
            ],
            "non_dz_trades": len(non_dz_trades),
            "non_dz_win_rate": round(non_dz_wr, 1),
            "non_dz_pnl": round(non_dz_pnl, 4),
            "dz_trades_would_block": len(dz_trades),
            "dz_would_block_wr": round(dz_wr, 1),
            "dz_would_block_pnl": round(dz_pnl, 4),
            "dz_pnl_saved": round(-dz_pnl, 4) if dz_pnl < 0 else 0,
            "toxic_hours": toxic_hours,
            "gold_hours": gold_hours,
        }

    def _compute_slot(self, trade_time_ms: int) -> str:
        """Compute 30-min slot from trade timestamp."""
        dt = datetime.fromtimestamp(trade_time_ms / 1000, tz=UTC7)
        bucket = (dt.minute // 30) * 30
        return f"{dt.hour:02d}:{bucket:02d}"

    @staticmethod
    def _is_in_dead_zone(hour: int, minute: int) -> bool:
        """Check if a time falls within any dead zone."""
        time_mins = hour * 60 + minute
        for dz in DEAD_ZONES:
            start_mins = dz[0] * 60 + dz[1]
            end_mins = dz[2] * 60 + dz[3]
            if start_mins <= time_mins < end_mins:
                return True
        return False
