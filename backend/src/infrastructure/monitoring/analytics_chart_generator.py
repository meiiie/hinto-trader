"""
AnalyticsChartGenerator — Infrastructure Layer

Generates chart images (equity curve, session heatmap) for Telegram reports.
Uses matplotlib with Agg backend (no display needed).

v6.3.0: Institutional Analytics System
"""

import logging
import tempfile
import os
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class AnalyticsChartGenerator:
    """
    Generates PNG charts for analytics reports.

    Charts:
    - Equity curve (cumulative PnL over trades)
    - Session heatmap (hourly WR/PnL grid)
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._matplotlib_available = False
        try:
            import matplotlib
            matplotlib.use('Agg')
            self._matplotlib_available = True
        except ImportError:
            self.logger.warning("matplotlib not available — charts disabled")

    def generate_equity_curve(self, equity_data: List[Dict]) -> Optional[str]:
        """
        Generate equity curve PNG.

        Args:
            equity_data: List of {"trade_num", "cumulative_pnl", "result"}

        Returns:
            Path to temp PNG file, or None if failed.
        """
        if not self._matplotlib_available or not equity_data:
            return None

        try:
            import matplotlib.pyplot as plt
            import matplotlib.ticker as mticker

            fig, ax = plt.subplots(figsize=(10, 5))

            x = [d["trade_num"] for d in equity_data]
            y = [d["cumulative_pnl"] for d in equity_data]

            # Color segments by win/loss
            colors = ['#00C853' if d["result"] == "WIN" else '#FF1744' for d in equity_data]

            # Plot line
            ax.plot(x, y, color='#2196F3', linewidth=1.5, alpha=0.8)
            ax.scatter(x, y, c=colors, s=20, zorder=5, alpha=0.7)

            # Zero line
            ax.axhline(y=0, color='gray', linestyle='--', alpha=0.5)

            # Fill positive/negative areas
            ax.fill_between(x, y, 0,
                            where=[v >= 0 for v in y],
                            color='#00C853', alpha=0.1)
            ax.fill_between(x, y, 0,
                            where=[v < 0 for v in y],
                            color='#FF1744', alpha=0.1)

            ax.set_xlabel('Trade #', fontsize=10)
            ax.set_ylabel('Cumulative PnL ($)', fontsize=10)
            ax.set_title('Equity Curve — Binance Truth', fontsize=12, fontweight='bold')
            ax.grid(True, alpha=0.3)
            ax.yaxis.set_major_formatter(mticker.FormatStrFormatter('$%.2f'))

            # Annotate final value
            if y:
                final = y[-1]
                color = '#00C853' if final >= 0 else '#FF1744'
                ax.annotate(f'${final:+.2f}', xy=(x[-1], y[-1]),
                            fontsize=11, fontweight='bold', color=color,
                            xytext=(10, 10), textcoords='offset points')

            plt.tight_layout()

            # Save to temp file
            tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False, prefix='equity_')
            fig.savefig(tmp.name, dpi=150, bbox_inches='tight')
            plt.close(fig)

            return tmp.name

        except Exception as e:
            self.logger.warning(f"Equity curve generation failed: {e}")
            return None

    def generate_session_heatmap(self, hourly_data: List[Dict]) -> Optional[str]:
        """
        Generate session heatmap PNG.

        Args:
            hourly_data: List of {"hour", "trades", "win_rate", "net_pnl", "in_dead_zone"}

        Returns:
            Path to temp PNG file, or None if failed.
        """
        if not self._matplotlib_available or not hourly_data:
            return None

        try:
            import matplotlib.pyplot as plt
            import matplotlib.colors as mcolors
            import numpy as np

            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 6), height_ratios=[1, 1])

            hours = [d["hour"] for d in hourly_data]
            pnl = [d["net_pnl"] for d in hourly_data]
            wr = [d["win_rate"] for d in hourly_data]
            trades = [d["trades"] for d in hourly_data]
            dz = [d.get("in_dead_zone", False) for d in hourly_data]

            # PnL bar chart
            colors_pnl = ['#FF1744' if p < 0 else '#00C853' for p in pnl]
            # Dim dead zone hours
            for i, is_dz in enumerate(dz):
                if is_dz:
                    colors_pnl[i] = '#9E9E9E'

            bars = ax1.bar(hours, pnl, color=colors_pnl, alpha=0.8, edgecolor='white', linewidth=0.5)
            ax1.axhline(y=0, color='gray', linestyle='-', alpha=0.3)
            ax1.set_ylabel('Net PnL ($)', fontsize=10)
            ax1.set_title('Session Performance Heatmap (UTC+7)', fontsize=12, fontweight='bold')
            ax1.set_xticks(hours)
            ax1.set_xticklabels([f'{h:02d}' for h in hours], fontsize=8)
            ax1.grid(True, axis='y', alpha=0.3)

            # Trade count + WR
            ax2_twin = ax2.twinx()
            ax2.bar(hours, trades, color='#2196F3', alpha=0.4, label='Trades')
            ax2_twin.plot(hours, wr, color='#FF9800', marker='o', markersize=4,
                          linewidth=1.5, label='Win Rate %')
            ax2_twin.axhline(y=60, color='#FF9800', linestyle='--', alpha=0.3)

            ax2.set_xlabel('Hour (UTC+7)', fontsize=10)
            ax2.set_ylabel('Trade Count', fontsize=10)
            ax2_twin.set_ylabel('Win Rate %', fontsize=10)
            ax2.set_xticks(hours)
            ax2.set_xticklabels([f'{h:02d}' for h in hours], fontsize=8)
            ax2.grid(True, axis='y', alpha=0.3)

            # DZ annotation
            for i, is_dz in enumerate(dz):
                if is_dz and i < len(hours):
                    ax1.axvspan(hours[i] - 0.4, hours[i] + 0.4,
                                alpha=0.1, color='red')

            plt.tight_layout()

            tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False, prefix='heatmap_')
            fig.savefig(tmp.name, dpi=150, bbox_inches='tight')
            plt.close(fig)

            return tmp.name

        except Exception as e:
            self.logger.warning(f"Session heatmap generation failed: {e}")
            return None

    @staticmethod
    def cleanup_chart(path: Optional[str]):
        """Delete temporary chart file."""
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
