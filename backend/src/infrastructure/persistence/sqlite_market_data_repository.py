"""
SQLiteMarketDataRepository - Infrastructure Layer

SQLite implementation of MarketDataRepository interface.
"""

import sqlite3
import shutil
import logging
from datetime import datetime
from typing import List, Optional
from pathlib import Path
from contextlib import contextmanager

from ...domain.repositories.market_data_repository import MarketDataRepository, RepositoryError
from ...domain.entities.candle import Candle
from ...domain.entities.indicator import Indicator
from ...domain.entities.market_data import MarketData


class SQLiteMarketDataRepository(MarketDataRepository):
    """SQLite implementation of MarketDataRepository"""

    def __init__(self, db_path: str = "crypto_data.db"):
        self.db_path = db_path
        self._memory_conn = None
        self.logger = logging.getLogger(__name__)

        # SOTA FIX: Create parent directory if needed (prevents init failure)
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        if db_path == ":memory:":
            self._memory_conn = sqlite3.connect(":memory:")
        self._init_database()

        # SOTA: Hinto In-Memory Price Cache (Hot Path)
        # Stores the latest real-time price tick for each symbol.
        # Used by PaperTradingService for sub-second PnL updates without DB latency.
        self._price_cache: dict[str, float] = {}

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections with WAL mode"""
        if self._memory_conn:
            yield self._memory_conn
        else:
            conn = sqlite3.connect(self.db_path)
            # SOTA: Enable WAL mode for concurrency
            # Write-Ahead Logging allows simultaneous readers and one writer
            conn.execute('PRAGMA journal_mode=WAL;')
            try:
                yield conn
            finally:
                conn.close()

    def _init_database(self) -> None:
        """
        Initialize database with default tables.

        SOTA Multi-Symbol: Creates btcusdt tables for backward compatibility.
        Other symbol tables are created dynamically via _ensure_table_exists().
        """
        # Create default btcusdt tables for backward compatibility
        default_symbols = ['btcusdt']
        timeframes = ['1m', '15m', '1h']

        with self._get_connection() as conn:
            cursor = conn.cursor()

            for symbol in default_symbols:
                for tf in timeframes:
                    table = self._get_table_name(symbol, tf)
                    self._create_table_if_not_exists(cursor, table)

            conn.commit()
            self.logger.debug(f"Initialized database with default tables")

    def _create_table_if_not_exists(self, cursor, table: str) -> None:
        """Create OHLCV table if it doesn't exist."""
        table_sql = self._quote_identifier(table)
        index_sql = self._quote_identifier(f"idx_{table}_timestamp")
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS {table_sql} (
                timestamp TEXT PRIMARY KEY,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                ema_7 REAL,
                rsi_6 REAL,
                volume_ma_20 REAL
            )
        ''')
        cursor.execute(f'''
            CREATE INDEX IF NOT EXISTS {index_sql}
            ON {table_sql}(timestamp)
        ''')

    def _ensure_table_exists(self, symbol: str, timeframe: str) -> str:
        """
        Ensure table exists for symbol/timeframe, create if needed.

        SOTA Multi-Symbol: Dynamic table creation per symbol.

        Returns:
            Table name
        """
        table = self._get_table_name(symbol, timeframe)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Check if table exists
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,)
            )
            if not cursor.fetchone():
                self._create_table_if_not_exists(cursor, table)
                conn.commit()
                self.logger.info(f"📊 Created new table: {table}")

        return table

    def _get_table_name(self, symbol: str, timeframe: str) -> str:
        """
        Get table name for symbol and timeframe.

        SOTA Multi-Symbol: Per-symbol tables for data isolation.
        Format: {symbol}_{timeframe} (e.g., ethusdt_15m)
        """
        return f"{symbol.lower()}_{timeframe}"

    @staticmethod
    def _quote_identifier(identifier: str) -> str:
        """Quote SQLite identifiers, including symbols that start with digits."""
        return '"' + identifier.replace('"', '""') + '"'

    def save_candle(self, candle: Candle, indicator: Indicator, timeframe: str, symbol: str = 'btcusdt') -> None:
        """
        Save candle with indicators.

        Args:
            candle: Candle entity
            indicator: Indicator entity
            timeframe: '1m', '15m', or '1h'
            symbol: Trading symbol (default: btcusdt for backward compat)
        """
        try:
            table = self._ensure_table_exists(symbol, timeframe)
            table_sql = self._quote_identifier(table)

            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(f'''
                    INSERT OR REPLACE INTO {table_sql}
                    (timestamp, open, high, low, close, volume, ema_7, rsi_6, volume_ma_20)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    candle.timestamp.isoformat(),
                    candle.open,
                    candle.high,
                    candle.low,
                    candle.close,
                    candle.volume,
                    indicator.ema_7,
                    indicator.rsi_6,
                    indicator.volume_ma_20
                ))
                conn.commit()
        except Exception as e:
            raise RepositoryError(f"Failed to save candle: {e}", e)

    def save_market_data(self, market_data: MarketData, symbol: str = 'btcusdt') -> None:
        """Save MarketData object (candle with indicators)"""
        self.save_candle(market_data.candle, market_data.indicator, market_data.timeframe, symbol)

    def save_candle_simple(self, candle: Candle, timeframe: str, symbol: str = 'btcusdt') -> None:
        """
        Save candle OHLCV only (without indicators).

        SOTA Multi-Symbol: Supports per-symbol storage.

        Args:
            candle: Candle entity with OHLCV data
            timeframe: '1m', '15m', or '1h'
            symbol: Trading symbol (e.g., 'btcusdt', 'ethusdt')
        """
        try:
            table = self._ensure_table_exists(symbol, timeframe)
            table_sql = self._quote_identifier(table)

            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(f'''
                    INSERT OR REPLACE INTO {table_sql}
                    (timestamp, open, high, low, close, volume, ema_7, rsi_6, volume_ma_20)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    candle.timestamp.isoformat(),
                    candle.open,
                    candle.high,
                    candle.low,
                    candle.close,
                    candle.volume,
                    None,  # ema_7
                    None,  # rsi_6
                    None   # volume_ma_20
                ))
                conn.commit()
                self.logger.debug(f"📦 Persisted {symbol}/{timeframe} candle: {candle.timestamp}")
        except Exception as e:
            raise RepositoryError(f"Failed to save simple candle: {e}", e)

    def get_latest_candles(self, symbol: str, timeframe: str, limit: int = 100) -> List[MarketData]:
        """
        Get latest N candles for a symbol.

        SOTA Multi-Symbol: Returns data from symbol-specific table.

        Args:
            symbol: Trading symbol (e.g., 'btcusdt', 'ethusdt')
            timeframe: '1m', '15m', or '1h'
            limit: Max candles to return
        """
        try:
            table = self._get_table_name(symbol, timeframe)
            table_sql = self._quote_identifier(table)

            with self._get_connection() as conn:
                cursor = conn.cursor()

                # Check if table exists first
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table,)
                )
                if not cursor.fetchone():
                    # Table doesn't exist - return empty (Binance fallback will be used)
                    self.logger.debug(f"Table {table} not found, returning empty")
                    return []

                cursor.execute(f'''
                    SELECT timestamp, open, high, low, close, volume,
                           ema_7, rsi_6, volume_ma_20
                    FROM {table_sql}
                    ORDER BY timestamp DESC
                    LIMIT ?
                ''', (limit,))

                results = []
                for row in cursor.fetchall():
                    candle = Candle(
                        timestamp=datetime.fromisoformat(row[0]),
                        open=row[1],
                        high=row[2],
                        low=row[3],
                        close=row[4],
                        volume=row[5]
                    )
                    indicator = Indicator(
                        ema_7=row[6],
                        rsi_6=row[7],
                        volume_ma_20=row[8]
                    )
                    market_data = MarketData(candle, indicator, timeframe)
                    results.append(market_data)

                return results
        except Exception as e:
            raise RepositoryError(f"Failed to get candles: {e}", e)

    def get_candles_by_date_range(
        self,
        timeframe: str,
        start: datetime,
        end: datetime,
        symbol: str = 'btcusdt'  # SOTA: Added for multi-symbol support
    ) -> List[MarketData]:
        """Get candles within date range"""
        try:
            table = self._get_table_name(symbol, timeframe)
            table_sql = self._quote_identifier(table)

            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(f'''
                    SELECT timestamp, open, high, low, close, volume,
                           ema_7, rsi_6, volume_ma_20
                    FROM {table_sql}
                    WHERE timestamp BETWEEN ? AND ?
                    ORDER BY timestamp DESC
                ''', (start.isoformat(), end.isoformat()))

                results = []
                for row in cursor.fetchall():
                    candle = Candle(
                        timestamp=datetime.fromisoformat(row[0]),
                        open=row[1], high=row[2], low=row[3],
                        close=row[4], volume=row[5]
                    )
                    indicator = Indicator(ema_7=row[6], rsi_6=row[7], volume_ma_20=row[8])
                    results.append(MarketData(candle, indicator, timeframe))

                return results
        except Exception as e:
            raise RepositoryError(f"Failed to get candles by date range: {e}", e)

    def get_candle_by_timestamp(
        self,
        timeframe: str,
        timestamp: datetime,
        symbol: str = 'btcusdt'  # SOTA: Added for multi-symbol support
    ) -> Optional[MarketData]:
        """Get specific candle by timestamp"""
        try:
            table = self._get_table_name(symbol, timeframe)
            table_sql = self._quote_identifier(table)

            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(f'''
                    SELECT timestamp, open, high, low, close, volume,
                           ema_7, rsi_6, volume_ma_20
                    FROM {table_sql}
                    WHERE timestamp = ?
                ''', (timestamp.isoformat(),))

                row = cursor.fetchone()
                if not row:
                    return None

                candle = Candle(
                    timestamp=datetime.fromisoformat(row[0]),
                    open=row[1], high=row[2], low=row[3],
                    close=row[4], volume=row[5]
                )
                indicator = Indicator(ema_7=row[6], rsi_6=row[7], volume_ma_20=row[8])
                return MarketData(candle, indicator, timeframe)
        except Exception as e:
            raise RepositoryError(f"Failed to get candle: {e}", e)

    def get_record_count(self, timeframe: str, symbol: str = 'btcusdt') -> int:
        """Get total record count"""
        try:
            table = self._get_table_name(symbol, timeframe)
            table_sql = self._quote_identifier(table)

            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(f'SELECT COUNT(*) FROM {table_sql}')
                return cursor.fetchone()[0]
        except Exception as e:
            raise RepositoryError(f"Failed to get record count: {e}", e)

    def get_latest_timestamp(self, timeframe: str, symbol: str = 'btcusdt') -> Optional[datetime]:
        """Get latest timestamp"""
        try:
            table = self._get_table_name(symbol, timeframe)
            table_sql = self._quote_identifier(table)

            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(f'SELECT MAX(timestamp) FROM {table_sql}')
                result = cursor.fetchone()[0]
                return datetime.fromisoformat(result) if result else None
        except Exception as e:
            raise RepositoryError(f"Failed to get latest timestamp: {e}", e)

    def delete_candles_before(self, timeframe: str, before: datetime, symbol: str = 'btcusdt') -> int:
        """
        Delete candles before date for a specific symbol.

        SOTA Multi-Symbol: Now supports per-symbol cleanup.
        """
        try:
            table = self._get_table_name(symbol, timeframe)
            table_sql = self._quote_identifier(table)

            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                )
                if not cursor.fetchone():
                    return 0
                cursor.execute(f'''
                    DELETE FROM {table_sql}
                    WHERE timestamp < ?
                ''', (before.isoformat(),))
                conn.commit()
                return cursor.rowcount
        except Exception as e:
            raise RepositoryError(f"Failed to delete candles: {e}", e)

    def get_database_size(self) -> float:
        """Get database size in MB"""
        try:
            if self.db_path == ":memory:":
                return 0.0

            path = Path(self.db_path)
            if path.exists():
                return path.stat().st_size / (1024 * 1024)
            return 0.0
        except Exception as e:
            raise RepositoryError(f"Failed to get database size: {e}", e)

    def backup_database(self, backup_path: str) -> None:
        """Backup database"""
        try:
            if self.db_path == ":memory:":
                raise RepositoryError("Cannot backup in-memory database")

            # Create backup directory if needed
            Path(backup_path).parent.mkdir(parents=True, exist_ok=True)

            # Copy database file
            shutil.copy2(self.db_path, backup_path)
        except Exception as e:
            raise RepositoryError(f"Failed to backup database: {e}", e)

    def get_table_info(self, timeframe: str, symbol: str = 'btcusdt') -> dict:
        """Get table information"""
        try:
            table = self._get_table_name(symbol, timeframe)
            table_sql = self._quote_identifier(table)

            with self._get_connection() as conn:
                cursor = conn.cursor()

                # Get record count
                cursor.execute(f'SELECT COUNT(*) FROM {table_sql}')
                record_count = cursor.fetchone()[0]

                # Get latest record
                cursor.execute(f'SELECT MAX(timestamp) FROM {table_sql}')
                latest = cursor.fetchone()[0]

                # Get oldest record
                cursor.execute(f'SELECT MIN(timestamp) FROM {table_sql}')
                oldest = cursor.fetchone()[0]

                return {
                    'record_count': record_count,
                    'size_mb': self.get_database_size(),
                    'latest_record': latest,
                    'oldest_record': oldest
                }
        except Exception as e:
            raise RepositoryError(f"Failed to get table info: {e}", e)

    def update_realtime_price(self, symbol: str, price: float) -> None:
        """
        Update the real-time price cache for a symbol.

        Args:
            symbol: Trading pair symbol (e.g., 'BTCUSDT')
            price: Current market price
        """
        if symbol and price > 0:
            self._price_cache[symbol.lower()] = price

    def get_realtime_price(self, symbol: str) -> float:
        """
        Get the latest real-time price from cache.
        Returns 0.0 if not found.

        Args:
            symbol: Trading pair symbol
        """
        return self._price_cache.get(symbol.lower(), 0.0)
