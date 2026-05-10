"""
BinanceTradeCollector — Application Layer

Fetches closed trades from Binance /fapi/v1/userTrades API.
Groups fills by orderId, computes net PnL, and persists to analytics DB.

Two collection modes:
1. After-close: Fire-and-forget after each trade close (real-time)
2. Daily reconciliation: Full sync to catch any gaps

v6.3.0: Institutional Analytics System
"""

import logging
import asyncio
from typing import List, Optional, Dict
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from ...domain.entities.binance_trade import BinanceTrade
from ...infrastructure.persistence.analytics_repository import AnalyticsRepository

# v6.0.0 deploy time (source of truth start)
V6_DEPLOY_TIME_MS = int(datetime(2026, 2, 11, 8, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)

# Current version tag
CURRENT_VERSION = "v6.2.0"

# UTC+7 offset
UTC7 = timezone(timedelta(hours=7))


class BinanceTradeCollector:
    """
    Collects trade data from Binance API and persists to SQLite.

    Passive/read-only — does NOT affect trading logic.
    Uses AsyncBinanceFuturesClient singleton for API calls.
    """

    def __init__(self, analytics_repo: AnalyticsRepository):
        self.repo = analytics_repo
        self.logger = logging.getLogger(__name__)
        self._async_client = None

    def _get_client(self):
        """Lazy-load AsyncBinanceFuturesClient singleton."""
        if self._async_client is None:
            from ...infrastructure.api.async_binance_client import AsyncBinanceFuturesClient
            self._async_client = AsyncBinanceFuturesClient()
        return self._async_client

    async def collect_after_close(self, symbol: str, delay_seconds: float = 3.0):
        """
        Fire-and-forget collection after a trade close.

        Waits a short delay for Binance to finalize the trade,
        then fetches recent trades for the symbol.
        """
        try:
            await asyncio.sleep(delay_seconds)

            client = self._get_client()
            # Fetch last 10 trades for this symbol (covers the just-closed trade)
            trades_data = await client._send_signed_request(
                "GET", "/fapi/v1/userTrades",
                {"symbol": symbol.upper(), "limit": 10}
            )

            if not trades_data:
                return

            binance_trades = self._process_fills(trades_data)
            if binance_trades:
                new_count = self.repo.upsert_trades(binance_trades)
                if new_count > 0:
                    self.logger.info(
                        f"📊 Analytics: collected {new_count} new trade(s) for {symbol}"
                    )
        except Exception as e:
            self.logger.warning(f"⚠️ Analytics collect_after_close({symbol}) failed: {e}")

    async def reconcile(self, since_ms: Optional[int] = None) -> Dict[str, int]:
        """
        Full reconciliation — fetch ALL trades since deployment.

        Used for:
        - Daily reconciliation at 00:05 UTC+7
        - Manual trigger via API
        - Initial backfill

        Returns: {"trades_collected": N, "new_trades": M}
        """
        try:
            start_time = since_ms or self.repo.get_latest_trade_time() or V6_DEPLOY_TIME_MS

            client = self._get_client()
            all_fills = []

            # Paginate through trades (Binance max 1000 per request)
            current_start = start_time
            max_pages = 100  # Safety limit: 100K fills max
            page = 0
            while page < max_pages:
                page += 1
                trades_data = await client._send_signed_request(
                    "GET", "/fapi/v1/userTrades",
                    {"startTime": current_start, "limit": 1000}
                )

                if not trades_data:
                    break

                all_fills.extend(trades_data)

                # If we got exactly 1000, there might be more
                if len(trades_data) >= 1000:
                    last_time = max(int(t['time']) for t in trades_data)
                    current_start = last_time + 1
                else:
                    break

            if page >= max_pages:
                self.logger.warning(f"⚠️ Reconciliation hit max pages ({max_pages})")

            binance_trades = self._process_fills(all_fills)
            new_count = self.repo.upsert_trades(binance_trades) if binance_trades else 0

            self.logger.info(
                f"📊 Analytics reconciliation: {len(all_fills)} fills → "
                f"{len(binance_trades)} close trades → {new_count} new"
            )

            return {
                "trades_collected": len(binance_trades),
                "new_trades": new_count,
                "total_fills": len(all_fills),
            }

        except Exception as e:
            self.logger.error(f"❌ Analytics reconciliation failed: {e}")
            return {"trades_collected": 0, "new_trades": 0, "error": str(e)}

    def _process_fills(self, fills: List[Dict]) -> List[BinanceTrade]:
        """
        Process raw Binance fills into BinanceTrade entities.

        Logic mirrors scripts/binance_v6_trades.py:
        1. Group fills by orderId
        2. Filter for CLOSE orders (realizedPnl != 0 or reduceOnly)
        3. Compute net PnL = sum(realizedPnl) - sum(commission)
        """
        # Group by orderId
        orders = defaultdict(list)
        for fill in fills:
            orders[fill['orderId']].append(fill)

        trades = []
        now_iso = datetime.now(timezone.utc).isoformat()

        for order_id, order_fills in orders.items():
            gross_pnl = sum(float(f.get('realizedPnl', 0)) for f in order_fills)
            commission = sum(float(f.get('commission', 0)) for f in order_fills)
            reduce_only = any(f.get('reduceOnly', False) for f in order_fills)

            # Skip OPEN orders (no PnL and not reduceOnly)
            if gross_pnl == 0 and not reduce_only:
                continue

            f0 = order_fills[0]
            trade_time = int(f0['time'])
            symbol = f0['symbol']
            close_side = f0['side']  # BUY or SELL

            # Infer direction: if close side is SELL → was LONG, if BUY → was SHORT
            direction = "LONG" if close_side == "SELL" else "SHORT"

            net_pnl = gross_pnl - commission
            result = "WIN" if net_pnl > 0 else "LOSS"

            # UTC+7 session info
            trade_dt_utc7 = datetime.fromtimestamp(trade_time / 1000, tz=UTC7)
            session_hour = trade_dt_utc7.hour
            # 30-min bucket: floor to nearest 30 min
            minute_bucket = (trade_dt_utc7.minute // 30) * 30
            session_slot = f"{session_hour:02d}:{minute_bucket:02d}"

            # Try to match exit_reason from live_positions DB
            exit_reason = self._lookup_exit_reason(symbol, trade_time)

            # Determine version tag based on trade time
            version_tag = self._get_version_tag(trade_time)

            trades.append(BinanceTrade(
                order_id=str(order_id),
                trade_time=trade_time,
                symbol=symbol,
                close_side=close_side,
                direction=direction,
                gross_pnl=gross_pnl,
                commission=commission,
                net_pnl=net_pnl,
                result=result,
                session_hour=session_hour,
                session_slot=session_slot,
                version_tag=version_tag,
                exit_reason=exit_reason,
                hold_duration_minutes=0,  # Enriched later if entry data available
                collected_at=now_iso,
            ))

        # Sort by trade time
        trades.sort(key=lambda t: t.trade_time)
        return trades

    def _lookup_exit_reason(self, symbol: str, trade_time_ms: int) -> str:
        """Try to match exit_reason from live_positions table (best-effort)."""
        try:
            from ...infrastructure.persistence.sqlite_order_repository import SQLiteOrderRepository
            # Use same DB path as analytics repo
            with self.repo._get_connection() as conn:
                cursor = conn.cursor()
                # Find closest closed position for this symbol within 60s window
                cursor.execute('''
                    SELECT exit_reason FROM live_positions
                    WHERE symbol = ? AND status IN ('CLOSED', 'REPLACED', 'GHOST_CLOSED')
                    AND exit_reason IS NOT NULL AND exit_reason != ''
                    ORDER BY ABS(
                        CAST(strftime('%%s', close_time) AS INTEGER) * 1000 - ?
                    ) ASC LIMIT 1
                ''', (symbol.upper(), trade_time_ms))
                row = cursor.fetchone()
                if row and row[0]:
                    return str(row[0])
        except Exception:
            pass
        return ""

    def _get_version_tag(self, trade_time_ms: int) -> str:
        """Determine version based on trade timestamp."""
        # Deploy timestamps (UTC)
        v620_deploy = int(datetime(2026, 2, 11, 19, 19, 0, tzinfo=timezone.utc).timestamp() * 1000)
        v610_deploy = int(datetime(2026, 2, 11, 12, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)

        if trade_time_ms >= v620_deploy:
            return CURRENT_VERSION
        elif trade_time_ms >= v610_deploy:
            return "v6.1.0"
        elif trade_time_ms >= V6_DEPLOY_TIME_MS:
            return "v6.0.0"
        return "pre-v6"
