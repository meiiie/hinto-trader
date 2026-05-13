"""
BacktestEngine - Application Layer

The orchestrator for backtesting trading strategies.
SOTA Feature: Multi-Timeframe Synchronization (15m + H4) with Pointer Optimization.
"""

import logging
import asyncio
from bisect import bisect_right
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, List, Optional, Dict, Any, Set, Tuple

from ...domain.entities.candle import Candle
from ...domain.entities.trading_signal import TradingSignal
from ..signals.signal_generator import SignalGenerator
from .execution_simulator import ExecutionSimulator
from ...domain.interfaces.i_historical_data_loader import IHistoricalDataLoader
from ..analysis.trend_filter import TrendFilter
from ..risk_management.circuit_breaker import CircuitBreaker
from ..services.signal_confirmation_service import SignalConfirmationService
from .time_filter import TimeFilter

if TYPE_CHECKING:
    from ..analysis.adaptive_regime_router import RollingRouterState
else:
    RollingRouterState = Any


class BacktestEngine:
    def __init__(
        self,
        signal_generator: SignalGenerator,
        loader: IHistoricalDataLoader,
        simulator: Optional[ExecutionSimulator] = None,
        trend_filter: Optional[TrendFilter] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
        symbol_quality_filter = None,
        blocked_symbol_sides: Optional[Set[Tuple[str, str]]] = None,
        rolling_router_schedule: Optional[Dict[str, RollingRouterState]] = None,
        rolling_router_exit_profiles: Optional[Dict[str, Dict[str, Any]]] = None,
        rolling_router_overlay_schedule: Optional[Dict[str, RollingRouterState]] = None,
        rolling_router_overlay_exit_profiles: Optional[Dict[str, Dict[str, Any]]] = None,
        rolling_router_symbol_active_from: Optional[Dict[str, datetime]] = None,
        use_signal_confirmation: bool = False,  # SOTA: Optional 2x confirmation
        time_filter: Optional[TimeFilter] = None,  # SOTA: Time-based death hour filter
        # BTC Regime Filter (Feb 2026)
        use_btc_regime_filter: bool = False,
        btc_regime_ema_fast: int = 5,
        btc_regime_ema_slow: int = 12,
        btc_regime_momentum_threshold: float = 0.5,
        # BTC Impulse Filter (research): signal-time side gate on BTC LTF return
        use_btc_impulse_filter: bool = False,
        btc_impulse_lookback_bars: int = 4,
        btc_impulse_threshold_pct: float = 0.5,
        # Breadth risk gate (research): portfolio-level side filter.
        use_breadth_risk_gate: bool = False,
        breadth_ema_bars: int = 96,
        breadth_momentum_bars: int = 24,
        breadth_long_threshold: float = 0.55,
        breadth_short_threshold: float = 0.55,
        breadth_min_symbols: int = 6,
    ):
        self.signal_generator = signal_generator
        self.loader = loader
        self.simulator = simulator or ExecutionSimulator()
        default_trend_period = int(getattr(signal_generator, "mtf_ema_period", 200) or 200)
        self.trend_filter = trend_filter or TrendFilter(ema_period=default_trend_period)
        self.circuit_breaker = circuit_breaker
        self.symbol_quality_filter = symbol_quality_filter
        self.blocked_symbol_sides: Set[Tuple[str, str]] = {
            (symbol.upper(), side.upper()) for symbol, side in (blocked_symbol_sides or set())
        }
        self.rolling_router_schedule = rolling_router_schedule or {}
        self.rolling_router_exit_profiles: Dict[str, Dict[str, Any]] = {
            preset: dict(profile)
            for preset, profile in (rolling_router_exit_profiles or {}).items()
        }
        self._rolling_router_states_sorted: List[RollingRouterState] = sorted(
            self.rolling_router_schedule.values(),
            key=lambda state: state.session_start_utc,
        )
        self._rolling_router_state_starts: List[datetime] = [
            state.session_start_utc for state in self._rolling_router_states_sorted
        ]
        self.rolling_router_overlay_schedule = rolling_router_overlay_schedule or {}
        self.rolling_router_overlay_exit_profiles: Dict[str, Dict[str, Any]] = {
            preset: dict(profile)
            for preset, profile in (rolling_router_overlay_exit_profiles or {}).items()
        }
        self._rolling_router_overlay_states_sorted: List[RollingRouterState] = sorted(
            self.rolling_router_overlay_schedule.values(),
            key=lambda state: state.session_start_utc,
        )
        self._rolling_router_overlay_state_starts: List[datetime] = [
            state.session_start_utc for state in self._rolling_router_overlay_states_sorted
        ]
        self.rolling_router_symbol_active_from: Dict[str, datetime] = {
            symbol.upper(): activation
            for symbol, activation in (rolling_router_symbol_active_from or {}).items()
        }
        self.use_signal_confirmation = use_signal_confirmation
        self.time_filter = time_filter  # SOTA: Time-based filter
        # PARITY FIX: Share time_filter with simulator for dead zone fill blocking
        if time_filter:
            self.simulator.time_filter = time_filter

        # BTC Regime Filter (Feb 2026): Block counter-trend based on BTC 4H EMA
        self.use_btc_regime_filter = use_btc_regime_filter
        self.btc_regime_ema_fast = btc_regime_ema_fast
        self.btc_regime_ema_slow = btc_regime_ema_slow
        self.btc_regime_momentum_threshold = btc_regime_momentum_threshold
        self._btc_regime_blocks = 0
        self._current_btc_regime = 'NEUTRAL'
        self.use_btc_impulse_filter = use_btc_impulse_filter
        self.btc_impulse_lookback_bars = max(1, int(btc_impulse_lookback_bars))
        self.btc_impulse_threshold_pct = float(btc_impulse_threshold_pct)
        self._btc_impulse_blocks = 0
        self.use_breadth_risk_gate = use_breadth_risk_gate
        self.breadth_ema_bars = max(2, int(breadth_ema_bars))
        self.breadth_momentum_bars = max(1, int(breadth_momentum_bars))
        self.breadth_long_threshold = float(breadth_long_threshold)
        self.breadth_short_threshold = float(breadth_short_threshold)
        self.breadth_min_symbols = max(1, int(breadth_min_symbols))
        self._breadth_long_blocks = 0
        self._breadth_short_blocks = 0
        self._quality_filter_rejections = 0
        self._termination_reason: Optional[str] = None
        self._terminated_early_at: Optional[datetime] = None
        self._coverage_warnings: List[str] = []
        self._research_symbol_side_blocks = 0
        self._rolling_router_shield_blocks = 0
        self._rolling_router_symbol_blocks = 0
        self._rolling_router_side_blocks = 0

        # SOTA: Signal confirmation service (matches live behavior when enabled)
        self.signal_confirmation = SignalConfirmationService(
            min_confirmations=2,
            max_wait_seconds=180  # 3 minutes = ~12 x 15m candles timeout
        ) if use_signal_confirmation else None

        self.logger = logging.getLogger(__name__)

    def _attach_router_exit_profile(
        self,
        signal: TradingSignal,
        active_router_state: Optional[RollingRouterState],
    ) -> None:
        if not active_router_state:
            return
        exit_profile = self.rolling_router_exit_profiles.get(active_router_state.preset)
        if not exit_profile:
            exit_profile = self.rolling_router_overlay_exit_profiles.get(active_router_state.preset)
        if not exit_profile:
            return
        signal.indicators = dict(signal.indicators)
        signal.indicators["research_exit_profile"] = dict(exit_profile)

    @staticmethod
    def _get_active_router_state_from(
        ts: datetime,
        starts: List[datetime],
        states: List[RollingRouterState],
    ) -> Optional[RollingRouterState]:
        if not states:
            return None
        index = bisect_right(starts, ts) - 1
        if index < 0:
            return None
        return states[index]

    def _get_active_router_state(self, ts: datetime) -> Optional[RollingRouterState]:
        return self._get_active_router_state_from(
            ts,
            self._rolling_router_state_starts,
            self._rolling_router_states_sorted,
        )

    def _get_active_router_overlay_state(self, ts: datetime) -> Optional[RollingRouterState]:
        return self._get_active_router_state_from(
            ts,
            self._rolling_router_overlay_state_starts,
            self._rolling_router_overlay_states_sorted,
        )

    def _get_effective_router_state(self, ts: datetime) -> Optional[RollingRouterState]:
        base_state = self._get_active_router_state(ts)
        overlay_state = self._get_active_router_overlay_state(ts)
        if base_state and base_state.preset != 'shield':
            return base_state
        if (
            overlay_state
            and overlay_state.preset == 'short_only_bounce_daily_pt15_maker_top50_toxicblk'
        ):
            return overlay_state
        return base_state

    def _get_portfolio_load_stats(self, interval: str) -> Dict[str, Dict[str, Any]]:
        getter = getattr(self.loader, "get_last_portfolio_load_stats", None)
        if callable(getter):
            stats = getter(interval)
            if isinstance(stats, dict):
                return stats
        return {}

    def _get_cache_coverage(self, symbol: str, interval: str) -> Dict[str, Any]:
        getter = getattr(self.loader, "get_cache_coverage", None)
        if callable(getter):
            stats = getter(symbol, interval)
            if isinstance(stats, dict):
                return stats
        return {}

    def _build_1m_coverage_error(
        self,
        symbols: List[str],
        start_time: datetime,
        end_time: Optional[datetime],
    ) -> Optional[str]:
        ltf_coverage = self._get_portfolio_load_stats("15m")
        coverage = self._get_portfolio_load_stats("1m")
        if not coverage:
            return None

        start_tolerance = timedelta(minutes=1)
        end_tolerance = timedelta(minutes=15)
        gaps: List[str] = []
        listing_limited: List[str] = []
        for symbol in symbols:
            symbol_start_time = self.rolling_router_symbol_active_from.get(symbol.upper(), start_time)
            ltf_stat = ltf_coverage.get(symbol, {})
            ltf_count = int(ltf_stat.get("count") or 0)
            ltf_start = ltf_stat.get("start")
            ltf_end = ltf_stat.get("end")

            if ltf_count <= 0 or ltf_start is None:
                cache_ltf = self._get_cache_coverage(symbol, "15m")
                cache_m1 = self._get_cache_coverage(symbol, "1m")
                cache_ltf_start = cache_ltf.get("start")
                cache_m1_start = cache_m1.get("start")
                if (
                    end_time is not None
                    and cache_ltf_start is not None
                    and cache_ltf_start > end_time + start_tolerance
                    and (
                        cache_m1_start is None
                        or cache_m1_start > end_time + start_tolerance
                    )
                ):
                    listing_limited.append(
                        f"{symbol}:listed_after_window {cache_ltf_start.isoformat()}"
                    )
                    continue
                gaps.append(f"{symbol}:missing_15m")
                continue

            stat = coverage.get(symbol, {})
            count = int(stat.get("count") or 0)
            first_ts = stat.get("start")
            last_ts = stat.get("end")

            if count <= 0 or first_ts is None:
                cache_m1 = self._get_cache_coverage(symbol, "1m")
                cache_m1_start = cache_m1.get("start")
                if (
                    end_time is not None
                    and cache_m1_start is not None
                    and cache_m1_start > end_time + start_tolerance
                    and ltf_start > end_time + start_tolerance
                ):
                    listing_limited.append(
                        f"{symbol}:listed_after_window {ltf_start.isoformat()}"
                    )
                    continue
                gaps.append(f"{symbol}:missing_1m")
                continue

            if ltf_start > symbol_start_time + start_tolerance:
                listing_limited.append(f"{symbol}:listed {ltf_start.isoformat()}")
            elif first_ts > symbol_start_time + start_tolerance:
                gaps.append(f"{symbol}:1m_starts {first_ts.isoformat()}")
                continue
            if end_time is not None and last_ts is not None and ltf_end is not None and last_ts < ltf_end - end_tolerance:
                gaps.append(f"{symbol}:1m_ends {last_ts.isoformat()}")

        self._coverage_warnings = listing_limited

        if not gaps:
            return None

        sample = ", ".join(gaps[:5])
        extra = "" if len(gaps) <= 5 else f" (+{len(gaps) - 5} more)"
        return (
            "1m coverage gap blocks like-live backtest: "
            f"{sample}{extra}. Backfill 1m cache or use a later window."
        )

    async def run_portfolio(
        self,
        symbols: List[str],
        interval: str,
        start_time: datetime,
        end_time: Optional[datetime] = None,
        warmup_candles: int = 50
    ) -> Dict[str, Any]:
        self._termination_reason = None
        self._terminated_early_at = None
        self._coverage_warnings = []
        if self.symbol_quality_filter and not self.rolling_router_schedule:
            eligible_symbols: List[str] = []
            rejected_symbols: List[str] = []
            for symbol in symbols:
                try:
                    eligible, reason = self.symbol_quality_filter.is_eligible(symbol, as_of=start_time)
                except TypeError:
                    eligible, reason = self.symbol_quality_filter.is_eligible(symbol)
                if eligible:
                    eligible_symbols.append(symbol)
                else:
                    rejected_symbols.append(f"{symbol}:{reason}")

            if rejected_symbols:
                self._quality_filter_rejections += len(rejected_symbols)
                self.logger.info(
                    f"Quality filter rejected {len(rejected_symbols)} symbols before backtest: {rejected_symbols}"
                )

            symbols = eligible_symbols

            if not symbols:
                return {"error": "No eligible symbols after quality filter"}

        # SOTA (Jan 2026): Load BTC candles for BTC filter
        if self.signal_generator.use_btc_filter:
            self.logger.info("📊 BTC FILTER: Loading BTC candles for trend detection...")
            try:
                # Load BTC candles for the same time range
                btc_candles = await self.loader.load_candles(
                    'BTCUSDT',
                    interval,
                    start_time,
                    end_time
                )
                self.signal_generator.set_btc_candles(btc_candles)
                self.logger.info(f"✅ BTC FILTER: Loaded {len(btc_candles)} BTC candles")
            except Exception as e:
                self.logger.error(f"❌ BTC FILTER: Failed to load BTC candles: {e}")
                self.logger.warning("⚠️ BTC FILTER: Continuing without BTC filter")
                self.signal_generator.use_btc_filter = False

        # 1. Load Data (with warmup buffer for signal generator)
        # LTF needs history BEFORE start_time for swing detection + warmup
        ltf_buffer_days = 7  # 7 days = 672 candles @ 15m, plenty for lookback + warmup
        ltf_start = start_time - timedelta(days=ltf_buffer_days)
        ltf_symbols = list(symbols)
        if self.use_btc_impulse_filter and 'BTCUSDT' not in ltf_symbols:
            ltf_symbols.append('BTCUSDT')
        ltf_timeline = await self.loader.load_portfolio_data(ltf_symbols, interval, ltf_start, end_time)

        # HTF needs enough history for the configured EMA period.
        htf_start = start_time - timedelta(days=60)
        # BTC Regime Filter: ensure BTCUSDT is in HTF data
        htf_symbols = symbols
        if self.use_btc_regime_filter and 'BTCUSDT' not in symbols:
            htf_symbols = symbols + ['BTCUSDT']
        htf_timeline = await self.loader.load_portfolio_data(htf_symbols, "4h", htf_start, end_time)

        # SOTA (Feb 2026): Load 1m data for position monitoring if enabled
        m1_timeline = {}
        if getattr(self.simulator, 'use_1m_monitoring', False):
            self.logger.info("📊 1M MONITORING: Loading 1m candle data for position monitoring...")
            try:
                m1_timeline = await self.loader.load_portfolio_data(symbols, "1m", ltf_start, end_time)
                self.logger.info(f"✅ 1M MONITORING: Loaded {len(m1_timeline)} 1m timestamps")
            except Exception as e:
                self.logger.error(f"❌ 1M MONITORING: Failed to load 1m data: {e}")
                self.logger.warning("⚠️ 1M MONITORING: Falling back to 15m-only monitoring")
                self.simulator.use_1m_monitoring = False

        if getattr(self.simulator, 'use_1m_monitoring', False):
            coverage_error = self._build_1m_coverage_error(symbols, start_time, end_time)
            if coverage_error:
                self.logger.error(coverage_error)
                return {"error": coverage_error}

        if not ltf_timeline:
            return {"error": "No data"}

        self.logger.info(f"🚀 Starting HTF-Enabled Backtest | {len(ltf_timeline)} steps | HTF: 4h")

        ltf_history_symbols = set(symbols)
        if self.use_btc_impulse_filter:
            ltf_history_symbols.add('BTCUSDT')
        symbol_histories_ltf: Dict[str, List[Candle]] = {s: [] for s in ltf_history_symbols}
        # Include BTCUSDT in HTF history if regime filter is on
        htf_history_symbols = set(symbols)
        if self.use_btc_regime_filter:
            htf_history_symbols.add('BTCUSDT')
        symbol_histories_htf: Dict[str, List[Candle]] = {s: [] for s in htf_history_symbols}

        # SOTA (Jan 2026): Replay Snapshots Storage
        self.replay_snapshots = []

        ltf_ts_list = sorted(ltf_timeline.keys())
        htf_ts_list = sorted(htf_timeline.keys())

        # SOTA (Feb 2026): 1m pointer for efficient sync
        m1_ts_list = sorted(m1_timeline.keys()) if m1_timeline else []
        m1_ptr = 0

        htf_ptr = 0 # Pointer for efficient HTF sync

        # 2. Main Time Loop
        for i, ts in enumerate(ltf_ts_list):
            # A. Update HTF histories up to current timestamp
            while htf_ptr < len(htf_ts_list) and htf_ts_list[htf_ptr] <= ts:
                h_ts = htf_ts_list[htf_ptr]
                for sym, candle in htf_timeline[h_ts].items():
                    symbol_histories_htf[sym].append(candle)
                htf_ptr += 1

            # B. Update LTF
            current_ltf_map = ltf_timeline[ts]
            for sym, candle in current_ltf_map.items():
                symbol_histories_ltf[sym].append(candle)

            # C. Determine Bias
            htf_bias_map = {}
            for sym in symbols:
                h_history = symbol_histories_htf.get(sym, [])
                if len(h_history) >= 200:
                    htf_bias_map[sym] = self.trend_filter.calculate_bias(h_history)
                else:
                    htf_bias_map[sym] = 'NEUTRAL'

            # C2. BTC Regime Detection (Feb 2026)
            if self.use_btc_regime_filter:
                btc_4h = symbol_histories_htf.get('BTCUSDT', [])
                if len(btc_4h) >= self.btc_regime_ema_slow:
                    self._current_btc_regime = self._calculate_btc_regime(btc_4h)

            # D. Update Simulator & Circuit Breaker Record
            self.simulator.update(current_ltf_map, ts)

            if self.circuit_breaker:
                # 1. Update Portfolio Health (Global Drawdown Check)
                self.circuit_breaker.update_portfolio_state(self.simulator.balance, ts)

                # 2. Record Completed Trades
                for trade in self.simulator.trades:
                    if trade.exit_time == ts:
                        self.circuit_breaker.record_trade_with_time(trade.symbol, trade.side, trade.pnl_usd, ts)

            # D2. SOTA (Feb 2026): 1m Position Monitoring
            # Process all 1m candles within this 15m bar for SL/TP/AC checks
            if m1_ts_list:
                trades_before_1m = len(self.simulator.trades)
                next_15m_ts = ltf_ts_list[i + 1] if i + 1 < len(ltf_ts_list) else ts + timedelta(minutes=15)
                while m1_ptr < len(m1_ts_list) and m1_ts_list[m1_ptr] < next_15m_ts:
                    m1_ts = m1_ts_list[m1_ptr]
                    self.simulator.update_positions_1m(m1_timeline[m1_ts], m1_ts)
                    # LIKE-LIVE: Check portfolio target on every 1m candle (not just 15m)
                    if self.simulator.portfolio_target > 0 and self.simulator.positions:
                        m1_candle_map = m1_timeline[m1_ts]
                        if self.simulator.check_portfolio_target(m1_candle_map):
                            symbols_to_close_1m = list(self.simulator.positions.keys())
                            for sym_close in symbols_to_close_1m:
                                if sym_close in m1_candle_map:
                                    c1m = m1_candle_map[sym_close]
                                    vol1m = (c1m.high - c1m.low) / c1m.open if c1m.open > 0 else 0
                                    slip1m = self.simulator.base_slippage_rate + (vol1m * 0.1)
                                    self.simulator._close_position(sym_close, c1m.close, "PORTFOLIO_TARGET", m1_ts, slip1m)
                    m1_ptr += 1
                # Record 1m-closed trades with circuit breaker
                if self.circuit_breaker and len(self.simulator.trades) > trades_before_1m:
                    for trade in self.simulator.trades[trades_before_1m:]:
                        self.circuit_breaker.record_trade_with_time(trade.symbol, trade.side, trade.pnl_usd, ts)

            if self.simulator.is_capital_exhausted():
                self._terminated_early_at = ts
                self._termination_reason = "capital_exhausted_no_compound"
                self.simulator._capital_exhausted_at = ts
                self.logger.warning(
                    "Stopping backtest early: no-compound balance fell below fixed slot size "
                    f"(${self.simulator.get_no_compound_slot_size():.2f}) at {ts.isoformat()}"
                )
                break

            # E. Signal Generation (only after start_time — buffer period is for history only)
            if ts < start_time:
                continue
            active_router_state: Optional[RollingRouterState] = None
            if self.rolling_router_schedule:
                active_router_state = self._get_effective_router_state(ts)
                if active_router_state and active_router_state.preset == 'shield':
                    self._rolling_router_shield_blocks += 1
                    continue
            breadth_state = None
            if self.use_breadth_risk_gate:
                breadth_state = self._calculate_breadth_state(symbol_histories_ltf, symbols)
            signals_batch = []
            for sym in symbols:
                candle = current_ltf_map.get(sym)
                if candle is None:
                    continue
                if len(symbol_histories_ltf[sym]) < warmup_candles:
                    continue
                if active_router_state and sym.upper() not in active_router_state.allowed_symbols:
                    self._rolling_router_symbol_blocks += 1
                    continue

                # SOTA: Tiered Time-based filter
                # Gets size multiplier (1.0/0.5/0.3/0.0) based on hour
                time_multiplier = 1.0  # Default full size
                if self.time_filter:
                    time_multiplier = self.time_filter.get_size_multiplier(ts)
                    if time_multiplier == 0:
                        continue  # Blocked hour (Tier 4)

                # Check Circuit Breaker
                is_long_blocked = False
                is_short_blocked = False
                if self.circuit_breaker:
                    is_long_blocked = self.circuit_breaker.is_blocked(sym, 'LONG', ts)
                    is_short_blocked = self.circuit_breaker.is_blocked(sym, 'SHORT', ts)

                # BTC Regime Filter: block counter-trend direction
                btc_impulse_pct = 0.0
                if self.use_btc_regime_filter and sym != 'BTCUSDT':
                    if self._current_btc_regime in ('STRONG_BULL', 'BULL'):
                        is_short_blocked = True
                    elif self._current_btc_regime in ('STRONG_BEAR', 'BEAR'):
                        is_long_blocked = True
                if self.use_btc_impulse_filter and sym != 'BTCUSDT':
                    btc_ltf = symbol_histories_ltf.get('BTCUSDT', [])
                    btc_impulse_pct = self._calculate_btc_impulse_pct(btc_ltf)
                    if btc_impulse_pct >= self.btc_impulse_threshold_pct:
                        is_short_blocked = True
                    elif btc_impulse_pct <= -self.btc_impulse_threshold_pct:
                        is_long_blocked = True

                if is_long_blocked and is_short_blocked:
                    continue

                # SOTA: Pass funding rate for --funding-filter
                funding_rate = 0
                if hasattr(self.simulator, 'funding_loader') and self.simulator.funding_loader:
                    funding_rate = self.simulator.funding_loader.get_funding_at_time(sym, ts)
                elif hasattr(self.simulator, 'funding_rates') and self.simulator.funding_rates:
                    funding_rate = self.simulator.funding_rates.get(sym, 0)

                signal = self.signal_generator.generate_signal(
                    symbol_histories_ltf[sym], sym, htf_bias=htf_bias_map.get(sym, 'NEUTRAL'),
                    funding_rate=funding_rate
                )

                if signal and signal.signal_type.value != 'neutral':
                    signal_side = 'LONG' if signal.signal_type.value == 'buy' else 'SHORT'
                    rolling_blocked_sides = (
                        active_router_state.blocked_symbol_sides if active_router_state else tuple()
                    )
                    if (
                        (sym.upper(), signal_side) in self.blocked_symbol_sides
                        or ("*", signal_side) in self.blocked_symbol_sides
                        or (sym.upper(), signal_side) in rolling_blocked_sides
                        or ("*", signal_side) in rolling_blocked_sides
                    ):
                        if (
                            (sym.upper(), signal_side) in rolling_blocked_sides
                            or ("*", signal_side) in rolling_blocked_sides
                        ):
                            self._rolling_router_side_blocks += 1
                        self._research_symbol_side_blocks += 1
                        continue
                    if self._is_blocked_by_breadth(signal_side, breadth_state):
                        if signal_side == "LONG":
                            self._breadth_long_blocks += 1
                        else:
                            self._breadth_short_blocks += 1
                        continue
                    # SOTA: Apply daily loss size penalty (Freqtrade style)
                    if self.circuit_breaker:
                        loss_penalty = self.circuit_breaker.get_daily_loss_penalty(sym, ts)
                        if loss_penalty <= 0:
                            continue  # Fully penalized = effectively blocked
                        time_multiplier *= loss_penalty
                    # SOTA: Store time multiplier for tiered sizing
                    signal.indicators['time_multiplier'] = time_multiplier
                    self._attach_router_exit_profile(signal, active_router_state)
                    # Filter signal by CB + BTC Regime
                    if signal.signal_type.value == 'buy' and is_long_blocked:
                        if self.use_btc_regime_filter and self._current_btc_regime in ('STRONG_BEAR', 'BEAR'):
                            self._btc_regime_blocks += 1
                        if self.use_btc_impulse_filter and btc_impulse_pct <= -self.btc_impulse_threshold_pct:
                            self._btc_impulse_blocks += 1
                        continue
                    if signal.signal_type.value == 'sell' and is_short_blocked:
                        if self.use_btc_regime_filter and self._current_btc_regime in ('STRONG_BULL', 'BULL'):
                            self._btc_regime_blocks += 1
                        if self.use_btc_impulse_filter and btc_impulse_pct >= self.btc_impulse_threshold_pct:
                            self._btc_impulse_blocks += 1
                        continue

                    # SOTA: Optional Signal Confirmation (matches live behavior)
                    if self.signal_confirmation:
                        confirmed_signal = self.signal_confirmation.process_signal(sym, signal)
                        if confirmed_signal:
                            signals_batch.append(confirmed_signal)
                        # else: signal pending confirmation, skip this candle
                    else:
                        # No confirmation - execute immediately (default backtest behavior)
                        signals_batch.append(signal)

            # F. Shark Tank Execution
            if signals_batch:
                # DEBUG: Log signal distribution
                buy_count = sum(1 for s in signals_batch if s.signal_type.value == 'buy')
                sell_count = sum(1 for s in signals_batch if s.signal_type.value == 'sell')
                if buy_count > 0 or sell_count > 0:
                    self.logger.debug(f"📊 Batch: BUY={buy_count}, SELL={sell_count}")

                # SOTA (Jan 2026): Check signal reversal BEFORE processing batch
                # This allows us to exit positions on opposite signals
                symbols_to_close_reversal = []
                for signal in signals_batch:
                    reversal_symbols = self.simulator.check_signal_reversal(signal)
                    symbols_to_close_reversal.extend(reversal_symbols)

                # Close positions due to signal reversal
                if symbols_to_close_reversal:
                    for symbol in symbols_to_close_reversal:
                        if symbol in self.simulator.positions:
                            current_price = current_ltf_map[symbol].close
                            volatility = (current_ltf_map[symbol].high - current_ltf_map[symbol].low) / current_ltf_map[symbol].open
                            slippage = self.simulator.base_slippage_rate + (volatility * 0.1)
                            self.simulator._close_position(
                                symbol=symbol,
                                price=current_price,
                                reason="SIGNAL_REVERSAL",
                                time=ts,
                                slippage=slippage
                            )

                # Process batch signals (after reversal exits)
                self.simulator.process_batch_signals(signals_batch)

            # SOTA (Jan 2026): Check portfolio profit target AFTER signal processing
            # This ensures we check after all positions are updated
            if self.simulator.check_portfolio_target(current_ltf_map):
                # Close all positions
                symbols_to_close = list(self.simulator.positions.keys())
                for symbol in symbols_to_close:
                    if symbol in current_ltf_map:
                        current_price = current_ltf_map[symbol].close
                        volatility = (current_ltf_map[symbol].high - current_ltf_map[symbol].low) / current_ltf_map[symbol].open
                        slippage = self.simulator.base_slippage_rate + (volatility * 0.1)
                        self.simulator._close_position(
                            symbol=symbol,
                            price=current_price,
                            reason="PORTFOLIO_TARGET",
                            time=ts,
                            slippage=slippage
                        )
                self.logger.info(f"📊 Portfolio target hit, closed {len(symbols_to_close)} positions")

            # G. Capture Replay Snapshot (SOTA Jan 2026)
            if getattr(self.simulator, 'capture_events', False):
                snapshot = self.simulator.get_snapshot(ts)
                if snapshot:
                    self.replay_snapshots.append(snapshot)

            if i % 1000 == 0:
                self.logger.info(f"Progress: {i}/{len(ltf_ts_list)} steps...")

        # D2-FIX: Process remaining 1m candles after last 15m bar
        # Without this, positions opened near end of data never get SL checked
        if m1_ts_list and m1_ptr < len(m1_ts_list):
            remaining_1m = 0
            while m1_ptr < len(m1_ts_list):
                m1_ts = m1_ts_list[m1_ptr]
                self.simulator.update_positions_1m(m1_timeline[m1_ts], m1_ts)
                m1_ptr += 1
                remaining_1m += 1
            if remaining_1m > 0:
                self.logger.info(f"Processed {remaining_1m} remaining 1m candles after main loop")

        # D2-FIX: Force-close any remaining open positions at last available price
        if self.simulator.positions:
            last_ts = m1_ts_list[-1] if m1_ts_list else ltf_ts_list[-1]
            last_candle_map = m1_timeline.get(last_ts, {}) if m1_ts_list else (
                {sym: symbol_histories_ltf[sym][-1] for sym in symbol_histories_ltf if symbol_histories_ltf[sym]}
            )
            remaining_symbols = list(self.simulator.positions.keys())
            for sym_close in remaining_symbols:
                if sym_close in last_candle_map:
                    c = last_candle_map[sym_close]
                    close_price = c.close if hasattr(c, 'close') else c
                    self.simulator._close_position(sym_close, close_price, "END_OF_DATA", last_ts, slippage=0.0)
            if remaining_symbols:
                self.logger.info(f"Force-closed {len(remaining_symbols)} remaining positions at end of data: {remaining_symbols}")

        # Prepare candle data for API
        candles_output = {}
        indicators_output = {}

        for sym, hist in symbol_histories_ltf.items():
            # 1. Candles
            candles_output[sym] = [
                {
                    "time": c.timestamp,
                    "open": c.open,
                    "high": c.high,
                    "low": c.low,
                    "close": c.close,
                    "volume": c.volume
                } for c in hist
            ]

            # 2. Visualization Indicators (Batch Calculation)
            # We use pandas for efficient batch processing for the frontend chart
            if not hist:
                continue

            try:
                import pandas as pd
                import numpy as np

                df = pd.DataFrame([vars(c) for c in hist])
                df.set_index('timestamp', inplace=True)
                df.sort_index(inplace=True)

                # A. Bollinger Bands (20, 2.0)
                # Matches standard Liquidity Sniper settings
                df['tp'] = (df['high'] + df['low'] + df['close']) / 3
                df['ma'] = df['tp'].rolling(window=20).mean()
                df['std'] = df['tp'].rolling(window=20).std()
                df['bb_upper'] = df['ma'] + (2.0 * df['std'])
                df['bb_lower'] = df['ma'] - (2.0 * df['std'])

                # B. VWAP (Rolling 24h = 96 periods of 15m)
                # Standard crypto intraday VWAP approximation
                v = df['volume'].values
                tp = df['tp'].values
                df['vwap'] = (df['volume'] * df['tp']).rolling(window=96).sum() / df['volume'].rolling(window=96).sum()

                # C. Limit Sniper Levels (Swing High/Low 20 + 0.1%)
                # Visualization only - to show where the bot IS LOOKING to enter
                df['swing_high'] = df['high'].rolling(window=20).max()
                df['swing_low'] = df['low'].rolling(window=20).min()
                df['limit_sell'] = df['swing_high'] * 1.001
                df['limit_buy'] = df['swing_low'] * 0.999

                # Fill NaN
                df.fillna(0, inplace=True) # Or keep None for chart to skip

                indicators_output[sym] = {
                    "bb_upper": df['bb_upper'].replace({np.nan: None}).tolist(),
                    "bb_lower": df['bb_lower'].replace({np.nan: None}).tolist(),
                    "vwap": df['vwap'].replace({np.nan: None}).tolist(),
                    "limit_sell": df['limit_sell'].replace({np.nan: None}).tolist(),
                    "limit_buy": df['limit_buy'].replace({np.nan: None}).tolist()
                }

            except ImportError:
                self.logger.warning("Pandas not found, skipping visualization indicators")
                indicators_output[sym] = {}
            except Exception as e:
                self.logger.error(f"Failed to calc visualization indicators for {sym}: {e}")
                indicators_output[sym] = {}

        # Prepare Blocked Periods (Circuit Breaker)
        blocked_periods = []
        if self.circuit_breaker:
             pass

        # Prepare Replay Data (SOTA Jan 2026)
        replay_data = {
            "snapshots": self.replay_snapshots,
            "symbols": symbols,
            "interval": interval,
            "candles": candles_output,      # Added: Full candle history for chart
            "indicators": indicators_output # Added: Pre-calculated indicators
        }

        # SOTA (Jan 2026): Format trades with frontend-expected field names
        formatted_trades = []
        for t in self.simulator.trades:
            trade_dict = t.__dict__.copy()
            # Add frontend aliases
            trade_dict['quantity'] = trade_dict.get('position_size', 0)
            trade_dict['margin_used'] = trade_dict.get('margin_at_entry', 0)
            trade_dict['funding_cost'] = trade_dict.get('funding_cost', 0)
            formatted_trades.append(trade_dict)

        # Add BTC regime stats to result
        stats = self.simulator.get_stats()
        stats["quality_filter_rejections"] = self._quality_filter_rejections
        if self.use_btc_regime_filter:
            stats['btc_regime_blocks'] = self._btc_regime_blocks
        if self.use_btc_impulse_filter:
            stats['btc_impulse_blocks'] = self._btc_impulse_blocks
        if self.use_breadth_risk_gate:
            stats["breadth_long_blocks"] = self._breadth_long_blocks
            stats["breadth_short_blocks"] = self._breadth_short_blocks
        if self._termination_reason:
            stats["termination_reason"] = self._termination_reason
            stats["terminated_early_at"] = self._terminated_early_at
        if self._coverage_warnings:
            stats["coverage_warnings"] = list(self._coverage_warnings)
        if self._research_symbol_side_blocks > 0:
            stats["research_symbol_side_blocks"] = self._research_symbol_side_blocks
        if self._rolling_router_shield_blocks > 0:
            stats["rolling_router_shield_blocks"] = self._rolling_router_shield_blocks
        if self._rolling_router_symbol_blocks > 0:
            stats["rolling_router_symbol_blocks"] = self._rolling_router_symbol_blocks
        if self._rolling_router_side_blocks > 0:
            stats["rolling_router_side_blocks"] = self._rolling_router_side_blocks

        return {
            "symbols": symbols,
            "stats": stats,
            "trades": formatted_trades,
            "equity": self.simulator.equity_curve,
            "candles": candles_output,
            "indicators": indicators_output,
            "blocked_periods": blocked_periods,
            "replay_data": replay_data if self.replay_snapshots else None
        }

    def _calculate_btc_regime(self, btc_candles: List[Candle]) -> str:
        """
        BTC Regime Detection using EMA cross + momentum on 4H candles.

        Returns: 'STRONG_BULL', 'BULL', 'NEUTRAL', 'BEAR', 'STRONG_BEAR'
        """
        closes = [c.close for c in btc_candles]
        if len(closes) < self.btc_regime_ema_slow:
            return 'NEUTRAL'

        ema_fast = self._ema(closes, self.btc_regime_ema_fast)
        ema_slow = self._ema(closes, self.btc_regime_ema_slow)

        # Momentum: last bar return as % (4H bar = ~4 hours)
        momentum = 0.0
        if len(closes) >= 2:
            momentum = (closes[-1] - closes[-2]) / closes[-2] * 100

        # Regime classification
        if ema_fast > ema_slow:
            if momentum > self.btc_regime_momentum_threshold:
                return 'STRONG_BULL'
            return 'BULL'
        elif ema_fast < ema_slow:
            if momentum < -self.btc_regime_momentum_threshold:
                return 'STRONG_BEAR'
            return 'BEAR'
        return 'NEUTRAL'

    def _calculate_breadth_state(
        self,
        symbol_histories_ltf: Dict[str, List[Candle]],
        symbols: List[str],
    ) -> Dict[str, float]:
        """Calculate current universe breadth without future data."""

        min_required = max(self.breadth_ema_bars, self.breadth_momentum_bars) + 1
        evaluated = 0
        bullish = 0
        bearish = 0

        for symbol in symbols:
            history = symbol_histories_ltf.get(symbol, [])
            if len(history) < min_required:
                continue
            closes = [float(c.close) for c in history[-min_required:]]
            current = closes[-1]
            past = closes[-self.breadth_momentum_bars - 1]
            if current <= 0 or past <= 0:
                continue
            ema_value = self._ema(closes, self.breadth_ema_bars)
            momentum = (current - past) / past
            evaluated += 1
            if current > ema_value and momentum > 0:
                bullish += 1
            elif current < ema_value and momentum < 0:
                bearish += 1

        if evaluated <= 0:
            return {
                "evaluated": 0.0,
                "bullish_ratio": 0.0,
                "bearish_ratio": 0.0,
            }

        return {
            "evaluated": float(evaluated),
            "bullish_ratio": bullish / evaluated,
            "bearish_ratio": bearish / evaluated,
        }

    def _is_blocked_by_breadth(
        self,
        signal_side: str,
        breadth_state: Optional[Dict[str, float]],
    ) -> bool:
        if not self.use_breadth_risk_gate:
            return False
        if not breadth_state or breadth_state.get("evaluated", 0.0) < self.breadth_min_symbols:
            return True
        if signal_side == "LONG":
            return breadth_state["bullish_ratio"] < self.breadth_long_threshold
        if signal_side == "SHORT":
            return breadth_state["bearish_ratio"] < self.breadth_short_threshold
        return False

    def _calculate_btc_impulse_pct(self, btc_candles: List[Candle]) -> float:
        """Return BTC LTF impulse over the configured lookback window."""
        if len(btc_candles) <= self.btc_impulse_lookback_bars:
            return 0.0

        reference_close = btc_candles[-(self.btc_impulse_lookback_bars + 1)].close
        current_close = btc_candles[-1].close
        if reference_close <= 0:
            return 0.0
        return ((current_close - reference_close) / reference_close) * 100.0

    @staticmethod
    def _rolling_router_session_key(ts: datetime) -> str:
        return ts.astimezone(timezone(timedelta(hours=7))).date().isoformat()

    @staticmethod
    def _ema(values: List[float], period: int) -> float:
        """Calculate EMA of the last value in the series."""
        if len(values) < period:
            return sum(values) / len(values) if values else 0
        multiplier = 2.0 / (period + 1)
        ema = sum(values[:period]) / period  # SMA seed
        for val in values[period:]:
            ema = (val - ema) * multiplier + ema
        return ema
