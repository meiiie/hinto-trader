"""
HistoricalVolumeService - Infrastructure Layer

Calculate historical 24h quote volume rankings without relying on current
top-volume snapshots.
"""

import hashlib
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from ..api.binance_rest_client import BinanceRestClient
from ...config.market_mode import MarketMode


class HistoricalVolumeService:
    """
    Calculate historical 24h trading volume at a specific date.

    Rankings are cached per date and universe definition. The default universe is
    built from exchange metadata so historical top-N selection is not constrained
    to the current top50 symbols.
    """

    CACHE_DIR = "data/cache/volume_rankings"

    def __init__(
        self,
        market_mode: MarketMode = MarketMode.FUTURES,
        cache_enabled: bool = True,
    ):
        self.logger = logging.getLogger(__name__)
        self.market_mode = market_mode
        self.cache_enabled = cache_enabled
        self.client = BinanceRestClient(market_mode=market_mode)

        if self.cache_enabled:
            os.makedirs(self.CACHE_DIR, exist_ok=True)

    def get_top_symbols_at_date(
        self,
        date: datetime,
        limit: int = 10,
        universe: Optional[List[str]] = None,
    ) -> List[str]:
        """
        Get top N symbols ranked by 24h quote volume at a specific date.

        Args:
            date: Date to evaluate (UTC)
            limit: Number of top symbols to return
            universe: Optional explicit universe. If omitted, use all trading USDT pairs.
        """
        ranked_symbols = self.get_ranked_symbols_at_date(date=date, universe=universe)
        return ranked_symbols[:limit]

    def get_symbol_volume_at_date(self, symbol: str, date: datetime) -> float:
        """
        Get a symbol's historical 24h quote volume at a specific date.

        Used by quality filters to avoid current-volume look-ahead bias when
        evaluating historical windows.
        """
        end_time = datetime(date.year, date.month, date.day, 0, 0, 0, tzinfo=timezone.utc)
        end_ms = int(end_time.timestamp() * 1000)

        candles = self.client.get_klines(
            symbol=symbol.upper(),
            interval="1h",
            limit=24,
            end_time=end_ms,
        )
        if not candles:
            return 0.0

        return sum(candle.volume * candle.close for candle in candles)

    def get_ranked_symbols_at_date(
        self,
        date: datetime,
        universe: Optional[List[str]] = None,
    ) -> List[str]:
        """
        Get the full historical volume ranking for a date.
        """
        date_str = date.strftime("%Y-%m-%d")
        cache_key = self._build_cache_key(date_str, universe)

        if self.cache_enabled:
            cached = self._load_from_cache(cache_key)
            if cached:
                self.logger.info(f"Loaded volume ranking from cache: {date_str}")
                return cached

        self.logger.info(f"Calculating volume ranking at {date_str}...")

        if universe is None:
            universe = self._get_default_universe(quote_asset="USDT")
            if not universe:
                self.logger.error("Failed to get base universe")
                return []

        volumes = self._calculate_volumes_parallel(universe, date)
        if not volumes:
            self.logger.warning("No volume data calculated, falling back to current universe order")
            return list(universe)

        ranked_symbols = [
            symbol for symbol, _ in sorted(volumes.items(), key=lambda item: item[1], reverse=True)
        ]
        self.logger.info(f"Top 5 at {date_str}: {ranked_symbols[:5]}")

        if self.cache_enabled:
            self._save_to_cache(cache_key, ranked_symbols)

        return ranked_symbols

    def get_top_eligible_symbols_at_date(
        self,
        date: datetime,
        limit: int,
        eligibility_fn: Callable[[str], Tuple[bool, str]],
        universe: Optional[List[str]] = None,
        candidate_limit: Optional[int] = None,
    ) -> Tuple[List[str], List[Tuple[str, str]]]:
        """
        Return the top N ranked symbols that also pass a caller-provided eligibility filter.

        This is used to make `top40/top50` mean top eligible symbols instead of
        top raw symbols that later collapse to a much smaller tradable universe.
        """
        ranked_symbols = self.get_ranked_symbols_at_date(date=date, universe=universe)
        if candidate_limit is not None and candidate_limit > 0:
            ranked_symbols = ranked_symbols[:candidate_limit]

        eligible: List[str] = []
        rejected: List[Tuple[str, str]] = []
        for symbol in ranked_symbols:
            is_eligible, reason = eligibility_fn(symbol)
            if is_eligible:
                eligible.append(symbol)
                if len(eligible) >= limit:
                    break
            else:
                rejected.append((symbol, reason))

        return eligible, rejected

    def _build_cache_key(self, date_str: str, universe: Optional[List[str]]) -> str:
        """
        Build a cache key that reflects the universe definition.

        `v2` intentionally invalidates older cache files produced by the legacy
        current-top50 seed universe.
        """
        if universe is None:
            scope = f"{self.market_mode.value}_all_trading_usdt_v2"
        else:
            normalized = ",".join(sorted({symbol.upper() for symbol in universe}))
            digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
            scope = f"{self.market_mode.value}_custom_{digest}_v2"

        return f"{date_str}_{scope}"

    def _get_default_universe(self, quote_asset: str = "USDT") -> List[str]:
        """
        Build a broad trading universe from exchange metadata.

        This reduces survivorship bias versus ranking only inside the current top50.
        """
        exchange_info = self.client.get_exchange_info()
        if not exchange_info:
            self.logger.warning("exchangeInfo unavailable, falling back to current top volume pairs")
            return self.client.get_top_volume_pairs(limit=100, quote_asset=quote_asset)

        symbols: List[str] = []
        for item in exchange_info.get("symbols", []):
            symbol = item.get("symbol", "")
            if not symbol.endswith(quote_asset):
                continue
            if item.get("status") != "TRADING":
                continue
            if symbol.startswith(("USDC", "FDUSD")):
                continue

            quote = item.get("quoteAsset")
            if quote and quote != quote_asset:
                continue

            if self.market_mode == MarketMode.FUTURES:
                contract_type = item.get("contractType")
                if contract_type and contract_type != "PERPETUAL":
                    continue

            symbols.append(symbol)

        if symbols:
            universe = sorted(set(symbols))
            self.logger.info(f"Base universe from exchangeInfo: {len(universe)} {quote_asset} symbols")
            return universe

        self.logger.warning("exchangeInfo returned no eligible symbols, falling back to current top volume pairs")
        return self.client.get_top_volume_pairs(limit=100, quote_asset=quote_asset)

    def _calculate_volumes_parallel(
        self,
        symbols: List[str],
        date: datetime,
    ) -> Dict[str, float]:
        """
        Calculate 24h USDT volume for each symbol at date.
        """
        volumes: Dict[str, float] = {}
        end_time = datetime(date.year, date.month, date.day, 0, 0, 0, tzinfo=timezone.utc)
        end_ms = int(end_time.timestamp() * 1000)

        def fetch_volume(symbol: str) -> tuple[str, float]:
            try:
                candles = self.client.get_klines(
                    symbol=symbol,
                    interval="1h",
                    limit=24,
                    end_time=end_ms,
                )
                if not candles:
                    return symbol, 0.0

                usdt_volume = sum(candle.volume * candle.close for candle in candles)
                return symbol, usdt_volume
            except Exception as exc:
                self.logger.debug(f"Error fetching {symbol}: {exc}")
                return symbol, 0.0

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(fetch_volume, symbol): symbol for symbol in symbols}
            for future in as_completed(futures):
                symbol, volume = future.result()
                if volume > 0:
                    volumes[symbol] = volume

        self.logger.info(f"Calculated volume for {len(volumes)}/{len(symbols)} symbols")
        return volumes

    def _load_from_cache(self, cache_key: str) -> Optional[List[str]]:
        cache_path = os.path.join(self.CACHE_DIR, f"{cache_key}.json")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as handle:
                    return json.load(handle)
            except Exception as exc:
                self.logger.warning(f"Failed to load cache: {exc}")

        return None

    def _save_to_cache(self, cache_key: str, symbols: List[str]) -> None:
        cache_path = os.path.join(self.CACHE_DIR, f"{cache_key}.json")
        try:
            with open(cache_path, "w", encoding="utf-8") as handle:
                json.dump(symbols, handle)
            self.logger.info(f"Cached volume ranking: {cache_path}")
        except Exception as exc:
            self.logger.warning(f"Failed to save cache: {exc}")

    def clear_cache(self) -> int:
        count = 0
        if os.path.exists(self.CACHE_DIR):
            for file_name in os.listdir(self.CACHE_DIR):
                if file_name.endswith(".json"):
                    os.remove(os.path.join(self.CACHE_DIR, file_name))
                    count += 1
        self.logger.info(f"Cleared {count} cached rankings")
        return count
