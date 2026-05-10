"""
AnalyticsReportService — Application Layer

Orchestrates daily analytics report generation:
1. Reconcile Binance trades
2. Compute all metrics
3. Save daily snapshot
4. Generate charts
5. Send Telegram report

v6.3.0: Institutional Analytics System
"""

import logging
from typing import Optional, Dict
from datetime import datetime, timezone, timedelta

from .binance_trade_collector import BinanceTradeCollector
from .analytics_engine import AnalyticsEngine
from .session_analyzer import SessionAnalyzer
from .symbol_alpha_tracker import SymbolAlphaTracker
from .direction_analyzer import DirectionAnalyzer
from ...infrastructure.monitoring.analytics_chart_generator import AnalyticsChartGenerator
from ...infrastructure.persistence.analytics_repository import AnalyticsRepository

UTC7 = timezone(timedelta(hours=7))


class AnalyticsReportService:
    """
    Orchestrates analytics report generation.

    Triggered:
    - Daily at 00:05 UTC+7 (from _daily_summary_loop)
    - On-demand via API POST /analytics/daily-report
    """

    def __init__(
        self,
        collector: BinanceTradeCollector,
        engine: AnalyticsEngine,
        session_analyzer: SessionAnalyzer,
        symbol_tracker: SymbolAlphaTracker,
        direction_analyzer: DirectionAnalyzer,
        chart_generator: AnalyticsChartGenerator,
        analytics_repo: AnalyticsRepository,
        telegram_service=None,
    ):
        self.collector = collector
        self.engine = engine
        self.session_analyzer = session_analyzer
        self.symbol_tracker = symbol_tracker
        self.direction_analyzer = direction_analyzer
        self.chart_generator = chart_generator
        self.repo = analytics_repo
        self.telegram_service = telegram_service
        self.logger = logging.getLogger(__name__)

    async def generate_daily_report(self) -> Dict:
        """
        Full daily report pipeline.

        1. Reconcile Binance trades
        2. Compute metrics
        3. Save snapshot
        4. Generate charts
        5. Send Telegram
        """
        try:
            # 1. Reconcile
            recon = await self.collector.reconcile()
            self.logger.info(f"📊 Reconciliation: {recon}")

            # 2. Full report
            report = self.engine.get_full_report()
            today_metrics = self.engine.get_today_metrics()

            # 3. Save snapshot
            snapshot = self.engine.save_daily_snapshot()

            # 4. Yesterday's snapshot for comparison
            yesterday = (datetime.now(UTC7) - timedelta(days=1)).strftime('%Y-%m-%d')
            prev_snapshot = None
            snapshots = self.repo.get_snapshots(days=7)
            for s in snapshots:
                if s.get('snapshot_date') == yesterday:
                    prev_snapshot = s
                    break

            # 5. Tier 2 data
            session_data = self.session_analyzer.get_session_heatmap()
            symbol_data = self.symbol_tracker.get_symbol_decomposition()
            direction_data = self.direction_analyzer.get_direction_split()

            # 6. Generate charts
            equity_chart_path = None
            heatmap_chart_path = None
            if report.get("equity_curve"):
                equity_chart_path = self.chart_generator.generate_equity_curve(
                    report["equity_curve"]
                )
            if session_data.get("hourly"):
                heatmap_chart_path = self.chart_generator.generate_session_heatmap(
                    session_data["hourly"]
                )

            # 7. Send Telegram
            if self.telegram_service:
                await self._send_telegram_report(
                    report, today_metrics, prev_snapshot,
                    session_data, symbol_data, direction_data,
                    equity_chart_path, heatmap_chart_path,
                )

            # Cleanup charts
            self.chart_generator.cleanup_chart(equity_chart_path)
            self.chart_generator.cleanup_chart(heatmap_chart_path)

            self.logger.info("📊 Daily analytics report completed")
            return {
                "status": "ok",
                "reconciliation": recon,
                "snapshot": snapshot,
                "report_trades": report.get("total_trades", 0),
            }

        except Exception as e:
            self.logger.error(f"❌ Daily analytics report failed: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

    async def _send_telegram_report(
        self, report: Dict, today: Dict, prev_snapshot: Optional[Dict],
        session_data: Dict, symbol_data: Dict, direction_data: Dict,
        equity_chart_path: Optional[str], heatmap_chart_path: Optional[str],
    ):
        """Format and send Telegram analytics report."""
        try:
            now = datetime.now(UTC7)
            date_str = now.strftime('%b %d, %Y')

            # Today section
            today_str = (
                f"📈 TODAY: {today['trades']} trades | "
                f"{today['wins']}W/{today['losses']}L = {today['win_rate']}% WR | "
                f"${today['net_pnl']:+.2f}"
            ) if today['trades'] > 0 else "📈 TODAY: No trades"

            # All-time section
            all_str = (
                f"📊 ALL: {report['total_trades']} trades | "
                f"{report['wins']}W/{report['losses']}L = {report['win_rate']}% WR | "
                f"${report['total_net_pnl']:+.2f}"
            )

            # R:R and Edge
            rr_str = (
                f"⚖️ R:R = {report['rr_ratio']} | "
                f"Edge = {report['edge_pp']:+.1f}pp | "
                f"PF = {report['profit_factor']}"
            )

            # vs Yesterday
            vs_str = ""
            if prev_snapshot:
                wr_delta = report['win_rate'] - (prev_snapshot.get('win_rate', 0) or 0)
                pnl_delta = today['net_pnl']
                edge_delta = report['edge_pp'] - (prev_snapshot.get('edge_pp', 0) or 0)
                vs_str = (
                    f"\n📉 vs Yesterday: WR {wr_delta:+.1f}pp | "
                    f"PnL ${pnl_delta:+.2f} | Edge {edge_delta:+.1f}pp"
                )

            # Significance
            sig = report.get('significance', {})
            sig_str = (
                f"🎯 Statistical Edge: p={sig.get('p_value', 1):.2f} "
                f"({'SIGNIFICANT' if sig.get('is_significant') else 'NOT significant'})\n"
                f"   Need ~{sig.get('trades_needed', '?')} trades at current edge"
            )

            # Top/Toxic symbols
            alpha = symbol_data.get("alpha", [])
            toxic = symbol_data.get("toxic", [])
            sym_str = ""
            if alpha:
                top2 = alpha[:2]
                sym_str += "🏆 Top: " + " | ".join(
                    f"{s['symbol']} ${s['net_pnl']:+.2f}" for s in top2
                )
            if toxic:
                bot2 = toxic[:2]
                sym_str += "\n💀 Toxic: " + " | ".join(
                    f"{s['symbol']} ${s['net_pnl']:+.2f}" for s in bot2
                )

            # Session
            dz = session_data.get("dead_zone_analysis", {})
            gold = dz.get("gold_hours", [])
            toxic_hrs = dz.get("toxic_hours", [])
            session_str = ""
            if gold:
                gold_range = f"{gold[0]['hour']:02d}-{gold[-1]['hour']+1:02d}h"
                gold_pnl = sum(g["net_pnl"] for g in gold)
                session_str += f"⏰ Gold Zone: {gold_range} (${gold_pnl:+.2f})"
            if toxic_hrs:
                toxic_range = f"{toxic_hrs[0]['hour']:02d}-{toxic_hrs[-1]['hour']+1:02d}h"
                session_str += f" | Toxic: {toxic_range} (BLOCKED)"

            # Direction
            dir_data = direction_data
            long_d = dir_data.get("long", {})
            short_d = dir_data.get("short", {})
            dir_str = (
                f"🧭 LONG {long_d.get('win_rate', 0)}% WR ${long_d.get('net_pnl', 0):+.2f} | "
                f"SHORT {short_d.get('win_rate', 0)}% WR ${short_d.get('net_pnl', 0):+.2f}"
            )

            # Risk
            risk = report.get("risk_metrics", {})
            risk_str = (
                f"💰 Max DD: ${risk.get('max_drawdown', 0):.2f} | "
                f"Sharpe: {risk.get('sharpe_per_trade', 0):.3f}"
            )

            # Compose
            message = (
                f"📊 <b>ANALYTICS REPORT — {date_str}</b>\n\n"
                f"{today_str}\n"
                f"{all_str}\n"
                f"{rr_str}"
                f"{vs_str}\n\n"
                f"{sig_str}\n\n"
            )
            if sym_str:
                message += f"{sym_str}\n\n"
            if session_str:
                message += f"{session_str}\n"
            message += f"{dir_str}\n\n{risk_str}"

            # Send text
            await self.telegram_service.send_message(message, silent=False)

            # Send equity curve chart
            if equity_chart_path:
                try:
                    await self.telegram_service.send_photo(
                        equity_chart_path,
                        caption="📈 Equity Curve — Binance Truth"
                    )
                except Exception as e:
                    self.logger.warning(f"Equity chart send failed: {e}")

        except Exception as e:
            self.logger.error(f"❌ Telegram analytics report failed: {e}")
