"""
Trading State Machine - Domain Layer

Defines the Finite State Machine (FSM) for trading lifecycle management.

States:
- BOOTSTRAP: System starting, loading historical data
- SCANNING: Waiting for trading signals
- ENTRY_PENDING: Order placed, waiting for fill
- IN_POSITION: Holding an active position
- COOLDOWN: Post-trade rest period
- HALTED: Emergency stop, manual intervention required
"""

from enum import Enum, auto
from typing import Set, Dict, List


class SystemState(Enum):
    """
    Trading system states for FSM.

    State Transitions:
    - BOOTSTRAP → SCANNING (warm-up complete)
    - BOOTSTRAP → HALTED (load failed)
    - SCANNING → ENTRY_PENDING (valid signal)
    - SCANNING → HALTED (critical error)
    - ENTRY_PENDING → IN_POSITION (order filled)
    - ENTRY_PENDING → SCANNING (order canceled/expired)
    - ENTRY_PENDING → HALTED (critical error)
    - IN_POSITION → COOLDOWN (position closed)
    - IN_POSITION → HALTED (critical error)
    - COOLDOWN → SCANNING (cooldown complete)
    - COOLDOWN → HALTED (critical error)
    """
    BOOTSTRAP = auto()      # Loading historical data for warm-up
    SCANNING = auto()       # Waiting for trading signals
    ENTRY_PENDING = auto()  # Order placed, waiting for fill
    IN_POSITION = auto()    # Holding an active position
    COOLDOWN = auto()       # Post-trade rest period
    HALTED = auto()         # Emergency stop

    @classmethod
    def get_all_states(cls) -> List['SystemState']:
        """Get all defined states."""
        return list(cls)

    @classmethod
    def get_state_count(cls) -> int:
        """Get total number of states."""
        return len(cls)

    @property
    def is_active_trading(self) -> bool:
        """Check if state allows active trading operations."""
        return self in (SystemState.SCANNING, SystemState.ENTRY_PENDING, SystemState.IN_POSITION)

    @property
    def is_terminal(self) -> bool:
        """Check if state is terminal (requires manual intervention)."""
        return self == SystemState.HALTED

    @property
    def can_receive_signals(self) -> bool:
        """Check if state can process new trading signals."""
        return self == SystemState.SCANNING


# Valid state transitions map
# Key: current state, Value: set of valid next states
VALID_TRANSITIONS: Dict[SystemState, Set[SystemState]] = {
    SystemState.BOOTSTRAP: {SystemState.SCANNING, SystemState.HALTED},
    SystemState.SCANNING: {SystemState.ENTRY_PENDING, SystemState.HALTED},
    SystemState.ENTRY_PENDING: {SystemState.IN_POSITION, SystemState.SCANNING, SystemState.HALTED},
    SystemState.IN_POSITION: {SystemState.COOLDOWN, SystemState.HALTED},
    SystemState.COOLDOWN: {SystemState.SCANNING, SystemState.HALTED},
    SystemState.HALTED: set(),  # Terminal state - no transitions out
}


def is_valid_transition(from_state: SystemState, to_state: SystemState) -> bool:
    """
    Check if a state transition is valid.

    Args:
        from_state: Current state
        to_state: Target state

    Returns:
        True if transition is valid, False otherwise

    Example:
        >>> is_valid_transition(SystemState.SCANNING, SystemState.ENTRY_PENDING)
        True
        >>> is_valid_transition(SystemState.SCANNING, SystemState.IN_POSITION)
        False
    """
    valid_targets = VALID_TRANSITIONS.get(from_state, set())
    return to_state in valid_targets


def get_valid_transitions(state: SystemState) -> Set[SystemState]:
    """
    Get all valid transitions from a given state.

    Args:
        state: Current state

    Returns:
        Set of valid target states
    """
    return VALID_TRANSITIONS.get(state, set())
