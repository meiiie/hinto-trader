"""
PerformanceMetrics Entity - Domain Layer

Represents trading performance statistics.

SOTA Professional Metrics (Dec 2025):
- Expectancy: Average $ expected per trade
- Per-Symbol Breakdown: Win rate, PnL, etc. by trading pair
"""

from dataclasses import dataclass, field
from typing import List, Dict, TYPE_CHECKING
from .paper_position import PaperPosition
from collections import defaultdict
import math

if TYPE_CHECKING:
    from .binance_trade import BinanceTrade

def _safe_float(val: float, decimals: int = 2) -> float:
    """SOTA: Sanitize float values for JSON serialization (No Inf/NaN)"""
    if val is None:
        return 0.0
    if math.isinf(val) or math.isnan(val):
        return 0.0  # Or return a high max value like 999.99 if preferred for UI
    return round(val, decimals)


@dataclass
class SymbolStats:
    """Per-symbol trading statistics."""
    symbol: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    profit_factor: float
    long_trades: int = 0
    short_trades: int = 0
    long_win_rate: float = 0.0
    short_win_rate: float = 0.0
    best_side: str = "-"  # 'LONG', 'SHORT', or '-'

    def to_dict(self) -> dict:
        return {
            'symbol': self.symbol.upper(),
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': _safe_float(self.win_rate * 100, 2),
            'total_pnl': _safe_float(self.total_pnl, 2),
            'profit_factor': _safe_float(self.profit_factor, 2),
            'long_trades': self.long_trades,
            'short_trades': self.short_trades,
            'long_win_rate': _safe_float(self.long_win_rate * 100, 1),
            'short_win_rate': _safe_float(self.short_win_rate * 100, 1),
            'best_side': self.best_side
        }


@dataclass
class ExitReasonStats:
    """
    SOTA Phase 24: Exit Reason Analytics for Bot Behavior Monitoring.

    Tracks win rate, avg P&L, and avg duration per exit reason.
    Critical for understanding bot decision quality.
    """
    reason: str  # TAKE_PROFIT, STOP_LOSS, SIGNAL_REVERSAL, MANUAL_CLOSE, MERGED
    count: int
    win_rate: float  # 0.0 - 1.0
    avg_pnl: float
    avg_duration_minutes: float
    total_pnl: float = 0.0

    def to_dict(self) -> dict:
        return {
            'reason': self.reason,
            'count': self.count,
            'win_rate': _safe_float(self.win_rate * 100, 2),
            'avg_pnl': _safe_float(self.avg_pnl, 2),
            'total_pnl': _safe_float(self.total_pnl, 2),
            'avg_duration_minutes': _safe_float(self.avg_duration_minutes, 1)
        }


@dataclass
class RiskMetrics:
    """
    SOTA Phase 24: Risk-Adjusted Performance Metrics.

    Used by professional quant traders to evaluate strategy quality.
    """
    sharpe_ratio: float = 0.0     # Risk-adjusted return (>1 good, >2 excellent)
    sortino_ratio: float = 0.0   # Downside-only risk (higher = better)
    calmar_ratio: float = 0.0    # Annual Return / Max Drawdown
    recovery_factor: float = 0.0 # Net Profit / Max Drawdown

    def to_dict(self) -> dict:
        return {
            'sharpe_ratio': _safe_float(self.sharpe_ratio, 2),
            'sortino_ratio': _safe_float(self.sortino_ratio, 2),
            'calmar_ratio': _safe_float(self.calmar_ratio, 2),
            'recovery_factor': _safe_float(self.recovery_factor, 2)
        }


@dataclass
class StreakStats:
    """
    SOTA Phase 24: Win/Loss Streak Patterns.

    Critical for monitoring bot consistency and detecting tilt/drawdown.
    """
    current_streak: int = 0      # Positive = wins, Negative = losses
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    avg_winner_duration_minutes: float = 0.0
    avg_loser_duration_minutes: float = 0.0

    def to_dict(self) -> dict:
        return {
            'current_streak': self.current_streak,
            'max_consecutive_wins': self.max_consecutive_wins,
            'max_consecutive_losses': self.max_consecutive_losses,
            'avg_winner_duration_minutes': _safe_float(self.avg_winner_duration_minutes, 1),
            'avg_loser_duration_minutes': _safe_float(self.avg_loser_duration_minutes, 1)
        }


