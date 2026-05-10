from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class PaperOrder:
    """Represents a paper trading order"""
    id: str
    symbol: str
    side: str  # 'BUY' or 'SELL'
    status: str  # 'PENDING', 'FILLED', 'CLOSED', 'CANCELLED'
    entry_price: float
    quantity: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    entry_time: datetime
    close_time: Optional[datetime] = None
    pnl: float = 0.0
    exit_reason: Optional[str] = None  # 'TP', 'SL', 'TIMEOUT'
