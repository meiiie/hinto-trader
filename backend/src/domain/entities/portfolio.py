"""
Portfolio Entity - Domain Layer

Represents the paper trading portfolio state.
"""

from dataclasses import dataclass, field
from typing import List
from .paper_position import PaperPosition


@dataclass
class Portfolio:
    """
    Represents the current state of a paper trading portfolio.

    Attributes:
        balance: Wallet balance (deposited + realized PnL)
        equity: Total equity (balance + unrealized PnL)
        unrealized_pnl: Total unrealized PnL from open positions
        realized_pnl: Total realized PnL from closed trades
        open_positions: List of currently open positions
    """
    balance: float
    equity: float
    unrealized_pnl: float
    realized_pnl: float
    open_positions: List[PaperPosition] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for API response"""
        return {
            'balance': self.balance,
            'equity': self.equity,
            'unrealized_pnl': self.unrealized_pnl,
            'realized_pnl': self.realized_pnl,
            'open_positions_count': len(self.open_positions),
            'open_positions': [
                {
                    'id': pos.id,
                    'symbol': pos.symbol,
                    'side': pos.side,
                    'entry_price': pos.entry_price,
                    'quantity': pos.quantity,
                    'margin': pos.margin,
                    'stop_loss': pos.stop_loss,
                    'take_profit': pos.take_profit,
                    'open_time': pos.open_time.isoformat() if pos.open_time else None
                }
                for pos in self.open_positions
            ]
        }
