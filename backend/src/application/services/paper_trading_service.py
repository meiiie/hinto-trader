import uuid
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Callable
from dataclasses import dataclass
from src.domain.entities.paper_position import PaperPosition
from src.domain.entities.trading_signal import TradingSignal, SignalType
from src.domain.entities.portfolio import Portfolio
from src.domain.entities.performance_metrics import PerformanceMetrics
from src.domain.repositories.i_order_repository import IOrderRepository
# SOTA FIX: Import Market Repository for Price Oracle
from src.infrastructure.persistence.sqlite_market_data_repository import SQLiteMarketDataRepository
from src.trading_contract import (
    PRODUCTION_AUTO_CLOSE_INTERVAL,
    PRODUCTION_BLOCKED_WINDOWS_STR,
    PRODUCTION_CB_MAX_CONSECUTIVE_LOSSES,
    PRODUCTION_CB_MAX_DAILY_DRAWDOWN_PCT,
    PRODUCTION_CLOSE_PROFITABLE_AUTO,
    PRODUCTION_LEVERAGE,
    PRODUCTION_LIMIT_CHASE_TIMEOUT_SECONDS,
    PRODUCTION_MAX_POSITIONS,
    PRODUCTION_ORDER_TYPE,
    PRODUCTION_ORDER_TTL_MINUTES,
    PRODUCTION_PORTFOLIO_TARGET_PCT,
    PRODUCTION_PROFITABLE_THRESHOLD_PCT,
    PRODUCTION_RISK_PER_TRADE,
    clamp_runtime_leverage,
    parse_blocked_windows,
)
import logging

logger = logging.getLogger(__name__)


@dataclass
class PaginatedTrades:
    """Paginated trade history result"""
    trades: List[PaperPosition]
    total: int
    page: int
    limit: int
    total_pages: int

    def to_dict(self) -> dict:
        return {
            'trades': [
                {
                    'id': t.id,
                    'symbol': t.symbol,
                    'side': t.side,
                    'status': t.status,
                    'entry_price': t.entry_price,
                    'quantity': t.quantity,
                    'margin': t.margin,
                    'stop_loss': t.stop_loss,
                    'take_profit': t.take_profit,
                    'open_time': t.open_time.isoformat() if t.open_time else None,
                    'close_time': t.close_time.isoformat() if t.close_time else None,
                    'realized_pnl': t.realized_pnl,
                    'exit_reason': t.exit_reason
                }
                for t in self.trades
            ],
            'total': self.total,
            'page': self.page,
            'limit': self.limit,
            'total_pages': self.total_pages
        }

