"""Trend-continuation reclaim strategy.

This strategy is intentionally research-only until backtests prove it. It looks
for a liquidity sweep that quickly reclaims the prior swing level, then targets
a larger reward multiple with a capped stop.
"""

from __future__ import annotations

from typing import Any, Optional

from ....domain.entities.trading_signal import SignalPriority, SignalType, TradingSignal
from ..strategy_ids import TREND_RUNNER_STRATEGY_ID


class TrendContinuationStrategy:
    """Generate positive-skew continuation signals after sweep/reclaim candles."""

    def __init__(
        self,
        lookback: int = 20,
        max_stop_pct: float = 0.012,
        atr_buffer_multiple: float = 0.10,
        min_body_to_range: float = 0.35,
        reward_r: float = 3.0,
    ):
        self.lookback = lookback
        self.max_stop_pct = max_stop_pct
        self.atr_buffer_multiple = atr_buffer_multiple
        self.min_body_to_range = min_body_to_range
        self.reward_r = reward_r

    def generate(
        self,
        ctx: Any,
        symbol: str,
        htf_bias: str = "NEUTRAL",
        **_: Any,
    ) -> Optional[TradingSignal]:
        if len(ctx.candles) < max(60, self.lookback + 2):
            return None
        if not ctx.atr_result or getattr(ctx.atr_result, "atr_value", 0) <= 0:
            return None

        candle = ctx.current_candle
        candle_range = candle.high - candle.low
        if candle_range <= 0:
            return None

        body_ratio = abs(candle.close - candle.open) / candle_range
        if body_ratio < self.min_body_to_range:
            return None

        prior = ctx.candles[-self.lookback - 1 : -1]
        swing_low = min(c.low for c in prior)
        swing_high = max(c.high for c in prior)
        atr = float(ctx.atr_result.atr_value)
        trend = self._resolve_trend(ctx.candles, htf_bias)

        long_reclaim = (
            trend == "BULLISH"
            and candle.low < swing_low
            and candle.close > swing_low
            and candle.close > candle.open
        )
        short_reclaim = (
            trend == "BEARISH"
            and candle.high > swing_high
            and candle.close < swing_high
            and candle.close < candle.open
        )

        if long_reclaim:
            return self._build_signal(
                ctx=ctx,
                symbol=symbol,
                signal_type=SignalType.BUY,
                sweep_level=swing_low,
                stop_loss=min(candle.low, swing_low) - atr * self.atr_buffer_multiple,
                trend=trend,
                atr=atr,
            )

        if short_reclaim:
            return self._build_signal(
                ctx=ctx,
                symbol=symbol,
                signal_type=SignalType.SELL,
                sweep_level=swing_high,
                stop_loss=max(candle.high, swing_high) + atr * self.atr_buffer_multiple,
                trend=trend,
                atr=atr,
            )

        return None

    def _build_signal(
        self,
        ctx: Any,
        symbol: str,
        signal_type: SignalType,
        sweep_level: float,
        stop_loss: float,
        trend: str,
        atr: float,
    ) -> Optional[TradingSignal]:
        entry = float(ctx.current_candle.close)
        risk = abs(entry - stop_loss)
        if risk <= 0:
            return None
        if risk / entry > self.max_stop_pct:
            return None

        is_long = signal_type == SignalType.BUY
        direction = 1 if is_long else -1
        tp1 = entry + direction * risk * self.reward_r
        tp2 = entry + direction * risk * (self.reward_r + 1.0)
        tp3 = entry + direction * risk * (self.reward_r + 2.0)

        indicators = dict(getattr(ctx, "indicators", {}) or {})
        indicators.update(
            {
                "strategy_id": TREND_RUNNER_STRATEGY_ID,
                "payoff_shape": "positive_skew",
                "sweep_level": round(sweep_level, 8),
                "atr": round(atr, 8),
                "risk_r": round(risk / entry, 6),
                "research_exit_profile": {
                    "profile_name": "trend_runner_3r",
                    "close_profitable_auto": False,
                    "profitable_threshold_pct": 20.0,
                    "trailing_stop_atr": 3.0,
                    "partial_close_ac": False,
                },
            }
        )

        return TradingSignal(
            symbol=symbol,
            signal_type=signal_type,
            priority=SignalPriority.HIGH,
            confidence=0.78,
            generated_at=ctx.current_candle.timestamp,
            price=ctx.current_price,
            entry_price=entry,
            is_limit_order=False,
            stop_loss=stop_loss,
            tp_levels={"tp1": tp1, "tp2": tp2, "tp3": tp3},
            risk_reward_ratio=self.reward_r,
            reasons=[
                f"Trend reclaim {signal_type.value.upper()} @ {entry:.4f}",
                f"Swept {sweep_level:.4f}, stop capped at {risk / entry:.2%}",
                f"Trend={trend}, target={self.reward_r:.1f}R",
            ],
            indicators=indicators,
        )

    @staticmethod
    def _resolve_trend(candles: list[Any], htf_bias: str) -> str:
        bias = (htf_bias or "NEUTRAL").upper()
        if bias in {"BULLISH", "BEARISH"}:
            return bias

        closes = [float(c.close) for c in candles]
        if len(closes) < 50:
            return "NEUTRAL"
        ema_fast = TrendContinuationStrategy._ema(closes, 20)
        ema_slow = TrendContinuationStrategy._ema(closes, 50)
        if ema_fast > ema_slow:
            return "BULLISH"
        if ema_fast < ema_slow:
            return "BEARISH"
        return "NEUTRAL"

    @staticmethod
    def _ema(values: list[float], period: int) -> float:
        multiplier = 2 / (period + 1)
        ema = sum(values[:period]) / period
        for value in values[period:]:
            ema = (value * multiplier) + (ema * (1 - multiplier))
        return ema
