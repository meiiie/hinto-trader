"""
Report Generator for Backtesting

Generates comprehensive backtest reports with visualizations.
"""

from datetime import datetime
from typing import List
import logging

from scripts.backtesting.performance_analyzer import BacktestResults
from scripts.backtesting.trade_simulator import Trade

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generate backtest reports and visualizations"""

    def generate_summary(
        self,
        results: BacktestResults,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        initial_capital: float
    ) -> str:
        """
        Generate text summary of backtest results

        Returns:
            Formatted text report
        """
        # Calculate period
        period_days = (end_date - start_date).days

        # Check if targets met
        win_rate_pass = "✅" if results.win_rate >= 70 else "❌"
        rr_pass = "✅" if results.avg_rr_ratio >= 1.5 else "❌"
        dd_pass = "✅" if results.max_drawdown_pct < 15 else "❌"
        sharpe_pass = "✅" if results.sharpe_ratio >= 1.0 else "❌"
        pf_pass = "✅" if results.profit_factor >= 1.5 else "❌"

        all_pass = all([
            results.win_rate >= 70,
            results.avg_rr_ratio >= 1.5,
            results.max_drawdown_pct < 15,
            results.sharpe_ratio >= 1.0,
            results.profit_factor >= 1.5
        ])

        # Calculate exit percentages (avoid division by zero)
        if results.total_trades > 0:
            tp1_pct = results.tp1_count / results.total_trades * 100
            tp2_pct = results.tp2_count / results.total_trades * 100
            tp3_pct = results.tp3_count / results.total_trades * 100
            sl_pct = results.sl_count / results.total_trades * 100
            timeout_pct = results.timeout_count / results.total_trades * 100
        else:
            tp1_pct = tp2_pct = tp3_pct = sl_pct = timeout_pct = 0.0

        report = f"""
{'='*65}
BACKTEST RESULTS - {symbol} {timeframe}
{'='*65}
Period: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')} ({period_days} days)
Initial Capital: ${initial_capital:,.2f}

TRADE STATISTICS:
{'-'*65}
Total Trades:        {results.total_trades}
Winning Trades:      {results.winning_trades} ({results.win_rate:.1f}%)  {win_rate_pass} Target: >70%
Losing Trades:       {results.losing_trades} ({100-results.win_rate:.1f}%)
Win Rate:            {results.win_rate:.1f}%       {win_rate_pass} {'PASS' if results.win_rate >= 70 else 'FAIL'}

PROFIT & LOSS:
{'-'*65}
Total P&L:           ${results.total_pnl:,.2f}
Total Return:        {results.total_pnl_pct:.2f}%
Average Win:         ${results.avg_win:,.2f}
Average Loss:        ${results.avg_loss:,.2f}
Average P&L:         ${results.avg_pnl:,.2f}
Avg R:R Ratio:       {results.avg_rr_ratio:.2f}        {rr_pass} Target: >1.5
Profit Factor:       {results.profit_factor:.2f}        {pf_pass} Target: >1.5

RISK METRICS:
{'-'*65}
Max Drawdown:        ${results.max_drawdown:,.2f} ({results.max_drawdown_pct:.2f}%)   {dd_pass} Target: <15%
Max Drawdown %:      {results.max_drawdown_pct:.2f}%
Sharpe Ratio:        {results.sharpe_ratio:.2f}             {sharpe_pass} Target: >1.0

EXIT BREAKDOWN:
{'-'*65}
TP1 Hit:             {results.tp1_count} ({tp1_pct:.1f}%)
TP2 Hit:             {results.tp2_count} ({tp2_pct:.1f}%)
TP3 Hit:             {results.tp3_count} ({tp3_pct:.1f}%)
Stop Loss Hit:       {results.sl_count} ({sl_pct:.1f}%)
Timeout:             {results.timeout_count} ({timeout_pct:.1f}%)

{'='*65}
{'✅ BACKTEST PASSED ALL TARGETS!' if all_pass else '❌ BACKTEST DID NOT MEET ALL TARGETS'}
{'='*65}
"""
        return report

    def generate_trade_log(self, trades: List[Trade]) -> str:
        """
        Generate detailed trade log

        Returns:
            Formatted trade log
        """
        if not trades:
            return "No trades to display"

        log = "\nDETAILED TRADE LOG:\n"
        log += "=" * 120 + "\n"
        log += f"{'#':<4} {'Entry Time':<20} {'Dir':<5} {'Entry':<10} {'Exit':<10} {'Reason':<12} {'P&L':<12} {'P&L%':<8}\n"
        log += "-" * 120 + "\n"

        for i, trade in enumerate(trades, 1):
            if trade.is_open():
                continue

            log += (
                f"{i:<4} "
                f"{trade.entry_time.strftime('%Y-%m-%d %H:%M'):<20} "
                f"{trade.direction:<5} "
                f"${trade.entry_price:<9.2f} "
                f"${trade.exit_price:<9.2f} "
                f"{trade.exit_reason.value:<12} "
                f"${trade.pnl:<11.2f} "
                f"{trade.pnl_pct:<7.2f}%\n"
            )

        log += "=" * 120 + "\n"
        return log

    def export_results(
        self,
        results: BacktestResults,
        summary: str,
        trade_log: str,
        output_path: str
    ) -> None:
        """
        Export results to file

        Args:
            results: Backtest results
            summary: Summary text
            trade_log: Trade log text
            output_path: Output file path
        """
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(summary)
                f.write("\n\n")
                f.write(trade_log)

            logger.info(f"Results exported to {output_path}")

        except Exception as e:
            logger.error(f"Error exporting results: {e}")
            raise

    def print_summary_table(self, results: BacktestResults) -> None:
        """Print summary metrics table"""
        print("\n" + "="*60)
        print("BACKTEST SUMMARY")
        print("="*60)
        print(f"{'Metric':<30} {'Target':<15} {'Actual':<15}")
        print("-"*60)

        metrics = [
            ("Win Rate", "> 70%", f"{results.win_rate:.1f}%", results.win_rate >= 70),
            ("Avg R:R Ratio", "> 1.5", f"{results.avg_rr_ratio:.2f}", results.avg_rr_ratio >= 1.5),
            ("Max Drawdown", "< 15%", f"{results.max_drawdown_pct:.2f}%", results.max_drawdown_pct < 15),
            ("Sharpe Ratio", "> 1.0", f"{results.sharpe_ratio:.2f}", results.sharpe_ratio >= 1.0),
            ("Profit Factor", "> 1.5", f"{results.profit_factor:.2f}", results.profit_factor >= 1.5),
        ]

        for name, target, actual, passed in metrics:
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"{name:<30} {target:<15} {actual:<15} {status}")

        print("="*60)