@dataclass
class PerformanceMetrics:
    """
    Trading performance metrics calculated from closed trades.

    SOTA Attributes (Dec 2025):
        - Core: total_trades, winning_trades, losing_trades, win_rate, profit_factor
        - Advanced: expectancy, average_win, average_loss, largest_win, largest_loss
        - Aggregated: max_drawdown, total_pnl, average_rr
    """
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    profit_factor: float
    max_drawdown: float
    total_pnl: float
    average_rr: float
    # SOTA: New Professional Metrics
    expectancy: float = 0.0
    average_win: float = 0.0
    average_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    # Per-symbol breakdown (computed separately)
    per_symbol: Dict[str, SymbolStats] = field(default_factory=dict)
    # SOTA Phase 24: Bot Behavior Analytics
    exit_reason_stats: Dict[str, ExitReasonStats] = field(default_factory=dict)
    risk_metrics: RiskMetrics = field(default_factory=RiskMetrics)
    streak_stats: StreakStats = field(default_factory=StreakStats)

    @classmethod
    def calculate_from_trades(cls, trades: List[PaperPosition]) -> 'PerformanceMetrics':
        """
        Calculate performance metrics from a list of closed trades.

        Args:
            trades: List of closed PaperPosition objects

        Returns:
            PerformanceMetrics instance with all SOTA metrics
        """
        if not trades:
            return cls(
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0.0,
                profit_factor=0.0,
                max_drawdown=0.0,
                total_pnl=0.0,
                average_rr=0.0,
                expectancy=0.0,
                average_win=0.0,
                average_loss=0.0,
                largest_win=0.0,
                largest_loss=0.0,
                per_symbol={},
                exit_reason_stats={},
                risk_metrics=RiskMetrics(),
                streak_stats=StreakStats()
            )

        total_trades = len(trades)
        winning_trades_list = [t for t in trades if t.realized_pnl > 0]
        losing_trades_list = [t for t in trades if t.realized_pnl < 0]
        winning_trades = len(winning_trades_list)
        losing_trades = len(losing_trades_list)

        # Win rate
        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
        loss_rate = losing_trades / total_trades if total_trades > 0 else 0.0

        # Profit factor
        gross_profit = sum(t.realized_pnl for t in winning_trades_list)
        gross_loss = abs(sum(t.realized_pnl for t in losing_trades_list))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf') if gross_profit > 0 else 0.0

        # Total PnL
        total_pnl = sum(t.realized_pnl for t in trades)

        # SOTA: Average Win / Average Loss
        average_win = gross_profit / winning_trades if winning_trades > 0 else 0.0
        average_loss = gross_loss / losing_trades if losing_trades > 0 else 0.0

        # SOTA: Expectancy = (Win% × Avg Win) - (Loss% × Avg Loss)
        expectancy = (win_rate * average_win) - (loss_rate * average_loss)

        # SOTA: Largest Win / Largest Loss
        largest_win = max((t.realized_pnl for t in winning_trades_list), default=0.0)
        largest_loss = min((t.realized_pnl for t in losing_trades_list), default=0.0)

        # Max Drawdown (calculate from equity curve)
        max_drawdown = cls._calculate_max_drawdown(trades)

        # Average R:R (simplified - based on actual returns)
        average_rr = cls._calculate_average_rr(trades)

        # Calculate per-symbol breakdown
        per_symbol = cls._calculate_per_symbol_stats(trades)

        # SOTA Phase 24: Bot Behavior Analytics
        exit_reason_stats = cls._calculate_exit_reason_stats(trades)
        risk_metrics = cls._calculate_risk_metrics(trades, total_pnl, max_drawdown)
        streak_stats = cls._calculate_streak_stats(trades, winning_trades_list, losing_trades_list)

        return cls(
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            profit_factor=profit_factor,
            max_drawdown=max_drawdown,
            total_pnl=total_pnl,
            average_rr=average_rr,
            expectancy=expectancy,
            average_win=average_win,
            average_loss=average_loss,
            largest_win=largest_win,
            largest_loss=largest_loss,
            per_symbol=per_symbol,
            exit_reason_stats=exit_reason_stats,
            risk_metrics=risk_metrics,
            streak_stats=streak_stats
        )

    @classmethod
    def _calculate_per_symbol_stats(cls, trades: List[PaperPosition]) -> Dict[str, SymbolStats]:
        """
        SOTA: Calculate breakdown by trading symbol.

        Returns Dict[symbol, SymbolStats] for analytics dashboard.
        """
        grouped: Dict[str, List[PaperPosition]] = defaultdict(list)
        for t in trades:
            symbol = (t.symbol or 'UNKNOWN').upper()
            grouped[symbol].append(t)

        result = {}
        for symbol, symbol_trades in grouped.items():
            total = len(symbol_trades)
            winners = [t for t in symbol_trades if t.realized_pnl > 0]
            losers = [t for t in symbol_trades if t.realized_pnl < 0]
            win_count = len(winners)
            loss_count = len(losers)

            # Win Rate
            win_rate = win_count / total if total > 0 else 0.0

            # PnL
            total_pnl = sum(t.realized_pnl for t in symbol_trades)

            # Profit Factor
            gross_profit = sum(t.realized_pnl for t in winners)
            gross_loss = abs(sum(t.realized_pnl for t in losers))
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float('inf') if gross_profit > 0 else 0.0)

            # LONG vs SHORT breakdown
            long_trades = [t for t in symbol_trades if t.side == 'LONG']
            short_trades = [t for t in symbol_trades if t.side == 'SHORT']
            long_winners = sum(1 for t in long_trades if t.realized_pnl > 0)
            short_winners = sum(1 for t in short_trades if t.realized_pnl > 0)
            long_win_rate = long_winners / len(long_trades) if long_trades else 0.0
            short_win_rate = short_winners / len(short_trades) if short_trades else 0.0

            # Best Side
            best_side = "-"
            if long_win_rate > short_win_rate and long_trades:
                best_side = "LONG"
            elif short_win_rate > long_win_rate and short_trades:
                best_side = "SHORT"

            result[symbol] = SymbolStats(
                symbol=symbol,
                total_trades=total,
                winning_trades=win_count,
                losing_trades=loss_count,
                win_rate=win_rate,
                total_pnl=total_pnl,
                profit_factor=profit_factor,
                long_trades=len(long_trades),
                short_trades=len(short_trades),
                long_win_rate=long_win_rate,
                short_win_rate=short_win_rate,
                best_side=best_side
            )

        return result

    @staticmethod
    def _calculate_max_drawdown(trades: List[PaperPosition]) -> float:
        """Calculate maximum drawdown from trade sequence"""
        if not trades:
            return 0.0

        # Sort by close time
        sorted_trades = sorted(
            [t for t in trades if t.close_time],
            key=lambda t: t.close_time
        )

        if not sorted_trades:
            return 0.0

        # Build equity curve
        equity = 10000.0  # Starting balance
        peak = equity
        max_dd = 0.0

        for trade in sorted_trades:
            equity += trade.realized_pnl
            if equity > peak:
                peak = equity
            drawdown = (peak - equity) / peak if peak > 0 else 0.0
            max_dd = max(max_dd, drawdown)

        return max_dd

    @staticmethod
    def _calculate_average_rr(trades: List[PaperPosition]) -> float:
        """Calculate average risk/reward ratio from trades"""
        if not trades:
            return 0.0

        rr_values = []
        for trade in trades:
            if trade.margin > 0:
                # R:R = PnL / Risk (margin)
                rr = trade.realized_pnl / trade.margin
                rr_values.append(rr)

        return sum(rr_values) / len(rr_values) if rr_values else 0.0

    @classmethod
    def _calculate_exit_reason_stats(cls, trades: List[PaperPosition]) -> Dict[str, ExitReasonStats]:
        """
        SOTA Phase 24: Analyze bot behavior by exit reason.

        Critical for understanding:
        - Is SIGNAL_REVERSAL profitable?
        - Is STOP_LOSS triggering too often?
        - How long does each exit type take?
        """
        from datetime import datetime
        grouped: Dict[str, List[PaperPosition]] = defaultdict(list)

        for t in trades:
            reason = t.exit_reason or 'UNKNOWN'
            grouped[reason].append(t)

        result = {}
        for reason, reason_trades in grouped.items():
            count = len(reason_trades)
            winners = [t for t in reason_trades if t.realized_pnl > 0]
            win_rate = len(winners) / count if count > 0 else 0.0

            total_pnl = sum(t.realized_pnl for t in reason_trades)
            avg_pnl = total_pnl / count if count > 0 else 0.0

            # Calculate average duration in minutes
            durations = []
            for t in reason_trades:
                if t.open_time and t.close_time:
                    try:
                        # Handle both datetime and string formats
                        open_time = t.open_time if isinstance(t.open_time, datetime) else datetime.fromisoformat(str(t.open_time).replace('Z', '+00:00'))
                        close_time = t.close_time if isinstance(t.close_time, datetime) else datetime.fromisoformat(str(t.close_time).replace('Z', '+00:00'))
                        duration_mins = (close_time - open_time).total_seconds() / 60
                        durations.append(duration_mins)
                    except:
                        pass
            avg_duration = sum(durations) / len(durations) if durations else 0.0

            result[reason] = ExitReasonStats(
                reason=reason,
                count=count,
                win_rate=win_rate,
                avg_pnl=avg_pnl,
                avg_duration_minutes=avg_duration,
                total_pnl=total_pnl
            )

        return result

    @classmethod
    def _calculate_risk_metrics(cls, trades: List[PaperPosition], total_pnl: float, max_drawdown: float) -> RiskMetrics:
        """
        SOTA Phase 24: Professional quant risk metrics.

        - Sharpe Ratio: Risk-adjusted return
        - Sortino Ratio: Downside-only volatility
        - Calmar Ratio: Return vs Max Drawdown
        - Recovery Factor: How well we recover from drawdowns
        """
        import statistics

        if not trades or len(trades) < 2:
            return RiskMetrics()

        returns = [t.realized_pnl for t in trades]

        # Sharpe Ratio = (Mean Return - Risk Free) / StdDev
        # Assuming risk-free = 0 for simplicity
        mean_return = statistics.mean(returns)
        std_dev = statistics.stdev(returns) if len(returns) > 1 else 0.0
        sharpe_ratio = mean_return / std_dev if std_dev > 0 else 0.0

        # Sortino Ratio = Mean Return / Downside Deviation
        negative_returns = [r for r in returns if r < 0]
        downside_dev = statistics.stdev(negative_returns) if len(negative_returns) > 1 else 0.0
        sortino_ratio = mean_return / downside_dev if downside_dev > 0 else (float('inf') if mean_return > 0 else 0.0)

        # Calmar Ratio = Annual Return / Max Drawdown
        # Simplified: using total return instead of annualized
        calmar_ratio = total_pnl / (max_drawdown * 10000) if max_drawdown > 0 else (float('inf') if total_pnl > 0 else 0.0)

        # Recovery Factor = Net Profit / Max Drawdown (in $)
        max_dd_dollars = max_drawdown * 10000  # Assuming $10k base
        recovery_factor = total_pnl / max_dd_dollars if max_dd_dollars > 0 else (float('inf') if total_pnl > 0 else 0.0)

        # Cap infinity to a displayable number
        sharpe_ratio = min(sharpe_ratio, 99.99)
        sortino_ratio = min(sortino_ratio, 99.99)
        calmar_ratio = min(calmar_ratio, 99.99)
        recovery_factor = min(recovery_factor, 99.99)

        return RiskMetrics(
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            calmar_ratio=calmar_ratio,
            recovery_factor=recovery_factor
        )

    @classmethod
    def _calculate_streak_stats(cls, trades: List[PaperPosition], winners: List[PaperPosition], losers: List[PaperPosition]) -> StreakStats:
        """
        SOTA Phase 24: Win/Loss streak analysis.

        Critical for detecting:
        - Current momentum (hot streak vs cold streak)
        - Historical consistency
        - Duration patterns
        """
        from datetime import datetime

        if not trades:
            return StreakStats()

        # Sort trades by close time
        sorted_trades = sorted(
            [t for t in trades if t.close_time],
            key=lambda t: t.close_time
        )

        if not sorted_trades:
            return StreakStats()

        # Calculate streaks
        current_streak = 0
        max_wins = 0
        max_losses = 0
        temp_wins = 0
        temp_losses = 0

        for t in sorted_trades:
            if t.realized_pnl > 0:
                temp_wins += 1
                temp_losses = 0
                max_wins = max(max_wins, temp_wins)
            elif t.realized_pnl < 0:
                temp_losses += 1
                temp_wins = 0
                max_losses = max(max_losses, temp_losses)
            else:
                # Break-even, reset both
                temp_wins = 0
                temp_losses = 0

        # Current streak from most recent trade
        if sorted_trades:
            last_pnl = sorted_trades[-1].realized_pnl
            current_streak = temp_wins if last_pnl > 0 else -temp_losses if last_pnl < 0 else 0

        # Average duration for winners vs losers
        def calc_avg_duration(trade_list):
            durations = []
            for t in trade_list:
                if t.open_time and t.close_time:
                    try:
                        open_time = t.open_time if isinstance(t.open_time, datetime) else datetime.fromisoformat(str(t.open_time).replace('Z', '+00:00'))
                        close_time = t.close_time if isinstance(t.close_time, datetime) else datetime.fromisoformat(str(t.close_time).replace('Z', '+00:00'))
                        duration_mins = (close_time - open_time).total_seconds() / 60
                        durations.append(duration_mins)
                    except:
                        pass
            return sum(durations) / len(durations) if durations else 0.0

        avg_winner_duration = calc_avg_duration(winners)
        avg_loser_duration = calc_avg_duration(losers)

        return StreakStats(
            current_streak=current_streak,
            max_consecutive_wins=max_wins,
            max_consecutive_losses=max_losses,
            avg_winner_duration_minutes=avg_winner_duration,
            avg_loser_duration_minutes=avg_loser_duration
        )

    @classmethod
    def calculate_from_binance_trades(cls, trades: List['BinanceTrade']) -> 'PerformanceMetrics':
        """
        v6.3.0: Calculate metrics from Binance truth data.

        Uses BinanceTrade.net_pnl (Binance API source of truth)
        instead of LocalPosition PnL.
        """
        if not trades:
            return cls(
                total_trades=0, winning_trades=0, losing_trades=0,
                win_rate=0.0, profit_factor=0.0, max_drawdown=0.0,
                total_pnl=0.0, average_rr=0.0,
            )

        total_trades = len(trades)
        winners = [t for t in trades if t.net_pnl > 0]
        losers = [t for t in trades if t.net_pnl < 0]
        winning_trades = len(winners)
        losing_trades = len(losers)

        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
        loss_rate = losing_trades / total_trades if total_trades > 0 else 0.0

        gross_profit = sum(t.net_pnl for t in winners)
        gross_loss = abs(sum(t.net_pnl for t in losers))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (
            float('inf') if gross_profit > 0 else 0.0
        )

        total_pnl = sum(t.net_pnl for t in trades)
        average_win = gross_profit / winning_trades if winning_trades > 0 else 0.0
        average_loss = gross_loss / losing_trades if losing_trades > 0 else 0.0
        expectancy = (win_rate * average_win) - (loss_rate * average_loss)
        largest_win = max((t.net_pnl for t in winners), default=0.0)
        largest_loss = min((t.net_pnl for t in losers), default=0.0)

        # Max drawdown from equity curve
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in trades:
            equity += t.net_pnl
            if equity > peak:
                peak = equity
            dd = peak - equity
            if dd > max_dd:
                max_dd = dd

        # R:R ratio
        rr = average_win / average_loss if average_loss > 0 else 0.0

        # Risk metrics
        import statistics as stats
        returns = [t.net_pnl for t in trades]
        if len(returns) > 1:
            mean_ret = stats.mean(returns)
            std_ret = stats.stdev(returns)
            sharpe = mean_ret / std_ret if std_ret > 0 else 0.0
            neg_rets = [r for r in returns if r < 0]
            dd_dev = stats.stdev(neg_rets) if len(neg_rets) > 1 else 0.0
            sortino = mean_ret / dd_dev if dd_dev > 0 else 0.0
        else:
            sharpe = sortino = 0.0

        risk = RiskMetrics(
            sharpe_ratio=min(sharpe, 99.99),
            sortino_ratio=min(sortino, 99.99),
            calmar_ratio=0.0,
            recovery_factor=total_pnl / max_dd if max_dd > 0 else 0.0,
        )

        return cls(
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            profit_factor=profit_factor,
            max_drawdown=max_dd,
            total_pnl=total_pnl,
            average_rr=rr,
            expectancy=expectancy,
            average_win=average_win,
            average_loss=average_loss,
            largest_win=largest_win,
            largest_loss=largest_loss,
            risk_metrics=risk,
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for API response (SOTA format)"""
        return {
            # Core Metrics
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': _safe_float(self.win_rate * 100, 2),  # As percentage
            'profit_factor': _safe_float(self.profit_factor, 2),
            'max_drawdown': _safe_float(self.max_drawdown * 100, 2),  # As percentage
            'total_pnl': _safe_float(self.total_pnl, 2),
            'average_rr': _safe_float(self.average_rr, 2),
            # SOTA: Advanced Metrics
            'expectancy': _safe_float(self.expectancy, 2),
            'average_win': _safe_float(self.average_win, 2),
            'average_loss': _safe_float(self.average_loss, 2),
            'largest_win': _safe_float(self.largest_win, 2),
            'largest_loss': _safe_float(self.largest_loss, 2),
            # Per-symbol breakdown
            'per_symbol': {k: v.to_dict() for k, v in self.per_symbol.items()},
            # SOTA Phase 24: Bot Behavior Analytics
            'exit_reason_stats': {k: v.to_dict() for k, v in self.exit_reason_stats.items()},
            'risk_metrics': self.risk_metrics.to_dict(),
            'streak_stats': self.streak_stats.to_dict(),
        }
