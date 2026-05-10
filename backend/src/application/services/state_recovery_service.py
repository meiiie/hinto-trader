"""
StateRecoveryService - Application Layer

Handles state recovery on startup to prevent orphaned positions.

Responsibilities:
- Check database for last persisted state
- Verify position with exchange if IN_POSITION
- Restore state or reset to SCANNING based on verification
- Log recovery actions for audit
- CRITICAL: Block auto-resume from HALTED state (Expert Feedback 3)

This service solves the "Orphaned Position" problem where the bot
restarts and forgets it was holding a position.

Expert Feedback 3 Update:
- Now uses IExchangeService instead of IRestClient for position verification
- Enhanced HALTED state handling with safety checks
- Returns action="blocked" for HALTED state recovery
"""

import logging
from typing import Optional, TYPE_CHECKING

from ...domain.entities.state_models import PersistedState, RecoveryResult
from ...domain.state_machine import SystemState
from ...domain.repositories.i_state_repository import IStateRepository
from ...domain.interfaces.i_exchange_service import IExchangeService

if TYPE_CHECKING:
    from .trading_state_machine import TradingStateMachine


class StateRecoveryService:
    """
    Service for recovering trading state on startup.

    Usage:
        recovery_service = StateRecoveryService(
            state_repository=sqlite_repo,
            exchange_service=paper_exchange_service
        )

        result = await recovery_service.recover_state(
            state_machine=trading_sm,
            symbol="btcusdt"
        )

        if result.action == "restored":
            print(f"Restored to {result.current_state.name}")
        elif result.action == "blocked":
            print("HALTED state - manual intervention required")
    """

    def __init__(
        self,
        state_repository: IStateRepository,
        exchange_service: Optional[IExchangeService] = None,
        # Backward compatibility - accept rest_client but prefer exchange_service
        rest_client: Optional[object] = None
    ):
        """
        Initialize StateRecoveryService.

        Args:
            state_repository: Repository for loading persisted state
            exchange_service: IExchangeService for verifying positions (preferred)
            rest_client: Legacy REST client (deprecated, for backward compatibility)
        """
        self._state_repository = state_repository
        self._exchange_service = exchange_service
        self._rest_client = rest_client  # Keep for backward compatibility
        self.logger = logging.getLogger(__name__)

        if exchange_service:
            self.logger.info(
                f"StateRecoveryService initialized with {exchange_service.get_exchange_type()} exchange"
            )

    async def recover_state(
        self,
        state_machine: 'TradingStateMachine',
        symbol: str = "btcusdt"
    ) -> RecoveryResult:
        """
        Recover state from database and verify with exchange.

        Recovery Logic:
        1. Load persisted state from database
        2. If no state found, return no_action
        3. If state is IN_POSITION, verify position with exchange
        4. If position exists, restore IN_POSITION state
        5. If position was closed, transition to SCANNING

        Args:
            state_machine: TradingStateMachine to restore state to
            symbol: Trading symbol

        Returns:
            RecoveryResult with action taken
        """
        self.logger.info(f"🔄 Starting state recovery for {symbol}...")

        # Step 1: Load persisted state
        persisted = self._state_repository.load_state(symbol)

        if not persisted:
            self.logger.info("No persisted state found, starting fresh")
            return RecoveryResult(
                action="no_action",
                current_state=state_machine.state,
                message="No persisted state found in database"
            )

        self.logger.info(f"Found persisted state: {persisted.state.name}")

        # Step 2: Handle based on persisted state
        if persisted.state == SystemState.IN_POSITION:
            return await self._recover_in_position(
                state_machine, persisted, symbol
            )
        elif persisted.state == SystemState.ENTRY_PENDING:
            return await self._recover_entry_pending(
                state_machine, persisted, symbol
            )
        elif persisted.state == SystemState.COOLDOWN:
            return self._recover_cooldown(state_machine, persisted)
        elif persisted.state == SystemState.HALTED:
            return self._recover_halted(state_machine, persisted)
        else:
            # BOOTSTRAP or SCANNING - just start fresh
            self.logger.info(f"Persisted state {persisted.state.name} - starting fresh")
            return RecoveryResult(
                action="no_action",
                previous_state=persisted.state,
                current_state=state_machine.state,
                message=f"Persisted state {persisted.state.name} does not require recovery"
            )

    async def _recover_in_position(
        self,
        state_machine: 'TradingStateMachine',
        persisted: PersistedState,
        symbol: str
    ) -> RecoveryResult:
        """
        Recover from IN_POSITION state.

        Verifies position with exchange before restoring.
        """
        self.logger.info("Recovering from IN_POSITION state...")

        # Verify position with exchange
        position_exists = await self._verify_position_exists(
            symbol, persisted.position_id
        )

        if position_exists:
            # Position still exists - restore state
            self.logger.info("✅ Position verified on exchange, restoring IN_POSITION")
            state_machine.restore_from_persisted(persisted)

            return RecoveryResult(
                action="restored",
                previous_state=persisted.state,
                current_state=SystemState.IN_POSITION,
                position_verified=True,
                message=f"Position {persisted.position_id} verified, restored to IN_POSITION"
            )
        else:
            # Position was closed while offline - reset to SCANNING
            self.logger.warning(
                "⚠️ Position not found on exchange, resetting to SCANNING"
            )

            # Delete stale persisted state
            self._state_repository.delete_state(symbol)

            return RecoveryResult(
                action="reset",
                previous_state=persisted.state,
                current_state=SystemState.BOOTSTRAP,  # Will transition to SCANNING after warmup
                position_verified=False,
                message=f"Position {persisted.position_id} not found on exchange, reset to SCANNING"
            )

    async def _recover_entry_pending(
        self,
        state_machine: 'TradingStateMachine',
        persisted: PersistedState,
        symbol: str
    ) -> RecoveryResult:
        """
        Recover from ENTRY_PENDING state.

        Checks if order was filled while offline.
        """
        self.logger.info("Recovering from ENTRY_PENDING state...")

        # Check order status
        order_filled = await self._check_order_filled(
            symbol, persisted.order_id
        )

        if order_filled:
            # Order was filled - we're now in position
            self.logger.info("✅ Order was filled, transitioning to IN_POSITION")

            # Update persisted state to IN_POSITION
            persisted.state = SystemState.IN_POSITION
            state_machine.restore_from_persisted(persisted)

            return RecoveryResult(
                action="restored",
                previous_state=SystemState.ENTRY_PENDING,
                current_state=SystemState.IN_POSITION,
                position_verified=True,
                message=f"Order {persisted.order_id} was filled, restored to IN_POSITION"
            )
        else:
            # Order was not filled or cancelled - reset to SCANNING
            self.logger.info("Order not filled, resetting to SCANNING")

            # Delete stale persisted state
            self._state_repository.delete_state(symbol)

            return RecoveryResult(
                action="reset",
                previous_state=SystemState.ENTRY_PENDING,
                current_state=SystemState.BOOTSTRAP,
                position_verified=False,
                message=f"Order {persisted.order_id} not filled, reset to SCANNING"
            )

    def _recover_cooldown(
        self,
        state_machine: 'TradingStateMachine',
        persisted: PersistedState
    ) -> RecoveryResult:
        """
        Recover from COOLDOWN state.

        Simply restores cooldown counter.
        """
        self.logger.info(
            f"Recovering from COOLDOWN state ({persisted.cooldown_remaining} remaining)"
        )

        if persisted.cooldown_remaining > 0:
            state_machine.restore_from_persisted(persisted)

            return RecoveryResult(
                action="restored",
                previous_state=persisted.state,
                current_state=SystemState.COOLDOWN,
                message=f"Restored COOLDOWN with {persisted.cooldown_remaining} candles remaining"
            )
        else:
            # Cooldown was complete - go to SCANNING
            return RecoveryResult(
                action="reset",
                previous_state=persisted.state,
                current_state=SystemState.BOOTSTRAP,
                message="Cooldown was complete, starting fresh"
            )

    def _recover_halted(
        self,
        state_machine: 'TradingStateMachine',
        persisted: PersistedState
    ) -> RecoveryResult:
        """
        Recover from HALTED state.

        CRITICAL SAFETY: Never auto-resume from HALTED state.
        This requires manual intervention to prevent accidental trading
        after a critical error.

        Expert Feedback 3: Enhanced safety checks
        - Log explicit warning message
        - Return action="blocked" instead of "restored"
        - Keep system in HALTED state
        """
        # Log critical warning per expert requirement
        self.logger.warning(
            "⛔ CẢNH BÁO: Bot bị tắt khi đang HALTED. Giữ nguyên trạng thái dừng."
        )
        self.logger.error(
            "🚫 SAFETY BLOCK: Auto-resume from HALTED is disabled. "
            "Manual intervention required to resume trading."
        )

        # Restore HALTED state to state machine
        state_machine.restore_from_persisted(persisted)

        # Return blocked action - NOT restored
        # This signals to the caller that the system is intentionally blocked
        return RecoveryResult(
            action="blocked",
            previous_state=persisted.state,
            current_state=SystemState.HALTED,
            message="Recovered from HALTED state. Manual intervention required."
        )

    async def _verify_position_exists(
        self,
        symbol: str,
        position_id: Optional[str]
    ) -> bool:
        """
        Verify position exists on exchange.

        Uses IExchangeService for unified position verification
        across paper and real trading modes.

        Expert Feedback 3: Now uses IExchangeService instead of IRestClient
        """
        # Prefer IExchangeService (new approach)
        if self._exchange_service:
            try:
                position = await self._exchange_service.get_position(symbol.upper())

                if position:
                    self.logger.info(
                        f"Found position via {self._exchange_service.get_exchange_type()}: "
                        f"{position.side} {position.size} @ {position.entry_price}"
                    )
                    return True
                else:
                    self.logger.info(
                        f"No open position found for {symbol} "
                        f"via {self._exchange_service.get_exchange_type()}"
                    )
                    return False

            except Exception as e:
                self.logger.error(f"Error verifying position via exchange service: {e}")
                # On error, assume position exists to be safe
                return True

        # Fallback to legacy REST client (backward compatibility)
        if self._rest_client:
            self.logger.warning("Using legacy REST client for position verification")
            try:
                positions = self._rest_client.get_open_positions(symbol)

                if positions and len(positions) > 0:
                    self.logger.info(f"Found {len(positions)} open position(s) for {symbol}")
                    return True
                else:
                    self.logger.info(f"No open positions found for {symbol}")
                    return False

            except Exception as e:
                self.logger.error(f"Error verifying position: {e}")
                return True

        # No exchange service configured
        self.logger.warning("No exchange service configured, assuming position exists")
        return True

    async def _check_order_filled(
        self,
        symbol: str,
        order_id: Optional[str]
    ) -> bool:
        """
        Check if order was filled on exchange.
        """
        if not self._rest_client or not order_id:
            self.logger.warning("Cannot check order status, assuming not filled")
            return False

        try:
            order = self._rest_client.get_order(symbol, order_id)

            if order and order.get('status') == 'FILLED':
                return True
            else:
                return False

        except Exception as e:
            self.logger.error(f"Error checking order status: {e}")
            return False

    def __repr__(self) -> str:
        return f"StateRecoveryService(repository={self._state_repository})"
