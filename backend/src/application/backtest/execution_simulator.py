"""
ExecutionSimulator - Application Layer

Simulates professional trade execution for backtesting.
SOTA Updates 2026.01.02:
1. "Hardcore Reality Mode": Liquidation Logic & Tier 1 Vol Cap.
2. Entry-based Leverage Calculation.
3. Semantic Exit Reasoning.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from ...domain.entities.candle import Candle
from ...domain.entities.trading_signal import TradingSignal, SignalType


@dataclass
class BacktestTrade:
    """Represents a completed trade with institutional reporting fields."""
    trade_id: str
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    pnl_usd: float
    pnl_pct: float
    exit_reason: str
    position_size: float
    notional_value: float = 0.0
    leverage_at_entry: float = 0.0
    # SOTA: Margin tracking for balance verification
    margin_at_entry: float = 0.0  # Available balance when position was opened
    # SOTA: Funding rate cost/revenue tracking
    # SOTA: Funding rate cost/revenue tracking
    funding_cost: float = 0.0  # Total funding paid/received during position hold
    # SOTA: Balance Snapshot
    balance_at_exit: float = 0.0
    # MFE/MAE: Peak ROE reached during trade lifetime
    peak_roe_pct: float = 0.0  # Maximum favorable excursion (highest ROE before close)
    entry_fee_paid: float = 0.0
    exit_fee_paid: float = 0.0
    entry_liquidity: str = ""
    exit_liquidity: str = ""


class ExecutionSimulator:
    """
    Simulates trade execution with Institutional-Grade constraints.
    Now includes BINANCE LIQUIDATION LOGIC & LIQUIDITY CAPS.
    """

    @staticmethod
    def _build_tp_levels(is_long: bool, tp1: float) -> Dict[str, float]:
        """Keep TP ladders monotonic for both directions."""
        if is_long:
            return {'tp1': tp1, 'tp2': tp1 * 1.05, 'tp3': tp1 * 1.10}
        return {'tp1': tp1, 'tp2': tp1 * 0.95, 'tp3': tp1 * 0.90}

    def __init__(
        self,
        initial_balance: float = 10000.0,
        # SOTA: Separate maker/taker fees (Binance Futures VIP 0)
        maker_fee_pct: float = 0.02,   # 0.02% for limit orders (maker)
        taker_fee_pct: float = 0.05,   # 0.05% for market/SL/TP (taker)
        slippage_pct: float = 0.02,
        risk_per_trade: float = 0.01,
        breakeven_trigger_r: float = 1.0,  # PARITY SYNC: Match LIVE (1.0R) - Jan 31 2026
        trailing_stop_atr: float = 4.0,
        fixed_leverage: float = 0.0,
        mode: str = "ISOLATED",
        max_leverage: float = 5.0,
        max_positions: int = 3,
        # NEW: Hardcore Reality Configs
        max_order_value: float = 50000.0, # Tier 1 Cap
        maintenance_margin_rate: float = 0.004, # 0.4%
        # SOTA: Funding Rate Simulation
        enable_funding_rate: bool = True,
        default_funding_rate: float = 0.01,  # 0.01% per 8 hours (typical)
        funding_rates: Dict[str, float] = None,  # Per-symbol static funding rates (fallback)
        funding_loader = None,  # FundingHistoryLoader for historical rates
        # SOTA: Per-Symbol Exchange Rules (from market_intelligence.json)
        symbol_rules: Dict[str, Dict[str, Any]] = None,  # {symbol: {max_leverage, min_qty, step_size, min_notional}}
        # SOTA: Order TTL (Time-To-Live) - 0 = GTC (Good Till Cancel), default for backtest
        # Paper/Testnet/Live use LocalSignalTracker with TTL (45 min default)
        order_ttl_minutes: int = 0,  # 0 = unlimited (GTC), >0 = cancel after N minutes
        # SOTA: Zombie Killer - Replace pending orders with new signals (matches Paper/Live)
        # Default OFF to preserve existing backtest results
        use_zombie_killer: bool = False,
        # SOTA: Full Take Profit at TP1 (Optional)
        full_tp_at_tp1: bool = False,
        # SOTA (Jan 2026): Pessimistic Fill Model - require price overshoot for fill
        # This matches institutional standards (Two Sigma, Renaissance)
        # 0.001 = 0.1% buffer beyond target price required for fill confirmation
        pessimistic_fill_buffer_pct: float = 0.001,
        # EXPERIMENTAL (Jan 2026): Block SHORT signals early (Layer 1+2) for hypothesis testing
        # When True, mimics LIVE OLD behavior to test overtrading hypothesis
        block_short_early: bool = False,
        # SOTA (Jan 2026): Time-Based Exit for Long-Duration Losing Trades
        # Based on institutional research (Renaissance, Two Sigma, Citadel)
        # When enabled, exits positions that exceed duration threshold AND are losing
        # Default OFF to preserve existing backtest results
        enable_time_based_exit: bool = False,
        time_based_exit_duration_hours: float = 2.0,  # Exit if duration > 2h AND loss
        # SOTA (Jan 2026): Fixed Profit Per Trade Strategy
        # Experimental approach: Exit when profit reaches $3 per trade
        # Purpose: Test if fixed profit targets improve consistency
        # Default OFF to preserve existing backtest results
        use_fixed_profit_3usd: bool = False,
        # SOTA (Jan 2026): Backtest Replay Event Recording
        # If True, records granular events for UI Replay (Queue state, Rejections)
        capture_events: bool = False,
        # SOTA (Jan 2026): Portfolio Profit Target
        # Exit all positions when total unrealized PnL reaches target
        # Institutional practice: Renaissance (0.5-1% daily), Two Sigma, Citadel
        portfolio_target: float = 0.0,  # 0 = disabled, >0 = target in USD
        portfolio_target_pct: float = 0.0,  # 0 = disabled, >0 = target as % of capital
        # SOTA (Jan 2026): Signal Reversal Exit
        # Exit position when high-confidence opposite signal appears
        # Institutional practice: Jane Street (85-95%), Citadel, Jump Trading
        enable_reversal_exit: bool = False,
        reversal_confidence: float = 0.90,  # Minimum confidence for reversal exit
        # EXPERIMENTAL (Jan 2026): Auto-Close Profitable Positions
        # Strategy: "Take profits early, let losses recover"
        # When enabled, automatically closes positions when ROE > threshold
        close_profitable_auto: bool = False,
        profitable_threshold_pct: float = 5.0,  # ROE threshold in percentage (SYNC: Match backtest --profitable-threshold-pct 5)
        profitable_check_interval: int = 1,  # Check every N candles (default 1 = every candle)
        # SOTA (Jan 2026): MAX SL Validation - Reject signals with SL too far
        # Formula: max_sl = max_sl_pct or (10% account risk / leverage)
        # With 20x: max_sl = 0.5%. Default OFF to preserve existing results.
        use_max_sl_validation: bool = False,
        max_sl_pct: float = None,  # Custom max SL percentage (e.g., 1.5 for 1.5%)
        # SOTA (Jan 2026): Profit Lock - Move SL to lock profit when ROE >= threshold
        # Strategy: When ROE >= threshold, move SL up to lock profit, keep position open
        use_profit_lock: bool = False,
        profit_lock_threshold_pct: float = 5.0,  # ROE threshold to trigger lock (default 5%)
        profit_lock_pct: float = 4.0,  # ROE to lock (default 4%, 1% buffer from threshold)
        # REALISTIC (Jan 2026): No-Compound Mode
        # When enabled, position size is fixed based on initial_balance, not current balance
        # This provides realistic backtest results without exponential growth
        no_compound: bool = False,
        # INSTITUTIONAL (Feb 2026): Volatility-Adjusted Position Sizing
        # Scale position size inversely with ATR (high vol = smaller size)
        use_vol_sizing: bool = False,
        # INSTITUTIONAL (Feb 2026): Dynamic TP/SL based on ATR
        # Scale TP, SL, and AUTO_CLOSE thresholds based on current vs average ATR
        use_dynamic_tp: bool = False,
        # v6.0.0: Only check SL on CLOSE stage of intra-bar path (matches LIVE candle-close SL)
        sl_on_close_only: bool = False,
        # v6.2.0: Hard cap tick-level loss limit (0 = disabled)
        hard_cap_pct: float = 0.0,
        # EXPERIMENTAL: Partial close at AC, trail the remainder
        partial_close_ac: bool = False,
        partial_close_ac_pct: float = 0.5,
        # RISK: Max positions in same direction (0 = disabled)
        max_same_direction: int = 0,
        # EXPERIMENTAL: Volume filter (signal candle > threshold × 20-candle avg)
        use_volume_filter: bool = False,
        volume_filter_threshold: float = 1.5,
        # SOTA (Feb 2026): Volume-Adjusted Slippage (Almgren-Chriss square-root impact)
        use_volume_slippage: bool = False,
        # SOTA (Feb 2026): 1m candle monitoring (closes biggest backtest-LIVE gap)
        use_1m_monitoring: bool = False,
        # SOTA (Feb 2026): Adversarial intra-bar path (De Prado)
        use_adversarial_path: bool = False,
        # v6.3.5: AC tick-level (check AC at every stage like Hard Cap, not just CLOSE)
        ac_tick_level: bool = False,
        # F3: Gradual Position Sizing (Balance Ramp)
        use_balance_ramp: bool = False,
        balance_ramp_rate: float = 0.20,
        balance_ramp_threshold: float = 0.30,
        # REALISTIC FILLS (Feb 2026): Fill LIMIT orders at target price, not candle extreme
        # BT was filling at candle LOW (LONG) / HIGH (SHORT) → 3-5% ROE advantage at 10x
        # LIVE fills at target price (market order triggered at target) → realistic
        use_realistic_fills: bool = True,
        # LIKE-LIVE (Feb 2026): AC exits at threshold price, not candle close price
        # BT was exiting at candle CLOSE (e.g. 15% ROE) instead of threshold (e.g. 7% ROE)
        # LIVE exits near threshold because 1m candles catch crossing early
        ac_threshold_exit: bool = False,
        # LIKE-LIVE (Feb 2026): N+1 fill rule — signals from candle N fill on N+1
        # BT allowed fill on same candle as signal → look-ahead bias
        # LIVE processes signal after candle N closes → fills on N+1 or later
        n1_fill: bool = False,
        # v6.5.12: DZ Force-Close — close ALL positions when dead zone starts
        dz_force_close: bool = False,
        # v6.6.0: Maker fee for entries/TP (simulates LIMIT orders)
        use_maker_fee_entries: bool = False,
        # LIKE-LIVE (Mar 2026): Resolve LIMIT entries at candle close after trigger
        # to approximate LocalSignalTracker -> GTX/MARKET fallback behavior.
        use_limit_chase_parity: bool = False,
    ):
        self.balance = initial_balance
        self.initial_balance = initial_balance
        # SOTA: Separate maker/taker fee rates
        self.maker_fee_rate = maker_fee_pct / 100.0   # 0.0002 (0.02%)
        self.taker_fee_rate = taker_fee_pct / 100.0   # 0.0005 (0.05%)
        self.use_maker_fee_entries = use_maker_fee_entries
        self.use_limit_chase_parity = use_limit_chase_parity
        self.base_slippage_rate = slippage_pct / 100.0
        self.risk_per_trade = risk_per_trade
        self.breakeven_trigger_r = breakeven_trigger_r
        self.trailing_stop_atr = trailing_stop_atr
        self.fixed_leverage = fixed_leverage
        self.mode = mode
        self.max_leverage = max_leverage
        self.max_positions = max_positions

        # Risk Configs
        self.max_order_value = max_order_value
        self.maintenance_margin_rate = maintenance_margin_rate

        # SOTA: Funding Rate Simulation
        self.enable_funding_rate = enable_funding_rate
        self.default_funding_rate = default_funding_rate / 100.0  # Convert to decimal
        self.funding_rates = funding_rates or {}  # Symbol -> static funding rate (fallback)
        self.funding_loader = funding_loader  # Historical funding loader
        self._last_funding_time: Optional[datetime] = None
        self._funding_interval_hours = 8  # Binance standard
        self._total_funding_paid = 0.0
        self._total_funding_received = 0.0

        # SOTA: Per-Symbol Exchange Rules
        self.symbol_rules = symbol_rules or {}  # {symbol: {max_leverage, min_qty, step_size, min_notional, qty_precision}}

        # SOTA: Order TTL - 0 = GTC (default for backtest), >0 = cancel after N minutes
        self.order_ttl_minutes = order_ttl_minutes

        # SOTA: Zombie Killer mode (replaces pending orders with new signals)
        self.use_zombie_killer = use_zombie_killer

        # SOTA (Jan 2026): Configurable TTL for testing
        self.order_ttl_minutes = order_ttl_minutes

        # SOTA: Full Take Profit at TP1 (Optional)
        # If True, close 100% at TP1. If False (default), close 60%.
        self.full_tp_at_tp1 = full_tp_at_tp1

        # SOTA (Jan 2026): Pessimistic Fill Buffer
        # Requires price to go BEYOND target by this percentage to confirm fill
        # This prevents optimistic fills where price barely touches target
        self.pessimistic_fill_buffer = pessimistic_fill_buffer_pct

        # EXPERIMENTAL (Jan 2026): Block SHORT signals early (Layer 1+2) for hypothesis testing
        # When True, mimics LIVE OLD behavior: blocks SHORT at signal generation and batch processing
        # This is for testing the hypothesis that early blocking causes overtrading
        self.block_short_early = block_short_early
        self._blocked_short_signals = 0  # Counter for blocked SHORT signals

        # SOTA (Jan 2026): Time-Based Exit Configuration
        # Institutional approach: Exit long-duration losing trades
        # Research shows trades > 2h are losing money (-$4.55 vs +$11.76 for < 1h)
        self.enable_time_based_exit = enable_time_based_exit
        self.time_based_exit_duration_hours = time_based_exit_duration_hours
        self._time_based_exits = 0  # Counter for time-based exits

        # SOTA (Jan 2026): Fixed Profit Per Trade Strategy
        # Experimental approach: Exit when profit reaches $3 per trade
        # Purpose: Test if fixed profit targets improve consistency
        self.use_fixed_profit_3usd = use_fixed_profit_3usd
        self._fixed_profit_exits = 0  # Counter for fixed profit exits

        # SOTA (Jan 2026): Event Recorder for UI Replay
        self.capture_events = capture_events
        self.events_log = []  # Stores snapshots of decision logic

        # SOTA (Jan 2026): Portfolio Profit Target
        # Calculate actual target from percentage if provided
        # LIVE recalculates this from current wallet balance, so keep pct mode
        # dynamic in backtest too.
        self.portfolio_target_pct = portfolio_target_pct
        self.portfolio_target = portfolio_target

        # SOTA (Jan 2026): Signal Reversal Exit
        self.enable_reversal_exit = enable_reversal_exit
        self.reversal_confidence = reversal_confidence
        self._reversal_exits = 0  # Counter for reversal exits

        self.close_profitable_auto = close_profitable_auto
        self.profitable_threshold_pct = profitable_threshold_pct
        self.profitable_check_interval = profitable_check_interval
        self._auto_close_exits = 0  # Counter for auto-close exits
        self._candle_count = 0  # Track candles for interval-based checks

        # SOTA (Jan 2026): MAX SL Validation (optional)
        self.use_max_sl_validation = use_max_sl_validation
        self.max_sl_pct = max_sl_pct  # Custom max SL percentage (None = use formula)
        self._max_sl_rejected = 0  # Counter for rejected signals

        # SOTA (Jan 2026): Profit Lock (optional)
        self.use_profit_lock = use_profit_lock
        self.profit_lock_threshold_pct = profit_lock_threshold_pct  # 5% default
        self.profit_lock_pct = profit_lock_pct  # 4% default
        self._profit_lock_triggered = 0  # Counter for profit locks triggered
        self._profit_locked_symbols = set()  # Track symbols with profit lock active

        # REALISTIC (Jan 2026): No-Compound Mode
        self.no_compound = no_compound
        self._capital_exhausted_at: Optional[datetime] = None
        self._capital_exhaustion_floor = (
            (self.initial_balance / self.max_positions) if self.max_positions > 0 else self.initial_balance
        )

        # F3: Gradual Position Sizing (Balance Ramp)
        self.use_balance_ramp = use_balance_ramp
        self.balance_ramp_rate = balance_ramp_rate
        self.balance_ramp_threshold = balance_ramp_threshold
        self._reference_balance: float = initial_balance
        self._ramp_adjustments: int = 0

        # INSTITUTIONAL (Feb 2026): Volatility-Adjusted Position Sizing
        self.use_vol_sizing = use_vol_sizing
        self._vol_sizing_adjustments = 0  # Counter

        # INSTITUTIONAL (Feb 2026): Dynamic TP/SL based on ATR
        self.use_dynamic_tp = use_dynamic_tp
        self._dynamic_tp_adjustments = 0  # Counter

        # v6.0.0: Only check SL on CLOSE stage (matches LIVE candle-close SL)
        self.sl_on_close_only = sl_on_close_only
        # v6.2.0: Hard cap tick-level loss limit
        self.hard_cap_pct = hard_cap_pct

        # EXPERIMENTAL: Partial close at AC threshold
        self.partial_close_ac = partial_close_ac
        self.partial_close_ac_pct = max(0.0, min(partial_close_ac_pct, 1.0))
        self._partial_ac_exits = 0

        # RISK: Max positions in same direction
        self.max_same_direction = max_same_direction
        self._direction_filter_blocks = 0

        # EXPERIMENTAL: Volume filter
        self.use_volume_filter = use_volume_filter
        self.volume_filter_threshold = volume_filter_threshold
        self._volume_filter_blocks = 0

        # SOTA (Feb 2026): Volume-Adjusted Slippage (Almgren-Chriss)
        self.use_volume_slippage = use_volume_slippage
        self._volume_history: Dict[str, list] = {}  # symbol → last 20 volumes
        self._volume_last_ts: Dict[str, Any] = {}  # symbol → last candle timestamp (dedup)

        # SOTA (Feb 2026): 1m candle monitoring for position SL/TP/AC
        # Closes the biggest backtest-LIVE gap: 15m checks miss SL triggers
        # that 1m candle close catches in LIVE
        self.use_1m_monitoring = use_1m_monitoring
        self._1m_covered_symbols: set = set()  # Track symbols with 1m data coverage

        # SOTA (Feb 2026): Adversarial intra-bar path (De Prado)
        # Instead of using candle direction (requires knowing CLOSE in advance),
        # always check the direction that's BAD for the open position first.
        # LONG → LOW first (SL side), SHORT → HIGH first (SL side)
        # This removes look-ahead bias from candle direction knowledge.
        self.use_adversarial_path = use_adversarial_path
        self.ac_tick_level = ac_tick_level

        # REALISTIC FILLS (Feb 2026): Fill at target price, not candle extreme
        self.use_realistic_fills = use_realistic_fills

        # LIKE-LIVE (Feb 2026): AC threshold exit + N+1 fill rule
        self.ac_threshold_exit = ac_threshold_exit
        self.n1_fill = n1_fill

        # v6.5.12: DZ Force-Close
        self.dz_force_close = dz_force_close
        self._dz_force_close_count = 0

        # PARITY FIX (Feb 2026): Dead zone check for pending order fills
        # LIVE has 3-layer defense blocking fills during dead zones
        # BT was only blocking signal generation (Step E), not pending order fills (Step D)
        self.time_filter = None  # Set by BacktestEngine after construction
        self._dead_zone_fill_blocks = 0  # Counter for blocked fills

        self.logger = logging.getLogger(__name__)

        # Log no_compound status AFTER logger is initialized
        if self.no_compound:
            self.logger.info(
                f"📊 NO-COMPOUND MODE: Fixed position size = ${initial_balance}/{self.max_positions} = "
                f"${initial_balance/self.max_positions:.2f}/slot"
            )

        if self.portfolio_target > 0:
            self.logger.info(
                f"🎯 INSTITUTIONAL: portfolio_target=${self.portfolio_target:.2f} "
                f"({(self.portfolio_target/initial_balance)*100:.2f}% of capital)"
            )
        current_target = self.get_portfolio_target_usd()
        if current_target > 0:
            if self.portfolio_target_pct > 0:
                self.logger.info(
                    f"ðŸŽ¯ INSTITUTIONAL: portfolio_target=${current_target:.2f} "
                    f"({self.portfolio_target_pct:.2f}% of current balance)"
                )
            else:
                self.logger.info(
                    f"ðŸŽ¯ INSTITUTIONAL: portfolio_target=${self.portfolio_target:.2f}"
                )
        if self.enable_reversal_exit:
            self.logger.info(
                f"🔄 INSTITUTIONAL: enable_reversal_exit=True - "
                f"Exit on opposite signals >= {reversal_confidence*100:.0f}% confidence"
            )
        if self.block_short_early:
            self.logger.info("🚫 EXPERIMENTAL: block_short_early=True - SHORT signals will be filtered early (mimics LIVE OLD)")
        if self.enable_time_based_exit:
            self.logger.info(
                f"⏰ INSTITUTIONAL: enable_time_based_exit=True - "
                f"Positions > {time_based_exit_duration_hours}h AND losing will be exited"
            )
        if self.use_fixed_profit_3usd:
            self.logger.info(
                "💰 EXPERIMENTAL: use_fixed_profit_3usd=True - "
                "Positions will exit when profit reaches $3.00"
            )
        if self.use_vol_sizing:
            self.logger.info(
                "📊 INSTITUTIONAL: use_vol_sizing=True - "
                "Position size scaled by ATR (high vol = smaller size)"
            )
        if self.use_dynamic_tp:
            self.logger.info(
                "📊 INSTITUTIONAL: use_dynamic_tp=True - "
                "TP/SL/AUTO_CLOSE scaled by ATR ratio"
            )
        if self.partial_close_ac:
            self.logger.info(
                "📊 EXPERIMENTAL: partial_close_ac=True - "
                f"Close {self.partial_close_ac_pct * 100:.0f}% at AC threshold, "
                f"trail remaining {100 - (self.partial_close_ac_pct * 100):.0f}%"
            )
        if self.max_same_direction > 0:
            self.logger.info(
                f"📊 RISK: max_same_direction={self.max_same_direction} - "
                f"Limit max positions per direction"
            )
        if self.use_volume_filter:
            self.logger.info(
                f"📊 EXPERIMENTAL: volume_filter=True - "
                f"Require signal candle volume >= {self.volume_filter_threshold}x avg"
            )
        if self.use_1m_monitoring:
            self.logger.info(
                "📊 SOTA: use_1m_monitoring=True - "
                "SL/TP/AC checked on 1m candle close (matches LIVE exactly)"
            )
        if self.use_adversarial_path:
            self.logger.info(
                "📊 SOTA: use_adversarial_path=True - "
                "De Prado adversarial path (SL direction first, no look-ahead)"
            )
        if self.use_volume_slippage:
            self.logger.info(
                "📊 SOTA: use_volume_slippage=True - "
                "Almgren-Chriss √vol slippage model (low vol = higher slippage)"
            )
        if self.close_profitable_auto:
            self.logger.info(
                f"💰 EXPERIMENTAL: close_profitable_auto=True - "
                f"Auto-close positions when ROE > {profitable_threshold_pct}%"
            )
        if self.ac_threshold_exit:
            self.logger.info(
                "📊 LIKE-LIVE: ac_threshold_exit=True - "
                "AC exits at threshold price (not candle close)"
            )
        if self.n1_fill:
            self.logger.info(
                "📊 LIKE-LIVE: n1_fill=True - "
                "Signals from candle N can only fill on N+1 or later"
            )

        self.positions: Dict[str, Dict[str, Any]] = {}
        self.pending_orders: Dict[str, Dict[str, Any]] = {}
        self._limit_entry_triggers = 0
        self._limit_entry_maker_fills = 0
        self._limit_entry_market_fallbacks = 0

        # SOTA: Isolated Margin Tracking (Critical fix for capital management)
        self.used_margin = 0.0  # Margin locked in OPEN POSITIONS
        self.locked_in_orders = 0.0  # Margin locked in PENDING ORDERS

        self.trades: List[BacktestTrade] = []
        self.equity_curve: List[Dict[str, Any]] = []

        # SOTA: Track latest prices for Proximity Locking (Proximity Sentry)
        self.latest_prices: Dict[str, float] = {}

        self.logger = logging.getLogger(__name__)

    def _get_ramped_balance(self) -> float:
        """Gradual position sizing: exponential convergence to actual balance.
        Prevents position size jumps after large balance changes (deposits/big wins)."""
        diff_pct = abs(self.balance - self._reference_balance) / self._reference_balance if self._reference_balance > 0 else 0
        if diff_pct < self.balance_ramp_threshold:
            # Within threshold — use actual balance, update reference
            self._reference_balance = self.balance
            return self.balance
        # Exponential convergence: ref moves toward actual by ramp_rate fraction
        self._reference_balance = self._reference_balance + (self.balance - self._reference_balance) * self.balance_ramp_rate
        self._ramp_adjustments += 1
        return self._reference_balance

    @property
    def available_balance(self) -> float:
        """
        SOTA: Calculate available balance for new positions.
        In Isolated Margin mode: Available = Balance - Used Margin (Positions) - Locked (Orders)
        """
        return max(0.0, self.balance - self.used_margin - self.locked_in_orders)

    @staticmethod
    def _get_exit_profile(entity: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not entity:
            return {}
        profile = entity.get("exit_profile")
        return dict(profile) if isinstance(profile, dict) else {}

    def _resolve_close_profitable_auto(self, entity: Optional[Dict[str, Any]]) -> bool:
        profile = self._get_exit_profile(entity)
        return bool(profile.get("close_profitable_auto", self.close_profitable_auto))

    def _resolve_profitable_threshold_pct(self, entity: Optional[Dict[str, Any]]) -> float:
        profile = self._get_exit_profile(entity)
        return float(profile.get("profitable_threshold_pct", self.profitable_threshold_pct))

    def _resolve_trailing_stop_atr(self, entity: Optional[Dict[str, Any]]) -> float:
        profile = self._get_exit_profile(entity)
        return float(profile.get("trailing_stop_atr", self.trailing_stop_atr))

    def _resolve_partial_close_ac(self, entity: Optional[Dict[str, Any]]) -> bool:
        profile = self._get_exit_profile(entity)
        return bool(profile.get("partial_close_ac", self.partial_close_ac))

    def _resolve_partial_close_ac_pct(self, entity: Optional[Dict[str, Any]]) -> float:
        profile = self._get_exit_profile(entity)
        return float(profile.get("partial_close_ac_pct", self.partial_close_ac_pct))

    def _resolve_effective_profitable_threshold(self, pos: Dict[str, Any]) -> float:
        effective_threshold = self._resolve_profitable_threshold_pct(pos)
        if self.use_dynamic_tp:
            atr_ratio = pos.get('atr_ratio', 1.0)
            effective_threshold = max(4.0, min(12.0, effective_threshold * atr_ratio))
        return effective_threshold

    def get_no_compound_slot_size(self) -> float:
        """Return the fixed capital allocation per slot in no-compound mode."""
        if self.max_positions <= 0:
            return self.initial_balance
        return self.initial_balance / self.max_positions

    def is_capital_exhausted(self) -> bool:
        """
        No-compound mode cannot open new positions once available cash drops below slot size.

        This is a terminal state only when there are no open positions or pending orders left.
        """
        if not self.no_compound:
            return False
        if self.positions or self.pending_orders:
            return False
        return self.available_balance < self.get_no_compound_slot_size()

    # ========================================================================
    # SOTA: Event Recorder Logic
    # ========================================================================

    def get_snapshot(self, timestamp: datetime) -> Dict[str, Any]:
        """Capture current state for UI Replay."""
        if not self.capture_events: return {}

        # Helper to serialize orders
        def serialize_order(o):
            return {
                'symbol': o['symbol'],
                'side': o['side'],
                'target_price': o['target_price'],
                'confidence': o.get('confidence', 0),
                'status': 'PENDING'
            }

        def serialize_pos(p):
            return {
                'symbol': p['symbol'],
                'side': p['side'],
                'entry_price': p['entry_price'],
                'sl': p['stop_loss'],
                'tp_hit': p['tp_hit_count']
            }

        return {
            "timestamp": timestamp.isoformat(),
            "balance": self.balance,
            "equity": self.equity_curve[-1]['balance'] if self.equity_curve else self.balance,
            "active_positions": [serialize_pos(p) for p in self.positions.values()],
            "pending_orders": [serialize_order(o) for o in self.pending_orders.values()],
            "events": [] # Populated during decision making
        }

    # ========================================================================
    # SOTA: Per-Symbol Exchange Rules Helpers
    # ========================================================================

    def _get_symbol_leverage_cap(self, symbol: str) -> float:
        """Get the maximum leverage allowed for a symbol from exchange rules."""
        if symbol in self.symbol_rules:
            rules = self.symbol_rules[symbol]
            # Some tokens only allow 2x or 5x (e.g., low-liquidity altcoins)
            return min(rules.get('max_leverage', self.max_leverage), self.max_leverage)
        return self.max_leverage

    def _round_quantity_to_step(self, symbol: str, quantity: float) -> float:
        """Round quantity to step_size (LOT_SIZE filter on Binance)."""
        if symbol in self.symbol_rules:
            rules = self.symbol_rules[symbol]
            step_size = rules.get('step_size', 0.001)
            precision = rules.get('qty_precision', 3)

            if step_size > 0:
                # Round down to nearest step
                rounded = (quantity // step_size) * step_size
                return round(rounded, precision)
        return quantity

    def _validate_min_notional(self, symbol: str, notional: float) -> bool:
        """Check if notional meets MIN_NOTIONAL requirement."""
        if symbol in self.symbol_rules:
            rules = self.symbol_rules[symbol]
            min_notional = rules.get('min_notional', 5.0)
            return notional >= min_notional

        # SOTA: Smart default min_notional when symbol not in rules
        # BTC/ETH have higher min_notional ($100), others typically $5-20
        symbol_upper = symbol.upper()
        if 'BTC' in symbol_upper:
            default_min = 100.0  # BTC min_notional = $100
        elif 'ETH' in symbol_upper:
            default_min = 20.0   # ETH min_notional = $20
        else:
            default_min = 5.0    # Most altcoins = $5

        self.logger.debug(f"⚠️ {symbol} not in symbol_rules, using default min_notional=${default_min}")
        return notional >= default_min

    def _get_min_qty(self, symbol: str) -> float:
        """Get minimum quantity for a symbol."""
        if symbol in self.symbol_rules:
            return self.symbol_rules[symbol].get('min_qty', 0.001)
        return 0.001


    def process_batch_signals(self, signals: List[TradingSignal]):
        """
        Process a batch of signals with Shark Tank logic (Competition).
        SOTA (Jan 2026): Instrumented with Event Recorder for UI Replay.
        """
        if not signals: return

        current_events = [] # For this batch

        # EXPERIMENTAL (Jan 2026): LAYER 2 - Block SHORT signals early (if flag enabled)
        # This mimics LIVE OLD behavior for hypothesis testing
        if self.block_short_early:
            original_count = len(signals)
            signals = [s for s in signals if s.signal_type != SignalType.SELL]
            filtered_count = original_count - len(signals)
            if filtered_count > 0:
                self._blocked_short_signals += filtered_count
                msg = f"🚫 Filtered {filtered_count} SHORT signals (block_short_early=True)"
                self.logger.info(msg)
                if self.capture_events:
                    current_events.append({"type": "FILTER", "msg": msg})
            if not signals:
                if self.capture_events: self.events_log.extend(current_events)
                return  # All signals were SHORT

        # RISK: Max same-direction filter
        if self.max_same_direction > 0:
            long_count = sum(1 for p in self.positions.values() if p['side'] == 'LONG') + \
                         sum(1 for o in self.pending_orders.values() if o['side'] == 'LONG')
            short_count = sum(1 for p in self.positions.values() if p['side'] == 'SHORT') + \
                          sum(1 for o in self.pending_orders.values() if o['side'] == 'SHORT')
            filtered = []
            for s in signals:
                side = 'LONG' if s.signal_type == SignalType.BUY else 'SHORT'
                if side == 'LONG' and long_count >= self.max_same_direction:
                    self._direction_filter_blocks += 1
                    continue
                if side == 'SHORT' and short_count >= self.max_same_direction:
                    self._direction_filter_blocks += 1
                    continue
                filtered.append(s)
                # Track increments for signals passing through this batch
                if side == 'LONG':
                    long_count += 1
                else:
                    short_count += 1
            signals = filtered
            if not signals:
                return

        # EXPERIMENTAL: Volume filter
        if self.use_volume_filter:
            original_count = len(signals)
            signals = [s for s in signals if s.indicators.get('volume_ratio', 0) >= self.volume_filter_threshold]
            blocked = original_count - len(signals)
            if blocked > 0:
                self._volume_filter_blocks += blocked
            if not signals:
                return

        # SOTA: Multi-Position Shark Tank Logic
        # Check if we have room for more positions
        current_active = len(self.positions) + len(self.pending_orders)

        if current_active >= self.max_positions:
            # SOTA: SMART RECYCLING (Best Practice) - Only if zombie_killer is enabled
            # If full, check if any NEW signal has higher confidence than the WORST pending order
            # This ensures we always have the "A-Team" in the tank.

            # SOTA FIX (Jan 2026): Only run recycling if use_zombie_killer is True
            if not self.use_zombie_killer:
                # When zombie killer is disabled, simply reject new signals when full
                if self.capture_events:
                    for s in signals:
                        current_events.append({
                            "type": "REJECT",
                            "symbol": s.symbol,
                            "reason": "MAX_SLOTS",
                            "conf": s.confidence
                        })
                    self.events_log.extend(current_events)
                return

            # 1. Identify worst pending order (lowest confidence)
            if not self.pending_orders: return # Should not happen if current_active >= max

            # SOTA: PROXIMITY SENTRY implementation
            # Filter out signals that are "Close to Filling" (within 0.2%)
            # These are "Locked" and should NOT be recycled.

            recyclable_candidates = []
            locked_orders = []

            for symbol, order in self.pending_orders.items():
                is_locked = False
                current_price = self.latest_prices.get(symbol)
                target_price = order.get('target_price')

                if current_price and target_price:
                    dist_pct = abs(current_price - target_price) / target_price
                    if dist_pct < 0.002:  # 0.2% proximity
                        is_locked = True
                        locked_orders.append(symbol)

                if not is_locked:
                    recyclable_candidates.append(order)

            if self.capture_events and locked_orders:
                current_events.append({
                    "type": "INFO",
                    "msg": f"🔒 Locked {len(locked_orders)} orders (Proximity < 0.2%)"
                })

            if not recyclable_candidates:
                # All pending orders are LOCKED (close to fill)
                if self.capture_events:
                    for s in signals:
                        current_events.append({
                            "type": "REJECT",
                            "symbol": s.symbol,
                            "reason": "ALL_LOCKED",
                            "conf": s.confidence
                        })
                    self.events_log.extend(current_events)
                return

            # Sort recyclable pending by confidence (ascending)
            sorted_pending = sorted(
                recyclable_candidates,
                key=lambda x: x.get('confidence', 0)
            )
            worst_pending = sorted_pending[0]

            # 2. Filter new signals that are BETTER than worst pending
            better_signals = [
                s for s in signals
                if s.symbol not in self.positions
                and s.symbol not in self.pending_orders
                and s.confidence > worst_pending.get('confidence', 0) * 1.1 # 10% buffer to avoid churn
            ]

            if not better_signals:
                if self.capture_events:
                    for s in signals:
                        current_events.append({
                            "type": "REJECT",
                            "symbol": s.symbol,
                            "reason": "LOW_CONF",
                            "conf": s.confidence
                        })
                    self.events_log.extend(current_events)
                return

            # 3. Sort better signals by confidence DESC, symbol ASC (deterministic tiebreaker)
            better_signals.sort(key=lambda s: (-s.confidence, s.symbol))
            best_new = better_signals[0]

            # 4. SWAP: Kill worst pending, Place best new
            self.logger.info(
                f"♻️ SMART RECYCLE: Killing {worst_pending['symbol']} (Conf: {worst_pending.get('confidence',0):.2f}) "
                f"for {best_new.symbol} (Conf: {best_new.confidence:.2f})"
            )

            if self.capture_events:
                current_events.append({
                    "type": "RECYCLE",
                    "killed": worst_pending['symbol'],
                    "killed_conf": worst_pending.get('confidence', 0),
                    "new": best_new.symbol,
                    "new_conf": best_new.confidence
                })

            self.cancel_pending_order(worst_pending['symbol'])
            self.place_order(best_new)

            if self.capture_events:
                self.events_log.extend(current_events)
            return

        # STANDARD FILL LOGIC (slots available)
        candidates = [s for s in signals if s.symbol not in self.positions and s.symbol not in self.pending_orders]
        if not candidates:
            if self.capture_events: self.events_log.extend(current_events)
            return

        # Sort by confidence DESC, then symbol ASC as deterministic tiebreaker
        candidates.sort(key=lambda s: (-s.confidence, s.symbol))

        available_slots = self.max_positions - current_active

        # Create decision log for standard fill
        if self.capture_events:
            for s in candidates[:available_slots]:
                current_events.append({
                    "type": "ACCEPT",
                    "symbol": s.symbol,
                    "conf": s.confidence,
                    "slots": available_slots
                })
            # Log rejections if any
            if len(candidates) > available_slots:
                for s in candidates[available_slots:]:
                    current_events.append({
                        "type": "REJECT",
                        "symbol": s.symbol,
                        "reason": "NO_SLOTS",
                        "conf": s.confidence
                    })
            self.events_log.extend(current_events)

        for i in range(min(len(candidates), available_slots)):
            self.place_order(candidates[i])

    def _get_max_sl_distance(self, leverage: float) -> float:
        """
        SOTA (Jan 2026): Max SL distance based on leverage.

        Formula: max_account_risk / leverage
        Target: Max 10% account risk per trade

        Example:
        - 20x: 10% / 20 = 0.5% max SL
        - 10x: 10% / 10 = 1% max SL
        - 5x:  10% / 5  = 2% max SL

        If self.max_sl_pct is set, use that instead.
        """
        # Use custom max_sl_pct if provided
        if self.max_sl_pct is not None:
            return self.max_sl_pct / 100.0  # Convert percentage to decimal

        # Otherwise calculate from leverage
        MAX_ACCOUNT_RISK = 0.10  # 10%
        return MAX_ACCOUNT_RISK / leverage if leverage > 0 else 0.02

    def _get_symbol_leverage_cap(self, symbol: str) -> float:
        """Get max leverage for symbol from rules, fallback to config."""
        if self.symbol_rules and symbol in self.symbol_rules:
            return self.symbol_rules[symbol].get('max_leverage', self.max_leverage)
        return self.max_leverage

    def _replace_pending_order(self, signal: TradingSignal):
        """ZOMBIE KILLER: Replace existing pending order with new signal (matches Paper/Live)."""
        symbol = signal.symbol
        if symbol not in self.pending_orders:
            return

        old_order = self.pending_orders[symbol]
        old_entry = old_order.get('entry', 0)

        # Release margin from old order
        old_margin = old_order.get('margin', 0)
        self.balance += old_margin

        self.logger.debug(
            f"💀 ZOMBIE KILLER: Replacing {symbol} pending "
            f"(old entry=${old_entry:.2f}, new entry=${signal.entry_price or signal.price:.2f})"
        )

        # Remove old and place new
        del self.pending_orders[symbol]
        self.place_order(signal)

    def place_order(self, signal: TradingSignal):
        symbol = signal.symbol
        if symbol in self.positions: return  # Can't have both position AND pending
        # Removed: `or symbol in self.pending_orders` to allow replacement via _replace_pending_order

        initial_sl = signal.stop_loss
        if not initial_sl: return

        target_entry = signal.entry_price or signal.price

        sl_dist_pct = abs(target_entry - initial_sl) / target_entry
        if sl_dist_pct < 0.005: return  # MIN SL check: Too tight (< 0.5%)

        # SOTA (Jan 2026): MAX SL Validation - Sync with LIVE (Optional)
        # Only active when use_max_sl_validation=True
        # Formula: max_sl_distance = MAX_ACCOUNT_RISK / leverage
        # Target: Max 10% account risk per trade
        if self.use_max_sl_validation:
            effective_lev = self.fixed_leverage if self.fixed_leverage > 0 else 10.0
            max_sl_dist = self._get_max_sl_distance(effective_lev)
            if sl_dist_pct > max_sl_dist:
                self.logger.debug(
                    f"🚫 {symbol}: SL too far ({sl_dist_pct:.2%}) for {effective_lev}x leverage. "
                    f"Max allowed: {max_sl_dist:.2%}. Skipping signal."
                )
                self._max_sl_rejected += 1
                return

        # SOTA: Get per-symbol leverage cap
        symbol_max_leverage = self._get_symbol_leverage_cap(symbol)

        # SOTA: Dynamic Capital Allocation for Shark Tank Slots
        # Instead of using only "Available Balance" (which shrinks after each order),
        # we calculate based on "Total Balance / Max Positions" to ensure equal weight.
        # This is the standard "Pod" or "Slot" management in institutional desks.
        #
        # REALISTIC (Jan 2026): No-Compound Mode
        # When no_compound=True, use initial_balance to prevent exponential growth
        if self.no_compound:
            base_balance = self.initial_balance
        elif self.use_balance_ramp:
            base_balance = self._get_ramped_balance()
        else:
            base_balance = self.balance
        capital_per_slot = base_balance / self.max_positions
        available = self.available_balance

        # ISOLATED MARGIN FIX (Mar 2026): Strict balance floor check
        # In Isolated Margin mode on Binance, you CANNOT open a position
        # with margin exceeding your actual cash balance. The available_balance
        # property tracks (balance - used_margin - locked_in_orders), but we
        # also enforce that the absolute balance itself is sufficient.
        # This prevents the simulator from acting like Cross Margin.
        if available <= 0:
            self.logger.debug(
                f"⛔ {symbol}: No available balance (bal=${self.balance:.2f}, "
                f"used=${self.used_margin:.2f}, locked=${self.locked_in_orders:.2f}), skipping"
            )
            return

        # ISOLATED MARGIN FIX (Mar 2026): Strict Rejection for No-Compound
        # If the user sets a fixed position size ($100), and the wallet shrinks
        # below $100, the trade MUST be rejected, not downsized.
        if self.no_compound and available < capital_per_slot:
            self.logger.debug(
                f"⛔ ISO_MARGIN REJECT: {symbol} requires fixed slot ${capital_per_slot:.2f} "
                f"but only has available=${available:.2f}. Trade aborted!"
            )
            return

        # Safety: For compounding mode, ensure we don't exceed what's actually in the wallet
        allocated_capital = min(capital_per_slot, available)

        # SOTA: Apply time-based multiplier for tiered sizing
        # Tier 1 = 100%, Tier 2 = 50%, Tier 3 = 30%, Tier 4 = blocked earlier
        time_multiplier = signal.indicators.get('time_multiplier', 1.0)
        if time_multiplier < 1.0:
            allocated_capital *= time_multiplier
            self.logger.debug(f"⏰ {symbol}: Time-adjusted capital to {time_multiplier*100:.0f}% = ${allocated_capital:.2f}")

        # INSTITUTIONAL (Feb 2026): Volatility-Adjusted Position Sizing
        # Scale position size inversely with current ATR vs 20-period average
        # High volatility → smaller size (reduce risk)
        # Low volatility → larger size (exploit calm markets)
        if self.use_vol_sizing:
            atr_value = signal.indicators.get('atr', 0)
            atr_avg = signal.indicators.get('atr_avg_20', 0)
            if atr_value > 0 and atr_avg > 0:
                vol_ratio = atr_value / atr_avg
                vol_multiplier = max(0.5, min(1.5, 1.0 / vol_ratio))
                old_capital = allocated_capital
                allocated_capital *= vol_multiplier
                self._vol_sizing_adjustments += 1
                self.logger.debug(
                    f"📊 VOL_SIZING: {symbol} | ATR={atr_value:.4f}, ATR_avg={atr_avg:.4f}, "
                    f"ratio={vol_ratio:.2f}, multiplier={vol_multiplier:.2f} | "
                    f"Capital: ${old_capital:.2f} → ${allocated_capital:.2f}"
                )

        if allocated_capital <= 0: return

        # Risk Management
        if self.fixed_leverage > 0:
            effective_leverage = min(self.fixed_leverage, symbol_max_leverage)
            notional = allocated_capital * effective_leverage
        else:
            # Risk 1% of the ENTIRE balance per slot
            risk_amt = self.balance * self.risk_per_trade
            notional = risk_amt / sl_dist_pct
            effective_leverage = notional / allocated_capital if allocated_capital > 0 else 0

        # Hard Leverage Cap & Liquidity Cap
        max_notional_leverage = allocated_capital * symbol_max_leverage
        final_max_notional = min(max_notional_leverage, self.max_order_value)

        if notional > final_max_notional:
            notional = final_max_notional

        # SOTA: Validate MIN_NOTIONAL
        if not self._validate_min_notional(symbol, notional):
            self.logger.debug(f"⚠️ {symbol}: notional ${notional:.2f} below min_notional, skipping")
            return

        # SOTA CRITICAL: Calculate and validate margin requirement
        effective_leverage = max(effective_leverage, 1.0)  # Ensure not division by zero
        margin_required = notional / effective_leverage

        # ISOLATED MARGIN FIX (Mar 2026): Re-check available at margin validation time
        # This catches race conditions where available changed between allocation and here
        current_available = self.available_balance
        if margin_required > current_available:
            self.logger.debug(
                f"⚠️ {symbol}: Margin ${margin_required:.2f} exceeds available ${current_available:.2f}, skipping"
            )
            return

        # Calculate position size
        raw_size = notional / target_entry

        # SOTA: Round quantity to step_size (LOT_SIZE filter)
        rounded_size = self._round_quantity_to_step(symbol, raw_size)

        # SOTA: Validate against min_qty
        min_qty = self._get_min_qty(symbol)
        if rounded_size < min_qty:
            self.logger.debug(f"⚠️ {symbol}: size {rounded_size} below min_qty {min_qty}, skipping")
            return

        # Recalculate actual notional after rounding
        actual_notional = rounded_size * target_entry

        # Recalculate exact margin required after rounding
        final_margin = actual_notional / effective_leverage

        # ISOLATED MARGIN FIX (Mar 2026): Triple-check with FRESH available balance
        # This is the definitive Binance Isolated Margin gate
        final_available = self.available_balance
        if final_margin > final_available:
            self.logger.debug(
                f"⛔ {symbol}: Final margin ${final_margin:.2f} > available ${final_available:.2f}, REJECTED"
            )
            return

        # SOTA: CRITICAL - Lock margin immediately
        self.locked_in_orders += final_margin

        # SOTA: CRITICAL - Second min_notional check AFTER rounding
        # This catches edge cases where rounding reduces notional below minimum
        # Example: BTC $90k, step 0.001, balance $17 × 10x = $170
        #          raw_size = 0.00189, rounded = 0.001, actual = $90 < min $100
        if not self._validate_min_notional(symbol, actual_notional):
            self.logger.debug(
                f"⚠️ {symbol}: actual_notional ${actual_notional:.2f} below min_notional AFTER rounding, skipping"
            )
            # Refund margin if check fails
            self.locked_in_orders -= final_margin
            return

        # INSTITUTIONAL (Feb 2026): Dynamic TP/SL based on ATR
        # Scale TP, SL based on current vs average ATR ratio
        dynamic_sl = initial_sl
        dynamic_tp_levels = signal.tp_levels
        atr_ratio_stored = 1.0  # Default ratio for position tracking

        if self.use_dynamic_tp:
            atr_value = signal.indicators.get('atr', 0)
            atr_avg = signal.indicators.get('atr_avg_20', 0)
            if atr_value > 0 and atr_avg > 0:
                atr_ratio = atr_value / atr_avg
                atr_ratio_stored = atr_ratio
                is_long = signal.signal_type == SignalType.BUY

                # Scale SL: base 1.0% price, clamp to 0.5%-2.0%
                base_sl_pct = abs(target_entry - initial_sl) / target_entry
                dynamic_sl_pct = max(0.005, min(0.02, base_sl_pct * atr_ratio))

                if is_long:
                    dynamic_sl = target_entry * (1 - dynamic_sl_pct)
                else:
                    dynamic_sl = target_entry * (1 + dynamic_sl_pct)

                # Scale TP: base 2.0% price, clamp to 1.0%-4.0%
                base_tp_pct = 0.02  # Default TP target
                dynamic_tp_pct = max(0.01, min(0.04, base_tp_pct * atr_ratio))

                if is_long:
                    tp1 = target_entry * (1 + dynamic_tp_pct)
                else:
                    tp1 = target_entry * (1 - dynamic_tp_pct)

                dynamic_tp_levels = self._build_tp_levels(is_long, tp1)

                # Update sl_dist_pct for downstream checks
                sl_dist_pct = abs(target_entry - dynamic_sl) / target_entry

                self._dynamic_tp_adjustments += 1
                self.logger.debug(
                    f"📊 DYNAMIC_TP: {symbol} | ATR_ratio={atr_ratio:.2f} | "
                    f"SL: {base_sl_pct*100:.2f}% → {dynamic_sl_pct*100:.2f}% | "
                    f"TP: {base_tp_pct*100:.2f}% → {dynamic_tp_pct*100:.2f}%"
                )

        exit_profile = signal.indicators.get("research_exit_profile")
        if isinstance(exit_profile, dict):
            exit_profile = dict(exit_profile)
        else:
            exit_profile = None

        self.pending_orders[symbol] = {
            'id': str(uuid.uuid4())[:8],
            'symbol': symbol,
            'side': 'LONG' if signal.signal_type == SignalType.BUY else 'SHORT',
            'type': 'LIMIT' if signal.is_limit_order else 'MARKET',
            'target_price': target_entry,
            'stop_loss': dynamic_sl,
            'tp_levels': dynamic_tp_levels,
            'notional': actual_notional,  # Use actual notional after rounding
            'entry_equity': self.balance,
            'initial_size': rounded_size,  # Use rounded size
            'remaining_size': rounded_size,  # Use rounded size
            'initial_risk': abs(target_entry - initial_sl),
            'is_breakeven': False,
            'tp_hit_count': 0,
            'max_price': target_entry,
            'atr': signal.indicators.get('atr', 0),
            'timestamp': signal.generated_at,
            'leverage_used': effective_leverage,
            'locked_margin': final_margin, # Track specific margin for this order
            'confidence': signal.confidence, # SOTA: Store confidence for Smart Recycling
            'atr_ratio': atr_ratio_stored,  # INSTITUTIONAL (Feb 2026): For dynamic AUTO_CLOSE
            # LIKE-LIVE: N+1 fill rule — cannot fill before next candle
            'earliest_fill_ts': (signal.generated_at + timedelta(minutes=15)) if self.n1_fill else None,
            'limit_triggered': False,
            'limit_trigger_stage': None,
            'limit_trigger_price': None,
            'exit_profile': exit_profile,
        }

    def update(self, candle_map: Dict[str, Candle], timestamp: datetime):
        # Increment candle count for interval-based checks
        self._candle_count += 1

        # SOTA: Process funding rate every 8 hours
        if self.enable_funding_rate:
            self._process_funding_rate(timestamp)

        for symbol, candle in candle_map.items():
            # SOTA: Update latest prices for Proximity check
            self.latest_prices[symbol] = candle.close
            self._process_symbol(symbol, candle, timestamp)

        unrealized_pnl = 0.0
        for sym, pos in self.positions.items():
            current_price = candle_map[sym].close if sym in candle_map else pos['entry_price']
            if pos['side'] == 'LONG':
                pnl = (current_price - pos['entry_price']) * pos['remaining_size']
            else:
                pnl = (pos['entry_price'] - current_price) * pos['remaining_size']
            unrealized_pnl += pnl

        total_equity = self.balance + unrealized_pnl
        self.equity_curve.append({'time': timestamp, 'balance': total_equity})

    def update_positions_1m(self, candle_map_1m: Dict[str, Candle], timestamp: datetime):
        """
        SOTA (Feb 2026): Monitor open positions using 1m candles.

        Closes the biggest backtest-LIVE gap: LIVE checks SL on every 1m candle
        close (15 checks per 15m bar), while backtest only checked at 15m close
        (1 check). This missed many SL triggers, inflating backtest WR by ~8-10pp.

        Checks (matching LIVE position_monitor_service.py):
        - Hard cap: tick-level at HIGH/LOW (every stage)
        - SL: 1m candle CLOSE only (Layer 1)
        - AC: 1m candle CLOSE only
        - TP: realtime at HIGH/LOW (every stage)
        - Breakeven trigger
        - Trailing stop update
        - MFE tracking
        """
        if not self.positions:
            return

        # v6.5.12: DZ Force-Close — close ALL positions when entering dead zone
        if self.dz_force_close and self.time_filter and self.positions:
            if self.time_filter.get_size_multiplier(timestamp) == 0:
                for sym in list(self.positions.keys()):
                    pos = self.positions[sym]
                    close_price = candle_map_1m[sym].close if sym in candle_map_1m else pos['entry_price']
                    slippage = self.base_slippage_rate
                    self._close_position(sym, close_price, "DZ_FORCE_CLOSE", timestamp, slippage)
                    self._dz_force_close_count += 1
                return  # All positions closed, skip normal monitoring

        symbols_to_process = [s for s in self.positions if s in candle_map_1m]
        # Track which symbols have 1m coverage (for 15m fallback logic)
        self._1m_covered_symbols.update(candle_map_1m.keys())

        for symbol in symbols_to_process:
            if symbol not in self.positions:
                continue  # May have been closed by earlier iteration

            pos = self.positions[symbol]
            candle = candle_map_1m[symbol]

            # Skip if position was just opened on this timestamp
            if pos['entry_time'] == timestamp:
                continue

            side = pos['side']
            entry_price = pos['entry_price']

            # Inline slippage (don't mix 1m volume into 15m volume history)
            volatility = (candle.high - candle.low) / candle.open if candle.open > 0 else 0
            slippage = self.base_slippage_rate + (volatility * 0.1)

            # Build 1m intra-bar path
            # Adversarial: always check SL direction first (no look-ahead needed)
            # Standard: use candle direction (requires knowing close)
            if self.use_adversarial_path:
                if side == 'LONG':
                    path = [('OPEN', candle.open), ('LOW', candle.low), ('HIGH', candle.high), ('CLOSE', candle.close)]
                else:
                    path = [('OPEN', candle.open), ('HIGH', candle.high), ('LOW', candle.low), ('CLOSE', candle.close)]
            else:
                is_bullish = candle.close >= candle.open
                if is_bullish:
                    path = [('OPEN', candle.open), ('LOW', candle.low), ('HIGH', candle.high), ('CLOSE', candle.close)]
                else:
                    path = [('OPEN', candle.open), ('HIGH', candle.high), ('LOW', candle.low), ('CLOSE', candle.close)]

            for stage, price in path:
                if symbol not in self.positions:
                    break  # Position was closed

                pos = self.positions[symbol]

                # --- Track Max/Min Price for Trailing ---
                if side == 'LONG':
                    pos['max_price'] = max(pos['max_price'], price)
                else:
                    pos['max_price'] = min(pos['max_price'], price)

                # --- MFE tracking ---
                margin = pos.get('margin', 0.0)
                if margin > 0:
                    if side == 'LONG':
                        curr_roe = ((price - entry_price) * pos['remaining_size'] / margin) * 100
                    else:
                        curr_roe = ((entry_price - price) * pos['remaining_size'] / margin) * 100
                    if curr_roe > pos.get('peak_roe', 0.0):
                        pos['peak_roe'] = curr_roe

                # --- 0. LIQUIDATION CHECK ---
                liq_price = pos['liq_price']
                is_liquidated = (side == 'LONG' and price <= liq_price) or \
                                (side == 'SHORT' and price >= liq_price)
                if is_liquidated:
                    self._liquidate_position(symbol, liq_price, timestamp)
                    break

                # --- 1. HARD CAP (every tick/stage) ---
                # FIX v6.3.5: Exit at threshold price, not candle extreme
                if self.hard_cap_pct > 0 and entry_price > 0:
                    if side == 'LONG':
                        hc_loss = (entry_price - price) / entry_price
                    else:
                        hc_loss = (price - entry_price) / entry_price
                    if hc_loss >= self.hard_cap_pct:
                        # Calculate exact threshold crossing price
                        if side == 'LONG':
                            hc_price = entry_price * (1 - self.hard_cap_pct)
                        else:
                            hc_price = entry_price * (1 + self.hard_cap_pct)
                        self._close_position(symbol, hc_price, "HARD_CAP", timestamp, slippage)
                        break

                # --- 2. TP (realtime, every stage) ---
                if pos['tp_hit_count'] == 0:
                    tp1 = pos['tp_levels'].get('tp1')
                    if tp1:
                        tp_hit = (side == 'LONG' and price >= tp1) or (side == 'SHORT' and price <= tp1)
                        if tp_hit:
                            tp_pct = 1.0 if self.full_tp_at_tp1 else 0.6
                            self._take_partial_profit(symbol, tp1, tp_pct, "TAKE_PROFIT_1", timestamp, slippage)
                            if symbol in self.positions:
                                self.positions[symbol]['stop_loss'] = entry_price
                                self.positions[symbol]['is_breakeven'] = True
                            break

                # --- 2b. AC TICK-LEVEL (like Hard Cap but for profit) ---
                # FIX: Exit at THRESHOLD price, not candle extreme
                # In LIVE, first tick crossing 7% triggers exit at ~7.0% ROE
                # Backtest must simulate this by capping exit price at threshold
                if self.ac_tick_level and self._resolve_close_profitable_auto(pos):
                    remaining_size = pos['remaining_size']
                    if side == 'LONG':
                        unrealized_pnl = (price - entry_price) * remaining_size
                    else:
                        unrealized_pnl = (entry_price - price) * remaining_size
                    if unrealized_pnl > 0 and margin > 0:
                        roe_pct = (unrealized_pnl / margin) * 100
                        effective_threshold = self._resolve_effective_profitable_threshold(pos)
                        if roe_pct > effective_threshold:
                            # Calculate exact threshold crossing price
                            # ROE% = (price_diff / entry) * leverage * 100
                            # → price_diff = ROE% * entry / (leverage * 100)
                            leverage = pos.get('leverage_at_entry', self.fixed_leverage)
                            threshold_diff = effective_threshold * entry_price / (leverage * 100)
                            if side == 'LONG':
                                threshold_price = entry_price + threshold_diff
                            else:
                                threshold_price = entry_price - threshold_diff
                            self._auto_close_exits += 1
                            self._close_position(symbol, threshold_price, "AUTO_CLOSE_PROFITABLE", timestamp, slippage)
                            break

                # --- 2c. PROFIT LOCK (every tick/stage, like Hard Cap) ---
                # FIX v6.3.5: Add PL to 1m path (was only in legacy 15m path)
                if self.use_profit_lock:
                    self._check_profit_lock(symbol, pos, price, timestamp)

                # --- CLOSE-only checks (SL, AC) ---
                if stage != 'CLOSE':
                    continue

                # --- 3. SL on 1m CLOSE (Layer 1, matches LIVE exactly) ---
                sl_hit = (side == 'LONG' and price <= pos['stop_loss']) or \
                         (side == 'SHORT' and price >= pos['stop_loss'])
                if sl_hit:
                    # Semantic exit reason
                    pnl_approx = (pos['stop_loss'] - entry_price) if side == 'LONG' else (entry_price - pos['stop_loss'])
                    if pnl_approx > 0:
                        reason = "TRAILING_STOP" if pos['tp_hit_count'] > 0 else "BREAKEVEN"
                    elif abs(pnl_approx) < entry_price * 0.0001:
                        reason = "BREAKEVEN"
                    else:
                        reason = "STOP_LOSS"

                    exec_price = pos['stop_loss']
                    if side == 'LONG' and price < exec_price:
                        exec_price = price
                    elif side == 'SHORT' and price > exec_price:
                        exec_price = price

                    self._close_position(symbol, exec_price, reason, timestamp, slippage)
                    break

                # --- 4. AUTO_CLOSE on 1m CLOSE ---
                if self._resolve_close_profitable_auto(pos):
                    remaining_size = pos['remaining_size']
                    if side == 'LONG':
                        unrealized_pnl = (price - entry_price) * remaining_size
                    else:
                        unrealized_pnl = (entry_price - price) * remaining_size

                    if unrealized_pnl > 0 and margin > 0:
                        roe_pct = (unrealized_pnl / margin) * 100
                        effective_threshold = self._resolve_effective_profitable_threshold(pos)

                        if roe_pct > effective_threshold:
                            # LIKE-LIVE: Exit at threshold price, not 1m close
                            if self.ac_threshold_exit:
                                leverage = pos.get('leverage_at_entry', self.fixed_leverage if self.fixed_leverage > 0 else 10.0)
                                threshold_diff = effective_threshold * entry_price / (leverage * 100)
                                if side == 'LONG':
                                    ac_exit_price = entry_price + threshold_diff
                                else:
                                    ac_exit_price = entry_price - threshold_diff
                            else:
                                ac_exit_price = price

                            # EXPERIMENTAL: Partial close at AC — close 50%, trail rest
                            partial_close_ac = self._resolve_partial_close_ac(pos)
                            partial_close_ac_pct = self._resolve_partial_close_ac_pct(pos)
                            if partial_close_ac:
                                self._partial_ac_exits += 1
                                self._auto_close_exits += 1
                                self._take_partial_profit(
                                    symbol,
                                    ac_exit_price,
                                    partial_close_ac_pct,
                                    "AUTO_CLOSE_PARTIAL",
                                    timestamp,
                                    slippage,
                                )
                                if symbol in self.positions:
                                    pos['stop_loss'] = entry_price
                                    pos['is_breakeven'] = True
                                break

                            self._auto_close_exits += 1
                            self._close_position(symbol, ac_exit_price, "AUTO_CLOSE_PROFITABLE", timestamp, slippage)
                            break

                # --- 5. Breakeven trigger ---
                if not pos['is_breakeven']:
                    # FIX (Feb 17): Direction-aware — only trigger on profitable moves
                    if side == 'LONG':
                        price_diff = price - entry_price
                    else:
                        price_diff = entry_price - price
                    if price_diff >= (pos['initial_risk'] * self.breakeven_trigger_r):
                        buffer = entry_price * 0.0005
                        pos['stop_loss'] = entry_price + buffer if side == 'LONG' else entry_price - buffer
                        pos['is_breakeven'] = True

                # --- 6. Trailing stop update ---
                if pos['tp_hit_count'] >= 1 and pos['atr'] > 0:
                    trail = pos['atr'] * self._resolve_trailing_stop_atr(pos)
                    if side == 'LONG':
                        new_sl = pos['max_price'] - trail
                        if new_sl > pos['stop_loss']:
                            pos['stop_loss'] = new_sl
                    else:
                        new_sl = pos['max_price'] + trail
                        if new_sl < pos['stop_loss']:
                            pos['stop_loss'] = new_sl

    def _process_funding_rate(self, timestamp: datetime):
        """
        SOTA: Apply funding rate to open positions every 8 hours.

        Funding mechanics (Binance perpetual):
        - Positive funding: Longs pay Shorts
        - Negative funding: Shorts pay Longs
        - Applied every 8 hours (00:00, 08:00, 16:00 UTC)

        Impact on P&L:
        - LONG + Positive funding → COST (减少利润)
        - LONG + Negative funding → REVENUE (增加利润)
        - SHORT + Positive funding → REVENUE (增加利润)
        - SHORT + Negative funding → COST (减少利润)
        """
        if not self.positions:
            return

        # Initialize last funding time
        if self._last_funding_time is None:
            self._last_funding_time = timestamp
            return

        # Check if 8 hours have passed
        hours_since_last = (timestamp - self._last_funding_time).total_seconds() / 3600

        if hours_since_last >= self._funding_interval_hours:
            # Apply funding to all open positions
            for symbol, pos in self.positions.items():
                # SOTA: Get historical funding rate if loader available
                if self.funding_loader:
                    # Use exact historical funding rate at this timestamp
                    funding_rate = self.funding_loader.get_funding_at_time(symbol, timestamp)
                else:
                    # Fallback to static rates
                    funding_rate = self.funding_rates.get(symbol, self.default_funding_rate)

                # Calculate funding payment
                notional_value = pos['remaining_size'] * pos['entry_price']
                funding_amount = notional_value * abs(funding_rate)

                # Determine direction: pay or receive
                is_long = pos['side'] == 'LONG'
                funding_positive = funding_rate > 0

                if is_long:
                    if funding_positive:
                        # Long pays shorts
                        self.balance -= funding_amount
                        pos['funding_cost'] = pos.get('funding_cost', 0) + funding_amount
                        self._total_funding_paid += funding_amount
                    else:
                        # Long receives from shorts
                        self.balance += funding_amount
                        pos['funding_cost'] = pos.get('funding_cost', 0) - funding_amount
                        self._total_funding_received += funding_amount
                else:
                    if funding_positive:
                        # Short receives from longs
                        self.balance += funding_amount
                        pos['funding_cost'] = pos.get('funding_cost', 0) - funding_amount
                        self._total_funding_received += funding_amount
                    else:
                        # Short pays longs
                        self.balance -= funding_amount
                        pos['funding_cost'] = pos.get('funding_cost', 0) + funding_amount
                        self._total_funding_paid += funding_amount

                self.logger.debug(
                    f"💰 Funding {symbol}: rate={funding_rate*100:.4f}%, "
                    f"amount=${funding_amount:.2f}, side={pos['side']}"
                )

            self._last_funding_time = timestamp

    def cancel_pending_order(self, symbol: str):
        """Cancel a pending order and release its locked margin."""
        if symbol in self.pending_orders:
            order = self.pending_orders[symbol]
            locked_margin = order.get('locked_margin', 0.0)
            self.locked_in_orders = max(0.0, self.locked_in_orders - locked_margin)
            del self.pending_orders[symbol]
            self.logger.debug(f"🚫 Cancelled pending order for {symbol}, released ${locked_margin:.2f}")

    def _calculate_slippage(self, candle: Candle, symbol: str) -> float:
        """
        SOTA (Feb 2026): One-sided volume-adjusted slippage.

        Model: Retail slippage = spread + volatility cost. Volume can only
        INCREASE slippage (thin book = wider spread), never REDUCE it below
        the base rate (spread floor).

        Based on Almgren-Chriss square-root law, but ONE-SIDED:
          - volume_ratio < 1.0 → penalty (multiplier > 1.0)
          - volume_ratio >= 1.0 → no change (multiplier = 1.0)

        This matches LIVE behavior: high volume doesn't reduce spread below
        the physical minimum (bid-ask spread + fee).
        """
        volatility = (candle.high - candle.low) / candle.open if candle.open > 0 else 0
        base_slippage = self.base_slippage_rate + (volatility * 0.1)

        if not self.use_volume_slippage:
            return base_slippage

        # Track rolling volume (once per candle, dedup across intra-bar stages)
        if symbol not in self._volume_history:
            self._volume_history[symbol] = []
        if symbol not in self._volume_last_ts or self._volume_last_ts[symbol] != candle.timestamp:
            self._volume_history[symbol].append(candle.volume)
            self._volume_last_ts[symbol] = candle.timestamp
            if len(self._volume_history[symbol]) > 20:
                self._volume_history[symbol] = self._volume_history[symbol][-20:]

        # Need enough history for meaningful average
        history = self._volume_history[symbol]
        if len(history) < 5:
            return base_slippage

        avg_volume = sum(history) / len(history)
        if avg_volume <= 0:
            return base_slippage

        volume_ratio = candle.volume / avg_volume

        # ONE-SIDED penalty: only penalize low volume, never reward high volume
        # Low vol (ratio=0.5): 1/√0.5 = 1.41x slippage (+41%)
        # Low vol (ratio=0.25): 1/√0.25 = 2.0x slippage (+100%)
        # Normal+ vol (ratio>=1.0): 1.0x (unchanged, spread floor preserved)
        # Cap at 3.16x to avoid extreme values
        if volume_ratio < 1.0:
            liquidity_multiplier = min(1.0 / max(volume_ratio ** 0.5, 0.316), 3.16)
        else:
            liquidity_multiplier = 1.0

        return base_slippage * liquidity_multiplier

    def _limit_trigger_crossed(self, order: Dict[str, Any], price: float) -> bool:
        """Require price to cross beyond target by the pessimistic buffer."""
        target = order['target_price']
        buffer = target * self.pessimistic_fill_buffer
        if order['side'] == 'LONG':
            return price < (target - buffer)
        return price > (target + buffer)

    def _resolve_limit_entry_fill(self, order: Dict[str, Any], close_price: float) -> tuple[float, bool]:
        """
        Approximate live LIMIT+GTX entry flow from candle data.

        Trigger occurs when price crosses the buffered target. Resolution happens at the
        candle close: if price still closes on the triggered side, assume passive maker
        fill at the target; otherwise assume GTX timeout/reject and market fallback at
        the close price.
        """
        target = order['target_price']
        if order['side'] == 'LONG':
            if close_price <= target:
                return target, True
            return close_price, False

        if close_price >= target:
            return target, True
        return close_price, False

    def _process_symbol(self, symbol: str, candle: Candle, time: datetime):
        # SOTA: Build intra-bar price path with SL/Liq checkpoints
        # This ensures SL triggers BEFORE liquidation when price passes through both levels
        path = self._build_intrabar_path(symbol, candle)

        for stage, price in path:
            # Check if position was closed in previous iteration
            if symbol not in self.positions and symbol not in self.pending_orders:
                break

            if symbol in self.pending_orders:
                order = self.pending_orders[symbol]

                # SOTA NOTE: TTL can be enabled via order_ttl_minutes parameter in __init__
                # Default is 0 (GTC - Good Till Cancel) for backtesting accuracy
                # TTL causes re-entry and overfitted results in backtest
                # Paper/Testnet/Live use TTL via LocalSignalTracker (45 min default)
                if self.order_ttl_minutes > 0 and order.get('timestamp'):
                    order_age_minutes = (time - order['timestamp']).total_seconds() / 60
                    if order_age_minutes > self.order_ttl_minutes:
                        self.logger.debug(f"⏰ TTL EXPIRED: {symbol} (age={order_age_minutes:.1f}min)")
                        self.cancel_pending_order(symbol)
                        continue

                # LIKE-LIVE: N+1 fill rule — skip if before earliest fill time
                earliest_fill = order.get('earliest_fill_ts')
                if earliest_fill and time < earliest_fill:
                    continue

                # PARITY FIX: Block pending order fills during dead zones
                # LIVE Layer 3 blocks MARKET ORDER at trigger time during dead zones
                # BT must also block fills during dead zones to match LIVE behavior
                if self.time_filter and self.time_filter.get_size_multiplier(time) == 0:
                    self._dead_zone_fill_blocks += 1
                    self.cancel_pending_order(symbol)
                    continue

                is_fill = False
                if order['type'] == 'MARKET':
                    if stage == 'OPEN': is_fill = True
                elif order['type'] == 'LIMIT':
                    if self.use_limit_chase_parity:
                        if not order.get('limit_triggered') and self._limit_trigger_crossed(order, price):
                            order['limit_triggered'] = True
                            order['limit_trigger_stage'] = stage
                            order['limit_trigger_price'] = price
                            self._limit_entry_triggers += 1

                        if order.get('limit_triggered'):
                            if stage != 'CLOSE':
                                continue

                            fill_at_price, is_maker_fill = self._resolve_limit_entry_fill(order, price)
                            slippage = 0.0 if is_maker_fill else self._calculate_slippage(candle, symbol)
                            self._execute_fill(
                                order,
                                fill_at_price,
                                time,
                                slippage,
                                is_maker_entry=is_maker_fill,
                            )
                            if is_maker_fill:
                                self._limit_entry_maker_fills += 1
                            else:
                                self._limit_entry_market_fallbacks += 1
                            del self.pending_orders[symbol]
                            continue
                    else:
                        is_fill = self._limit_trigger_crossed(order, price)

                if is_fill:
                    slippage = self._calculate_slippage(candle, symbol)
                    # REALISTIC FILLS (Feb 2026): Use target price for LIMIT orders
                    # Old behavior: fill at candle LOW/HIGH → 3-5% ROE advantage (unrealistic)
                    # New behavior: fill at target_price → matches LIVE market order at trigger
                    if self.use_realistic_fills and order['type'] == 'LIMIT':
                        fill_at_price = order['target_price']
                    else:
                        fill_at_price = price
                    self._execute_fill(order, fill_at_price, time, slippage)
                    del self.pending_orders[symbol]
                    continue

            # Skip position monitoring if 1m monitoring handles it
            # BUT: fallback to 15m CLOSE-only check if symbol has no 1m data
            if self.use_1m_monitoring:
                if symbol in self._1m_covered_symbols:
                    continue
                # No 1m data: check SL/HC/TP/AC at CLOSE (match 1m behavior)
                # v6.6.0 FIX (B1+B2): Fixed SL units + added TP/AC checks
                if stage == 'CLOSE' and symbol in self.positions:
                    pos = self.positions[symbol]
                    if pos['entry_time'] == time:
                        continue
                    entry_price = pos['entry_price']
                    side = pos['side']
                    slippage = self.base_slippage_rate
                    leverage = pos.get('leverage', self.fixed_leverage or 10)

                    # Calculate price-based loss ratio
                    if side == 'LONG':
                        price_diff_ratio = (entry_price - price) / entry_price
                    else:
                        price_diff_ratio = (price - entry_price) / entry_price

                    # Hard cap check (already in decimal: 0.02 for 2%)
                    if self.hard_cap_pct > 0 and entry_price > 0:
                        if price_diff_ratio >= self.hard_cap_pct:
                            hc_price = entry_price * (1 - self.hard_cap_pct) if side == 'LONG' else entry_price * (1 + self.hard_cap_pct)
                            self._close_position(symbol, hc_price, "HARD_CAP", time, slippage)
                            continue

                    # SL check (B1 FIX: convert max_sl_pct from percentage to decimal)
                    if self.sl_on_close_only and self.max_sl_pct is not None and self.max_sl_pct > 0:
                        sl_decimal = self.max_sl_pct / 100.0 if self.max_sl_pct > 0.1 else self.max_sl_pct
                        if price_diff_ratio >= sl_decimal:
                            sl_price = entry_price * (1 - sl_decimal) if side == 'LONG' else entry_price * (1 + sl_decimal)
                            self._close_position(symbol, sl_price, "STOP_LOSS", time, slippage)
                            continue

                    # B2 FIX: TP check
                    if pos.get('take_profit') and entry_price > 0:
                        tp_price = pos['take_profit']
                        if (side == 'LONG' and price >= tp_price) or (side == 'SHORT' and price <= tp_price):
                            self._close_position(symbol, tp_price, "TAKE_PROFIT", time, slippage)
                            continue

                    # B2 FIX: AC check (profitable auto-close)
                    if self._resolve_close_profitable_auto(pos) and leverage > 0 and entry_price > 0:
                        if side == 'LONG':
                            roe_pct = ((price - entry_price) / entry_price) * leverage * 100
                        else:
                            roe_pct = ((entry_price - price) / entry_price) * leverage * 100
                        effective_threshold = self._resolve_effective_profitable_threshold(pos)
                        if roe_pct >= effective_threshold:
                            if self.ac_threshold_exit:
                                threshold_diff = effective_threshold * entry_price / (leverage * 100)
                                ac_price = entry_price + threshold_diff if side == 'LONG' else entry_price - threshold_diff
                            else:
                                ac_price = price
                            self._close_position(symbol, ac_price, "AUTO_CLOSE", time, slippage)
                            continue

                    # B2 FIX: MFE tracking
                    if side == 'LONG':
                        pos['mfe'] = max(pos.get('mfe', 0), (price - entry_price) / entry_price * 100)
                    else:
                        pos['mfe'] = max(pos.get('mfe', 0), (entry_price - price) / entry_price * 100)
                continue

            if symbol in self.positions:
                pos = self.positions[symbol]
                if pos['entry_time'] == time: continue
                self._update_position_logic(pos, price, time, candle, stage=stage)

    def _build_intrabar_path(self, symbol: str, candle: Candle) -> list:
        """
        SOTA: Build realistic price path within a candle.

        Includes SL and Liquidation prices as checkpoints to ensure
        SL triggers BEFORE liquidation (Binance realistic behavior).

        Standard mode:
          For bullish candle (close >= open): OPEN → LOW → HIGH → CLOSE
          For bearish candle (close < open):  OPEN → HIGH → LOW → CLOSE

        Adversarial mode (De Prado):
          For LONG positions: OPEN → LOW → HIGH → CLOSE (SL direction first)
          For SHORT positions: OPEN → HIGH → LOW → CLOSE (SL direction first)
          No position: standard bullish/bearish path
        """
        # Adversarial path: check the direction that hurts the position FIRST
        # This removes look-ahead bias from knowing candle direction (close vs open)
        if self.use_adversarial_path and symbol in self.positions:
            side = self.positions[symbol]['side']
            if side == 'LONG':
                # LONG: LOW is dangerous (SL), check it first
                base_path = [
                    ('OPEN', candle.open),
                    ('LOW', candle.low),
                    ('HIGH', candle.high),
                    ('CLOSE', candle.close)
                ]
            else:
                # SHORT: HIGH is dangerous (SL), check it first
                base_path = [
                    ('OPEN', candle.open),
                    ('HIGH', candle.high),
                    ('LOW', candle.low),
                    ('CLOSE', candle.close)
                ]
        else:
            # Standard mode: use candle direction
            is_bullish = candle.close >= candle.open
            if is_bullish:
                base_path = [
                    ('OPEN', candle.open),
                    ('LOW', candle.low),
                    ('HIGH', candle.high),
                    ('CLOSE', candle.close)
                ]
            else:
                base_path = [
                    ('OPEN', candle.open),
                    ('HIGH', candle.high),
                    ('LOW', candle.low),
                    ('CLOSE', candle.close)
                ]

        # SOTA: Insert SL and Liq prices as checkpoints if position exists
        if symbol in self.positions:
            pos = self.positions[symbol]
            sl_price = pos['stop_loss']
            liq_price = pos['liq_price']
            side = pos['side']

            # Determine price range to check
            price_min = candle.low
            price_max = candle.high

            checkpoints = []

            # Add SL if within candle range (SL should trigger FIRST)
            if price_min <= sl_price <= price_max:
                checkpoints.append(('SL_CHECK', sl_price))

            # Add Liq if within candle range (Liq triggers AFTER SL)
            if price_min <= liq_price <= price_max:
                checkpoints.append(('LIQ_CHECK', liq_price))

            if checkpoints:
                # For LONG: SL and Liq are BELOW entry, so they appear on the way DOWN
                # Sort checkpoints by distance from entry (closer = triggered first)
                if side == 'LONG':
                    # SL is higher than Liq, so SL triggers first on downward move
                    checkpoints.sort(key=lambda x: -x[1])  # Descending (higher first)
                else:
                    # For SHORT: SL and Liq are ABOVE entry
                    checkpoints.sort(key=lambda x: x[1])   # Ascending (lower first)

                # Insert checkpoints before the SL-side price stage
                # LOW first in path → insert at idx 1 (after OPEN, before LOW)
                # HIGH first in path → insert at idx 2 (after HIGH, before LOW)
                if self.use_adversarial_path and symbol in self.positions:
                    # Adversarial: LONG→LOW first (idx 1), SHORT→HIGH first
                    low_first = (self.positions[symbol]['side'] == 'LONG')
                else:
                    low_first = (candle.close >= candle.open)  # bullish → LOW first

                if low_first:
                    insert_idx = 1  # After OPEN, before LOW
                else:
                    insert_idx = 2  # After HIGH, before LOW

                for i, cp in enumerate(checkpoints):
                    base_path.insert(insert_idx + i, cp)

        return base_path


    def _update_position_logic(self, pos, price, time, candle, stage='CLOSE'):
        side = pos['side']
        symbol = pos['symbol']
        slippage = self._calculate_slippage(candle, symbol)

        # 0. LIQUIDATION CHECK (Hardcore Mode)
        liq_price = pos['liq_price']
        is_liquidated = (side == 'LONG' and price <= liq_price) or \
                        (side == 'SHORT' and price >= liq_price)

        if is_liquidated:
            self._liquidate_position(symbol, liq_price, time)
            return

        # Track Max/Min Price for Trailing
        if side == 'LONG': pos['max_price'] = max(pos['max_price'], price)
        else: pos['max_price'] = min(pos['max_price'], price)

        # MFE tracking: update peak ROE every tick
        margin = pos.get('margin', 0.0)
        if margin > 0:
            if side == 'LONG':
                curr_roe = ((price - pos['entry_price']) * pos['remaining_size'] / margin) * 100
            else:
                curr_roe = ((pos['entry_price'] - price) * pos['remaining_size'] / margin) * 100
            if curr_roe > pos.get('peak_roe', 0.0):
                pos['peak_roe'] = curr_roe

        # 0.5. TIME-BASED EXIT CHECK (Institutional Approach)
        # Based on research: Renaissance Technologies, Two Sigma, Citadel
        # Exit positions that exceed duration threshold AND are losing
        # This prevents "dead money" and reduces opportunity cost
        if self.enable_time_based_exit:
            duration_hours = (time - pos['entry_time']).total_seconds() / 3600

            if duration_hours > self.time_based_exit_duration_hours:
                # Calculate current unrealized PnL
                if side == 'LONG':
                    unrealized_pnl = (price - pos['entry_price']) * pos['remaining_size']
                else:  # SHORT
                    unrealized_pnl = (pos['entry_price'] - price) * pos['remaining_size']

                # Exit if losing (unrealized PnL < 0)
                if unrealized_pnl < 0:
                    self._time_based_exits += 1
                    self.logger.info(
                        f"⏰ TIME_BASED_EXIT: {symbol} | Duration: {duration_hours:.1f}h > {self.time_based_exit_duration_hours}h | "
                        f"Unrealized PnL: ${unrealized_pnl:.2f} | Total time-based exits: {self._time_based_exits}"
                    )
                    self._close_position(symbol, price, "TIME_BASED_EXIT_LONG_DURATION", time, slippage)
                    return

        # 1. SL Check
        # v6.0.0: When sl_on_close_only, only check SL at CLOSE stage (matches LIVE)
        if not self.sl_on_close_only or stage == 'CLOSE':
            sl_hit = (side == 'LONG' and price <= pos['stop_loss']) or \
                     (side == 'SHORT' and price >= pos['stop_loss'])
        else:
            sl_hit = False
            # v6.2.0: Hard cap check at ALL stages (matches LIVE tick-level)
            # FIX v6.3.5: Exit at threshold price, not candle extreme
            if self.hard_cap_pct > 0 and pos.get('entry_price', 0) > 0:
                if side == 'LONG':
                    hc_loss = (pos['entry_price'] - price) / pos['entry_price']
                else:
                    hc_loss = (price - pos['entry_price']) / pos['entry_price']
                if hc_loss >= self.hard_cap_pct:
                    # Calculate exact threshold crossing price
                    if side == 'LONG':
                        hc_price = pos['entry_price'] * (1 - self.hard_cap_pct)
                    else:
                        hc_price = pos['entry_price'] * (1 + self.hard_cap_pct)
                    self._close_position(symbol, hc_price, "HARD_CAP", time, slippage)
                    return
        if sl_hit:
            # SOTA FIX (Jan 2026): Semantic Exit Reason Correction
            # Check actual PnL to determine correct exit reason
            # - If exit_price > entry (LONG) or exit_price < entry (SHORT) → TRAILING_STOP or BREAKEVEN
            # - Otherwise → STOP_LOSS (actual loss)

            # Calculate approximate PnL based on SL price
            pnl_approx = (pos['stop_loss'] - pos['entry_price']) if side == 'LONG' else (pos['entry_price'] - pos['stop_loss'])

            # Determine semantic exit reason
            if pnl_approx > 0:
                # SL is above entry (LONG) or below entry (SHORT) → Profit exit
                reason = "TRAILING_STOP" if pos['tp_hit_count'] > 0 else "BREAKEVEN"
            elif abs(pnl_approx) < pos['entry_price'] * 0.0001:
                # SL is at entry (within 0.01%) → Breakeven
                reason = "BREAKEVEN"
            else:
                # SL is below entry (LONG) or above entry (SHORT) → Loss exit
                reason = "STOP_LOSS"

            # SOTA FIX: Gap-Down Logic
            # If Market Price < SL (Long), we sell at Market, not at SL.
            # Otherwise we fill at SL (perfect touch).
            exec_price = pos['stop_loss']
            if side == 'LONG' and price < exec_price:
                exec_price = price
            elif side == 'SHORT' and price > exec_price:
                exec_price = price

            self._close_position(symbol, exec_price, reason, time, slippage)
            return

        # 1.5. FIXED PROFIT CHECK (Experimental)
        # SOTA (Jan 2026): Exit when profit reaches $3.00
        # Purpose: Test if fixed profit targets improve consistency
        # Priority: After SL (safety first), before TP (profit target)
        if self.use_fixed_profit_3usd:
            if self._check_fixed_profit_exit(symbol, pos, price, time, slippage):
                return  # Position closed, skip remaining checks

        # 1.6. AUTO-CLOSE PROFITABLE CHECK
        # FIX v6.3.5b: Check AC at ALL stages (like Hard Cap), but:
        #   - At CLOSE: exit at close price (matches LIVE 1m candle close behavior)
        #   - At non-CLOSE (OPEN/HIGH/LOW): exit at THRESHOLD price (simulates 1m close catching crossing)
        # RATIONALE: LIVE checks AC 15x per 15m candle (every 1m close).
        #   Old bug: exit at extreme prices (too optimistic, inflated WR 15pp)
        #   Previous fix: only check at CLOSE (too conservative, missed 14/15 checks)
        #   This fix: check all stages but cap exit at threshold (balanced, realistic)
        if self._resolve_close_profitable_auto(pos):
            if stage == 'CLOSE':
                # At candle close: exit at close price (normal LIVE behavior)
                if self._check_auto_close_profitable(symbol, pos, price, time, slippage):
                    return  # Position closed, skip remaining checks
            else:
                # At non-CLOSE stages: check if threshold is crossed, exit at threshold price
                # This simulates a 1m candle close catching the crossing near the threshold
                if self._check_auto_close_at_threshold(symbol, pos, price, time, slippage):
                    return  # Position closed, skip remaining checks

        # 1.7. PROFIT LOCK CHECK (SOTA Jan 2026)
        # Strategy: When ROE >= threshold, move SL up to lock profit
        # Do NOT close position - just protect gains while allowing more upside
        # Priority: After auto-close (if not closing), before standard TP/Trailing
        # NOTE: PL fires at ALL stages (tick-level) — correct, like Hard Cap
        if self.use_profit_lock:
            self._check_profit_lock(symbol, pos, price, time)
            # Don't return - position is still open, continue with other checks

        # 2. TP Check
        if pos['tp_hit_count'] == 0:
            tp1 = pos['tp_levels'].get('tp1')
            if tp1:
                tp_hit = (side == 'LONG' and price >= tp1) or (side == 'SHORT' and price <= tp1) # Fix: price <= tp1 for SHORT
                if tp_hit:
                    # Default behavior: Partial TP (60% or 100%)
                    tp_pct = 1.0 if self.full_tp_at_tp1 else 0.6
                    self._take_partial_profit(symbol, tp1, tp_pct, "TAKE_PROFIT_1", time, slippage)
                    pos['stop_loss'] = pos['entry_price']
                    pos['is_breakeven'] = True

        # 3. Breakeven Trigger
        if not pos['is_breakeven']:
            # FIX (Feb 17): Direction-aware — only trigger on profitable moves
            if side == 'LONG':
                price_diff = price - pos['entry_price']
            else:
                price_diff = pos['entry_price'] - price
            if price_diff >= (pos['initial_risk'] * self.breakeven_trigger_r):
                buffer = pos['entry_price'] * 0.0005
                pos['stop_loss'] = pos['entry_price'] + buffer if side == 'LONG' else pos['entry_price'] - buffer
                pos['is_breakeven'] = True

        # 4. Trailing Stop Update
        if pos['tp_hit_count'] >= 1 and pos['atr'] > 0:
            trail = pos['atr'] * self._resolve_trailing_stop_atr(pos)
            if side == 'LONG':
                new_sl = pos['max_price'] - trail
                if new_sl > pos['stop_loss']: pos['stop_loss'] = new_sl
            else:
                new_sl = pos['max_price'] + trail
                if new_sl < pos['stop_loss']: pos['stop_loss'] = new_sl

    def _execute_fill(self, order, price, time, slippage, is_maker_entry: Optional[bool] = None):
        if is_maker_entry is None:
            is_maker_entry = bool(order['type'] == 'LIMIT' and self.use_maker_fee_entries)

        effective_slippage = 0.0 if is_maker_entry else slippage
        fill_price = price * (1 + effective_slippage) if order['side'] == 'LONG' else price * (1 - effective_slippage)
        size = order['notional'] / fill_price
        # v6.6.0: Maker fee for LIMIT entries, taker for MARKET
        entry_fee_rate = self.maker_fee_rate if is_maker_entry else self.taker_fee_rate
        entry_fee = order['notional'] * entry_fee_rate
        self.balance -= entry_fee

        # Calculate Liquidation Price (Binance Isolated Formula Approximation)
        # Liq = Entry * (1 - 1/Lev + MM) for Long
        effective_leverage = order.get('leverage_used', self.fixed_leverage if self.fixed_leverage > 0 else 10.0)

        mm_rate = self.maintenance_margin_rate

        if order['side'] == 'LONG':
            liq_price = fill_price * (1 - (1/effective_leverage) + mm_rate)
        else:
            liq_price = fill_price * (1 + (1/effective_leverage) - mm_rate)

        # SOTA CRITICAL: Calculate and deduct margin (Isolated Margin Mode)
        # Margin was already locked when order was placed.
        # Now we move it from locked_in_orders to used_margin.

        locked_margin = order.get('locked_margin', 0.0)
        self.locked_in_orders = max(0.0, self.locked_in_orders - locked_margin)

        # Recalculate exact used margin based on fill price (might differ slightly from lock)
        # But to be safe, we track what we actually committed.
        margin = order['notional'] / effective_leverage
        self.used_margin += margin

        # SOTA FIX (Jan 2026): Recalculate SL from actual fill price
        # Institutional Standard (Two Sigma, Renaissance, Citadel):
        # "Stop loss MUST be calculated from ACTUAL fill price, not theoretical signal price"
        original_sl_distance = abs(order['target_price'] - order['stop_loss'])

        if order['side'] == 'LONG':
            recalculated_sl = fill_price - original_sl_distance
        else:  # SHORT
            recalculated_sl = fill_price + original_sl_distance

        # Log recalculation for debugging
        if abs(recalculated_sl - order['stop_loss']) > 0.0001:  # Significant difference
            self.logger.debug(
                f"📐 SL Recalculated: {order['symbol']} | "
                f"Signal SL: {order['stop_loss']:.4f} → New SL: {recalculated_sl:.4f} | "
                f"Fill: {fill_price:.4f}, Distance: {original_sl_distance:.4f}"
            )

        self.positions[order['symbol']] = {
            'id': order['id'],
            'symbol': order['symbol'],
            'side': order['side'],
            'entry_price': fill_price,
            'entry_time': time,
            'stop_loss': recalculated_sl,  # ✅ FIXED: Use recalculated SL from fill price
            'liq_price': liq_price,
            'tp_levels': order['tp_levels'],
            'initial_size': size,
            'remaining_size': size,
            'notional_value': order['notional'],
            'entry_equity': order['entry_equity'],
            'initial_risk': abs(fill_price - recalculated_sl),  # ✅ FIXED: Use recalculated SL
            'is_breakeven': False,
            'tp_hit_count': 0,
            'max_price': fill_price,
            'atr': order['atr'],
            # SOTA: Track margin for proper capital management
            'margin': margin,
            'leverage_at_entry': effective_leverage,
            # INSTITUTIONAL (Feb 2026): ATR ratio for dynamic AUTO_CLOSE
            'atr_ratio': order.get('atr_ratio', 1.0),
            # MFE tracking: peak ROE during trade lifetime
            'peak_roe': 0.0,
            'entry_fee_total': entry_fee,
            'entry_liquidity': 'MAKER' if is_maker_entry else 'TAKER',
            'exit_profile': dict(order['exit_profile']) if isinstance(order.get('exit_profile'), dict) else None,
        }
        self.logger.debug(
            f"🚀 FILLED {order['symbol']} {order['side']} @ {fill_price:.2f} | "
            f"Margin: ${margin:.2f} | Lev: {effective_leverage:.1f}x | Liq: {liq_price:.2f}"
        )

    def _liquidate_position(self, symbol, price, time):
        """Force close due to liquidation. Loss = Initial Margin."""
        pos = self.positions[symbol]

        # Use stored margin from position
        margin_lost = pos.get('margin', pos['notional_value'] / pos.get('leverage_at_entry', 10.0))

        # SOTA: Release margin (it's lost, but still release tracking)
        self.used_margin = max(0.0, self.used_margin - margin_lost)

        # Deduct margin loss from balance
        self.balance -= margin_lost

        self._record_trade(
            pos,
            price,
            -margin_lost,
            "LIQUIDATION",
            time,
            pos['remaining_size'],
            exit_fee=0.0,
            exit_liquidity='TAKER',
        )
        self.logger.warning(f"☠️ LIQUIDATED {symbol} at {price:.2f}. Lost ${margin_lost:.2f}")
        del self.positions[symbol]

    def _take_partial_profit(self, symbol, price, pct, reason, time, slippage):
        pos = self.positions[symbol]
        close_size = min(pos['initial_size'] * pct, pos['remaining_size'])
        fill_price = price * (1 - slippage) if pos['side'] == 'LONG' else price * (1 + slippage)
        pnl = ((fill_price - pos['entry_price']) if pos['side'] == 'LONG' else (pos['entry_price'] - fill_price)) * close_size
        # v6.6.0: TP exits use maker fee when LIMIT configured
        tp_fee_rate = self.maker_fee_rate if self.use_maker_fee_entries else self.taker_fee_rate
        fee = (fill_price * close_size) * tp_fee_rate
        net_pnl = pnl - fee
        self.balance += net_pnl
        pos['remaining_size'] -= close_size
        pos['tp_hit_count'] += 1
        self._record_trade(
            pos,
            fill_price,
            net_pnl,
            reason,
            time,
            close_size,
            exit_fee=fee,
            exit_liquidity='MAKER' if tp_fee_rate == self.maker_fee_rate else 'TAKER',
        )

        # SOTA FIX (Jan 2026): If position fully closed (100% TP), clean up immediately
        # This prevents "Zombie Positions" with 0 size from triggering later exits
        if pos['remaining_size'] <= 0:
            # Release margin
            margin_to_release = pos.get('margin', 0)
            self.used_margin = max(0.0, self.used_margin - margin_to_release)
            # Remove from open positions
            del self.positions[symbol]
            self.logger.debug(f"🧹 FULL TP CLEANUP: {symbol} removed (100% closed)")

    def _check_fixed_profit_exit(self, symbol: str, pos: Dict[str, Any], price: float, time: datetime, slippage: float) -> bool:
        """
        SOTA (Jan 2026): Check if position should exit due to fixed $3 profit threshold.

        Returns:
            True if position was closed, False otherwise
        """
        # Calculate unrealized PnL
        remaining_size = pos['remaining_size']
        entry_price = pos['entry_price']
        side = pos['side']

        if side == 'LONG':
            unrealized_pnl = (price - entry_price) * remaining_size
        else:  # SHORT
            unrealized_pnl = (entry_price - price) * remaining_size

        # Check if profit >= $3.00 threshold
        if unrealized_pnl >= 3.00:
            self._fixed_profit_exits += 1
            self.logger.info(
                f"💰 FIXED_PROFIT_3USD: {symbol} | "
                f"Unrealized PnL: ${unrealized_pnl:.2f} >= $3.00 | "
                f"Price: {price:.4f} | Entry: {entry_price:.4f} | "
                f"Total fixed profit exits: {self._fixed_profit_exits}"
            )
            self._close_position(symbol, price, "FIXED_PROFIT_3USD", time, slippage)
            return True

        return False

    def _check_auto_close_profitable(self, symbol: str, pos: Dict[str, Any], price: float, time: datetime, slippage: float) -> bool:
        """
        EXPERIMENTAL (Jan 2026): Check if position should be auto-closed due to reaching profit threshold.

        Strategy: "Take profits early, let losses recover"
        - Automatically closes positions when ROE > threshold
        - Keeps losing positions open (PnL < 0)
        - Checks every N candles (configurable via profitable_check_interval)

        Args:
            symbol: Trading symbol
            pos: Position dictionary
            price: Current market price
            time: Current timestamp
            slippage: Slippage rate for execution

        Returns:
            True if position was closed, False otherwise
        """
        # Guard: Feature disabled
        if not self._resolve_close_profitable_auto(pos):
            return False

        # Guard: Check interval (only check every N candles)
        if self._candle_count % self.profitable_check_interval != 0:
            return False

        # Calculate unrealized PnL
        remaining_size = pos['remaining_size']
        entry_price = pos['entry_price']
        side = pos['side']
        margin = pos.get('margin', 0.0)

        if side == 'LONG':
            unrealized_pnl = (price - entry_price) * remaining_size
        else:  # SHORT
            unrealized_pnl = (entry_price - price) * remaining_size

        # Guard: Only close profitable positions (PnL > 0)
        if unrealized_pnl <= 0:
            return False

        # Calculate ROE percentage
        if margin <= 0:
            self.logger.warning(
                f"⚠️ Position {symbol} has invalid margin ({margin}), skipping auto-close check"
            )
            return False

        roe_pct = (unrealized_pnl / margin) * 100

        # INSTITUTIONAL (Feb 2026): Dynamic AUTO_CLOSE threshold based on ATR
        effective_threshold = self._resolve_effective_profitable_threshold(pos)

        # Check if ROE exceeds threshold
        if roe_pct > effective_threshold:
            threshold_label = (
                f"{effective_threshold:.1f}% (dynamic)"
                if self.use_dynamic_tp
                else f"{self._resolve_profitable_threshold_pct(pos)}%"
            )

            # LIKE-LIVE: Calculate threshold price (exit at threshold, not candle close)
            # In LIVE, 1m candle catches the crossing near threshold → exit ~7.0% ROE
            # In old BT, 15m candle close could be 15% ROE → free +8% ROE per trade
            if self.ac_threshold_exit:
                leverage = pos.get('leverage_at_entry', self.fixed_leverage if self.fixed_leverage > 0 else 10.0)
                threshold_diff = effective_threshold * entry_price / (leverage * 100)
                if side == 'LONG':
                    exit_price = entry_price + threshold_diff
                else:
                    exit_price = entry_price - threshold_diff
            else:
                exit_price = price

            # EXPERIMENTAL: Partial close at AC — close 50%, trail rest
            partial_close_ac = self._resolve_partial_close_ac(pos)
            partial_close_ac_pct = self._resolve_partial_close_ac_pct(pos)
            if partial_close_ac:
                self._partial_ac_exits += 1
                self._auto_close_exits += 1
                self.logger.info(
                    f"💰 AUTO_CLOSE_PARTIAL: {symbol} | "
                    f"ROE: {roe_pct:.2f}% > threshold: {threshold_label} | "
                    f"Closing {partial_close_ac_pct * 100:.0f}%, trailing rest | "
                    f"PnL: ${unrealized_pnl:.2f}"
                )
                self._take_partial_profit(
                    symbol,
                    exit_price,
                    partial_close_ac_pct,
                    "AUTO_CLOSE_PARTIAL",
                    time,
                    slippage,
                )
                # If position still open after partial close, set breakeven + trailing
                if symbol in self.positions:
                    pos['stop_loss'] = entry_price
                    pos['is_breakeven'] = True
                return True

            self._auto_close_exits += 1
            self.logger.info(
                f"💰 AUTO_CLOSE_PROFITABLE: {symbol} | "
                f"ROE: {roe_pct:.2f}% > threshold: {threshold_label} | "
                f"PnL: ${unrealized_pnl:.2f} | Price: {exit_price:.4f} | Entry: {entry_price:.4f} | "
                f"Total auto-close exits: {self._auto_close_exits}"
            )
            self._close_position(symbol, exit_price, "AUTO_CLOSE_PROFITABLE", time, slippage)
            return True

        return False

    def _check_auto_close_at_threshold(self, symbol: str, pos: Dict[str, Any], price: float, time, slippage: float) -> bool:
        """
        FIX v6.3.5b: Check AC at non-CLOSE stages, exit at THRESHOLD price.

        Same pattern as Hard Cap: if price crosses threshold during the candle,
        exit at the exact threshold price (not at the extreme candle price).
        This simulates LIVE where a 1m candle close would catch the crossing
        near the threshold price, not at the 15m candle HIGH/LOW.
        """
        remaining_size = pos['remaining_size']
        entry_price = pos['entry_price']
        side = pos['side']
        margin = pos.get('margin', 0.0)

        if side == 'LONG':
            unrealized_pnl = (price - entry_price) * remaining_size
        else:
            unrealized_pnl = (entry_price - price) * remaining_size

        if unrealized_pnl <= 0 or margin <= 0:
            return False

        roe_pct = (unrealized_pnl / margin) * 100

        effective_threshold = self._resolve_effective_profitable_threshold(pos)

        if roe_pct > effective_threshold:
            # Calculate exact threshold crossing price (same as 1m ac_tick_level logic)
            leverage = pos.get('leverage_at_entry', self.fixed_leverage if self.fixed_leverage > 0 else 10.0)
            threshold_diff = effective_threshold * entry_price / (leverage * 100)
            if side == 'LONG':
                threshold_price = entry_price + threshold_diff
            else:
                threshold_price = entry_price - threshold_diff

            self._auto_close_exits += 1
            self.logger.info(
                f"💰 AUTO_CLOSE_AT_THRESHOLD: {symbol} | "
                f"ROE: {roe_pct:.2f}% > threshold: {effective_threshold:.1f}% | "
                f"Exit at threshold price: {threshold_price:.4f} (not stage price: {price:.4f}) | "
                f"Entry: {entry_price:.4f}"
            )
            self._close_position(symbol, threshold_price, "AUTO_CLOSE_PROFITABLE", time, slippage)
            return True

        return False

    def _check_profit_lock(self, symbol: str, pos: Dict[str, Any], price: float, time: datetime) -> bool:
        """
        SOTA (Jan 2026): Check if profit lock should be triggered.

        Strategy: When ROE >= threshold, move SL up to lock profit, keep position open.
        - Do NOT close position - just move SL
        - Allow profit to run while protecting gains
        - 1% buffer between threshold (5%) and lock (4%) to avoid wick triggers

        Args:
            symbol: Trading symbol
            pos: Position dictionary
            price: Current market price
            time: Current timestamp

        Returns:
            True if profit lock was triggered/updated, False otherwise
        """
        # Guard: Feature disabled
        if not self.use_profit_lock:
            return False

        # Calculate unrealized ROE
        remaining_size = pos['remaining_size']
        entry_price = pos['entry_price']
        side = pos['side']
        margin = pos.get('margin', 0.0)
        # FIX v6.3.5: Use correct leverage field name (was 'leverage' → default 1.0!)
        leverage = pos.get('leverage_at_entry', self.fixed_leverage if self.fixed_leverage > 0 else 10.0)

        if side == 'LONG':
            unrealized_pnl = (price - entry_price) * remaining_size
        else:  # SHORT
            unrealized_pnl = (entry_price - price) * remaining_size

        # Guard: Only lock profitable positions
        if unrealized_pnl <= 0:
            return False

        # Guard: Invalid margin
        if margin <= 0:
            return False

        roe_pct = (unrealized_pnl / margin) * 100

        # Check if ROE >= threshold to trigger lock
        if roe_pct >= self.profit_lock_threshold_pct:
            # Calculate lock price at profit_lock_pct ROE
            # For LONG: lock_price = entry * (1 + lock_roe / leverage)
            # For SHORT: lock_price = entry * (1 - lock_roe / leverage)
            lock_roe_decimal = self.profit_lock_pct / 100.0  # e.g., 6% = 0.06

            if side == 'LONG':
                lock_price = entry_price * (1 + lock_roe_decimal / leverage)
                # Only move SL up (never down for LONG)
                if lock_price > pos['stop_loss']:
                    old_sl = pos['stop_loss']
                    pos['stop_loss'] = lock_price

                    # First time triggering profit lock?
                    if symbol not in self._profit_locked_symbols:
                        self._profit_locked_symbols.add(symbol)
                        self._profit_lock_triggered += 1
                        self.logger.info(
                            f"🔒 PROFIT_LOCK: {symbol} | ROE: {roe_pct:.2f}% >= {self.profit_lock_threshold_pct}% | "
                            f"SL: ${old_sl:.4f} → ${lock_price:.4f} (lock {self.profit_lock_pct}% ROE) | "
                            f"Total locks: {self._profit_lock_triggered}"
                        )
                    else:
                        # Trailing profit lock
                        self.logger.debug(
                            f"🔒 PROFIT_LOCK TRAIL: {symbol} | SL: ${old_sl:.4f} → ${lock_price:.4f}"
                        )
                    return True
            else:  # SHORT
                lock_price = entry_price * (1 - lock_roe_decimal / leverage)
                # Only move SL down (never up for SHORT)
                if lock_price < pos['stop_loss']:
                    old_sl = pos['stop_loss']
                    pos['stop_loss'] = lock_price

                    if symbol not in self._profit_locked_symbols:
                        self._profit_locked_symbols.add(symbol)
                        self._profit_lock_triggered += 1
                        self.logger.info(
                            f"🔒 PROFIT_LOCK: {symbol} | ROE: {roe_pct:.2f}% >= {self.profit_lock_threshold_pct}% | "
                            f"SL: ${old_sl:.4f} → ${lock_price:.4f} (lock {self.profit_lock_pct}% ROE) | "
                            f"Total locks: {self._profit_lock_triggered}"
                        )
                    else:
                        self.logger.debug(
                            f"🔒 PROFIT_LOCK TRAIL: {symbol} | SL: ${old_sl:.4f} → ${lock_price:.4f}"
                        )
                    return True

        return False

    def get_portfolio_target_usd(self) -> float:
        """Return the active portfolio target in USD."""
        if self.portfolio_target_pct > 0:
            return max(0.0, self.balance * (self.portfolio_target_pct / 100.0))
        return max(0.0, self.portfolio_target)

    def check_portfolio_target(self, candle_map: Dict[str, Candle]) -> bool:
        """
        SOTA (Jan 2026): Check if portfolio profit target hit.

        Institutional practice:
        - Renaissance Technologies: Daily profit target 0.5-1% of capital
        - Two Sigma: Portfolio-level risk limits
        - Citadel: Intraday profit targets per strategy

        Returns:
            True if portfolio target hit, False otherwise
        """
        target_usd = self.get_portfolio_target_usd()
        if target_usd <= 0:
            return False

        # Calculate total unrealized PnL across all positions
        total_unrealized_pnl = 0.0

        for symbol, pos in self.positions.items():
            # Get current price from candle map
            if symbol not in candle_map:
                continue

            current_price = candle_map[symbol].close
            remaining_size = pos['remaining_size']
            entry_price = pos['entry_price']
            side = pos['side']

            if side == 'LONG':
                unrealized_pnl = (current_price - entry_price) * remaining_size
            else:  # SHORT
                unrealized_pnl = (entry_price - current_price) * remaining_size

            total_unrealized_pnl += unrealized_pnl

        # Check if target hit
        if total_unrealized_pnl >= target_usd:
            self.logger.info(
                f"🎯 PORTFOLIO_TARGET_HIT: Total PnL ${total_unrealized_pnl:.2f} >= Target ${self.portfolio_target:.2f} | "
                f"Open positions: {len(self.positions)}"
            )
            return True

        return False

    def check_signal_reversal(self, signal: TradingSignal) -> List[str]:
        """
        SOTA (Jan 2026): Check if signal indicates reversal for open positions.

        Institutional practice:
        - Jane Street: Exit on opposite signal detection (85-95% confidence)
        - Citadel: Momentum reversal detection
        - Jump Trading: Real-time signal monitoring

        Returns:
            List of symbols to close due to signal reversal
        """
        if not self.enable_reversal_exit:
            return []

        symbols_to_close = []

        for symbol, pos in self.positions.items():
            if symbol != signal.symbol:
                continue

            # LONG position + SHORT signal = reversal
            if pos['side'] == 'LONG' and signal.signal_type == SignalType.SELL:
                if signal.confidence >= self.reversal_confidence:
                    symbols_to_close.append(symbol)
                    self._reversal_exits += 1
                    self.logger.info(
                        f"🔄 SIGNAL_REVERSAL: {symbol} LONG → SHORT signal "
                        f"(conf={signal.confidence:.2%}) | Total reversal exits: {self._reversal_exits}"
                    )

            # SHORT position + LONG signal = reversal
            elif pos['side'] == 'SHORT' and signal.signal_type == SignalType.BUY:
                if signal.confidence >= self.reversal_confidence:
                    symbols_to_close.append(symbol)
                    self._reversal_exits += 1
                    self.logger.info(
                        f"🔄 SIGNAL_REVERSAL: {symbol} SHORT → LONG signal "
                        f"(conf={signal.confidence:.2%}) | Total reversal exits: {self._reversal_exits}"
                    )

        return symbols_to_close

    def _close_position(self, symbol, price, reason, time, slippage):
        pos = self.positions[symbol]
        remaining = pos['remaining_size']
        fill_price = price * (1 - slippage) if pos['side'] == 'LONG' else price * (1 + slippage)
        pnl = ((fill_price - pos['entry_price']) if pos['side'] == 'LONG' else (pos['entry_price'] - fill_price)) * remaining
        # v6.6.0: SL/HC always taker (MARKET). AC/TP use maker when configured.
        sl_reasons = {'STOP_LOSS', 'HARD_CAP', 'LIQUIDATION', 'extreme_loss', 'MAX_DRAWDOWN', 'TIME_EXIT', 'DZ_FORCE_CLOSE'}
        exit_fee_rate = self.taker_fee_rate
        if self.use_maker_fee_entries and reason.upper() not in sl_reasons:
            exit_fee_rate = self.maker_fee_rate
        exit_fee = (fill_price * remaining) * exit_fee_rate
        net_pnl = pnl - exit_fee

        # SOTA CRITICAL: Release margin back to available balance (Isolated Margin Mode)
        margin_to_release = pos.get('margin', 0)
        self.used_margin = max(0.0, self.used_margin - margin_to_release)

        # Add P&L to balance (margin is already tracked separately)
        self.balance += net_pnl

        self._record_trade(
            pos,
            fill_price,
            net_pnl,
            reason,
            time,
            remaining,
            exit_fee=exit_fee,
            exit_liquidity='MAKER' if exit_fee_rate == self.maker_fee_rate else 'TAKER',
        )
        del self.positions[symbol]

    def _record_trade(self, pos, exit_price, pnl, reason, time, size, exit_fee: float = 0.0, exit_liquidity: str = ""):
        pct_of_original = size / pos['initial_size']
        leverage = pos.get('leverage_at_entry', pos['notional_value'] / pos['entry_equity'] if pos['entry_equity'] > 0 else 0)
        entry_fee_paid = pos.get('entry_fee_total', 0.0) * pct_of_original
        net_pnl_after_all_fees = pnl - entry_fee_paid

        trade = BacktestTrade(
            trade_id=pos['id'],
            symbol=pos['symbol'],
            side=pos['side'],
            entry_price=pos['entry_price'],
            exit_price=exit_price,
            entry_time=pos['entry_time'],
            exit_time=time,
            pnl_usd=net_pnl_after_all_fees,
            pnl_pct=(net_pnl_after_all_fees / (pos['notional_value'] * pct_of_original)) * 100 if pct_of_original > 0 else 0,
            exit_reason=reason,
            position_size=size,
            notional_value=pos['notional_value'] * pct_of_original,
            leverage_at_entry=leverage,
            margin_at_entry=pos.get('margin', pos['entry_equity']),  # SOTA: Use actual margin from position
            funding_cost=pos.get('funding_cost', 0.0) * pct_of_original,  # Proportional funding
            balance_at_exit=self.balance,
            peak_roe_pct=pos.get('peak_roe', 0.0),
            entry_fee_paid=entry_fee_paid,
            exit_fee_paid=exit_fee,
            entry_liquidity=pos.get('entry_liquidity', ''),
            exit_liquidity=exit_liquidity,
        )
        self.trades.append(trade)

    def get_stats(self) -> Dict[str, Any]:
        if not self.trades:
            return {
                "initial_balance": self.initial_balance,
                "final_balance": self.balance,
                "net_return_usd": 0.0,
                "net_return_pct": 0.0,
                "total_trades": 0,
                "win_rate": 0.0,
                "winning_trades": 0,
                "losing_trades": 0,
                "capital_exhausted": self.is_capital_exhausted(),
                "capital_exhausted_at": self._capital_exhausted_at,
                "no_compound_slot_size": self.get_no_compound_slot_size() if self.no_compound else 0.0,
                "available_balance": self.available_balance,
                "limit_entry_triggers": self._limit_entry_triggers,
                "limit_entry_maker_fills": self._limit_entry_maker_fills,
                "limit_entry_market_fallbacks": self._limit_entry_market_fallbacks,
            }
        winning_trades = [t for t in self.trades if t.pnl_usd > 0]
        total_pnl = sum(t.pnl_usd for t in self.trades)
        total_funding_cost = sum(t.funding_cost for t in self.trades)

        # SOTA: Net Return should be based on BALANCE change, not just trade PnL sum
        # This captures Entry Fees, Funding, etc. that affect balance directly.
        net_return_usd = self.balance - self.initial_balance

        return {
            "initial_balance": self.initial_balance,
            "final_balance": self.balance,
            "net_return_usd": net_return_usd,
            "net_return_pct": (net_return_usd / self.initial_balance) * 100,
            "total_trades": len(self.trades),
            "win_rate": (len(winning_trades) / len(self.trades)) * 100,
            "winning_trades": len(winning_trades),
            "losing_trades": len(self.trades) - len(winning_trades),
            # SOTA: Funding rate metrics
            "funding_paid": self._total_funding_paid,
            "funding_received": self._total_funding_received,
            "funding_net": self._total_funding_received - self._total_funding_paid,
            "total_funding_cost_in_trades": total_funding_cost,
            "capital_exhausted": self.is_capital_exhausted(),
            "capital_exhausted_at": self._capital_exhausted_at,
            "no_compound_slot_size": self.get_no_compound_slot_size() if self.no_compound else 0.0,
            "available_balance": self.available_balance,
            "limit_entry_triggers": self._limit_entry_triggers,
            "limit_entry_maker_fills": self._limit_entry_maker_fills,
            "limit_entry_market_fallbacks": self._limit_entry_market_fallbacks,
        }
