"""
SignalGenerator - Application Layer

Generates trading signals using Liquidity Sniper strategy (Limit Orders).
SOTA Logic: Front-running liquidity sweeps at Swing Points.
SOTA (Feb 2026): SHORT trading ENABLED - All 3 layers of defense disabled
"""

import logging
import os
from datetime import datetime
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field

from ...domain.entities.candle import Candle
from ...domain.entities.trading_signal import TradingSignal, SignalType, SignalPriority
from ...domain.interfaces import (
    IVWAPCalculator,
    IBollingerCalculator,
    IStochRSICalculator,
    ISFPDetector,
    SFPType,
    IATRCalculator
)
from ..services.tp_calculator import TPCalculator
from ..services.stop_loss_calculator import StopLossCalculator
from ...strategies.strategy_registry import StrategyRegistry, StrategyConfig


@dataclass
class MarketContext:
    candles: List[Candle]
    current_candle: Candle
    current_price: float
    vwap_result: Optional[Any] = None
    bb_result: Optional[Any] = None
    stoch_result: Optional[Any] = None
    atr_result: Optional[Any] = None
    sfp_result: Optional[Any] = None
    indicators: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return True


class SignalGenerator:
    def __init__(
        self,
        vwap_calculator: IVWAPCalculator,
        bollinger_calculator: IBollingerCalculator,
        stoch_rsi_calculator: IStochRSICalculator,
        sfp_detector: Optional[ISFPDetector] = None,
        atr_calculator: Optional[IATRCalculator] = None,
        volume_profile_calculator: Optional[Any] = None,
        tp_calculator: Optional[TPCalculator] = None,
        stop_loss_calculator: Optional[StopLossCalculator] = None,
        account_size: float = 100.0,
        use_btc_filter: bool = False,  # SOTA (Jan 2026): BTC Trend Filter
        use_adx_regime_filter: bool = False,  # INSTITUTIONAL (Feb 2026): ADX Regime Filter
        use_htf_filter: bool = False,  # EXPERIMENTAL: HTF trend alignment filter
        use_adx_max_filter: bool = False,  # Block when ADX > threshold (trending too strong for mean-reversion)
        adx_max_threshold: float = 40.0,  # ADX threshold for max filter
        use_bb_filter: bool = False,  # Bollinger Bands proximity filter
        use_stochrsi_filter: bool = False,  # StochRSI oversold/overbought filter
        sniper_lookback: int = 20,  # Swing point lookback period
        sniper_proximity: float = 0.015,  # Proximity threshold (1.5% = 0.015)
        # SOTA (Feb 2026): Signal quality improvement flags (backtest only, default OFF)
        fix_vwap_scoring: bool = False,  # Fix inverted VWAP scoring
        use_volume_confirm: bool = False,  # Z-score >= 1.0 volume confirmation
        use_bounce_confirm: bool = False,  # Pin bar / rejection candle confirmation
        use_ema_regime_filter: bool = False,  # EMA 9/21 counter-trend block
        use_atr_sl: bool = False,  # ATR-based stop loss (2x ATR, capped 0.5-2.0%)
        use_funding_filter: bool = False,  # Block overcrowded funding directions
        # Phase 1 Strategy Filters (Feb 2026)
        use_delta_divergence: bool = False,  # Volume Delta Divergence filter
        use_mtf_trend: bool = False,  # MTF Trend filter (faster EMA on 4H)
        mtf_ema_period: int = 50,  # MTF trend EMA period on 4H (50 = ~8 days)
        **kwargs
    ):
        self.vwap_calculator = vwap_calculator
        self.bollinger_calculator = bollinger_calculator
        self.stoch_rsi_calculator = stoch_rsi_calculator
        self.sfp_detector = sfp_detector
        self.atr_calculator = atr_calculator
        self.volume_profile_calculator = volume_profile_calculator
        self.tp_calculator = tp_calculator or TPCalculator()
        self.stop_loss_calculator = stop_loss_calculator or StopLossCalculator()

        self.account_size = account_size
        self.logger = logging.getLogger(__name__)

        # INSTITUTIONAL (Feb 2026): ADX Regime Filter
        # ADX > 25 = trending → trade normally
        # ADX 20-25 = weak trend → penalize confidence (-15%)
        # ADX < 20 = choppy → SKIP entry (avoid whipsaw losses)
        self.use_adx_regime_filter = use_adx_regime_filter
        self._blocked_by_adx_filter = 0
        self._penalized_by_adx_filter = 0

        # EXPERIMENTAL: HTF trend alignment filter
        self.use_htf_filter = use_htf_filter
        self._blocked_by_htf_filter = 0

        if self.use_htf_filter:
            self.logger.info("📊 HTF FILTER: Enabled - Block counter-trend signals (LONG vs BEARISH, SHORT vs BULLISH)")

        if self.use_adx_regime_filter:
            self.logger.info("📊 ADX REGIME FILTER: Enabled - ADX<20=block, 20-25=penalty")

        # Mean-reversion indicator filters
        self.use_adx_max_filter = use_adx_max_filter
        self.adx_max_threshold = adx_max_threshold
        self._blocked_by_adx_max = 0
        self.use_bb_filter = use_bb_filter
        self._blocked_by_bb = 0
        self.use_stochrsi_filter = use_stochrsi_filter
        self._blocked_by_stochrsi = 0

        if self.use_adx_max_filter:
            self.logger.info(f"📊 ADX MAX FILTER: Enabled - Block when ADX > {self.adx_max_threshold}")
        if self.use_bb_filter:
            self.logger.info("📊 BB FILTER: Enabled - BUY only near lower band, SELL only near upper band")
        if self.use_stochrsi_filter:
            self.logger.info("📊 STOCHRSI FILTER: Enabled - BUY when oversold, SELL when overbought")

        # Entry parameters (tunable)
        self.sniper_lookback = sniper_lookback
        self.sniper_proximity = sniper_proximity
        if sniper_lookback != 20 or sniper_proximity != 0.015:
            self.logger.info(f"📊 SNIPER PARAMS: lookback={sniper_lookback}, proximity={sniper_proximity*100:.1f}%")

        # SOTA (Feb 2026): Signal quality improvement flags
        self.fix_vwap_scoring = fix_vwap_scoring
        self.use_volume_confirm = use_volume_confirm
        self.use_bounce_confirm = use_bounce_confirm
        self.use_ema_regime_filter = use_ema_regime_filter
        self.use_atr_sl = use_atr_sl
        self.use_funding_filter = use_funding_filter
        self._blocked_by_volume_confirm = 0
        self._blocked_by_bounce_confirm = 0
        self._blocked_by_ema_regime_filter = 0
        self._blocked_by_funding_filter = 0

        if fix_vwap_scoring:
            self.logger.info("📊 FIX VWAP: Enabled - reward CLOSENESS to VWAP (not distance)")
        if use_volume_confirm:
            self.logger.info("📊 VOLUME CONFIRM: Enabled - require Z-score >= 1.0")
        if use_bounce_confirm:
            self.logger.info("📊 BOUNCE CONFIRM: Enabled - require pin bar / rejection candle")
        if use_ema_regime_filter:
            self.logger.info("📊 REGIME FILTER: Enabled - block counter-trend via EMA 9/21")
        if use_atr_sl:
            self.logger.info("📊 ATR SL: Enabled - 2.0x ATR stop loss (capped 0.5-2.0%)")
        if use_funding_filter:
            self.logger.info("📊 FUNDING FILTER: Enabled - block overcrowded directions (>0.05%)")

        # Phase 1 Strategy Filters (Feb 2026)
        self.use_delta_divergence = use_delta_divergence
        self._blocked_by_delta_divergence = 0
        self._delta_calculator = None
        if use_delta_divergence:
            from ...infrastructure.indicators.volume_delta_calculator import VolumeDeltaCalculator
            self._delta_calculator = VolumeDeltaCalculator(divergence_lookback=14)
            self.logger.info("📊 DELTA DIVERGENCE: Enabled - block signals contradicted by volume delta")

        self.use_mtf_trend = use_mtf_trend
        self.mtf_ema_period = mtf_ema_period
        self._blocked_by_mtf_trend = 0
        if use_mtf_trend:
            self.logger.info(f"📊 MTF TREND: Enabled - EMA({mtf_ema_period}) on 4H, block counter-trend")

        # SOTA (Feb 2026): SHORT trading ENABLED - no filtering
        self._env = os.getenv("ENV", "paper").lower()
        self._is_live_mode = (self._env == "live")
        self._blocked_short_signals = 0

        if self._is_live_mode:
            self.logger.info("✅ LIVE MODE: SHORT trading ENABLED (all 3 layers disabled)")

        # SOTA (Jan 2026): BTC Trend Filter (Institutional Approach)
        # Based on research: Renaissance Technologies, Two Sigma, Citadel
        # Logic: Filter altcoin signals based on BTC trend (EMA 50/200 crossover)
        self.use_btc_filter = use_btc_filter
        self._btc_candles = []  # Cache for BTC candles
        self._blocked_by_btc_filter = 0  # Counter for blocked signals

        if self.use_btc_filter:
            self.logger.info("📊 BTC FILTER: Enabled - Altcoins will follow BTC trend (EMA 50/200)")

    def _prepare_market_context(self, candles: List[Candle]) -> MarketContext:
        current_candle = candles[-1]
        ctx = MarketContext(candles=candles, current_candle=current_candle, current_price=current_candle.close)

        ctx.vwap_result = self.vwap_calculator.calculate_vwap(candles)
        ctx.stoch_result = self.stoch_rsi_calculator.calculate_stoch_rsi(candles)
        ctx.bb_result = self.bollinger_calculator.calculate_bands(candles, ctx.current_price)

        if self.atr_calculator:
            ctx.atr_result = self.atr_calculator.calculate_atr(candles)

        ctx.indicators = {
            'atr': ctx.atr_result.atr_value if ctx.atr_result else 0
        }

        # INSTITUTIONAL (Feb 2026): Calculate 20-period ATR average for vol-sizing & dynamic TP
        if ctx.atr_result and ctx.atr_result.atr_value > 0 and len(candles) >= 34:
            # Efficient: use True Range series and rolling avg instead of recalculating ADX N times
            # SOTA FIX: Slice array to prevent O(N^2) bottleneck
            true_ranges = self.atr_calculator._calculate_true_ranges(candles[-21:])
            if len(true_ranges) >= 20:
                # ATR is a smoothed average of TR. We approximate ATR_avg_20 as
                # the average of the last 20 ATR values by computing ATR at different endpoints
                # Simplified: use average of last 20 true ranges as proxy
                recent_trs = true_ranges[-20:]
                ctx.indicators['atr_avg_20'] = sum(recent_trs) / len(recent_trs)

        return ctx

    def _build_tp_levels(self, signal_type: SignalType, tp1: float) -> Dict[str, float]:
        """Build monotonic TP ladders for both long and short signals."""
        if signal_type == SignalType.SELL:
            return {'tp1': tp1, 'tp2': tp1 * 0.95, 'tp3': tp1 * 0.90}
        return {'tp1': tp1, 'tp2': tp1 * 1.05, 'tp3': tp1 * 1.10}

    def _normalize_funding_rate(self, funding_rate: Any) -> float:
        """
        Normalize funding to Binance raw decimal format.

        Binance APIs return raw decimals (0.0001 = 0.01%), while internal
        intelligence caches may store percent values (0.01 = 0.01%).
        """
        try:
            rate = float(funding_rate)
        except (TypeError, ValueError):
            return 0.0

        if abs(rate) > 0.01:
            rate /= 100.0
        return rate

    def generate_signal(self, candles: List[Candle], symbol: str, htf_bias: str = 'NEUTRAL', **kwargs) -> Optional[TradingSignal]:
        if len(candles) < 50: return None
        config = StrategyRegistry.get_config(symbol)
        ctx = self._prepare_market_context(candles)

        # Use Limit Sniper Logic
        return self._strategy_liquidity_sniper(ctx, config, symbol, htf_bias, **kwargs)

    def _strategy_liquidity_sniper(self, ctx: MarketContext, config: StrategyConfig, symbol: str, htf_bias: str, **kwargs) -> Optional[TradingSignal]:
        if not ctx.atr_result: return None

        # 1. Find recent Swing High/Low
        lookback = self.sniper_lookback
        # SOTA FIX (Jan 2026): Include current candle in swing calculation
        # This matches LIVE behavior where signal is generated AFTER candle close
        recent_candles = ctx.candles[-lookback:]  # Include current candle
        swing_low = min([c.low for c in recent_candles])
        swing_high = max([c.high for c in recent_candles])

        # 2. Check Proximity
        current_price = ctx.current_price
        dist_to_low = (current_price - swing_low) / swing_low
        dist_to_high = (swing_high - current_price) / swing_high

        signal_type = None
        limit_price = 0.0
        stop_loss = 0.0
        tp1 = 0.0

        # SOTA FIX (Jan 2026): Check BOTH conditions independently
        # Then pick the one with SMALLER distance (closer to swing point)
        buy_valid = 0 < dist_to_low < self.sniper_proximity
        sell_valid = 0 < dist_to_high < self.sniper_proximity

        # DEBUG: Log signal decision
        if buy_valid or sell_valid:
            self.logger.debug(
                f"🎯 {symbol}: price={current_price:.2f}, "
                f"swing_low={swing_low:.2f} (dist={dist_to_low*100:.2f}%), "
                f"swing_high={swing_high:.2f} (dist={dist_to_high*100:.2f}%), "
                f"buy_valid={buy_valid}, sell_valid={sell_valid}"
            )

        # SOTA STRATEGY (Feb 2026): Fixed 1.0% SL
        # User Preference: Predictable risk (~11% ROE at 10x).
        # This provides a reasonable buffer for Alts without the complexity of ATR.

        # SOTA STRATEGY (Feb 2026): Fixed 1.0% SL
        # User Preference: Predictable risk (~11% ROE at 10x).

        # Consistent TP calculation (Risk:Reward 2:1 based on SL distance)
        # Strategy says "TP1 = 60%, Trailing = 40%".

        if buy_valid and sell_valid:
            # Both conditions true - pick the one CLOSER to its swing point
            if dist_to_low <= dist_to_high:
                # Closer to swing low → BUY
                limit_price = swing_low * 0.999
                signal_type = SignalType.BUY
                stop_loss = limit_price * 0.99  # Fixed 1% SL
                tp1 = limit_price * 1.02
                self.logger.debug(f"  → BUY (closer to swing low) | SL 1%")
            else:
                # Closer to swing high → SELL
                limit_price = swing_high * 1.001
                signal_type = SignalType.SELL
                stop_loss = limit_price * 1.01  # Fixed 1% SL
                tp1 = limit_price * 0.98
                self.logger.debug(f"  → SELL (closer to swing high) | SL 1%")
        elif buy_valid:
            # Only BUY condition true
            limit_price = swing_low * 0.999
            signal_type = SignalType.BUY
            stop_loss = limit_price * 0.99  # Fixed 1% SL
            tp1 = limit_price * 1.02
        elif sell_valid:
            # Only SELL condition true
            limit_price = swing_high * 1.001
            signal_type = SignalType.SELL
            stop_loss = limit_price * 1.01  # Fixed 1% SL
            tp1 = limit_price * 0.98

        # SOTA: ATR-based Stop Loss (replaces fixed 1% when enabled)
        if signal_type and self.use_atr_sl and ctx.atr_result and ctx.atr_result.atr_value > 0:
            atr_val = ctx.atr_result.atr_value
            sl_distance = atr_val * 2.0  # 2x ATR — industry standard for crypto
            sl_pct = sl_distance / limit_price
            sl_pct = max(0.005, min(0.02, sl_pct))  # Cap: 0.5% min, 2.0% max

            if signal_type == SignalType.BUY:
                stop_loss = limit_price * (1 - sl_pct)
            else:
                stop_loss = limit_price * (1 + sl_pct)

        if not signal_type: return None

        # SOTA: Volume confirmation — require Z-score >= 1.0 (84th percentile)
        if self.use_volume_confirm:
            volumes = [c.volume for c in ctx.candles[-20:]]
            if len(volumes) >= 20:
                mean_vol = sum(volumes) / len(volumes)
                std_vol = (sum((v - mean_vol) ** 2 for v in volumes) / len(volumes)) ** 0.5
                if std_vol > 0:
                    vol_z = (ctx.current_candle.volume - mean_vol) / std_vol
                else:
                    vol_z = 0
                if vol_z < 1.0:
                    self._blocked_by_volume_confirm += 1
                    return None
                ctx.indicators['volume_z_score'] = round(vol_z, 2)

        # SOTA: Bounce confirmation — require pin bar / rejection candle
        if self.use_bounce_confirm:
            c = ctx.current_candle
            body = abs(c.close - c.open)
            total_range = c.high - c.low
            if total_range > 0 and body / total_range <= 0.4:
                if signal_type == SignalType.BUY:
                    lower_wick = min(c.open, c.close) - c.low
                    if lower_wick / total_range < 0.5:
                        self._blocked_by_bounce_confirm += 1
                        return None
                else:  # SELL
                    upper_wick = c.high - max(c.open, c.close)
                    if upper_wick / total_range < 0.5:
                        self._blocked_by_bounce_confirm += 1
                        return None
            else:
                self._blocked_by_bounce_confirm += 1
                return None

        # EXPERIMENTAL: HTF Bias Filter (re-enabled via --htf-filter flag)
        if self.use_htf_filter:
            if signal_type == SignalType.BUY and htf_bias == 'BEARISH':
                self._blocked_by_htf_filter += 1
                return None
            if signal_type == SignalType.SELL and htf_bias == 'BULLISH':
                self._blocked_by_htf_filter += 1
                return None

        # SOTA (Jan 2026): BTC Trend Filter (Institutional Approach)
        # Filter altcoin signals based on BTC trend
        # Logic: Don't fight the market leader (BTC)
        if self.use_btc_filter and symbol != 'BTCUSDT':
            btc_trend = self.get_btc_trend()

            # Block LONG signals when BTC is bearish
            if signal_type == SignalType.BUY and btc_trend == 'BEARISH':
                self._blocked_by_btc_filter += 1
                self.logger.debug(
                    f"🚫 BTC FILTER: Blocked LONG signal for {symbol} "
                    f"(BTC trend: {btc_trend}, price near swing low)"
                )
                return None

            # Block SHORT signals when BTC is bullish
            if signal_type == SignalType.SELL and btc_trend == 'BULLISH':
                self._blocked_by_btc_filter += 1
                self.logger.debug(
                    f"🚫 BTC FILTER: Blocked SHORT signal for {symbol} "
                    f"(BTC trend: {btc_trend}, price near swing high)"
                )
                return None

            # Log allowed signals
            self.logger.debug(
                f"✅ BTC FILTER: Allowed {signal_type.value.upper()} signal for {symbol} "
                f"(BTC trend: {btc_trend})"
            )

        # SOTA: EMA regime filter — block counter-trend mean-reversion
        if self.use_ema_regime_filter:
            closes = [c.close for c in ctx.candles[-25:]]
            if len(closes) >= 21:
                ema9 = self._calculate_ema_value(closes, 9)
                ema21 = self._calculate_ema_value(closes, 21)
                if signal_type == SignalType.BUY and ema9 < ema21:
                    self._blocked_by_ema_regime_filter += 1
                    return None
                if signal_type == SignalType.SELL and ema9 > ema21:
                    self._blocked_by_ema_regime_filter += 1
                    return None

        # SOTA: Funding rate filter — block overcrowded directions
        if self.use_funding_filter:
            funding_rate = self._normalize_funding_rate(kwargs.get('funding_rate', 0))
            if funding_rate != 0:
                # High positive funding → longs overcrowded → block BUY
                if funding_rate > 0.0005 and signal_type == SignalType.BUY:
                    self._blocked_by_funding_filter += 1
                    return None
                # High negative funding → shorts overcrowded → block SELL
                if funding_rate < -0.0005 and signal_type == SignalType.SELL:
                    self._blocked_by_funding_filter += 1
                    return None

        # Phase 1: Volume Delta Divergence Filter (Feb 2026)
        # Block signals where volume delta contradicts the trade direction
        # BUY near swing low: delta should be rising (accumulation) or bullish divergence
        # SELL near swing high: delta should be falling (distribution) or bearish divergence
        if self.use_delta_divergence and self._delta_calculator and len(ctx.candles) >= 20:
            try:
                cum_result = self._delta_calculator.calculate_cumulative(ctx.candles[-30:])
                delta_trend = cum_result.delta_trend  # "rising", "falling", "neutral"
                has_bull_div = cum_result.has_bullish_divergence
                has_bear_div = cum_result.has_bearish_divergence

                if signal_type == SignalType.BUY:
                    # BUY requires: rising delta OR bullish divergence (accumulation)
                    # Block if: falling delta AND no bullish divergence (selling pressure)
                    if delta_trend == "falling" and not has_bull_div:
                        self._blocked_by_delta_divergence += 1
                        return None
                elif signal_type == SignalType.SELL:
                    # SELL requires: falling delta OR bearish divergence (distribution)
                    # Block if: rising delta AND no bearish divergence (buying pressure)
                    if delta_trend == "rising" and not has_bear_div:
                        self._blocked_by_delta_divergence += 1
                        return None
            finally:
                reset = getattr(self._delta_calculator, "reset", None)
                if callable(reset):
                    reset()
                else:
                    history = getattr(self._delta_calculator, "_delta_history", None)
                    if isinstance(history, list):
                        history.clear()

        # Phase 1: MTF Trend Filter (Feb 2026)
        # Uses faster EMA (default 50) on 4H instead of EMA200
        # Only allows trades in direction of 4H trend
        if self.use_mtf_trend and htf_bias != 'NEUTRAL':
            if signal_type == SignalType.BUY and htf_bias == 'BEARISH':
                self._blocked_by_mtf_trend += 1
                return None
            if signal_type == SignalType.SELL and htf_bias == 'BULLISH':
                self._blocked_by_mtf_trend += 1
                return None

        # 3. Calculate Score (for Shark Tank)
        # Higher score if closer to VWAP stretch or other confluence
        score = 0.7 # Base
        if ctx.vwap_result:
            vwap_dist = abs(current_price - ctx.vwap_result.vwap) / ctx.vwap_result.vwap
            if self.fix_vwap_scoring:
                # SOTA: Mean-reversion works best NEAR VWAP (institutional consensus)
                score += max(0, 0.2 - vwap_dist * 20)  # CLOSE to VWAP = higher score
            else:
                score += min(0.2, vwap_dist * 10)  # Legacy: FAR from VWAP = higher score

        # Always compute volume ratio for analytics/filtering
        volumes = [c.volume for c in ctx.candles[-20:]]
        avg_vol = sum(volumes) / len(volumes) if volumes else 1.0
        ctx.indicators['volume_ratio'] = round(ctx.current_candle.volume / avg_vol, 2) if avg_vol > 0 else 0.0

        signal = TradingSignal(
            symbol=symbol,
            signal_type=signal_type,
            confidence=score,
            generated_at=ctx.current_candle.timestamp,
            price=ctx.current_price,
            entry_price=limit_price,
            is_limit_order=True,
            stop_loss=stop_loss,
            tp_levels=self._build_tp_levels(signal_type, tp1),
            risk_reward_ratio=(abs(tp1 - limit_price) / abs(limit_price - stop_loss)),
            reasons=[f"Sniper Limit @ {limit_price:.2f}"],
            indicators=ctx.indicators
        )

        # INSTITUTIONAL (Feb 2026): ADX Regime Filter
        # Filter signals based on ADX trend strength to avoid whipsaw in choppy markets
        if self.use_adx_regime_filter:
            # Use the ADX calculator already injected via DI or create one
            adx_calc = getattr(self, 'adx_calculator', None)
            if adx_calc is None:
                adx_calc = getattr(self, '_adx_calc_instance', None)
            if adx_calc is None:
                from ...infrastructure.indicators.adx_calculator import ADXCalculator
                adx_calc = ADXCalculator(period=14)
                self._adx_calc_instance = adx_calc

            adx_result = adx_calc.calculate_adx(ctx.candles)
            signal.indicators['adx_value'] = adx_result.adx_value
            signal.indicators['adx_regime'] = adx_result.trend_strength

            if adx_result.adx_value < 20:
                # Choppy market → block signal
                self._blocked_by_adx_filter += 1
                self.logger.debug(
                    f"🚫 ADX FILTER: Blocked {signal.signal_type.value} for {symbol} "
                    f"(ADX={adx_result.adx_value:.1f} < 20, regime=CHOPPY)"
                )
                return None
            elif adx_result.adx_value < 25:
                # Weak trend → penalize confidence
                old_conf = signal.confidence
                signal.confidence *= 0.85
                self._penalized_by_adx_filter += 1
                self.logger.debug(
                    f"⚠️ ADX FILTER: Penalized {symbol} confidence "
                    f"{old_conf:.2f} → {signal.confidence:.2f} "
                    f"(ADX={adx_result.adx_value:.1f}, regime=WEAK)"
                )

        # Mean-reversion indicator filters (Feb 2026)
        # ADX Max Filter: Block when trending too strongly (breakouts destroy swing trades)
        if self.use_adx_max_filter:
            adx_calc = getattr(self, 'adx_calculator', None)
            if adx_calc is None:
                adx_calc = getattr(self, '_adx_calc_instance', None)
            if adx_calc is None:
                from ...infrastructure.indicators.adx_calculator import ADXCalculator
                adx_calc = ADXCalculator(period=14)
                self._adx_calc_instance = adx_calc
            adx_result = adx_calc.calculate_adx(ctx.candles)
            signal.indicators['adx_value'] = adx_result.adx_value
            if adx_result.adx_value > self.adx_max_threshold:
                self._blocked_by_adx_max += 1
                self.logger.debug(
                    f"🚫 ADX MAX: Blocked {signal.signal_type.value} for {symbol} "
                    f"(ADX={adx_result.adx_value:.1f} > {self.adx_max_threshold})"
                )
                return None

        # Bollinger Bands Filter: Only trade near bands (mean-reversion confirmation)
        if self.use_bb_filter and ctx.bb_result:
            pct_b = ctx.bb_result.percent_b
            signal.indicators['bb_pct_b'] = round(pct_b, 3)
            if signal.signal_type == SignalType.BUY and pct_b > 0.3:
                self._blocked_by_bb += 1
                self.logger.debug(
                    f"🚫 BB FILTER: Blocked BUY for {symbol} (%B={pct_b:.2f} > 0.3, not near lower band)"
                )
                return None
            if signal.signal_type == SignalType.SELL and pct_b < 0.7:
                self._blocked_by_bb += 1
                self.logger.debug(
                    f"🚫 BB FILTER: Blocked SELL for {symbol} (%B={pct_b:.2f} < 0.7, not near upper band)"
                )
                return None

        # StochRSI Filter: Only trade when momentum confirms (oversold for BUY, overbought for SELL)
        if self.use_stochrsi_filter and ctx.stoch_result:
            k_value = ctx.stoch_result.k_value
            signal.indicators['stochrsi_k'] = round(k_value, 1)
            if signal.signal_type == SignalType.BUY and k_value > 30:
                self._blocked_by_stochrsi += 1
                self.logger.debug(
                    f"🚫 STOCHRSI: Blocked BUY for {symbol} (K={k_value:.1f} > 30, not oversold)"
                )
                return None
            if signal.signal_type == SignalType.SELL and k_value < 70:
                self._blocked_by_stochrsi += 1
                self.logger.debug(
                    f"🚫 STOCHRSI: Blocked SELL for {symbol} (K={k_value:.1f} < 70, not overbought)"
                )
                return None

        # SOTA (Feb 2026): SHORT trading ENABLED - All 3 layers disabled
        # SHORT signals now execute normally just like LONG signals
        if self._is_live_mode and signal.signal_type == SignalType.SELL:
            self.logger.debug(
                f"✅ LIVE MODE: SHORT signal PASSED for {symbol} "
                f"(confidence={signal.confidence:.2f}, SHORT trading ENABLED)"
            )
            # Do NOT return None - SHORT signals execute normally

        return signal

    def get_blocked_short_count(self) -> int:
        """Get number of blocked SHORT signals this session (Layer 1)."""
        return self._blocked_short_signals

    # SOTA (Jan 2026): BTC Trend Filter Methods
    # Based on institutional research: Renaissance, Two Sigma, Citadel

    def set_btc_candles(self, candles: List[Candle]):
        """Set BTC candles for trend calculation.

        Args:
            candles: List of BTC candles (BTCUSDT)
        """
        self._btc_candles = candles
        if self.use_btc_filter:
            btc_trend = self.get_btc_trend()
            self.logger.info(f"📊 BTC FILTER: Loaded {len(candles)} BTC candles, current trend: {btc_trend}")

    def get_btc_trend(self) -> str:
        """Calculate BTC trend using EMA 50/200 crossover.

        Returns:
            'BULLISH': Golden Cross (EMA 50 > EMA 200 + 1% buffer)
            'BEARISH': Death Cross (EMA 50 < EMA 200 - 1% buffer)
            'NEUTRAL': No clear trend or insufficient data

        Logic:
            - Golden Cross: EMA 50 > EMA 200 * 1.01 → BULLISH
            - Death Cross: EMA 50 < EMA 200 * 0.99 → BEARISH
            - 1% buffer reduces whipsaw in sideways markets
        """
        if len(self._btc_candles) < 200:
            return 'NEUTRAL'

        # Extract close prices
        closes = [c.close for c in self._btc_candles]

        # Calculate EMA 50 and EMA 200
        ema_50 = self._calculate_ema_value(closes, 50)
        ema_200 = self._calculate_ema_value(closes, 200)

        # Golden Cross / Death Cross with 1% buffer
        if ema_50 > ema_200 * 1.01:
            return 'BULLISH'
        elif ema_50 < ema_200 * 0.99:
            return 'BEARISH'
        else:
            return 'NEUTRAL'

    def _calculate_ema_value(self, values: List[float], period: int) -> float:
        """Calculate EMA value (helper method).

        Args:
            values: List of price values
            period: EMA period (e.g., 50, 200)

        Returns:
            EMA value

        Formula:
            EMA = (Close - EMA_prev) * Multiplier + EMA_prev
            Multiplier = 2 / (Period + 1)
        """
        if len(values) < period:
            # Not enough data, return simple average
            return sum(values) / len(values)

        # Calculate multiplier
        multiplier = 2 / (period + 1)

        # Initialize EMA with SMA of first 'period' values
        ema = sum(values[:period]) / period

        # Calculate EMA for remaining values
        for value in values[period:]:
            ema = (value - ema) * multiplier + ema

        return ema

    def get_blocked_by_btc_filter_count(self) -> int:
        """Get number of signals blocked by BTC filter this session."""
        return self._blocked_by_btc_filter

    def get_blocked_by_adx_filter_count(self) -> int:
        """Get number of signals blocked by ADX regime filter this session."""
        return self._blocked_by_adx_filter

    def get_penalized_by_adx_filter_count(self) -> int:
        """Get number of signals penalized by ADX regime filter this session."""
        return self._penalized_by_adx_filter

    def get_blocked_by_htf_filter_count(self) -> int:
        """Get number of signals blocked by HTF trend filter this session."""
        return self._blocked_by_htf_filter

    def get_blocked_by_volume_confirm_count(self) -> int:
        return self._blocked_by_volume_confirm

    def get_blocked_by_bounce_confirm_count(self) -> int:
        return self._blocked_by_bounce_confirm

    def get_blocked_by_ema_regime_filter_count(self) -> int:
        return self._blocked_by_ema_regime_filter

    def get_blocked_by_funding_filter_count(self) -> int:
        return self._blocked_by_funding_filter

    def get_blocked_by_delta_divergence_count(self) -> int:
        return self._blocked_by_delta_divergence

    def get_blocked_by_mtf_trend_count(self) -> int:
        return self._blocked_by_mtf_trend
