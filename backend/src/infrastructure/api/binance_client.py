"""
BinanceClient - Infrastructure Layer

Binance API client for fetching market data.
Refactored version without Config dependency.
"""

import requests
import pandas as pd
from typing import Optional
import logging


class BinanceClient:
    """
    Client for interacting with Binance API.

    This client handles:
    - HTTP requests to Binance API
    - Data conversion to pandas DataFrame
    - Error handling and retries
    - Rate limiting awareness
    """

    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        """
        Initialize Binance client.

        Args:
            api_key: Binance API key (optional for public endpoints)
            api_secret: Binance API secret (optional for public endpoints)
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://api.binance.com/api/v3"
        self.session = requests.Session()
        self.logger = logging.getLogger(__name__)

        # Set headers if API key is provided
        if self.api_key:
            self.session.headers.update({
                'X-MBX-APIKEY': self.api_key
            })

    def get_klines(
        self,
        symbol: str = 'BTCUSDT',
        interval: str = '15m',
        limit: int = 100
    ) -> Optional[pd.DataFrame]:
        """
        Get kline/candlestick data from Binance.

        Args:
            symbol: Trading pair symbol (default: 'BTCUSDT')
            interval: Kline interval (default: '15m')
            limit: Number of klines to retrieve (default: 100, max: 1000)

        Returns:
            DataFrame with columns: open_time, open, high, low, close, volume
            Returns None if request fails

        Raises:
            requests.RequestException: If API request fails
        """
        try:
            # Validate parameters
            if limit > 1000:
                limit = 1000
                self.logger.warning(f"Limit reduced to 1000 (max allowed)")

            # Prepare request parameters
            params = {
                'symbol': symbol.upper(),
                'interval': interval,
                'limit': limit
            }

            # Make API request
            self.logger.debug(f"Fetching {limit} klines for {symbol} ({interval})")
            response = self.session.get(
                f"{self.base_url}/klines",
                params=params,
                timeout=30
            )

            # Handle HTTP errors
            if response.status_code == 403:
                self.logger.error("API access forbidden - check API key")
                raise requests.RequestException("API access forbidden")
            elif response.status_code == 429:
                self.logger.error("Rate limit exceeded")
                raise requests.RequestException("Rate limit exceeded")
            elif response.status_code >= 500:
                self.logger.error(f"Binance server error: {response.status_code}")
                raise requests.RequestException(f"Server error: {response.status_code}")

            response.raise_for_status()

            # Parse response
            data = response.json()

            if not data:
                self.logger.warning("No data returned from API")
                return None

            # Convert to DataFrame
            df = pd.DataFrame(data, columns=[
                'open_time', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'number_of_trades',
                'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
            ])

            # Keep only required columns
            df = df[['open_time', 'open', 'high', 'low', 'close', 'volume']]

            # Convert data types
            df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
            df['open'] = df['open'].astype(float)
            df['high'] = df['high'].astype(float)
            df['low'] = df['low'].astype(float)
            df['close'] = df['close'].astype(float)
            df['volume'] = df['volume'].astype(float)

            # Set timestamp as index
            df.set_index('open_time', inplace=True)
            df.index.name = 'timestamp'

            self.logger.info(f"Successfully fetched {len(df)} klines for {symbol}")
            return df

        except requests.RequestException as e:
            self.logger.error(f"API request failed: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error in get_klines: {e}")
            return None

    def get_server_time(self) -> Optional[int]:
        """
        Get Binance server time.

        Returns:
            Server time in milliseconds, None if request fails
        """
        try:
            response = self.session.get(
                f"{self.base_url}/time",
                timeout=10
            )
            response.raise_for_status()

            data = response.json()
            return data['serverTime']

        except Exception as e:
            self.logger.error(f"Failed to get server time: {e}")
            return None

    def test_connection(self) -> bool:
        """
        Test connection to Binance API.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            server_time = self.get_server_time()
            return server_time is not None
        except Exception:
            return False

    def close(self):
        """
        Close the HTTP session.

        Should be called when done using the client.
        """
        if self.session:
            self.session.close()

    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()

    def __repr__(self) -> str:
        """String representation"""
        return (
            f"BinanceClient("
            f"base_url='{self.base_url}', "
            f"authenticated={bool(self.api_key)}"
            f")"
        )
