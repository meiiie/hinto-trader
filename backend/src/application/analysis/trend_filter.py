"""
HTF Trend Filter - Application Layer

Determines the higher timeframe bias using a configurable EMA period.
SOTA Principle: never fight the H4 trend.
"""

import logging
import pandas as pd
from typing import List, Dict, Optional, Tuple, Union
from enum import Enum
from dataclasses import dataclass

from ...domain.entities.candle import Candle


class TrendDirection(Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class TrendFilter:
    """
    Analyzes HTF (Higher Timeframe) data to provide a trading bias.
    """

    def __init__(self, ema_period: int = 200, buffer_pct: float = 0.005):
        if ema_period < 1:
            raise ValueError("EMA period must be at least 1")

        if not (0.0 <= buffer_pct < 0.10):
            raise ValueError("Buffer percentage must be between 0.0 and 0.10")

        self.ema_period = ema_period
        self.buffer_pct = buffer_pct
        self.logger = logging.getLogger(__name__)

    def _calculate_ema(self, candles: List[Candle], period: int) -> float:
        """
        Calculate EMA for the given period.
        """
        if not candles:
            return 0.0

        # Limit history to what is needed to stabilize EMA (~5x period)
        history_needed = max(1000, period * 5)
        calc_candles = candles[-history_needed:] if len(candles) > history_needed else candles

        # Calculate EMA without Pandas
        k = 2 / (period + 1)
        ema = calc_candles[0].close
        for c in calc_candles[1:]:
            ema = (c.close * k) + (ema * (1 - k))
        return ema

    def get_trend_direction(self, candles: List[Candle]) -> TrendDirection:
        """
        Returns TrendDirection.BULLISH, BEARISH, or NEUTRAL.
        """
        if len(candles) < self.ema_period:
            return TrendDirection.NEUTRAL

        ema_value = self._calculate_ema(candles, self.ema_period)
        current_price = candles[-1].close

        # SOTA: Add a small buffer to avoid whipsaws around EMA
        buffer = ema_value * self.buffer_pct

        if current_price > (ema_value + buffer):
            return TrendDirection.BULLISH
        elif current_price < (ema_value - buffer):
            return TrendDirection.BEARISH
        else:
            return TrendDirection.NEUTRAL

    def calculate_bias(self, htf_candles: List[Candle]) -> str:
        """
        Legacy wrapper for get_trend_direction.
        Returns string value of the enum.
        """
        return self.get_trend_direction(htf_candles).value

    def is_trade_allowed(self, signal_type: str, candles: List[Candle]) -> Tuple[bool, str]:
        """
        Check if trade is allowed based on trend direction.
        Returns (is_allowed, reason).
        """
        trend = self.get_trend_direction(candles)

        if signal_type not in ['BUY', 'SELL']:
            return False, f"Invalid signal direction: {signal_type}"

        if trend == TrendDirection.BULLISH:
            if signal_type == 'BUY':
                return True, "BUY allowed in bullish trend"
            else:
                return False, "SELL rejected in bullish trend"

        elif trend == TrendDirection.BEARISH:
            if signal_type == 'SELL':
                return True, "SELL allowed in bearish trend"
            else:
                return False, "BUY rejected in bearish trend"

        else: # NEUTRAL
            return False, f"{signal_type} rejected in neutral trend"

    def get_trend_info(self, candles: List[Candle]) -> Dict:
        """
        Return detailed trend information.
        """
        if len(candles) < self.ema_period:
            return {
                'is_valid': False,
                'ema_value': 0.0
            }

        ema_value = self._calculate_ema(candles, self.ema_period)
        current_price = candles[-1].close
        buffer = ema_value * self.buffer_pct

        trend = self.get_trend_direction(candles)

        return {
            'is_valid': True,
            'direction': trend.value,
            'ema_value': ema_value,
            'current_price': current_price,
            'spread_pct': (current_price - ema_value) / ema_value,
            'bullish_threshold': ema_value + buffer,
            'bearish_threshold': ema_value - buffer
        }

    def __repr__(self) -> str:
        return f"TrendFilter(ema_period={self.ema_period}, buffer={self.buffer_pct*100:.1f}%)"
