"""
State Models - Domain Layer

Data models for state machine operations including:
- StateTransition: Record of state changes
- PersistedState: State persistence for recovery
- FilterResult: Result of hard filter checks
- WarmupResult: Result of cold start warm-up
- RecoveryResult: Result of state recovery on startup
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List
from enum import Enum

from ..state_machine import SystemState


@dataclass
class StateTransition:
    """
    Record of a state transition.

    Used for:
    - Audit logging
    - EventBus publishing
    - Debugging state flow

    Attributes:
        from_state: Previous state
        to_state: New state
        reason: Human-readable reason for transition
        timestamp: When transition occurred
        order_id: Associated order ID (if applicable)
        position_id: Associated position ID (if applicable)
    """
    from_state: SystemState
    to_state: SystemState
    reason: str
    timestamp: datetime = field(default_factory=datetime.now)
    order_id: Optional[str] = None
    position_id: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'from_state': self.from_state.name,
            'to_state': self.to_state.name,
            'reason': self.reason,
            'timestamp': self.timestamp.isoformat(),
            'order_id': self.order_id,
            'position_id': self.position_id
        }

    def __str__(self) -> str:
        return f"{self.from_state.name} → {self.to_state.name}: {self.reason}"


@dataclass
class PersistedState:
    """
    Persisted state for recovery after restart.

    Stored in database/file to allow bot to resume
    from last known state after crash or restart.

    Attributes:
        state: Current system state
        order_id: Active order ID (if in ENTRY_PENDING)
        position_id: Active position ID (if in IN_POSITION)
        cooldown_remaining: Candles remaining in cooldown
        timestamp: When state was persisted
        symbol: Trading symbol
    """
    state: SystemState
    timestamp: datetime = field(default_factory=datetime.now)
    order_id: Optional[str] = None
    position_id: Optional[str] = None
    cooldown_remaining: int = 0
    symbol: str = "btcusdt"

    def to_dict(self) -> dict:
        """Convert to dictionary for persistence."""
        return {
            'state': self.state.name,
            'timestamp': self.timestamp.isoformat(),
            'order_id': self.order_id,
            'position_id': self.position_id,
            'cooldown_remaining': self.cooldown_remaining,
            'symbol': self.symbol
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'PersistedState':
        """Create from dictionary (loaded from storage)."""
        return cls(
            state=SystemState[data['state']],
            timestamp=datetime.fromisoformat(data['timestamp']),
            order_id=data.get('order_id'),
            position_id=data.get('position_id'),
            cooldown_remaining=data.get('cooldown_remaining', 0),
            symbol=data.get('symbol', 'btcusdt')
        )


@dataclass
class FilterResult:
    """
    Result of a hard filter check.

    Used by ADX and Spread filters to communicate
    pass/fail status with details.

    Attributes:
        passed: Whether filter passed
        filter_name: Name of the filter (e.g., "ADX", "Spread")
        value: Actual value checked
        threshold: Threshold used for comparison
        reason: Human-readable explanation
    """
    passed: bool
    filter_name: str
    value: float
    threshold: float
    reason: str

    def to_dict(self) -> dict:
        """Convert to dictionary for logging/serialization."""
        return {
            'passed': self.passed,
            'filter_name': self.filter_name,
            'value': self.value,
            'threshold': self.threshold,
            'reason': self.reason
        }

    def __str__(self) -> str:
        status = "✅ PASS" if self.passed else "❌ FAIL"
        return f"{self.filter_name}: {status} (value={self.value:.4f}, threshold={self.threshold:.4f})"


@dataclass
class WarmupResult:
    """
    Result of cold start warm-up process.

    Contains information about historical data loading
    and indicator initialization.

    Attributes:
        success: Whether warm-up completed successfully
        candles_processed: Number of historical candles processed
        vwap_value: Current VWAP value after warm-up
        stoch_rsi_k: Current StochRSI K value
        stoch_rsi_d: Current StochRSI D value
        adx_value: Current ADX value
        duration_seconds: Time taken for warm-up
        error: Error message if failed
    """
    success: bool
    candles_processed: int = 0
    vwap_value: float = 0.0
    stoch_rsi_k: float = 0.0
    stoch_rsi_d: float = 0.0
    adx_value: float = 0.0
    duration_seconds: float = 0.0
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for logging."""
        return {
            'success': self.success,
            'candles_processed': self.candles_processed,
            'vwap_value': self.vwap_value,
            'stoch_rsi_k': self.stoch_rsi_k,
            'stoch_rsi_d': self.stoch_rsi_d,
            'adx_value': self.adx_value,
            'duration_seconds': self.duration_seconds,
            'error': self.error
        }

    def __str__(self) -> str:
        if self.success:
            return (
                f"✅ Warm-up complete: {self.candles_processed} candles, "
                f"VWAP={self.vwap_value:.2f}, ADX={self.adx_value:.1f}"
            )
        else:
            return f"❌ Warm-up failed: {self.error}"


@dataclass
class RecoveryResult:
    """
    Result of state recovery attempt on startup.

    Used by StateRecoveryService to communicate the outcome
    of attempting to restore state after bot restart.

    Attributes:
        action: Action taken ("restored", "reset", "no_action")
        previous_state: State found in database (if any)
        current_state: State after recovery
        position_verified: Whether position was verified with exchange
        message: Human-readable description of recovery action
    """
    action: str  # "restored", "reset", "no_action"
    current_state: SystemState
    message: str
    previous_state: Optional[SystemState] = None
    position_verified: bool = False

    def to_dict(self) -> dict:
        """Convert to dictionary for logging/serialization."""
        return {
            'action': self.action,
            'previous_state': self.previous_state.name if self.previous_state else None,
            'current_state': self.current_state.name,
            'position_verified': self.position_verified,
            'message': self.message
        }

    def __str__(self) -> str:
        if self.action == "restored":
            return f"✅ State restored: {self.current_state.name} (verified={self.position_verified})"
        elif self.action == "reset":
            return f"🔄 State reset: {self.previous_state.name if self.previous_state else 'None'} → {self.current_state.name}"
        else:
            return f"ℹ️ No recovery needed: {self.message}"
