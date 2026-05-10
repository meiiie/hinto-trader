"""
ProfitChartGenerator - SOTA Equity Curve Chart Generator

Pattern: Institutional Portfolio Reporting
- Generates matplotlib equity curve charts
- Scheduled sending via Telegram
- Manual trigger via API

Created: 2026-02-01
Purpose: Fix REAL MONEY gap - provide visual performance metrics
"""

import asyncio
import logging
import io
import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict, TYPE_CHECKING
from dataclasses import dataclass

# matplotlib import with agg backend for headless server
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

if TYPE_CHECKING:
    from ...infrastructure.persistence.sqlite_order_repository import SQLiteOrderRepository
    from ...infrastructure.notifications.telegram_service import TelegramService

logger = logging.getLogger(__name__)


@dataclass
class TradePoint:
    """Single trade for equity curve calculation."""
    timestamp: datetime
    pnl: float
    cumulative_pnl: float
    symbol: str
    side: str


class ProfitChartGenerator:
    """
    SOTA Profit Chart Generator

    Generates professional equity curve charts and sends via Telegram.
    Scheduled to run every N hours automatically.

    Features:
    - Equity curve visualization
    - Win/Loss coloring
    - Drawdown overlay
    - Session statistics

    Usage:
        generator = ProfitChartGenerator(
            order_repo=sqlite_repo,
            telegram_service=telegram,
            interval_hours=5.0
        )
        await generator.start()
    """

    # Chart styling
    CHART_STYLE = {
        'figure.facecolor': '#1e1e1e',
        'axes.facecolor': '#2d2d2d',
        'axes.edgecolor': '#555555',
        'axes.labelcolor': '#ffffff',
        'text.color': '#ffffff',
        'xtick.color': '#ffffff',
        'ytick.color': '#ffffff',
        'grid.color': '#444444',
        'grid.alpha': 0.5
    }

    def __init__(
        self,
        order_repo: 'SQLiteOrderRepository',
        telegram_service: Optional['TelegramService'] = None,
        interval_hours: float = 5.0,
        output_dir: str = "data/charts",
        enabled: bool = True
    ):
        """
        Initialize ProfitChartGenerator.

        Args:
            order_repo: SQLite repository for trade history
            telegram_service: Telegram service for sending charts
            interval_hours: Hours between automatic chart generation
            output_dir: Directory to save chart images
            enabled: Whether service is enabled
        """
        self._order_repo = order_repo
        self._telegram = telegram_service
        self._interval_hours = interval_hours
        self._output_dir = output_dir
        self._enabled = enabled

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_generated: Optional[datetime] = None

        # Stats
        self._charts_generated = 0
        self._charts_sent = 0

        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)

        logger.info(
            f"📊 ProfitChartGenerator initialized: "
            f"interval={interval_hours}h, output_dir={output_dir}"
        )

    async def start(self):
        """Start scheduled chart generation."""
        if self._running:
            logger.warning("ProfitChartGenerator already running")
            return

        if not self._enabled:
            logger.info("ProfitChartGenerator disabled, not starting")
            return

        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info(f"📈 ProfitChartGenerator started (every {self._interval_hours}h)")

    async def stop(self):
        """Stop scheduled chart generation."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("🛑 ProfitChartGenerator stopped")

    async def _scheduler_loop(self):
        """Main scheduler loop."""
        interval_seconds = self._interval_hours * 3600

        while self._running:
            try:
                await self.generate_and_send_chart()
                await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Chart generation error: {e}")
                await asyncio.sleep(60)  # Retry after 1 minute on error

    async def generate_and_send_chart(self) -> Dict:
        """
        Generate equity curve chart and send to Telegram.

        Returns:
            Dict with generation results
        """
        try:
            # 1. Load trade history
            trades = await self._load_trades()

            if not trades:
                logger.info("No trades found for chart generation")
                return {'success': False, 'reason': 'no_trades'}

            # 2. Generate chart
            chart_path = await self._generate_chart(trades)

            if not chart_path:
                return {'success': False, 'reason': 'chart_generation_failed'}

            self._charts_generated += 1
            self._last_generated = datetime.now()

            # 3. Send to Telegram
            if self._telegram:
                sent = await self._send_chart(chart_path, trades)
                if sent:
                    self._charts_sent += 1

            logger.info(f"✅ Chart generated and sent: {chart_path}")

            return {
                'success': True,
                'chart_path': chart_path,
                'trades_count': len(trades),
                'timestamp': datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"❌ Chart generation failed: {e}")
            return {'success': False, 'error': str(e)}

    async def _load_trades(self) -> List[TradePoint]:
        """Load closed trades from database."""
        trades = []

        try:
            # Get closed orders from database (last 7 days)
            closed_orders = self._order_repo.get_closed_orders(limit=500)

            cumulative_pnl = 0.0

            for order in closed_orders:
                pnl = getattr(order, 'realized_pnl', 0) or 0
                cumulative_pnl += pnl

                # Parse timestamp
                exit_time = getattr(order, 'exit_time', None)
                if isinstance(exit_time, str):
                    try:
                        exit_time = datetime.fromisoformat(exit_time.replace('Z', '+00:00'))
                    except:
                        exit_time = datetime.now()
                elif exit_time is None:
                    exit_time = datetime.now()

                trades.append(TradePoint(
                    timestamp=exit_time,
                    pnl=pnl,
                    cumulative_pnl=cumulative_pnl,
                    symbol=getattr(order, 'symbol', 'UNKNOWN'),
                    side=getattr(order, 'side', 'UNKNOWN')
                ))

            # Sort by timestamp
            trades.sort(key=lambda t: t.timestamp)

            # Recalculate cumulative after sort
            cumulative_pnl = 0.0
            for trade in trades:
                cumulative_pnl += trade.pnl
                trade.cumulative_pnl = cumulative_pnl

        except Exception as e:
            logger.error(f"Failed to load trades: {e}")

        return trades

    async def _generate_chart(self, trades: List[TradePoint]) -> Optional[str]:
        """
        Generate matplotlib equity curve chart.

        Args:
            trades: List of TradePoints

        Returns:
            Path to saved chart image
        """
        try:
            # Apply dark theme
            plt.rcParams.update(self.CHART_STYLE)

            # Create figure with 2 subplots
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8),
                                           height_ratios=[3, 1],
                                           sharex=True)
            fig.suptitle('Hinto - Equity Curve',
                        fontsize=14, fontweight='bold', color='#00ff88')

            # Data preparation
            timestamps = [t.timestamp for t in trades]
            cumulative_pnl = [t.cumulative_pnl for t in trades]
            individual_pnl = [t.pnl for t in trades]

            # === Subplot 1: Equity Curve ===
            ax1.fill_between(timestamps, 0, cumulative_pnl,
                           alpha=0.3, color='#00ff88', label='Equity')
            ax1.plot(timestamps, cumulative_pnl,
                    color='#00ff88', linewidth=2, label='Cumulative P&L')

            # Mark max drawdown
            peak = 0
            max_dd = 0
            max_dd_idx = 0
            for i, pnl in enumerate(cumulative_pnl):
                if pnl > peak:
                    peak = pnl
                dd = peak - pnl
                if dd > max_dd:
                    max_dd = dd
                    max_dd_idx = i

            if max_dd > 0 and max_dd_idx > 0:
                ax1.axhline(y=cumulative_pnl[max_dd_idx],
                           color='#ff4444', linestyle='--', alpha=0.5)
                ax1.annotate(f'Max DD: ${max_dd:.2f}',
                           xy=(timestamps[max_dd_idx], cumulative_pnl[max_dd_idx]),
                           xytext=(10, -20), textcoords='offset points',
                           color='#ff4444', fontsize=9)

            # Final P&L annotation
            final_pnl = cumulative_pnl[-1] if cumulative_pnl else 0
            color = '#00ff88' if final_pnl >= 0 else '#ff4444'
            ax1.annotate(f'Total: ${final_pnl:.2f}',
                        xy=(timestamps[-1], final_pnl),
                        xytext=(10, 10), textcoords='offset points',
                        color=color, fontsize=12, fontweight='bold')

            ax1.set_ylabel('Cumulative P&L ($)', fontsize=10)
            ax1.grid(True, alpha=0.3)
            ax1.legend(loc='upper left')

            # === Subplot 2: Individual Trade P&L ===
            colors = ['#00ff88' if pnl >= 0 else '#ff4444' for pnl in individual_pnl]
            ax2.bar(timestamps, individual_pnl, color=colors, alpha=0.8, width=0.02)
            ax2.axhline(y=0, color='#888888', linewidth=0.5)
            ax2.set_ylabel('Trade P&L ($)', fontsize=10)
            ax2.set_xlabel('Time', fontsize=10)
            ax2.grid(True, alpha=0.3)

            # Format x-axis
            ax2.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))
            plt.xticks(rotation=45)

            # Stats text box
            wins = sum(1 for pnl in individual_pnl if pnl > 0)
            losses = len(individual_pnl) - wins
            win_rate = wins / len(individual_pnl) * 100 if individual_pnl else 0
            avg_win = sum(p for p in individual_pnl if p > 0) / wins if wins > 0 else 0
            avg_loss = sum(p for p in individual_pnl if p <= 0) / losses if losses > 0 else 0

            stats_text = (
                f"Trades: {len(trades)} | "
                f"Win Rate: {win_rate:.1f}% | "
                f"Avg Win: ${avg_win:.2f} | "
                f"Avg Loss: ${avg_loss:.2f}"
            )
            fig.text(0.5, 0.02, stats_text, ha='center', fontsize=10, color='#cccccc')

            # Timestamp
            fig.text(0.99, 0.02, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                    ha='right', fontsize=8, color='#888888')

            plt.tight_layout(rect=[0, 0.05, 1, 0.95])

            # Save chart
            timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
            chart_path = os.path.join(self._output_dir, f"equity_curve_{timestamp_str}.png")
            plt.savefig(chart_path, dpi=150, facecolor='#1e1e1e', edgecolor='none')
            plt.close(fig)

            return chart_path

        except Exception as e:
            logger.error(f"Failed to generate chart: {e}")
            return None

    async def _send_chart(self, chart_path: str, trades: List[TradePoint]) -> bool:
        """Send chart to Telegram."""
        if not self._telegram:
            return False

        try:
            # Calculate summary stats
            total_pnl = trades[-1].cumulative_pnl if trades else 0
            wins = sum(1 for t in trades if t.pnl > 0)
            win_rate = wins / len(trades) * 100 if trades else 0

            caption = (
                f"📊 <b>Hinto - Performance Report</b>\n\n"
                f"<b>Period:</b> Last {len(trades)} trades\n"
                f"<b>Total P&L:</b> <code>${total_pnl:+.2f}</code>\n"
                f"<b>Win Rate:</b> <code>{win_rate:.1f}%</code>\n"
                f"<b>Generated:</b> {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            )

            # Send photo
            sent = await self._telegram.send_photo(chart_path, caption)
            return sent

        except Exception as e:
            logger.error(f"Failed to send chart: {e}")
            return False

    async def generate_now(self) -> Dict:
        """
        Trigger manual chart generation.

        Returns:
            Dict with generation results
        """
        return await self.generate_and_send_chart()

    def get_stats(self) -> Dict:
        """Get generator statistics."""
        return {
            'enabled': self._enabled,
            'running': self._running,
            'interval_hours': self._interval_hours,
            'charts_generated': self._charts_generated,
            'charts_sent': self._charts_sent,
            'last_generated': self._last_generated.isoformat() if self._last_generated else None,
            'output_dir': self._output_dir
        }

    def __repr__(self) -> str:
        status = "RUNNING" if self._running else "STOPPED"
        return f"ProfitChartGenerator({status}, interval={self._interval_hours}h)"
