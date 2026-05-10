"""
SQLiteStateRepository - Infrastructure Layer

SQLite implementation of IStateRepository for state persistence.
"""

import sqlite3
import logging
import json
from datetime import datetime
from typing import Optional
from pathlib import Path

from ...domain.repositories.i_state_repository import IStateRepository
from ...domain.entities.state_models import PersistedState
from ...domain.state_machine import SystemState


class SQLiteStateRepository(IStateRepository):
    """
    SQLite implementation of state persistence.

    Stores trading state machine state in SQLite database
    for recovery after restart.

    Usage:
        repo = SQLiteStateRepository("data/trading_system.db")

        # Save state
        state = PersistedState(state=SystemState.IN_POSITION, order_id="123")
        repo.save_state(state)

        # Load state
        loaded = repo.load_state(symbol="btcusdt")
        if loaded:
            print(f"Restored state: {loaded.state.name}")
    """

    TABLE_NAME = "trading_state"

    def __init__(self, db_path: str = "data/trading_system.db"):
        """
        Initialize SQLite state repository.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)

        # Ensure directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        # Initialize database
        self._init_db()

        self.logger.info(f"SQLiteStateRepository initialized: {db_path}")

    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} (
                    symbol TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    order_id TEXT,
                    position_id TEXT,
                    cooldown_remaining INTEGER DEFAULT 0,
                    timestamp TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def save_state(self, state: PersistedState) -> bool:
        """
        Persist current state to SQLite.

        Uses UPSERT (INSERT OR REPLACE) to handle both new and existing states.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(f"""
                    INSERT OR REPLACE INTO {self.TABLE_NAME}
                    (symbol, state, order_id, position_id, cooldown_remaining, timestamp, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    state.symbol,
                    state.state.name,
                    state.order_id,
                    state.position_id,
                    state.cooldown_remaining,
                    state.timestamp.isoformat(),
                    datetime.now().isoformat()
                ))
                conn.commit()

            self.logger.debug(f"State saved: {state.state.name} for {state.symbol}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to save state: {e}")
            return False

    def load_state(self, symbol: str = "btcusdt") -> Optional[PersistedState]:
        """
        Load persisted state from SQLite.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(f"""
                    SELECT state, order_id, position_id, cooldown_remaining, timestamp
                    FROM {self.TABLE_NAME}
                    WHERE symbol = ?
                """, (symbol,))

                row = cursor.fetchone()

                if not row:
                    self.logger.debug(f"No persisted state found for {symbol}")
                    return None

                state_name, order_id, position_id, cooldown_remaining, timestamp_str = row

                persisted = PersistedState(
                    state=SystemState[state_name],
                    timestamp=datetime.fromisoformat(timestamp_str),
                    order_id=order_id,
                    position_id=position_id,
                    cooldown_remaining=cooldown_remaining or 0,
                    symbol=symbol
                )

                self.logger.info(f"State loaded: {persisted.state.name} for {symbol}")
                return persisted

        except Exception as e:
            self.logger.error(f"Failed to load state: {e}")
            return None

    def delete_state(self, symbol: str = "btcusdt") -> bool:
        """
        Delete persisted state from SQLite.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(f"""
                    DELETE FROM {self.TABLE_NAME}
                    WHERE symbol = ?
                """, (symbol,))
                conn.commit()

            self.logger.info(f"State deleted for {symbol}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to delete state: {e}")
            return False

    def has_state(self, symbol: str = "btcusdt") -> bool:
        """
        Check if state exists for symbol.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(f"""
                    SELECT 1 FROM {self.TABLE_NAME}
                    WHERE symbol = ?
                """, (symbol,))

                return cursor.fetchone() is not None

        except Exception as e:
            self.logger.error(f"Failed to check state: {e}")
            return False

    def __repr__(self) -> str:
        return f"SQLiteStateRepository(db_path={self.db_path})"
