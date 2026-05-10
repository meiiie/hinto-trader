"""
BinanceRestClient - Infrastructure Layer

REST API client for fetching historical data from Binance.
Supports both SPOT and FUTURES markets.
"""

import requests
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any

from ...domain.entities.candle import Candle
from ...config.market_mode import MarketMode, get_market_config, get_default_market_mode


class BinanceRestClient:
    """
    REST API client for Binance market data.

    SOTA: Supports both SPOT and FUTURES modes via MarketMode parameter.
    Default is FUTURES for Limit Sniper strategy accuracy.

    Features:
    - Fetch historical klines (candles)
    - Support multiple intervals
    - Dual market mode (SPOT/FUTURES)
    - Error handling and retries
    - Rate limit awareness
    """

    # URL constants for reference
    SPOT_URL = "https://api.binance.com/api/v3"
    FUTURES_URL = "https://fapi.binance.com/fapi/v1"

    def __init__(
        self,
        market_mode: Optional[MarketMode] = None,
        timeout: int = 10
    ):
        """
        Initialize REST client.

        Args:
            market_mode: SPOT or FUTURES (default: from env or FUTURES)
            timeout: Request timeout in seconds
        """
        self.market_mode = market_mode or get_default_market_mode()
        self.config = get_market_config(self.market_mode)
        self.base_url = self.config.rest_base_url
        self.timeout = timeout
        self.logger = logging.getLogger(__name__)

        self.logger.info(f"🌐 BinanceRestClient initialized: {self.market_mode.value.upper()} mode ({self.base_url})")

    def get_klines(
        self,
        symbol: str = "BTCUSDT",
        interval: str = "1m",
        limit: int = 100,
        end_time: Optional[int] = None
    ) -> List[Candle]:
        """
        Fetch historical klines from Binance.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            interval: Kline interval (e.g., '1m', '15m', '1h')
            limit: Number of klines to fetch (max 1000)
            end_time: End time in milliseconds (default: now)

        Returns:
            List of Candle entities
        """
        if limit > 1000:
            self.logger.warning(f"Limit {limit} exceeds max 1000, using 1000")
            limit = 1000

        try:
            url = f"{self.base_url}/klines"

            params = {
                'symbol': symbol.upper(),
                'interval': interval,
                'limit': limit
            }

            if end_time:
                params['endTime'] = end_time

            self.logger.debug(f"Fetching klines: {params}")

            response = requests.get(
                url,
                params=params,
                timeout=self.timeout
            )
            response.raise_for_status()

            data = response.json()

            # Parse klines to Candle entities
            candles = []
            for kline in data:
                candle = self._parse_kline(kline)
                if candle:
                    candles.append(candle)

            self.logger.info(f"Fetched {len(candles)} klines for {symbol} {interval}")
            return candles

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Failed to fetch klines: {e}")
            return []
        except Exception as e:
            self.logger.error(f"Error parsing klines: {e}")
            return []

    def _parse_kline(self, kline: List) -> Optional[Candle]:
        """
        Parse Binance kline array to Candle entity.

        Binance kline format:
        [
            1499040000000,      # 0: Open time
            "0.01634790",       # 1: Open
            "0.80765069",       # 2: High
            "0.01575800",       # 3: Low
            "0.01577100",       # 4: Close
            "148976.11427815",  # 5: Volume
            1499644799999,      # 6: Close time
            "2434.19055334",    # 7: Quote asset volume
            31,                 # 8: Number of trades
            "1756.87402397",    # 9: Taker buy base asset volume
            "28.46694368",      # 10: Taker buy quote asset volume
            "0"                 # 11: Ignore
        ]

        Args:
            kline: Kline array from Binance

        Returns:
            Candle entity or None if parsing fails
        """
        try:
            timestamp_ms = int(kline[0])
            open_price = float(kline[1])
            high_price = float(kline[2])
            low_price = float(kline[3])
            close_price = float(kline[4])
            volume = float(kline[5])

            # CRITICAL SOTA FIX: Use timezone-aware datetime to ensure correct .timestamp() conversion
            # utcfromtimestamp creates NAIVE datetime, .timestamp() wrongly assumes local time
            # fromtimestamp with tz=timezone.utc creates AWARE datetime, .timestamp() works correctly
            timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)

            return Candle(
                timestamp=timestamp,
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=volume
            )

        except (ValueError, IndexError) as e:
            self.logger.error(f"Error parsing kline: {e}")
            return None

    def get_server_time(self) -> Optional[int]:
        """
        Get server time from Binance.

        Returns:
            Server time in milliseconds or None if failed
        """
        try:
            url = f"{self.base_url}/time"
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()

            data = response.json()
            return data.get('serverTime')

        except Exception as e:
            self.logger.error(f"Failed to get server time: {e}")
            return None

    def get_exchange_info(self) -> Optional[Dict[str, Any]]:
        """
        Get exchange information.

        Returns:
            Exchange info dict or None if failed
        """
        try:
            url = f"{self.base_url}/exchangeInfo"
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()

            return response.json()

        except Exception as e:
            self.logger.error(f"Failed to get exchange info: {e}")
            return None

    def get_top_volume_pairs(self, limit: int = 10, quote_asset: str = "USDT") -> List[str]:
        """
        Get top trading pairs by 24h quote volume.

        Args:
            limit: Number of pairs to return
            quote_asset: Filter by quote asset (e.g., 'USDT')

        Returns:
            List of symbol strings (e.g., ['BTCUSDT', 'ETHUSDT'])
        """
        try:
            url = f"{self.base_url}/ticker/24hr"
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()

            data = response.json()

            # Filter and sort
            filtered = [
                item for item in data
                if item['symbol'].endswith(quote_asset)
                and not item['symbol'].startswith('USDC') # Exclude stable pairs
                and not item['symbol'].startswith('FDUSD')
            ]

            # Sort by quoteVolume (descending)
            sorted_pairs = sorted(
                filtered,
                key=lambda x: float(x['quoteVolume']),
                reverse=True
            )

            return [item['symbol'] for item in sorted_pairs[:limit]]

        except Exception as e:
            self.logger.error(f"Failed to get top volume pairs: {e}")
            return []

    def __repr__(self) -> str:
        """String representation"""
        return f"BinanceRestClient(mode={self.market_mode.value}, base_url={self.base_url})"
