"""
TradingStateMachine - Application Layer

Finite State Machine for trading lifecycle management.

Responsibilities:
- Manage state transitions with validation
- Enforce transition rules
- Publish state change events via EventBus
- Track cooldown periods
- Handle emergency halt

States:
- BOOTSTRAP: Loading historical data
- SCANNING: Waiting for signals
- ENTRY_PENDING: Order placed, waiting for fill
- IN_POSITION: Holding position
- COOLDOWN: Post-trade rest
- HALTED: Emergency stop
"""

import logging
from datetime import datetime
from typing import Optional, List, Any, TYPE_CHECKING

from ...domain.state_machine import (
    SystemState,
    is_valid_transition,
    get_valid_transitions,
    VALID_TRANSITIONS
)
from ...domain.entities.state_models import StateTransition, PersistedState

if TYPE_CHECKING:
    from ...api.event_bus import EventBus


class InvalidStateTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""
    pass


class TradingStateMachine:
    """
    Finite State Machine for trading lifecycle management.

    Usage:
        sm = TradingStateMachine(event_bus=event_bus)
        sm.transition_to(SystemState.SCANNING, reason="Warm-up complete")

        # Check current state
        if sm.can_receive_signals:
            signal = generate_signal()
            if signal:
                sm.transition_to(SystemState.ENTRY_PENDING, reason="Signal detected")
    """

    def __init__(
        self,
        event_bus: Optional['EventBus'] = None,
        initial_state: SystemState = SystemState.BOOTSTRAP,
        cooldown_candles: int = 4,
        symbol: str = "btcusdt"
    ):
        """
        Initialize the state machine.

        Args:
            event_bus: EventBus for publishing state changes
            initial_state: Starting state (default: BOOTSTRAP)
            cooldown_candles: Number of candles to wait in COOLDOWN (default: 4)
            symbol: Trading symbol
        """
        self._state = initial_state
        self._event_bus = event_bus
        self._cooldown_candles = cooldown_candles
        self._cooldown_counter = 0
        self._symbol = symbol

        # Order/Position tracking
        self._current_order_id: Optional[str] = None
        self._current_position_id: Optional[str] = None

        # Transition history for debugging
        self._transition_history: List[StateTransition] = []
        self._max_history = 100  # Keep last 100 transitions

        self.logger = logging.getLogger(__name__)
        self.logger.info(f"TradingStateMachine initialized in {initial_state.name}")

    @property
    def state(self) -> SystemState:
        """Get current state."""
        return self._state

    @property
    def can_receive_signals(self) -> bool:
        """Check if machine can process new trading signals."""
        return self._state.can_receive_signals

    @property
    def is_active_trading(self) -> bool:
        """Check if in active trading state."""
        return self._state.is_active_trading

    @property
    def is_halted(self) -> bool:
        """Check if machine is halted."""
        return self._state == SystemState.HALTED

    def check_trading_allowed(self) -> tuple:
        """
        Check if trading operations are allowed.

        Expert Feedback 3: Safety check for HALTED state.

        Returns:
            Tuple of (allowed: bool, reason: str)

        Example:
            allowed, reason = sm.check_trading_allowed()
            if not allowed:
                logger.warning(f"Trading blocked: {reason}")
                return
        """
        if self._state == SystemState.HALTED:
            return (
                False,
                "Trading blocked: System is in HALTED state. Manual intervention required."
            )

        if self._state == SystemState.BOOTSTRAP:
            return (
                False,
                "Trading blocked: System is still in BOOTSTRAP state (warming up)."
            )

        return (True, "Trading allowed")

    @property
    def cooldown_remaining(self) -> int:
        """Get remaining cooldown candles."""
        return self._cooldown_counter

    @property
    def current_order_id(self) -> Optional[str]:
        """Get current order ID."""
        return self._current_order_id

    @property
    def current_position_id(self) -> Optional[str]:
        """Get current position ID."""
        return self._current_position_id

    def set_event_bus(self, event_bus: 'EventBus') -> None:
        """Set EventBus for state change publishing."""
        self._event_bus = event_bus
        self.logger.info("EventBus connected to TradingStateMachine")

    def transition_to(
        self,
        new_state: SystemState,
        reason: str,
        order_id: Optional[str] = None,
        position_id: Optional[str] = None
    ) -> StateTransition:
        """
        Transition to a new state.

        Args:
            new_state: Target state
            reason: Human-readable reason for transition
            order_id: Associated order ID (optional)
            position_id: Associated position ID (optional)

        Returns:
            StateTransition record

        Raises:
            InvalidStateTransitionError: If transition is not valid
        """
        old_state = self._state

        # Validate transition
        if not is_valid_transition(old_state, new_state):
            valid_targets = get_valid_transitions(old_state)
            raise InvalidStateTransitionError(
                f"Invalid transition: {old_state.name} → {new_state.name}. "
                f"Valid targets: {[s.name for s in valid_targets]}"
            )

        # Create transition record
        transition = StateTransition(
            from_state=old_state,
            to_state=new_state,
            reason=reason,
            timestamp=datetime.now(),
            order_id=order_id,
            position_id=position_id
        )

        # Update state
        self._state = new_state

        # Update order/position tracking
        if order_id:
            self._current_order_id = order_id
        if position_id:
            self._current_position_id = position_id

        # Handle special state logic
        if new_state == SystemState.COOLDOWN:
            self._cooldown_counter = self._cooldown_candles
        elif new_state == SystemState.SCANNING:
            # Clear order/position when returning to scanning
            self._current_order_id = None
            self._current_position_id = None
            self._cooldown_counter = 0

        # Record transition
        self._transition_history.append(transition)
        if len(self._transition_history) > self._max_history:
            self._transition_history.pop(0)

        # Log transition
        self.logger.info(f"🔄 State transition: {transition}")

        # Publish to EventBus
        self._publish_state_change(transition)

        return transition

    def halt(self, reason: str) -> StateTransition:
        """
        Emergency halt - transition to HALTED from any state.

        Args:
            reason: Reason for halt

        Returns:
            StateTransition record
        """
        if self._state == SystemState.HALTED:
            self.logger.warning("Already in HALTED state")
            return StateTransition(
                from_state=SystemState.HALTED,
                to_state=SystemState.HALTED,
                reason=f"Already halted. New reason: {reason}"
            )

        # Force transition to HALTED (always valid from any state)
        return self.transition_to(SystemState.HALTED, reason=f"EMERGENCY: {reason}")

    def tick_cooldown(self) -> bool:
        """
        Decrement cooldown counter (call on each candle).

        Returns:
            True if cooldown complete and transitioned to SCANNING
        """
        if self._state != SystemState.COOLDOWN:
            return False

        self._cooldown_counter -= 1
        self.logger.debug(f"Cooldown tick: {self._cooldown_counter} remaining")

        if self._cooldown_counter <= 0:
            self.transition_to(
                SystemState.SCANNING,
                reason=f"Cooldown complete ({self._cooldown_candles} candles)"
            )
            return True

        return False

    def _publish_state_change(self, transition: StateTransition) -> None:
        """Publish state change event to EventBus."""
        if not self._event_bus:
            self.logger.debug("No EventBus configured, skipping publish")
            return

        try:
            # Use dedicated state_change event type (Task 11)
            state_data = {
                **transition.to_dict(),
                'current_state': self._state.name,
                'cooldown_remaining': self._cooldown_counter
            }
            self._event_bus.publish_state_change(state_data, symbol=self._symbol)
            self.logger.debug(f"Published state change: {transition}")
        except Exception as e:
            self.logger.error(f"Failed to publish state change: {e}")

    def get_persisted_state(self) -> PersistedState:
        """Get current state for persistence."""
        return PersistedState(
            state=self._state,
            timestamp=datetime.now(),
            order_id=self._current_order_id,
            position_id=self._current_position_id,
            cooldown_remaining=self._cooldown_counter,
            symbol=self._symbol
        )

    def restore_from_persisted(self, persisted: PersistedState) -> None:
        """
        Restore state from persisted data.

        Note: This bypasses normal transition validation.
        Should only be used during startup recovery.
        """
        self._state = persisted.state
        self._current_order_id = persisted.order_id
        self._current_position_id = persisted.position_id
        self._cooldown_counter = persisted.cooldown_remaining
        self._symbol = persisted.symbol

        self.logger.info(
            f"Restored state from persistence: {persisted.state.name}, "
            f"order={persisted.order_id}, position={persisted.position_id}"
        )

    def get_transition_history(self, limit: int = 10) -> List[StateTransition]:
        """Get recent transition history."""
        return self._transition_history[-limit:]

    def get_status(self) -> dict:
        """Get current status as dictionary."""
        trading_allowed, trading_reason = self.check_trading_allowed()
        return {
            'state': self._state.name,
            'can_receive_signals': self.can_receive_signals,
            'is_active_trading': self.is_active_trading,
            'is_halted': self.is_halted,
            'trading_allowed': trading_allowed,
            'trading_blocked_reason': trading_reason if not trading_allowed else None,
            'cooldown_remaining': self._cooldown_counter,
            'current_order_id': self._current_order_id,
            'current_position_id': self._current_position_id,
            'symbol': self._symbol,
            'transition_count': len(self._transition_history)
        }

    def __repr__(self) -> str:
        return f"TradingStateMachine(state={self._state.name}, symbol={self._symbol})"
