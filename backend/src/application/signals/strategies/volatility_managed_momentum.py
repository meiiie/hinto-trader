"""Volatility-managed momentum strategy.

Research-only family. It approximates volatility-managed time-series momentum
inside the signal layer: trade momentum pullback reclaims only when recent
realized volatility is below the symbol's own longer baseline.
"""

from __future__ import annotations

from statistics import pstdev
from typing import Any, Optional

from ....domain.entities.trading_signal import SignalPriority, SignalType, TradingSignal
from ..strategy_ids import VOLATILITY_MANAGED_MOMENTUM_STRATEGY_ID


class VolatilityManagedMomentumStrategy:
    """Generate momentum signals gated by realized-volatility regime."""

    def __init__(
        self,
        ema_fast: int = 48,
        ema_slow: int = 192,
        momentum_bars: int = 192,
        vol_short_bars: int = 48,
        vol_long_bars: int = 384,
        max_vol_ratio: float = 0.80,
        min_momentum_pct: float = 0.012,
        min_body_ratio: float = 0.25,
        min_volume_ratio: float = 0.85,
        volume_lookback: int = 48,
        swing_lookback: int = 24,
        atr_buffer_multiple: float = 0.20,
        max_stop_pct: float = 0.012,
        reward_r: float = 2.2,
        vwap_buffer_pct: float = 0.0005,
    ) -> None:
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.momentum_bars = momentum_bars
        self.vol_short_bars = vol_short_bars
        self.vol_long_bars = vol_long_bars
        self.max_vol_ratio = max_vol_ratio
        self.min_momentum_pct = min_momentum_pct
        self.min_body_ratio = min_body_ratio
        self.min_volume_ratio = min_volume_ratio
        self.volume_lookback = volume_lookback
        self.swing_lookback = swing_lookback
        self.atr_buffer_multiple = atr_buffer_multiple
        self.max_stop_pct = max_stop_pct
        self.reward_r = reward_r
        self.vwap_buffer_pct = vwap_buffer_pct

    def generate(
        self,
        ctx: Any,
        symbol: str,
        htf_bias: str = "NEUTRAL",
        **_: Any,
    ) -> Optional[TradingSignal]:
        min_candles = max(
            self.ema_slow + 2,
            self.momentum_bars + 2,
            self.vol_long_bars + 2,
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
        if body_ratio < self.min_body_ratio:
            return None

        closes = [float(c.close) for c in ctx.candles]
        ema_fast_value = self._ema(closes, self.ema_fast)
        ema_slow_value = self._ema(closes, self.ema_slow)
        momentum = self._pct_change(closes, self.momentum_bars)
        volume_ratio = self._volume_ratio(ctx.candles)
        if volume_ratio < self.min_volume_ratio:
            return None

        short_vol = self._realized_vol(closes, self.vol_short_bars)
        long_vol = self._realized_vol(closes, self.vol_long_bars)
        if long_vol <= 0 or short_vol > long_vol * self.max_vol_ratio:
            return None

        vwap_distance = self._vwap_distance(ctx, close)
        bias = (htf_bias or "NEUTRAL").upper()
        trend_up = (
            ema_fast_value > ema_slow_value
            and momentum >= self.min_momentum_pct
            and bias != "BEARISH"
            and vwap_distance >= -self.vwap_buffer_pct
        )
        trend_down = (
            ema_fast_value < ema_slow_value
            and momentum <= -self.min_momentum_pct
            and bias != "BULLISH"
            and vwap_distance <= self.vwap_buffer_pct
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
                momentum,
                short_vol,
                long_vol,
                volume_ratio,
                body_ratio,
                vwap_distance,
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
                momentum,
                short_vol,
                long_vol,
                volume_ratio,
                body_ratio,
                vwap_distance,
            )
        return None

    def _build_signal(
        self,
        ctx: Any,
        symbol: str,
        signal_type: SignalType,
        stop_loss: float,
        ema_fast_value: float,
        momentum: float,
        short_vol: float,
        long_vol: float,
        volume_ratio: float,
        body_ratio: float,
        vwap_distance: float,
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
                "strategy_id": VOLATILITY_MANAGED_MOMENTUM_STRATEGY_ID,
                "payoff_shape": "positive_skew",
                "ema_fast": round(ema_fast_value, 8),
                "momentum_pct": round(momentum * 100.0, 4),
                "short_realized_vol": round(short_vol, 6),
                "long_realized_vol": round(long_vol, 6),
                "vol_ratio": round(short_vol / long_vol, 4) if long_vol > 0 else 0.0,
                "risk_r": round(stop_pct, 6),
                "volume_ratio": round(volume_ratio, 4),
                "body_ratio": round(body_ratio, 4),
                "vwap_distance_pct": round(vwap_distance * 100.0, 4),
                "research_exit_profile": {
                    "profile_name": "vol_managed_momentum_2p2r",
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
            confidence=0.76,
            generated_at=ctx.current_candle.timestamp,
            price=entry,
            entry_price=entry,
            is_limit_order=False,
            stop_loss=stop_loss,
            tp_levels={"tp1": tp1, "tp2": tp2, "tp3": tp3},
            risk_reward_ratio=self.reward_r,
            reasons=[
                f"Vol-managed momentum {signal_type.value.upper()} @ {entry:.4f}",
                f"Momentum={momentum:.2%}, vol ratio={short_vol / long_vol:.2f}",
                f"Stop={stop_pct:.2%}, volume={volume_ratio:.2f}x, target={self.reward_r:.1f}R",
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

    def _vwap_distance(self, ctx: Any, entry: float) -> float:
        vwap = getattr(getattr(ctx, "vwap_result", None), "vwap", None)
        if not vwap or float(vwap) <= 0:
            return 0.0
        return (entry - float(vwap)) / float(vwap)

    @staticmethod
    def _realized_vol(values: list[float], bars: int) -> float:
        if len(values) < bars + 1:
            return 0.0
        window = values[-bars - 1 :]
        returns = []
        for previous, current in zip(window, window[1:]):
            if previous > 0:
                returns.append((current - previous) / previous)
        if len(returns) < 2:
            return 0.0
        return pstdev(returns)

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
