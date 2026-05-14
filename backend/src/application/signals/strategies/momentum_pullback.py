"""Adaptive momentum pullback trend runner.

Research-only strategy family inspired by time-series momentum. It avoids raw
breakout chasing: first require a multi-horizon trend, then enter only after a
pullback reclaims a short EMA with controlled ATR risk.
"""

from __future__ import annotations

from typing import Any, Optional

from ....domain.entities.trading_signal import SignalPriority, SignalType, TradingSignal
from ..strategy_ids import MOMENTUM_PULLBACK_STRATEGY_ID


class MomentumPullbackStrategy:
    """Generate trend-continuation signals after EMA pullbacks."""

    def __init__(
        self,
        ema_fast: int = 48,
        ema_slow: int = 192,
        momentum_short_bars: int = 24,
        momentum_long_bars: int = 96,
        swing_lookback: int = 16,
        atr_buffer_multiple: float = 0.35,
        max_stop_pct: float = 0.014,
        reward_r: float = 2.4,
        min_long_momentum_pct: float = 0.006,
        min_short_momentum_pct: float = 0.010,
        min_reclaim_body_ratio: float = 0.30,
        min_volume_ratio: float = 0.95,
        volume_lookback: int = 48,
    ) -> None:
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.momentum_short_bars = momentum_short_bars
        self.momentum_long_bars = momentum_long_bars
        self.swing_lookback = swing_lookback
        self.atr_buffer_multiple = atr_buffer_multiple
        self.max_stop_pct = max_stop_pct
        self.reward_r = reward_r
        self.min_long_momentum_pct = min_long_momentum_pct
        self.min_short_momentum_pct = min_short_momentum_pct
        self.min_reclaim_body_ratio = min_reclaim_body_ratio
        self.min_volume_ratio = min_volume_ratio
        self.volume_lookback = volume_lookback

    def generate(
        self,
        ctx: Any,
        symbol: str,
        htf_bias: str = "NEUTRAL",
        **_: Any,
    ) -> Optional[TradingSignal]:
        min_candles = max(
            self.ema_slow + 2,
            self.momentum_long_bars + 2,
            self.volume_lookback + 2,
            self.swing_lookback + 2,
        )
        if len(ctx.candles) < min_candles:
            return None
        if not ctx.atr_result or getattr(ctx.atr_result, "atr_value", 0) <= 0:
            return None

        current = ctx.current_candle
        previous = ctx.candles[-2]
        close = float(current.close)
        if close <= 0:
            return None

        candle_range = float(current.high - current.low)
        if candle_range <= 0:
            return None
        body_ratio = abs(float(current.close - current.open)) / candle_range
        if body_ratio < self.min_reclaim_body_ratio:
            return None

        closes = [float(c.close) for c in ctx.candles]
        ema_fast_value = self._ema(closes, self.ema_fast)
        ema_slow_value = self._ema(closes, self.ema_slow)
        momentum_short = self._pct_change(closes, self.momentum_short_bars)
        momentum_long = self._pct_change(closes, self.momentum_long_bars)
        volume_ratio = self._volume_ratio(ctx.candles)
        if volume_ratio < self.min_volume_ratio:
            return None

        bias = (htf_bias or "NEUTRAL").upper()
        trend_up = (
            ema_fast_value > ema_slow_value
            and momentum_long >= self.min_long_momentum_pct
            and momentum_short > 0
            and bias != "BEARISH"
        )
        trend_down = (
            ema_fast_value < ema_slow_value
            and momentum_long <= -self.min_short_momentum_pct
            and momentum_short < 0
            and bias != "BULLISH"
        )

        long_reclaim = (
            trend_up
            and previous.close <= ema_fast_value
            and current.close > ema_fast_value
            and current.close > current.open
        )
        short_reclaim = (
            trend_down
            and previous.close >= ema_fast_value
            and current.close < ema_fast_value
            and current.close < current.open
        )

        atr = float(ctx.atr_result.atr_value)
        swing = ctx.candles[-self.swing_lookback - 1 : -1]
        if long_reclaim:
            swing_low = min(float(c.low) for c in swing)
            stop = min(float(current.low), swing_low) - atr * self.atr_buffer_multiple
            return self._build_signal(
                ctx,
                symbol,
                SignalType.BUY,
                stop,
                ema_fast_value,
                momentum_short,
                momentum_long,
                volume_ratio,
                body_ratio,
            )
        if short_reclaim:
            swing_high = max(float(c.high) for c in swing)
            stop = max(float(current.high), swing_high) + atr * self.atr_buffer_multiple
            return self._build_signal(
                ctx,
                symbol,
                SignalType.SELL,
                stop,
                ema_fast_value,
                momentum_short,
                momentum_long,
                volume_ratio,
                body_ratio,
            )
        return None

    def _build_signal(
        self,
        ctx: Any,
        symbol: str,
        signal_type: SignalType,
        stop_loss: float,
        ema_fast_value: float,
        momentum_short: float,
        momentum_long: float,
        volume_ratio: float,
        body_ratio: float,
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
        tp2 = entry + direction * risk * (self.reward_r + 1.0)
        tp3 = entry + direction * risk * (self.reward_r + 2.0)

        indicators = dict(getattr(ctx, "indicators", {}) or {})
        indicators.update(
            {
                "strategy_id": MOMENTUM_PULLBACK_STRATEGY_ID,
                "payoff_shape": "positive_skew",
                "ema_fast": round(ema_fast_value, 8),
                "momentum_short_pct": round(momentum_short * 100.0, 4),
                "momentum_long_pct": round(momentum_long * 100.0, 4),
                "risk_r": round(stop_pct, 6),
                "volume_ratio": round(volume_ratio, 4),
                "body_ratio": round(body_ratio, 4),
                "research_exit_profile": {
                    "profile_name": "momentum_pullback_2p4r",
                    "close_profitable_auto": False,
                    "profitable_threshold_pct": 20.0,
                    "trailing_stop_atr": 2.8,
                    "partial_close_ac": False,
                },
            }
        )

        return TradingSignal(
            symbol=symbol,
            signal_type=signal_type,
            priority=SignalPriority.HIGH,
            confidence=0.76,
            generated_at=ctx.current_candle.timestamp,
            price=entry,
            entry_price=entry,
            is_limit_order=False,
            stop_loss=stop_loss,
            tp_levels={"tp1": tp1, "tp2": tp2, "tp3": tp3},
            risk_reward_ratio=self.reward_r,
            reasons=[
                f"Momentum pullback {signal_type.value.upper()} @ {entry:.4f}",
                f"Stop={stop_pct:.2%}, mom24={momentum_short:.2%}, mom96={momentum_long:.2%}",
                f"Volume={volume_ratio:.2f}x, body={body_ratio:.2f}, target={self.reward_r:.1f}R",
            ],
            indicators=indicators,
        )

    def _volume_ratio(self, candles: list[Any]) -> float:
        recent = candles[-self.volume_lookback - 1 : -1]
        if not recent:
            return 0.0
        avg_volume = sum(float(c.volume) for c in recent) / len(recent)
        if avg_volume <= 0:
            return 0.0
        return float(candles[-1].volume) / avg_volume

    @staticmethod
    def _pct_change(values: list[float], lookback: int) -> float:
        past = values[-lookback - 1]
        if past <= 0:
            return 0.0
        return (values[-1] - past) / past

    @staticmethod
    def _ema(values: list[float], period: int) -> float:
        multiplier = 2 / (period + 1)
        ema = sum(values[:period]) / period
        for value in values[period:]:
            ema = (value * multiplier) + (ema * (1 - multiplier))
        return ema
