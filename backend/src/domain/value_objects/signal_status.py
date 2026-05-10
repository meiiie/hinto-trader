"""
Signal Status - Value Object for Signal Lifecycle

Defines the possible states of a trading signal through its lifecycle.
"""

from enum import Enum


class SignalStatus(Enum):
    """
    Signal lifecycle status transitions.

    Lifecycle:
        GENERATED → PENDING → EXECUTED
                  → EXPIRED (if TTL exceeded)
                  → REJECTED (if filtered)
                  → CANCELLED (if user/system cancelled)
    """

    GENERATED = "generated"   # Just created by SignalGenerator
    PENDING = "pending"       # Sent to frontend, awaiting action
    EXECUTED = "executed"     # Order created from this signal
    EXPIRED = "expired"       # TTL exceeded without action
    REJECTED = "rejected"     # Filtered by regime/hard filters
    CANCELLED = "cancelled"   # User or system cancelled

    @property
    def is_terminal(self) -> bool:
        """Check if this is a terminal state (no further transitions)."""
        return self in [
            SignalStatus.EXECUTED,
            SignalStatus.EXPIRED,
            SignalStatus.REJECTED,
            SignalStatus.CANCELLED
        ]

    @property
    def is_actionable(self) -> bool:
        """Check if signal can still be executed."""
        return self in [SignalStatus.GENERATED, SignalStatus.PENDING]

    def __str__(self) -> str:
        return self.value
