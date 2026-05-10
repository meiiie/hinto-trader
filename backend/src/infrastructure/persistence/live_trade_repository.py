"""
Live Trade Repository - Trade Persistence for Backtest-Mode Live Trading

Persists trades, orders, and candle buffers to SQLite database.
Enables state recovery after restart.

SOTA (Jan 2026): Reuses existing SQLiteOrderRepository infrastructure
"""

import sqlite3
import json
import csv
from typing import List, Optional, Dict
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager


class LiveTradeRepository:
    """
    Repository for persisting live trading data.

    Responsibilities:
    - Save/load trades (filled orders)
    - Save/load pending orders
    - Export trades to CSV (matching backtest format)
    - Save/load candle history buffers
    - Provide state recovery on restart
    """

    def __init__(self, db_path: str = "data/live_trading.db"):
        """
        Initialize Live Trade Repository.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._ensure_db_directory()
        self._init_tables()

    def _ensure_db_directory(self):
        """Ensure database directory exists"""
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _get_connection(self):
        """Context manager for database connection with WAL mode"""
        conn = sqlite3.connect(self.db_path)
        # Enable WAL mode for concurrency
        conn.execute('PRAGMA journal_mode=WAL;')
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_tables(self):
        """Initialize database tables"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Trades table (filled orders)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS live_trades (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    quantity REAL NOT NULL,
                    leverage INTEGER NOT NULL,
                    margin REAL NOT NULL,
                    notional REAL NOT NULL,

                    -- TP/SL
                    initial_sl REAL NOT NULL,
                    initial_tp REAL NOT NULL,
                    final_sl REAL,

                    -- Timestamps
                    entry_time TEXT NOT NULL,
                    exit_time TEXT,

                    -- P&L
                    gross_pnl REAL DEFAULT 0,
                    entry_fee REAL DEFAULT 0,
                    exit_fee REAL DEFAULT 0,
                    funding_fee REAL DEFAULT 0,
                    net_pnl REAL DEFAULT 0,

                    -- Exit info
                    exit_reason TEXT,
                    tp_hit_count INTEGER DEFAULT 0,

                    -- Signal info
                    confidence REAL,
                    atr REAL,

                    -- Status
                    status TEXT NOT NULL DEFAULT 'OPEN'
                )
            ''')

            # Pending orders table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS live_pending_orders (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    target_price REAL NOT NULL,
                    quantity REAL NOT NULL,
                    leverage INTEGER NOT NULL,

                    -- TP/SL (for when order fills)
                    stop_loss REAL NOT NULL,
                    take_profit REAL NOT NULL,

                    -- Signal info
                    confidence REAL,
                    atr REAL,

                    -- TTL
                    created_at TEXT NOT NULL,
                    ttl_minutes INTEGER NOT NULL,
                    expires_at TEXT NOT NULL,

                    -- Status
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    cancelled_reason TEXT
                )
            ''')

            # Candle buffers table (for state recovery)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS live_candle_buffers (
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    candles_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (symbol, timeframe)
                )
            ''')

            # System state table (balance, etc.)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS live_system_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            ''')

            # Create indexes for performance
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_live_trades_symbol ON live_trades(symbol)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_live_trades_status ON live_trades(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_live_trades_entry_time ON live_trades(entry_time)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_live_pending_symbol ON live_pending_orders(symbol)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_live_pending_status ON live_pending_orders(status)')

            conn.commit()

    # =========================================================================
    # TRADES CRUD
    # =========================================================================

    def save_trade(self, trade: Dict) -> None:
        """
        Save a trade (filled order).

        Args:
            trade: Trade dict with all fields
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO live_trades (
                    id, symbol, side, entry_price, exit_price, quantity, leverage, margin, notional,
                    initial_sl, initial_tp, final_sl,
                    entry_time, exit_time,
                    gross_pnl, entry_fee, exit_fee, funding_fee, net_pnl,
                    exit_reason, tp_hit_count,
                    confidence, atr,
                    status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                trade['id'],
                trade['symbol'],
                trade['side'],
                trade['entry_price'],
                trade.get('exit_price'),
                trade['quantity'],
                trade['leverage'],
                trade['margin'],
                trade['notional'],
                trade['initial_sl'],
                trade['initial_tp'],
                trade.get('final_sl'),
                trade['entry_time'],
                trade.get('exit_time'),
                trade.get('gross_pnl', 0),
                trade.get('entry_fee', 0),
                trade.get('exit_fee', 0),
                trade.get('funding_fee', 0),
                trade.get('net_pnl', 0),
                trade.get('exit_reason'),
                trade.get('tp_hit_count', 0),
                trade.get('confidence'),
                trade.get('atr'),
                trade.get('status', 'OPEN')
            ))
            conn.commit()

    def update_trade(self, trade_id: str, updates: Dict) -> None:
        """
        Update a trade.

        Args:
            trade_id: Trade ID
            updates: Dict of fields to update
        """
        if not updates:
            return

        # Build dynamic UPDATE query
        set_clauses = []
        values = []

        for key, value in updates.items():
            set_clauses.append(f"{key} = ?")
            values.append(value)

        values.append(trade_id)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = f"UPDATE live_trades SET {', '.join(set_clauses)} WHERE id = ?"
            cursor.execute(query, values)
            conn.commit()

    def get_trade(self, trade_id: str) -> Optional[Dict]:
        """Get trade by ID"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM live_trades WHERE id = ?', (trade_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_open_trades(self) -> List[Dict]:
        """Get all open trades"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM live_trades WHERE status = 'OPEN' ORDER BY entry_time")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_closed_trades(self, limit: int = 100) -> List[Dict]:
        """Get closed trades"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM live_trades WHERE status = 'CLOSED' ORDER BY exit_time DESC LIMIT ?",
                (limit,)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_all_trades(self) -> List[Dict]:
        """Get all trades (for export)"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM live_trades ORDER BY entry_time")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    # =========================================================================
    # PENDING ORDERS CRUD
    # =========================================================================

    def save_pending_order(self, order: Dict) -> None:
        """Save a pending order"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO live_pending_orders (
                    id, symbol, side, target_price, quantity, leverage,
                    stop_loss, take_profit,
                    confidence, atr,
                    created_at, ttl_minutes, expires_at,
                    status, cancelled_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                order['id'],
                order['symbol'],
                order['side'],
                order['target_price'],
                order['quantity'],
                order['leverage'],
                order['stop_loss'],
                order['take_profit'],
                order.get('confidence'),
                order.get('atr'),
                order['created_at'],
                order['ttl_minutes'],
                order['expires_at'],
                order.get('status', 'PENDING'),
                order.get('cancelled_reason')
            ))
            conn.commit()

    def update_pending_order(self, order_id: str, updates: Dict) -> None:
        """Update a pending order"""
        if not updates:
            return

        set_clauses = []
        values = []

        for key, value in updates.items():
            set_clauses.append(f"{key} = ?")
            values.append(value)

        values.append(order_id)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = f"UPDATE live_pending_orders SET {', '.join(set_clauses)} WHERE id = ?"
            cursor.execute(query, values)
            conn.commit()

    def get_pending_order(self, order_id: str) -> Optional[Dict]:
        """Get pending order by ID"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM live_pending_orders WHERE id = ?', (order_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_pending_orders(self) -> List[Dict]:
        """Get all pending orders"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM live_pending_orders WHERE status = 'PENDING' ORDER BY created_at")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def remove_pending_order(self, order_id: str) -> None:
        """Remove a pending order (filled or cancelled)"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM live_pending_orders WHERE id = ?', (order_id,))
            conn.commit()

    # =========================================================================
    # CANDLE BUFFERS PERSISTENCE
    # =========================================================================

    def save_candle_buffer(self, symbol: str, timeframe: str, candles: List[Dict]) -> None:
        """
        Save candle buffer to disk.

        Args:
            symbol: Symbol (e.g., 'btcusdt')
            timeframe: Timeframe (e.g., '15m')
            candles: List of candle dicts
        """
        candles_json = json.dumps(candles)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO live_candle_buffers (symbol, timeframe, candles_json, updated_at)
                VALUES (?, ?, ?, ?)
            ''', (symbol, timeframe, candles_json, datetime.now(timezone.utc).isoformat()))
            conn.commit()

    def load_candle_buffer(self, symbol: str, timeframe: str) -> Optional[List[Dict]]:
        """
        Load candle buffer from disk.

        Args:
            symbol: Symbol (e.g., 'btcusdt')
            timeframe: Timeframe (e.g., '15m')

        Returns:
            List of candle dicts or None if not found
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT candles_json FROM live_candle_buffers WHERE symbol = ? AND timeframe = ?',
                (symbol, timeframe)
            )
            row = cursor.fetchone()

            if row:
                return json.loads(row['candles_json'])
            return None

    # =========================================================================
    # SYSTEM STATE PERSISTENCE
    # =========================================================================

    def save_state(self, key: str, value: str) -> None:
        """Save system state"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO live_system_state (key, value, updated_at)
                VALUES (?, ?, ?)
            ''', (key, value, datetime.now(timezone.utc).isoformat()))
            conn.commit()

    def load_state(self, key: str) -> Optional[str]:
        """Load system state"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT value FROM live_system_state WHERE key = ?', (key,))
            row = cursor.fetchone()
            return row['value'] if row else None

    def save_balance(self, balance: float) -> None:
        """Save current balance"""
        self.save_state('balance', str(balance))

    def load_balance(self) -> Optional[float]:
        """Load balance from disk"""
        value = self.load_state('balance')
        return float(value) if value else None

    # =========================================================================
    # CSV EXPORT (matching backtest format)
    # =========================================================================

    def export_to_csv(self, filepath: str) -> None:
        """
        Export trades to CSV format matching backtest.

        Args:
            filepath: Output CSV file path
        """
        trades = self.get_all_trades()

        if not trades:
            return

        # Ensure directory exists
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)

        # CSV headers matching backtest format
        headers = [
            'symbol', 'side', 'entry_price', 'exit_price', 'quantity',
            'entry_time', 'exit_time', 'exit_reason',
            'gross_pnl', 'entry_fee', 'exit_fee', 'funding_fee', 'net_pnl',
            'leverage', 'margin', 'notional',
            'initial_sl', 'initial_tp', 'final_sl',
            'tp_hit_count', 'confidence', 'atr'
        ]

        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()

            for trade in trades:
                # Only export closed trades
                if trade['status'] != 'CLOSED':
                    continue

                row = {key: trade.get(key, '') for key in headers}
                writer.writerow(row)

    # =========================================================================
    # STATISTICS
    # =========================================================================

    def get_stats(self) -> Dict:
        """Get trading statistics"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Total trades
            cursor.execute("SELECT COUNT(*) FROM live_trades WHERE status = 'CLOSED'")
            total_trades = cursor.fetchone()[0]

            # Winning trades
            cursor.execute("SELECT COUNT(*) FROM live_trades WHERE status = 'CLOSED' AND net_pnl > 0")
            winning_trades = cursor.fetchone()[0]

            # Total P&L
            cursor.execute("SELECT SUM(net_pnl) FROM live_trades WHERE status = 'CLOSED'")
            total_pnl = cursor.fetchone()[0] or 0

            # Open positions
            cursor.execute("SELECT COUNT(*) FROM live_trades WHERE status = 'OPEN'")
            open_positions = cursor.fetchone()[0]

            # Pending orders
            cursor.execute("SELECT COUNT(*) FROM live_pending_orders WHERE status = 'PENDING'")
            pending_orders = cursor.fetchone()[0]

            return {
                'total_trades': total_trades,
                'winning_trades': winning_trades,
                'losing_trades': total_trades - winning_trades,
                'win_rate': (winning_trades / total_trades * 100) if total_trades > 0 else 0,
                'total_pnl': total_pnl,
                'open_positions': open_positions,
                'pending_orders': pending_orders
            }

    def close(self):
        """
        Close database connection and flush all pending writes.

        Called during graceful shutdown to ensure all data is persisted.
        """
        # Since we use context managers, connections are already closed
        # But we can ensure WAL checkpoint is executed
        try:
            with self._get_connection() as conn:
                # Force WAL checkpoint to flush all pending writes
                conn.execute('PRAGMA wal_checkpoint(FULL);')
                conn.commit()
        except Exception as e:
            # Log but don't raise - we're shutting down anyway
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Error during database close: {e}")
