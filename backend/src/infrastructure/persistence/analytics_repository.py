"""
AnalyticsRepository — Infrastructure Layer

SQLite persistence for Binance trade analytics data.
Tables: binance_trades, analytics_snapshots.

v6.3.0: Institutional Analytics System
"""

import sqlite3
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from contextlib import contextmanager

from ...domain.entities.binance_trade import BinanceTrade


class AnalyticsRepository:
    """
    SQLite repository for analytics data (binance_trades + snapshots).

    Uses same DB file as SQLiteOrderRepository (trading_system.db).
    WAL mode for concurrent read/write.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self._init_tables()

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute('PRAGMA journal_mode=WAL;')
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_tables(self):
        """Create analytics tables if not exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS binance_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT NOT NULL,
                    trade_time INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    close_side TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    gross_pnl REAL NOT NULL,
                    commission REAL NOT NULL,
                    net_pnl REAL NOT NULL,
                    result TEXT NOT NULL,
                    session_hour INTEGER,
                    session_slot TEXT,
                    version_tag TEXT DEFAULT '',
                    exit_reason TEXT DEFAULT '',
                    hold_duration_minutes REAL DEFAULT 0,
                    collected_at TEXT NOT NULL,
                    UNIQUE(order_id)
                )
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_binance_trades_time
                ON binance_trades(trade_time)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_binance_trades_symbol
                ON binance_trades(symbol)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_binance_trades_version
                ON binance_trades(version_tag)
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS analytics_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_date TEXT NOT NULL,
                    total_trades INTEGER,
                    win_rate REAL,
                    profit_factor REAL,
                    total_net_pnl REAL,
                    rr_ratio REAL,
                    edge_pp REAL,
                    sharpe_per_trade REAL,
                    max_drawdown REAL,
                    day_trades INTEGER,
                    day_net_pnl REAL,
                    day_win_rate REAL,
                    p_value REAL,
                    version_tag TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(snapshot_date)
                )
            ''')

            conn.commit()
            self.logger.info("📊 Analytics tables initialized")

    # ==================
    # binance_trades CRUD
    # ==================

    def upsert_trade(self, trade: BinanceTrade) -> bool:
        """Insert or update a Binance trade. Returns True if new trade inserted."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO binance_trades (
                    order_id, trade_time, symbol, close_side, direction,
                    gross_pnl, commission, net_pnl, result,
                    session_hour, session_slot, version_tag, exit_reason,
                    hold_duration_minutes, collected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    gross_pnl = excluded.gross_pnl,
                    commission = excluded.commission,
                    net_pnl = excluded.net_pnl,
                    result = excluded.result,
                    exit_reason = excluded.exit_reason,
                    hold_duration_minutes = excluded.hold_duration_minutes,
                    collected_at = excluded.collected_at
            ''', (
                trade.order_id, trade.trade_time, trade.symbol,
                trade.close_side, trade.direction,
                trade.gross_pnl, trade.commission, trade.net_pnl, trade.result,
                trade.session_hour, trade.session_slot, trade.version_tag,
                trade.exit_reason, trade.hold_duration_minutes, trade.collected_at,
            ))
            conn.commit()
            return cursor.rowcount > 0

    def upsert_trades(self, trades: List[BinanceTrade]) -> int:
        """Batch upsert. Returns count of new trades."""
        new_count = 0
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for trade in trades:
                cursor.execute('''
                    INSERT INTO binance_trades (
                        order_id, trade_time, symbol, close_side, direction,
                        gross_pnl, commission, net_pnl, result,
                        session_hour, session_slot, version_tag, exit_reason,
                        hold_duration_minutes, collected_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(order_id) DO UPDATE SET
                        gross_pnl = excluded.gross_pnl,
                        commission = excluded.commission,
                        net_pnl = excluded.net_pnl,
                        result = excluded.result,
                        exit_reason = excluded.exit_reason,
                        hold_duration_minutes = excluded.hold_duration_minutes,
                        collected_at = excluded.collected_at
                ''', (
                    trade.order_id, trade.trade_time, trade.symbol,
                    trade.close_side, trade.direction,
                    trade.gross_pnl, trade.commission, trade.net_pnl, trade.result,
                    trade.session_hour, trade.session_slot, trade.version_tag,
                    trade.exit_reason, trade.hold_duration_minutes, trade.collected_at,
                ))
                if cursor.rowcount > 0:
                    new_count += 1
            conn.commit()
        return new_count

    def get_all_trades(self, version_tag: Optional[str] = None,
                       since_ms: Optional[int] = None,
                       limit: int = 10000) -> List[BinanceTrade]:
        """Get trades with optional filters."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM binance_trades WHERE 1=1"
            params = []

            if version_tag:
                query += " AND version_tag = ?"
                params.append(version_tag)
            if since_ms:
                query += " AND trade_time >= ?"
                params.append(since_ms)

            query += " ORDER BY trade_time ASC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            return [BinanceTrade.from_db_row(row) for row in cursor.fetchall()]

    def get_trades_for_day(self, date_str: str) -> List[BinanceTrade]:
        """Get trades for a specific day (YYYY-MM-DD in UTC+7)."""
        from datetime import datetime, timezone, timedelta
        utc7 = timezone(timedelta(hours=7))
        day_start = datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=utc7)
        day_end = day_start + timedelta(days=1)
        start_ms = int(day_start.timestamp() * 1000)
        end_ms = int(day_end.timestamp() * 1000)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM binance_trades WHERE trade_time >= ? AND trade_time < ? ORDER BY trade_time ASC",
                (start_ms, end_ms)
            )
            return [BinanceTrade.from_db_row(row) for row in cursor.fetchall()]

    def get_trade_count(self) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM binance_trades")
            return cursor.fetchone()[0]

    def get_latest_trade_time(self) -> Optional[int]:
        """Get the most recent trade_time (for incremental collection)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(trade_time) FROM binance_trades")
            result = cursor.fetchone()[0]
            return result if result else None

    def order_id_exists(self, order_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM binance_trades WHERE order_id = ?", (order_id,))
            return cursor.fetchone() is not None

    def cleanup_old_trades(self, retention_days: int = 90) -> int:
        """Delete trades older than retention period."""
        from datetime import timedelta
        cutoff_ms = int((datetime.utcnow() - timedelta(days=retention_days)).timestamp() * 1000)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM binance_trades WHERE trade_time < ?", (cutoff_ms,))
            deleted = cursor.rowcount
            conn.commit()
            return deleted

    # ==================
    # analytics_snapshots CRUD
    # ==================

    def save_snapshot(self, snapshot: Dict[str, Any]) -> None:
        """Upsert daily analytics snapshot."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO analytics_snapshots (
                    snapshot_date, total_trades, win_rate, profit_factor,
                    total_net_pnl, rr_ratio, edge_pp, sharpe_per_trade,
                    max_drawdown, day_trades, day_net_pnl, day_win_rate,
                    p_value, version_tag, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(snapshot_date) DO UPDATE SET
                    total_trades = excluded.total_trades,
                    win_rate = excluded.win_rate,
                    profit_factor = excluded.profit_factor,
                    total_net_pnl = excluded.total_net_pnl,
                    rr_ratio = excluded.rr_ratio,
                    edge_pp = excluded.edge_pp,
                    sharpe_per_trade = excluded.sharpe_per_trade,
                    max_drawdown = excluded.max_drawdown,
                    day_trades = excluded.day_trades,
                    day_net_pnl = excluded.day_net_pnl,
                    day_win_rate = excluded.day_win_rate,
                    p_value = excluded.p_value,
                    version_tag = excluded.version_tag,
                    created_at = excluded.created_at
            ''', (
                snapshot['snapshot_date'], snapshot.get('total_trades', 0),
                snapshot.get('win_rate', 0), snapshot.get('profit_factor', 0),
                snapshot.get('total_net_pnl', 0), snapshot.get('rr_ratio', 0),
                snapshot.get('edge_pp', 0), snapshot.get('sharpe_per_trade', 0),
                snapshot.get('max_drawdown', 0),
                snapshot.get('day_trades', 0), snapshot.get('day_net_pnl', 0),
                snapshot.get('day_win_rate', 0),
                snapshot.get('p_value', 0), snapshot.get('version_tag', ''),
                snapshot.get('created_at', datetime.utcnow().isoformat()),
            ))
            conn.commit()

    def get_snapshots(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get recent snapshots."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM analytics_snapshots ORDER BY snapshot_date DESC LIMIT ?",
                (days,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_latest_snapshot(self) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM analytics_snapshots ORDER BY snapshot_date DESC LIMIT 1"
            )
            row = cursor.fetchone()
            return dict(row) if row else None
