"""
Performance Analyzer for Backtesting

Calculates comprehensive performance metrics from backtest results.
"""

from dataclasses import dataclass
from typing import List
import logging
import numpy as np

from scripts.backtesting.trade_simulator import Trade, ExitReason

logger = logging.getLogger(__name__)


@dataclass
class BacktestResults:
    """Comprehensive backtest performance metrics"""
    # Trade statistics
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float

    # P&L metrics
    total_pnl: float
    total_pnl_pct: float
    avg_win: float
    avg_loss: float
    avg_pnl: float

    # Risk metrics
    avg_rr_ratio: float
    max_drawdown: float
    max_drawdown_pct: float
    sharpe_ratio: float
    profit_factor: float

    # Exit breakdown
    tp1_count: int
    tp2_count: int
    tp3_count: int
    sl_count: int
    timeout_count: int

    # Raw data
    trades: List[Trade]
    equity_curve: List[float]


class PerformanceAnalyzer:
    """Analyze backtest performance and calculate metrics"""

    def analyze(
        self,
        trades: List[Trade],
        equity_curve: List[float],
        initial_capital: float
    ) -> BacktestResults:
        """
        Calculate all performance metrics

        Args:
            trades: List of closed trades
            equity_curve: Equity curve over time
            initial_capital: Starting capital

        Returns:
            BacktestResults with all metrics
        """
        logger.info(f"Analyzing {len(trades)} trades")

        # Filter closed trades only
        closed_trades = [t for t in trades if not t.is_open()]

        if not closed_trades:
            logger.warning("No closed trades to analyze")
            return self._empty_results(trades, equity_curve)

        # Calculate metrics
        win_rate = self.calculate_win_rate(closed_trades)
        avg_win, avg_loss = self.calculate_avg_win_loss(closed_trades)
        avg_rr = self.calculate_avg_rr(closed_trades)
        max_dd, max_dd_pct = self.calculate_max_drawdown(equity_curve, initial_capital)
        sharpe = self.calculate_sharpe_ratio(equity_curve, initial_capital)
        profit_factor = self.calculate_profit_factor(closed_trades)

        # Exit breakdown
        exit_counts = self._count_exit_reasons(closed_trades)

        # Total P&L
        total_pnl = sum(t.pnl for t in closed_trades)
        total_pnl_pct = (total_pnl / initial_capital) * 100

        # Average P&L
        avg_pnl = total_pnl / len(closed_trades) if closed_trades else 0

        results = BacktestResults(
            total_trades=len(closed_trades),
            winning_trades=len([t for t in closed_trades if t.pnl > 0]),
            losing_trades=len([t for t in closed_trades if t.pnl <= 0]),
            win_rate=win_rate,
            total_pnl=total_pnl,
            total_pnl_pct=total_pnl_pct,
            avg_win=avg_win,
            avg_loss=avg_loss,
            avg_pnl=avg_pnl,
            avg_rr_ratio=avg_rr,
            max_drawdown=max_dd,
            max_drawdown_pct=max_dd_pct,
            sharpe_ratio=sharpe,
            profit_factor=profit_factor,
            tp1_count=exit_counts['TP1'],
            tp2_count=exit_counts['TP2'],
            tp3_count=exit_counts['TP3'],
            sl_count=exit_counts['STOP_LOSS'],
            timeout_count=exit_counts['TIMEOUT'],
            trades=closed_trades,
            equity_curve=equity_curve
        )

        logger.info(f"Analysis complete: Win rate {win_rate:.1f}%, Sharpe {sharpe:.2f}")
        return results

    def calculate_win_rate(self, trades: List[Trade]) -> float:
        """Calculate win rate percentage"""
        if not trades:
            return 0.0

        winning = len([t for t in trades if t.pnl > 0])
        return (winning / len(trades)) * 100

    def calculate_avg_win_loss(self, trades: List[Trade]) -> tuple[float, float]:
        """Calculate average win and average loss"""
        wins = [t.pnl for t in trades if t.pnl > 0]
        losses = [t.pnl for t in trades if t.pnl <= 0]

        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0

        return avg_win, avg_loss

    def calculate_avg_rr(self, trades: List[Trade]) -> float:
        """Calculate average risk/reward ratio"""
        rr_ratios = []

        for trade in trades:
            if trade.pnl is None:
                continue

            # Calculate risk (entry to stop loss)
            if trade.direction == 'BUY':
                risk = (trade.entry_price - trade.stop_loss) * trade.position_size
            else:
                risk = (trade.stop_loss - trade.entry_price) * trade.position_size

            if risk > 0:
                rr = trade.pnl / risk
                rr_ratios.append(rr)

        return sum(rr_ratios) / len(rr_ratios) if rr_ratios else 0.0

    def calculate_max_drawdown(
        self,
        equity_curve: List[float],
        initial_capital: float
    ) -> tuple[float, float]:
        """
        Calculate maximum drawdown

        Returns:
            (max_drawdown_dollars, max_drawdown_percentage)
        """
        if len(equity_curve) < 2:
            return 0.0, 0.0

        peak = equity_curve[0]
        max_dd = 0.0

        for value in equity_curve:
            if value > peak:
                peak = value

            drawdown = peak - value
            if drawdown > max_dd:
                max_dd = drawdown

        max_dd_pct = (max_dd / initial_capital) * 100 if initial_capital > 0 else 0.0

        return max_dd, max_dd_pct

    def calculate_sharpe_ratio(
        self,
        equity_curve: List[float],
        initial_capital: float,
        risk_free_rate: float = 0.0
    ) -> float:
        """
        Calculate Sharpe ratio

        Sharpe = (avg_return - risk_free_rate) / std_dev_returns
        """
        if len(equity_curve) < 2:
            return 0.0

        # Calculate returns
        returns = []
        for i in range(1, len(equity_curve)):
            ret = (equity_curve[i] - equity_curve[i-1]) / equity_curve[i-1]
            returns.append(ret)

        if not returns:
            return 0.0

        avg_return = np.mean(returns)
        std_return = np.std(returns)

        if std_return == 0:
            return 0.0

        sharpe = (avg_return - risk_free_rate) / std_return

        # Annualize (assuming daily returns)
        sharpe_annualized = sharpe * np.sqrt(252)

        return sharpe_annualized

    def calculate_profit_factor(self, trades: List[Trade]) -> float:
        """
        Calculate profit factor

        Profit Factor = Gross Profit / Gross Loss
        """
        gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in trades if t.pnl <= 0))

        if gross_loss == 0:
            return float('inf') if gross_profit > 0 else 0.0

        return gross_profit / gross_loss

    def _count_exit_reasons(self, trades: List[Trade]) -> dict:
        """Count trades by exit reason"""
        counts = {
            'TP1': 0,
            'TP2': 0,
            'TP3': 0,
            'STOP_LOSS': 0,
            'TIMEOUT': 0
        }

        for trade in trades:
            if trade.exit_reason:
                counts[trade.exit_reason.value] += 1

        return counts

    def _empty_results(
        self,
        trades: List[Trade],
        equity_curve: List[float]
    ) -> BacktestResults:
        """Return empty results when no trades"""
        return BacktestResults(
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0.0,
            total_pnl=0.0,
            total_pnl_pct=0.0,
            avg_win=0.0,
            avg_loss=0.0,
            avg_pnl=0.0,
            avg_rr_ratio=0.0,
            max_drawdown=0.0,
            max_drawdown_pct=0.0,
            sharpe_ratio=0.0,
            profit_factor=0.0,
            tp1_count=0,
            tp2_count=0,
            tp3_count=0,
            sl_count=0,
            timeout_count=0,
            trades=trades,
            equity_curve=equity_curve
        )
