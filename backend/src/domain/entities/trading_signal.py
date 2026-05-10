"""
Trading Signal Entity

Defines the structure and types of trading signals with full lifecycle tracking.
Moved from application layer to domain layer to avoid circular dependencies.

Enhanced with Signal Lifecycle fields:
- id: Unique identifier (UUID)
- status: Current lifecycle status
- Timestamps for GENERATED → PENDING → EXECUTED transitions
- order_id: Link to created order
- outcome: Trade result tracking
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Any
import uuid

from ..value_objects.signal_status import SignalStatus


class SignalType(Enum):
    """Trading signal types"""
    BUY = "buy"
    SELL = "sell"
    NEUTRAL = "neutral"


class ConfidenceLevel(Enum):
    """Confidence level categories"""
    HIGH = "high"      # >= 80%
    MEDIUM = "medium"  # 65-79%
    LOW = "low"        # < 65%


class SignalPriority(Enum):
    """Signal priority levels"""
    HIGH = "high"      # Immediate action (SFP, Breakout)
    MEDIUM = "medium"  # Normal action (Pullback)
    LOW = "low"        # Low confidence


@dataclass
class TradingSignal:
    """
    Trading signal with full lifecycle tracking.

    Core Attributes:
        signal_type: Type of signal (BUY, SELL, NEUTRAL)
        priority: Signal priority (HIGH, MEDIUM, LOW)
        confidence: Confidence level (0.0 to 1.0)
        price: Price at signal generation
        indicators: Dict of indicator values
        reasons: List of reasons for the signal

    Trade Attributes:
        entry_price: Entry price for the trade
        tp_levels: Take profit levels dict with tp1, tp2, tp3
        stop_loss: Stop loss price
        position_size: Position size
        risk_reward_ratio: Risk/reward ratio

    Lifecycle Attributes (NEW):
        id: Unique identifier (UUID)
        status: Current lifecycle status
        generated_at: When signal was created
        pending_at: When signal was shown to user
        executed_at: When order was created
        expired_at: When signal expired
        order_id: Link to created order
        outcome: Trade result tracking
    """
    # Core fields
    symbol: str  # SOTA FIX: Signal must know its symbol
    signal_type: SignalType
    confidence: float
    price: float
    priority: SignalPriority = field(default=SignalPriority.MEDIUM) # Default to Medium
    indicators: Dict[str, Any] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)

    # Trade Attributes
    entry_price: Optional[float] = None
    is_limit_order: bool = False # SOTA: Support Limit Orders
    tp_levels: Optional[Dict[str, float]] = None  # {'tp1': price, 'tp2': price, 'tp3': price}
    stop_loss: Optional[float] = None
    position_size: Optional[float] = None
    risk_reward_ratio: Optional[float] = None

    # Lifecycle fields (NEW)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: SignalStatus = field(default=SignalStatus.GENERATED)
    generated_at: datetime = field(default_factory=datetime.now)
    pending_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    expired_at: Optional[datetime] = None
    order_id: Optional[str] = None
    outcome: Optional[Dict[str, Any]] = None

    # Backward compatibility: timestamp property
    @property
    def timestamp(self) -> datetime:
        """Backward compatibility: returns generated_at."""
        return self.generated_at

    @property
    def confidence_level(self) -> 'ConfidenceLevel':
        """Get confidence level based on confidence score"""
        if self.confidence >= 0.80:
            return ConfidenceLevel.HIGH
        elif self.confidence >= 0.65:
            return ConfidenceLevel.MEDIUM
        else:
            return ConfidenceLevel.LOW

    @property
    def execution_latency_ms(self) -> Optional[float]:
        """Time from generation to execution in milliseconds."""
        if self.generated_at and self.executed_at:
            # SOTA FIX: Handle naive/aware datetime mismatch safely
            gen_at = self.generated_at
            exec_at = self.executed_at
            # Make both naive for safe comparison (remove tzinfo if present)
            if gen_at.tzinfo is not None:
                gen_at = gen_at.replace(tzinfo=None)
            if exec_at.tzinfo is not None:
                exec_at = exec_at.replace(tzinfo=None)
            delta = exec_at - gen_at
            return delta.total_seconds() * 1000
        return None

    @property
    def is_actionable(self) -> bool:
        """Check if signal can still be executed."""
        return self.status in [SignalStatus.GENERATED, SignalStatus.PENDING]

    # Lifecycle methods
    def mark_pending(self) -> None:
        """Mark signal as shown to user."""
        self.status = SignalStatus.PENDING
        self.pending_at = datetime.now(timezone.utc)

    def mark_executed(self, order_id: str) -> None:
        """Mark signal as executed with order link."""
        self.status = SignalStatus.EXECUTED
        self.executed_at = datetime.now(timezone.utc)
        self.order_id = order_id

    def mark_expired(self) -> None:
        """Mark signal as expired."""
        self.status = SignalStatus.EXPIRED
        self.expired_at = datetime.now(timezone.utc)

    def mark_rejected(self, reason: str) -> None:
        """Mark signal as rejected by filter."""
        self.status = SignalStatus.REJECTED
        self.reasons.append(f"REJECTED: {reason}")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for API response."""
        return {
            "id": self.id,
            "symbol": self.symbol,  # SOTA FIX: Include symbol in JSON
            "signal_type": self.signal_type.value,
            "priority": self.priority.value,
            "status": self.status.value,
            "confidence": self.confidence,
            "confidence_level": self.confidence_level.value,
            "price": self.price,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "tp_levels": self.tp_levels,
            "position_size": self.position_size,
            "risk_reward_ratio": self.risk_reward_ratio,
            "indicators": self.indicators,
            "reasons": self.reasons,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "pending_at": self.pending_at.isoformat() if self.pending_at else None,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
            "expired_at": self.expired_at.isoformat() if self.expired_at else None,
            "order_id": self.order_id,
            "execution_latency_ms": self.execution_latency_ms,
            "outcome": self.outcome
        }

    def __str__(self) -> str:
        """String representation"""
        emoji = "🟢" if self.signal_type == SignalType.BUY else "🔴" if self.signal_type == SignalType.SELL else "⚪"
        return (
            f"{emoji} {self.signal_type.value.upper()} Signal "
            f"(Confidence: {self.confidence:.0%}) at ${self.price:,.2f}"
        )
