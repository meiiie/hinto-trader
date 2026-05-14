import sqlite3
import json
from typing import List, Optional, Tuple
from datetime import datetime
from contextlib import contextmanager
from src.domain.entities.paper_position import PaperPosition
from src.domain.repositories.i_order_repository import IOrderRepository


def _parse_datetime(value) -> Optional[datetime]:
    """
    SOTA: Robust datetime parsing that handles multiple formats.
    Returns timezone-NAIVE datetime for compatibility with datetime.now().

    Handles:
    - Standard ISO format (2025-12-28T12:00:00)
    - UTC 'Z' suffix (2025-12-28T12:00:00Z)
    - Timezone offset (2025-12-28T12:00:00+00:00)
    - None/empty values
    """
    if not value:
        return None

    try:
        # Handle string type
        if isinstance(value, str):
            # Replace 'Z' suffix with UTC offset (Python < 3.11 compatibility)
            normalized = value.replace('Z', '+00:00')
            parsed = datetime.fromisoformat(normalized)
            # CRITICAL: Strip timezone to return naive datetime
            # This ensures compatibility with datetime.now() comparisons
            if parsed.tzinfo is not None:
                parsed = parsed.replace(tzinfo=None)
            return parsed
        # If already datetime, strip timezone if present
        elif isinstance(value, datetime):
            if value.tzinfo is not None:
                return value.replace(tzinfo=None)
            return value
        else:
            return None
    except (ValueError, TypeError):
        return None

