"""Volatility compression breakout strategy.

Research-only positive-skew family. It waits for Bollinger bandwidth to compress
relative to its own history, then only trades an expansion breakout when trend
and volume agree.
"""

from __future__ import annotations

from statistics import fmean, pstdev
from typing import Any, Optional

from ....domain.entities.trading_signal import SignalPriority, SignalType, TradingSignal
from ..strategy_ids import VOLATILITY_SQUEEZE_STRATEGY_ID


class VolatilitySqueezeBreakoutStrategy:
    """Generate signals after volatility compression starts expanding."""

    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        width_lookback: int = 160,
        squeeze_percentile: float = 0.20,
        expansion_ratio: float = 1.12,
        ema_fast: int = 50,
        ema_slow: int = 200,
        breakout_lookback: int = 96,
        close_location_min: float = 0.70,
        volume_lookback: int = 48,
        min_volume_ratio: float = 1.25,
        atr_stop_multiple: float = 1.2,
        max_stop_pct: float = 0.010,
        reward_r: float = 2.2,
        min_band_break_pct: float = 0.0003,
    ) -> None:
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.width_lookback = width_lookback
        self.squeeze_percentile = squeeze_percentile
        self.expansion_ratio = expansion_ratio
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.breakout_lookback = breakout_lookback
        self.close_location_min = close_location_min
        self.volume_lookback = volume_lookback
        self.min_volume_ratio = min_volume_ratio
        self.atr_stop_multiple = atr_stop_multiple
        self.max_stop_pct = max_stop_pct
        self.reward_r = reward_r
        self.min_band_break_pct = min_band_break_pct

    def generate(
        self,
        ctx: Any,
        symbol: str,
        htf_bias: str = "NEUTRAL",
        **_: Any,
    ) -> Optional[TradingSignal]:
        min_candles = max(
            self.ema_slow + 2,
            self.width_lookback + self.bb_period + 2,
            self.breakout_lookback + 2,
            self.volume_lookback + 2,
        )
        if len(ctx.candles) < min_candles:
            return None
        if not ctx.atr_result or getattr(ctx.atr_result, "atr_value", 0) <= 0:
            return None

        closes = [float(c.close) for c in ctx.candles]
        current = ctx.current_candle
        close = float(current.close)
        if close <= 0:
            return None

        bands = self._bollinger(closes[-self.bb_period :])
        if bands is None:
            return None
        middle, upper, lower, width = bands
        previous_width = self._band_width(closes[-self.bb_period - 1 : -1])
        if previous_width <= 0 or width < previous_width * self.expansion_ratio:
            return None

        width_history = self._recent_width_history(closes)
        if len(width_history) < self.width_lookback + 1:
            return None
        squeeze_threshold = self._percentile(width_history[-self.width_lookback - 1 : -1], self.squeeze_percentile)
        if previous_width > squeeze_threshold:
            return None

        volume_ratio = self._volume_ratio(ctx.candles)
        if volume_ratio < self.min_volume_ratio:
            return None

        fast = self._ema(closes, self.ema_fast)
        slow = self._ema(closes, self.ema_slow)
        bias = (htf_bias or "NEUTRAL").upper()
        trend_up = fast > slow and bias != "BEARISH"
        trend_down = fast < slow and bias != "BULLISH"
        recent_range = ctx.candles[-self.breakout_lookback - 1 : -1]
        previous_high = max(float(c.high) for c in recent_range)
        previous_low = min(float(c.low) for c in recent_range)
        close_location = self._close_location(current)

        long_breakout = (
            trend_up
            and close > upper * (1.0 + self.min_band_break_pct)
            and close > previous_high * (1.0 + self.min_band_break_pct)
            and close_location >= self.close_location_min
            and current.close > current.open
        )
        short_breakout = (
            trend_down
            and close < lower * (1.0 - self.min_band_break_pct)
            and close < previous_low * (1.0 - self.min_band_break_pct)
            and close_location <= (1.0 - self.close_location_min)
            and current.close < current.open
        )

        atr = float(ctx.atr_result.atr_value)
        if long_breakout:
            stop = min(middle, close - atr * self.atr_stop_multiple)
            return self._build_signal(
                ctx, symbol, SignalType.BUY, stop, width, previous_width, squeeze_threshold, volume_ratio
            )
        if short_breakout:
            stop = max(middle, close + atr * self.atr_stop_multiple)
            return self._build_signal(
                ctx, symbol, SignalType.SELL, stop, width, previous_width, squeeze_threshold, volume_ratio
            )
        return None

    def _build_signal(
        self,
        ctx: Any,
        symbol: str,
        signal_type: SignalType,
        stop_loss: float,
        width: float,
        previous_width: float,
        squeeze_threshold: float,
        volume_ratio: float,
    ) -> Optional[TradingSignal]:
        entry = float(ctx.current_candle.close)
        risk = abs(entry - stop_loss)
        if risk <= 0:
            return None
        stop_pct = risk / entry
        if stop_pct > self.max_stop_pct:
            return None

        direction = 1 if signal_type == SignalType.BUY else -1
        tp1 = entry + direction * risk * self.reward_r
        tp2 = entry + direction * risk * (self.reward_r + 1.2)
        tp3 = entry + direction * risk * (self.reward_r + 2.4)

        indicators = dict(getattr(ctx, "indicators", {}) or {})
        indicators.update(
            {
                "strategy_id": VOLATILITY_SQUEEZE_STRATEGY_ID,
                "payoff_shape": "positive_skew",
                "bb_width": round(width, 6),
                "bb_previous_width": round(previous_width, 6),
                "squeeze_threshold": round(squeeze_threshold, 6),
                "risk_r": round(stop_pct, 6),
                "volume_ratio": round(volume_ratio, 4),
                "breakout_lookback": self.breakout_lookback,
                "research_exit_profile": {
                    "profile_name": "vol_squeeze_structure_2p2r",
                    "close_profitable_auto": False,
                    "profitable_threshold_pct": 20.0,
                    "trailing_stop_atr": 2.6,
                    "partial_close_ac": False,
                },
            }
        )

        return TradingSignal(
            symbol=symbol,
            signal_type=signal_type,
            priority=SignalPriority.HIGH,
            confidence=0.75,
            generated_at=ctx.current_candle.timestamp,
            price=entry,
            entry_price=entry,
            is_limit_order=False,
            stop_loss=stop_loss,
            tp_levels={"tp1": tp1, "tp2": tp2, "tp3": tp3},
            risk_reward_ratio=self.reward_r,
            reasons=[
                f"Volatility squeeze {signal_type.value.upper()} breakout @ {entry:.4f}",
                f"Width {previous_width:.4f}->{width:.4f}, threshold={squeeze_threshold:.4f}",
                f"Stop={stop_pct:.2%}, volume={volume_ratio:.2f}x, target={self.reward_r:.1f}R",
            ],
            indicators=indicators,
        )

    def _width_history(self, closes: list[float]) -> list[float]:
        widths = []
        for end in range(self.bb_period, len(closes) + 1):
            width = self._band_width(closes[end - self.bb_period : end])
            if width > 0:
                widths.append(width)
        return widths

    def _recent_width_history(self, closes: list[float]) -> list[float]:
        required = self.width_lookback + self.bb_period + 1
        if len(closes) < required:
            return []
        return self._width_history(closes[-required:])

    def _band_width(self, values: list[float]) -> float:
        bands = self._bollinger(values)
        if not bands:
            return 0.0
        return bands[3]

    def _bollinger(self, values: list[float]) -> Optional[tuple[float, float, float, float]]:
        if len(values) < self.bb_period:
            return None
        middle = fmean(values)
        if middle <= 0:
            return None
        deviation = pstdev(values)
        upper = middle + self.bb_std * deviation
        lower = middle - self.bb_std * deviation
        width = (upper - lower) / middle
        return middle, upper, lower, width

    def _volume_ratio(self, candles: list[Any]) -> float:
        recent = candles[-self.volume_lookback - 1 : -1]
        if not recent:
            return 0.0
        avg_volume = sum(float(c.volume) for c in recent) / len(recent)
        if avg_volume <= 0:
            return 0.0
        return float(candles[-1].volume) / avg_volume

    @staticmethod
    def _close_location(candle: Any) -> float:
        high = float(candle.high)
        low = float(candle.low)
        if high <= low:
            return 0.5
        return (float(candle.close) - low) / (high - low)

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        index = min(max(int(round((len(ordered) - 1) * percentile)), 0), len(ordered) - 1)
        return ordered[index]

    @staticmethod
    def _ema(values: list[float], period: int) -> float:
        multiplier = 2 / (period + 1)
        ema = sum(values[:period]) / period
        for value in values[period:]:
            ema = (value * multiplier) + (ema * (1 - multiplier))
        return ema
