"""
SOTA Local Position Tracker (Jan 2026)

Pattern: Two Sigma, Citadel, Jane Street
- Never trust exchange APIs for trading decisions
- Track every fill locally with exact prices and fees
- Calculate volume-weighted averages
- Use ACTUAL leverage confirmed by exchange
"""

from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class FillRecord:
    """
    Single fill record with exact data from exchange.

    Attributes:
        timestamp: When fill occurred
        order_id: Exchange order ID
        price: Exact fill price
        quantity: Exact fill quantity
        fee: Fee charged for this fill
        fee_asset: Asset used to pay fee (usually USDT)
        is_maker: True if maker order (lower fee)
    """
    timestamp: datetime
    order_id: str
    price: float
    quantity: float
    fee: float
    fee_asset: str = 'USDT'
    is_maker: bool = False


@dataclass
class LocalPosition:
    """
    SOTA Local Position Tracker (Feb 2026).

    Institutional Pattern (Two Sigma, Citadel):
    - Track every fill locally, never trust exchange for PnL
    - Calculate volume-weighted average entry
    - Use ACTUAL leverage confirmed by exchange
    - Separate unrealized vs realized PnL (SOTA Feb 2026)

    Why Local Tracking:
    - Exchange APIs have lag (100-500ms)
    - Exchange PnL excludes fees or uses estimates
    - Exchange uses wrong leverage assumptions
    - Exchange uses markPrice (not fillable price)

    PnL Methods (SOTA Feb 2026):
    - get_unrealized_pnl(): For OPEN positions - deducts entry fee only
      (matches Binance REST API behavior)
    - get_realized_pnl(): For CLOSED positions - deducts both fees

    Usage:
        pos = LocalPosition(symbol='BTCUSDT', side='LONG', intended_leverage=20)
        pos.add_entry_fill(FillRecord(...))
        pos.set_actual_leverage(10)  # From exchange confirmation

        # While position is OPEN:
        pnl = pos.get_unrealized_pnl(current_price)
        roe = pos.get_roe_percent(current_price)

        # After position CLOSES:
        final_pnl = pos.get_realized_pnl(exit_price)
    """

    symbol: str
    side: str  # 'LONG' or 'SHORT'
    intended_leverage: int  # What we requested (e.g. 20)
    actual_leverage: Optional[int] = None  # What exchange actually uses

    # Fill tracking
    entry_fills: List[FillRecord] = field(default_factory=list)
    exit_fills: List[FillRecord] = field(default_factory=list)

    # Calculated values (cached)
    _avg_entry_price: Optional[float] = None
    _total_entry_cost: float = 0.0
    _total_entry_qty: float = 0.0
    _total_entry_fees: float = 0.0
    _actual_margin_used: Optional[float] = None
    _net_quantity: Optional[float] = None
    _cached_realized_pnl: Optional[float] = None  # Saved when exit fills arrive (before qty→0)

    # Metadata
    signal_id: Optional[str] = None  # Signal UUID for notification tracking
    opened_at: datetime = field(default_factory=datetime.now)
    closed_at: Optional[datetime] = None

    # Signal metadata (v5.5.0): For comprehensive CSV tracking
    signal_confidence: Optional[float] = None
    signal_entry_target: Optional[float] = None
    signal_sl: Optional[float] = None
    signal_tp1: Optional[float] = None
    signal_time: Optional[str] = None

    @property
    def avg_entry_price(self) -> float:
        """Public accessor for average entry price."""
        return self._avg_entry_price if self._avg_entry_price is not None else 0.0

    @property
    def quantity(self) -> float:
        """Public accessor for NET quantity (Entry - Exit)."""
        if self._net_quantity is None:
            self._recalculate_net()
        return self._net_quantity

    @property
    def total_quantity(self) -> float:
        """
        Public accessor for TOTAL entry quantity (before any exits).

        SOTA FIX (Feb 2026): Added property to fix AttributeError in portfolio PnL callback.
        This is the total quantity entered, not accounting for partial exits.
        For net quantity (entry - exit), use the `quantity` property instead.

        Returns:
            Total entry quantity (float)
        """
        return self._total_entry_qty

    def add_entry_fill(self, fill: FillRecord) -> None:
        """
        Record entry fill and recalculate averages.

        SOTA FIX (Feb 10, 2026): Dedup by order_id to prevent double-counting
        if Binance sends duplicate WebSocket ORDER_TRADE_UPDATE events.

        Args:
            fill: Fill record from exchange
        """
        # Dedup: reject if same order_id + same quantity already recorded
        for existing in self.entry_fills:
            if existing.order_id == fill.order_id and abs(existing.quantity - fill.quantity) < 1e-10:
                logger.warning(
                    f"DEDUP: Duplicate entry fill rejected for {self.symbol} | "
                    f"order_id={fill.order_id}, qty={fill.quantity:.6f}"
                )
                return

        self.entry_fills.append(fill)
        self._recalculate_entry()

        logger.debug(
            f"Fill added: {self.symbol} | "
            f"Price: ${fill.price:.6f} | "
            f"Qty: {fill.quantity:.2f} | "
            f"Fee: ${fill.fee:.4f} | "
            f"Total fills: {len(self.entry_fills)}"
        )

    def add_exit_fill(self, fill: FillRecord) -> None:
        """
        Record exit fill (partial or full).

        SOTA FIX (Feb 9, 2026): Cache realized PnL BEFORE adding fill.
        SOTA FIX (Feb 10, 2026): Dedup by order_id to prevent double-counting.
        v6.1.0 FIX (Feb 11, 2026): Cumulative quantity dedup — fixes ghost close bug.

        Args:
            fill: Fill record from exchange
        """
        # v6.1.0 FIX: Cumulative quantity dedup (replaces order_id+qty dedup)
        # OLD BUG: Dedup used (order_id, qty) as key — failed when exchange splits
        # a MARKET order into equal-sized partial fills (e.g. 2×6 for 12 total).
        # Both fills had identical (order_id, qty) → second fill rejected →
        # is_fully_closed never true → position orphaned (invisible to system).
        # NEW: Reject fill only if position is already fully exited.
        total_entry_qty = sum(f.quantity for f in self.entry_fills)
        current_exit_qty = sum(f.quantity for f in self.exit_fills)
        if total_entry_qty > 0 and current_exit_qty >= total_entry_qty - 1e-10:
            logger.warning(
                f"DEDUP: Exit fill rejected for {self.symbol} | "
                f"Position already fully exited: exit_qty={current_exit_qty:.6f} >= "
                f"entry_qty={total_entry_qty:.6f} | fill order_id={fill.order_id}"
            )
            return

        # Cache realized PnL BEFORE quantity changes
        if self._avg_entry_price and self.quantity > 0:
            self._cached_realized_pnl = self.get_realized_pnl(fill.price)

        self.exit_fills.append(fill)
        self._recalculate_net()

        logger.debug(
            f"Exit Fill added: {self.symbol} | "
            f"Price: ${fill.price:.6f} | "
            f"Qty: {fill.quantity:.2f} | "
            f"Remaining Net Qty: {self._net_quantity:.2f} | "
            f"Cached PnL: ${self._cached_realized_pnl:.2f}" if self._cached_realized_pnl else
            f"Exit Fill added: {self.symbol} | "
            f"Price: ${fill.price:.6f} | "
            f"Qty: {fill.quantity:.2f} | "
            f"Remaining Net Qty: {self._net_quantity:.2f}"
        )

    def _recalculate_entry(self) -> None:
        """Calculate volume-weighted average entry price."""
        if not self.entry_fills:
            return

        # Volume-weighted average price
        total_cost = sum(f.price * f.quantity for f in self.entry_fills)
        total_qty = sum(f.quantity for f in self.entry_fills)
        total_fees = sum(f.fee for f in self.entry_fills)

        self._total_entry_cost = total_cost
        self._total_entry_qty = total_qty
        self._total_entry_fees = total_fees

        if total_qty > 0:
            self._avg_entry_price = total_cost / total_qty

            logger.debug(
                f"Entry recalculated: {self.symbol} | "
                f"Avg: ${self._avg_entry_price:.6f} | "
                f"Qty: {total_qty:.2f} | "
                f"Cost: ${total_cost:.2f} | "
                f"Fees: ${total_fees:.2f}"
            )

        # Also update net
        self._recalculate_net()

    def _recalculate_net(self) -> None:
        """Calculate net quantity (Entry - Exit)."""
        total_entry = sum(f.quantity for f in self.entry_fills)
        total_exit = sum(f.quantity for f in self.exit_fills)

        self._net_quantity = total_entry - total_exit

        # Prevent negative quantity (floating point errors)
        if self._net_quantity < 0.0000001:
            self._net_quantity = 0.0

    def set_actual_leverage(self, leverage: int) -> None:
        """
        Set CONFIRMED leverage from exchange.

        CRITICAL: May differ from intended leverage!
        Example: Requested 20x but exchange uses 10x.

        Args:
            leverage: Actual leverage confirmed by exchange
        """
        if leverage <= 0:
            logger.error(f"Invalid leverage: {leverage}, must be > 0")
            return

        self.actual_leverage = leverage

        # Calculate actual margin used
        if self._avg_entry_price and self._total_entry_qty:
            notional = self._avg_entry_price * self._total_entry_qty
            self._actual_margin_used = notional / leverage

            logger.info(
                f"✅ Leverage confirmed: {self.symbol} = {leverage}x | "
                f"Intended: {self.intended_leverage}x | "
                f"Margin: ${self._actual_margin_used:.2f}"
            )

    def get_unrealized_pnl(self, current_price: float) -> float:
        """
        Calculate LOCAL unrealized PnL (entry fee only).

        SOTA FIX (Feb 2026): Only deduct ENTRY fee (already paid).
        Do NOT deduct exit fee - it hasn't occurred yet!

        This matches Binance REST API `/fapi/v2/positionRisk` behavior,
        which returns mark-price-based unrealized PnL without exit fees.

        Formula:
            LONG: (current - entry) × qty - entry_fee
            SHORT: (entry - current) × qty - entry_fee

        Fee: 0.05% taker fee (Binance VIP 0 standard rate)

        For REALIZED PnL (after position closes), use get_realized_pnl().

        Args:
            current_price: Current market price

        Returns:
            Unrealized profit/loss in USDT (negative = loss)
        """
        if not self._avg_entry_price or self._total_entry_qty == 0:
            return 0.0

        # Price difference
        if self.side == 'LONG':
            price_diff = current_price - self._avg_entry_price
        else:  # SHORT
            price_diff = self._avg_entry_price - current_price

        # Gross P&L (before fees) based on REMAINING (NET) Quantity
        gross_pnl = price_diff * self.quantity

        # SOTA FIX (Feb 2026): Only deduct ENTRY fee (already paid)
        # Exit fee is NOT deducted - position is still open!
        TAKER_FEE_RATE = 0.0005  # 0.05% (Binance VIP 0 taker rate)

        entry_notional = self._avg_entry_price * self.quantity
        entry_fee = entry_notional * TAKER_FEE_RATE

        # Unrealized PnL = Gross - Entry Fee (exit fee not yet incurred)
        unrealized_pnl = gross_pnl - entry_fee

        return unrealized_pnl

    def get_realized_pnl(self, exit_price: float) -> float:
        """
        Calculate REALIZED PnL after position closes (includes both fees).

        SOTA (Feb 2026): Use this for closed positions.
        Includes BOTH entry fee (paid at open) and exit fee (paid at close).

        SOTA FIX (Feb 9, 2026): Return cached PnL if quantity already zeroed.
        WebSocket fill events arrive and call add_exit_fill() BEFORE close
        functions can call this method. The cached value was computed
        when quantity was still > 0.

        Formula:
            LONG: (exit - entry) × qty - entry_fee - exit_fee
            SHORT: (entry - exit) × qty - entry_fee - exit_fee

        Args:
            exit_price: Price at which position was closed

        Returns:
            Realized profit/loss in USDT (negative = loss)
        """
        if not self._avg_entry_price or self._total_entry_qty == 0:
            return 0.0

        # If quantity already zeroed by exit fills, return cached PnL
        if self.quantity == 0 and self._cached_realized_pnl is not None:
            return self._cached_realized_pnl

        # Price difference
        if self.side == 'LONG':
            price_diff = exit_price - self._avg_entry_price
        else:  # SHORT
            price_diff = self._avg_entry_price - exit_price

        # Gross P&L
        gross_pnl = price_diff * self.quantity

        # Both entry and exit fees
        TAKER_FEE_RATE = 0.0005  # 0.05%

        entry_notional = self._avg_entry_price * self.quantity
        exit_notional = exit_price * self.quantity

        entry_fee = entry_notional * TAKER_FEE_RATE
        exit_fee = exit_notional * TAKER_FEE_RATE

        # Realized PnL = Gross - Entry Fee - Exit Fee
        realized_pnl = gross_pnl - entry_fee - exit_fee

        return realized_pnl

    def get_roe_percent(self, current_price: float) -> float:
        """
        Calculate ROE using ACTUAL margin.

        Formula:
            ROE% = (unrealized_pnl / actual_margin) × 100

        SOTA FIX (Feb 2026): Use ACTUAL leverage if available, fallback to intended.
        BUG FIX #2: Critical bug - was using intended_leverage instead of actual_leverage!

        Args:
            current_price: Current market price

        Returns:
            ROE percentage (positive = profit, negative = loss)
        """
        # SOTA FIX (Feb 2026): Use ACTUAL leverage if available, fallback to intended
        # Critical: Exchange may use different leverage than requested!
        # Example: Requested 10x but exchange uses 20x → Must use 20x for ROE
        margin_to_use = self._actual_margin_used

        if not margin_to_use or margin_to_use == 0:
            # BUG FIX #2: Use actual_leverage if confirmed, otherwise fallback to intended
            leverage_to_use = self.actual_leverage if self.actual_leverage else self.intended_leverage

            if leverage_to_use > 0 and self._avg_entry_price and self._total_entry_qty:
                notional = self._avg_entry_price * self._total_entry_qty
                margin_to_use = notional / leverage_to_use

                # Log which leverage was used for debugging
                if self.actual_leverage:
                    logger.debug(f"{self.symbol}: Using actual_leverage {self.actual_leverage}x for ROE")
                else:
                    logger.debug(f"{self.symbol}: Using intended_leverage {self.intended_leverage}x for ROE (actual not set)")
            else:
                return 0.0

        pnl = self.get_unrealized_pnl(current_price)
        roe = (pnl / margin_to_use) * 100

        return roe

    def get_summary(self, current_price: float) -> dict:
        """
        Get detailed position summary for logging/debugging.

        Args:
            current_price: Current market price

        Returns:
            Dictionary with all position details
        """
        return {
            'symbol': self.symbol,
            'side': self.side,
            'signal_id': self.signal_id,
            'opened_at': self.opened_at.isoformat(),
            'entry_fills_count': len(self.entry_fills),
            'avg_entry_price': self._avg_entry_price,
            'total_quantity': self._total_entry_qty,
            'total_entry_cost': self._total_entry_cost,
            'total_entry_fees': self._total_entry_fees,
            'intended_leverage': self.intended_leverage,
            'actual_leverage': self.actual_leverage,
            'actual_margin': self._actual_margin_used,
            'current_price': current_price,
            'unrealized_pnl': self.get_unrealized_pnl(current_price),
            'roe_percent': self.get_roe_percent(current_price),
        }

    def __repr__(self) -> str:
        return (
            f"LocalPosition(symbol={self.symbol}, side={self.side}, "
            f"entry={'${:.6f}'.format(self._avg_entry_price) if self._avg_entry_price else 'N/A'}, "
            f"qty={self._total_entry_qty:.2f}, "
            f"leverage={self.actual_leverage or self.intended_leverage}x)"
        )