class SQLiteOrderRepository(IOrderRepository):
    """SQLite implementation of Position Repository (Futures)"""

    def __init__(self, db_path: str = "data/trading_system.db"):
        self.db_path = db_path
        self._init_tables()

    def _init_tables(self) -> None:
        """Initialize database tables if they don't exist"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Paper positions table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS paper_positions (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    status TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    quantity REAL NOT NULL,
                    leverage INTEGER DEFAULT 1,
                    margin REAL NOT NULL,
                    liquidation_price REAL,
                    stop_loss REAL DEFAULT 0,
                    take_profit REAL DEFAULT 0,
                    open_time TEXT NOT NULL,
                    close_time TEXT,
                    realized_pnl REAL DEFAULT 0,
                    exit_reason TEXT,
                    highest_price REAL DEFAULT 0,
                    lowest_price REAL DEFAULT 0,
                    signal_metadata TEXT
                )
            ''')

            # Paper account table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS paper_account (
                    id INTEGER PRIMARY KEY,
                    balance REAL NOT NULL DEFAULT 10000.0
                )
            ''')

            # Settings table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # SOTA (Jan 2026): Live positions table for persisting TP/SL across restarts
            # Mirrors paper_positions structure for consistency
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS live_positions (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    entry_price REAL NOT NULL,
                    quantity REAL NOT NULL,
                    leverage INTEGER DEFAULT 1,
                    margin REAL DEFAULT 0,
                    stop_loss REAL DEFAULT 0,
                    take_profit REAL DEFAULT 0,
                    sl_order_id TEXT,
                    tp_order_id TEXT,
                    open_time TEXT NOT NULL,
                    close_time TEXT,
                    realized_pnl REAL DEFAULT 0,
                    exit_reason TEXT,
                    highest_price REAL DEFAULT 0,
                    lowest_price REAL DEFAULT 0,
                    signal_id TEXT
                )
            ''')

            # Initialize account if not exists
            cursor.execute('SELECT COUNT(*) FROM paper_account')
            if cursor.fetchone()[0] == 0:
                cursor.execute('INSERT INTO paper_account (id, balance) VALUES (1, 10000.0)')

            # Create indexes for performance
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_paper_positions_status ON paper_positions(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_paper_positions_entry_time ON paper_positions(open_time)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_live_positions_status ON live_positions(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_live_positions_symbol ON live_positions(symbol)')

            # SOTA (Jan 2026): Migration - Add ATR column if not exists
            # Required for trailing stop logic consistency with Backtest
            try:
                cursor.execute('ALTER TABLE paper_positions ADD COLUMN atr REAL DEFAULT 0')
            except sqlite3.OperationalError:
                pass  # Column already exists

            try:
                cursor.execute('ALTER TABLE live_positions ADD COLUMN atr REAL DEFAULT 0')
            except sqlite3.OperationalError:
                pass  # Column already exists

            # SOTA (Jan 2026): Migration - Add partial TP fields
            try:
                cursor.execute('ALTER TABLE paper_positions ADD COLUMN tp_hit_count INTEGER DEFAULT 0')
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute('ALTER TABLE paper_positions ADD COLUMN initial_quantity REAL DEFAULT 0')
            except sqlite3.OperationalError:
                pass

            # Paper-real provenance: keep source signal quality after converting
            # a signal into a pending paper order.
            try:
                cursor.execute('ALTER TABLE paper_positions ADD COLUMN signal_id TEXT')
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute('ALTER TABLE paper_positions ADD COLUMN confidence REAL')
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute('ALTER TABLE paper_positions ADD COLUMN confidence_level TEXT')
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute('ALTER TABLE paper_positions ADD COLUMN risk_reward_ratio REAL')
            except sqlite3.OperationalError:
                pass

            # SOTA FIX (Jan 2026): Add tp_hit_count to live_positions for TP tracking
            try:
                cursor.execute('ALTER TABLE live_positions ADD COLUMN tp_hit_count INTEGER DEFAULT 0')
            except sqlite3.OperationalError:
                pass  # Column already exists

            # SOTA FIX (Jan 2026): Add phase column for trailing stop state persistence
            # Required for correct trailing stop behavior after backend restart
            # Values: 'ENTRY', 'BREAKEVEN', 'TRAILING', 'CLOSED'
            try:
                cursor.execute('ALTER TABLE live_positions ADD COLUMN phase TEXT DEFAULT "ENTRY"')
            except sqlite3.OperationalError:
                pass  # Column already exists

            # SOTA FIX (Jan 2026): Add is_breakeven flag for backward compatibility
            # True when breakeven has been triggered (SL moved to entry)
            try:
                cursor.execute('ALTER TABLE live_positions ADD COLUMN is_breakeven INTEGER DEFAULT 0')
            except sqlite3.OperationalError:
                pass  # Column already exists

            # SOTA (Feb 2026): Add exit_price column for daily CSV export
            try:
                cursor.execute('ALTER TABLE live_positions ADD COLUMN exit_price REAL DEFAULT 0')
            except sqlite3.OperationalError:
                pass  # Column already exists

            # v6.3.0: Analytics tables (binance_trades + analytics_snapshots)
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
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_binance_trades_time ON binance_trades(trade_time)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_binance_trades_symbol ON binance_trades(symbol)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_binance_trades_version ON binance_trades(version_tag)')

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

    @contextmanager
    def _get_connection(self):
        """Context manager for database connection with WAL mode."""
        conn = sqlite3.connect(self.db_path)
        # SOTA: Enable WAL mode for concurrency (Write-Ahead Logging)
        # This prevents writers from blocking readers
        conn.execute('PRAGMA journal_mode=WAL;')
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def save_order(self, position: PaperPosition) -> None:
        """Save a new position (or replace if exists)"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO paper_positions (
                    id, symbol, side, status, entry_price, quantity,
                    leverage, margin, liquidation_price,
                    stop_loss, take_profit,
                    open_time, close_time, realized_pnl, exit_reason,
                    highest_price, lowest_price, atr,
                    signal_id, confidence, confidence_level, risk_reward_ratio
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                position.id, position.symbol, position.side, position.status,
                position.entry_price, position.quantity,
                position.leverage, position.margin, position.liquidation_price,
                position.stop_loss, position.take_profit,
                position.open_time.isoformat(),
                position.close_time.isoformat() if position.close_time else None,
                position.realized_pnl, position.exit_reason,
                position.highest_price, position.lowest_price,
                position.atr,
                position.signal_id, position.confidence,
                position.confidence_level, position.risk_reward_ratio
            ))
            conn.commit()

    def update_order(self, position: PaperPosition) -> None:
        """Update an existing position"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE paper_positions SET
                    status = ?,
                    close_time = ?,
                    realized_pnl = ?,
                    exit_reason = ?,
                    entry_price = ?,
                    quantity = ?,
                    margin = ?,
                    liquidation_price = ?,
                    stop_loss = ?,
                    highest_price = ?,
                    lowest_price = ?
                WHERE id = ?
            ''', (
                position.status,
                position.close_time.isoformat() if position.close_time else None,
                position.realized_pnl,
                position.exit_reason,
                position.entry_price,
                position.quantity,
                position.margin,
                position.liquidation_price,
                position.stop_loss,
                position.highest_price,
                position.lowest_price,
                position.id
            ))
            conn.commit()

    def get_order(self, position_id: str) -> Optional[PaperPosition]:
        """Get position by ID"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM paper_positions WHERE id = ?', (position_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_position(row)
            return None

    def get_active_orders(self) -> List[PaperPosition]:
        """Get all active positions (OPEN)"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM paper_positions WHERE status = 'OPEN'")
            rows = cursor.fetchall()
            return [self._row_to_position(row) for row in rows]

    def get_pending_orders(self) -> List[PaperPosition]:
        """Get all pending orders (PENDING)"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM paper_positions WHERE status = 'PENDING'")
            rows = cursor.fetchall()
            return [self._row_to_position(row) for row in rows]

    def get_closed_orders(self, limit: int = 50) -> List[PaperPosition]:
        """Get closed positions"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM paper_positions WHERE status = 'CLOSED' ORDER BY close_time DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            return [self._row_to_position(row) for row in rows]

    def get_account_balance(self) -> float:
        """Get current wallet balance"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT balance FROM paper_account WHERE id = 1')
            row = cursor.fetchone()
            if row:
                return row['balance']
            return 10000.0 # Default fallback

    def update_account_balance(self, balance: float) -> None:
        """Update wallet balance"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE paper_account SET balance = ? WHERE id = 1', (balance,))
            conn.commit()

    def _row_to_position(self, row) -> PaperPosition:
        """Convert DB row to PaperPosition object"""
        def row_value(key, default=None):
            try:
                return row[key]
            except (IndexError, KeyError, ValueError):
                return default

        # Handle new columns if they exist (or default to 0.0)
        # Since we are using sqlite3.Row, we can check keys or use try/except
        try:
            highest_price = row['highest_price']
            lowest_price = row['lowest_price']
        except IndexError: # If accessed by index
             highest_price = 0.0
             lowest_price = 0.0
        except ValueError: # If accessed by name but missing
             highest_price = 0.0
             lowest_price = 0.0
        except: # Fallback
             highest_price = 0.0
             lowest_price = 0.0

        # SOTA (Jan 2026): Load ATR for trailing stop
        try:
            atr = row['atr'] or 0.0
        except:
            atr = 0.0

        return PaperPosition(
            id=row['id'],
            symbol=row['symbol'],
            side=row['side'],
            status=row['status'],
            entry_price=row['entry_price'],
            quantity=row['quantity'],
            leverage=row['leverage'],
            margin=row['margin'],
            liquidation_price=row['liquidation_price'],
            stop_loss=row['stop_loss'],
            take_profit=row['take_profit'],
            open_time=_parse_datetime(row['open_time']) or datetime.now(),  # SOTA: Safe parsing
            close_time=_parse_datetime(row['close_time']),  # SOTA: Safe parsing (can be None)
            realized_pnl=row['realized_pnl'],
            exit_reason=row['exit_reason'],
            highest_price=highest_price,
            lowest_price=lowest_price,
            atr=atr,
            signal_id=row_value('signal_id'),
            confidence=row_value('confidence'),
            confidence_level=row_value('confidence_level'),
            risk_reward_ratio=row_value('risk_reward_ratio')
        )

    def reset_database(self) -> None:
        """Reset database (Clear all data)"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Clear tables
            cursor.execute("DELETE FROM paper_positions")
            # Reset account balance
            cursor.execute("UPDATE paper_account SET balance = 10000.0 WHERE id = 1")
            conn.commit()

    def get_closed_orders_paginated(
        self, page: int, limit: int,
        symbol: Optional[str] = None,
        side: Optional[str] = None,
        pnl_filter: Optional[str] = None  # 'profit', 'loss', or None for all
    ) -> Tuple[List[PaperPosition], int]:
        """
        Get closed orders with pagination and optional filters.

        SOTA Phase 24c: Server-side filtering before pagination.

        Args:
            page: Page number (1-indexed)
            limit: Number of items per page
            symbol: Optional filter by symbol (e.g., 'BTCUSDT')
            side: Optional filter by side ('LONG' or 'SHORT')
            pnl_filter: 'profit' for P&L > 0, 'loss' for P&L < 0, None for all

        Returns:
            Tuple of (list of positions, total count matching filters)
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Build dynamic WHERE clause
            where_clauses = ["status = 'CLOSED'"]
            params: List = []

            if symbol:
                where_clauses.append("symbol = ?")
                params.append(symbol.lower())  # SOTA FIX: DB stores lowercase (bnbusdt not BNBUSDT)

            if side:
                where_clauses.append("side = ?")
                params.append(side.upper())

            if pnl_filter == 'profit':
                where_clauses.append("realized_pnl > 0")
            elif pnl_filter == 'loss':
                where_clauses.append("realized_pnl < 0")

            where_sql = " AND ".join(where_clauses)

            # Get total count (with filters)
            cursor.execute(f"SELECT COUNT(*) FROM paper_positions WHERE {where_sql}", params)
            total_count = cursor.fetchone()[0]

            # Get paginated results (sorted by close_time descending)
            offset = (page - 1) * limit
            cursor.execute(f"""
                SELECT * FROM paper_positions
                WHERE {where_sql}
                ORDER BY open_time DESC
                LIMIT ? OFFSET ?
            """, params + [limit, offset])

            rows = cursor.fetchall()
            positions = [self._row_to_position(row) for row in rows]

            return positions, total_count

    # Settings methods
    def get_setting(self, key: str) -> Optional[str]:
        """Get a setting value by key"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
            row = cursor.fetchone()
            return row['value'] if row else None

    def set_setting(self, key: str, value: str) -> None:
        """Set a setting value"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
            ''', (key, value, datetime.now().isoformat()))
            conn.commit()

    def get_all_settings(self) -> dict:
        """Get all settings as a dictionary"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT key, value FROM settings')
            rows = cursor.fetchall()
            return {row['key']: row['value'] for row in rows}

    # =========================================================================
    # LIVE POSITIONS CRUD (SOTA Jan 2026)
    # Persists TP/SL data across bot restarts
    # =========================================================================

    def save_live_position(self, symbol: str, side: str, entry_price: float,
                          quantity: float, stop_loss: float, take_profit: float,
                          leverage: int = 1, signal_id: str = None,
                          atr: float = 0.0, phase: str = 'ENTRY',
                          is_breakeven: bool = False) -> str:
        """
        Save a new live position with SL/TP from signal.

        SOTA: If a position for this symbol already exists, close it first.
        This prevents duplicate entries.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            side: 'LONG' or 'SHORT'
            entry_price: Entry price
            quantity: Position size
            stop_loss: Stop loss price from signal
            take_profit: Take profit price from signal
            leverage: Position leverage
            signal_id: Optional signal ID for tracing
            atr: ATR value for trailing stop (SOTA Jan 2026)
            phase: Position phase ('ENTRY', 'BREAKEVEN', 'TRAILING') - SOTA Jan 2026
            is_breakeven: True if breakeven triggered - SOTA Jan 2026

        Returns:
            Position ID
        """
        symbol_upper = symbol.upper()
        position_id = f"live_{symbol_upper}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # First, mark any existing OPEN positions for this symbol as REPLACED
            cursor.execute('''
                UPDATE live_positions
                SET status = 'REPLACED', close_time = ?
                WHERE symbol = ? AND status = 'OPEN'
            ''', (datetime.now().isoformat(), symbol_upper))

            # Then insert the new position (SOTA: include ATR, phase, is_breakeven for trailing)
            cursor.execute('''
                INSERT INTO live_positions
                (id, symbol, side, status, entry_price, quantity, leverage,
                 stop_loss, take_profit, open_time, highest_price, lowest_price,
                 signal_id, atr, phase, is_breakeven)
                VALUES (?, ?, ?, 'OPEN', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                position_id, symbol_upper, side, entry_price, quantity, leverage,
                stop_loss, take_profit, datetime.now().isoformat(),
                entry_price if side == 'LONG' else 0,
                entry_price if side == 'SHORT' else float('inf'),
                signal_id,
                atr,  # SOTA: Persist ATR for trailing stop after restart
                phase,  # SOTA: Persist phase for state recovery
                1 if is_breakeven else 0  # SOTA: Persist is_breakeven flag
            ))
            conn.commit()

        return position_id

    def get_open_live_positions(self) -> List[dict]:
        """
        Get all open live positions with their SL/TP.

        SOTA: Returns only the LATEST entry per symbol to handle duplicates.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Use subquery to get only the latest entry per symbol
            cursor.execute('''
                SELECT * FROM live_positions lp
                WHERE status = 'OPEN'
                AND open_time = (
                    SELECT MAX(open_time) FROM live_positions
                    WHERE symbol = lp.symbol AND status = 'OPEN'
                )
            ''')
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_all_live_positions(self) -> List[dict]:
        """
        SOTA (Feb 2026): Get ALL live positions (OPEN + CLOSED).
        Used by daily summary to query today's closed trades.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM live_positions ORDER BY open_time DESC')
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_live_position_by_symbol(self, symbol: str) -> Optional[dict]:
        """Get open live position by symbol."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM live_positions
                WHERE symbol = ? AND status = 'OPEN'
                ORDER BY open_time DESC LIMIT 1
            ''', (symbol.upper(),))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_live_position_sl(self, symbol: str, new_sl: float, sl_order_id: str = None):
        """Update stop loss for a live position (trailing stop)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if sl_order_id:
                cursor.execute('''
                    UPDATE live_positions
                    SET stop_loss = ?, sl_order_id = ?
                    WHERE symbol = ? AND status = 'OPEN'
                ''', (new_sl, sl_order_id, symbol.upper()))
            else:
                cursor.execute('''
                    UPDATE live_positions
                    SET stop_loss = ?
                    WHERE symbol = ? AND status = 'OPEN'
                ''', (new_sl, symbol.upper()))
            conn.commit()

    def update_live_position_watermarks(self, symbol: str, highest: float, lowest: float):
        """Update price watermarks for trailing stop calculation."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE live_positions
                SET highest_price = MAX(highest_price, ?),
                    lowest_price = MIN(lowest_price, ?)
                WHERE symbol = ? AND status = 'OPEN'
            ''', (highest, lowest, symbol.upper()))
            conn.commit()

    def update_live_position_tp_hit_count(self, symbol: str, tp_hit_count: int):
        """
        SOTA FIX (Jan 2026): Update tp_hit_count for a live position.

        Called when TP1 is hit to persist the state for restart recovery.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            tp_hit_count: Number of TP levels hit (1, 2, or 3)
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE live_positions
                SET tp_hit_count = ?
                WHERE symbol = ? AND status = 'OPEN'
            ''', (tp_hit_count, symbol.upper()))
            conn.commit()

    def update_live_position_phase(self, symbol: str, phase: str, is_breakeven: bool):
        """
        SOTA FIX (Jan 2026): Update phase and is_breakeven for a live position.

        Called when position transitions to BREAKEVEN or TRAILING phase.
        Critical for trailing stop to work correctly after backend restart.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            phase: Position phase ('ENTRY', 'BREAKEVEN', 'TRAILING', 'CLOSED')
            is_breakeven: True if breakeven has been triggered
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE live_positions
                SET phase = ?, is_breakeven = ?
                WHERE symbol = ? AND status = 'OPEN'
            ''', (phase, 1 if is_breakeven else 0, symbol.upper()))
            conn.commit()

    def close_live_position(self, symbol: str, exit_price: float,
                           realized_pnl: float, exit_reason: str = 'MANUAL'):
        """Close a live position with exit price for daily CSV export."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE live_positions
                SET status = 'CLOSED', close_time = ?, exit_price = ?,
                    realized_pnl = ?, exit_reason = ?
                WHERE symbol = ? AND status = 'OPEN'
            ''', (datetime.now().isoformat(), exit_price, realized_pnl,
                  exit_reason, symbol.upper()))
            conn.commit()

    def remove_live_position(self, symbol: str):
        """Remove live position when position no longer exists on exchange."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM live_positions
                WHERE symbol = ? AND status = 'OPEN'
            ''', (symbol.upper(),))
            conn.commit()

    # =========================================================================
    # PENDING ORDERS CRUD (SOTA Jan 2026)
    # Persists pending limit orders with TP/SL for restart recovery
    # =========================================================================

    def save_pending_live_order(self, symbol: str, order_id: str, side: str,
                                entry_price: float, quantity: float,
                                stop_loss: float, take_profit: float,
                                leverage: int = 1) -> str:
        """
        SOTA: Save pending limit order with TP/SL for restart recovery.

        When limit order is placed, save its TP/SL info immediately.
        This allows recovery of TP/SL even if bot restarts before fill.
        """
        symbol_upper = symbol.upper()
        position_id = f"pending_{symbol_upper}_{order_id}"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO live_positions
                (id, symbol, side, status, entry_price, quantity, leverage,
                 stop_loss, take_profit, open_time, signal_id)
                VALUES (?, ?, ?, 'PENDING', ?, ?, ?, ?, ?, ?, ?)
            ''', (
                position_id, symbol_upper, side, entry_price, quantity, leverage,
                stop_loss, take_profit, datetime.now().isoformat(), str(order_id)
            ))
            conn.commit()

        return position_id

    def get_pending_live_orders(self) -> List[dict]:
        """Get all pending live orders with their TP/SL."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM live_positions WHERE status = 'PENDING'")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_pending_order_by_symbol(self, symbol: str) -> Optional[dict]:
        """Get pending order by symbol."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM live_positions
                WHERE symbol = ? AND status = 'PENDING'
                ORDER BY open_time DESC LIMIT 1
            ''', (symbol.upper(),))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_pending_to_open(self, symbol: str, entry_price: float, quantity: float):
        """Update pending order to OPEN when it fills."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE live_positions
                SET status = 'OPEN', entry_price = ?, quantity = ?
                WHERE symbol = ? AND status = 'PENDING'
            ''', (entry_price, quantity, symbol.upper()))
            conn.commit()

    def remove_pending_order(self, symbol: str):
        """Remove pending order (cancelled or expired)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM live_positions
                WHERE symbol = ? AND status = 'PENDING'
            ''', (symbol.upper(),))
            conn.commit()

    def remove_stale_watermark(self, symbol: str):
        """
        SOTA FIX (Jan 2026): Remove stale live position from DB.

        Called when a position no longer exists on exchange but is still in DB.
        This prevents ghost position tracking after manual closes or missed events.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Set status to GHOST_CLOSED (don't delete - keep for history)
            cursor.execute('''
                UPDATE live_positions
                SET status = 'GHOST_CLOSED', close_time = CURRENT_TIMESTAMP, exit_reason = 'STALE_CLEANUP'
                WHERE symbol = ? AND status IN ('OPEN', 'PENDING')
            ''', (symbol.upper(),))
            conn.commit()

    # =========================================================================
    # DAILY CLEANUP (SOTA Feb 2026)
    # Prevents unbounded DB growth on EC2
    # =========================================================================

    def cleanup_old_signals(self, retention_days: int = 7) -> int:
        """
        Delete signals older than retention_days.

        Signals table grows ~2,800 rows/day. With 7-day retention,
        max rows stays around ~20K instead of unbounded.

        Returns:
            Number of rows deleted.
        """
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Check if signals table exists (it's in the same DB on EC2)
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='signals'"
            )
            if not cursor.fetchone():
                return 0

            cursor.execute(
                "DELETE FROM signals WHERE generated_at < ?", (cutoff,)
            )
            deleted = cursor.rowcount
            conn.commit()
            return deleted

    def cleanup_ghost_positions(self, max_age_hours: int = 24) -> int:
        """
        Soft-close OPEN positions older than max_age_hours as GHOST_CLOSED.

        Ghost positions are OPEN records in DB that no longer exist on exchange
        (e.g., from restarts, manual closes). Marking them GHOST_CLOSED preserves
        history while removing them from active queries.

        Returns:
            Number of positions soft-closed.
        """
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(hours=max_age_hours)).isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE live_positions
                SET status = 'GHOST_CLOSED', exit_reason = 'GHOST_CLEANUP',
                    close_time = ?
                WHERE status = 'OPEN' AND open_time < ?
            ''', (datetime.now().isoformat(), cutoff))
            closed = cursor.rowcount
            conn.commit()
            return closed

    def cleanup_old_closed_positions(self, retention_days: int = 30) -> int:
        """
        Delete CLOSED/REPLACED/GHOST_CLOSED positions older than retention_days.

        Daily CSV export already captures trade history, so old closed records
        can be safely purged after 30 days.

        Returns:
            Number of rows deleted.
        """
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM live_positions
                WHERE status IN ('CLOSED', 'REPLACED', 'GHOST_CLOSED')
                AND open_time < ?
            ''', (cutoff,))
            deleted = cursor.rowcount
            conn.commit()
            return deleted

    def vacuum_database(self) -> float:
        """
        Run VACUUM to reclaim disk space after deletions.

        Returns:
            New database size in MB.
        """
        import os
        # VACUUM cannot run inside a transaction, use raw connection
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute('VACUUM')
        finally:
            conn.close()

        # Return file size in MB
        try:
            size_bytes = os.path.getsize(self.db_path)
            return round(size_bytes / (1024 * 1024), 2)
        except OSError:
            return 0.0
