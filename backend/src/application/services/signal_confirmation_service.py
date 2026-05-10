"""
Signal Confirmation Service - SOTA Pattern

Prevents whipsaw by requiring multiple consecutive signals
in the same direction before execution.

Following institutional trading practices from:
- Binance Futures Bot Framework
- Two Sigma signal validation patterns
- ICT/SMC confirmation methodology

Created: 2025-12-31
Purpose: Fix whipsaw problem causing 91% SIGNAL_REVERSAL exits
"""

from datetime import datetime
from typing import Dict, Optional
from dataclasses import dataclass
from src.domain.entities.trading_signal import TradingSignal, SignalType
import logging

logger = logging.getLogger(__name__)


@dataclass
class PendingSignal:
    """Track pending signal confirmation state."""
    signal: TradingSignal
    first_seen: datetime
    confirmation_count: int
    symbol: str


class SignalConfirmationService:
    """
    SOTA: Require N consecutive bars with same signal direction.

    Default: 2 bars confirmation (can be configured)

    This prevents:
    - Single-bar noise signals
    - Rapid BUY/SELL flipping
    - Whipsaw during ranging markets

    How it works:
    1. First signal of a direction -> stored as "pending"
    2. Same signal 1+ minutes later -> increment confirmation count
    3. When count >= min_confirmations -> signal confirmed and returned
    4. If opposite signal received -> reset with new direction
    5. If timeout exceeded -> reset

    Example flow:
        t=0:  BUY signal -> pending (1/2 confirmations)
        t=1m: BUY signal -> confirmed! (2/2) -> execute trade

    vs Whipsaw prevented:
        t=0:  BUY signal -> pending (1/2)
        t=1m: SELL signal -> reset to SELL pending (1/2)
        t=2m: BUY signal -> reset to BUY pending (1/2)
        -> No trades executed due to oscillation
    """

    def __init__(
        self,
        min_confirmations: int = 2,
        max_wait_seconds: int = 180  # 3 minutes
    ):
        """
        Initialize service.

        Args:
            min_confirmations: Number of consecutive same-direction signals required
            max_wait_seconds: Maximum time to wait for confirmation before reset
        """
        self.min_confirmations = min_confirmations
        self.max_wait_seconds = max_wait_seconds
        self._pending: Dict[str, PendingSignal] = {}

        logger.info(
            f"📋 SignalConfirmationService initialized: "
            f"min_confirmations={min_confirmations}, "
            f"max_wait={max_wait_seconds}s"
        )

    def process_signal(
        self,
        symbol: str,
        signal: TradingSignal
    ) -> Optional[TradingSignal]:
        """
        Process incoming signal and return confirmed signal if valid.

        Args:
            symbol: Trading symbol
            signal: New signal to process

        Returns:
            Confirmed TradingSignal if validation passes, None otherwise
        """
        key = symbol.lower()
        now = datetime.now()

        # Skip NEUTRAL signals
        if signal.signal_type == SignalType.NEUTRAL:
            return None


        # Check if we have an existing pending signal
        if key not in self._pending:
            # First signal - start confirmation window
            self._pending[key] = PendingSignal(
                signal=signal,
                first_seen=now,
                confirmation_count=1,
                symbol=symbol
            )
            logger.info(
                f"📋 {symbol}: Signal {signal.signal_type.value.upper()} received, "
                f"awaiting confirmation (1/{self.min_confirmations})"
            )
            return None  # Don't execute yet

        pending = self._pending[key]

        # Check timeout
        elapsed = (now - pending.first_seen).total_seconds()
        if elapsed > self.max_wait_seconds:
            # Timeout - reset with new signal
            self._pending[key] = PendingSignal(
                signal=signal,
                first_seen=now,
                confirmation_count=1,
                symbol=symbol
            )
            logger.info(
                f"⏰ {symbol}: Confirmation timeout after {elapsed:.0f}s, "
                f"resetting with {signal.signal_type.value.upper()} signal"
            )
            return None

        # Check if same direction
        if signal.signal_type == pending.signal.signal_type:
            # Same direction - increment confirmation count
            pending.confirmation_count += 1
            # Update with latest signal (better entry price)
            pending.signal = signal

            logger.info(
                f"✅ {symbol}: Signal {signal.signal_type.value.upper()} confirmed "
                f"({pending.confirmation_count}/{self.min_confirmations})"
            )

            if pending.confirmation_count >= self.min_confirmations:
                # CONFIRMED! Return the latest signal (best entry)
                confirmed_signal = signal
                del self._pending[key]  # Clear pending

                logger.info(
                    f"🎯 {symbol}: SIGNAL CONFIRMED after "
                    f"{pending.confirmation_count} confirmations! "
                    f"Direction: {confirmed_signal.signal_type.value.upper()}"
                )
                return confirmed_signal
        else:
            # Direction changed - reset with new signal
            old_direction = pending.signal.signal_type.value.upper()
            new_direction = signal.signal_type.value.upper()

            self._pending[key] = PendingSignal(
                signal=signal,
                first_seen=now,
                confirmation_count=1,
                symbol=symbol
            )
            logger.info(
                f"🔄 {symbol}: Direction changed from {old_direction} to {new_direction}, "
                f"resetting confirmation (1/{self.min_confirmations})"
            )

        return None  # Not confirmed yet

    def clear_pending(self, symbol: str) -> None:
        """Clear pending confirmation for a symbol."""
        key = symbol.lower()
        if key in self._pending:
            del self._pending[key]
            logger.info(f"🗑️ {symbol}: Pending confirmation cleared")

    def clear_all(self) -> None:
        """Clear all pending confirmations."""
        self._pending.clear()
        logger.info("🗑️ All pending confirmations cleared")

    def get_pending_status(self, symbol: str) -> Optional[Dict]:
        """Get pending confirmation status for a symbol."""
        key = symbol.lower()
        if key in self._pending:
            p = self._pending[key]
            elapsed = (datetime.now() - p.first_seen).total_seconds()
            return {
                "symbol": symbol,
                "direction": p.signal.signal_type.value,
                "confirmations": p.confirmation_count,
                "required": self.min_confirmations,
                "first_seen": p.first_seen.isoformat(),
                "elapsed_seconds": round(elapsed, 1),
                "timeout_in": round(max(0, self.max_wait_seconds - elapsed), 1)
            }
        return None

    def get_all_pending(self) -> Dict[str, Dict]:
        """Get all pending confirmation statuses."""
        result = {}
        for key in self._pending:
            status = self.get_pending_status(key)
            if status:
                result[key] = status
        return result
