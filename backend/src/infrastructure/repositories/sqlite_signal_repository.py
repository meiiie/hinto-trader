"""
SQLite Signal Repository - Infrastructure Layer

SQLite implementation of ISignalRepository for signal persistence.
Uses the existing paper_trading.db database.
"""

import sqlite3
import json
import logging
from datetime import datetime, timedelta
from typing import List, Optional
from pathlib import Path

from src.domain.entities.trading_signal import TradingSignal, SignalType
from src.domain.value_objects.signal_status import SignalStatus
from src.domain.repositories.i_signal_repository import ISignalRepository


class NumpyJSONEncoder(json.JSONEncoder):
    """
    Custom JSON encoder that handles numpy and datetime types.

    SOTA FIX: Signals contain numpy types from indicator calculations
    (pandas/numpy) that standard json.dumps() cannot serialize.
    """

    def default(self, obj):
        import numpy as np

        # Handle datetime
        if isinstance(obj, datetime):
            return obj.isoformat()

        # Handle numpy bool
        if isinstance(obj, (np.bool_, np.bool8)):
            return bool(obj)

        # Handle numpy integers
        if isinstance(obj, (np.integer, np.int64, np.int32, np.int16, np.int8)):
            return int(obj)

        # Handle numpy floats
        if isinstance(obj, (np.floating, np.float64, np.float32, np.float16)):
            return float(obj)

        # Handle numpy arrays
        if isinstance(obj, np.ndarray):
            return obj.tolist()

        return super().default(obj)


