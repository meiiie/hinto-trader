"""
Signal Lifecycle Service - Application Layer

Manages the full lifecycle of trading signals:
1. Assign IDs and persist new signals
2. Track status transitions
3. Link signals to orders
4. Expire stale signals
5. Provide query interface for history

Integration point: Layer -1 (before Regime Filter)
"""

import logging
from typing import Optional, List
from datetime import datetime, timedelta

from src.domain.entities.trading_signal import TradingSignal
from src.domain.value_objects.signal_status import SignalStatus
from src.domain.repositories.i_signal_repository import ISignalRepository


class SignalLifecycleService:
    """
    Manages the full lifecycle of trading signals.

    Responsibilities:
    1. Assign IDs and persist new signals
    2. Track status transitions
    3. Link signals to orders
    4. Expire stale signals
    5. Provide query interface for history

    Usage:
        service = SignalLifecycleService(signal_repository)

        # Register new signal
        signal = service.register_signal(new_signal)

        # Mark as pending when shown
        service.mark_pending(signal.id)

        # Mark as executed when order created
        service.mark_executed(signal.id, order_id)

        # Get history
        history = service.get_signal_history(days=7)
    """

    # Signal TTL before expiration (5 minutes default)
    DEFAULT_TTL_SECONDS = 300

    def __init__(
        self,
        signal_repository: ISignalRepository,
        ttl_seconds: int = DEFAULT_TTL_SECONDS
    ):
        """
        Initialize lifecycle service.

        Args:
            signal_repository: Repository for signal persistence
            ttl_seconds: Time-to-live before signals expire
        """
        self.repo = signal_repository
        self.ttl_seconds = ttl_seconds
        self.logger = logging.getLogger(__name__)

        self.logger.info(
            f"SignalLifecycleService initialized (TTL: {ttl_seconds}s)"
        )

    def register_signal(self, signal: TradingSignal) -> TradingSignal:
        """
        Register a newly generated signal.

        - Ensures ID is assigned
        - Sets status to GENERATED
        - Persists to repository

        Args:
            signal: Signal to register

        Returns:
            Registered signal with ID
        """
        # Ensure ID is assigned
        if not signal.id:
            import uuid
            signal.id = str(uuid.uuid4())

        # Set initial status
        signal.status = SignalStatus.GENERATED
        if not signal.generated_at:
            signal.generated_at = datetime.now()

        # Persist
        self.repo.save(signal)

        self.logger.info(
            f"📝 Signal registered: {signal.id[:8]}... "
            f"{signal.signal_type.value.upper()} @ ${signal.price:,.2f}"
        )

        return signal

    def mark_pending(self, signal_id: str) -> Optional[TradingSignal]:
        """
        Mark signal as pending (shown to user).

        Args:
            signal_id: UUID of the signal

        Returns:
            Updated signal or None if not found
        """
        signal = self.repo.get_by_id(signal_id)

        if signal and signal.is_actionable:
            signal.mark_pending()
            self.repo.update(signal)

            self.logger.info(f"⏳ Signal {signal_id[:8]}... → PENDING")
            return signal

        return None

    def mark_executed(
        self,
        signal_id: str,
        order_id: str
    ) -> Optional[TradingSignal]:
        """
        Mark signal as executed and link to order.

        Args:
            signal_id: UUID of the signal
            order_id: UUID of the created order

        Returns:
            Updated signal or None if not found
        """
        signal = self.repo.get_by_id(signal_id)

        if signal and signal.is_actionable:
            signal.mark_executed(order_id)
            self.repo.update(signal)

            latency = signal.execution_latency_ms or 0
            self.logger.info(
                f"✅ Signal {signal_id[:8]}... → EXECUTED "
                f"(order: {order_id[:8]}..., latency: {latency:.0f}ms)"
            )
            return signal

        return None

    def mark_expired(self, signal_id: str) -> Optional[TradingSignal]:
        """
        Mark signal as expired.

        Args:
            signal_id: UUID of the signal

        Returns:
            Updated signal or None if not found
        """
        signal = self.repo.get_by_id(signal_id)

        if signal and signal.is_actionable:
            signal.mark_expired()
            self.repo.update(signal)

            self.logger.info(f"⏰ Signal {signal_id[:8]}... → EXPIRED")
            return signal

        return None

    def expire_stale_signals(self) -> int:
        """
        Expire signals older than TTL.

        Returns:
            Number of signals expired
        """
        count = self.repo.expire_old_pending(self.ttl_seconds)

        if count > 0:
            self.logger.info(f"⏰ Expired {count} stale signals")

        return count

    def get_signal_by_id(self, signal_id: str) -> Optional[TradingSignal]:
        """
        Get signal by ID.

        Args:
            signal_id: UUID of the signal

        Returns:
            Signal or None if not found
        """
        return self.repo.get_by_id(signal_id)

    def get_signal_for_order(self, order_id: str) -> Optional[TradingSignal]:
        """
        Get the signal that created an order.

        Args:
            order_id: UUID of the order

        Returns:
            Signal or None if not found
        """
        return self.repo.get_by_order_id(order_id)

    def get_pending_signals(self) -> List[TradingSignal]:
        """Get all pending signals."""
        return self.repo.get_by_status(SignalStatus.PENDING)

    def get_pending_count(self) -> int:
        """Get count of pending signals."""
        return self.repo.get_pending_count()

    def get_signal_history(
        self,
        days: int = 7,
        limit: int = 100,
        offset: int = 0
    ) -> List[TradingSignal]:
        """
        Get signal history for the last N days.

        Args:
            days: Number of days to look back
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of signals
        """
        start_date = datetime.now() - timedelta(days=days)
        return self.repo.get_history(
            start_date=start_date,
            limit=limit,
            offset=offset
        )

    def get_total_count(self, days: int = 7) -> int:
        """
        Get total count of signals in the last N days.

        Args:
            days: Number of days to look back

        Returns:
            Total count
        """
        start_date = datetime.now() - timedelta(days=days)
        return self.repo.get_total_count(start_date=start_date)

    def get_filtered_signal_history(
        self,
        days: int = 7,
        limit: int = 100,
        offset: int = 0,
        symbol: Optional[str] = None,
        signal_type: Optional[str] = None,
        status: Optional[str] = None,
        min_confidence: Optional[float] = None
    ) -> List[TradingSignal]:
        """
        Get filtered signal history for analysis.

        SOTA Phase 25: Server-side filtering for signal research.

        Args:
            days: Number of days to look back
            limit: Maximum number of results
            offset: Number of results to skip
            symbol: Filter by trading symbol (e.g., BTCUSDT)
            signal_type: Filter by type (buy or sell)
            status: Filter by status (generated, pending, executed, expired)
            min_confidence: Minimum confidence threshold

        Returns:
            List of filtered signals
        """
        start_date = datetime.now() - timedelta(days=days)
        return self.repo.get_filtered_history(
            start_date=start_date,
            limit=limit,
            offset=offset,
            symbol=symbol,
            signal_type=signal_type,
            status=status,
            min_confidence=min_confidence
        )

    def get_filtered_count(
        self,
        days: int = 7,
        symbol: Optional[str] = None,
        signal_type: Optional[str] = None,
        status: Optional[str] = None,
        min_confidence: Optional[float] = None
    ) -> int:
        """
        Get total count of filtered signals.

        Args:
            days: Number of days to look back
            symbol: Filter by symbol
            signal_type: Filter by type
            status: Filter by status
            min_confidence: Minimum confidence

        Returns:
            Total count matching filters
        """
        start_date = datetime.now() - timedelta(days=days)
        return self.repo.get_filtered_count(
            start_date=start_date,
            symbol=symbol,
            signal_type=signal_type,
            status=status,
            min_confidence=min_confidence
        )

    def update_signal_outcome(
        self,
        signal_id: str,
        outcome: dict
    ) -> Optional[TradingSignal]:
        """
        Update signal with trade outcome.

        Args:
            signal_id: UUID of the signal
            outcome: Dict with pnl, pnl_pct, exit_reason, etc.

        Returns:
            Updated signal or None if not found
        """
        signal = self.repo.get_by_id(signal_id)

        if signal:
            signal.outcome = outcome
            self.repo.update(signal)

            pnl = outcome.get('pnl', 0)
            emoji = "💰" if pnl > 0 else "📉"
            self.logger.info(
                f"{emoji} Signal {signal_id[:8]}... outcome: "
                f"PnL ${pnl:+.2f}"
            )
            return signal

        return None
