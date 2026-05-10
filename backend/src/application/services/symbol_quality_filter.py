"""
Symbol Quality Filter - Execution Quality Layer

Filters out symbols that are structurally unsafe to trade, not just symbols that
look bad in one recent regime.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set, Tuple

from src.trading_contract import (
    PRODUCTION_MIN_SYMBOL_HISTORY_DAYS,
    get_production_symbol_blacklist,
)


class SymbolQualityFilter:
    """
    Filters symbols by execution quality before allowing trade execution.

    Current layers:
    - Non-ASCII detection for exotic / malformed symbols
    - Dynamic blacklist persisted in DB
    - Minimum 24h volume threshold
    - Minimum cached history depth for 1m monitoring parity
    """

    DEFAULT_BLACKLIST: Set[str] = set(get_production_symbol_blacklist())

    def __init__(
        self,
        min_24h_volume_usd: float = 50_000_000.0,
        max_spread_pct: float = 0.3,
        cache_ttl_seconds: int = 7200,
        binance_client=None,
        historical_volume_provider=None,
        block_non_ascii: bool = True,
        settings_repo=None,
        history_provider=None,
        min_symbol_history_days: int = PRODUCTION_MIN_SYMBOL_HISTORY_DAYS,
        history_interval: str = "1m",
    ):
        self.min_24h_volume_usd = min_24h_volume_usd
        self.max_spread_pct = max_spread_pct
        self.cache_ttl_seconds = cache_ttl_seconds
        self._client = binance_client
        self._historical_volume_provider = historical_volume_provider
        self.block_non_ascii = block_non_ascii
        self._settings_repo = settings_repo
        self._history_provider = history_provider
        self.min_symbol_history_days = min_symbol_history_days
        self.history_interval = history_interval

        self._blacklist: Set[str] = set(self.DEFAULT_BLACKLIST)
        self._load_blacklist_from_db()

        self._volume_cache: Dict[str, Tuple[float, float]] = {}
        self._historical_volume_cache: Dict[Tuple[str, str], float] = {}
        self._rejected_count: Dict[str, int] = {}

        self.logger = logging.getLogger(__name__)
        self.logger.info(
            "SymbolQualityFilter initialized: "
            f"blacklist={sorted(self._blacklist)}, "
            f"min_vol=${min_24h_volume_usd/1e6:.0f}M, "
            f"min_history={min_symbol_history_days}d/{history_interval}, "
            f"non_ascii_block={block_non_ascii}, "
            f"db_persist={'yes' if settings_repo else 'no'}"
        )

    def is_eligible(self, symbol: str, as_of: Optional[datetime] = None) -> Tuple[bool, str]:
        """
        Check if a symbol passes quality filters.

        Args:
            symbol: Trading symbol
            as_of: Evaluation time. Defaults to current UTC time.

        Returns:
            (is_eligible, reason)
        """
        symbol_upper = symbol.upper()

        if self.block_non_ascii and self._has_non_ascii(symbol_upper):
            self._track_rejection(symbol_upper, "NON_ASCII")
            return False, f"NON_ASCII: {symbol_upper} contains non-standard characters"

        if symbol_upper in self._blacklist:
            self._track_rejection(symbol_upper, "BLACKLISTED")
            return False, f"BLACKLISTED: {symbol_upper} is a known problematic symbol"

        history_error = self._check_history_depth(symbol_upper, as_of=as_of)
        if history_error:
            self._track_rejection(symbol_upper, "INSUFFICIENT_HISTORY")
            return False, history_error

        volume = self._get_volume(symbol_upper, as_of=as_of)
        if volume is not None and volume < self.min_24h_volume_usd:
            self._track_rejection(symbol_upper, "LOW_VOLUME")
            volume_label = "hist_24h_vol" if as_of is not None else "24h vol"
            return False, (
                f"LOW_VOLUME: {symbol_upper} {volume_label}=${volume/1e6:.1f}M "
                f"< ${self.min_24h_volume_usd/1e6:.0f}M minimum"
            )

        return True, ""

    @staticmethod
    def _has_non_ascii(symbol: str) -> bool:
        base = symbol.replace("USDT", "").replace("BUSD", "").replace("USDC", "")
        return any(ord(char) > 127 for char in base)

    def _check_history_depth(self, symbol: str, as_of: Optional[datetime]) -> Optional[str]:
        if self.min_symbol_history_days <= 0 or self._history_provider is None:
            return None
        if not hasattr(self._history_provider, "get_cache_coverage"):
            return None

        coverage = self._history_provider.get_cache_coverage(symbol, self.history_interval)
        start = coverage.get("start")
        count = int(coverage.get("count") or 0)
        if start is None or count <= 0:
            return (
                f"INSUFFICIENT_HISTORY: {symbol} missing usable {self.history_interval} cache "
                f"(need >= {self.min_symbol_history_days}d)"
            )

        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)

        cutoff = self._resolve_as_of(as_of) - timedelta(days=self.min_symbol_history_days)
        if start > cutoff:
            age_days = max(0.0, (self._resolve_as_of(as_of) - start).total_seconds() / 86400.0)
            return (
                f"INSUFFICIENT_HISTORY: {symbol} has {age_days:.1f}d of {self.history_interval} history "
                f"< {self.min_symbol_history_days}d minimum"
            )

        return None

    @staticmethod
    def _resolve_as_of(as_of: Optional[datetime]) -> datetime:
        resolved = as_of or datetime.now(timezone.utc)
        if resolved.tzinfo is None:
            return resolved.replace(tzinfo=timezone.utc)
        return resolved.astimezone(timezone.utc)

    def _track_rejection(self, symbol: str, reason: str) -> None:
        key = f"{symbol}:{reason}"
        self._rejected_count[key] = self._rejected_count.get(key, 0) + 1

    def _get_volume(self, symbol: str, as_of: Optional[datetime]) -> Optional[float]:
        historical_volume = self._get_historical_volume(symbol, as_of=as_of)
        if historical_volume is not None:
            return historical_volume
        return self._get_cached_volume(symbol)

    def _get_historical_volume(self, symbol: str, as_of: Optional[datetime]) -> Optional[float]:
        if as_of is None or self._historical_volume_provider is None:
            return None
        if not hasattr(self._historical_volume_provider, "get_symbol_volume_at_date"):
            return None

        resolved = self._resolve_as_of(as_of)
        cache_key = (symbol, resolved.strftime("%Y-%m-%d"))
        if cache_key in self._historical_volume_cache:
            return self._historical_volume_cache[cache_key]

        try:
            volume = float(
                self._historical_volume_provider.get_symbol_volume_at_date(symbol, resolved)
            )
        except Exception as exc:
            self.logger.debug(f"Historical volume fetch failed for {symbol}: {exc}")
            return None

        self._historical_volume_cache[cache_key] = volume
        return volume

    def _get_cached_volume(self, symbol: str) -> Optional[float]:
        now = time.time()

        if symbol in self._volume_cache:
            volume, cached_at = self._volume_cache[symbol]
            if now - cached_at < self.cache_ttl_seconds:
                return volume

        if self._client:
            try:
                volume = self._fetch_24h_volume(symbol)
                if volume is not None:
                    self._volume_cache[symbol] = (volume, now)
                    return volume
            except Exception as exc:
                self.logger.debug(f"Volume fetch failed for {symbol}: {exc}")

        return None

    def _fetch_24h_volume(self, symbol: str) -> Optional[float]:
        if not self._client:
            return None

        try:
            if hasattr(self._client, "get_ticker_24h"):
                ticker = self._client.get_ticker_24h(symbol)
                if ticker:
                    return float(ticker.get("quoteVolume", 0))
            elif hasattr(self._client, "client"):
                ticker = self._client.client.futures_ticker(symbol=symbol)
                if ticker:
                    return float(ticker.get("quoteVolume", 0))
        except Exception as exc:
            self.logger.debug(f"Failed to fetch ticker for {symbol}: {exc}")

        return None

    def _load_blacklist_from_db(self) -> None:
        if not self._settings_repo:
            return
        try:
            raw = self._settings_repo.get_setting("symbol_blacklist")
            if raw:
                self._blacklist = set(json.loads(raw))
        except Exception:
            pass

    def _persist_blacklist(self) -> None:
        if not self._settings_repo:
            return
        try:
            self._settings_repo.set_setting(
                "symbol_blacklist", json.dumps(sorted(self._blacklist))
            )
        except Exception as exc:
            self.logger.warning(f"Failed to persist blacklist to DB: {exc}")

    def extend_blacklist(self, symbols: List[str], persist: bool = False) -> None:
        added = []
        for symbol in symbols:
            symbol_upper = symbol.upper().strip()
            if not symbol_upper:
                continue
            if symbol_upper not in self._blacklist:
                self._blacklist.add(symbol_upper)
                added.append(symbol_upper)

        if persist and added:
            self._persist_blacklist()

        if added:
            mode = "persisted" if persist else "session-only"
            self.logger.info(
                f"Added {len(added)} symbols to {mode} blacklist: {sorted(added)}"
            )

    def add_to_blacklist(self, symbol: str) -> None:
        self.extend_blacklist([symbol], persist=True)
        self.logger.info(f"Current blacklist: {sorted(self._blacklist)}")

    def remove_from_blacklist(self, symbol: str) -> None:
        self._blacklist.discard(symbol.upper())
        self._persist_blacklist()
        self.logger.info(f"Removed {symbol.upper()} from blacklist. Current: {sorted(self._blacklist)}")

    def get_blacklist(self) -> List[str]:
        return sorted(self._blacklist)

    def get_status(self) -> Dict:
        return {
            "blacklist": sorted(self._blacklist),
            "blacklist_count": len(self._blacklist),
            "min_24h_volume_usd": self.min_24h_volume_usd,
            "max_spread_pct": self.max_spread_pct,
            "block_non_ascii": self.block_non_ascii,
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "min_symbol_history_days": self.min_symbol_history_days,
            "history_interval": self.history_interval,
            "cached_symbols": len(self._volume_cache),
            "rejection_stats": dict(self._rejected_count),
        }
