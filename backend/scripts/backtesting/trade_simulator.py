"""
Trade Simulator for Backtesting

Simulates trade execution based on signals and tracks P&L.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Dict
from enum import Enum
import logging

from src.domain.entities.candle import Candle
from src.domain.entities.enhanced_signal import EnhancedSignal
from src.application.signals.signal_generator import TradingSignal

logger = logging.getLogger(__name__)


class ExitReason(Enum):
    """Trade exit reasons"""
    TP1 = "TP1"
    TP2 = "TP2"
    TP3 = "TP3"
    STOP_LOSS = "STOP_LOSS"
    TIMEOUT = "TIMEOUT"


@dataclass
class Trade:
    """Represents a single trade"""
    entry_time: datetime
    entry_price: float
    direction: str  # 'BUY' or 'SELL'
    position_size: float
    stop_loss: float
    tp1: float
    tp2: float
    tp3: float

    # Exit info (filled when trade closes)
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[ExitReason] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None

    def is_open(self) -> bool:
        """Check if trade is still open"""
        return self.exit_time is None

    def calculate_pnl(self) -> float:
        """Calculate P&L for closed trade"""
        if not self.exit_price:
            return 0.0

        if self.direction == 'BUY':
            pnl = (self.exit_price - self.entry_price) * self.position_size
        else:  # SELL
            pnl = (self.entry_price - self.exit_price) * self.position_size

        return pnl


class TradeSimulator:
    """Simulate trade execution and track performance"""

    def __init__(
        self,
        initial_capital: float = 10000.0,
        max_hold_time: timedelta = timedelta(hours=24)
    ):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.max_hold_time = max_hold_time

        self.trades: List[Trade] = []
        self.open_trades: List[Trade] = []
        self.equity_curve: List[float] = [initial_capital]

    def execute_signal(
        self,
        signal: TradingSignal,
        candles: List[Candle]
    ) -> Optional[Trade]:
        """
        Execute trade based on signal

        Args:
            signal: Enhanced trading signal
            candles: Historical candles for execution

        Returns:
            Trade object if executed, None otherwise
        """
        # Don't open new trade if already have open position
        if self.open_trades:
            logger.debug("Skipping signal - already have open position")
            return None

        # Handle different signal types (EnhancedSignal vs TradingSignal)
        if hasattr(signal, 'take_profit') and hasattr(signal.take_profit, 'tp1'):
            # EnhancedSignal
            tp1 = signal.take_profit.tp1
            tp2 = signal.take_profit.tp2
            tp3 = signal.take_profit.tp3
            direction = signal.direction
        else:
            # TradingSignal
            tp_levels = signal.tp_levels or {}
            tp1 = tp_levels.get('tp1', 0.0)
            tp2 = tp_levels.get('tp2', 0.0)
            tp3 = tp_levels.get('tp3', 0.0)
            direction = signal.signal_type.value.upper()

        # Create trade
        trade = Trade(
            entry_time=signal.timestamp,
            entry_price=signal.entry_price,
            direction=direction,
            position_size=signal.position_size or 0.0,
            stop_loss=signal.stop_loss,
            tp1=tp1,
            tp2=tp2,
            tp3=tp3
        )

        self.trades.append(trade)
        self.open_trades.append(trade)

        logger.info(
            f"Opened {trade.direction} trade at {trade.entry_price} "
            f"(size: {trade.position_size:.4f})"
        )

        return trade

    def update_trades(self, current_candle: Candle) -> None:
        """
        Update open trades and check exit conditions

        Args:
            current_candle: Current candle for price checking
        """
        for trade in self.open_trades[:]:  # Copy list to allow removal
            exit_reason = self._check_exit_conditions(trade, current_candle)

            if exit_reason:
                self._close_trade(trade, current_candle, exit_reason)

    def _check_exit_conditions(
        self,
        trade: Trade,
        candle: Candle
    ) -> Optional[ExitReason]:
        """
        Check if any exit condition is met

        Returns:
            ExitReason if should exit, None otherwise
        """
        # Check timeout
        if candle.timestamp - trade.entry_time > self.max_hold_time:
            return ExitReason.TIMEOUT

        if trade.direction == 'BUY':
            # Check stop loss
            if candle.low <= trade.stop_loss:
                return ExitReason.STOP_LOSS

            # Check take profits (in order)
            if candle.high >= trade.tp3:
                return ExitReason.TP3
            elif candle.high >= trade.tp2:
                return ExitReason.TP2
            elif candle.high >= trade.tp1:
                return ExitReason.TP1

        else:  # SELL
            # Check stop loss
            if candle.high >= trade.stop_loss:
                return ExitReason.STOP_LOSS

            # Check take profits (in order)
            if candle.low <= trade.tp3:
                return ExitReason.TP3
            elif candle.low <= trade.tp2:
                return ExitReason.TP2
            elif candle.low <= trade.tp1:
                return ExitReason.TP1

        return None

    def _close_trade(
        self,
        trade: Trade,
        candle: Candle,
        exit_reason: ExitReason
    ) -> None:
        """Close trade and update capital"""
        # Determine exit price based on reason
        if exit_reason == ExitReason.STOP_LOSS:
            exit_price = trade.stop_loss
        elif exit_reason == ExitReason.TP1:
            exit_price = trade.tp1
        elif exit_reason == ExitReason.TP2:
            exit_price = trade.tp2
        elif exit_reason == ExitReason.TP3:
            exit_price = trade.tp3
        else:  # TIMEOUT
            exit_price = candle.close

        # Update trade
        trade.exit_time = candle.timestamp
        trade.exit_price = exit_price
        trade.exit_reason = exit_reason
        trade.pnl = trade.calculate_pnl()
        trade.pnl_pct = (trade.pnl / (trade.entry_price * trade.position_size)) * 100

        # Update capital
        self.capital += trade.pnl
        self.equity_curve.append(self.capital)

        # Remove from open trades
        self.open_trades.remove(trade)

        logger.info(
            f"Closed {trade.direction} trade at {exit_price} "
            f"({exit_reason.value}): P&L ${trade.pnl:.2f} ({trade.pnl_pct:.2f}%)"
        )

    def get_summary(self) -> Dict:
        """Get trading summary"""
        closed_trades = [t for t in self.trades if not t.is_open()]

        return {
            'total_trades': len(closed_trades),
            'open_trades': len(self.open_trades),
            'initial_capital': self.initial_capital,
            'final_capital': self.capital,
            'total_pnl': self.capital - self.initial_capital,
            'total_pnl_pct': ((self.capital - self.initial_capital) / self.initial_capital) * 100
        }
