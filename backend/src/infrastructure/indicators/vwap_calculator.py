"""
VWAP Calculator - Volume Weighted Average Price

Replaces EMA for trend identification in intraday trading.
VWAP shows the average price weighted by volume - where institutional money is.
"""

from typing import List, Optional
from dataclasses import dataclass
import pandas as pd

from ...domain.entities.candle import Candle


@dataclass
class VWAPResult:
    """VWAP calculation result"""
    vwap: float
    period_volume: float
    typical_price_volume: float


class VWAPCalculator:
    """
    Calculate Volume Weighted Average Price (VWAP).

    VWAP = Σ(Typical Price × Volume) / Σ(Volume)
    Typical Price = (High + Low + Close) / 3

    Usage:
        - Price > VWAP: Bullish bias (buy pullbacks)
        - Price < VWAP: Bearish bias (sell rallies)
        - VWAP acts as dynamic support/resistance
    """

    def __init__(self):
        """Initialize VWAP calculator"""
        pass

    def calculate_vwap(self, candles: List[Candle]) -> Optional[VWAPResult]:
        """
        Calculate VWAP for given candles.

        Args:
            candles: List of Candle objects (chronological order)

        Returns:
            VWAPResult with VWAP value, or None if insufficient data
        """
        if not candles or len(candles) < 1:
            return None

        # Filter candles for the current day (Anchored VWAP)
        if not candles:
            return None

        last_candle = candles[-1]
        current_date = last_candle.timestamp.date()

        # Traverse backwards to extract only the current day's candles (O(1) approach)
        day_candles = []
        for c in reversed(candles):
            if c.timestamp.date() == current_date:
                day_candles.append(c)
            else:
                break
        day_candles.reverse()

        if not day_candles:
            return None

        # Calculate typical price for each candle
        typical_prices = [
            (c.high + c.low + c.close) / 3.0
            for c in day_candles
        ]

        # Calculate TPV (Typical Price × Volume)
        typical_price_volume = [
            tp * c.volume
            for tp, c in zip(typical_prices, day_candles)
        ]

        # Sum values
        total_tpv = sum(typical_price_volume)
        total_volume = sum(c.volume for c in day_candles)

        # Avoid division by zero
        if total_volume == 0:
            return None

        # Calculate VWAP
        vwap = total_tpv / total_volume

        return VWAPResult(
            vwap=vwap,
            period_volume=total_volume,
            typical_price_volume=total_tpv
        )

    def calculate_vwap_series(self, candles: List[Candle]) -> Optional[pd.Series]:
        """
        Calculate rolling VWAP series (useful for charting).

        Args:
            candles: List of Candle objects

        Returns:
            Pandas Series with VWAP values for each candle
        """
        if not candles or len(candles) < 1:
            return None

        # Convert to DataFrame
        df = pd.DataFrame({
            'timestamp': [c.timestamp for c in candles],
            'high': [c.high for c in candles],
            'low': [c.low for c in candles],
            'close': [c.close for c in candles],
            'volume': [c.volume for c in candles]
        })

        # SOTA FIX: Ensure timestamp is datetime aware before accessing .dt
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True, errors='coerce')
            df.dropna(subset=['timestamp'], inplace=True)


        # Calculate typical price
        df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3

        # Calculate TPV
        df['tpv'] = df['typical_price'] * df['volume']

        # Group by date to implement Anchored VWAP (reset daily)
        # We use the date part of the timestamp for grouping
        df['date'] = df['timestamp'].dt.date

        # Calculate cumulative sums per group (day)
        df['cum_tpv'] = df.groupby('date')['tpv'].cumsum()
        df['cum_volume'] = df.groupby('date')['volume'].cumsum()

        # Calculate VWAP
        df['vwap'] = df['cum_tpv'] / df['cum_volume']

        return df['vwap']

    def is_above_vwap(self, price: float, vwap: float, buffer_pct: float = 0.0) -> bool:
        """
        Check if price is above VWAP with optional buffer.

        Args:
            price: Current price
            vwap: VWAP value
            buffer_pct: Buffer percentage (e.g., 0.001 = 0.1%)

        Returns:
            True if price > VWAP * (1 + buffer)
        """
        return price > vwap * (1 + buffer_pct)

    def is_below_vwap(self, price: float, vwap: float, buffer_pct: float = 0.0) -> bool:
        """
        Check if price is below VWAP with optional buffer.

        Args:
            price: Current price
            vwap: VWAP value
            buffer_pct: Buffer percentage (e.g., 0.001 = 0.1%)

        Returns:
            True if price < VWAP * (1 - buffer)
        """
        return price < vwap * (1 - buffer_pct)

    def calculate_distance_from_vwap(self, price: float, vwap: float) -> float:
        """
        Calculate percentage distance from VWAP.

        Args:
            price: Current price
            vwap: VWAP value

        Returns:
            Percentage distance (positive if above, negative if below)
        """
        return ((price - vwap) / vwap) * 100.0
