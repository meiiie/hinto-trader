"""
Stochastic RSI Calculator

More sensitive oscillator for timing entries in trending markets.
Combines Stochastic and RSI for faster signals.
"""

from typing import List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import pandas as pd
import numpy as np

from ...domain.entities.candle import Candle


class StochRSIZone(Enum):
    """Stochastic RSI zones"""
    OVERSOLD = "oversold"  # < 20
    NEUTRAL = "neutral"     # 20-80
    OVERBOUGHT = "overbought"  # > 80


@dataclass
class StochRSIResult:
    """Stochastic RSI calculation result"""
    k_value: float  # Fast line
    d_value: float  # Slow line (signal line)
    rsi_value: float  # Underlying RSI
    zone: StochRSIZone
    is_oversold: bool  # K < 20
    is_overbought: bool  # K > 80
    k_cross_up: bool  # K crossed above D (bullish)
    k_cross_down: bool  # K crossed below D (bearish)


class StochRSICalculator:
    """
    Calculate Stochastic RSI.

    Formula:
        1. Calculate RSI(rsi_period)
        2. StochRSI = (RSI - Min(RSI, k_period)) / (Max(RSI, k_period) - Min(RSI, k_period))
        3. %K = SMA(StochRSI, k_period)
        4. %D = SMA(%K, d_period)

    Usage:
        - %K < 20 + Cross up: Bullish trigger
        - %K > 80 + Cross down: Bearish trigger
        - More sensitive than regular RSI for intraday trading
    """

    def __init__(
        self,
        k_period: int = 3,
        d_period: int = 3,
        rsi_period: int = 14,
        stoch_period: int = 14
    ):
        """
        Initialize Stochastic RSI calculator.

        Args:
            k_period: %K smoothing period (default: 3)
            d_period: %D smoothing period (default: 3)
            rsi_period: RSI calculation period (default: 14)
            stoch_period: Stochastic lookback period (default: 14)
        """
        self.k_period = k_period
        self.d_period = d_period
        self.rsi_period = rsi_period
        self.stoch_period = stoch_period

    def calculate_rsi(self, closes: pd.Series, period: int) -> pd.Series:
        """Calculate RSI"""
        delta = closes.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def calculate_stoch_rsi(
        self,
        candles: List[Candle]
    ) -> Optional[StochRSIResult]:
        """
        Calculate Stochastic RSI for given candles.

        Args:
            candles: List of Candle objects (chronological order)

        Returns:
            StochRSIResult or None if insufficient data
        """
        min_required = self.rsi_period + self.stoch_period + self.k_period + self.d_period

        if not candles or len(candles) < min_required:
            return None

        # Limit history to what is needed to stabilize RSI (~10x period) + required periods
        history_needed = max(150, self.rsi_period * 10) + self.stoch_period + self.k_period + self.d_period
        calc_candles = candles[-history_needed:] if len(candles) > history_needed else candles

        # Extract close prices natively
        closes = [c.close for c in calc_candles]

        # Step 1: Calculate RSI
        # Native Wilder's Smoothing RSI
        rsis = [0.0] * len(closes)
        gains = [0.0] * len(closes)
        losses = [0.0] * len(closes)

        for i in range(1, len(closes)):
            change = closes[i] - closes[i-1]
            gains[i] = max(0.0, change)
            losses[i] = max(0.0, -change)

        # Initial averages
        avg_gain = sum(gains[1:self.rsi_period+1]) / self.rsi_period
        avg_loss = sum(losses[1:self.rsi_period+1]) / self.rsi_period
        if avg_loss == 0:
            rsis[self.rsi_period] = 100.0
        else:
            rsis[self.rsi_period] = 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))

        # Smoothed averages
        for i in range(self.rsi_period + 1, len(closes)):
            avg_gain = (avg_gain * (self.rsi_period - 1) + gains[i]) / self.rsi_period
            avg_loss = (avg_loss * (self.rsi_period - 1) + losses[i]) / self.rsi_period
            if avg_loss == 0:
                rsis[i] = 100.0
            else:
                rsis[i] = 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))

        # Step 2: Calculate Stochastic of RSI
        stoch_rsis = [50.0] * len(closes)
        start_stoch = self.rsi_period + self.stoch_period - 1
        for i in range(start_stoch, len(closes)):
            window = rsis[i - self.stoch_period + 1 : i + 1]
            min_rsi = min(window)
            max_rsi = max(window)
            if max_rsi == min_rsi:
                stoch_rsis[i] = 50.0
            else:
                stoch_rsis[i] = ((rsis[i] - min_rsi) / (max_rsi - min_rsi)) * 100.0

        # Step 3: Calculate %K (SMA of StochRSI)
        k_lines = [50.0] * len(closes)
        start_k = start_stoch + self.k_period - 1
        for i in range(start_k, len(closes)):
            k_lines[i] = sum(stoch_rsis[i - self.k_period + 1 : i + 1]) / self.k_period

        # Step 4: Calculate %D (SMA of %K)
        d_lines = [50.0] * len(closes)
        start_d = start_k + self.d_period - 1
        for i in range(start_d, len(closes)):
            d_lines[i] = sum(k_lines[i - self.d_period + 1 : i + 1]) / self.d_period

        k_current = k_lines[-1]
        d_current = d_lines[-1]
        rsi_current = rsis[-1]

        # Get previous values for crossover detection
        k_previous = k_lines[-2] if len(k_lines) > 1 else k_current
        d_previous = d_lines[-2] if len(d_lines) > 1 else d_current

        # Determine zone
        if k_current < 20:
            zone = StochRSIZone.OVERSOLD
        elif k_current > 80:
            zone = StochRSIZone.OVERBOUGHT
        else:
            zone = StochRSIZone.NEUTRAL

        # Detect crossovers
        k_cross_up = (k_previous <= d_previous) and (k_current > d_current)
        k_cross_down = (k_previous >= d_previous) and (k_current < d_current)

        return StochRSIResult(
            k_value=float(k_current),
            d_value=float(d_current),
            rsi_value=float(rsi_current),
            zone=zone,
            is_oversold=k_current < 20,
            is_overbought=k_current > 80,
            k_cross_up=bool(k_cross_up),
            k_cross_down=bool(k_cross_down)
        )

    def get_series(
        self,
        candles: List[Candle]
    ) -> Optional[Tuple[pd.Series, pd.Series]]:
        """
        Get full StochRSI series for plotting.

        Args:
            candles: List of Candle objects

        Returns:
            Tuple of (%K series, %D series) or None
        """
        min_required = self.rsi_period + self.stoch_period + self.k_period + self.d_period

        if not candles or len(candles) < min_required:
            return None

        closes = pd.Series([c.close for c in candles])

        # Calculate RSI
        rsi = self.calculate_rsi(closes, self.rsi_period)

        # Calculate Stochastic of RSI
        rsi_min = rsi.rolling(window=self.stoch_period).min()
        rsi_max = rsi.rolling(window=self.stoch_period).max()
        stoch_rsi = (rsi - rsi_min) / (rsi_max - rsi_min) * 100
        stoch_rsi = stoch_rsi.fillna(50)

        # Calculate %K and %D
        k_line = stoch_rsi.rolling(window=self.k_period).mean()
        d_line = k_line.rolling(window=self.d_period).mean()

        return (k_line, d_line)
