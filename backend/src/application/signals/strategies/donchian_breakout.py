"""Donchian breakout trend runner.

This is a research-only positive-skew strategy family. It enters when the close
breaks a prior channel with volatility and volume confirmation, then relies on
ATR-defined risk and larger R-multiple targets rather than a high win rate.
"""

from __future__ import annotations

from typing import Any, Optional

from ....domain.entities.trading_signal import SignalPriority, SignalType, TradingSignal
from ..strategy_ids import DONCHIAN_BREAKOUT_STRATEGY_ID


class DonchianBreakoutStrategy:
    """Generate market-entry breakout signals from prior Donchian channels."""

    def __init__(
        self,
        lookback: int = 192,
        ema_fast: int = 64,
        ema_slow: int = 192,
        atr_stop_multiple: float = 1.6,
        max_stop_pct: float = 0.018,
        reward_r: float = 3.2,
        min_breakout_pct: float = 0.0012,
        volume_lookback: int = 96,
        min_volume_ratio: float = 1.40,
        min_body_to_range: float = 0.45,
        min_close_location: float = 0.75,
        min_atr_pct: float = 0.001,
        max_atr_pct: float = 0.035,
    ):
        self.lookback = lookback
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.atr_stop_multiple = atr_stop_multiple
        self.max_stop_pct = max_stop_pct
        self.reward_r = reward_r
        self.min_breakout_pct = min_breakout_pct
        self.volume_lookback = volume_lookback
        self.min_volume_ratio = min_volume_ratio
        self.min_body_to_range = min_body_to_range
        self.min_close_location = min_close_location
        self.min_atr_pct = min_atr_pct
        self.max_atr_pct = max_atr_pct

    def generate(
        self,
        ctx: Any,
        symbol: str,
        htf_bias: str = "NEUTRAL",
        **_: Any,
    ) -> Optional[TradingSignal]:
        min_candles = max(self.lookback + 2, self.ema_slow + 2, self.volume_lookback + 2)
        if len(ctx.candles) < min_candles:
            return None
        if not ctx.atr_result or getattr(ctx.atr_result, "atr_value", 0) <= 0:
            return None

        current = ctx.current_candle
        previous = ctx.candles[-self.lookback - 1 : -1]
        upper = max(c.high for c in previous)
        lower = min(c.low for c in previous)
        if upper <= 0 or lower <= 0:
            return None

        closes = [float(c.close) for c in ctx.candles]
        trend = self._resolve_trend(closes, htf_bias)
        volume_ratio = self._volume_ratio(ctx.candles)
        if volume_ratio < self.min_volume_ratio:
            return None

        close_price = float(current.close)
        candle_range = float(current.high - current.low)
        if candle_range <= 0 or close_price <= 0:
            return None
        body_ratio = abs(float(current.close - current.open)) / candle_range
        if body_ratio < self.min_body_to_range:
            return None
        close_location = (close_price - float(current.low)) / candle_range
        atr = float(ctx.atr_result.atr_value)
        atr_pct = atr / close_price
        if atr_pct < self.min_atr_pct or atr_pct > self.max_atr_pct:
            return None

        long_breakout = (
            trend == "BULLISH"
            and close_price > upper * (1.0 + self.min_breakout_pct)
            and current.close > current.open
            and close_location >= self.min_close_location
        )
        short_breakout = (
            trend == "BEARISH"
            and close_price < lower * (1.0 - self.min_breakout_pct)
            and current.close < current.open
            and close_location <= (1.0 - self.min_close_location)
        )

        if long_breakout:
            stop = max(close_price - atr * self.atr_stop_multiple, lower)
            return self._build_signal(
                ctx, symbol, SignalType.BUY, upper, stop, trend, atr, volume_ratio, body_ratio
            )
        if short_breakout:
            stop = min(close_price + atr * self.atr_stop_multiple, upper)
            return self._build_signal(
                ctx, symbol, SignalType.SELL, lower, stop, trend, atr, volume_ratio, body_ratio
            )
        return None

    def _build_signal(
        self,
        ctx: Any,
        symbol: str,
        signal_type: SignalType,
        channel_level: float,
        stop_loss: float,
        trend: str,
        atr: float,
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

        is_long = signal_type == SignalType.BUY
        direction = 1 if is_long else -1
        tp1 = entry + direction * risk * self.reward_r
        tp2 = entry + direction * risk * (self.reward_r + 1.5)
        tp3 = entry + direction * risk * (self.reward_r + 3.0)

        indicators = dict(getattr(ctx, "indicators", {}) or {})
        indicators.update(
            {
                "strategy_id": DONCHIAN_BREAKOUT_STRATEGY_ID,
                "payoff_shape": "positive_skew",
                "donchian_lookback": self.lookback,
                "channel_level": round(channel_level, 8),
                "atr": round(atr, 8),
                "risk_r": round(stop_pct, 6),
                "volume_ratio": round(volume_ratio, 4),
                "body_ratio": round(body_ratio, 4),
                "research_exit_profile": {
                    "profile_name": "donchian_breakout_3p2r_strict",
                    "close_profitable_auto": False,
                    "profitable_threshold_pct": 20.0,
                    "trailing_stop_atr": 2.4,
                    "partial_close_ac": False,
                },
            }
        )

        return TradingSignal(
            symbol=symbol,
            signal_type=signal_type,
            priority=SignalPriority.HIGH,
            confidence=0.74,
            generated_at=ctx.current_candle.timestamp,
            price=entry,
            entry_price=entry,
            is_limit_order=False,
            stop_loss=stop_loss,
            tp_levels={"tp1": tp1, "tp2": tp2, "tp3": tp3},
            risk_reward_ratio=self.reward_r,
            reasons=[
                f"Donchian {signal_type.value.upper()} breakout @ {entry:.4f}",
                (
                    f"Channel={channel_level:.4f}, stop={stop_pct:.2%}, "
                    f"volume={volume_ratio:.2f}x, body={body_ratio:.2f}"
                ),
                f"Trend={trend}, target={self.reward_r:.1f}R",
            ],
            indicators=indicators,
        )

    def _resolve_trend(self, closes: list[float], htf_bias: str) -> str:
        bias = (htf_bias or "NEUTRAL").upper()
        if bias in {"BULLISH", "BEARISH"}:
            return bias

        fast = self._ema(closes, self.ema_fast)
        slow = self._ema(closes, self.ema_slow)
        if fast > slow:
            return "BULLISH"
        if fast < slow:
            return "BEARISH"
        return "NEUTRAL"

    def _volume_ratio(self, candles: list[Any]) -> float:
        recent = candles[-self.volume_lookback - 1 : -1]
        if not recent:
            return 0.0
        avg_volume = sum(float(c.volume) for c in recent) / len(recent)
        if avg_volume <= 0:
            return 0.0
        return float(candles[-1].volume) / avg_volume

    @staticmethod
    def _ema(values: list[float], period: int) -> float:
        multiplier = 2 / (period + 1)
        ema = sum(values[:period]) / period
        for value in values[period:]:
            ema = (value * multiplier) + (ema * (1 - multiplier))
        return ema
