"""
SharkTankCoordinator - Application Layer

SOTA: Central coordinator for multi-symbol signal batching.
Matches backtest Shark Tank behavior exactly:
- Collects signals from all symbols within a time window
- Ranks by confidence score
- Executes best N based on max_positions

Created: 2026-01-03
Purpose: Fix gap where realtime didn't batch-rank signals like backtest
"""

import logging
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Callable, Set
from dataclasses import dataclass, field
from threading import Lock

from ...domain.entities.trading_signal import TradingSignal, SignalType


@dataclass
class BatchedSignal:
    """Signal waiting in batch queue."""
    signal: TradingSignal
    symbol: str
    received_at: datetime
    confidence: float


class SharkTankCoordinator:
    """
    SOTA: Multi-symbol signal coordinator matching backtest.

    How it works:
    1. collect_signal() - RealtimeService calls this instead of executing immediately
    2. Every batch_interval_seconds, process_batch() is called
    3. Signals are ranked by confidence
    4. Best signals (up to max_positions - current_positions) are executed

    This prevents the situation where 10 symbols signal at once
    and all 10 try to open positions.
    """

    def __init__(
        self,
        max_positions: int = 3,
        batch_interval_seconds: float = 5.0,  # Collect for 5 seconds, then execute
        enable_smart_recycling: bool = False,  # SOTA SYNC (Jan 2026): Default FALSE to match backtest
    ):
        self.max_positions = max_positions
        self.batch_interval = batch_interval_seconds
        self.enable_smart_recycling = enable_smart_recycling  # SOTA: Store recycling flag

        self._pending_signals: Dict[str, BatchedSignal] = {}  # symbol -> signal
        self._last_batch_time: datetime = datetime.now()
        self._lock = Lock()
        self._flush_task: Optional[asyncio.Task] = None  # SOTA: For debounce timer

        # CRITICAL: Initialize logger FIRST (before any logging calls)
        self.logger = logging.getLogger(__name__)

        # SOTA FIX (Jan 2026): Single Batch Per Candle - Track candle timestamps
        # This prevents multiple batches per candle (root cause of 2-10x signals)
        self._current_candle_time: Optional[datetime] = None  # Candle being processed
        self._last_candle_time: Optional[datetime] = None     # Last processed candle

        # SOTA (Feb 2026): SHORT trading ENABLED - Layer 2 disabled
        import os
        self._env = os.getenv("ENV", "paper").lower()
        self._is_live_mode = (self._env == "live")
        self._blocked_short_signals = 0  # Legacy counter, no longer blocking

        # CRITICAL FIX (Jan 2026): Batch cooldown to match backtest
        # UPDATED (Jan 26, 2026): Different cooldown for LIVE vs BACKTEST
        # - BACKTEST: 900s (15 min) - signals arrive at candle close
        # - LIVE: 60s (1 min) - signals arrive continuously
        env = os.getenv("ENV", "paper").lower()
        if env == "live":
            self.batch_cooldown_seconds = 60  # 1 minute for LIVE
            self.logger.info("🦈 LIVE MODE: Batch cooldown = 60s (allows 15 batches per 15min)")
        else:
            self.batch_cooldown_seconds = 900  # 15 minutes for BACKTEST
            self.logger.info("🦈 BACKTEST MODE: Batch cooldown = 900s (1 batch per candle)")
        self._last_batch_processed_time: Optional[datetime] = None

        # SOTA (Feb 2026): Symbol Quality Filter (injected post-init)
        self.symbol_quality_filter = None

        # SOTA (Feb 9, 2026): Circuit Breaker (injected post-init by DI Container)
        # Used for: (1) Trading Schedule dead-zone check, (2) Per-symbol CB filtering
        self.circuit_breaker = None

        # Metrics
        self.metrics = {
            'batches_processed': 0,
            'batches_rejected_cooldown': 0,
            'batches_deferred_cooldown': 0,
            'total_signals_processed': 0,
            'total_signals_rejected': 0
        }
        self._cooldown_defer_until: Optional[datetime] = None

        # Callbacks
        self._execute_callback: Optional[Callable[[TradingSignal], None]] = None
        self._get_open_positions_callback: Optional[Callable[[], int]] = None
        self._get_available_margin_callback: Optional[Callable[[], float]] = None
        # SOTA (Jan 2026): Smart Recycling callbacks - matches ExecutionSimulator
        self._get_pending_orders_callback: Optional[Callable[[], List[Dict]]] = None
        self._get_current_prices_callback: Optional[Callable[[], Dict[str, float]]] = None
        self._cancel_order_callback: Optional[Callable[[str], bool]] = None
        # SOTA (Jan 2026): Position filter callback - CRITICAL for matching backtest behavior
        self._get_position_symbols_callback: Optional[Callable[[], Set[str]]] = None

        # SOTA: Minimum margin required to attempt order
        # Binance Futures USDT-M minimum notional is $5
        # Set low to support small accounts (e.g., $17 balance)
        self.min_margin_required = 5.0  # $5 minimum (was $50 - too high)

        # SOTA: Proximity Sentry threshold - orders within this % of target are LOCKED
        self.proximity_lock_pct = 0.002  # 0.2% - matches backtest

        # SOTA: Confidence buffer for recycling - new signal must be 10% better
        self.recycle_confidence_buffer = 1.1  # 10% buffer to avoid churn

        self.logger.info(
            f"🦈 SharkTankCoordinator initialized: "
            f"max_positions={max_positions}, batch_interval={batch_interval_seconds}s, "
            f"recycling={enable_smart_recycling}"
        )

        if self._is_live_mode:
            self.logger.info("✅ LIVE MODE: SHORT trading ENABLED (Layer 2 filter disabled)")

    def set_callbacks(
        self,
        execute_callback: Callable[[TradingSignal], None],
        get_open_positions_callback: Callable[[], int],
        get_available_margin_callback: Optional[Callable[[], float]] = None,
        # SOTA (Jan 2026): New callbacks for Smart Recycling
        get_pending_orders_callback: Optional[Callable[[], List[Dict]]] = None,
        get_current_prices_callback: Optional[Callable[[], Dict[str, float]]] = None,
        cancel_order_callback: Optional[Callable[[str], bool]] = None,
        # SOTA (Jan 2026): Position filter callback - CRITICAL for matching backtest
        get_position_symbols_callback: Optional[Callable[[], Set[str]]] = None
    ):
        """
        Set callbacks for signal execution.

        Args:
            execute_callback: Function to execute a signal (routes to live/paper)
            get_open_positions_callback: Function to get current open position count
            get_available_margin_callback: Function to get available margin (SOTA)
            get_pending_orders_callback: Function to get list of pending orders with confidence
            get_current_prices_callback: Function to get current prices for PROXIMITY SENTRY
            cancel_order_callback: Function to cancel a pending order by symbol
            get_position_symbols_callback: Function to get set of symbols with open positions (CRITICAL)
        """
        self._execute_callback = execute_callback
        self._get_open_positions_callback = get_open_positions_callback
        self._get_available_margin_callback = get_available_margin_callback
        self._get_pending_orders_callback = get_pending_orders_callback
        self._get_current_prices_callback = get_current_prices_callback
        self._cancel_order_callback = cancel_order_callback
        self._get_position_symbols_callback = get_position_symbols_callback

    def collect_signal(self, signal: TradingSignal, symbol: str) -> bool:
        """
        Collect signal for batch processing.

        SOTA: Instead of executing immediately, signals are queued.
        Only the best signals (by confidence) will be executed.

        CRITICAL FIX (Jan 2026): Removed auto-batch on timer.
        Batch is now processed via force_process() called by main.py
        after all 15m candle signals are received. This matches backtest
        behavior exactly where ALL signals at same timestamp are ranked.

        SOTA FIX (Jan 2026): Single Batch Per Candle - Track candle timestamp.
        Prevents multiple batches per candle (root cause of 2-10x signals).
        Each candle is processed exactly ONCE, matching BACKTEST behavior.

        SOTA (Feb 2026): SHORT trading ENABLED - Layer 2 disabled.
        SHORT signals now pass through to execution like LONG signals.

        Args:
            signal: Trading signal
            symbol: Symbol name

        Returns:
            True if signal was queued, False if rejected
        """
        # SOTA (Feb 2026): LAYER 2 DISABLED - Allow SHORT signals
        # SHORT trading enabled by user request
        # if self._is_live_mode and signal.signal_type == SignalType.SELL:
        #     self.logger.info(
        #         f"🚫 LIVE MODE: SHORT signal REJECTED in Shark Tank for {symbol} "
        #         f"(Long-Only Mode Active)"
        #     )
        #     self._blocked_short_signals += 1
        #     return False  # REJECT

        # SOTA FIX (Jan 2026): Single Batch Per Candle
        # Extract candle timestamp from signal
        candle_time = signal.generated_at if signal.generated_at else datetime.now()

        # SOTA FIX (Feb 2026): Normalize to 15-minute candle boundary
        # Different symbols may have microsecond differences in generated_at
        # for the same candle. Floor to 15-minute boundary for reliable dedup.
        candle_key = candle_time.replace(second=0, microsecond=0)
        candle_key = candle_key.replace(minute=(candle_key.minute // 15) * 15)

        with self._lock:
            # Check if we already processed this candle
            if self._last_candle_time and self._last_candle_time == candle_key:
                self.logger.debug(
                    f"⏭️ Duplicate candle {candle_time.strftime('%H:%M:%S')} - "
                    f"rejecting {symbol} (already processed)"
                )
                return False  # Reject - this candle was already processed

            # Only keep one signal per symbol (latest wins)
            self._pending_signals[symbol.upper()] = BatchedSignal(
                signal=signal,
                symbol=symbol.upper(),
                received_at=datetime.now(),
                confidence=signal.confidence
            )

            self.logger.info(
                f"🦈 Signal queued: {symbol} {signal.signal_type.value} "
                f"(confidence={signal.confidence:.2f}, pending={len(self._pending_signals)}, "
                f"candle={candle_time.strftime('%H:%M:%S')})"
            )

            # SOTA FIX (Jan 2026): Event-Driven Debounce Flush
            # When first signal arrives, start a short timer to collect peer signals.
            # This handles the async nature of 50 symbols closing candles slightly apart.
            if self._flush_task is None:
                self._current_candle_time = candle_key  # Track current candle (normalized)
                self.logger.info(
                    f"🦈 First signal received ({symbol}) for candle {candle_time.strftime('%H:%M:%S')}. "
                    f"Starting 2s batch timer..."
                )
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    # Unit tests and synchronous scripts call force_process() manually.
                    self._flush_task = None
                else:
                    self._flush_task = loop.create_task(self._debounce_flush())

            return True

    async def _debounce_flush(self):
        """
        Wait for other signals to arrive from the same candle event, then flush.
        SOTA: Simulates synchronous batch processing in an async system.

        FIX 3: Improved debounce logic to ensure only 1 batch per 15m candle.
        Prevents multiple timer triggers within the same candle period.

        CRITICAL FIX (Jan 2026): Mark candle as processed after batch completes.
        This prevents the same candle from being processed multiple times.
        """
        try:
            await asyncio.sleep(2.0)  # Wait 2s for all 50 symbols to finish calc

            # Check if this is still the active flush task
            # If another task already processed, skip to avoid duplicate batch
            if self._flush_task is None:
                self.logger.debug("⏭️ Debounce timer expired but task already cleared - skipping duplicate batch")
                return

            self.force_process()
        except Exception as e:
            self.logger.error(f"SharkTank debounce failed: {e}")
        finally:
            # CRITICAL FIX: Mark this candle as processed
            # This prevents new signals from the same candle from triggering another batch
            with self._lock:
                if self._current_candle_time:
                    self._last_candle_time = self._current_candle_time
                    self.logger.info(
                        f"✅ Candle {self._current_candle_time.strftime('%H:%M:%S')} marked as processed "
                        f"(prevents duplicate batches)"
                    )
                self._flush_task = None

    def _process_batch(self):
        """
        Process queued signals - rank and execute best N.

        SOTA: Matches backtest process_batch_signals() logic exactly.

        CRITICAL FIX (Jan 2026): Added filter to exclude signals from symbols
        that already have open positions or pending orders. This matches
        backtest ExecutionSimulator.process_batch_signals() behavior exactly.

        SOTA (Jan 2026): Layer 2 - Additional SHORT filter in batch processing.
        This catches any SHORT signals that bypassed Layer 1 filter.

        CRITICAL FIX (Jan 2026): Batch cooldown check to prevent multiple
        batches per 15-minute period. This matches backtest behavior where
        only 1 batch is processed per candle close.
        """
        if not self._pending_signals:
            return

        # ================================================================
        # SOTA (Feb 9, 2026): TRADING SCHEDULE — Dead Zone Check
        # Block ALL entries during configurable time windows.
        # This runs BEFORE any other logic to save CPU on dead hours.
        # ================================================================
        if self.circuit_breaker:
            now_utc = datetime.now(timezone.utc)
            is_blocked, reason = self.circuit_breaker.is_in_blocked_window(now_utc)
            if is_blocked:
                self.logger.info(
                    f"🚫 TRADING SCHEDULE: {reason}. "
                    f"Rejecting {len(self._pending_signals)} signals."
                )
                self.metrics['total_signals_rejected'] += len(self._pending_signals)
                self._pending_signals.clear()
                return
        # ================================================================

        # CRITICAL FIX (Jan 2026): Batch cooldown check
        # Prevents multiple batches per 15-minute period
        now = datetime.now()
        if self._last_batch_processed_time:
            time_since_last = (now - self._last_batch_processed_time).total_seconds()
            if time_since_last < self.batch_cooldown_seconds:
                remaining = self.batch_cooldown_seconds - time_since_last
                self.logger.info(
                    f"🚫 BATCH COOLDOWN: {time_since_last:.0f}s / {self.batch_cooldown_seconds}s. "
                    f"Deferring {len(self._pending_signals)} signals. "
                    f"Next batch in {remaining:.0f}s"
                )
                defer_until = self._last_batch_processed_time + timedelta(seconds=self.batch_cooldown_seconds)
                if self._cooldown_defer_until != defer_until:
                    self.metrics['batches_rejected_cooldown'] += 1  # Legacy metric name.
                    self.metrics['batches_deferred_cooldown'] += 1
                    self._cooldown_defer_until = defer_until
                return

        self._last_batch_time = datetime.now()

        # SOTA (Feb 2026): LAYER 2 DISABLED - Allow SHORT signals in batch processing
        # SHORT trading enabled per user request (Feb 6, 2026)
        # if self._is_live_mode:
        #     original_count = len(self._pending_signals)
        #     self._pending_signals = {
        #         s: bs for s, bs in self._pending_signals.items()
        #         if bs.signal.signal_type != SignalType.SELL
        #     }
        #     removed = original_count - len(self._pending_signals)
        #     if removed > 0:
        #         self.logger.info(
        #             f"🧹 Cleaned {removed} SHORT signals from batch queue (Long-Only enforcement)"
        #         )

        if not self._pending_signals:
            self.logger.info("🦈 Batch: All signals filtered out (Empty after clean)")
            return

        # ================================================================
        # SOTA FIX (Jan 2026): FILTER SIGNALS - MATCH BACKTEST EXACTLY
        # Backtest: candidates = [s for s in signals
        #                         if s.symbol not in self.positions
        #                         and s.symbol not in self.pending_orders]
        # ================================================================
        position_symbols: Set[str] = set()
        pending_symbols: Set[str] = set()

        # Get symbols with open positions
        if self._get_position_symbols_callback:
            try:
                position_symbols = self._get_position_symbols_callback()
            except Exception as e:
                self.logger.error(f"Failed to get position symbols: {e}")

        # Get symbols with pending orders (from LocalSignalTracker)
        if self._get_pending_orders_callback:
            try:
                pending_orders = self._get_pending_orders_callback()
                pending_symbols = {o.get('symbol', '').upper() for o in pending_orders if o.get('symbol')}
            except Exception as e:
                self.logger.error(f"Failed to get pending symbols: {e}")

        # Filter out signals from symbols with existing position/pending
        original_count = len(self._pending_signals)
        filtered_signals = {
            symbol: bs for symbol, bs in self._pending_signals.items()
            if symbol not in position_symbols
            and symbol not in pending_symbols
        }

        filtered_count = original_count - len(filtered_signals)
        if filtered_count > 0:
            filtered_list = [s for s in self._pending_signals.keys()
                           if s in position_symbols or s in pending_symbols]
            self.logger.info(
                f"🦈 FILTER: Removed {filtered_count} signals from symbols with existing position/pending: {filtered_list}"
            )

        # Use filtered signals for this batch
        self._pending_signals = filtered_signals

        if not self._pending_signals:
            self.logger.info("🦈 Batch: All signals filtered out (all have existing position/pending)")
            return
        # ================================================================
        # END FILTER LOGIC
        # ================================================================

        # ================================================================
        # SOTA (Feb 2026): SYMBOL QUALITY FILTER
        # Reject exotic/meme/low-liquidity symbols before ranking
        # ================================================================
        if self.symbol_quality_filter:
            quality_filtered = {}
            for sym, bs in self._pending_signals.items():
                try:
                    eligible, reason = self.symbol_quality_filter.is_eligible(
                        sym,
                        as_of=bs.signal.generated_at or bs.received_at,
                    )
                except TypeError:
                    eligible, reason = self.symbol_quality_filter.is_eligible(sym)
                if eligible:
                    quality_filtered[sym] = bs
                else:
                    self.logger.warning(
                        f"🚫 QUALITY FILTER: {sym} rejected - {reason}"
                    )
            rejected_count = len(self._pending_signals) - len(quality_filtered)
            if rejected_count > 0:
                self.logger.info(
                    f"🔍 Quality filter: {rejected_count} symbols rejected, "
                    f"{len(quality_filtered)} passed"
                )
            self._pending_signals = quality_filtered

            if not self._pending_signals:
                self.logger.info("🦈 Batch: All signals rejected by quality filter")
                return
        # ================================================================
        # END QUALITY FILTER
        # ================================================================

        # ================================================================
        # SOTA (Feb 9, 2026): CIRCUIT BREAKER — Per-Symbol Direction Filter
        # Block signals from symbols with consecutive losses or daily limit hit.
        # Institutional pattern: prevent revenge-trading on losing symbols.
        # ================================================================
        if self.circuit_breaker:
            now_utc = datetime.now(timezone.utc)
            cb_filtered = {}
            for sym, bs in self._pending_signals.items():
                signal_side = 'LONG' if bs.signal.signal_type == SignalType.BUY else 'SHORT'
                if self.circuit_breaker.is_blocked(sym, signal_side, now_utc):
                    reason = self.circuit_breaker.get_block_reason(sym, signal_side, now_utc)
                    self.logger.warning(
                        f"🛡️ CB BLOCK: {sym} {signal_side} rejected — {reason}"
                    )
                else:
                    cb_filtered[sym] = bs
            cb_rejected = len(self._pending_signals) - len(cb_filtered)
            if cb_rejected > 0:
                self.logger.info(
                    f"🛡️ Circuit Breaker: {cb_rejected} signals blocked, "
                    f"{len(cb_filtered)} passed"
                )
            self._pending_signals = cb_filtered

            if not self._pending_signals:
                self.logger.info("🦈 Batch: All signals blocked by Circuit Breaker")
                return
        # ================================================================
        # END CIRCUIT BREAKER FILTER
        # ================================================================

        # Get current position count
        current_positions = 0
        if self._get_open_positions_callback:
            current_positions = self._get_open_positions_callback()

        available_slots = max(0, self.max_positions - current_positions)

        if available_slots == 0:
            # SOTA FIX (Jan 2026): Only run recycling if enable_smart_recycling is True
            if not self.enable_smart_recycling:
                # When recycling is disabled, simply reject new signals when full
                self.logger.info(
                    f"🦈 Batch: No slots ({current_positions}/{self.max_positions}), "
                    f"recycling DISABLED. Discarding {len(self._pending_signals)} signals."
                )
                self._pending_signals.clear()
                return

            # SOTA (Jan 2026): SMART RECYCLING - Matches backtest ExecutionSimulator exactly
            # When slots are full, swap worst pending (lowest confidence) with best new (highest confidence)
            # This ensures we always have the "A-Team" in the tank.
            # NOTE: This can cause over-trading if enabled. Use with caution.

            # 0. Need callbacks to perform recycling
            if not (self._get_pending_orders_callback and self._cancel_order_callback):
                self.logger.info(
                    f"🦈 Batch: No slots ({current_positions}/{self.max_positions}), "
                    f"no recycling callbacks. Discarding {len(self._pending_signals)} signals."
                )
                self._pending_signals.clear()
                return

            pending_orders = self._get_pending_orders_callback()
            if not pending_orders:
                # All slots are open positions (no pending orders to recycle)
                self.logger.info(
                    f"🦈 Batch: All slots are positions (no pending orders to recycle). "
                    f"Discarding {len(self._pending_signals)} signals."
                )
                self._pending_signals.clear()
                return

            # 1. PROXIMITY SENTRY: Filter out pending orders that are "Close to Filling"
            current_prices = {}
            if self._get_current_prices_callback:
                current_prices = self._get_current_prices_callback()

            recyclable_candidates = []
            for order in pending_orders:
                is_locked = False
                symbol = order.get('symbol', '')
                target_price = order.get('target_price', order.get('entry_price', 0))
                current_price = current_prices.get(symbol)

                if current_price and target_price:
                    dist_pct = abs(current_price - target_price) / target_price if target_price > 0 else 1.0
                    if dist_pct < self.proximity_lock_pct:  # 0.2%
                        is_locked = True
                        self.logger.debug(f"🔒 LOCKED: {symbol} within {dist_pct*100:.2f}% of target")

                if not is_locked:
                    recyclable_candidates.append(order)

            if not recyclable_candidates:
                self.logger.info(
                    f"🦈 Batch: All pending orders LOCKED (near fill). "
                    f"Discarding {len(self._pending_signals)} signals."
                )
                self._pending_signals.clear()
                return

            # 2. Sort recyclable pending by confidence (ascending) - worst first
            sorted_pending = sorted(
                recyclable_candidates,
                key=lambda x: x.get('confidence', 0)
            )
            worst_pending = sorted_pending[0]
            worst_conf = worst_pending.get('confidence', 0)

            # 3. Filter new signals that are BETTER than worst pending (10% buffer)
            better_signals = [
                bs for bs in self._pending_signals.values()
                if bs.confidence > worst_conf * self.recycle_confidence_buffer  # 1.1 = 10% better
            ]

            if not better_signals:
                self.logger.info(
                    f"🦈 Batch: No signal beats worst pending ({worst_pending.get('symbol')} conf={worst_conf:.2f}). "
                    f"Discarding {len(self._pending_signals)} signals."
                )
                self._pending_signals.clear()
                return

            # 4. Sort better signals by confidence (descending) - best first
            better_signals.sort(key=lambda x: x.confidence, reverse=True)
            best_new = better_signals[0]

            # 5. SWAP: Kill worst pending, Place best new
            worst_symbol = worst_pending.get('symbol', '')
            self.logger.info(
                f"♻️ SMART RECYCLE: Killing {worst_symbol} (Conf: {worst_conf:.2f}) "
                f"for {best_new.symbol} (Conf: {best_new.confidence:.2f})"
            )

            # Cancel worst
            try:
                self._cancel_order_callback(worst_symbol)
            except Exception as e:
                self.logger.error(f"Failed to cancel {worst_symbol}: {e}")
                self._pending_signals.clear()
                return

            # Execute best
            if self._execute_callback:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._execute_async(best_new.signal))
                except RuntimeError:
                    self._execute_callback(best_new.signal)

            self._pending_signals.clear()
            return

        # SOTA: Check available margin before attempting orders
        available_margin = 0.0
        if self._get_available_margin_callback:
            available_margin = self._get_available_margin_callback()

        if available_margin < self.min_margin_required:
            self.logger.warning(
                f"🚫 Insufficient margin: ${available_margin:.2f} < ${self.min_margin_required:.2f}. "
                f"Skipping {len(self._pending_signals)} signals. Add funds to continue trading."
            )
            self._pending_signals.clear()
            return

        # Rank by confidence (highest first)
        candidates = list(self._pending_signals.values())
        candidates.sort(key=lambda x: x.confidence, reverse=True)

        self.logger.info(
            f"🦈 Processing batch: {len(candidates)} signals, "
            f"{available_slots} slots, ${available_margin:.2f} available"
        )

        # Execute top N - SOTA: Non-blocking execution
        executed_count = 0
        for batched in candidates[:available_slots]:
            if self._execute_callback:
                try:
                    self.logger.info(
                        f"🦈 Executing #{executed_count + 1}: {batched.symbol} "
                        f"(score={batched.confidence:.2f})"
                    )
                    # SOTA: Fire and forget - don't block event loop
                    # Use asyncio.to_thread for sync callbacks
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(self._execute_async(batched.signal))
                    except RuntimeError:
                        # No event loop - run synchronously
                        self._execute_callback(batched.signal)
                    executed_count += 1
                except Exception as e:
                    self.logger.error(f"Failed to execute {batched.symbol}: {e}")

        # Clear batch
        self._pending_signals.clear()

        # CRITICAL FIX (Jan 2026): Update last batch time and metrics
        self._last_batch_processed_time = now
        self._cooldown_defer_until = None
        self.metrics['batches_processed'] += 1
        self.metrics['total_signals_processed'] += executed_count

        self.logger.info(
            f"🦈 Batch complete: {executed_count}/{len(candidates)} signals queued. "
            f"Next batch allowed at {(now + timedelta(seconds=self.batch_cooldown_seconds)).strftime('%H:%M:%S')}"
        )

    async def _execute_async(self, signal):
        """Execute signal in background thread (non-blocking)."""
        try:
            self.logger.info(f"⚡ Async executing: {signal.symbol}")
            await asyncio.to_thread(self._execute_callback, signal)
            self.logger.info(f"✅ Async complete: {signal.symbol}")
        except Exception as e:
            self.logger.error(f"❌ Async execution failed: {signal.symbol} - {e}", exc_info=True)

    def force_process(self):
        """Force process current batch (called on timer or shutdown)."""
        with self._lock:
            self._process_batch()

    def get_pending_count(self) -> int:
        """Get number of signals waiting in batch."""
        return len(self._pending_signals)

    def get_blocked_short_count(self) -> int:
        """Get number of blocked SHORT signals this session (Layer 2)."""
        return self._blocked_short_signals

    def get_metrics(self) -> Dict:
        """Get batch processing metrics."""
        return {
            **self.metrics,
            'last_batch_time': self._last_batch_processed_time.isoformat()
                              if self._last_batch_processed_time else None,
            'cooldown_seconds': self.batch_cooldown_seconds
        }

    def get_status(self) -> Dict:
        """Get coordinator status for monitoring."""
        with self._lock:
            pending_list = [
                {
                    "symbol": bs.symbol,
                    "direction": bs.signal.signal_type.value,
                    "confidence": bs.confidence,
                    "queued_at": bs.received_at.isoformat()
                }
                for bs in self._pending_signals.values()
            ]

            return {
                "enabled": True,
                "max_positions": self.max_positions,
                "batch_interval_seconds": self.batch_interval,
                "pending_signals": len(pending_list),
                "pending_list": pending_list,
                "last_batch_time": self._last_batch_time.isoformat(),
                "metrics": self.get_metrics()
            }
