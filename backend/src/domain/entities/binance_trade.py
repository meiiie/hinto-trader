"""
BinanceTrade Entity — Domain Layer

Represents a single closed trade from Binance API (source of truth).
Groups fills by orderId and computes net PnL = realizedPnl - commission.

v6.3.0: Institutional Analytics System
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BinanceTrade:
    """
    A closed trade derived from Binance /fapi/v1/userTrades.

    Each instance represents ONE close order (may have multiple fills).
    PnL is computed from Binance API data, NOT from LocalPosition.
    """
    order_id: str
    trade_time: int                     # Unix ms from Binance
    symbol: str
    close_side: str                     # BUY or SELL (the closing side)
    direction: str                      # LONG or SHORT (inferred from close_side)
    gross_pnl: float                    # Sum of realizedPnl from fills
    commission: float                   # Sum of commission from fills
    net_pnl: float                      # gross_pnl - commission
    result: str                         # WIN or LOSS
    session_hour: int = 0               # UTC+7 hour (0-23)
    session_slot: str = ""              # "HH:MM" 30-min bucket
    version_tag: str = ""               # e.g. "v6.2.0"
    exit_reason: str = ""               # SL_HIT, TP_HIT, AUTO_CLOSE, etc.
    hold_duration_minutes: float = 0.0  # From entry to exit
    collected_at: str = ""              # ISO timestamp when collected

    @property
    def is_win(self) -> bool:
        return self.net_pnl > 0

    @property
    def is_loss(self) -> bool:
        return self.net_pnl < 0

    def to_dict(self) -> dict:
        return {
            'order_id': self.order_id,
            'trade_time': self.trade_time,
            'symbol': self.symbol,
            'close_side': self.close_side,
            'direction': self.direction,
            'gross_pnl': round(self.gross_pnl, 4),
            'commission': round(self.commission, 4),
            'net_pnl': round(self.net_pnl, 4),
            'result': self.result,
            'session_hour': self.session_hour,
            'session_slot': self.session_slot,
            'version_tag': self.version_tag,
            'exit_reason': self.exit_reason,
            'hold_duration_minutes': round(self.hold_duration_minutes, 1),
            'collected_at': self.collected_at,
        }

    @classmethod
    def from_db_row(cls, row) -> 'BinanceTrade':
        """Create from sqlite3.Row or dict."""
        return cls(
            order_id=str(row['order_id']),
            trade_time=int(row['trade_time']),
            symbol=str(row['symbol']),
            close_side=str(row['close_side']),
            direction=str(row['direction']),
            gross_pnl=float(row['gross_pnl']),
            commission=float(row['commission']),
            net_pnl=float(row['net_pnl']),
            result=str(row['result']),
            session_hour=int(row['session_hour'] or 0),
            session_slot=str(row['session_slot'] or ''),
            version_tag=str(row['version_tag'] or ''),
            exit_reason=str(row['exit_reason'] or ''),
            hold_duration_minutes=float(row['hold_duration_minutes'] or 0),
            collected_at=str(row['collected_at'] or ''),
        )