class SQLiteSignalRepository(ISignalRepository):
    """
    SQLite implementation of signal repository.

    Stores signals in a dedicated 'signals' table within
    the existing paper_trading.db database.
    """

    def __init__(self, db_path: str = "data/paper_trading.db"):
        """
        Initialize repository with database path.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self._ensure_table()
        self.logger.info(f"SQLiteSignalRepository initialized: {db_path}")

    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_table(self) -> None:
        """Create signals table if not exists."""
        # Ensure data directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL DEFAULT 'BTCUSDT',
                signal_type TEXT NOT NULL,
                status TEXT NOT NULL,
                confidence REAL NOT NULL,
                price REAL NOT NULL,
                entry_price REAL,
                stop_loss REAL,
                tp1 REAL,
                tp2 REAL,
                tp3 REAL,
                position_size REAL,
                risk_reward_ratio REAL,
                generated_at TIMESTAMP NOT NULL,
                pending_at TIMESTAMP,
                executed_at TIMESTAMP,
                expired_at TIMESTAMP,
                order_id TEXT,
                indicators_json TEXT,
                reasons_json TEXT,
                outcome_json TEXT
            )
        """)

        # Create indexes for common queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_signals_status
            ON signals(status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_signals_generated_at
            ON signals(generated_at DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_signals_order_id
            ON signals(order_id)
        """)

        # SOTA: Auto-migration for schema updates without manual intervention
        try:
            cursor.execute("PRAGMA table_info(signals)")
            existing_columns = {info[1] for info in cursor.fetchall()}

            # Map of column_name -> column_definition
            required_columns = {
                'symbol': "TEXT NOT NULL DEFAULT 'BTCUSDT'",
                'entry_price': "REAL",
                'stop_loss': "REAL",
                'tp1': "REAL",
                'tp2': "REAL",
                'tp3': "REAL",
                'position_size': "REAL",
                'risk_reward_ratio': "REAL",
                'pending_at': "TIMESTAMP",
                'executed_at': "TIMESTAMP",
                'expired_at': "TIMESTAMP",
                'order_id': "TEXT",
                'indicators_json': "TEXT",
                'reasons_json': "TEXT",
                'outcome_json': "TEXT"
            }

            for col_name, col_def in required_columns.items():
                if col_name not in existing_columns:
                    self.logger.warning(f"Schema mismatch: '{col_name}' column missing. Migrating...")
                    cursor.execute(f"ALTER TABLE signals ADD COLUMN {col_name} {col_def}")
                    self.logger.info(f"✅ Schema migration: Added '{col_name}' column")

            conn.commit()

        except Exception as e:
            self.logger.error(f"Migration check failed: {e}")

        conn.commit()
        conn.close()


    def save(self, signal: TradingSignal) -> None:
        """Persist a new signal."""
        conn = self._get_connection()
        cursor = conn.cursor()

        tp_levels = signal.tp_levels or {}

        try:
            cursor.execute("""
                INSERT INTO signals (
                    id, symbol, signal_type, status, confidence, price,
                    entry_price, stop_loss, tp1, tp2, tp3,
                    position_size, risk_reward_ratio,
                    generated_at, pending_at, executed_at, expired_at,
                    order_id, indicators_json, reasons_json, outcome_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                signal.id,
                signal.symbol,
                signal.signal_type.value,
                signal.status.value,
                signal.confidence,
                signal.price,
                signal.entry_price,
                signal.stop_loss,
                tp_levels.get('tp1'),
                tp_levels.get('tp2'),
                tp_levels.get('tp3'),
                signal.position_size,
                signal.risk_reward_ratio,
                signal.generated_at.isoformat() if signal.generated_at else datetime.now().isoformat(),
                signal.pending_at.isoformat() if signal.pending_at else None,
                signal.executed_at.isoformat() if signal.executed_at else None,
                signal.expired_at.isoformat() if signal.expired_at else None,
                signal.order_id,
                json.dumps(signal.indicators, cls=NumpyJSONEncoder),
                json.dumps(signal.reasons, cls=NumpyJSONEncoder),
                json.dumps(signal.outcome, cls=NumpyJSONEncoder) if signal.outcome else None
            ))

            conn.commit()
            self.logger.debug(f"Signal saved: {signal.id}")

        except Exception as e:
            self.logger.error(f"Error saving signal: {e}")
            raise
        finally:
            conn.close()

    def update(self, signal: TradingSignal) -> None:
        """Update existing signal."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                UPDATE signals SET
                    status = ?,
                    pending_at = ?,
                    executed_at = ?,
                    expired_at = ?,
                    order_id = ?,
                    outcome_json = ?
                WHERE id = ?
            """, (
                signal.status.value,
                signal.pending_at.isoformat() if signal.pending_at else None,
                signal.executed_at.isoformat() if signal.executed_at else None,
                signal.expired_at.isoformat() if signal.expired_at else None,
                signal.order_id,
                json.dumps(signal.outcome, cls=NumpyJSONEncoder) if signal.outcome else None,
                signal.id
            ))

            conn.commit()
            self.logger.debug(f"Signal updated: {signal.id}")

        except Exception as e:
            self.logger.error(f"Error updating signal: {e}")
            raise
        finally:
            conn.close()

    def get_by_id(self, signal_id: str) -> Optional[TradingSignal]:
        """Get signal by ID."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT * FROM signals WHERE id = ?", (signal_id,))
            row = cursor.fetchone()

            if row:
                return self._row_to_signal(row)
            return None

        finally:
            conn.close()

    def get_by_status(
        self,
        status: SignalStatus,
        limit: int = 50
    ) -> List[TradingSignal]:
        """Get signals by status."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT * FROM signals
                WHERE status = ?
                ORDER BY generated_at DESC
                LIMIT ?
            """, (status.value, limit))

            rows = cursor.fetchall()
            return [self._row_to_signal(row) for row in rows]

        finally:
            conn.close()

    def get_by_order_id(self, order_id: str) -> Optional[TradingSignal]:
        """Get signal linked to an order."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT * FROM signals WHERE order_id = ?", (order_id,))
            row = cursor.fetchone()

            if row:
                return self._row_to_signal(row)
            return None

        finally:
            conn.close()

    def get_history(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[TradingSignal]:
        """Get signal history with pagination."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            query = "SELECT * FROM signals WHERE 1=1"
            params = []

            if start_date:
                query += " AND generated_at >= ?"
                params.append(start_date.isoformat())

            if end_date:
                query += " AND generated_at <= ?"
                params.append(end_date.isoformat())

            query += " ORDER BY generated_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(query, params)
            rows = cursor.fetchall()

            return [self._row_to_signal(row) for row in rows]

        finally:
            conn.close()

    def get_pending_count(self) -> int:
        """Count pending signals."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                "SELECT COUNT(*) FROM signals WHERE status = ?",
                (SignalStatus.PENDING.value,)
            )
            return cursor.fetchone()[0]

        finally:
            conn.close()

    def get_total_count(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> int:
        """Get total count of signals for pagination."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            query = "SELECT COUNT(*) FROM signals WHERE 1=1"
            params = []

            if start_date:
                query += " AND generated_at >= ?"
                params.append(start_date.isoformat())

            if end_date:
                query += " AND generated_at <= ?"
                params.append(end_date.isoformat())

            cursor.execute(query, params)
            return cursor.fetchone()[0]

        finally:
            conn.close()

    def get_filtered_history(
        self,
        start_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
        symbol: Optional[str] = None,
        signal_type: Optional[str] = None,
        status: Optional[str] = None,
        min_confidence: Optional[float] = None
    ) -> List[TradingSignal]:
        """
        Get filtered signal history for analysis.

        SOTA Phase 25: Server-side filtering for signal research.

        Args:
            start_date: Filter signals after this date
            limit: Maximum number of results
            offset: Number of results to skip
            symbol: Filter by trading symbol (e.g., BTCUSDT)
            signal_type: Filter by type (buy or sell)
            status: Filter by status (generated, pending, executed, expired)
            min_confidence: Minimum confidence threshold

        Returns:
            List of filtered signals
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            query = "SELECT * FROM signals WHERE 1=1"
            params = []

            if start_date:
                query += " AND generated_at >= ?"
                params.append(start_date.isoformat())

            if symbol:
                query += " AND UPPER(symbol) = ?"
                params.append(symbol.upper())

            if signal_type:
                query += " AND signal_type = ?"
                params.append(signal_type.lower())

            if status:
                query += " AND status = ?"
                params.append(status.lower())

            if min_confidence is not None:
                query += " AND confidence >= ?"
                params.append(min_confidence)

            query += " ORDER BY generated_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(query, params)
            rows = cursor.fetchall()

            return [self._row_to_signal(row) for row in rows]

        finally:
            conn.close()

    def get_filtered_count(
        self,
        start_date: Optional[datetime] = None,
        symbol: Optional[str] = None,
        signal_type: Optional[str] = None,
        status: Optional[str] = None,
        min_confidence: Optional[float] = None
    ) -> int:
        """
        Get total count of filtered signals.

        Args:
            start_date: Filter signals after this date
            symbol: Filter by symbol
            signal_type: Filter by type
            status: Filter by status
            min_confidence: Minimum confidence

        Returns:
            Total count matching filters
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            query = "SELECT COUNT(*) FROM signals WHERE 1=1"
            params = []

            if start_date:
                query += " AND generated_at >= ?"
                params.append(start_date.isoformat())

            if symbol:
                query += " AND UPPER(symbol) = ?"
                params.append(symbol.upper())

            if signal_type:
                query += " AND signal_type = ?"
                params.append(signal_type.lower())

            if status:
                query += " AND status = ?"
                params.append(status.lower())

            if min_confidence is not None:
                query += " AND confidence >= ?"
                params.append(min_confidence)

            cursor.execute(query, params)
            return cursor.fetchone()[0]

        finally:
            conn.close()

    def expire_old_pending(self, ttl_seconds: int = 300) -> int:
        """Expire pending signals older than TTL."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cutoff = (datetime.now() - timedelta(seconds=ttl_seconds)).isoformat()
            now = datetime.now().isoformat()

            cursor.execute("""
                UPDATE signals
                SET status = ?, expired_at = ?
                WHERE status IN (?, ?) AND generated_at < ?
            """, (
                SignalStatus.EXPIRED.value,
                now,
                SignalStatus.GENERATED.value,
                SignalStatus.PENDING.value,
                cutoff
            ))

            count = cursor.rowcount
            conn.commit()

            return count

        finally:
            conn.close()

    def _row_to_signal(self, row: sqlite3.Row) -> TradingSignal:
        """Convert database row to TradingSignal entity."""
        # Build tp_levels dict
        tp_levels = {}
        if row['tp1']:
            tp_levels['tp1'] = row['tp1']
        if row['tp2']:
            tp_levels['tp2'] = row['tp2']
        if row['tp3']:
            tp_levels['tp3'] = row['tp3']

        # Parse JSON fields
        indicators = json.loads(row['indicators_json']) if row['indicators_json'] else {}
        reasons = json.loads(row['reasons_json']) if row['reasons_json'] else []
        outcome = json.loads(row['outcome_json']) if row['outcome_json'] else None

        # Parse timestamps
        def parse_dt(val):
            if val:
                return datetime.fromisoformat(val)
            return None

        return TradingSignal(
            id=row['id'],
            symbol=row['symbol'] if row['symbol'] else 'BTCUSDT',
            signal_type=SignalType(row['signal_type']),
            status=SignalStatus(row['status']),
            confidence=row['confidence'],
            price=row['price'],
            entry_price=row['entry_price'],
            stop_loss=row['stop_loss'],
            tp_levels=tp_levels if tp_levels else None,
            position_size=row['position_size'],
            risk_reward_ratio=row['risk_reward_ratio'],
            indicators=indicators,
            reasons=reasons,
            generated_at=parse_dt(row['generated_at']) or datetime.now(),
            pending_at=parse_dt(row['pending_at']),
            executed_at=parse_dt(row['executed_at']),
            expired_at=parse_dt(row['expired_at']),
            order_id=row['order_id'],
            outcome=outcome
        )
