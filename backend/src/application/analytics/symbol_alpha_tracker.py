"""
SymbolAlphaTracker — Application Layer

Classifies symbols into ALPHA+, NEUTRAL, TOXIC based on historical performance.
Uses Binance truth data for per-symbol PnL decomposition.

v6.3.0: Institutional Analytics System
"""

import logging
from typing import List, Dict, Optional
from collections import defaultdict

from ...domain.entities.binance_trade import BinanceTrade
from ...infrastructure.persistence.analytics_repository import AnalyticsRepository


# Classification thresholds
ALPHA_MIN_TRADES = 2
ALPHA_PNL_THRESHOLD = 0.5    # Net PnL > $0.50 = ALPHA+
TOXIC_PNL_THRESHOLD = -0.5   # Net PnL < -$0.50 = TOXIC


class SymbolAlphaTracker:
    """
    Per-symbol performance classifier.

    Categories:
    - ALPHA+: Consistently profitable (PnL > threshold, WR > 55%)
    - NEUTRAL: Marginal or insufficient data
    - TOXIC: Consistently losing (PnL < threshold)
    """

    def __init__(self, analytics_repo: AnalyticsRepository):
        self.repo = analytics_repo
        self.logger = logging.getLogger(__name__)

    def get_symbol_decomposition(self, version_tag: Optional[str] = None) -> Dict:
        """
        Full per-symbol alpha decomposition.

        Returns classified symbols with stats.
        """
        trades = self.repo.get_all_trades(version_tag=version_tag)
        if not trades:
            return {"symbols": [], "alpha": [], "neutral": [], "toxic": []}

        # Group by symbol
        by_symbol = defaultdict(list)
        for t in trades:
            by_symbol[t.symbol].append(t)

        symbols = []
        alpha_list = []
        neutral_list = []
        toxic_list = []

        for sym, sym_trades in sorted(by_symbol.items()):
            count = len(sym_trades)
            wins = sum(1 for t in sym_trades if t.is_win)
            losses = count - wins
            wr = wins / count * 100 if count > 0 else 0
            net_pnl = sum(t.net_pnl for t in sym_trades)
            gross_pnl = sum(t.gross_pnl for t in sym_trades)
            fees = sum(t.commission for t in sym_trades)
            avg_pnl = net_pnl / count if count > 0 else 0

            # Direction breakdown
            longs = [t for t in sym_trades if t.direction == "LONG"]
            shorts = [t for t in sym_trades if t.direction == "SHORT"]
            long_wins = sum(1 for t in longs if t.is_win)
            short_wins = sum(1 for t in shorts if t.is_win)
            long_wr = long_wins / len(longs) * 100 if longs else 0
            short_wr = short_wins / len(shorts) * 100 if shorts else 0

            # Classify
            if count >= ALPHA_MIN_TRADES and net_pnl > ALPHA_PNL_THRESHOLD:
                classification = "ALPHA+"
            elif count >= ALPHA_MIN_TRADES and net_pnl < TOXIC_PNL_THRESHOLD:
                classification = "TOXIC"
            else:
                classification = "NEUTRAL"

            entry = {
                "symbol": sym,
                "classification": classification,
                "trades": count,
                "wins": wins,
                "losses": losses,
                "win_rate": round(wr, 1),
                "net_pnl": round(net_pnl, 4),
                "gross_pnl": round(gross_pnl, 4),
                "fees": round(fees, 4),
                "avg_pnl": round(avg_pnl, 4),
                "long_trades": len(longs),
                "long_wr": round(long_wr, 1),
                "short_trades": len(shorts),
                "short_wr": round(short_wr, 1),
            }
            symbols.append(entry)

            if classification == "ALPHA+":
                alpha_list.append(entry)
            elif classification == "TOXIC":
                toxic_list.append(entry)
            else:
                neutral_list.append(entry)

        # Sort by net PnL
        alpha_list.sort(key=lambda x: x["net_pnl"], reverse=True)
        toxic_list.sort(key=lambda x: x["net_pnl"])
        symbols.sort(key=lambda x: x["net_pnl"], reverse=True)

        return {
            "symbols": symbols,
            "alpha": alpha_list,
            "neutral": neutral_list,
            "toxic": toxic_list,
            "summary": {
                "total_symbols": len(symbols),
                "alpha_count": len(alpha_list),
                "neutral_count": len(neutral_list),
                "toxic_count": len(toxic_list),
                "alpha_pnl": round(sum(s["net_pnl"] for s in alpha_list), 4),
                "toxic_pnl": round(sum(s["net_pnl"] for s in toxic_list), 4),
            }
        }
