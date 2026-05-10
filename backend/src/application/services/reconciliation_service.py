"""
ReconciliationService - SOTA Position Sync with Exchange

Pattern: Two Sigma, Citadel, Renaissance Technologies
- Periodic sync of local state with Binance exchange
- Detects position drift (quantity mismatch, orphan positions)
- Alerts via Telegram when drift detected

Created: 2026-02-01
Purpose: Fix REAL MONEY gap - ensure local state matches exchange
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional, List, TYPE_CHECKING
from dataclasses import dataclass

if TYPE_CHECKING:
    from .live_trading_service import LiveTradingService
    from .position_monitor_service import PositionMonitorService
    from ...infrastructure.notifications.telegram_service import TelegramService

logger = logging.getLogger(__name__)


@dataclass
class DriftReport:
    """Report of detected position drift."""
    drift_type: str  # 'ORPHAN', 'MISSING', 'QUANTITY_MISMATCH'
    symbol: str
    local_qty: float
    exchange_qty: float
    local_side: str
    exchange_side: str
    timestamp: datetime

    @property
    def severity(self) -> str:
        """Get drift severity for alerting."""
        if self.drift_type == 'MISSING':
            return 'CRITICAL'  # Position closed without us knowing
        elif self.drift_type == 'ORPHAN':
            return 'HIGH'  # Position on exchange we're not tracking
        elif self.drift_type == 'QUANTITY_MISMATCH':
            return 'MEDIUM'  # Partial close on exchange
        return 'LOW'


class ReconciliationService:
    """
    SOTA Exchange Reconciliation Service

    Periodically syncs local position state with Binance exchange.
    Detects and alerts on position drift to prevent PnL calculation errors.

    Usage:
        reconciliation = ReconciliationService(
            exchange_client=async_client,
            position_monitor=position_monitor,
            live_trading_service=live_service,
            telegram_service=telegram
        )
        await reconciliation.start()
    """

    def __init__(
        self,
        exchange_client,  # Binance async client
        position_monitor: 'PositionMonitorService',
        live_trading_service: 'LiveTradingService',
        telegram_service: Optional['TelegramService'] = None,
        interval_seconds: int = 60,
        enabled: bool = True
    ):
        """
        Initialize ReconciliationService.

        Args:
            exchange_client: Binance async client for API calls
            position_monitor: PositionMonitorService for local state
            live_trading_service: LiveTradingService for position data
            telegram_service: Optional TelegramService for alerts
            interval_seconds: Seconds between reconciliation cycles
            enabled: Whether service is enabled
        """
        self._client = exchange_client
        self._position_monitor = position_monitor
        self._live_service = live_trading_service
        self._telegram = telegram_service
        self._interval = interval_seconds
        self._enabled = enabled

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_reconcile: Optional[datetime] = None

        # Stats
        self._reconcile_count = 0
        self._drift_count = 0
        self._last_drift: Optional[DriftReport] = None

        logger.info(
            f"📊 ReconciliationService initialized: "
            f"interval={interval_seconds}s, enabled={enabled}"
        )

    async def start(self):
        """Start reconciliation loop."""
        if self._running:
            logger.warning("ReconciliationService already running")
            return

        if not self._enabled:
            logger.info("ReconciliationService disabled, not starting")
            return

        self._running = True
        self._task = asyncio.create_task(self._reconcile_loop())
        logger.info("🔄 ReconciliationService started")

    async def stop(self):
        """Stop reconciliation loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("🛑 ReconciliationService stopped")

    async def _reconcile_loop(self):
        """Main reconciliation loop."""
        while self._running:
            try:
                await self._reconcile_once()
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Reconciliation error: {e}")
                await asyncio.sleep(self._interval)

    async def _reconcile_once(self) -> List[DriftReport]:
        """
        Run single reconciliation cycle.

        Returns:
            List of detected drifts
        """
        self._reconcile_count += 1
        self._last_reconcile = datetime.now()
        drifts: List[DriftReport] = []

        try:
            # 1. Get positions from Binance
            exchange_positions = await self._get_exchange_positions()

            # 2. Get local tracked positions
            local_positions = self._get_local_positions()

            # 3. Compare and detect drifts
            drifts = self._detect_drifts(local_positions, exchange_positions)

            if drifts:
                self._drift_count += len(drifts)
                self._last_drift = drifts[0]

                # 4. Alert via Telegram
                await self._alert_drifts(drifts)

                # 5. Auto-fix quantity drifts
                await self._auto_fix_quantity_drifts(drifts)

            logger.debug(
                f"✅ Reconciliation #{self._reconcile_count}: "
                f"exchange={len(exchange_positions)}, local={len(local_positions)}, "
                f"drifts={len(drifts)}"
            )

        except Exception as e:
            logger.error(f"❌ Reconciliation failed: {e}")

        return drifts

    async def _get_exchange_positions(self) -> Dict[str, dict]:
        """Get all open positions from Binance."""
        positions = {}

        try:
            if self._client is None:
                return positions

            # Get all account positions from Binance
            account = await self._client.futures_account()

            for pos in account.get('positions', []):
                qty = float(pos.get('positionAmt', 0))
                if qty != 0:  # Only include open positions
                    symbol = pos.get('symbol', '')
                    positions[symbol] = {
                        'symbol': symbol,
                        'quantity': abs(qty),
                        'side': 'LONG' if qty > 0 else 'SHORT',
                        'entry_price': float(pos.get('entryPrice', 0)),
                        'unrealized_pnl': float(pos.get('unRealizedProfit', 0)),
                        'leverage': int(pos.get('leverage', 1))
                    }

        except Exception as e:
            logger.error(f"Failed to get exchange positions: {e}")

        return positions

    def _get_local_positions(self) -> Dict[str, dict]:
        """Get all locally tracked positions."""
        positions = {}

        try:
            # Get from PositionMonitor
            if self._position_monitor:
                for symbol, pos in self._position_monitor._positions.items():
                    positions[symbol] = {
                        'symbol': symbol,
                        'quantity': pos.quantity,
                        'side': pos.side,
                        'entry_price': pos.entry_price,
                        'current_sl': pos.current_sl,
                        'initial_tp': pos.initial_tp
                    }

            # Merge with LiveTradingService active_positions
            if self._live_service:
                for symbol, pos in self._live_service.active_positions.items():
                    if symbol not in positions:
                        positions[symbol] = {
                            'symbol': symbol,
                            'quantity': pos.get('size', 0),
                            'side': pos.get('side', 'UNKNOWN'),
                            'entry_price': pos.get('entry_price', 0)
                        }

        except Exception as e:
            logger.error(f"Failed to get local positions: {e}")

        return positions

    def _detect_drifts(
        self,
        local: Dict[str, dict],
        exchange: Dict[str, dict]
    ) -> List[DriftReport]:
        """
        Detect drifts between local and exchange positions.

        Args:
            local: Local position dict
            exchange: Exchange position dict

        Returns:
            List of DriftReports
        """
        drifts = []
        now = datetime.now()

        # Check for MISSING (local exists, exchange doesn't)
        for symbol, local_pos in local.items():
            if symbol not in exchange:
                drifts.append(DriftReport(
                    drift_type='MISSING',
                    symbol=symbol,
                    local_qty=local_pos.get('quantity', 0),
                    exchange_qty=0,
                    local_side=local_pos.get('side', 'UNKNOWN'),
                    exchange_side='NONE',
                    timestamp=now
                ))
            else:
                # Check for QUANTITY_MISMATCH
                exchange_pos = exchange[symbol]
                local_qty = local_pos.get('quantity', 0)
                exchange_qty = exchange_pos.get('quantity', 0)

                # Allow 1% tolerance for rounding
                if abs(local_qty - exchange_qty) / max(local_qty, 0.0001) > 0.01:
                    drifts.append(DriftReport(
                        drift_type='QUANTITY_MISMATCH',
                        symbol=symbol,
                        local_qty=local_qty,
                        exchange_qty=exchange_qty,
                        local_side=local_pos.get('side', 'UNKNOWN'),
                        exchange_side=exchange_pos.get('side', 'UNKNOWN'),
                        timestamp=now
                    ))

        # Check for ORPHAN (exchange exists, local doesn't)
        for symbol, exchange_pos in exchange.items():
            if symbol not in local:
                drifts.append(DriftReport(
                    drift_type='ORPHAN',
                    symbol=symbol,
                    local_qty=0,
                    exchange_qty=exchange_pos.get('quantity', 0),
                    local_side='NONE',
                    exchange_side=exchange_pos.get('side', 'UNKNOWN'),
                    timestamp=now
                ))

        return drifts

    async def _alert_drifts(self, drifts: List[DriftReport]):
        """Send Telegram alerts for detected drifts."""
        if not self._telegram or not drifts:
            return

        for drift in drifts:
            severity_emoji = {
                'CRITICAL': '🚨',
                'HIGH': '⚠️',
                'MEDIUM': '⚡',
                'LOW': 'ℹ️'
            }.get(drift.severity, '❓')

            message = (
                f"{severity_emoji} <b>POSITION DRIFT DETECTED</b>\n\n"
                f"<b>Type:</b> {drift.drift_type}\n"
                f"<b>Symbol:</b> {drift.symbol}\n"
                f"<b>Local:</b> {drift.local_qty} {drift.local_side}\n"
                f"<b>Exchange:</b> {drift.exchange_qty} {drift.exchange_side}\n"
                f"<b>Time:</b> {drift.timestamp.strftime('%H:%M:%S')}\n"
            )

            if drift.drift_type == 'MISSING':
                message += (
                    f"\n<b>⚠️ ACTION REQUIRED:</b>\n"
                    f"Position closed on exchange but local state still tracking.\n"
                    f"Local monitoring will be removed."
                )
            elif drift.drift_type == 'ORPHAN':
                message += (
                    f"\n<b>⚠️ ACTION REQUIRED:</b>\n"
                    f"Position on exchange not tracked locally.\n"
                    f"Manual close or restart backend with SAFE MODE."
                )

            try:
                await self._telegram.send_message(message)
            except Exception as e:
                logger.error(f"Failed to send drift alert: {e}")

    async def _auto_fix_quantity_drifts(self, drifts: List[DriftReport]):
        """
        Auto-fix quantity mismatches by syncing local state.

        MISSING positions: Remove from local tracking
        QUANTITY_MISMATCH: Update local quantity
        ORPHAN: Log only (requires manual action)
        """
        for drift in drifts:
            try:
                if drift.drift_type == 'MISSING':
                    # Position closed on exchange, remove local tracking
                    if self._position_monitor and drift.symbol in self._position_monitor._positions:
                        pos = self._position_monitor._positions[drift.symbol]

                        # SOTA (Feb 2026): Grace period to prevent race conditions
                        # Don't remove positions opened in the last 30 seconds
                        # This prevents reconciliation from interfering with new signals
                        if hasattr(pos, 'entry_time') and pos.entry_time:
                            age_seconds = (datetime.now() - pos.entry_time).total_seconds()
                            if age_seconds < 30:  # 30 second grace period
                                logger.info(
                                    f"⏳ Skipping MISSING drift for {drift.symbol} "
                                    f"(age={age_seconds:.1f}s < 30s grace period)"
                                )
                                continue

                        # Safe to remove - position is old enough
                        self._position_monitor.stop_monitoring(drift.symbol)
                        logger.warning(
                            f"🗑️ Removed MISSING position from local: {drift.symbol}"
                        )

                elif drift.drift_type == 'QUANTITY_MISMATCH':
                    # Sync local quantity with exchange
                    if self._position_monitor:
                        await self._position_monitor.sync_quantity_from_exchange(
                            drift.symbol,
                            drift.exchange_qty
                        )
                        logger.info(
                            f"🔄 Synced quantity for {drift.symbol}: "
                            f"{drift.local_qty} → {drift.exchange_qty}"
                        )

                # ORPHAN requires manual action - just logged

            except Exception as e:
                logger.error(f"Failed to auto-fix drift for {drift.symbol}: {e}")

    async def reconcile_now(self) -> Dict:
        """
        Trigger manual reconciliation.

        Returns:
            Dict with reconciliation results
        """
        drifts = await self._reconcile_once()

        return {
            'success': True,
            'timestamp': datetime.now().isoformat(),
            'drifts_found': len(drifts),
            'drifts': [
                {
                    'type': d.drift_type,
                    'symbol': d.symbol,
                    'severity': d.severity,
                    'local_qty': d.local_qty,
                    'exchange_qty': d.exchange_qty
                }
                for d in drifts
            ]
        }

    def get_stats(self) -> Dict:
        """Get reconciliation statistics."""
        return {
            'enabled': self._enabled,
            'running': self._running,
            'interval_seconds': self._interval,
            'reconcile_count': self._reconcile_count,
            'drift_count': self._drift_count,
            'last_reconcile': self._last_reconcile.isoformat() if self._last_reconcile else None,
            'last_drift': {
                'type': self._last_drift.drift_type,
                'symbol': self._last_drift.symbol,
                'time': self._last_drift.timestamp.isoformat()
            } if self._last_drift else None
        }

    def __repr__(self) -> str:
        status = "RUNNING" if self._running else "STOPPED"
        return f"ReconciliationService({status}, interval={self._interval}s)"