class PaperTradingService:
    """
    Paper Trading Engine (USDT-M Futures).
    Simulates Futures trading with Leverage (Default 1x).
    """

    # Cooldown durations
    DEFAULT_COOLDOWN_SECONDS = 300  # 5 minutes for normal exits
    REVERSAL_COOLDOWN_SECONDS = 600  # 10 minutes after SIGNAL_REVERSAL

    # SOTA (Jan 2026): Fee simulation - Binance Futures VIP 0
    MAKER_FEE_PCT = 0.0002   # 0.02% for limit orders
    TAKER_FEE_PCT = 0.0005   # 0.05% for market/SL/TP orders

    # SOTA (Jan 2026): Slippage simulation
    BASE_SLIPPAGE_PCT = 0.0002  # 0.02% base slippage

    # SOTA (Jan 2026): Funding rate simulation
    FUNDING_RATE_PCT = 0.0001   # 0.01% per 8 hours (Binance default)
    FUNDING_INTERVAL_HOURS = 8

    def __init__(
        self,
        repository: IOrderRepository,
        market_data_repository: Optional[SQLiteMarketDataRepository] = None,
        signal_lifecycle_service=None,
    ):
        self.repo = repository
        self.market_data_repo = market_data_repository
        self.signal_lifecycle_service = signal_lifecycle_service

        # SOTA: Load from Settings (persisted in SQLite) instead of hardcoding.
        # Defaults mirror the documented production contract.
        try:
            settings = self.repo.get_all_settings()
            self.MAX_POSITIONS = int(settings.get('max_positions', PRODUCTION_MAX_POSITIONS))
            self.RISK_PER_TRADE = float(
                settings.get('risk_percent', PRODUCTION_RISK_PER_TRADE * 100)
            ) / 100
            self.LEVERAGE = clamp_runtime_leverage(settings.get('leverage', PRODUCTION_LEVERAGE))
        except Exception:
            self.MAX_POSITIONS = PRODUCTION_MAX_POSITIONS
            self.RISK_PER_TRADE = PRODUCTION_RISK_PER_TRADE
            self.LEVERAGE = PRODUCTION_LEVERAGE

        # CRITICAL FIX: Per-symbol cooldowns (instead of global)
        # This allows trades on ETHUSDT while BTCUSDT is in cooldown
        self._cooldowns: Dict[str, datetime] = {}
        self._cooldown_durations: Dict[str, int] = {}  # Store duration per symbol

        # SOTA FIX: Allow position flip (close + open opposite)
        self.ALLOW_FLIP = True

        # SOTA SYNC: Margin tracking (matches Backtest execution_simulator.py line 59-61)
        # In Isolated Margin mode, we track margin locked in positions and pending orders
        self._used_margin = 0.0       # Margin locked in OPEN positions
        self._locked_in_orders = 0.0  # Margin locked in PENDING orders

        # State Machine Callbacks (ISSUE-001 Fix)
        # Called when a PENDING order is filled and becomes OPEN
        self.on_order_filled: Optional[Callable[[str], None]] = None
        # Called when a position is closed (SL/TP/LIQ/MANUAL)
        self.on_position_closed: Optional[Callable[[str, str], None]] = None

    def _mark_signal_pending(self, signal_id: Optional[str]) -> None:
        if not signal_id or not self.signal_lifecycle_service:
            return
        try:
            self.signal_lifecycle_service.mark_pending(signal_id)
        except Exception as e:
            logger.warning(f"Failed to mark paper signal pending {signal_id}: {e}")

    def _mark_signal_executed(self, signal_id: Optional[str], order_id: str) -> None:
        if not signal_id or not self.signal_lifecycle_service:
            return
        try:
            self.signal_lifecycle_service.mark_executed(signal_id, order_id)
        except Exception as e:
            logger.warning(f"Failed to mark paper signal executed {signal_id}: {e}")

    def _mark_signal_expired(self, signal_id: Optional[str]) -> None:
        if not signal_id or not self.signal_lifecycle_service:
            return
        try:
            self.signal_lifecycle_service.mark_expired(signal_id)
        except Exception as e:
            logger.warning(f"Failed to mark paper signal expired {signal_id}: {e}")

    def get_wallet_balance(self) -> float:
        """Get Wallet Balance (Total Deposited + Realized PnL)"""
        return self.repo.get_account_balance()

    def get_positions(self) -> List[PaperPosition]:
        """Get all OPEN positions"""
        return self.repo.get_active_orders()

    def get_available_balance(self) -> float:
        """
        SOTA SYNC: Calculate available balance like Backtest (line 117-123).
        Available = Wallet Balance - Used Margin (Positions) - Locked (Pending Orders)
        """
        return max(0.0, self.get_wallet_balance() - self._used_margin - self._locked_in_orders)

    def calculate_unrealized_pnl(self, current_price_override: float = 0.0) -> float:
        """
        Calculate Total Unrealized PnL of all open positions.

        SOTA FIX:
        Uses 'Price Oracle' (MarketDataRepository) to fetch symbol-specific prices.
        Ignores 'current_price_override' unless strictly necessary (single symbol context).
        """
        positions = self.get_positions()
        total_pnl = 0.0

        for pos in positions:
            price_to_use = 0.0

            # 1. Try to get price from Repository (Priority 1)
            # 1. Try to get price from Repository (Priority 1)
            if self.market_data_repo:
                # 1a. HOT PATH: In-Memory Cache
                price_to_use = self.market_data_repo.get_realtime_price(pos.symbol)

                # 1b. COLD PATH: DB Fallback (if cache empty)
                if price_to_use == 0.0:
                    candles = self.market_data_repo.get_latest_candles(pos.symbol, '1m', 1)
                    if candles and len(candles) > 0:
                        price_to_use = candles[0].close

            # 2. Fallback to override if logic allows (Weak fallback)
            # Only if we couldn't get price from repo and override is provided
            if price_to_use == 0.0 and current_price_override > 0:
                 price_to_use = current_price_override

            # 3. Calculate PnL for this position
            if price_to_use > 0:
                total_pnl += pos.calculate_unrealized_pnl(price_to_use)

        return total_pnl

    def get_positions_with_pnl(self) -> List[dict]:
        """
        Get all open positions enriched with PnL and current price.

        SOTA: Returns a View Model (Dictionary) ready for API response.
        Uses correct per-symbol pricing from Repository.
        """
        positions = self.get_positions()
        enriched = []

        for pos in positions:
            current_price = 0.0

            # Get Price from Repo
            if self.market_data_repo:
                # 1. HOT PATH: In-Memory Cache (Realtime)
                current_price = self.market_data_repo.get_realtime_price(pos.symbol)

                # 2. COLD PATH: DB Fallback
                if current_price == 0.0:
                    candles = self.market_data_repo.get_latest_candles(pos.symbol, '1m', 1)
                    if candles and len(candles) > 0:
                        current_price = candles[0].close  # SOTA: MarketData now has .close property

            # Fallback (Should not happen in prod if data exists)
            if current_price == 0.0:
                 current_price = pos.entry_price # Prevent division by zero / crazy numbers

            pnl = pos.calculate_unrealized_pnl(current_price)
            roe = pos.calculate_roe(current_price)

            enriched.append({
                "id": pos.id,
                "symbol": pos.symbol,
                "side": pos.side,
                "status": pos.status,
                "entry_price": pos.entry_price,
                "quantity": pos.quantity,
                "margin": pos.margin,
                "stop_loss": pos.stop_loss,
                "take_profit": pos.take_profit,
                # SOTA: Add local_tpsl for frontend display compatibility
                "local_tpsl": {
                    "stop_loss": pos.stop_loss or 0,
                    "take_profit": pos.take_profit or 0
                },
                # Paper mode has no exchange orders - empty
                "exchange_tpsl": {
                    "stop_loss": 0,
                    "take_profit": 0
                },
                "open_time": pos.open_time.isoformat() if pos.open_time else None,
                "size_usd": pos.quantity * pos.entry_price,
                "current_price": current_price,
                "current_value": pos.quantity * current_price,
                "unrealized_pnl": pnl,
                "roe_pct": roe
            })

        return enriched

    def get_margin_balance(self, current_price: float = 0.0) -> float:
        """Margin Balance = Wallet Balance + Unrealized PnL"""
        # SOTA: calculate_unrealized_pnl now handles price lookup internally
        return self.get_wallet_balance() + self.calculate_unrealized_pnl(current_price)

    def get_available_balance(self, current_price: float) -> float:
        """
        Available Balance = Margin Balance - Used Margin (Open + Pending)
        """
        margin_balance = self.get_margin_balance(current_price)
        used_margin = 0.0

        # 1. Margin of Open Positions
        for pos in self.get_positions():
            used_margin += pos.margin

        # 2. Margin of Pending Orders (Locked)
        pending_orders = self.repo.get_pending_orders()
        for order in pending_orders:
            used_margin += order.margin

        return max(0.0, margin_balance - used_margin)

    def _calculate_risk_capped_notional(
        self,
        wallet_balance: float,
        allocated_capital: float,
        entry_price: float,
        stop_loss: float,
    ) -> float:
        """
        Calculate order notional from slot allocation and account-risk cap.

        Slot allocation caps margin usage. The risk cap makes risk_percent mean
        the intended maximum loss at stop-loss, which is the safer paper behavior
        for small accounts.
        """
        max_notional_by_margin = allocated_capital * self.LEVERAGE

        if entry_price <= 0 or stop_loss <= 0 or self.RISK_PER_TRADE <= 0:
            return max_notional_by_margin

        stop_distance = abs(entry_price - stop_loss)
        if stop_distance <= 0:
            return max_notional_by_margin

        stop_distance_pct = stop_distance / entry_price
        risk_budget = wallet_balance * self.RISK_PER_TRADE
        max_notional_by_risk = risk_budget / stop_distance_pct

        return min(max_notional_by_margin, max_notional_by_risk)

    def on_signal_received(self, signal: TradingSignal, symbol: str = "BTCUSDT") -> None:
        """
        Handle new trading signal.

        CRITICAL FIX:
        - Per-symbol cooldown check (was global)
        - Longer cooldown after SIGNAL_REVERSAL (10 min vs 5 min)
        - Allow position flip (close + open opposite direction)
        """
        # CRITICAL FIX: Per-symbol cooldown check
        symbol_key = symbol.lower()
        if symbol_key in self._cooldowns:
            cooldown_duration = self._cooldown_durations.get(
                symbol_key, self.DEFAULT_COOLDOWN_SECONDS
            )
            time_since_close = (datetime.now() - self._cooldowns[symbol_key]).total_seconds()
            if time_since_close < cooldown_duration:
                remaining = int(cooldown_duration - time_since_close)
                logger.info(f"⏸️ COOLDOWN {symbol}: {remaining}s remaining. Signal ignored.")
                return

        # SOTA SYNC (Jan 2026): IGNORE new signals for symbols with existing pending
        # This matches backtest behavior where first entry at swing point = optimal.
        # Rationale: First signal captures exact swing point. Later signals have
        # worse entry prices as price has moved.
        pending_orders = self.repo.get_pending_orders()
        for order in pending_orders:
            if order.symbol == symbol:
                logger.info(
                    f"⏭️ Paper: IGNORING new {symbol} signal "
                    f"(keeping existing pending order {order.id})"
                )
                return  # Keep existing pending, ignore new signal

        # 1. Check existing positions
        active_positions = self.get_positions()
        for pos in active_positions:
            if pos.symbol == symbol:
                # If signal is opposite to current position
                if (pos.side == 'LONG' and signal.signal_type == SignalType.SELL) or \
                   (pos.side == 'SHORT' and signal.signal_type == SignalType.BUY):
                    logger.info(f"🔄 REVERSAL SIGNAL: Closing {pos.side} position.")
                    self.close_position(pos, signal.price, "SIGNAL_REVERSAL")

                    # CRITICAL FIX: Set per-symbol cooldown with LONGER duration for reversals
                    self._cooldowns[symbol_key] = datetime.now()
                    self._cooldown_durations[symbol_key] = self.REVERSAL_COOLDOWN_SECONDS
                    logger.info(f"⏰ Set {symbol} cooldown: {self.REVERSAL_COOLDOWN_SECONDS}s (REVERSAL)")

                    # SOTA FIX: If ALLOW_FLIP, continue to open new position
                    if not self.ALLOW_FLIP:
                        logger.info("⏹️ FLIP disabled. Not opening opposite position.")
                        return
                    else:
                        logger.info(f"↪️ FLIP enabled. Opening new {signal.signal_type.value.upper()} position.")
                        # Continue to create new position (don't return)
                        break
                else:
                    # Same side -> Allow adding to position (Merging)
                    pass

        # SOTA SYNC: Count Active + Pending (matches Backtest line 182-183)
        pending_count = len(self.repo.get_pending_orders())
        current_slots = len(active_positions) + pending_count
        if current_slots >= self.MAX_POSITIONS:
            # Only block if we are opening a NEW position (not adding to existing)
            has_position = any(p.symbol == symbol for p in active_positions)
            if not has_position:
                logger.info(f"⚠️ SKIPPED: Max slots reached ({current_slots}/{self.MAX_POSITIONS})")
                return

        # 2. Calculate Position Size (Pod Allocation - matches Backtest line 205-220)
        # SOTA SYNC: Equal capital per slot ensures consistent behavior across all modes
        wallet_balance = self.get_wallet_balance()
        capital_per_slot = wallet_balance / self.MAX_POSITIONS

        # CRITICAL FIX: get_available_balance requires current_price argument
        entry_price = signal.entry_price if signal.entry_price else signal.price
        available = self.get_available_balance(entry_price)

        # Safety: Don't exceed what's actually available
        allocated_capital = min(capital_per_slot, available)
        if allocated_capital <= 0:
            logger.info(f"⚠️ SKIPPED: No available capital (avail=${available:.2f})")
            return

        # entry_price already computed above
        if entry_price <= 0: return

        stop_loss = signal.stop_loss if signal.stop_loss else 0.0

        # Calculate notional with a real account-risk cap.
        position_size_usd = self._calculate_risk_capped_notional(
            wallet_balance=wallet_balance,
            allocated_capital=allocated_capital,
            entry_price=entry_price,
            stop_loss=stop_loss,
        )
        margin_required = position_size_usd / self.LEVERAGE

        # Calculate quantity from notional
        quantity = position_size_usd / entry_price

        # SOTA (Jan 2026): Validate min_notional (Match Backtest)
        MIN_NOTIONAL = 5.0  # $5 minimum (Binance standard)
        if position_size_usd < MIN_NOTIONAL:
            logger.info(f"⚠️ SKIPPED: notional ${position_size_usd:.2f} below min ${MIN_NOTIONAL}")
            return

        # 3. Create PENDING Position (Limit Order)
        tp1 = signal.tp_levels.get('tp1', 0.0) if signal.tp_levels else 0.0
        risk = abs(entry_price - stop_loss) if stop_loss else 0.0
        reward = abs(tp1 - entry_price) if tp1 else 0.0
        risk_reward_ratio = signal.risk_reward_ratio
        if risk_reward_ratio is None and risk > 0 and reward > 0:
            risk_reward_ratio = reward / risk

        # Calculate Liquidation Price (Binance Isolated Margin Formula)
        # SOTA SYNC: Match Backtest formula with MMR (line 603-606)
        MMR = 0.004  # Maintenance Margin Rate (0.4% - Binance standard)
        if signal.signal_type == SignalType.BUY:
            liq_price = entry_price * (1 - (1/self.LEVERAGE) + MMR)
        else:
            liq_price = entry_price * (1 + (1/self.LEVERAGE) - MMR)

        position = PaperPosition(
            id=str(uuid.uuid4()),
            symbol=symbol,
            side='LONG' if signal.signal_type == SignalType.BUY else 'SHORT',
            status="PENDING",  # Wait for price
            entry_price=entry_price,
            quantity=quantity,
            leverage=self.LEVERAGE,
            margin=margin_required,
            liquidation_price=liq_price,
            stop_loss=stop_loss,
            take_profit=tp1,
            open_time=datetime.now(),
            # SOTA (Jan 2026): Pass ATR for trailing stop (match Backtest)
            atr=signal.indicators.get('atr', 0.0) if signal.indicators else 0.0,
            signal_id=signal.id,
            confidence=signal.confidence,
            confidence_level=signal.confidence_level.value,
            risk_reward_ratio=risk_reward_ratio
        )

        self.repo.save_order(position)
        self._mark_signal_pending(signal.id)

        # SOTA SYNC: Lock margin immediately (matches Backtest line 277)
        self._locked_in_orders += margin_required

        logger.info(f"⏳ PENDING {position.side} {position.symbol} @ {position.entry_price:.2f} | Size: ${position_size_usd:.2f} | Margin: ${margin_required:.2f}")

    def close_position(self, position: PaperPosition, exit_price: float, reason: str) -> None:
        """
        Close a position and update Wallet Balance.

        CRITICAL FIX: Sets per-symbol cooldown based on exit reason.
        """
        pnl = position.calculate_unrealized_pnl(exit_price)

        # SOTA (Jan 2026): Deduct exit fee (Taker - market/SL/TP)
        notional = exit_price * position.quantity
        exit_fee = notional * self.TAKER_FEE_PCT
        pnl -= exit_fee
        logger.debug(f"💸 Exit fee: ${exit_fee:.4f} (0.05% of ${notional:.2f})")

        position.status = 'CLOSED'
        position.close_time = datetime.now()
        position.realized_pnl = (position.realized_pnl or 0.0) + pnl
        position.exit_reason = reason

        # Update DB
        self.repo.update_order(position)

        # SOTA SYNC: Release margin when position closes (matches Backtest logic)
        self._used_margin -= position.margin
        self._used_margin = max(0.0, self._used_margin)  # Safety: never go negative

        # Update Wallet Balance
        current_balance = self.repo.get_account_balance()
        self.repo.update_account_balance(current_balance + pnl)

        # CRITICAL FIX: Set per-symbol cooldown based on exit reason
        symbol_key = position.symbol.lower()
        self._cooldowns[symbol_key] = datetime.now()

        # Longer cooldown for reversals (indicates ranging market)
        if reason == "SIGNAL_REVERSAL":
            self._cooldown_durations[symbol_key] = self.REVERSAL_COOLDOWN_SECONDS
        else:
            self._cooldown_durations[symbol_key] = self.DEFAULT_COOLDOWN_SECONDS

        # SOTA FIX (Jan 2026): Update Circuit Breaker state (matching backtest)
        if hasattr(self, 'circuit_breaker') and self.circuit_breaker:
            from datetime import timezone
            current_time = datetime.now(timezone.utc)
            self.circuit_breaker.record_trade_with_time(
                position.symbol.upper(),
                position.side,  # 'LONG' or 'SHORT'
                pnl,
                current_time
            )
            logger.debug(f"🛡️ CB updated: {position.symbol} {position.side} PnL=${pnl:.2f}")

        logger.info(
            f"💰 CLOSED {position.side} | PnL: ${pnl:.2f} | Reason: {reason} | "
            f"Cooldown: {self._cooldown_durations.get(symbol_key, 300)}s"
        )

    def close_position_by_id(self, position_id: str, current_price: float, reason: str = "MANUAL_CLOSE") -> bool:
        """Close a position by its ID"""
        position = self.repo.get_order(position_id)
        if position and position.status == 'OPEN':
            self.close_position(position, current_price, reason)

            # ISSUE-001 Fix: Notify state machine of manual close
            if self.on_position_closed:
                try:
                    self.on_position_closed(position_id, reason)
                except Exception as e:
                    logger.error(f"Error in on_position_closed callback: {e}")
            return True
        return False

    def reset_account(self) -> None:
        """Reset paper trading account and data"""
        self.repo.reset_database()
        logger.info("🔄 PAPER TRADING RESET: Database cleared and balance reset to $10,000")

    def process_market_data(self, current_price: float, high: float, low: float, symbol: str) -> None:
        """
        1. Check PENDING orders -> Fill if price hit (Merge if needed) OR TTL Expire.
        2. Check OPEN positions -> SL/TP/Liq.

        SOTA FIX: Added 'symbol' parameter to filter processing.
        Prevents applying BTC prices to ETH positions (Cross-Talk Bug).
        """
        # A. Handle PENDING Orders (Filter by Symbol)
        all_pending = self.repo.get_pending_orders()
        pending_orders = [o for o in all_pending if o.symbol.lower() == symbol.lower()]

        TTL_SECONDS = 50 * 60 # 50 minutes (~3.3 candles of 15m) - SOTA SYNC with backtest

        for order in pending_orders:
            # Check TTL
            time_diff = (datetime.now() - order.open_time).total_seconds()
            if time_diff > TTL_SECONDS:
                logger.info(f"⏰ TTL EXPIRED: Cancelling pending order {order.id}")
                order.status = 'CANCELLED'
                order.exit_reason = 'TTL_EXPIRED'
                order.close_time = datetime.now()
                self.repo.update_order(order)
                self._mark_signal_expired(order.signal_id)
                continue

            is_filled = False
            if order.side == 'LONG':
                # Buy Limit: Low <= Entry
                if low <= order.entry_price:
                    is_filled = True
            elif order.side == 'SHORT':
                # Sell Limit: High >= Entry
                if high >= order.entry_price:
                    is_filled = True

            if is_filled:
                # SOTA (Jan 2026): Deduct entry fee (Maker - limit order)
                notional = order.entry_price * order.quantity
                entry_fee = notional * self.MAKER_FEE_PCT
                current_balance = self.repo.get_account_balance()
                self.repo.update_account_balance(current_balance - entry_fee)
                logger.debug(f"💸 Entry fee: ${entry_fee:.4f} (0.02% of ${notional:.2f})")

                # MERGE LOGIC (One-way Mode)
                existing_positions = [p for p in self.get_positions() if p.symbol == order.symbol and p.side == order.side]

                if existing_positions:
                    # Merge into existing position
                    parent_pos = existing_positions[0]

                    total_qty = parent_pos.quantity + order.quantity
                    total_margin = parent_pos.margin + order.margin

                    # Weighted Average Entry Price
                    avg_entry = ((parent_pos.entry_price * parent_pos.quantity) + (order.entry_price * order.quantity)) / total_qty

                    # Update Parent Position
                    parent_pos.entry_price = avg_entry
                    parent_pos.quantity = total_qty
                    parent_pos.margin = total_margin
                    parent_pos.realized_pnl = (parent_pos.realized_pnl or 0.0) - entry_fee

                    # Recalculate Liquidation Price
                    if parent_pos.side == 'LONG':
                        parent_pos.liquidation_price = avg_entry - (total_margin / total_qty)
                    else:
                        parent_pos.liquidation_price = avg_entry + (total_margin / total_qty)

                    self.repo.update_order(parent_pos)

                    # Mark Pending Order as MERGED (Closed)
                    order.status = 'CLOSED'
                    order.exit_reason = 'MERGED'
                    order.close_time = datetime.now()
                    self.repo.update_order(order)
                    self._mark_signal_executed(order.signal_id, order.id)

                    logger.info(f"🔗 MERGED {order.side} {order.symbol} | New Avg Entry: {avg_entry:.2f}")

                else:
                    # No existing position -> Promote to OPEN
                    order.status = 'OPEN'
                    order.open_time = datetime.now() # Update fill time
                    # Store initial quantity for partial TP
                    order.initial_quantity = order.quantity
                    order.realized_pnl = (order.realized_pnl or 0.0) - entry_fee
                    self.repo.update_order(order)
                    self._mark_signal_executed(order.signal_id, order.id)
                    logger.info(f"✅ FILLED {order.side} {order.symbol} @ {order.entry_price} (fee: ${entry_fee:.4f})")

                    # ISSUE-001 Fix: Notify state machine of order fill
                    if self.on_order_filled:
                        try:
                            self.on_order_filled(order.id)
                        except Exception as e:
                            logger.error(f"Error in on_order_filled callback: {e}")

        # B. Handle OPEN Positions (Filter by Symbol)
        all_positions = self.get_positions()
        active_positions = [p for p in all_positions if p.symbol.lower() == symbol.lower()]

        for pos in active_positions:
            exit_price = None
            reason = None

            # --- TRAILING STOP LOGIC (TUNED) ---
            # 1. Update High/Low Watermark
            if pos.side == 'LONG':
                if pos.highest_price == 0 or high > pos.highest_price:
                    pos.highest_price = high
            else:
                if pos.lowest_price == 0 or low < pos.lowest_price:
                    pos.lowest_price = low

            # 2. Calculate ROI
            roe = pos.calculate_roe(current_price)

            # SOTA FIX: Breakeven Trigger (Match Backtest - 1.5×Risk)
            # Calculate initial_risk from entry and original SL
            # If SL was already moved, use entry as reference
            initial_risk = abs(pos.entry_price - pos.stop_loss) if pos.stop_loss != pos.entry_price else pos.entry_price * 0.005
            price_diff = abs(current_price - pos.entry_price)

            # Trigger breakeven at 1.5×Risk (matching Backtest)
            BREAKEVEN_TRIGGER_R = 1.5
            BREAKEVEN_BUFFER_PCT = 0.0005  # 0.05% buffer

            if price_diff >= initial_risk * BREAKEVEN_TRIGGER_R:
                buffer = pos.entry_price * BREAKEVEN_BUFFER_PCT
                if pos.side == 'LONG':
                    new_be_sl = pos.entry_price + buffer
                    if pos.stop_loss < new_be_sl:
                        pos.stop_loss = new_be_sl
                        logger.info(f"🛡️ BREAKEVEN (1.5R): {pos.symbol} SL → {new_be_sl:.4f}")
                else:
                    new_be_sl = pos.entry_price - buffer
                    if pos.stop_loss == 0 or pos.stop_loss > new_be_sl:
                        pos.stop_loss = new_be_sl
                        logger.info(f"🛡️ BREAKEVEN (1.5R): {pos.symbol} SL → {new_be_sl:.4f}")

            # SOTA FIX: Trailing Stop (Match Backtest - ATR×4)
            # Use pos.atr if available, fallback to 4×initial_risk
            TRAILING_MULT = 4.0  # Same as Backtest ATR multiplier
            trail_distance = pos.atr * TRAILING_MULT if pos.atr > 0 else initial_risk * TRAILING_MULT

            # Check if breakeven already triggered (SL at or past entry)
            breakeven_triggered = (
                (pos.side == 'LONG' and pos.stop_loss >= pos.entry_price) or
                (pos.side == 'SHORT' and pos.stop_loss > 0 and pos.stop_loss <= pos.entry_price)
            )

            if breakeven_triggered and trail_distance > 0:
                if pos.side == 'LONG':
                    # Trail: New SL = Highest - (ATR×4)
                    new_sl = pos.highest_price - trail_distance
                    if new_sl > pos.stop_loss:
                        pos.stop_loss = new_sl
                        logger.debug(f"📈 TRAILING: {pos.symbol} SL → {new_sl:.4f}")
                else:
                    # Trail: New SL = Lowest + (ATR×4)
                    if pos.lowest_price > 0:
                        new_sl = pos.lowest_price + trail_distance
                        if new_sl < pos.stop_loss:
                            pos.stop_loss = new_sl
                            logger.debug(f"📈 TRAILING: {pos.symbol} SL → {new_sl:.4f}")

            # Update Position in DB (to save SL changes)
            self.repo.update_order(pos)

            # --- EXIT LOGIC ---
            # SOTA FIX: Use independent `if` blocks instead of `elif` chain
            # Previously, when SL existed but didn't trigger, elif skipped TP check!

            # 1. Check Liquidation (highest priority)
            if pos.side == 'LONG' and low <= pos.liquidation_price:
                exit_price = pos.liquidation_price
                reason = 'LIQUIDATION'
            elif pos.side == 'SHORT' and high >= pos.liquidation_price:
                exit_price = pos.liquidation_price
                reason = 'LIQUIDATION'

            # 2. Check Stop Loss (INDEPENDENT - not elif!)
            if exit_price is None and pos.stop_loss > 0:
                if pos.side == 'LONG' and low <= pos.stop_loss:
                    exit_price = pos.stop_loss
                    reason = 'STOP_LOSS'
                elif pos.side == 'SHORT' and high >= pos.stop_loss:
                    exit_price = pos.stop_loss
                    reason = 'STOP_LOSS'

            # 3. SOTA: Partial Take Profit (60% at TP1, match Backtest)
            # Only trigger if TP1 not yet hit
            if exit_price is None and pos.take_profit > 0 and pos.tp_hit_count == 0:
                tp1_hit = False
                if pos.side == 'LONG' and high >= pos.take_profit:
                    tp1_hit = True
                elif pos.side == 'SHORT' and low <= pos.take_profit:
                    tp1_hit = True

                if tp1_hit:
                    # Close 60% of position at TP1
                    PARTIAL_TP_PCT = 0.6  # Match Backtest
                    close_qty = pos.quantity * PARTIAL_TP_PCT
                    remaining_qty = pos.quantity - close_qty

                    # Calculate PnL for partial close
                    if pos.side == 'LONG':
                        partial_pnl = (pos.take_profit - pos.entry_price) * close_qty
                    else:
                        partial_pnl = (pos.entry_price - pos.take_profit) * close_qty

                    partial_notional = pos.take_profit * close_qty
                    partial_exit_fee = partial_notional * self.TAKER_FEE_PCT
                    partial_pnl -= partial_exit_fee

                    # Update wallet balance with partial profit
                    current_balance = self.repo.get_account_balance()
                    self.repo.update_account_balance(current_balance + partial_pnl)

                    # Update position: reduce quantity, mark TP1 hit, move SL to breakeven
                    pos.margin *= (1 - PARTIAL_TP_PCT)
                    pos.quantity = remaining_qty
                    pos.tp_hit_count = 1
                    pos.realized_pnl = (pos.realized_pnl or 0.0) + partial_pnl
                    pos.stop_loss = pos.entry_price + (pos.entry_price * 0.0005 if pos.side == 'LONG' else -pos.entry_price * 0.0005)  # Small buffer

                    # Log partial close
                    logger.info(
                        f"🎯 PARTIAL TP1 (60%): {pos.symbol} @ {pos.take_profit:.4f} | "
                        f"PnL: ${partial_pnl:.2f} | Fee: ${partial_exit_fee:.4f} | "
                        f"Remaining: {remaining_qty:.4f}"
                    )

                    # Update DB
                    self.repo.update_order(pos)

                    # Don't set exit_price - position continues with remaining quantity

            if exit_price:
                self.close_position(pos, exit_price, reason)

                # ISSUE-001 Fix: Notify state machine of position close
                if self.on_position_closed:
                    try:
                        self.on_position_closed(pos.id, reason)
                    except Exception as e:
                        logger.error(f"Error in on_position_closed callback: {e}")

    # ==================== NEW METHODS FOR DESKTOP APP ====================

    def get_portfolio(self, current_price: float = 0.0) -> Portfolio:
        """
        Get current portfolio state.

        Args:
            current_price: Current market price for PnL calculation

        Returns:
            Portfolio object with balance, equity, positions
        """
        balance = self.get_wallet_balance()
        positions = self.get_positions()
        unrealized_pnl = self.calculate_unrealized_pnl(current_price) if current_price > 0 else 0.0

        # Calculate realized PnL from closed trades
        closed_trades = self.repo.get_closed_orders(limit=1000)
        realized_pnl = sum(t.realized_pnl for t in closed_trades)

        equity = balance + unrealized_pnl

        return Portfolio(
            balance=balance,
            equity=equity,
            unrealized_pnl=unrealized_pnl,
            realized_pnl=realized_pnl,
            open_positions=positions
        )

    def get_trade_history(
        self, page: int = 1, limit: int = 20,
        symbol: Optional[str] = None,
        side: Optional[str] = None,
        pnl_filter: Optional[str] = None
    ) -> PaginatedTrades:
        """
        Get paginated trade history with optional filters.

        SOTA Phase 24c: Server-side filtering support.

        Args:
            page: Page number (1-indexed)
            limit: Items per page
            symbol: Optional filter by symbol
            side: Optional filter by side ('LONG'/'SHORT')
            pnl_filter: Optional 'profit' or 'loss' filter

        Returns:
            PaginatedTrades with trades and pagination info
        """
        trades, total = self.repo.get_closed_orders_paginated(
            page, limit, symbol=symbol, side=side, pnl_filter=pnl_filter
        )
        total_pages = (total + limit - 1) // limit  # Ceiling division

        return PaginatedTrades(
            trades=trades,
            total=total,
            page=page,
            limit=limit,
            total_pages=total_pages
        )

    def calculate_performance(self, days: int = 7) -> PerformanceMetrics:
        """
        Calculate performance metrics for the specified period.

        Args:
            days: Number of days to analyze (default: 7)

        Returns:
            PerformanceMetrics object
        """
        # Get all closed trades (we'll filter by date)
        all_trades = self.repo.get_closed_orders(limit=10000)

        # Filter by date range
        cutoff_date = datetime.now() - timedelta(days=days)
        recent_trades = [
            t for t in all_trades
            if t.close_time and t.close_time >= cutoff_date
        ]

        return PerformanceMetrics.calculate_from_trades(recent_trades)

    # ==================== SETTINGS METHODS ====================

    def get_settings(self) -> dict:
        """Get all trading settings"""
        settings = self.repo.get_all_settings()
        blocked_windows_raw = settings.get("blocked_windows", PRODUCTION_BLOCKED_WINDOWS_STR)
        try:
            blocked_windows = parse_blocked_windows(blocked_windows_raw) if blocked_windows_raw else []
        except ValueError:
            blocked_windows = []

        def as_bool(key: str, default: bool) -> bool:
            raw = settings.get(key, "true" if default else "false")
            return str(raw).strip().lower() in {"1", "true", "yes", "on"}

        # Return defaults aligned with the documented production contract.
        return {
            'risk_percent': float(settings.get('risk_percent', str(PRODUCTION_RISK_PER_TRADE * 100))),
            'max_positions': int(settings.get('max_positions', str(PRODUCTION_MAX_POSITIONS))),
            'leverage': clamp_runtime_leverage(settings.get('leverage', PRODUCTION_LEVERAGE)),
            'auto_execute': as_bool('auto_execute', False),
            'execution_ttl_minutes': int(
                settings.get('execution_ttl_minutes', str(PRODUCTION_ORDER_TTL_MINUTES))
            ),
            'smart_recycling': as_bool('smart_recycling', False),      # Default False (TTL45 Standard)
            # SOTA (Jan 2026): Auto-Close Profitable Positions
            'close_profitable_auto': as_bool('close_profitable_auto', PRODUCTION_CLOSE_PROFITABLE_AUTO),
            'profitable_threshold_pct': float(
                settings.get('profitable_threshold_pct', str(PRODUCTION_PROFITABLE_THRESHOLD_PCT))
            ),
            'auto_close_interval': settings.get('auto_close_interval', PRODUCTION_AUTO_CLOSE_INTERVAL),
            # SOTA (Jan 2026): Portfolio Target
            'portfolio_target_pct': float(
                settings.get('portfolio_target_pct', str(PRODUCTION_PORTFOLIO_TARGET_PCT))
            ),
            'max_consecutive_losses': int(
                settings.get('max_consecutive_losses', str(PRODUCTION_CB_MAX_CONSECUTIVE_LOSSES))
            ),
            'cooldown_minutes': float(settings.get('cooldown_minutes', "0")),
            'daily_symbol_loss_limit': int(settings.get('daily_symbol_loss_limit', "0")),
            'blocked_windows': blocked_windows,
            'blocked_windows_enabled': as_bool('blocked_windows_enabled', bool(blocked_windows)),
            'blocked_windows_utc_offset': int(settings.get('blocked_windows_utc_offset', "7")),
            'max_daily_drawdown_pct': float(
                settings.get('max_daily_drawdown_pct', str(PRODUCTION_CB_MAX_DAILY_DRAWDOWN_PCT))
            ),
            'dz_force_close_enabled': as_bool('dz_force_close_enabled', False),
            'order_type': settings.get('order_type', PRODUCTION_ORDER_TYPE),
            'limit_chase_timeout_seconds': int(
                settings.get('limit_chase_timeout_seconds', str(PRODUCTION_LIMIT_CHASE_TIMEOUT_SECONDS))
            ),
            # NOTE: rr_ratio removed - backtest uses SL/TP from strategy signal
        }

    def update_settings(self, settings: dict) -> dict:
        """
        Update trading settings.

        Args:
            settings: Dict with setting keys and values

        Returns:
            Updated settings dict
        """
        # SOTA (Jan 2026): Include auto-close and portfolio target settings
        allowed_keys = [
            'risk_percent', 'max_positions', 'leverage', 'auto_execute',
            'execution_ttl_minutes', 'smart_recycling',
            'close_profitable_auto', 'profitable_threshold_pct', 'auto_close_interval',
            'portfolio_target_pct', 'max_consecutive_losses', 'cooldown_minutes',
            'daily_symbol_loss_limit', 'blocked_windows', 'blocked_windows_enabled',
            'blocked_windows_utc_offset', 'max_daily_drawdown_pct',
            'dz_force_close_enabled', 'order_type', 'limit_chase_timeout_seconds'
        ]

        for key, value in settings.items():
            if key in allowed_keys:
                if key == 'leverage':
                    value = clamp_runtime_leverage(value)
                # Convert bool to string for storage
                if isinstance(value, bool):
                    value = 'true' if value else 'false'
                self.repo.set_setting(key, str(value))

                # Apply to service immediately
                if key == 'risk_percent':
                    self.RISK_PER_TRADE = float(value) / 100
                elif key == 'max_positions':
                    self.MAX_POSITIONS = int(value)
                elif key == 'leverage':
                    self.LEVERAGE = int(value)

        logger.info(f"📝 Settings updated: {settings}")
        return self.get_settings()

    def execute_trade(self, signal: TradingSignal, symbol: str = "BTCUSDT") -> Optional[str]:
        """
        Execute a trade from a signal (wrapper for on_signal_received).

        Args:
            signal: Trading signal to execute
            symbol: Trading symbol

        Returns:
            Position ID if created, None otherwise
        """
        # Store current position count
        before_count = len(self.get_positions()) + len(self.repo.get_pending_orders())

        # Execute via existing method
        self.on_signal_received(signal, symbol)

        # Check if new position was created
        after_count = len(self.get_positions()) + len(self.repo.get_pending_orders())

        if after_count > before_count:
            # Return the latest pending order ID
            pending = self.repo.get_pending_orders()
            if pending:
                return pending[-1].id

        return None
