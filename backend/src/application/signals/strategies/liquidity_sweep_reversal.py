"""Liquidity sweep reversal strategy.

Research-only family. It fades failed stop-run candles: price must sweep a
recent swing high/low, close back inside the prior range, and show a clear wick
rejection with capped ATR risk.
"""

from __future__ import annotations

from typing import Any, Optional

from ....domain.entities.trading_signal import SignalPriority, SignalType, TradingSignal
from ..strategy_ids import LIQUIDITY_SWEEP_REVERSAL_STRATEGY_ID


class LiquiditySweepReversalStrategy:
    """Generate reversal signals after failed swing sweeps."""

    def __init__(
        self,
        lookback: int = 48,
        volume_lookback: int = 48,
        max_stop_pct: float = 0.012,
        atr_buffer_multiple: float = 0.12,
        min_sweep_atr: float = 0.10,
        min_wick_ratio: float = 0.45,
        min_close_location: float = 0.65,
        min_volume_ratio: float = 1.10,
        max_vwap_distance_pct: float = 0.012,
        max_momentum_abs_pct: float = 0.025,
        momentum_lookback: int = 96,
        reward_r: float = 1.8,
    ) -> None:
        self.lookback = lookback
        self.volume_lookback = volume_lookback
        self.max_stop_pct = max_stop_pct
        self.atr_buffer_multiple = atr_buffer_multiple
        self.min_sweep_atr = min_sweep_atr
        self.min_wick_ratio = min_wick_ratio
        self.min_close_location = min_close_location
        self.min_volume_ratio = min_volume_ratio
        self.max_vwap_distance_pct = max_vwap_distance_pct
        self.max_momentum_abs_pct = max_momentum_abs_pct
        self.momentum_lookback = momentum_lookback
        self.reward_r = reward_r

    def generate(
        self,
        ctx: Any,
        symbol: str,
        htf_bias: str = "NEUTRAL",
        **_: Any,
    ) -> Optional[TradingSignal]:
        min_candles = max(self.lookback + 2, self.volume_lookback + 2, self.momentum_lookback + 2)
        if len(ctx.candles) < min_candles:
            return None
        if not ctx.atr_result or getattr(ctx.atr_result, "atr_value", 0) <= 0:
            return None

        candle = ctx.current_candle
        entry = float(candle.close)
        if entry <= 0:
            return None

        candle_range = float(candle.high - candle.low)
        if candle_range <= 0:
            return None

        atr = float(ctx.atr_result.atr_value)
        prior = ctx.candles[-self.lookback - 1 : -1]
        swing_low = min(float(c.low) for c in prior)
        swing_high = max(float(c.high) for c in prior)
        lower_wick_ratio = float(candle.lower_shadow) / candle_range
        upper_wick_ratio = float(candle.upper_shadow) / candle_range
        close_location = self._close_location(candle)
        volume_ratio = self._volume_ratio(ctx.candles)
        momentum = self._pct_change([float(c.close) for c in ctx.candles], self.momentum_lookback)
        vwap_distance = self._vwap_distance(ctx, entry)
        bias = (htf_bias or "NEUTRAL").upper()

        if volume_ratio < self.min_volume_ratio:
            return None
        if abs(momentum) > self.max_momentum_abs_pct:
            return None
        if abs(vwap_distance) > self.max_vwap_distance_pct:
            return None

        swept_low = float(candle.low) < swing_low - atr * self.min_sweep_atr
        reclaimed_low = entry > swing_low and close_location >= self.min_close_location
        long_reversal = (
            bias != "BEARISH"
            and swept_low
            and reclaimed_low
            and lower_wick_ratio >= self.min_wick_ratio
            and candle.close > candle.open
        )

        swept_high = float(candle.high) > swing_high + atr * self.min_sweep_atr
        reclaimed_high = entry < swing_high and close_location <= (1.0 - self.min_close_location)
        short_reversal = (
            bias != "BULLISH"
            and swept_high
            and reclaimed_high
            and upper_wick_ratio >= self.min_wick_ratio
            and candle.close < candle.open
        )

        if long_reversal:
            stop = min(float(candle.low), swing_low) - atr * self.atr_buffer_multiple
            return self._build_signal(
                ctx,
                symbol,
                SignalType.BUY,
                stop,
                swing_low,
                volume_ratio,
                lower_wick_ratio,
                close_location,
                momentum,
                vwap_distance,
            )
        if short_reversal:
            stop = max(float(candle.high), swing_high) + atr * self.atr_buffer_multiple
            return self._build_signal(
                ctx,
                symbol,
                SignalType.SELL,
                stop,
                swing_high,
                volume_ratio,
                upper_wick_ratio,
                close_location,
                momentum,
                vwap_distance,
            )
        return None

    def _build_signal(
        self,
        ctx: Any,
        symbol: str,
        signal_type: SignalType,
        stop_loss: float,
        sweep_level: float,
        volume_ratio: float,
        wick_ratio: float,
        close_location: float,
        momentum: float,
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
        tp2 = entry + direction * risk * (self.reward_r + 0.8)
        tp3 = entry + direction * risk * (self.reward_r + 1.6)

        indicators = dict(getattr(ctx, "indicators", {}) or {})
        indicators.update(
            {
                "strategy_id": LIQUIDITY_SWEEP_REVERSAL_STRATEGY_ID,
                "payoff_shape": "positive_skew",
                "sweep_level": round(sweep_level, 8),
                "risk_r": round(stop_pct, 6),
                "volume_ratio": round(volume_ratio, 4),
                "wick_ratio": round(wick_ratio, 4),
                "close_location": round(close_location, 4),
                "momentum_pct": round(momentum * 100.0, 4),
                "vwap_distance_pct": round(vwap_distance * 100.0, 4),
                "research_exit_profile": {
                    "profile_name": "liquidity_sweep_reversal_1p8r",
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
                f"Liquidity sweep reversal {signal_type.value.upper()} @ {entry:.4f}",
                f"Sweep={sweep_level:.4f}, stop={stop_pct:.2%}, wick={wick_ratio:.2f}",
                f"Volume={volume_ratio:.2f}x, VWAP distance={vwap_distance:.2%}",
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
    def _pct_change(values: list[float], lookback: int) -> float:
        past = values[-lookback - 1]
        if past <= 0:
            return 0.0
        return (values[-1] - past) / past

    @staticmethod
    def _close_location(candle: Any) -> float:
        high = float(candle.high)
        low = float(candle.low)
        if high <= low:
            return 0.5
        return (float(candle.close) - low) / (high - low)
