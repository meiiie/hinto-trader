"""
LocalSignalTracker - SOTA Institutional-Grade Signal Management

PATTERN: OMS-lite (Order Management System)

Flow:
    Signal Generated → Store locally → Price tick → Check trigger → MARKET execute

Benefits:
    - No zombie orders (signals are local, not on exchange)
    - Perfect state sync (single source of truth)
    - Identical behavior: Paper = Testnet = Live
    - No cancel API needed

Usage:
    tracker = LocalSignalTracker(...)
    tracker.add_signal(signal)        # Just stores locally
    tracker.on_price_update(sym, px)  # Called on each WebSocket tick
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Optional, Callable, Any
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class SignalDirection(Enum):
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass
class PendingSignal:
    """
    Represents a pending trading signal waiting for price trigger.

    NOT an exchange order - purely local tracking.
    """
    symbol: str
    direction: SignalDirection
    target_price: float
    stop_loss: float
    take_profit: float
    quantity: float
    leverage: int = 10
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None
    signal_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0  # SOTA: For Smart Recycling prioritization
    last_known_price: Optional[float] = None # SOTA: For Proximity Locking

    def __post_init__(self):
        # SOTA FIX (Jan 23, 2026): Default 50 minutes TTL
        # Prevents zombie orders while allowing reasonable fill time
        # If expires_at is None, it will be set by add_signal() based on ttl parameter
        if self.expires_at is None:
            pass  # expires_at will be set by add_signal() based on ttl parameter

    @property
    def is_expired(self) -> bool:
        """Check if signal has expired (timezone-aware)."""
        from datetime import timezone
        now = datetime.now(timezone.utc)
        expires = self.expires_at
        # Handle both aware and naive datetimes for backward compatibility
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return now > expires

    def should_trigger(self, current_price: float) -> bool:
        """
        Check if current price should trigger this signal.

        LONG: Trigger when price <= target (price dropped to entry)
        SHORT: Trigger when price >= target (price rose to entry)
        """
        if self.is_expired:
            return False

        if self.direction == SignalDirection.LONG:
            return current_price <= self.target_price
        else:  # SHORT
            return current_price >= self.target_price


class LocalSignalTracker:
    """
    SOTA Institutional-Grade Local Signal Tracker

    Replaces exchange-based LIMIT order management with local tracking.
    Executes MARKET orders when price conditions are met.

    Pattern: OMS-lite (Order Management System)
    Used by: Two Sigma, Citadel, Renaissance, Crypto Hedge Funds
    """

    def __init__(
        self,
        execute_callback: Optional[Callable] = None,
        max_pending: int = 10,
        default_ttl_minutes: int = 50,  # SOTA FIX (Jan 23, 2026): 50 minutes TTL - prevents zombie orders
        enable_recycling: bool = True,   # SOTA SYNC: Match backtest --zombie-killer (ON)
        # SOTA FIX (Jan 2026): Position check callback for defense in depth
        has_position_callback: Optional[Callable[[str], bool]] = None,
        # SOTA FIX (Jan 2026): Total slots callback - CRITICAL for max_positions enforcement
        # Returns: (current_positions_count, current_pending_count)
        get_total_slots_callback: Optional[Callable[[], tuple]] = None
    ):
        """
        Args:
            execute_callback: Called when signal triggers.
                              Signature: (signal: PendingSignal, current_price: float) -> bool
            max_pending: Maximum pending signals (matches max_positions)
            default_ttl_minutes: Time-to-live for pending signals
            enable_recycling: If True, replaces low-confidence signals when full.
            has_position_callback: Callback to check if symbol has open position (defense in depth)
            get_total_slots_callback: Callback to get (positions_count, pending_count) for slot enforcement
        """
        self.pending_signals: Dict[str, PendingSignal] = {}
        self.execute_callback = execute_callback
        self.max_pending = max_pending
        self.default_ttl_minutes = default_ttl_minutes
        self.enable_recycling = enable_recycling
        # SOTA FIX (Jan 2026): Position check callback
        self._has_position_callback = has_position_callback
        # SOTA FIX (Jan 2026): Total slots callback for max_positions enforcement
        self._get_total_slots_callback = get_total_slots_callback

        # Stats for monitoring
        self._signals_added = 0
        self._signals_triggered = 0
        self._signals_expired = 0
        self._signals_replaced = 0
        self._signals_blocked_by_position = 0  # SOTA: Track blocked signals
        self._signals_blocked_by_max_slots = 0  # SOTA: Track blocked by max slots

        # SOTA FIX (Jan 2026): Cooldown Tracker
        # Prevents rapid re-entry after SL (Churning)
        self._cooldown_tracker: Dict[str, datetime] = {}

        logger.info(f"📊 LocalSignalTracker initialized (max={max_pending}, ttl={default_ttl_minutes}min, recycling={enable_recycling})")

    def get_pending_signal(self, symbol: str) -> Optional[PendingSignal]:
        """SOTA: Retrieve pending signal for a symbol if it exists."""
        return self.pending_signals.get(symbol.upper())

    def set_cooldown(self, symbol: str, minutes: int = 30):
        """Set a cooldown period for a symbol (e.g., after SL)."""
        expiry = datetime.now() + timedelta(minutes=minutes)
        self._cooldown_tracker[symbol.upper()] = expiry
        logger.info(f"❄️ Cooldown set for {symbol.upper()} until {expiry.strftime('%H:%M:%S')} ({minutes}m)")

    def add_signal(
        self,
        symbol: str,
        direction: SignalDirection,
        target_price: float,
        stop_loss: float,
        take_profit: float,
        quantity: float,
        leverage: int = 10,
        ttl_minutes: Optional[int] = None,
        signal_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
        confidence: float = 0.0  # SOTA: New arg
    ) -> PendingSignal:
        """
        Add a pending signal for local tracking.

        SOTA SYNC (Jan 2026): IGNORE new signals for existing pending symbols.
        This matches backtest behavior where first entry at swing point = optimal.

        Rationale: First signal captures exact swing point. Later signals have
        worse entry prices as price has moved. Research shows replacing orders
        degrades execution quality.

        NO Binance API call - purely local storage!

        Returns:
            PendingSignal object, or None if ignored
        """
        symbol = symbol.upper()

        # SOTA FIX (Jan 2026): Cooldown Check
        # Prevents "Churning" where we re-enter same symbol immediately after SL.
        if symbol in self._cooldown_tracker:
            expiry = self._cooldown_tracker[symbol]
            if datetime.now() < expiry:
                logger.info(f"❄️ LocalSignalTracker: {symbol} is cooling down until {expiry.strftime('%H:%M:%S')}")
                return None
            else:
                # Expired, clean up
                del self._cooldown_tracker[symbol]

        # SOTA FIX (Jan 2026): DEFENSE IN DEPTH - Check if symbol has open position
        # This is a secondary check after SharkTank filter, to catch any edge cases
        # Matches backtest: if s.symbol not in self.positions
        if self._has_position_callback:
            try:
                if self._has_position_callback(symbol):
                    logger.info(
                        f"🚫 LocalSignalTracker: BLOCKING {symbol} signal - already has OPEN POSITION"
                    )
                    self._signals_blocked_by_position += 1
                    return None
            except Exception as e:
                logger.error(f"Position check callback failed: {e}")

        # SOTA SYNC: IGNORE new signals for symbols with existing pending
        # This matches profitable backtest behavior (first entry = best entry)
        if symbol in self.pending_signals:
            old_signal = self.pending_signals[symbol]
            logger.info(
                f"⏭️ LocalSignalTracker: IGNORING new {symbol} signal "
                f"(keeping existing target=${old_signal.target_price:.2f})"
            )
            return None  # Keep existing pending, ignore new signal

        # ════════════════════════════════════════════════════════════════════════
        # SOTA FIX (Jan 2026): Check TOTAL slots (positions + pending) vs max_positions
        # CRITICAL: This was the bug causing 8 slots when max=5!
        # Old logic: only checked len(pending_signals) >= max_pending
        # New logic: check (positions + pending) >= max_positions
        # ════════════════════════════════════════════════════════════════════════
        total_slots_used = len(self.pending_signals)  # Default: just pending
        positions_count = 0

        if self._get_total_slots_callback:
            try:
                positions_count, pending_count = self._get_total_slots_callback()
                total_slots_used = positions_count + pending_count
                logger.debug(f"📊 Slot check: {positions_count} positions + {pending_count} pending = {total_slots_used}/{self.max_pending}")
            except Exception as e:
                logger.error(f"get_total_slots_callback failed: {e}")
                total_slots_used = len(self.pending_signals)

        # Check max slots (positions + pending)
        if total_slots_used >= self.max_pending:
            # SOTA: SMART RECYCLING (Jan 2026) -> Only if enabled
            if self.enable_recycling:
                # SOTA: PROXIMITY SENTRY implementation
                # Filter out signals that are "Close to Filling" (within 0.2%)
                # These are "Locked" and should NOT be recycled.

                recyclable_candidates = []

                for s in self.pending_signals.values():
                    # Calculate proximity if we have price data
                    is_locked = False
                    # SOTA: Ensure we use the latest available price
                    price_to_check = s.last_known_price

                    if price_to_check and s.target_price > 0:
                        dist_pct = abs(price_to_check - s.target_price) / s.target_price
                        if dist_pct < 0.002:  # 0.2% proximity
                            is_locked = True
                    else:
                        # SOTA SAFETY: If no price known, assume NOT locked (recyclable)
                        # Unless it was just added (less than 1 min old), then protect it
                        if (datetime.now() - s.created_at).total_seconds() < 60:
                             is_locked = True

                    if not is_locked:
                        recyclable_candidates.append(s)

                if not recyclable_candidates:
                    logger.warning(
                        f"⚠️ Max slots ({total_slots_used}/{self.max_pending}) reached. "
                        f"All signals are LOCKED (close to fill). Ignoring {symbol}."
                    )
                    self._signals_blocked_by_max_slots += 1
                    return None

                # 1. Identify worst pending (lowest confidence) among RECYCLABLE
                sorted_pending = sorted(
                    recyclable_candidates,
                    key=lambda s: s.confidence
                )
                worst_pending = sorted_pending[0]

                # 2. Check if new signal is significantly better (10% buffer)
                # SOTA FIX: Use explicit 'confidence' argument first, then metadata fallback
                new_confidence = confidence or (metadata.get('confidence', 0) if metadata else 0)

                if new_confidence > worst_pending.confidence * 1.1:
                    logger.info(
                        f"♻️ SMART RECYCLE: Replacing {worst_pending.symbol} (Conf:{worst_pending.confidence:.2f}) "
                        f"with {symbol} (Conf:{new_confidence:.2f})"
                    )
                    del self.pending_signals[worst_pending.symbol]
                    self._signals_replaced += 1
                else:
                    logger.warning(
                        f"⚠️ Max slots ({total_slots_used}/{self.max_pending}) reached. "
                        f"New {symbol} ({new_confidence:.2f}) not better than worst {worst_pending.symbol} ({worst_pending.confidence:.2f}). Ignored."
                    )
                    self._signals_blocked_by_max_slots += 1
                    return None
            else:
                # Legacy behavior: Reject new signal if full
                logger.warning(f"⚠️ Max slots ({total_slots_used}/{self.max_pending}) reached. Recycling DISABLED. Ignoring {symbol}.")
                self._signals_blocked_by_max_slots += 1
                return None

        # Create pending signal
        ttl = ttl_minutes if ttl_minutes is not None else self.default_ttl_minutes

        # SOTA FIX (Jan 23, 2026): Handle TTL=0 as GTC (Good Till Cancel)
        if ttl == 0:
            # GTC: Set expiry to far future (100 years)
            expires_at = datetime.now() + timedelta(days=36500)
        else:
            expires_at = datetime.now() + timedelta(minutes=ttl)

        signal = PendingSignal(
            symbol=symbol,
            direction=direction,
            target_price=target_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            quantity=quantity,
            leverage=leverage,
            expires_at=expires_at,
            signal_id=signal_id,
            metadata=metadata or {},
            confidence=confidence or (metadata.get('confidence', 0) if metadata else 0)
        )

        self.pending_signals[symbol] = signal
        self._signals_added += 1

        ttl_display = "GTC (unlimited)" if ttl == 0 else f"{ttl}min"
        logger.info(
            f"📋 LocalSignalTracker: Added {direction.value} {symbol} "
            f"target=${target_price:.4f} SL=${stop_loss:.4f} TP=${take_profit:.4f} "
            f"(expires: {ttl_display})"
        )

        return signal

    def on_price_update(self, symbol: str, current_price: float) -> Optional[PendingSignal]:
        """
        Called on each WebSocket price tick.

        Checks if price conditions are met for any pending signals.
        If triggered, executes via callback and removes from pending.

        Returns:
            Triggered signal if any, None otherwise
        """
        symbol = symbol.upper()

        if symbol not in self.pending_signals:
            return None

        signal = self.pending_signals[symbol]

        # SOTA: Update last known price for Proximity Locking logic
        signal.last_known_price = current_price

        # Check expiry
        if signal.is_expired:
            logger.info(f"⏰ Signal expired: {symbol} (was target=${signal.target_price:.4f})")
            del self.pending_signals[symbol]
            self._signals_expired += 1
            return None

        # Check trigger condition
        if signal.should_trigger(current_price):
            logger.info(
                f"🎯 SIGNAL TRIGGERED: {signal.direction.value} {symbol} "
                f"target=${signal.target_price:.4f} current=${current_price:.4f}"
            )

            # Execute via callback
            if self.execute_callback:
                try:
                    success = self.execute_callback(signal, current_price)
                    if success:
                        self._signals_triggered += 1
                except Exception as e:
                    logger.error(f"❌ Execute callback failed: {e}")

            # Remove from pending
            del self.pending_signals[symbol]
            return signal

        return None

    def on_candle_close(self, symbol: str, candle_low: float, candle_high: float,
                        pessimistic_buffer: float = 0.001) -> Optional[PendingSignal]:
        """
        SOTA (Jan 2026): Check fills using closed candle HIGH/LOW.

        This ensures Live trading does not miss fills that Backtest would catch.
        Uses same pessimistic fill model as backtest for parity.

        Args:
            symbol: Trading pair
            candle_low: Lowest price in the closed candle
            candle_high: Highest price in the closed candle
            pessimistic_buffer: Required overshoot (default 0.1% = 0.001)

        Returns:
            Triggered signal if any, None otherwise
        """
        symbol = symbol.upper()

        if symbol not in self.pending_signals:
            return None

        signal = self.pending_signals[symbol]

        # Check expiry
        if signal.is_expired:
            logger.info(f"⏰ Signal expired: {symbol} (was target=${signal.target_price:.4f})")
            del self.pending_signals[symbol]
            self._signals_expired += 1
            return None

        # SOTA: Pessimistic Fill Model (matches backtest)
        # Require price to go BEYOND target by buffer to confirm fill
        target = signal.target_price
        buffer = target * pessimistic_buffer

        is_fill = False
        fill_price = 0.0

        if signal.direction == SignalDirection.LONG:
            # LONG: Candle LOW must go BELOW (target - buffer)
            fill_threshold = target - buffer
            if candle_low < fill_threshold:
                is_fill = True
                fill_price = target  # Fill at target (optimistic execution)
        else:  # SHORT
            # SHORT: Candle HIGH must go ABOVE (target + buffer)
            fill_threshold = target + buffer
            if candle_high > fill_threshold:
                is_fill = True
                fill_price = target  # Fill at target

        if is_fill:
            logger.info(
                f"🎯 CANDLE FILL: {signal.direction.value} {symbol} "
                f"target=${target:.4f} low=${candle_low:.4f} high=${candle_high:.4f}"
            )

            # Execute via callback
            if self.execute_callback:
                try:
                    success = self.execute_callback(signal, fill_price)
                    if success:
                        self._signals_triggered += 1
                except Exception as e:
                    logger.error(f"❌ Execute callback failed: {e}")

            # Remove from pending
            del self.pending_signals[symbol]
            return signal

        return None

    def remove_signal(self, symbol: str) -> bool:
        """Manually remove a pending signal."""
        symbol = symbol.upper()
        if symbol in self.pending_signals:
            del self.pending_signals[symbol]
            logger.info(f"🗑️ Signal removed: {symbol}")
            return True
        return False

    def cancel_signal(self, symbol: str) -> bool:
        """Cancel a pending signal (alias for remove_signal for SharkTank compatibility)."""
        logger.info(f"♻️ Cancel signal called for: {symbol}")
        return self.remove_signal(symbol)

    def clear_all(self):
        """Clear all pending signals."""
        count = len(self.pending_signals)
        self.pending_signals.clear()
        logger.info(f"🧹 Cleared all {count} pending signals")

    def get_signal(self, symbol: str) -> Optional[PendingSignal]:
        """Get pending signal for symbol."""
        return self.pending_signals.get(symbol.upper())

    def get_all_pending(self) -> Dict[str, PendingSignal]:
        """Get all pending signals."""
        return self.pending_signals.copy()

    def cleanup_expired(self) -> int:
        """Remove all expired signals. Returns count removed."""
        expired = [s for s in self.pending_signals if self.pending_signals[s].is_expired]
        for symbol in expired:
            del self.pending_signals[symbol]
            self._signals_expired += 1
        if expired:
            logger.info(f"🧹 Cleaned up {len(expired)} expired signals")
        return len(expired)

    def get_stats(self) -> Dict[str, int]:
        """Get tracker statistics."""
        return {
            "pending": len(self.pending_signals),
            "added": self._signals_added,
            "triggered": self._signals_triggered,
            "expired": self._signals_expired,
            "replaced": self._signals_replaced,
            "blocked_by_position": self._signals_blocked_by_position,
            "blocked_by_max_slots": self._signals_blocked_by_max_slots  # SOTA: New stat
        }

    def __len__(self) -> int:
        return len(self.pending_signals)

    def __repr__(self) -> str:
        return f"LocalSignalTracker(pending={len(self)}, stats={self.get_stats()})"
