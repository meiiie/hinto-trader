"""
FundingHistoryLoader - Smart Local Data Warehouse for Funding Rates

SOTA Implementation (Jan 2026):
- Parquet-based caching for historical funding rates
- Incremental sync (only fetch missing data)
- ZSTD compression for minimal storage (~2KB per month per symbol)
- Binary search for efficient timestamp lookups

Data Source: Binance Futures API GET /fapi/v1/fundingRate

Storage Structure:
  backend/data/cache/
  ├── BTCUSDT/
  │   ├── 15m.parquet      (candles - existing)
  │   ├── 1h.parquet
  │   └── funding.parquet  (NEW - funding rates)
  └── metadata.json
"""

import logging
import json
import os
import time
import requests
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
from pathlib import Path
from bisect import bisect_left

import pandas as pd


class FundingHistoryLoader:
    """
    Smart Local Data Warehouse for Historical Funding Rates.

    Uses Parquet format for:
    - Columnar storage (optimized for time-series)
    - ZSTD compression (3-5x smaller than CSV)
    - Fast lookups via binary search

    Features:
    - Incremental sync: Only fetches missing data
    - Automatic cache validation
    - Per-symbol funding rate lookup by timestamp

    Usage:
        loader = FundingHistoryLoader()
        funding = loader.get_funding_at_time("BTCUSDT", some_timestamp)
    """

    # Cache directory relative to backend/
    CACHE_DIR = Path(__file__).parent.parent.parent.parent / "data" / "cache"

    # Binance API
    BINANCE_FUTURES_URL = "https://fapi.binance.com"

    # Parquet compression
    COMPRESSION = "zstd"

    # Default funding rate if no data available
    DEFAULT_FUNDING_RATE = 0.0001  # 0.01%

    def __init__(self):
        """Initialize loader with cache directory setup."""
        self.logger = logging.getLogger(__name__)

        # Ensure cache directory exists
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)

        # In-memory cache for loaded funding data
        self._funding_cache: Dict[str, pd.DataFrame] = {}

    def load_funding_history(
        self,
        symbol: str,
        start_time: datetime,
        end_time: datetime
    ) -> pd.DataFrame:
        """
        Load historical funding rates for a symbol.

        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            start_time: Start of period
            end_time: End of period

        Returns:
            DataFrame with columns: [timestamp, funding_rate, mark_price]
        """
        symbol = symbol.upper()

        # Check in-memory cache first
        if symbol in self._funding_cache:
            df = self._funding_cache[symbol]
            if self._covers_period(df, start_time, end_time):
                self.logger.debug(f"📦 Using memory cache for {symbol} funding")
                return df

        # Check Parquet cache
        cache_file = self._get_cache_path(symbol)

        if cache_file.exists():
            try:
                df = pd.read_parquet(cache_file)

                if self._covers_period(df, start_time, end_time):
                    self.logger.debug(f"📦 Using disk cache for {symbol} funding")
                    self._funding_cache[symbol] = df
                    return df
                else:
                    # Need to extend cache
                    df = self._extend_cache(symbol, df, start_time, end_time)
                    self._funding_cache[symbol] = df
                    return df

            except Exception as e:
                self.logger.warning(f"⚠️ Cache corrupted for {symbol}, re-fetching: {e}")

        # Fetch from API
        df = self._fetch_from_binance(symbol, start_time, end_time)

        if df is not None and not df.empty:
            # Save to cache
            self._save_to_cache(symbol, df)
            self._funding_cache[symbol] = df
        else:
            # Cache empty result to prevent re-fetching on every candle
            self._funding_cache[symbol] = pd.DataFrame()

        return df

    def get_funding_at_time(
        self,
        symbol: str,
        timestamp: datetime
    ) -> float:
        """
        Get funding rate at a specific timestamp.

        Uses binary search to find the most recent funding event before timestamp.

        Args:
            symbol: Trading pair
            timestamp: Time to query

        Returns:
            Funding rate as decimal (e.g., 0.0001 = 0.01%)
        """
        symbol = symbol.upper()

        # Get or load funding data
        if symbol not in self._funding_cache:
            # Load with reasonable range around timestamp
            start = timestamp - timedelta(days=7)
            end = timestamp + timedelta(days=1)
            self.load_funding_history(symbol, start, end)

        df = self._funding_cache.get(symbol)

        if df is None or df.empty:
            return self.DEFAULT_FUNDING_RATE

        # Convert timestamp to milliseconds for comparison
        ts_ms = int(timestamp.timestamp() * 1000)

        # Binary search for nearest funding event before timestamp
        timestamps = df['timestamp'].values
        idx = bisect_left(timestamps, ts_ms)

        if idx == 0:
            # Before first funding event, use first rate
            return df.iloc[0]['funding_rate']
        elif idx >= len(timestamps):
            # After last funding event, use last rate
            return df.iloc[-1]['funding_rate']
        else:
            # Use the rate from the most recent funding event
            return df.iloc[idx - 1]['funding_rate']

    def preload_symbols(
        self,
        symbols: List[str],
        start_time: datetime,
        end_time: datetime
    ):
        """
        Preload funding history for multiple symbols.

        Call this at backtest start for efficiency.
        """
        self.logger.info(f"📊 Preloading funding history for {len(symbols)} symbols...")

        for symbol in symbols:
            try:
                self.load_funding_history(symbol, start_time, end_time)
            except Exception as e:
                self.logger.warning(f"⚠️ Failed to load funding for {symbol}: {e}")

        self.logger.info(f"✅ Funding history preloaded for {len(self._funding_cache)} symbols")

    def _get_cache_path(self, symbol: str) -> Path:
        """Get cache file path for symbol."""
        symbol_dir = self.CACHE_DIR / symbol
        symbol_dir.mkdir(parents=True, exist_ok=True)
        return symbol_dir / "funding.parquet"

    def _covers_period(
        self,
        df: pd.DataFrame,
        start_time: datetime,
        end_time: datetime
    ) -> bool:
        """Check if DataFrame covers the requested period."""
        if df.empty:
            return False

        start_ms = int(start_time.timestamp() * 1000)
        end_ms = int(end_time.timestamp() * 1000)

        df_start = df['timestamp'].min()
        df_end = df['timestamp'].max()

        # Allow 8 hours buffer (one funding interval)
        buffer_ms = 8 * 60 * 60 * 1000

        return df_start <= start_ms + buffer_ms and df_end >= end_ms - buffer_ms

    def _fetch_from_binance(
        self,
        symbol: str,
        start_time: datetime,
        end_time: datetime
    ) -> pd.DataFrame:
        """
        Fetch funding rate history from Binance API.

        API: GET /fapi/v1/fundingRate
        - symbol: required
        - startTime, endTime: optional timestamp in ms
        - limit: 1000 max
        """
        self.logger.info(f"📡 Fetching funding history for {symbol} from Binance...")

        all_data = []
        start_ms = int(start_time.timestamp() * 1000)
        end_ms = int(end_time.timestamp() * 1000)

        current_start = start_ms

        while current_start < end_ms:
            try:
                params = {
                    "symbol": symbol,
                    "startTime": current_start,
                    "endTime": end_ms,
                    "limit": 1000
                }

                response = requests.get(
                    f"{self.BINANCE_FUTURES_URL}/fapi/v1/fundingRate",
                    params=params,
                    timeout=10
                )

                if response.status_code != 200:
                    self.logger.warning(f"⚠️ Binance API error: {response.text}")
                    break

                data = response.json()

                if not data:
                    break

                all_data.extend(data)

                # Move to next batch
                last_time = data[-1]['fundingTime']
                current_start = last_time + 1

                # Rate limit protection
                time.sleep(0.1)

            except Exception as e:
                self.logger.error(f"❌ Failed to fetch funding for {symbol}: {e}")
                break

        if not all_data:
            self.logger.warning(f"⚠️ No funding data for {symbol}")
            return pd.DataFrame()

        # Convert to DataFrame
        df = pd.DataFrame(all_data)
        df = df.rename(columns={
            'fundingTime': 'timestamp',
            'fundingRate': 'funding_rate',
            'markPrice': 'mark_price'
        })

        # Clean data before type conversion (handle empty strings from Binance API)
        # Replace empty strings with NaN for numeric columns
        for col in ['funding_rate', 'mark_price']:
            if col in df.columns:
                df[col] = df[col].replace('', pd.NA)

        # Convert types with error handling
        try:
            df['timestamp'] = df['timestamp'].astype('int64')
            df['funding_rate'] = pd.to_numeric(df['funding_rate'], errors='coerce')

            if 'mark_price' in df.columns:
                df['mark_price'] = pd.to_numeric(df['mark_price'], errors='coerce')

                # Log if we found invalid data
                invalid_count = df['mark_price'].isna().sum()
                if invalid_count > 0:
                    self.logger.warning(
                        f"⚠️ Found {invalid_count} invalid mark_price values for {symbol}, "
                        f"replaced with NaN"
                    )

            # Check funding_rate validity (critical field)
            invalid_funding = df['funding_rate'].isna().sum()
            if invalid_funding > 0:
                self.logger.warning(
                    f"⚠️ Found {invalid_funding} invalid funding_rate values for {symbol}, "
                    f"using default rate {self.DEFAULT_FUNDING_RATE}"
                )
                df['funding_rate'] = df['funding_rate'].fillna(self.DEFAULT_FUNDING_RATE)

        except Exception as e:
            self.logger.error(f"❌ Type conversion failed for {symbol}: {e}")
            return pd.DataFrame()

        # Sort by timestamp
        df = df.sort_values('timestamp').reset_index(drop=True)

        self.logger.info(f"✅ Fetched {len(df)} funding events for {symbol}")

        return df

    def _extend_cache(
        self,
        symbol: str,
        existing_df: pd.DataFrame,
        start_time: datetime,
        end_time: datetime
    ) -> pd.DataFrame:
        """Extend existing cache with new data."""

        # Determine what we need
        existing_start = existing_df['timestamp'].min()
        existing_end = existing_df['timestamp'].max()

        start_ms = int(start_time.timestamp() * 1000)
        end_ms = int(end_time.timestamp() * 1000)

        new_data = []

        # Fetch earlier data if needed
        if start_ms < existing_start:
            earlier_df = self._fetch_from_binance(
                symbol,
                start_time,
                datetime.fromtimestamp(existing_start / 1000, tz=timezone.utc)
            )
            if not earlier_df.empty:
                new_data.append(earlier_df)

        # Add existing data
        new_data.append(existing_df)

        # Fetch later data if needed
        if end_ms > existing_end:
            later_df = self._fetch_from_binance(
                symbol,
                datetime.fromtimestamp(existing_end / 1000, tz=timezone.utc),
                end_time
            )
            if not later_df.empty:
                new_data.append(later_df)

        # Merge all data
        merged = pd.concat(new_data, ignore_index=True)
        merged = merged.drop_duplicates(subset=['timestamp']).sort_values('timestamp')

        # Save extended cache
        self._save_to_cache(symbol, merged)

        return merged

    def _save_to_cache(self, symbol: str, df: pd.DataFrame):
        """Save DataFrame to Parquet cache."""
        cache_file = self._get_cache_path(symbol)
        df.to_parquet(cache_file, compression=self.COMPRESSION, index=False)
        self.logger.debug(f"💾 Saved {len(df)} funding events to cache for {symbol}")

    def get_stats(self) -> Dict:
        """Get loader statistics."""
        return {
            "symbols_loaded": len(self._funding_cache),
            "total_events": sum(len(df) for df in self._funding_cache.values()),
            "cache_dir": str(self.CACHE_DIR)
        }

    def clear_cache(self, symbol: Optional[str] = None):
        """Clear funding cache."""
        if symbol:
            cache_file = self._get_cache_path(symbol)
            if cache_file.exists():
                cache_file.unlink()
            if symbol in self._funding_cache:
                del self._funding_cache[symbol]
        else:
            # Clear all funding caches
            for dir_path in self.CACHE_DIR.iterdir():
                if dir_path.is_dir():
                    funding_file = dir_path / "funding.parquet"
                    if funding_file.exists():
                        funding_file.unlink()
            self._funding_cache.clear()
