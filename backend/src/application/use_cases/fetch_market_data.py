"""
FetchMarketDataUseCase - Application Layer

Use case for fetching market data from external API.
"""

from typing import List, Protocol
import pandas as pd
from datetime import datetime

from ...domain.entities.candle import Candle


class BinanceClientProtocol(Protocol):
    """Protocol defining the interface for Binance API client"""
    def get_klines(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        """Fetch klines data from Binance API"""
        ...


class FetchMarketDataUseCase:
    """
    Use case for fetching market data from Binance API.

    This use case:
    1. Fetches raw data from Binance API
    2. Converts to domain entities (Candle)
    3. Returns list of Candle entities

    Dependencies are injected via constructor (Dependency Injection).
    """

    def __init__(self, binance_client: BinanceClientProtocol):
        """
        Initialize use case with dependencies.

        Args:
            binance_client: Client for fetching data from Binance API
        """
        self.client = binance_client

    def execute(
        self,
        symbol: str = 'BTCUSDT',
        timeframe: str = '15m',
        limit: int = 100
    ) -> List[Candle]:
        """
        Execute the use case: fetch market data and convert to entities.

        Args:
            symbol: Trading pair (default: 'BTCUSDT')
            timeframe: Timeframe (default: '15m')
            limit: Number of candles to fetch (default: 100)

        Returns:
            List of Candle entities

        Raises:
            ValueError: If parameters are invalid
            RuntimeError: If API call fails
        """
        # Validate inputs
        if limit <= 0:
            raise ValueError(f"Limit must be positive, got {limit}")

        if limit > 1000:
            raise ValueError(f"Limit cannot exceed 1000, got {limit}")

        # Fetch data from API
        try:
            df = self.client.get_klines(symbol, timeframe, limit)
        except Exception as e:
            raise RuntimeError(f"Failed to fetch data from Binance: {e}") from e

        if df is None or df.empty:
            return []

        # Vectorized conversion — avoid iterrows() overhead
        try:
            timestamps = pd.to_datetime(df['open_time'], unit='ms').dt.to_pydatetime().tolist()
            opens = df['open'].astype(float).tolist()
            highs = df['high'].astype(float).tolist()
            lows = df['low'].astype(float).tolist()
            closes = df['close'].astype(float).tolist()
            volumes = df['volume'].astype(float).tolist()
            return [
                Candle(timestamp=ts, open=o, high=h, low=l, close=c, volume=v)
                for ts, o, h, l, c, v in zip(timestamps, opens, highs, lows, closes, volumes)
            ]
        except (KeyError, ValueError):
            return []
