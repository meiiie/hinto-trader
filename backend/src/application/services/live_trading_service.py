"""
LiveTradingService - Application Layer

Bridges signal generation → order execution for live trading.
This is the "brain" that connects strategy signals to real orders.

SOTA Features:
- Signal validation before execution
- Position size calculation (risk-based)
- Order lifecycle management
- Safety checks (max positions, drawdown limits)
- Testnet/Production toggle

WARNING: This service executes REAL trades when connected to production!
"""

import os
import asyncio
import threading  # SOTA FIX (Feb 2026): For RLock on _local_positions (sync+async compatibility)
import logging
from collections import defaultdict
from typing import Optional, Dict, List, Any, TYPE_CHECKING
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import random  # SOTA FIX (Feb 2026): For periodic portfolio PnL logging
import time  # v6.1.0: For _closing_symbols_ts timeout tracking

if TYPE_CHECKING:
    from ...infrastructure.execution.priority_execution_queue import PriorityExecutionQueue
    from ...infrastructure.execution.execution_worker import ExecutionWorker

from ..backtest.execution_simulator import BacktestTrade
from ...infrastructure.api.binance_futures_client import (
    BinanceFuturesClient,
    OrderSide,
    OrderType,
    TimeInForce,
    FuturesOrder,
    FuturesPosition
)
from ...domain.entities.trading_signal import TradingSignal, SignalType
from .local_signal_tracker import LocalSignalTracker, PendingSignal, SignalDirection

# SOTA (Jan 2026): Import event bus for position event broadcasting
from ...api.event_bus import get_event_bus
from ...domain.entities.local_position_tracker import LocalPosition, FillRecord

from ...infrastructure.notifications.telegram_service import (
    TelegramService,
    PositionContext,  # SOTA: Rich context for entry notifications
    ExitContext,      # SOTA: Rich context for exit notifications
    SystemAlert,      # SOTA (Feb 2026): System health alerts
)
from ...trading_contract import (
    PRODUCTION_AUTO_CLOSE_INTERVAL,
    PRODUCTION_CLOSE_PROFITABLE_AUTO,
    PRODUCTION_LIMIT_CHASE_TIMEOUT_SECONDS,
    PRODUCTION_MAX_SL_PCT,
    PRODUCTION_ORDER_TTL_MINUTES,
    PRODUCTION_ORDER_TYPE,
    PRODUCTION_PORTFOLIO_TARGET_PCT,
    PRODUCTION_PROFITABLE_THRESHOLD_PCT,
)


@dataclass
class ShortSignalFilterMetrics:
    """Metrics for SHORT signal filtering (3-layer defense)."""
    layer1_blocked: int  # SignalGenerator
    layer2_blocked: int  # SharkTankCoordinator
    layer3_blocked: int  # LiveTradingService
    total_blocked: int
    session_start: datetime
    mode: str  # "live", "paper", "backtest"


class TradingMode(Enum):
    PAPER = "paper"      # Internal simulation (SQLite)
    TESTNET = "testnet"  # Binance testnet (demo money)
    LIVE = "live"        # Production (real money)


@dataclass
class LiveTradeResult:
    """Result of a live trade execution."""
    success: bool
    order: Optional[FuturesOrder] = None
    error: Optional[str] = None
    signal_id: Optional[str] = None
    timestamp: datetime =  None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)


@dataclass
class PendingOrderInfo:
    """
    Stores signal info alongside pending order.

    SOTA: When limit order fills (via User Data Stream),
    we use this info to place bracket orders (SL/TP).
    """
    order: FuturesOrder
    signal: TradingSignal
    stop_loss: float
    take_profit: float
    entry_side: str  # 'BUY' or 'SELL'
    quantity: float


@dataclass
class PositionState:
    """
    SOTA Hybrid TP/SL: Tracks active position with exchange order IDs.

    This enables:
    1. Display TP/SL in Portfolio from local state
    2. Update trailing stop by cancel old → place new
    3. Sync verification between local and exchange
    """
    symbol: str
    entry_price: float
    quantity: float
    side: str  # 'LONG' or 'SHORT'
    leverage: int

    # TP/SL values
    initial_sl: float = 0.0      # Original SL from signal
    current_sl: float = 0.0      # Updated by trailing/breakeven
    initial_tp: float = 0.0      # Original TP from signal
    current_tp: float = 0.0      # May change with partial closes

    # Exchange order IDs (for cancel/update)
    sl_order_id: Optional[str] = None
    tp_order_id: Optional[str] = None

    # Watermarks for trailing stop logic
    highest_price: float = 0.0
    lowest_price: float = float('inf')

    # Timestamps
    entry_time: Optional[datetime] = None


class LiveTradingService:
    """
    SOTA Live Trading Service.

    Connects signal generation to order execution with:
    - Risk management (position sizing)
    - Safety limits (max positions, drawdown)
    - Order lifecycle tracking
    - Multi-symbol support

    Usage:
        service = LiveTradingService(mode=TradingMode.TESTNET)

        # Execute a signal
        result = service.execute_signal(signal)

        # Check positions
        positions = service.get_all_positions()
    """

    def __init__(
        self,
        mode: TradingMode = TradingMode.TESTNET,
        risk_per_trade: float = 0.01,  # 1% risk per trade
        max_positions: int = 4,  # DATA-DRIVEN: pos4 optimal (Feb 23 sweep: pos3=PT-dependent, pos5=diluted)
        max_leverage: int = 20,  # v6.6.0: Match production 20x (validated Feb 23 sweep)
        max_drawdown_pct: float = 0.15,  # 15% max drawdown
        enable_trading: bool = True,
        settings_repo = None,  # SOTA: Optional IOrderRepository for Settings sync
        intelligence_service = None, # SOTA: Injected Intelligence Service
        order_repo = None,  # SOTA (Jan 2026): For persisting live position TP/SL
        # SOTA (Jan 2026): BTC Filter
        use_btc_filter: bool = False,  # Filter signals based on BTC EMA 50/200
        # SOTA (Jan 2026): Portfolio Target
        portfolio_target_pct: float = 0.0,  # Portfolio profit target % (0 = disabled, default 8% for LIVE)
        # SOTA (Jan 2026): MAX SL Validation - Reject signals with SL too far
        use_max_sl_validation: bool = True,  # PARITY FIX: Match backtest --max-sl-validation
        max_sl_pct: float = PRODUCTION_MAX_SL_PCT,
        telegram_service: Optional[TelegramService] = None,  # SOTA: Telegram Notification Service
    ):
        """
        Initialize LiveTradingService.

        Args:
            mode: Trading mode (PAPER, TESTNET, LIVE)
            risk_per_trade: Risk per trade as decimal (0.01 = 1%)
            max_positions: Maximum concurrent positions
            max_leverage: Maximum leverage allowed
            max_drawdown_pct: Maximum drawdown before stopping
            enable_trading: Master switch for trading
            settings_repo: Optional repository for loading persistent settings
            intelligence_service: Shared MarketIntelligenceService instance
        """
        self.logger = logging.getLogger(__name__)
        self.telegram_service = telegram_service  # SOTA Notification
        self.mode = mode

        # SOTA (Jan 2026): Store settings_repo for later use in execute_signal()
        self.settings_repo = settings_repo

        # SOTA (Jan 2026): BTC Filter - Store constructor param
        self._use_btc_filter = use_btc_filter

        # SOTA (Jan 2026): Portfolio Target - Store constructor param
        # Default 10% for LIVE mode, 0% (disabled) for others
        is_live_mode = mode == TradingMode.LIVE

        # Validation: portfolio_target_pct must be 0-100
        if portfolio_target_pct < 0 or portfolio_target_pct > 100:
            logger.warning(
                f"⚠️ Invalid portfolio_target_pct={portfolio_target_pct}. "
                f"Must be 0-100. Using default."
            )
            portfolio_target_pct = PRODUCTION_PORTFOLIO_TARGET_PCT if is_live_mode else 0.0

        if portfolio_target_pct == 0.0 and is_live_mode:
            self.portfolio_target_pct = PRODUCTION_PORTFOLIO_TARGET_PCT
        else:
            self.portfolio_target_pct = portfolio_target_pct

        # SOTA (Jan 2026): Auto-Close Profitable - Store constructor params
        # Default: ENABLED (True) to match settings.py API default
        # Threshold default: 10.0% ROE
        self.close_profitable_auto: bool = PRODUCTION_CLOSE_PROFITABLE_AUTO
        self.profitable_threshold_pct: float = PRODUCTION_PROFITABLE_THRESHOLD_PCT

        # SOTA (Feb 2026): SHORT Trading ENABLED
        # Updated: Allow both LONG and SHORT directions
        self.allow_shorts: bool = True

        # SOTA (Feb 2026): Configurable AUTO_CLOSE check interval
        # '1m' = institutional standard (higher win rate, lower overshoot)
        # '15m' = backtest parity (matches OHLC discretization)
        self.auto_close_interval: str = PRODUCTION_AUTO_CLOSE_INTERVAL

        # v6.6.0: Order Type Configuration (MARKET→LIMIT migration path)
        # Production contract defaults to LIMIT+GTX with MARKET fallback.
        self.order_type: str = PRODUCTION_ORDER_TYPE
        self.limit_chase_timeout_seconds: int = PRODUCTION_LIMIT_CHASE_TIMEOUT_SECONDS

        # v6.6.0: LIMIT order statistics (for Telegram daily summary)
        self._limit_stats = {
            'attempted': 0, 'filled': 0,
            'rejected': 0,   # -5022 (price crosses book)
            'timeout': 0,    # 5s expired, cancelled
            'error': 0,      # Network/API error
            'fallback': 0    # Total MARKET fallbacks (= rejected + timeout + error)
        }
        # v6.6.0: Pending entry guard — prevents max_positions race with concurrent LIMIT orders
        self._pending_entry_symbols: set = set()
        # v6.6.0: Thread pool for GTX polling — prevents event loop blocking during 5s poll
        from concurrent.futures import ThreadPoolExecutor
        self._gtx_thread_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="gtx")

        # SOTA (Feb 2026): Profit Lock (ratchet stop)
        # When ROE >= threshold, move SL to lock profit without closing position
        # Lets winners run while protecting gains (institutional pattern)
        self.use_profit_lock: bool = False  # DATA-DRIVEN: PL conflicts with AUTO_CLOSE 7% (gap too narrow, cuts winners)
        self.profit_lock_threshold_pct: float = 5.0  # ROE % to trigger lock
        self.profit_lock_pct: float = 4.0  # ROE % to lock (1% buffer from threshold)

        # SOTA (Jan 2026): Local position tracking (institutional pattern)
        # Replaces unreliable Binance unrealizedProfit
        self._local_positions: Dict[str, LocalPosition] = {}
        # SOTA FIX (Feb 2026): Use threading.RLock for sync+async compatibility
        # Pattern from Two Sigma/Citadel: RLock is reentrant and works in both sync/async contexts
        self._local_positions_lock = threading.RLock()

        # SOTA (Jan 2026): Pending Exit Reasons (for Telegram Notifications)
        # Store reason (SL/TP/TRAILING) when initiating local exit
        self._pending_exit_reasons: Dict[str, str] = {}
        # SOTA FIX (Feb 2026): Use threading.RLock for sync+async compatibility
        self._pending_exit_reasons_lock = threading.RLock()

        # SOTA FIX (Feb 2026): Dedupe entry notifications
        # Track symbols already notified to prevent duplicate entry notifications from partial fills
        self._notified_entry_symbols: set = set()

        # SOTA (Feb 2026): Dedupe exit notifications
        # Track symbols already notified via backup exit path to prevent double-sending
        # (fill-based path in _record_fill_to_local_tracker may also fire)
        self._exit_notified_symbols: set = set()

        # SOTA (Feb 2026): Track async tasks for clean shutdown
        self._daily_summary_task: Optional[asyncio.Task] = None

        # v6.3.0: Analytics collector (fire-and-forget after each close)
        self._analytics_collector = None  # Wired by DI container
        self._analytics_report_service = None  # Wired by DI container

        # SOTA FIX (Feb 2026): Initialize balance tracking for Portfolio Target
        # These are set by user_data_stream.py on first ACCOUNT_UPDATE
        # Without this, AttributeError when checking initial_balance == 0
        self.initial_balance: float = 0.0
        self.peak_balance: float = 0.0

        self.logger.info("✅ LOCAL PnL tracking enabled (SOTA 2026) with thread-safe locks")

        # SOTA: Load from Settings if repository provided (sync with Paper/Backtest)
        # Defaults match backtest CLI: --max-pos 10 --leverage 10 --risk 0.01
        if settings_repo:
            try:
                settings = settings_repo.get_all_settings()
                self.max_positions = int(settings.get('max_positions', max_positions))
                self.max_leverage = int(settings.get('leverage', max_leverage))
                self.risk_per_trade = float(settings.get('risk_percent', risk_per_trade * 100)) / 100
                # SOTA: Load Smart Recycling setting (handle str or bool)
                # SOTA SYNC (Jan 2026): Default TRUE to match backtest --zombie-killer
                sr_val = settings.get('smart_recycling', True)  # Default True for Parity with backtest
                self.enable_recycling = str(sr_val).lower() == 'true' if isinstance(sr_val, (str, bool)) else True

                # SOTA: Load TTL setting
                # SOTA FIX (Jan 23, 2026): Default 50 minutes TTL
                # Prevents zombie orders while allowing reasonable fill time
                # Load from settings or use 50 minutes default
                self.order_ttl_minutes = int(
                    settings.get('execution_ttl_minutes', PRODUCTION_ORDER_TTL_MINUTES)
                )

                # SOTA (Jan 2026): Load auto_execute from settings
                ae_val = settings.get('auto_execute', True)  # Default True for LIVE mode
                self.enable_trading = str(ae_val).lower() == 'true' if isinstance(ae_val, str) else bool(ae_val)

                # SOTA (Jan 2026): Load BTC Filter setting
                self._use_btc_filter = settings.get('use_btc_filter', use_btc_filter)

                # SOTA (Jan 2026): Load Portfolio Target setting
                # Default 10% for LIVE mode, 0% (disabled) for others
                loaded_target = float(settings.get('portfolio_target_pct', self.portfolio_target_pct))
                if loaded_target < 0 or loaded_target > 100:
                    self.logger.warning(f"⚠️ Invalid portfolio_target_pct={loaded_target}. Must be 0-100. Using default.")
                else:
                    self.portfolio_target_pct = loaded_target

                # SOTA (Jan 2026): Load Auto-Close Profitable settings
                # Default: disabled (False), threshold 10.0% (SOTA FIX Feb 2026)
                # SOTA FIX: Add None check to prevent overwriting defaults
                ac_val = settings.get('close_profitable_auto')
                if ac_val is not None:
                    self.close_profitable_auto = str(ac_val).lower() == 'true' if isinstance(ac_val, str) else bool(ac_val)
                # else: keep default (False)

                threshold_val = settings.get('profitable_threshold_pct')
                if threshold_val is not None:
                    threshold = float(threshold_val)
                    # Validate threshold
                    if threshold <= 0 or threshold > 100:
                        self.logger.warning(
                            f"⚠️ Invalid profitable_threshold_pct={threshold}. Must be 0-100. "
                            f"Using default {PRODUCTION_PROFITABLE_THRESHOLD_PCT:.1f}%."
                        )
                        self.profitable_threshold_pct = PRODUCTION_PROFITABLE_THRESHOLD_PCT
                    # Keep user-configured threshold
                    # Root Cause: DB stores stale 5.0% from old config, causing premature exit
                    else:
                        self.profitable_threshold_pct = threshold
                # else: keep production default threshold configured above

                # SOTA (Feb 2026): Load Profit Lock settings
                pl_val = settings.get('use_profit_lock')
                if pl_val is not None:
                    self.use_profit_lock = str(pl_val).lower() == 'true' if isinstance(pl_val, str) else bool(pl_val)
                pl_threshold = settings.get('profit_lock_threshold_pct')
                if pl_threshold is not None:
                    self.profit_lock_threshold_pct = float(pl_threshold)
                pl_lock = settings.get('profit_lock_pct')
                if pl_lock is not None:
                    self.profit_lock_pct = float(pl_lock)

                # SOTA FIX (Feb 2026): Load auto_close_interval from DB
                aci_val = settings.get('auto_close_interval')
                if aci_val is not None and str(aci_val).strip() in ('1m', '15m'):
                    self.auto_close_interval = str(aci_val).strip()

                # v6.5.12: Load DZ Force-Close setting from DB
                dz_fc_val = settings.get('dz_force_close_enabled')
                if dz_fc_val is not None:
                    self.dz_force_close_enabled = str(dz_fc_val).lower() == 'true' if isinstance(dz_fc_val, str) else bool(dz_fc_val)
                else:
                    self.dz_force_close_enabled = True  # Default: enabled

                # v6.6.0 FIX (L2): Load order_type and limit_chase_timeout from DB
                # Without this, LIMIT setting reverts to MARKET after every restart
                ot_val = settings.get('order_type')
                if ot_val is not None and str(ot_val).upper() in ('MARKET', 'LIMIT'):
                    self.order_type = str(ot_val).upper()
                lct_val = settings.get('limit_chase_timeout_seconds')
                if lct_val is not None:
                    self.limit_chase_timeout_seconds = max(5, min(300, int(lct_val)))

                self.logger.info(f"📊 Settings loaded: max_pos={self.max_positions}, leverage={self.max_leverage}, risk={self.risk_per_trade*100}%, recycling={self.enable_recycling}, ttl={self.order_ttl_minutes}m, auto_execute={self.enable_trading}, portfolio_target={self.portfolio_target_pct}%, auto_close={self.close_profitable_auto}, threshold={self.profitable_threshold_pct}%, profit_lock={self.use_profit_lock}, interval={self.auto_close_interval}, dz_force_close={self.dz_force_close_enabled}, order_type={self.order_type}, limit_timeout={self.limit_chase_timeout_seconds}s")
            except Exception as e:
                self.logger.warning(f"⚠️ Failed to load settings: {e}. Using defaults.")
                self.max_positions = max_positions
                self.max_leverage = max_leverage
                self.risk_per_trade = risk_per_trade
                self.enable_recycling = False
                self.order_ttl_minutes = PRODUCTION_ORDER_TTL_MINUTES
        else:
            # No settings repo - use parameters directly
            self.max_positions = max_positions
            self.max_leverage = max_leverage
            self.risk_per_trade = risk_per_trade
            # SOTA SYNC (Jan 2026): Default FALSE to match backtest (--zombie-killer OFF by default)
            self.enable_recycling = False  # ✅ FIX: Match backtest default (--zombie-killer must be explicitly enabled)
            self.order_ttl_minutes = PRODUCTION_ORDER_TTL_MINUTES
            self.dz_force_close_enabled = True  # v6.5.12: Default enabled

        self.max_drawdown_pct = max_drawdown_pct

        # SOTA (Jan 2026): MAX SL Validation config
        self.use_max_sl_validation = use_max_sl_validation
        self.max_sl_pct = max_sl_pct
        self._max_sl_rejected = 0  # Counter for rejected signals

        # ════════════════════════════════════════════════════════════════════════
        # SAFE MODE - ENV-BASED (Jan 2026 SOTA)
        # ════════════════════════════════════════════════════════════════════════
        # LIVE: Start in Safe Mode, user must click "Bắt Đầu Trade"
        # TESTNET/PAPER: Auto-start for testing efficiency
        # ════════════════════════════════════════════════════════════════════════
        # ✅ CRITICAL FIX (Jan 28, 2026): FORCE Safe Mode in LIVE regardless of DB
        # Bug: DB auto_execute=True was overriding Safe Mode after restart
        # Fix: Always set enable_trading=False in LIVE mode on startup
        # ════════════════════════════════════════════════════════════════════════
        if is_live_mode:
            self._safe_mode = True  # LIVE: Require user confirmation
            self._safe_mode_cleared = False
            self.enable_trading = False  # ✅ ALWAYS False on restart - user MUST click "Bắt Đầu Trade"
            self.logger.info("🛡️ LIVE MODE: Safe Mode ENABLED - waiting for user activation")
        else:
            self._safe_mode = False  # Testnet/Paper: Auto-start
            self._safe_mode_cleared = True
            if not hasattr(self, 'enable_trading'):
                self.enable_trading = True  # Auto-enabled
            self.logger.info(f"🚀 {mode.value.upper()} MODE: Trading auto-enabled")

        # SOTA (Jan 2026): STARTUP_GRACE_PERIOD - Block signal execution after restart
        # Prevents instant SL from stale candle data triggering signals immediately
        # SOTA FIX (Jan 2026): Reduced from 30s to 10s
        # Rationale: 30s too long, misses good signals. 10s sufficient to load candle data.
        self._startup_time = datetime.now()
        self.STARTUP_GRACE_PERIOD_SECONDS = 10
        self.BRO_HEARTBEAT_STARTUP_GRACE_SECONDS = 180
        self.BRO_HEARTBEAT_MAX_STALENESS_SECONDS = 300
        self.logger.info(f"⏳ STARTUP_GRACE_PERIOD: {self.STARTUP_GRACE_PERIOD_SECONDS}s cooldown active")

        # Track state
        self.active_positions: Dict[str, FuturesPosition] = {}
        self.pending_orders: Dict[str, 'PendingOrderInfo'] = {}  # Updated type
        self.trade_history: List[LiveTradeResult] = []
        self.peak_balance: float = 0

        # SOTA: Watermarks for trailing stop (matching Paper Trading)
        self._position_watermarks: Dict[str, Dict[str, float]] = {}

        # SOTA SYNC: Margin tracking (matches Backtest execution_simulator.py line 59-61)
        # In Isolated Margin mode, we track margin locked in positions and pending orders
        self._used_margin = 0.0       # Margin locked in OPEN positions
        self._locked_in_orders = 0.0  # Margin locked in PENDING orders

        # SOTA FIX (Jan 2026 - Bug #7): Thread lock for race condition protection
        # Prevents race condition when updating _used_margin and _locked_in_orders
        # Note: threading module imported at top of file (line 19)
        self._balance_lock = threading.Lock()

        # SOTA: User Data Stream for fill detection
        self._user_data_client = None
        self._listen_key: Optional[str] = None

        # SOTA: Bracket order tracking for OCO management
        # When TP fills → cancel SL, when SL fills → cancel TP
        self._bracket_orders: Dict[str, Dict[str, int]] = {}
        # Format: {symbol: {'sl_order_id': 123, 'tp_order_id': 456}}

        # SOTA Hybrid TP/SL: Comprehensive position state tracking
        # Stores PositionState objects with SL/TP order IDs and watermarks
        self._position_states: Dict[str, PositionState] = {}

        # SOTA (Jan 2026): Order repository for persisting live positions with TP/SL
        self.order_repo = order_repo

        # SOTA (Jan 2026): Priority Execution Queue and Worker
        # Initialized in initialize_async() for non-blocking startup
        self._execution_queue: Optional['PriorityExecutionQueue'] = None
        self._execution_worker: Optional['ExecutionWorker'] = None

        # SOTA (Jan 2026): LocalSignalTracker - Institutional-grade OMS-lite
        # Replaces exchange LIMIT orders with local tracking + MARKET execution
        # SOTA (Jan 2026): LocalSignalTracker - Institutional-grade OMS-lite
        # Replaces exchange LIMIT orders with local tracking + MARKET execution
        # NOTE: Initialized lazily via property to allow self-healing
        self._signal_tracker = None

        # SOTA (Jan 2026): PositionMonitorService - Real-time trailing/breakeven
        # Now with LOCAL SL/TP (not on exchange) to avoid stop-hunting
        # CRITICAL: Use singleton to ensure callbacks are wired correctly!
        # Callbacks will be wired in _setup_position_monitor() after initialize_async()
        from .position_monitor_service import get_position_monitor
        self.position_monitor = get_position_monitor()

        # SOTA FIX (Jan 2026): Portfolio Target Race Condition Fix - Close Mutex
        # Prevents duplicate close attempts when portfolio target hit
        # Uses asyncio.Lock for thread-safe close operations
        self._closing_symbols: set = set()  # Symbols currently being closed
        self._closing_symbols_ts: dict = {}  # v6.1.0: Timestamp when added (for timeout)
        self._close_lock = asyncio.Lock()  # Mutex for close operations

        # v5.5.0: Comprehensive CSV buffer for trade tracking
        self._closed_trades_buffer: list = []
        self._trade_counter_today: int = 0
        self._cumulative_pnl_today: float = 0.0

        # SOTA (Feb 2026): SHORT trading ENABLED - Layer 3 disabled
        self._blocked_short_signals = 0
        if mode == TradingMode.LIVE:
            self.logger.info("✅ LIVE MODE: SHORT trading ENABLED (all 3 layers disabled)")

        # SOTA (Jan 2026): Log Aggressive Trailing + BTC Filter configuration
        self.logger.info(
            f"🔍 BTC Filter: {'ENABLED' if self._use_btc_filter else 'DISABLED'}"
        )





        # SOTA LAZY INIT (Jan 2026): Don't do I/O in constructor!
        # Following Two Sigma/Citadel pattern: defer all network calls
        # Constructor only stores config; call initialize_async() after event loop starts

        self._initialized = False
        self._use_testnet = (mode == TradingMode.TESTNET)

        # Placeholders - will be populated in initialize_async()
        self.client = None
        self.async_client = None
        self.intelligence_service = intelligence_service  # Can be pre-injected
        self.initial_balance = 0.0
        self.peak_balance = 0.0
        self._cached_balance = 0.0
        self._cached_available = 0.0

        # SOTA: Cache settings
        self._portfolio_cache: Optional[Dict] = None
        self._portfolio_cache_time: float = 0.0
        self.PORTFOLIO_CACHE_TTL = 5.0
        self._portfolio_fetch_lock: Optional[asyncio.Lock] = None

        # Local cache
        self._cached_open_orders: Dict[int, Dict] = {}
        self._cached_positions_list: List[Any] = []
        self._local_cache_initialized = False
        self._cached_prices: Dict[str, float] = {}  # SOTA FIX: Cache for current prices (PROXIMITY SENTRY)

        if mode == TradingMode.PAPER:
            self.logger.info("📝 Paper trading mode - no real orders")
        else:
            # Just log intent, actual init happens in initialize_async()
            mode_str = "🧪 TESTNET" if self._use_testnet else "🔴 LIVE"
            self.logger.info(f"{mode_str} trading mode configured (lazy init)")

        # DEBUG: avoid touching the lazy property here; constructor should stay side-effect free
        self.logger.info(
            f"🔧 __init__ complete: id={id(self)}, "
            f"signal_tracker_ready={self._signal_tracker is not None}, "
            f"enable_trading={self.enable_trading}"
        )

        # SOTA (Jan 2026): Register AUTO-CLOSE callback with PositionMonitor
        if self.close_profitable_auto and self.position_monitor:
            self.position_monitor.register_close_callback(self._check_auto_close_local)
            # NOTE: Portfolio PnL callback REMOVED (Feb 9, 2026)
            # Local tracker PnL was unreliable (ghost entries, wrong entry prices)
            # Portfolio target now uses MonitoredPosition data directly (exchange-accurate)
            # SOTA (Feb 2026): Sync AUTO_CLOSE interval to PositionMonitor
            self.position_monitor.set_auto_close_interval(self.auto_close_interval)
            self.logger.info(f"✅ Registered LOCAL auto-close callback (interval={self.auto_close_interval})")

    # SOTA: Lazy Property for Signal Tracker (Self-Healing Pattern)
    @property
    def signal_tracker(self):
        if self._signal_tracker is None:
            self.logger.warning("⚠️ signal_tracker accessed but not ready - Self-Healing activated!")
            self._signal_tracker = LocalSignalTracker(
                execute_callback=self._execute_triggered_signal,
                max_pending=self.max_positions,
                default_ttl_minutes=self.order_ttl_minutes,
                enable_recycling=self.enable_recycling,
                # SOTA FIX (Jan 2026): Position check callback for defense in depth
                # Matches backtest: if s.symbol not in self.positions
                has_position_callback=self._has_open_position,
                # SOTA FIX (Jan 2026): Total slots callback - CRITICAL for max_positions enforcement
                # This fixes the bug where 8 slots were used when max=5
                get_total_slots_callback=self._get_total_slots
            )
            self.logger.info("✅ signal_tracker self-healed and initialized.")
        return self._signal_tracker

    def _get_total_slots(self) -> tuple:
        """
        SOTA FIX (Jan 2026): Get total slots used (positions + pending).

        CRITICAL: This callback ensures LocalSignalTracker enforces max_positions
        correctly by counting BOTH positions AND pending signals.

        Returns:
            Tuple of (positions_count, pending_count)
        """
        positions_count = len(self.active_positions)
        pending_count = len(self._signal_tracker.pending_signals) if self._signal_tracker else 0
        return (positions_count, pending_count)

    def _has_open_position(self, symbol: str) -> bool:
        """
        SOTA FIX (Jan 2026): Check if symbol has open position.
        Used by LocalSignalTracker for defense in depth filtering.
        """
        return symbol.upper() in self.active_positions

    # ════════════════════════════════════════════════════════════════════════
    # SOTA (Jan 2026): BTC Filter - Market Regime Detection
    # Pattern: Two Sigma, Renaissance - Filter signals based on market trend
    # ════════════════════════════════════════════════════════════════════════

    def _calculate_ema(self, prices: List[float], period: int) -> float:
        """
        Calculate Exponential Moving Average.

        SOTA (Jan 2026): Matches backtest EMA calculation for parity.

        Args:
            prices: List of prices (oldest first)
            period: EMA period (e.g., 50, 200)

        Returns:
            EMA value (float), or 0.0 if insufficient data
        """
        if len(prices) < period:
            return 0.0

        try:
            # Use pandas for accurate EMA calculation
            import pandas as pd
            series = pd.Series(prices)
            ema = series.ewm(span=period, adjust=False).mean().iloc[-1]
            return float(ema)
        except Exception as e:
            self.logger.error(f"❌ EMA calculation error: {e}")
            return 0.0

    async def _get_btc_trend(self) -> str:
        """
        Get BTC trend from EMA 50/200 crossover.

        SOTA (Jan 2026): Matches backtest BTC filter logic for parity.

        Returns:
            'BULLISH' if EMA50 > EMA200 (Golden Cross)
            'BEARISH' if EMA50 < EMA200 (Death Cross)
            'NEUTRAL' if error or insufficient data (fail-safe)
        """
        try:
            # Fetch BTC 1h candles (last 200 for EMA200 calculation)
            klines = await self.async_client.get_klines(
                symbol='BTCUSDT',
                interval='1h',
                limit=200
            )

            if not klines or len(klines) < 200:
                self.logger.warning("⚠️ BTC Filter: Insufficient candle data")
                return 'NEUTRAL'

            # Extract close prices (index 4 in kline array)
            close_prices = [float(k[4]) for k in klines]

            # Calculate EMAs
            ema_50 = self._calculate_ema(close_prices, 50)
            ema_200 = self._calculate_ema(close_prices, 200)

            if ema_50 == 0 or ema_200 == 0:
                self.logger.warning("⚠️ BTC Filter: EMA calculation failed")
                return 'NEUTRAL'

            # Determine trend
            if ema_50 > ema_200:
                trend = 'BULLISH'
                self.logger.debug(
                    f"🔍 BTC Filter: BULLISH (Golden Cross) | "
                    f"EMA50: {ema_50:.2f} > EMA200: {ema_200:.2f}"
                )
            else:
                trend = 'BEARISH'
                self.logger.debug(
                    f"🔍 BTC Filter: BEARISH (Death Cross) | "
                    f"EMA50: {ema_50:.2f} < EMA200: {ema_200:.2f}"
                )

            return trend

        except Exception as e:
            self.logger.error(f"❌ BTC Filter error: {e}")
            return 'NEUTRAL'  # Fail-safe: allow signals on error

    # ════════════════════════════════════════════════════════════════════════
    # SOTA SAFE MODE API (Jan 2026)
    # Pattern: Two Sigma, Citadel - explicit user confirmation before trading
    # ════════════════════════════════════════════════════════════════════════

    def activate_trading(self, clear_old_data: bool = True) -> dict:
        """
        Activate trading from SAFE MODE.

        Called when user clicks "Bắt Đầu Trade" button in frontend.
        Clears old pending signals and watermarks to prevent ghost orders.

        Args:
            clear_old_data: If True, clear old pending signals and watermarks

        Returns:
            Dict with activation status
        """
        if clear_old_data:
            # Clear old pending signals from LocalSignalTracker
            if hasattr(self, '_signal_tracker') and self._signal_tracker:
                old_count = len(self._signal_tracker.pending_signals)
                self._signal_tracker.pending_signals.clear()
                self.logger.info(f"🧹 Cleared {old_count} old pending signals")

            # Clear old watermarks
            old_watermarks = len(self._position_watermarks)
            self._position_watermarks.clear()
            self.logger.info(f"🧹 Cleared {old_watermarks} old watermarks")

            # Clear pending orders from memory
            old_pending = len(self.pending_orders)
            self.pending_orders.clear()
            self.logger.info(f"🧹 Cleared {old_pending} old pending orders")

            # SOTA FIX (Jan 2026): Reload ACTIVE position watermarks from DB
            # We only want to clear PENDING signals/orders, NOT lose SL/TP for OPEN positions!
            try:
                open_orders = self.client.get_open_orders() if self.client else []
                self._sync_position_states_from_exchange(open_orders)
                self.logger.info(f"🔄 Reloaded {len(self._position_watermarks)} position watermarks from DB")
            except Exception as e:
                self.logger.warning(f"⚠️ Failed to reload watermarks from DB: {e}")

            self._safe_mode_cleared = True

        # Activate trading
        self._safe_mode = False
        self.enable_trading = True

        self.logger.info(f"🚀 TRADING ACTIVATED: enable_trading=True, safe_mode=False, cleared={clear_old_data}")

        # SOTA (Jan 2026): Restore position monitoring for existing positions
        # This ensures trailing/SL/TP works after restart
        self._restore_position_monitoring()

        return {
            "status": "active",
            "safe_mode": False,
            "enable_trading": True,
            "cleared_data": clear_old_data
        }

    def deactivate_trading(self) -> dict:
        """
        Deactivate trading (enter SAFE MODE).

        Called when user wants to pause trading.
        """
        self._safe_mode = True
        self.enable_trading = False
        self.logger.info("⏸️ TRADING DEACTIVATED: (Safe Mode ENABLED)")

        # Stop monitoring but keep state
        if hasattr(self, 'monitor') and self.monitor:
            for symbol in list(self.monitor.get_all_positions().keys()):
                self.monitor.stop_monitoring(symbol)

        return {
            "status": "inactive",
            "safe_mode": True,
            "enable_trading": False
        }

    def _sync_position_states_from_exchange(self, open_orders: List[dict]):
        """
        SOTA (Feb 2026): Restore local state (Watermarks, Phases) from DB.

        Called during activate_trading() to recover state after restart.
        Crucial for Trailing Stop and Breakeven to resume correctly.
        """
        if not self.order_repo:
            self.logger.warning("⚠️ Cannot sync position states: No order_repo")
            return

        try:
            # 1. Fetch saved live positions from DB
            saved_positions = self.order_repo.get_open_live_positions()
            restored_count = 0

            for saved_pos in saved_positions:
                symbol = saved_pos['symbol']

                # 2. Restore Watermarks (Critical for Trailing Stop)
                # Ensure we have all necessary fields, default to safe values if missing
                self._position_watermarks[symbol] = {
                    'current_sl': saved_pos.get('stop_loss', 0),
                    'tp_target': saved_pos.get('take_profit', 0),
                    'is_breakeven': bool(saved_pos.get('is_breakeven', 0)),
                    'tp_hit_count': saved_pos.get('tp_hit_count', 0),
                    'phase': saved_pos.get('phase', 'ENTRY'),
                    'highest': saved_pos.get('highest_price', 0),
                    'lowest': saved_pos.get('lowest_price', float('inf')),
                    'entry_price': saved_pos.get('entry_price', 0),
                    'atr': saved_pos.get('atr', 0),
                    'side': saved_pos.get('side', '')
                }

                # 3. Restore LocalPosition tracker (for accurate PnL)
                # This ensures _calculate_portfolio_pnl_local works immediately
                # SOTA FIX (Feb 2026): Use correct LocalPosition API
                with self._local_positions_lock:
                    from ...domain.entities.local_position_tracker import LocalPosition, FillRecord

                    # Create LocalPosition with correct params
                    leverage = saved_pos.get('leverage', 1)
                    local_pos = LocalPosition(
                        symbol=symbol,
                        side=saved_pos.get('side', ''),
                        intended_leverage=leverage
                    )

                    # Restore internal state directly (for restart recovery)
                    # This bypasses normal fill tracking but preserves PnL calculation accuracy
                    entry_price = saved_pos.get('entry_price', 0)
                    quantity = saved_pos.get('quantity', 0)

                    if entry_price > 0 and quantity > 0:
                        # Set internal values directly for PnL calculation
                        local_pos._avg_entry_price = entry_price
                        local_pos._total_entry_qty = quantity
                        local_pos._total_entry_cost = entry_price * quantity
                        local_pos._net_quantity = quantity  # No partial exits on restore
                        local_pos._total_entry_fees = entry_price * quantity * 0.0005  # Estimate 0.05% taker fee

                        # Set actual leverage (same as intended on restore)
                        local_pos.actual_leverage = leverage
                        local_pos._actual_margin_used = (entry_price * quantity) / leverage

                    self._local_positions[symbol] = local_pos

                restored_count += 1
                self.logger.debug(f"♻️ Restored state for {symbol}: Phase={saved_pos.get('phase')}, SL={saved_pos.get('stop_loss')}")

            self.logger.info(f"✅ Synced {restored_count} position states from DB")

        except Exception as e:
            self.logger.error(f"❌ Failed to sync position states: {e}", exc_info=True)

    def get_trading_status(self) -> dict:
        """
        Get current trading status for frontend.

        Returns:
            Dict with safe_mode, enable_trading, mode string
        """
        status = {
            "safe_mode": self._safe_mode,
            "enable_trading": self.enable_trading,
            "mode": "TRADING" if self.enable_trading else "SAFE_MODE",
            "pending_signals": len(self._signal_tracker.pending_signals) if hasattr(self, '_signal_tracker') and self._signal_tracker else 0,
            "active_positions": len(self.active_positions),
            "cleared_on_activate": self._safe_mode_cleared
        }

        # SOTA (Jan 2026): Add execution queue metrics
        if self._execution_queue:
            queue_metrics = self._execution_queue.get_metrics()
            status["execution_queue"] = {
                "size": queue_metrics.get('current_size', 0),
                "total_processed": queue_metrics.get('total_processed', 0),
                "duplicates_rejected": queue_metrics.get('duplicates_rejected', 0),
                "pending_symbols": queue_metrics.get('pending_symbols', [])
            }

        if self._execution_worker:
            latency_stats = self._execution_worker.get_latency_stats()
            status["execution_latency"] = {
                "avg_ms": round(latency_stats.get('avg_latency_ms', 0), 1),
                "max_ms": round(latency_stats.get('max_latency_ms', 0), 1),
                "warnings": latency_stats.get('warnings_count', 0),
                "critical": latency_stats.get('critical_count', 0)
            }

        return status

    def _setup_position_monitor(self):
        """
        ═══════════════════════════════════════════════════════════════════════
        SOTA Local-First Pattern (Jan 2026): Setup PositionMonitorService callbacks.

        Wires the monitor to:
        - Close positions via MARKET order (when local SL/TP hit)
        - Cancel backup SL on exchange (cleanup after exit)
        - Partial close for TP1 (60% close)
        - TradeLogger for detailed debugging

        CRITICAL FIX (Jan 2026): Always wire callbacks, not just when None.
        This ensures callbacks are updated if LiveTradingService is recreated.
        ═══════════════════════════════════════════════════════════════════════
        """
        from .position_monitor_service import get_position_monitor, PositionMonitorService
        from .trade_logger import get_trade_logger

        monitor = get_position_monitor()
        trade_logger = get_trade_logger()

        # SOTA (Jan 2026): Apply Full TP (100% at TP1) as requested
        monitor.full_tp_at_tp1 = True

        # SOTA FIX (Jan 2026): ALWAYS wire callbacks to ensure they point to current instance
        # Previous bug: if monitor._close_position was already set (from previous instance),
        # callbacks would point to stale/dead LiveTradingService instance!
        monitor._close_position = self._local_exit_position
        # SOTA FIX (Jan 2026): Use unified cleanup function instead of _cancel_backup_sl
        # This ensures ALL orders (regular + algo) are cancelled, not just backup SL
        monitor._cleanup_orders = self._cleanup_all_orders_for_symbol
        monitor._partial_close = self.partial_close_position
        monitor._update_sl = None  # LOCAL_ONLY_MODE: No exchange SL updates for trailing
        monitor._persist_sl = self._persist_sl_to_db  # SOTA: DB persistence for SL
        monitor._persist_tp_hit = self._persist_tp_hit_to_db  # SOTA FIX: DB persistence for tp_hit_count
        monitor._persist_phase = self._persist_phase_to_db  # SOTA FIX (Jan 2026): DB persistence for phase
        monitor._persist_watermarks = self._persist_watermarks_to_db  # SOTA FIX (Jan 2026): DB persistence for watermarks
        monitor._trade_logger = trade_logger  # SOTA FIX: TradeLogger for debugging
        monitor._telegram_service = self.telegram_service  # SOTA (Feb 2026): Wire Telegram for breakeven notifications

        # SOTA (Jan 2026): Wire ASYNC callbacks for minimal latency TP/SL execution
        # These are used by _on_tp1_hit_async and _on_sl_hit_async for direct await
        # instead of fire-and-forget asyncio.create_task
        monitor._partial_close_async = self.partial_close_position_async
        monitor._close_position_async = self.close_position_async

        # SOTA FIX (Jan 2026): Wire Circuit Breaker for trade recording
        if hasattr(self, 'circuit_breaker') and self.circuit_breaker:
            monitor._circuit_breaker = self.circuit_breaker
            self.logger.info("🛡️ Circuit Breaker wired to PositionMonitor")

        # SOTA (Jan 2026): Portfolio Target - Pass to PositionMonitor
        # Calculate portfolio_target_usd from percentage and initial balance
        if self.portfolio_target_pct > 0 and self.initial_balance > 0:
            portfolio_target_usd = self.initial_balance * (self.portfolio_target_pct / 100.0)
            monitor.set_portfolio_target(portfolio_target_usd)
            self.logger.info(
                f"🎯 Portfolio Target: {self.portfolio_target_pct}% "
                f"(${portfolio_target_usd:.2f})"
            )
        else:
            monitor.set_portfolio_target(0.0)
            self.logger.info("🎯 Portfolio Target: DISABLED")

        # SOTA FIX (Feb 2026): Auto-Close Profitable - Callback DEPRECATED
        # Replaced by exchange-side TP_CLOSE orders or internal monitor logic
        # monitor._check_auto_close_callback = self._check_auto_close_profitable

        # SOTA FIX (Feb 2026): Wire auto_close flag from LiveTradingService → PositionMonitorService
        # BUG FIX #1: Flag was loaded from settings but NEVER wired to monitor!
        monitor.use_auto_close = self.close_profitable_auto
        monitor.auto_close_threshold_pct = self.profitable_threshold_pct

        if self.close_profitable_auto:
            self.logger.info(
                f"💰 Auto-Close Profitable: ENABLED "
                f"(ROE > {self.profitable_threshold_pct}%)"
            )
        else:
            self.logger.info("💰 Auto-Close Profitable: DISABLED")

        # SOTA (Feb 2026): Wire Profit Lock from LiveTradingService → PositionMonitorService
        monitor.use_profit_lock = self.use_profit_lock
        if self.use_profit_lock:
            monitor.PROFIT_LOCK_THRESHOLD_ROE = self.profit_lock_threshold_pct / 100.0
            monitor.PROFIT_LOCK_ROE = self.profit_lock_pct / 100.0
            self.logger.info(
                f"🔒 Profit Lock: ENABLED "
                f"(threshold={self.profit_lock_threshold_pct}%, lock={self.profit_lock_pct}%)"
            )
        else:
            self.logger.info("🔒 Profit Lock: DISABLED")

        # SOTA FIX (Jan 2026): Enhanced verification logging for debugging
        # Log all callback states to help diagnose TP1 execution issues
        # SOTA FIX (Feb 2026): Separate REQUIRED vs OPTIONAL callbacks
        # Circuit Breaker is OPTIONAL (disabled by default) - should not trigger CRITICAL
        required_callbacks = {
            'partial_close': monitor._partial_close is not None,
            'partial_close_async': monitor._partial_close_async is not None,
            'close_position': monitor._close_position is not None,
            'close_position_async': monitor._close_position_async is not None,
            'cleanup_orders': monitor._cleanup_orders is not None,
            'persist_sl': monitor._persist_sl is not None,
            'persist_tp_hit': monitor._persist_tp_hit is not None,
            'persist_phase': monitor._persist_phase is not None,
            'persist_watermarks': monitor._persist_watermarks is not None,
            'trade_logger': monitor._trade_logger is not None,
        }

        optional_callbacks = {
            'circuit_breaker': hasattr(monitor, '_circuit_breaker') and monitor._circuit_breaker is not None
        }

        all_required_wired = all(required_callbacks.values())

        if all_required_wired:
            optional_status = ", ".join([f"{k}={'ON' if v else 'OFF'}" for k, v in optional_callbacks.items()])
            self.logger.info(
                f"✅ PositionMonitor callbacks FULLY wired: "
                f"LOCAL_ONLY_MODE={PositionMonitorService.LOCAL_ONLY_MODE}, "
                f"10 required callbacks OK | Optional: {optional_status}"
            )
        else:
            missing = [k for k, v in required_callbacks.items() if not v]
            self.logger.critical(
                f"🚨 CRITICAL: PositionMonitor REQUIRED callbacks INCOMPLETE! "
                f"Missing: {missing}. TP1 execution may fail!"
            )

    def _persist_tp_hit_to_db(self, symbol: str, tp_hit_count: int) -> bool:
        """
        SOTA FIX (Jan 2026): Persist tp_hit_count to DB for restart recovery.

        Called by PositionMonitorService when TP1 is hit.
        Also clears tp_target in watermarks so UI shows "--" for TP after hit.

        CRITICAL FIX (Jan 2026): Creates watermark if missing to prevent silent failures.

        Args:
            symbol: Trading pair
            tp_hit_count: Number of TP levels hit

        Returns:
            Success status
        """
        try:
            symbol_upper = symbol.upper()

            # CRITICAL FIX (Jan 2026): Create watermark if not exists
            if symbol_upper not in self._position_watermarks:
                self.logger.warning(
                    f"⚠️ Watermark missing for {symbol_upper}! Creating minimal entry for TP hit update. "
                    f"(keys={len(self._position_watermarks)})"
                )
                self._position_watermarks[symbol_upper] = {
                    'current_sl': 0,
                    'tp_target': 0,
                    'is_breakeven': False,
                    'tp_hit_count': 0,
                    'phase': 'ENTRY',
                    'highest': 0,
                    'lowest': float('inf'),
                    'entry_price': 0,
                    'atr': 0,
                    'side': ''
                }
                self.logger.info(f"✅ Created watermark for {symbol_upper} for TP hit update")

            # SOTA FIX (Jan 2026): Update watermarks for UI display
            # Clear tp_target after TP1 hit so UI shows "--" for TP
            self._position_watermarks[symbol_upper]['tp_hit_count'] = tp_hit_count
            if tp_hit_count >= 1:
                # TP1 hit - clear tp_target so UI shows "--"
                self._position_watermarks[symbol_upper]['tp_target'] = 0
                self.logger.info(f"🔄 Watermark tp_target cleared for {symbol_upper} (TP1 hit, tp_hit_count={tp_hit_count})")

            if self.order_repo:
                self.order_repo.update_live_position_tp_hit_count(symbol_upper, tp_hit_count)
                self.logger.debug(f"💾 tp_hit_count persisted to DB: {symbol_upper} = {tp_hit_count}")
                return True
            else:
                self.logger.debug(f"⚠️ No order_repo to persist tp_hit_count for {symbol_upper}")
                return False

        except Exception as e:
            self.logger.warning(f"⚠️ Failed to persist tp_hit_count to DB: {e}")
            return False

    def _persist_phase_to_db(self, symbol: str, phase: str, is_breakeven: bool) -> bool:
        """
        SOTA FIX (Jan 2026): Persist phase and is_breakeven to DB for restart recovery.

        Called by PositionMonitorService when phase transitions:
        - ENTRY → BREAKEVEN (breakeven triggered)
        - ENTRY/BREAKEVEN → TRAILING (TP1 hit)

        CRITICAL FIX (Jan 2026): Creates watermark if missing to prevent silent failures.

        Args:
            symbol: Trading pair
            phase: New phase ('ENTRY', 'BREAKEVEN', 'TRAILING')
            is_breakeven: True if breakeven has been triggered

        Returns:
            Success status
        """
        try:
            symbol_upper = symbol.upper()

            # CRITICAL FIX (Jan 2026): Create watermark if not exists
            if symbol_upper not in self._position_watermarks:
                self.logger.warning(
                    f"⚠️ Watermark missing for {symbol_upper}! Creating minimal entry for phase update. "
                    f"(keys={len(self._position_watermarks)})"
                )
                self._position_watermarks[symbol_upper] = {
                    'current_sl': 0,
                    'tp_target': 0,
                    'is_breakeven': False,
                    'tp_hit_count': 0,
                    'phase': 'ENTRY',
                    'highest': 0,
                    'lowest': float('inf'),
                    'entry_price': 0,
                    'atr': 0,
                    'side': ''
                }
                self.logger.info(f"✅ Created watermark for {symbol_upper} for phase update")

            # Update watermark with new phase
            old_phase = self._position_watermarks[symbol_upper].get('phase', 'ENTRY')
            self._position_watermarks[symbol_upper]['phase'] = phase
            self._position_watermarks[symbol_upper]['is_breakeven'] = is_breakeven
            self.logger.info(f"🔄 Watermark phase updated: {symbol_upper} {old_phase} → {phase}, is_breakeven={is_breakeven}")

            if self.order_repo:
                self.order_repo.update_live_position_phase(symbol_upper, phase, is_breakeven)
                self.logger.info(f"💾 Phase persisted to DB: {symbol_upper} = {phase}, is_breakeven={is_breakeven}")
                return True
            else:
                self.logger.debug(f"⚠️ No order_repo to persist phase for {symbol_upper}")
                return False

        except Exception as e:
            self.logger.warning(f"⚠️ Failed to persist phase to DB: {e}")
            return False

    def _persist_watermarks_to_db(self, symbol: str, highest: float, lowest: float) -> bool:
        """
        SOTA FIX (Jan 2026): Persist watermarks to DB for restart recovery.

        Called by PositionMonitorService when SL changes in _update_trailing().
        Persists max_price/min_price for correct trailing stop calculation after restart.

        Args:
            symbol: Trading pair
            highest: Highest price seen (for LONG trailing)
            lowest: Lowest price seen (for SHORT trailing)

        Returns:
            Success status
        """
        try:
            symbol_upper = symbol.upper()

            if self.order_repo:
                self.order_repo.update_live_position_watermarks(symbol_upper, highest, lowest)
                self.logger.debug(f"💾 Watermarks persisted to DB: {symbol_upper} highest={highest:.4f}, lowest={lowest:.4f}")
                return True
            else:
                self.logger.debug(f"⚠️ No order_repo to persist watermarks for {symbol_upper}")
                return False

        except Exception as e:
            self.logger.warning(f"⚠️ Failed to persist watermarks to DB: {e}")
            return False

    def _broadcast_sl_update(
        self,
        symbol: str,
        new_sl: float,
        old_sl: float,
        reason: str = 'BREAKEVEN'
    ):
        """
        SOTA FIX v2 (Jan 2026): Broadcast SL update event via WebSocket.

        Enables real-time UI update without polling. Frontend receives event
        and updates Portfolio display immediately.

        Event structure:
        {
            "type": "SL_UPDATE",
            "symbol": "FOGOUSDT",
            "new_sl": 0.0523,
            "old_sl": 0.0512,
            "reason": "BREAKEVEN",  # or "TRAILING"
            "timestamp": "2026-01-14T10:30:00Z"
        }

        Args:
            symbol: Trading pair
            new_sl: New stop loss price
            old_sl: Previous stop loss price
            reason: Update reason ('BREAKEVEN', 'TRAILING')
        """
        # SOTA FIX (Jan 2026 - Bug #24): Validate inputs before broadcast
        import math

        # Validate symbol
        if not symbol or not isinstance(symbol, str):
            self.logger.warning(f"⚠️ Invalid symbol for SL broadcast: {symbol}")
            return

        # Validate new_sl
        if not isinstance(new_sl, (int, float)) or new_sl <= 0 or math.isnan(new_sl) or math.isinf(new_sl):
            self.logger.warning(f"⚠️ Invalid new_sl for broadcast: {new_sl}")
            return

        # Validate old_sl (can be 0 for initial SL)
        if not isinstance(old_sl, (int, float)) or old_sl < 0 or math.isnan(old_sl) or math.isinf(old_sl):
            self.logger.warning(f"⚠️ Invalid old_sl for broadcast: {old_sl}")
            return

        # Validate reason
        if reason not in ['BREAKEVEN', 'TRAILING', 'MANUAL']:
            self.logger.warning(f"⚠️ Invalid reason for broadcast: {reason}, using UNKNOWN")
            reason = 'UNKNOWN'

        try:
            from ...api.event_bus import get_event_bus

            event_bus = get_event_bus()
            event_data = {
                'type': 'SL_UPDATE',
                'symbol': symbol.upper(),
                'new_sl': round(new_sl, 8),  # Round to 8 decimals for precision
                'old_sl': round(old_sl, 8),
                'reason': reason,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

            # SOTA FIX (Jan 2026): Use convenience method with BroadcastEvent wrapper
            # Old API (deprecated): event_bus.publish('sl_update', event_data)
            # New API: event_bus.publish_sl_update(event_data, symbol)
            event_bus.publish_sl_update(event_data, symbol)
            self.logger.info(
                f"📡 SL_UPDATE broadcast: {symbol} ${old_sl:.4f} → ${new_sl:.4f} ({reason})"
            )
        except Exception as e:
            # Don't block SL update if broadcast fails
            self.logger.warning(f"⚠️ Failed to broadcast SL update: {e}")

    def _restore_position_monitoring(self):
        """
        SOTA (Jan 2026): Restore position monitoring for existing positions on restart.

        Called after positions are loaded from DB to ensure trailing/SL/TP works.

        50 symbols with 5 positions:
        - Only 5 symbols get MonitoredPosition created
        - Other 45 symbols: PositionMonitor._on_price_update returns early
        - No performance overhead for non-position symbols
        """
        from .position_monitor_service import MonitoredPosition

        restored_count = 0
        skipped_count = 0

        for symbol, pos in self.active_positions.items():
            # Skip empty positions
            if pos.position_amt == 0:
                continue

            # v6.1.0 FIX: Skip symbols currently being closed (same as _ensure_positions_monitored)
            if symbol.upper() in self._closing_symbols:
                continue

            # Skip if already monitored
            if self.position_monitor.get_position(symbol):
                skipped_count += 1
                continue

            # Get watermark data (loaded from DB via _sync_position_states_from_exchange)
            watermark = self._position_watermarks.get(symbol, {})

            # SOTA DEBUG (Jan 2026): Log watermark state for debugging
            wm_sl = watermark.get('current_sl', 0) if watermark else 0
            wm_tp = watermark.get('tp_target', 0) if watermark else 0
            self.logger.info(f"📊 [RESTORE] {symbol}: watermark={bool(watermark)}, SL={wm_sl:.4f}, TP={wm_tp:.4f}")

            side = 'LONG' if pos.position_amt > 0 else 'SHORT'

            # SOTA FIX (Jan 2026): Create minimal watermark if not exists
            # This ensures local_tpsl is populated for orphan positions
            if not watermark or (watermark.get('current_sl', 0) == 0 and watermark.get('tp_target', 0) == 0):
                # Orphan position - get SL/TP from DB or calculate defaults
                sl_from_db = 0.0
                tp_from_db = 0.0

                # Try to get from DB first
                if self.order_repo:
                    try:
                        db_pos = self.order_repo.get_live_position(symbol)
                        if db_pos:
                            sl_from_db = db_pos.get('stop_loss', 0.0)
                            tp_from_db = db_pos.get('take_profit', 0.0)
                            self.logger.info(f"📊 [RESTORE] {symbol}: Got SL/TP from DB (SL={sl_from_db:.4f}, TP={tp_from_db:.4f})")
                    except Exception as e:
                        self.logger.warning(f"⚠️ [RESTORE] {symbol}: Failed to get from DB: {e}")

                # Fallback: Calculate 2% default SL if DB empty
                if sl_from_db == 0.0:
                    if side == 'LONG':
                        sl_from_db = pos.entry_price * 0.98  # 2% below entry
                    else:
                        sl_from_db = pos.entry_price * 1.02  # 2% above entry
                    self.logger.info(f"📊 [RESTORE] {symbol}: Calculated default 2% SL={sl_from_db:.4f}")

                self.logger.info(f"📊 [RESTORE] {symbol}: ORPHAN detected, creating watermark with SL={sl_from_db:.4f}, TP={tp_from_db:.4f}")

                self._position_watermarks[symbol] = {
                    'highest': pos.entry_price if side == 'LONG' else 0,
                    'lowest': pos.entry_price if side == 'SHORT' else float('inf'),
                    'current_sl': sl_from_db,
                    'tp_target': tp_from_db,
                    'entry_price': pos.entry_price,
                    'is_breakeven': False,
                    'tp_hit_count': 0,
                    'atr': 0,
                    'side': side,
                    'local_first_mode': True,  # SOTA: Flag for Local-First positions
                    'is_orphan': True  # SOTA: Flag that this was an orphan position
                }
                watermark = self._position_watermarks[symbol]
                self.logger.info(f"📊 Created watermark for orphan position: {symbol}")

            monitored_pos = MonitoredPosition(
                symbol=symbol,
                side=side,
                entry_price=pos.entry_price,
                quantity=abs(pos.position_amt),
                leverage=pos.leverage or self.max_leverage,
                initial_sl=watermark.get('current_sl', 0),
                initial_tp=watermark.get('tp_target', 0),
                atr=watermark.get('atr', 0),
                # SOTA FIX (Jan 2026): Restore full state from watermark
                tp_hit_count=watermark.get('tp_hit_count', 0),
                max_price=watermark.get('highest', pos.entry_price),
                min_price=watermark.get('lowest', pos.entry_price)
            )

            # SOTA FIX (Jan 2026): Derive phase from DB or tp_hit_count
            # This ensures trailing stop works correctly after restart
            db_phase = watermark.get('phase', 'ENTRY')
            tp_hit_count = watermark.get('tp_hit_count', 0)
            is_breakeven = watermark.get('is_breakeven', False)

            # Import PositionPhase for phase conversion
            from .position_monitor_service import PositionPhase

            # Backward compatibility: derive phase if not stored correctly
            if db_phase == 'ENTRY' and tp_hit_count >= 1:
                db_phase = 'TRAILING'
            elif db_phase == 'ENTRY' and is_breakeven:
                db_phase = 'BREAKEVEN'

            # Convert string to enum
            try:
                monitored_pos.phase = PositionPhase(db_phase.lower())
            except ValueError:
                monitored_pos.phase = PositionPhase.ENTRY

            # SOTA FIX (Jan 2026): Set is_breakeven based on phase or DB value
            if monitored_pos.phase in [PositionPhase.BREAKEVEN, PositionPhase.TRAILING]:
                monitored_pos.is_breakeven = True
            else:
                monitored_pos.is_breakeven = is_breakeven

            self.position_monitor.start_monitoring(monitored_pos)
            restored_count += 1

            # SOTA FIX (Jan 2026): Enhanced logging for state restoration
            self.logger.info(
                f"📊 Restored {symbol} {side}: phase={db_phase}, tp_hit={tp_hit_count}, "
                f"atr={watermark.get('atr', 0):.4f}, is_breakeven={monitored_pos.is_breakeven}, "
                f"SL={watermark.get('current_sl', 0):.2f}, TP={watermark.get('tp_target', 0):.2f}"
            )

        if restored_count > 0:
            self.logger.info(
                f"📊 Restored monitoring for {restored_count} existing positions "
                f"(skipped {skipped_count} already monitored)"
            )

    def _ensure_positions_monitored(self):
        """
        SOTA (Jan 2026): Lightweight check to ensure all active positions are monitored.

        Called frequently from _sync_local_cache_async (every 5s).
        Uses quick check to avoid overhead when no changes needed.

        This fixes the bug where AUTO_CLOSE didn't work because positions
        weren't registered for monitoring after restart.
        """
        if not hasattr(self, 'position_monitor') or not self.position_monitor:
            return

        # Quick check: Count unmonitored positions
        unmonitored_count = 0
        for symbol, pos in self.active_positions.items():
            if pos.position_amt == 0:
                continue
            # v6.1.0 FIX: Skip symbols currently being closed.
            # OLD BUG: _ensure_positions_monitored ran every 5s and re-adopted
            # positions in DEFERRED close path (stop_monitoring already called).
            # This created zombie positions that triggered TP/AC on already-closing
            # positions, causing Phantom WIN (logged as WIN, actual execution = LOSS).
            if symbol.upper() in self._closing_symbols:
                continue
            if not self.position_monitor.get_position(symbol):
                unmonitored_count += 1

        # Only call full restore if there are unmonitored positions
        if unmonitored_count > 0:
            self.logger.info(
                f"🔄 Found {unmonitored_count} unmonitored positions, registering for monitoring..."
            )
            self._restore_position_monitoring()

    def _is_bro_heartbeat_healthy(self) -> tuple[bool, str]:
        """Return whether BroSubSoul heartbeat is healthy enough to allow new entries."""
        settings_repo = getattr(self, "settings_repo", None)
        if not settings_repo:
            return True, "heartbeat guard skipped (no settings repo)"

        startup_time = getattr(self, "_startup_time", None)
        startup_grace = float(getattr(self, "BRO_HEARTBEAT_STARTUP_GRACE_SECONDS", 180))
        if isinstance(startup_time, datetime):
            startup_age = (datetime.now() - startup_time).total_seconds()
            if startup_age < startup_grace:
                return True, f"startup grace active ({startup_age:.0f}s < {startup_grace:.0f}s)"

        try:
            all_settings = (
                settings_repo.get_all_settings()
                if hasattr(settings_repo, "get_all_settings")
                else {}
            )
        except Exception as exc:
            return False, f"heartbeat settings read error: {exc}"

        raw_heartbeat = all_settings.get("bro_subsoul_last_heartbeat")
        if raw_heartbeat in (None, "", 0, "0"):
            return False, "heartbeat missing"

        try:
            heartbeat_ts = int(float(raw_heartbeat))
        except (TypeError, ValueError):
            return False, f"heartbeat invalid: {raw_heartbeat!r}"

        now_ts = int(time.time())
        if heartbeat_ts > now_ts + 60:
            return False, f"heartbeat is in the future: {heartbeat_ts}"

        staleness = now_ts - heartbeat_ts
        max_staleness = int(getattr(self, "BRO_HEARTBEAT_MAX_STALENESS_SECONDS", 300))
        if staleness > max_staleness:
            return False, f"heartbeat stale: {staleness}s > {max_staleness}s"

        return True, f"heartbeat healthy ({staleness}s old)"


    def _local_exit_position(self, symbol: str, reason: str = "MANUAL") -> bool:
        """
        SOTA Local-First: Close position via MARKET order when local SL/TP hit.

        Called by PositionMonitorService when local SL condition is met.
        """
        # SOTA (Jan 2026): Store exit reason for Telegram notification
        # FIX P1 (Feb 13, 2026): Use .upper() to match WebSocket lookup keys
        self._pending_exit_reasons[symbol.upper()] = reason

        try:
            result = self.close_position(symbol)
            if result.success:
                self.logger.info(f"✅ LOCAL EXIT: {symbol} closed via MARKET")
                return True
            else:
                self.logger.error(f"❌ LOCAL EXIT failed: {result.error}")
                return False
        except Exception as e:
            self.logger.error(f"❌ LOCAL EXIT error: {e}")
            return False
    def _record_fill_to_local_tracker(
        self,
        symbol: str,
        fill_price: float,
        fill_qty: float,
        fill_fee: float,
        order_id: str,
        side: str,  # SOTA FIX: Required for Entry/Exit detection
        is_maker: bool = False
    ):
        """
        SOTA (Jan 2026): Record fill to LOCAL tracker for accurate PnL.
        SOTA FIX (Feb 2026): Thread-safe with RLock
        """
        # SOTA FIX (Feb 9, 2026): Determine if this is an exit fill BEFORE lock
        # If tracker doesn't exist and this is an exit fill, it means
        # the position was already closed and cleaned up — DON'T create ghost tracker
        is_exit_fill = False
        with self._local_positions_lock:
            tracker = self._local_positions.get(symbol)
            if tracker:
                is_exit_fill = (side == 'SELL' and tracker.side == 'LONG') or \
                               (side == 'BUY' and tracker.side == 'SHORT')

        if not tracker:
            # v5.5.0 FIX 1: PRIMARY guard — is this symbol being closed right now?
            # close_position_async/market deferred path: tracker deleted but fills still arriving
            if symbol in self._closing_symbols:
                self.logger.info(
                    f"🛡️ CLOSE-IN-PROGRESS: Ignoring fill for {symbol} "
                    f"(close pending, preventing ghost)"
                )
                return

            # SECONDARY: Check active_positions to determine if this is an exit
            pos = self.active_positions.get(symbol)
            if pos:
                pos_side = 'LONG' if pos.position_amt > 0 else 'SHORT'
                is_exit_fill = (side == 'SELL' and pos_side == 'LONG') or \
                               (side == 'BUY' and pos_side == 'SHORT')

            if is_exit_fill:
                # Ghost prevention: Don't create tracker for closing fills
                self.logger.warning(
                    f"⚠️ GHOST PREVENTION: Ignoring exit fill for {symbol} "
                    f"(tracker already cleaned up, position already closed)"
                )
                return

            # Self-healing for ENTRY fills only (e.g. after restart)
            self.logger.warning(f"⚠️ Local tracker missing for {symbol}. Creating new one (entry fill).")

            # Determine side and signal_id from pending signal or order side
            pos_side = 'LONG'  # Default
            heal_signal_id = None
            pending = self.signal_tracker.get_pending_signal(symbol)
            if pending:
                pos_side = pending.direction.value
                heal_signal_id = getattr(pending, 'signal_id', None) or getattr(getattr(pending, 'signal', None), 'signal_id', None)
            elif side == 'BUY':
                pos_side = 'LONG'
            elif side == 'SELL':
                pos_side = 'SHORT'

            with self._local_positions_lock:
                self._local_positions[symbol] = LocalPosition(
                    symbol=symbol,
                    side=pos_side,
                    intended_leverage=self.max_leverage,
                    signal_id=heal_signal_id
                )
                tracker = self._local_positions[symbol]

            # Detect actual leverage OUTSIDE lock (REST API call, 100-500ms)
            try:
                actual_lev = self._detect_actual_leverage(symbol)
                if actual_lev:
                    tracker.set_actual_leverage(actual_lev)
                    self.logger.info(f"✅ Set actual leverage for {symbol}: {actual_lev}x")
            except Exception as e:
                self.logger.debug(f"Leverage detection skipped: {e}")

        with self._local_positions_lock:
            tracker = self._local_positions.get(symbol)
            if not tracker:
                return
        fill = FillRecord(
            timestamp=datetime.now(),
            order_id=order_id,
            price=fill_price,
            quantity=fill_qty,
            fee=fill_fee,
            fee_asset='USDT',  # Assumption for USDT-margined futures
            is_maker=is_maker
        )

        # SOTA (Jan 2026): Unified Notification Logic (Entry/Exit/PnL)
        if self.telegram_service:
            self.logger.info(f"📱 Telegram service available, preparing notification for {symbol}")
            try:
                # 1. Capture State BEFORE fill update
                current_qty = getattr(tracker, 'quantity', 0.0)
                is_closing = False
                pnl = 0.0
                roi = 0.0

                # SOTA FIX (Feb 2026): Determine if this fill is an exit (closing) fill
                # Compare order side with tracker side:
                # - SELL order on LONG position = EXIT
                # - BUY order on SHORT position = EXIT
                # - Otherwise = ENTRY (adding to position)
                is_exit = (side == 'SELL' and tracker.side == 'LONG') or \
                          (side == 'BUY' and tracker.side == 'SHORT')

                # SOTA FIX (Jan 2026): Use is_exit flag instead of qty heuristic
                # Old heuristic was buggy: qty matching could trigger on partial entry fills
                if is_exit and current_qty > 0:
                    pnl = tracker.get_unrealized_pnl(fill_price)
                    roi = tracker.get_roe_percent(fill_price)
                    is_closing = True
                    self.logger.info(f"📊 Detected CLOSING fill for {symbol}")

                # 2. Add Fill (Update State) - MOVED HERE to ensure tracker is updated
                if is_exit:
                    tracker.add_exit_fill(fill)
                else:
                    tracker.add_entry_fill(fill)
                    # FIX (Feb 17): Sync MonitoredPosition entry_price with LocalPosition VWAP
                    # Multi-fill MARKET orders cause divergence between first-fill and avg price
                    if hasattr(self, 'position_monitor') and self.position_monitor:
                        monitored = self.position_monitor.get_position(symbol)
                        if monitored and tracker.avg_entry_price > 0:
                            old_entry = monitored.entry_price
                            new_entry = tracker.avg_entry_price
                            if abs(old_entry - new_entry) > old_entry * 0.0001:
                                monitored.entry_price = new_entry
                                monitored.initial_risk = abs(new_entry - monitored.initial_sl)
                                self.logger.info(
                                    f"📊 ENTRY PRICE SYNCED: {symbol} | "
                                    f"Old=${old_entry:.6f} → New=${new_entry:.6f}"
                                )

                # 3. Send Notification
                # SOTA FIX (Feb 2026): Get signal_id from LocalPosition tracker
                # Previously used pending signal lookup, but pending is deleted before fill arrives
                signal_id = getattr(tracker, 'signal_id', None)

                # SOTA (Jan 2026): Get precise exit reason (e.g. SL_HIT, TP_HIT)
                # Default to MARKET_FILL if no pending reason found
                # Use get() instead of pop() to persist reason across split order fills
                exit_reason = self._pending_exit_reasons.get(symbol, "MARKET_FILL")

                # SOTA FIX (Feb 2026): Only send close notification on FULL CLOSE
                # Check tracker.quantity AFTER add_exit_fill() to detect full close
                # This prevents 4+ notifications from partial fills of single market order
                is_fully_closed = is_closing and tracker.quantity == 0

                if is_fully_closed:
                    # v5.5.0 FIX 2c: Deferred close path — handle via _complete_deferred_close
                    if symbol in self._closing_symbols:
                        exit_reason = self._pending_exit_reasons.get(symbol, "DEFERRED")
                    else:
                        # v5.5.0 FIX 10: Exchange-initiated close (backup SL, liquidation)
                        # When exchange closes position independently (ALGO/STOP_MARKET triggers),
                        # _closing_symbols is NOT set. Must still update CB/DB/cleanup.
                        # Without this fix, CB never records the loss → allows immediate re-entry.
                        exit_reason = self._pending_exit_reasons.get(symbol, "BACKUP_SL")
                        self._closing_symbols.add(symbol)  # Prevent ghost on late fills
                        self._closing_symbols_ts[symbol] = time.time()
                        self.logger.warning(
                            f"🔄 EXCHANGE-INITIATED CLOSE: {symbol} | "
                            f"Backup SL/liquidation detected, running full completion (CB+DB+cleanup)")

                    self._complete_deferred_close(symbol, tracker, exit_reason)
                    return  # Full completion path handles everything (CB + DB + notify + cleanup)
                elif symbol not in self._notified_entry_symbols:
                    # SOTA FIX (Feb 2026): Only send 1 entry notification per position
                    # Skip if already notified for this symbol (partial fills from same order)
                    self._notified_entry_symbols.add(symbol)

                    # SOTA (Jan 2026): Use PositionContext for entry notifications
                    tracker_side = getattr(tracker, 'side', 'UNKNOWN')
                    # SOTA FIX (Feb 2026): Use intended_leverage instead of hardcoded /20
                    # Some symbols have max leverage < 20 (e.g., 10x), causing exchange to auto-reduce
                    intended_leverage = getattr(tracker, 'intended_leverage', 20)
                    # FIX (Feb 2026): Field is 'actual_leverage', not '_actual_leverage'
                    actual_leverage = getattr(tracker, 'actual_leverage', None) or intended_leverage

                    # Use AGGREGATED fill data for accurate notification
                    total_entry_qty = sum(f.quantity for f in tracker.entry_fills)
                    total_entry_cost = sum(f.price * f.quantity for f in tracker.entry_fills)
                    avg_entry_price = total_entry_cost / total_entry_qty if total_entry_qty > 0 else fill_price

                    # SOTA FIX (Feb 2026): Calculate margin from fill data
                    total_notional = total_entry_qty * avg_entry_price
                    margin_used = total_notional / actual_leverage if actual_leverage > 0 else total_notional / 20

                    all_order_ids = list(set(str(f.order_id) for f in tracker.entry_fills))

                    # SOTA FIX (Feb 2026): Get SL/TP from MonitoredPosition
                    # LocalPosition doesn't track SL/TP (it only tracks fills)
                    # MonitoredPosition is created in start_monitoring() BEFORE this notification
                    sl_price = 0.0
                    tp_price = 0.0
                    if hasattr(self, 'position_monitor') and self.position_monitor:
                        monitored = self.position_monitor.get_position(symbol)
                        if monitored:
                            sl_price = monitored.current_sl or getattr(monitored, 'initial_sl', 0.0)
                            tp_price = getattr(monitored, 'initial_tp', 0.0)
                            self.logger.debug(f"📊 Got SL/TP from MonitoredPosition: SL=${sl_price:.4f}, TP=${tp_price:.4f}")

                    position_context = PositionContext(
                        symbol=symbol,
                        side=tracker_side,
                        entry_price=avg_entry_price,  # Aggregated avg
                        filled_qty=total_entry_qty,    # Total qty
                        margin_used=margin_used,
                        leverage=actual_leverage,
                        stop_loss=sl_price,            # SOTA FIX: From MonitoredPosition
                        take_profit=tp_price,          # SOTA FIX: From MonitoredPosition
                        order_id=', '.join(all_order_ids),  # All order IDs
                        signal_id=signal_id or 'N/A',
                        timestamp=datetime.now().isoformat()
                    )

                    self.logger.info(f"📤 Telegram ENTRY notification (SOTA) queued for {symbol} ({tracker_side}) | {len(tracker.entry_fills)} fills")
                    asyncio.create_task(
                        self.telegram_service.notify_position_opened(position_context)
                    )

            except Exception as e:
                self.logger.error(f"❌ Telegram notify error: {e}", exc_info=True)
        else:
            # FIX (Feb 9, 2026): Record fill even when telegram is unavailable
            # Previously fills were only recorded inside the telegram block
            is_exit = (side == 'SELL' and tracker.side == 'LONG') or \
                      (side == 'BUY' and tracker.side == 'SHORT')
            if is_exit:
                tracker.add_exit_fill(fill)
            else:
                tracker.add_entry_fill(fill)
                # FIX (Feb 17): Sync MonitoredPosition entry_price with LocalPosition VWAP
                if hasattr(self, 'position_monitor') and self.position_monitor:
                    monitored = self.position_monitor.get_position(symbol)
                    if monitored and tracker.avg_entry_price > 0:
                        old_entry = monitored.entry_price
                        new_entry = tracker.avg_entry_price
                        if abs(old_entry - new_entry) > old_entry * 0.0001:
                            monitored.entry_price = new_entry
                            monitored.initial_risk = abs(new_entry - monitored.initial_sl)
                            self.logger.info(
                                f"📊 ENTRY PRICE SYNCED: {symbol} | "
                                f"Old=${old_entry:.6f} → New=${new_entry:.6f}"
                            )
            self.logger.warning(f"⚠️ Telegram service not available for {symbol} notification")

    def _send_exit_notification(self, symbol: str, exit_price: float, pnl: float, reason: str):
        """
        SOTA (Feb 2026): Backup exit notification from close paths.

        Ensures Telegram exit notification is sent even when WebSocket fill events
        are missed. Deduplicates with fill-based notifications via _exit_notified_symbols.

        Args:
            symbol: Trading pair
            exit_price: Price at which position closed
            pnl: Realized PnL
            reason: Exit reason (SL_HIT, TP_HIT, AUTO_CLOSE, MANUAL, etc.)
        """
        if not self.telegram_service:
            return

        symbol_upper = symbol.upper()

        # Dedup: skip if already notified (fill-based path fired first)
        if symbol_upper in self._exit_notified_symbols:
            self.logger.debug(f"📤 Exit notification already sent for {symbol_upper}, skipping backup")
            return

        self._exit_notified_symbols.add(symbol_upper)

        # Schedule cleanup of dedup set after 60s (allow both paths to check)
        async def _cleanup_dedup():
            await asyncio.sleep(60)
            self._exit_notified_symbols.discard(symbol_upper)
        try:
            asyncio.create_task(_cleanup_dedup())
        except RuntimeError:
            pass  # No event loop - skip cleanup

        try:
            # Get tracker data (may already be cleaned up, use cached data)
            tracker = None
            with self._local_positions_lock:
                tracker = self._local_positions.get(symbol_upper)

            # FIX (Feb 2026): Skip notification if tracker is None — no data to show
            if not tracker:
                self.logger.warning(f"⚠️ Backup exit notification skipped for {symbol_upper}: no tracker data")
                return

            # Build ExitContext from available data
            entry_price = tracker.avg_entry_price if tracker else 0.0
            side = tracker.side if tracker else 'UNKNOWN'
            signal_id = getattr(tracker, 'signal_id', None) if tracker else None
            total_qty = tracker.total_quantity if tracker else 0.0
            entry_fees = sum(f.fee for f in tracker.entry_fills) if tracker else 0.0
            exit_fees = abs(exit_price * total_qty * 0.0005) if total_qty > 0 else 0.0
            margin = tracker._actual_margin_used if tracker and tracker._actual_margin_used else (
                entry_price * total_qty / tracker.intended_leverage if tracker and tracker.intended_leverage > 0 else 1.0
            )
            roe_pct = (pnl / margin * 100) if margin > 0 else 0.0

            duration_minutes = 0
            if tracker and tracker.opened_at:
                duration_minutes = int((datetime.now() - tracker.opened_at).total_seconds() / 60)

            # FIX (Feb 2026): Get max_profit/max_drawdown from MonitoredPosition watermarks
            max_profit_val = 0.0
            max_drawdown_val = 0.0
            if tracker and hasattr(self, 'position_monitor') and self.position_monitor:
                monitored = self.position_monitor.get_position(symbol_upper)
                if monitored:
                    if side == 'LONG':
                        max_profit_val = (monitored.max_price - entry_price) * total_qty if monitored.max_price > entry_price else 0.0
                        max_drawdown_val = (entry_price - monitored.min_price) * total_qty if monitored.min_price < entry_price else 0.0
                    else:
                        max_profit_val = (entry_price - monitored.min_price) * total_qty if monitored.min_price < entry_price else 0.0
                        max_drawdown_val = (monitored.max_price - entry_price) * total_qty if monitored.max_price > entry_price else 0.0

            exit_context = ExitContext(
                symbol=symbol_upper,
                side=side,
                entry_price=entry_price,
                exit_price=exit_price,
                filled_qty=total_qty,
                realized_pnl=pnl,
                roe_percent=roe_pct,
                fees_total=entry_fees + exit_fees,
                fees_breakdown={'entry_fee': entry_fees, 'exit_fee': exit_fees},
                reason=reason,
                duration_minutes=duration_minutes,
                order_ids=[],
                signal_id=signal_id or 'N/A',
                timestamp=datetime.now().isoformat(),
                max_profit=max_profit_val,
                max_drawdown=max_drawdown_val
            )

            asyncio.create_task(
                self.telegram_service.notify_position_closed(exit_context)
            )
            self.logger.info(f"📤 Backup exit notification queued for {symbol_upper} | PnL=${pnl:.2f} | Reason={reason}")

        except Exception as e:
            self.logger.warning(f"⚠️ Backup exit notification failed for {symbol_upper}: {e}")

    def _complete_deferred_close(self, symbol: str, tracker, reason: str):
        """
        v5.5.0: Complete a deferred close when WebSocket fills arrive.

        Called from _record_fill_to_local_tracker when is_fully_closed AND
        symbol in _closing_symbols. The original close path (close_position_async
        or _close_position_market) got exit_price=0 from the MARKET order response,
        so it deferred CB/DB/notification to this method which has REAL fill data.

        Args:
            symbol: Trading pair (already uppercased)
            tracker: LocalPosition with exit fills recorded
            reason: Exit reason from _pending_exit_reasons
        """
        try:
            # 1. Compute avg exit price from fills
            total_exit_qty = sum(f.quantity for f in tracker.exit_fills)
            total_exit_cost = sum(f.price * f.quantity for f in tracker.exit_fills)
            avg_exit_price = total_exit_cost / total_exit_qty if total_exit_qty > 0 else 0.0

            if avg_exit_price == 0:
                self.logger.error(f"❌ DEFERRED CLOSE: {symbol} still has exit_price=0 after fills")
                return

            # 2. Get PnL (cached by add_exit_fill)
            pnl = tracker._cached_realized_pnl if tracker._cached_realized_pnl is not None else tracker.get_realized_pnl(avg_exit_price)
            side = tracker.side

            self.logger.info(
                f"✅ DEFERRED CLOSE COMPLETE: {symbol} | Exit=${avg_exit_price:.4f} | "
                f"PnL=${pnl:.4f} | Reason={reason}"
            )

            # 3. Circuit Breaker update (REAL exit_price)
            try:
                if hasattr(self, 'circuit_breaker') and self.circuit_breaker:
                    self.circuit_breaker.record_trade_with_time(
                        symbol, side, pnl, datetime.now(timezone.utc)
                    )
                    self.logger.debug(f"🛡️ CB updated (deferred): {symbol} {side} PnL=${pnl:.2f}")
            except Exception as cb_err:
                self.logger.warning(f"⚠️ CB update failed (deferred): {cb_err}")

            # 4. DB persist (REAL PnL)
            try:
                if self.order_repo:
                    self.order_repo.close_live_position(symbol, avg_exit_price, pnl, reason)
                    self.logger.info(f"💾 DB position closed (deferred): {symbol} PnL=${pnl:.2f}")
            except Exception as db_err:
                self.logger.warning(f"⚠️ DB persist failed (deferred): {db_err}")

            # 5. Telegram exit notification
            self._send_exit_notification(symbol, avg_exit_price, pnl, reason)

            # 6. Stop monitoring
            try:
                from .position_monitor_service import get_position_monitor
                monitor = get_position_monitor()
                monitor.stop_monitoring(symbol)
            except Exception as mon_err:
                self.logger.debug(f"Stop monitoring cleanup (deferred): {mon_err}")

            # 7. CSV buffer
            self._add_to_csv_buffer(symbol, tracker, avg_exit_price, pnl, reason)

            # 7b. v6.3.0: Analytics collection (fire-and-forget)
            if self._analytics_collector:
                try:
                    asyncio.create_task(self._analytics_collector.collect_after_close(symbol))
                except Exception:
                    pass

            # 8. State cleanup
            if symbol in self.active_positions:
                del self.active_positions[symbol]
            with self._local_positions_lock:
                self._local_positions.pop(symbol, None)

            # 9. Clean dedup sets
            self._notified_entry_symbols.discard(symbol)
            self._exit_notified_symbols.discard(symbol)

            # 10. Clean pending exit reason
            if symbol in self._pending_exit_reasons:
                del self._pending_exit_reasons[symbol]

        except Exception as e:
            self.logger.error(f"❌ DEFERRED CLOSE FAILED: {symbol} | {e}", exc_info=True)

        finally:
            # v5.5.0 FIX: Delay discard by 5s to catch late-arriving fills
            # Without this, fills arriving after discard bypass ghost prevention
            # and create false ENTRY notifications
            async def _delayed_discard():
                await asyncio.sleep(5)
                self._closing_symbols.discard(symbol)
                self._closing_symbols_ts.pop(symbol, None)
            try:
                asyncio.create_task(_delayed_discard())
            except RuntimeError:
                # No event loop — discard immediately (shouldn't happen in LIVE)
                self._closing_symbols.discard(symbol)
                self._closing_symbols_ts.pop(symbol, None)

    def _add_to_csv_buffer(self, symbol: str, tracker, exit_price: float, pnl: float, reason: str):
        """
        v5.5.0: Add closed trade to CSV buffer with 31 columns.

        Triggers _send_csv_milestone() every 10 trades.

        Args:
            symbol: Trading pair
            tracker: LocalPosition with all fill data
            exit_price: Avg exit price
            pnl: Realized PnL
            reason: Exit reason
        """
        try:
            self._trade_counter_today += 1
            self._cumulative_pnl_today += pnl

            entry_price = tracker.avg_entry_price
            total_qty = tracker.total_quantity
            side = tracker.side
            leverage = tracker.actual_leverage or tracker.intended_leverage
            margin = tracker._actual_margin_used or (entry_price * total_qty / leverage if leverage > 0 else 0)
            roe_pct = (pnl / margin * 100) if margin > 0 else 0.0

            # Entry/exit fees
            entry_fee = sum(f.fee for f in tracker.entry_fills)
            exit_fee = sum(f.fee for f in tracker.exit_fills)

            # Duration
            opened_at = getattr(tracker, 'opened_at', None)
            duration_min = 0
            if opened_at:
                duration_min = round((datetime.now() - opened_at).total_seconds() / 60, 1)

            # Slippage
            signal_target = getattr(tracker, 'signal_entry_target', None)
            slippage_entry_pct = 0.0
            if signal_target and signal_target > 0:
                slippage_entry_pct = (entry_price - signal_target) / signal_target * 100

            # MFE/MAE from MonitoredPosition watermarks
            mfe_pct = 0.0
            mae_pct = 0.0
            monitored = None
            if hasattr(self, 'position_monitor') and self.position_monitor:
                monitored = self.position_monitor.get_position(symbol)
                if monitored:
                    if side == 'LONG':
                        if monitored.max_price > entry_price:
                            mfe_pct = (monitored.max_price - entry_price) / entry_price * 100
                        if monitored.min_price < entry_price:
                            mae_pct = (entry_price - monitored.min_price) / entry_price * 100
                    else:
                        if monitored.min_price < entry_price:
                            mfe_pct = (entry_price - monitored.min_price) / entry_price * 100
                        if monitored.max_price > entry_price:
                            mae_pct = (monitored.max_price - entry_price) / entry_price * 100

            # R-multiple
            signal_sl = getattr(tracker, 'signal_sl', None)
            r_multiple = 0.0
            if signal_sl and signal_sl > 0 and entry_price > 0:
                initial_risk = abs(entry_price - signal_sl)
                if initial_risk > 0:
                    r_multiple = pnl / (initial_risk * total_qty) if total_qty > 0 else 0.0

            # Breakeven (reuse monitored from MFE/MAE block above)
            breakeven_triggered = False
            if monitored:
                breakeven_triggered = getattr(monitored, 'breakeven_triggered', False)

            # Balance after
            balance_after = (self._cached_balance or self.initial_balance or 0) + pnl

            entry_time = tracker.opened_at.isoformat() if tracker.opened_at else ''
            exit_time = datetime.now().isoformat()

            row = {
                'signal_id': getattr(tracker, 'signal_id', '') or '',
                'symbol': symbol,
                'side': side,
                'confidence': getattr(tracker, 'signal_confidence', 0.0) or 0.0,
                'signal_time': getattr(tracker, 'signal_time', '') or '',
                'signal_entry_target': signal_target or 0.0,
                'signal_sl': signal_sl or 0.0,
                'signal_tp1': getattr(tracker, 'signal_tp1', 0.0) or 0.0,
                'entry_price': entry_price,
                'entry_time': entry_time,
                'entry_qty': total_qty,
                'entry_fee': entry_fee,
                'leverage': leverage,
                'margin': margin,
                'slippage_entry_pct': round(slippage_entry_pct, 4),
                'breakeven_triggered': breakeven_triggered,
                'highest_price': getattr(monitored, 'max_price', 0.0) if monitored else 0.0,
                'lowest_price': getattr(monitored, 'min_price', 0.0) if monitored else 0.0,
                'mfe_pct': round(mfe_pct, 4),
                'mae_pct': round(mae_pct, 4),
                'exit_price': exit_price,
                'exit_time': exit_time,
                'exit_fee': exit_fee,
                'exit_reason': reason,
                'duration_min': duration_min,
                'realized_pnl': round(pnl, 4),
                'roe_pct': round(roe_pct, 2),
                'r_multiple': round(r_multiple, 3),
                'cumulative_pnl': round(self._cumulative_pnl_today, 4),
                'trade_number': self._trade_counter_today,
                'balance_after': round(balance_after, 2),
            }

            self._closed_trades_buffer.append(row)
            self.logger.info(f"📊 CSV buffer: trade #{self._trade_counter_today} | {symbol} {side} PnL=${pnl:.2f}")

            # Trigger milestone every 10 trades
            if self._trade_counter_today % 10 == 0:
                try:
                    asyncio.create_task(self._send_csv_milestone())
                except RuntimeError:
                    pass  # No event loop

        except Exception as e:
            self.logger.warning(f"⚠️ CSV buffer add failed: {e}")

    async def _send_csv_milestone(self):
        """
        v5.5.0: Send accumulated CSV buffer via Telegram every 10 trades.
        """
        if not self.telegram_service or not self._closed_trades_buffer:
            return

        import csv
        import tempfile
        import os

        try:
            today = datetime.now().strftime('%Y-%m-%d')
            total_trades = len(self._closed_trades_buffer)
            wins = sum(1 for r in self._closed_trades_buffer if r['realized_pnl'] > 0)
            losses = total_trades - wins
            wr = (wins / total_trades * 100) if total_trades > 0 else 0

            csv_path = os.path.join(
                tempfile.gettempdir(),
                f"trades_{today}_milestone_{self._trade_counter_today}_{os.getpid()}.csv"
            )

            columns = [
                'signal_id', 'symbol', 'side', 'confidence', 'signal_time',
                'signal_entry_target', 'signal_sl', 'signal_tp1',
                'entry_price', 'entry_time', 'entry_qty', 'entry_fee', 'leverage', 'margin',
                'slippage_entry_pct', 'breakeven_triggered', 'highest_price', 'lowest_price',
                'mfe_pct', 'mae_pct',
                'exit_price', 'exit_time', 'exit_fee', 'exit_reason', 'duration_min',
                'realized_pnl', 'roe_pct', 'r_multiple',
                'cumulative_pnl', 'trade_number', 'balance_after',
            ]

            with open(csv_path, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                writer.writeheader()
                for row in self._closed_trades_buffer:
                    writer.writerow(row)

            caption = (
                f"Trades CSV | {today} | {total_trades} trades "
                f"(1-{total_trades}) | PnL: ${self._cumulative_pnl_today:.2f} | "
                f"W:{wins} L:{losses} | WR: {wr:.0f}%"
            )

            await self.telegram_service.send_document(csv_path, caption=caption)
            self.logger.info(f"📊 CSV milestone sent: {total_trades} trades")

            try:
                os.remove(csv_path)
            except Exception:
                pass

        except Exception as e:
            self.logger.warning(f"⚠️ CSV milestone send failed: {e}")

    async def _daily_summary_loop(self):
        """
        SOTA (Feb 2026): Daily summary scheduler.

        Runs at 00:00 UTC+7 (17:00 UTC) every day.
        Sends daily performance summary + CSV export via Telegram.
        """
        from datetime import timedelta

        while True:
            try:
                # Calculate seconds until next 17:00 UTC (00:00 UTC+7)
                now = datetime.now(timezone.utc)
                target = now.replace(hour=17, minute=0, second=0, microsecond=0)
                if now >= target:
                    target += timedelta(days=1)
                wait_seconds = (target - now).total_seconds()

                self.logger.info(
                    f"📊 Daily summary scheduled in {wait_seconds/3600:.1f}h "
                    f"(at {target.strftime('%H:%M')} UTC)"
                )
                await asyncio.sleep(wait_seconds)

                # Send daily summary
                await self._send_daily_summary()

                # Run DB cleanup after summary
                await self._run_daily_cleanup()

                # v6.3.0: Analytics daily report (00:05 UTC+7)
                if self._analytics_report_service:
                    try:
                        await asyncio.sleep(300)  # Wait 5 minutes after cleanup
                        await self._analytics_report_service.generate_daily_report()
                    except Exception as analytics_err:
                        self.logger.warning(f"⚠️ Analytics daily report failed: {analytics_err}")

            except asyncio.CancelledError:
                self.logger.info("📊 Daily summary loop cancelled")
                break
            except Exception as e:
                self.logger.error(f"❌ Daily summary loop error: {e}")
                await asyncio.sleep(300)  # Retry in 5 minutes

    async def _send_daily_summary(self):
        """
        SOTA (Feb 2026): Generate and send daily performance summary + CSV.
        """
        if not self.telegram_service:
            return

        from ...infrastructure.notifications.telegram_service import DailySummary
        import csv
        import tempfile
        import os

        try:
            today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

            # Query closed positions from DB
            # DB columns: open_time, close_time, realized_pnl, exit_reason, exit_price
            closed_trades = []
            if self.order_repo:
                try:
                    all_positions = self.order_repo.get_all_live_positions()
                    closed_trades = [
                        p for p in all_positions
                        if p.get('status') == 'CLOSED'
                        and (p.get('close_time') or '').startswith(today)
                    ]
                except Exception as e:
                    self.logger.warning(f"⚠️ Failed to query closed trades: {e}")

            if not closed_trades:
                # Still send summary even with 0 trades
                self.logger.info(f"📊 No trades closed today ({today})")

            # Calculate statistics
            total_trades = len(closed_trades)
            pnls = [float(t.get('realized_pnl', 0)) for t in closed_trades]
            winning = [p for p in pnls if p > 0]
            losing = [p for p in pnls if p < 0]
            total_pnl = sum(pnls)

            # Estimate fees (0.1% round trip)
            total_fees = sum(
                float(t.get('entry_price', 0)) * float(t.get('quantity', 0)) * 0.001
                for t in closed_trades
            )

            # Duration
            durations = []
            for t in closed_trades:
                opened = t.get('open_time', '')
                closed = t.get('close_time', '')
                if opened and closed:
                    try:
                        d_open = datetime.fromisoformat(opened.replace('Z', '+00:00'))
                        d_close = datetime.fromisoformat(closed.replace('Z', '+00:00'))
                        durations.append((d_close - d_open).total_seconds() / 60)
                    except Exception:
                        pass

            avg_duration = sum(durations) / len(durations) if durations else 0

            # Portfolio value
            portfolio_value = self._cached_balance or self.initial_balance or 0

            # Drawdown
            drawdown = 0.0
            if self.peak_balance > 0:
                drawdown = ((self.peak_balance - portfolio_value) / self.peak_balance) * 100

            # Profit factor
            gross_profit = sum(winning)
            gross_loss = abs(sum(losing))
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf') if gross_profit > 0 else 0

            summary = DailySummary(
                date=today,
                total_trades=total_trades,
                winning_trades=len(winning),
                losing_trades=len(losing),
                total_pnl=total_pnl,
                total_fees=total_fees,
                avg_trade_duration=avg_duration,
                best_trade_pnl=max(pnls) if pnls else 0,
                worst_trade_pnl=min(pnls) if pnls else 0,
                portfolio_value=portfolio_value,
                drawdown_percent=drawdown,
                win_rate=(len(winning) / total_trades * 100) if total_trades > 0 else 0,
                profit_factor=profit_factor
            )

            # Send summary message
            await self.telegram_service.notify_daily_summary(summary)
            self.logger.info(f"📊 Daily summary sent: {total_trades} trades, PnL=${total_pnl:.2f}")

            # v5.5.0: Send comprehensive CSV from buffer (31 columns)
            if self._closed_trades_buffer:
                try:
                    await self._send_csv_milestone()
                    self.logger.info(f"📊 Final daily CSV sent: {len(self._closed_trades_buffer)} trades from buffer")
                except Exception as csv_err:
                    self.logger.warning(f"⚠️ Buffer CSV send failed: {csv_err}")

                # Reset buffer for next day
                self._closed_trades_buffer.clear()
                self._trade_counter_today = 0
                self._cumulative_pnl_today = 0.0
            elif closed_trades:
                # Fallback: DB-based CSV if buffer is empty (e.g. after restart)
                try:
                    csv_path = os.path.join(
                        tempfile.gettempdir(),
                        f"trades_{today}_{os.getpid()}.csv"
                    )
                    with open(csv_path, 'w', newline='') as f:
                        writer = csv.writer(f)
                        writer.writerow([
                            'signal_id', 'symbol', 'side', 'entry_price', 'exit_price',
                            'quantity', 'pnl', 'roe_pct', 'reason', 'duration_min',
                            'entry_time', 'exit_time'
                        ])
                        for t in closed_trades:
                            entry_p = float(t.get('entry_price', 0))
                            exit_p = float(t.get('exit_price', 0))
                            qty = float(t.get('quantity', 0))
                            trade_pnl = float(t.get('realized_pnl', 0))
                            lev = float(t.get('leverage', 10))
                            margin_val = entry_p * qty / lev if lev > 0 else 1
                            roe = (trade_pnl / margin_val * 100) if margin_val > 0 else 0

                            dur = 0
                            opened = t.get('open_time', '')
                            closed_t = t.get('close_time', '')
                            if opened and closed_t:
                                try:
                                    d_open = datetime.fromisoformat(opened.replace('Z', '+00:00'))
                                    d_close = datetime.fromisoformat(closed_t.replace('Z', '+00:00'))
                                    dur = int((d_close - d_open).total_seconds() / 60)
                                except Exception:
                                    pass

                            writer.writerow([
                                t.get('signal_id', ''), t.get('symbol', ''), t.get('side', ''),
                                f"{entry_p:.4f}", f"{exit_p:.4f}", f"{qty:.6f}",
                                f"{trade_pnl:.4f}", f"{roe:.2f}", t.get('exit_reason', ''),
                                dur, t.get('open_time', ''), t.get('close_time', ''),
                            ])

                    await self.telegram_service.send_document(
                        csv_path,
                        caption=f"Trades CSV (DB fallback) - {today} | {total_trades} trades | PnL: ${total_pnl:.2f}"
                    )
                    self.logger.info(f"📊 Daily CSV sent (DB fallback): {csv_path}")
                    try:
                        os.remove(csv_path)
                    except Exception:
                        pass
                except Exception as csv_err:
                    self.logger.warning(f"⚠️ CSV generation failed: {csv_err}")

        except Exception as e:
            self.logger.error(f"❌ Daily summary generation failed: {e}")

    async def _run_daily_cleanup(self):
        """
        SOTA (Feb 2026): Daily database cleanup to prevent unbounded growth.

        Runs after daily summary at 00:00 UTC+7. Cleans:
        - signals older than 7 days (~2,800/day → max ~20K rows)
        - ghost OPEN positions older than 24 hours
        - CLOSED/REPLACED/GHOST_CLOSED positions older than 30 days
        Then VACUUMs to reclaim disk space.
        """
        if not self.order_repo:
            return

        try:
            signals_deleted = self.order_repo.cleanup_old_signals(retention_days=7)
            ghosts_closed = self.order_repo.cleanup_ghost_positions(max_age_hours=24)
            old_deleted = self.order_repo.cleanup_old_closed_positions(retention_days=30)
            db_size_mb = self.order_repo.vacuum_database()

            self.logger.info(
                f"🧹 Daily cleanup: signals={signals_deleted}, ghosts={ghosts_closed}, "
                f"old_positions={old_deleted}, DB={db_size_mb}MB"
            )

            # Send Telegram cleanup report
            if self.telegram_service:
                try:
                    report = (
                        f"🧹 <b>Daily DB Cleanup</b>\n\n"
                        f"• Signals deleted (>7d): <code>{signals_deleted}</code>\n"
                        f"• Ghost positions closed (>24h): <code>{ghosts_closed}</code>\n"
                        f"• Old closed positions deleted (>30d): <code>{old_deleted}</code>\n"
                        f"• DB size after VACUUM: <code>{db_size_mb} MB</code>"
                    )
                    await self.telegram_service.send_message(report, silent=True)
                except Exception as tg_err:
                    self.logger.warning(f"⚠️ Cleanup Telegram report failed: {tg_err}")

        except Exception as e:
            self.logger.error(f"❌ Daily cleanup failed: {e}")

    def _send_system_alert(self, alert_type: str, component: str, message: str, details: Dict[str, Any] = None):
        """
        SOTA (Feb 2026): Send system health alert via Telegram.

        Args:
            alert_type: CRITICAL, ERROR, WARNING, INFO
            component: System component name
            message: Alert message
            details: Additional context
        """
        if not self.telegram_service:
            return
        try:
            alert = SystemAlert(
                alert_type=alert_type,
                component=component,
                message=message,
                details=details or {},
                timestamp=datetime.now().isoformat()
            )
            asyncio.create_task(
                self.telegram_service.notify_system_alert(alert)
            )
        except Exception as e:
            self.logger.debug(f"System alert notification failed: {e}")

    def _detect_actual_leverage(self, symbol: str) -> Optional[int]:
        """
        SOTA (Jan 2026): Detect ACTUAL leverage from Binance.
        v5.5.0 FIX: Use get_position() instead of futures_position_information()
        which may not exist on all client versions and crashes.
        """
        try:
            pos = self.client.get_position(symbol.upper())
            if pos:
                lev = int(getattr(pos, 'leverage', 0)) or None
                if lev:
                    self.logger.info(f"🔍 Detected ACTUAL leverage for {symbol}: {lev}x")
                return lev
            return None
        except Exception as e:
            self.logger.error(f"❌ Failed to detect actual leverage: {e}")
            return None

    # NOTE: _check_auto_close_local is defined at end of file (line ~7222)
    # with SOTA v4 implementation that includes guard check and better logging

    def _calculate_portfolio_pnl_local(self, price_map: Dict[str, float]) -> float:
        """
        SOTA (Jan 2026): Calculate TOTAL Portfolio PnL using Local Trackers.

        Source of Truth: LocalPosition (Net of Fees, Actual Leverage).
        Price Source: PositionMonitor (Real-Time Ticks).

        Args:
            price_map: Dict {symbol: current_close_price}
        """
        total_pnl = 0.0
        try:
            # SOTA FIX (Feb 2026): Thread-safe iteration with copy
            with self._local_positions_lock:
                positions_snapshot = list(self._local_positions.items())

            for symbol, tracker in positions_snapshot:
                if not tracker:
                    continue

                # Get latest price from map (provided by PositionMonitor)
                current_price = price_map.get(symbol)

                # Validation
                if not current_price or current_price <= 0:
                    continue

                # SOTA FIX (Feb 2026): Unrealized PnL = entry fee only (matches Binance API)
                pnl = tracker.get_unrealized_pnl(current_price)
                total_pnl += pnl

            # Log periodically (1% chance to reduce noise)
            if total_pnl != 0 and random.randint(1, 100) == 1:
                self.logger.info(f"💰 Portfolio Unrealized PnL: ${total_pnl:.2f}")

            return total_pnl

        except Exception as e:
            self.logger.error(f"❌ Error in _calculate_portfolio_pnl_local: {e}")
            return 0.0


    def _cancel_backup_sl(self, symbol: str) -> bool:
        """
        SOTA Local-First: Cancel backup SL on exchange after position closes.

        Called by PositionMonitorService after local exit or TP hit.

        DEPRECATED: Use _cleanup_all_orders_for_symbol() instead for comprehensive cleanup.
        """
        try:
            symbol_upper = symbol.upper()
            watermark = self._position_watermarks.get(symbol_upper, {})
            backup_sl_id = watermark.get('sl_order_id')

            if backup_sl_id and self.client:
                # Cancel the algo order
                self.client.cancel_algo_order(
                    symbol=symbol_upper,
                    algo_id=backup_sl_id
                )
                self.logger.info(f"🧹 BACKUP SL CANCELLED: {symbol_upper} [AlgoID: {backup_sl_id}]")

                # Clean up watermark
                if symbol_upper in self._position_watermarks:
                    del self._position_watermarks[symbol_upper]

                return True

            return False

        except Exception as e:
            self.logger.warning(f"⚠️ Failed to cancel backup SL for {symbol}: {e}")
            return False

    def _cleanup_all_orders_for_symbol(self, symbol: str, reason: str = "UNKNOWN") -> int:
        """
        SOTA (Jan 2026): Unified cleanup - cancel ALL orders (regular + algo) for a symbol.

        This function ensures NO orphaned orders remain after position closes.
        Called from: close_position, _on_sl_hit, _on_tp_hit, _cleanup_stale_tracking

        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            reason: Cleanup reason for logging (SL_HIT, TP_HIT, MANUAL, ORPHAN, STALE, STARTUP)

        Returns:
            Total count of orders cancelled
        """
        symbol_upper = symbol.upper()
        cancelled_count = 0

        self.logger.info(f"🧹 [{reason}] Starting cleanup for {symbol_upper}...")

        if not self.client:
            self.logger.warning(f"⚠️ No client available for cleanup: {symbol_upper}")
            return 0

        # 1. Cancel regular orders (LIMIT, MARKET, etc.)
        try:
            self.client.cancel_all_orders(symbol_upper)
            self.logger.info(f"🧹 [{reason}] Cancelled regular orders: {symbol_upper}")
        except Exception as e:
            self.logger.warning(f"⚠️ [{reason}] Failed to cancel regular orders for {symbol_upper}: {e}")

        # 2. Cancel ALL algo orders (STOP_MARKET, TAKE_PROFIT_MARKET)
        try:
            algo_orders = self.client.get_open_algo_orders(symbol_upper)
            if algo_orders:
                self.logger.info(f"🧹 [{reason}] Found {len(algo_orders)} algo orders for {symbol_upper}")
                for ao in algo_orders:
                    algo_id = ao.get('algoId') or ao.get('orderId')
                    algo_type = ao.get('orderType') or ao.get('type', 'UNKNOWN')
                    trigger_price = ao.get('triggerPrice') or ao.get('stopPrice', 0)

                    if algo_id:
                        try:
                            self.client.cancel_algo_order(symbol_upper, str(algo_id))
                            cancelled_count += 1
                            self.logger.info(
                                f"🧹 [{reason}] Cancelled algo order: {symbol_upper} "
                                f"[AlgoID: {algo_id}] Type: {algo_type} Trigger: ${float(trigger_price):.4f}"
                            )
                        except Exception as cancel_err:
                            self.logger.warning(
                                f"⚠️ [{reason}] Failed to cancel algo {algo_id}: {cancel_err}"
                            )
            else:
                self.logger.debug(f"🧹 [{reason}] No algo orders found for {symbol_upper}")
        except Exception as e:
            self.logger.warning(f"⚠️ [{reason}] Failed to fetch/cancel algo orders for {symbol_upper}: {e}")

        # 3. Clean local state
        if symbol_upper in self._position_watermarks:
            del self._position_watermarks[symbol_upper]
            self.logger.debug(f"🧹 [{reason}] Cleaned watermark: {symbol_upper}")

        if symbol_upper in self._bracket_orders:
            del self._bracket_orders[symbol_upper]
            self.logger.debug(f"🧹 [{reason}] Cleaned bracket orders: {symbol_upper}")

        if symbol_upper in self._position_states:
            del self._position_states[symbol_upper]
            self.logger.debug(f"🧹 [{reason}] Cleaned position state: {symbol_upper}")

        self.logger.info(f"✅ [{reason}] Cleanup complete for {symbol_upper}: {cancelled_count} algo orders cancelled")

        return cancelled_count

    def _startup_orphan_cleanup(self) -> Dict[str, Any]:
        """
        SOTA (Jan 2026): Clean orphan orders on startup.

        Called during initialization to ensure no stale algo orders remain
        from previous sessions that could affect new positions.

        Returns:
            Dict with cleanup results
        """
        results = {
            'orphan_algo_cancelled': 0,
            'active_positions': 0,
            'errors': []
        }

        self.logger.info("🚀 Starting startup orphan cleanup...")

        if not self.client:
            self.logger.warning("⚠️ No client available for startup cleanup")
            return results

        try:
            # 1. Fetch all positions with retry logic
            MAX_RETRIES = 3
            positions = None
            for attempt in range(MAX_RETRIES):
                try:
                    positions = self.client.get_positions()
                    break
                except Exception as e:
                    if attempt < MAX_RETRIES - 1:
                        import time
                        delay = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                        self.logger.warning(f"⚠️ [STARTUP] get_positions attempt {attempt + 1} failed: {e}, retrying in {delay}s...")
                        time.sleep(delay)
                    else:
                        self.logger.error(f"❌ [STARTUP] Failed to get positions after {MAX_RETRIES} attempts, ABORTING cleanup")
                        results['errors'].append(f"Failed to get positions after {MAX_RETRIES} attempts")
                        return results  # ABORT cleanup if can't get positions

            active_symbols = {
                p.symbol for p in positions
                if abs(p.position_amt) > 0
            }
            results['active_positions'] = len(active_symbols)

            self.logger.info(f"📊 Found {len(active_symbols)} active positions: {', '.join(active_symbols) if active_symbols else 'None'}")

            # 2. Fetch all algo orders with retry logic
            algo_orders = None
            for attempt in range(MAX_RETRIES):
                try:
                    algo_orders = self.client.get_open_algo_orders() or []
                    break
                except Exception as e:
                    if attempt < MAX_RETRIES - 1:
                        import time
                        delay = 2 ** attempt
                        self.logger.warning(f"⚠️ [STARTUP] get_open_algo_orders attempt {attempt + 1} failed: {e}, retrying in {delay}s...")
                        time.sleep(delay)
                    else:
                        self.logger.warning(f"⚠️ [STARTUP] Failed to get algo orders after {MAX_RETRIES} attempts, continuing with empty list")
                        algo_orders = []  # Continue with empty list

            if not algo_orders:
                self.logger.info("✅ No algo orders found - nothing to cleanup")
                return results

            self.logger.info(f"📋 Found {len(algo_orders)} algo orders")

            # 3. Cancel orphan algo orders (orders without positions)
            from ...infrastructure.api.algo_order_parser import AlgoOrderParser

            for ao in algo_orders:
                symbol = AlgoOrderParser.get_symbol(ao)
                if symbol and symbol not in active_symbols:
                    # Orphan detected
                    algo_id = AlgoOrderParser.get_order_id(ao)
                    algo_type = AlgoOrderParser.get_order_type(ao)
                    trigger_price = AlgoOrderParser.get_trigger_price(ao)

                    try:
                        self.client.cancel_algo_order(symbol, str(algo_id))
                        results['orphan_algo_cancelled'] += 1
                        self.logger.info(
                            f"🧹 [STARTUP] Cancelled orphan: {symbol} "
                            f"[AlgoID: {algo_id}] Type: {algo_type} Trigger: ${trigger_price:.4f}"
                        )
                    except Exception as cancel_err:
                        error_msg = f"Failed to cancel {symbol} [{algo_id}]: {cancel_err}"
                        results['errors'].append(error_msg)
                        self.logger.warning(f"⚠️ [STARTUP] {error_msg}")

            self.logger.info(
                f"✅ Startup cleanup complete: "
                f"{results['orphan_algo_cancelled']} orphans cancelled, "
                f"{results['active_positions']} active positions"
            )

        except Exception as e:
            error_msg = f"Startup cleanup failed: {e}"
            results['errors'].append(error_msg)
            self.logger.error(f"❌ {error_msg}")

        return results

    def _persist_sl_to_db(
        self,
        symbol: str,
        new_sl: float,
        entry_price: float = 0.0,  # SOTA FIX (Jan 2026): Pass from MonitoredPosition
        side: str = ''             # SOTA FIX (Jan 2026): Pass from MonitoredPosition
    ) -> bool:
        """
        SOTA (Jan 2026): Persist SL to DB for restart recovery AND update watermarks for UI.

        Called by PositionMonitorService when trailing/breakeven updates SL.
        Ensures SL changes survive backend restart AND show in UI immediately.

        CRITICAL FIX (Jan 2026): Creates watermark if missing to prevent silent failures.
        This fixes the bug where SL wasn't updated after TP1 hit because watermark didn't exist.

        CRITICAL FIX v2 (Jan 2026): Now accepts entry_price and side to create complete watermarks.
        This fixes the bug where UI showed backup SL instead of breakeven because watermark had
        entry_price=0, causing effective_sl to fallback to exchange_sl.

        Args:
            symbol: Trading pair
            new_sl: New stop loss price
            entry_price: Position entry price (from MonitoredPosition)
            side: Position side 'LONG' or 'SHORT' (from MonitoredPosition)

        Returns:
            Success status
        """
        try:
            symbol_upper = symbol.upper()
            old_sl = 0.0

            # SOTA FIX (Jan 2026): Update watermarks for UI display
            # Without this, breakeven/trailing SL changes don't appear in portfolio!
            if symbol_upper in self._position_watermarks:
                old_sl = self._position_watermarks[symbol_upper].get('current_sl', 0)
                self._position_watermarks[symbol_upper]['current_sl'] = new_sl

                # SOTA FIX v2 (Jan 2026): Update entry_price and side if provided and missing
                if entry_price > 0 and self._position_watermarks[symbol_upper].get('entry_price', 0) == 0:
                    self._position_watermarks[symbol_upper]['entry_price'] = entry_price
                if side and not self._position_watermarks[symbol_upper].get('side'):
                    self._position_watermarks[symbol_upper]['side'] = side

                self.logger.info(f"🔄 Watermark SL updated: {symbol_upper} ${old_sl:.4f} → ${new_sl:.4f} (keys={len(self._position_watermarks)})")
            else:
                # CRITICAL FIX (Jan 2026): Create watermark if not exists
                # This fixes the bug where TP1 hit but SL wasn't updated because watermark was missing!

                # CRITICAL FIX v2 (Jan 2026): Use passed entry_price and side instead of 0/''
                # If not provided, try to get from active_positions as fallback
                actual_entry = entry_price
                actual_side = side

                if actual_entry == 0 or not actual_side:
                    # Fallback: Try to get from active_positions
                    if symbol_upper in self.active_positions:
                        pos = self.active_positions[symbol_upper]
                        if actual_entry == 0:
                            actual_entry = pos.entry_price if hasattr(pos, 'entry_price') else 0
                        if not actual_side:
                            actual_side = 'LONG' if (hasattr(pos, 'position_amt') and pos.position_amt > 0) else 'SHORT'

                self.logger.warning(
                    f"⚠️ Watermark missing for {symbol_upper}! Creating with entry=${actual_entry:.4f}, side={actual_side}. "
                    f"(keys={len(self._position_watermarks)})"
                )
                self._position_watermarks[symbol_upper] = {
                    'current_sl': new_sl,
                    'tp_target': 0,  # Already hit (TP1 triggered this SL update)
                    'is_breakeven': True,
                    'tp_hit_count': 1,
                    'phase': 'TRAILING',
                    'highest': 0,
                    'lowest': float('inf'),
                    'entry_price': actual_entry,  # CRITICAL FIX v2: Use actual value
                    'atr': 0,
                    'side': actual_side  # CRITICAL FIX v2: Use actual value
                }
                self.logger.info(f"✅ Created watermark for {symbol_upper} with SL=${new_sl:.4f}, entry=${actual_entry:.4f}, side={actual_side}")

            # CRITICAL FIX v2 (Jan 2026): Invalidate portfolio cache immediately
            # This ensures next get_portfolio() returns fresh data with new SL
            self._portfolio_cache = None
            self._portfolio_cache_time = 0
            self.logger.debug(f"🗑️ Portfolio cache invalidated after SL update for {symbol_upper}")

            # SOTA FIX v2 (Jan 2026): Broadcast WebSocket event for real-time UI update
            self._broadcast_sl_update(symbol_upper, new_sl, old_sl, 'BREAKEVEN')

            if self.order_repo:
                self.order_repo.update_live_position_sl(symbol_upper, new_sl)
                self.logger.debug(f"💾 SL persisted to DB: {symbol_upper} @ ${new_sl:.4f}")
                return True
            else:
                self.logger.debug(f"⚠️ No order_repo to persist SL for {symbol_upper}")
                return False

        except Exception as e:
            self.logger.warning(f"⚠️ Failed to persist SL to DB: {e}")
            return False

    def execute_signal(self, signal: TradingSignal) -> bool:
        """
        SOTA (Jan 2026): Execute signal by adding to LocalSignalTracker.

        Called by SharkTankCoordinator via execute_signal_callback.
        The signal is added to local tracker and will be executed via MARKET
        order when price hits target (LocalSignalTracker pattern).

        SOTA (Jan 2026): Layer 3 - Final safety check for SHORT signals in LIVE mode.
        This is the last line of defense - signals should never reach here.

        Args:
            signal: TradingSignal from strategy

        Returns:
            True if signal was added successfully, False if rejected
        """
        # SOTA (Jan 2026): BTC Filter - Block signals based on BTC trend
        if self._use_btc_filter:
            import asyncio
            try:
                # SOTA FIX (Feb 2026): Safe async execution
                # Check if already in async context to avoid RuntimeError
                try:
                    asyncio.get_running_loop()
                    # Already in async context - skip BTC filter (fail-safe: allow signal)
                    self.logger.debug("BTC Filter skipped (async context) - allowing signal")
                    btc_trend = 'NEUTRAL'
                except RuntimeError:
                    # Not in async context - safe to use asyncio.run()
                    btc_trend = asyncio.run(self._get_btc_trend())

                if btc_trend == 'BEARISH':
                    # Death Cross - Block ALL signals
                    self.logger.warning(
                        f"🚫 BTC FILTER BLOCKED: {signal.symbol} {signal.signal_type.name} | "
                        f"BTC Death Cross (EMA50 < EMA200) - Market bearish"
                    )
                    return False

                elif btc_trend == 'BULLISH' and signal.signal_type == SignalType.SELL:
                    # Golden Cross - Block SHORT signals only
                    self.logger.warning(
                        f"🚫 BTC FILTER BLOCKED: {signal.symbol} SHORT | "
                        f"BTC Golden Cross (EMA50 > EMA200) - Only LONG allowed"
                    )
                    return False

                # BULLISH + LONG → Allow
                # NEUTRAL → Allow (fail-safe: don't block on errors)
                self.logger.info(
                    f"✅ BTC FILTER PASSED: {signal.symbol} {signal.signal_type.name} | "
                    f"BTC Trend: {btc_trend}"
                )
            except Exception as e:
                self.logger.error(f"❌ BTC Filter execution error: {e} - Allowing signal (fail-safe)")
                # Fail-safe: allow signal on error

        # SOTA (Jan 2026): LAYER 3 - Final safety check for SHORT signals in LIVE mode
        # SOTA (Feb 2026): SHORT Signals ENABLED for Shark Tank Mode
        # The blocking logic below is commented out to allow SHORT execution.
        # Logic verified in SHORT-Signal-Audit-Feb2026.md

        # if self.mode == TradingMode.LIVE and signal.signal_type == SignalType.SELL:
        #     self._blocked_short_signals += 1
        #     error_msg = (
        #         f"🚨 SHORT signal blocked at execution for {signal.symbol}! "
        #         f"(This is EXPECTED - SHORT signals occupy Shark Tank slots but don't fill) "
        #         f"(total_blocked={self._blocked_short_signals})"
        #     )
        #     self.logger.info(error_msg)  # Changed from critical to info
        #     return False  # Block execution

        # SOTA (Feb 9, 2026): Circuit Breaker check - block entry if symbol/side is blocked
        if hasattr(self, 'circuit_breaker') and self.circuit_breaker:
            cb_time = datetime.now(timezone.utc)
            signal_side = 'LONG' if signal.signal_type == SignalType.BUY else 'SHORT'

            # Check trading schedule (dead zone windows)
            is_in_deadzone, deadzone_reason = self.circuit_breaker.is_in_blocked_window(cb_time)
            if is_in_deadzone:
                self.logger.warning(
                    f"🛡️ CB SCHEDULE BLOCK: {signal.symbol} rejected — {deadzone_reason}"
                )
                try:
                    if self.telegram_service:
                        asyncio.create_task(self.telegram_service.send_message(
                            f"<b>[DEAD ZONE]</b> {signal.symbol} {signal_side}\n"
                            f"Reason: <code>{deadzone_reason}</code>\n"
                            f"Time: {cb_time.strftime('%H:%M:%S')} UTC", silent=True))
                except Exception:
                    pass
                return False

            # Check global block (portfolio drawdown)
            if self.circuit_breaker.global_blocked_until and cb_time < self.circuit_breaker.global_blocked_until:
                self.logger.warning(
                    f"🛡️ CB GLOBAL BLOCK: ALL trading halted until "
                    f"{self.circuit_breaker.global_blocked_until.strftime('%H:%M:%S')} "
                    f"(daily drawdown exceeded). Rejecting {signal.symbol}"
                )
                self._send_system_alert(
                    'CRITICAL', 'CircuitBreaker',
                    f"ALL trading HALTED — daily drawdown exceeded {self.circuit_breaker.max_daily_drawdown_pct*100:.0f}%",
                    {'blocked_symbol': signal.symbol, 'side': signal_side,
                     'until': self.circuit_breaker.global_blocked_until.strftime('%H:%M:%S') + ' UTC'}
                )
                return False

            # Check per-symbol + direction block (consecutive losses / daily limit)
            if self.circuit_breaker.is_blocked(signal.symbol.upper(), signal_side, cb_time):
                reason = self.circuit_breaker.get_block_reason(signal.symbol.upper(), signal_side, cb_time)
                self.logger.warning(
                    f"🛡️ CB SYMBOL BLOCK: {signal.symbol} {signal_side} blocked — {reason}"
                )
                try:
                    if self.telegram_service:
                        asyncio.create_task(self.telegram_service.send_message(
                            f"<b>[CB BLOCK]</b> {signal.symbol} {signal_side}\n"
                            f"Reason: <code>{reason}</code>\n"
                            f"Time: {cb_time.strftime('%H:%M:%S')} UTC", silent=True))
                except Exception:
                    pass
                return False

        # SOTA (Jan 2026): Use enable_trading flag directly
        # This is set at init from settings_repo and can be updated via API
        auto_execute = self.enable_trading

        self.logger.info(f"📨 execute_signal called: {signal.symbol} auto_execute={auto_execute}, self_id={id(self)}")

        if not auto_execute:
            # SOTA (Jan 2026): SAFE MODE SIGNAL QUEUING
            # Even if trading is disabled, we should still QUEUE signals in the Tracker.
            # They will be "Pending" but won't trigger MARKET orders until trading is enabled.
            # Exception: If "Kill Switch" is active (global disable), maybe reject?
            # For now, we allow queuing so user sees "Pending" signals in UI.
            self.logger.info(f"ℹ️ Safe Mode / Trading Disabled: Signal for {signal.symbol} will be QUEUED but not executed.")
            # Proceed to add to tracker...
            pass

        # Access signal_tracker property (triggers self-healing if needed)
        tracker = self.signal_tracker

        if tracker is None:
            self.logger.error(f"❌ Signal tracker FAILED to initialize! self_id={id(self)}")
            return False

        # Calculate position sizing
        settings = self.settings_repo.get_all_settings() if self.settings_repo else {}

        # SOTA (Jan 2026): Robust Casting & Error Handling
        try:
            leverage = float(settings.get('leverage', self.max_leverage))

            # Get cached balance for sizing
            # BUG FIX (Feb 2026): Use WALLET balance (total), NOT available balance
            # BT uses: base_balance (total) / max_positions → EQUAL slots
            # Old code used _cached_available which SHRINKS as positions open,
            # causing later positions to get geometrically smaller margins:
            #   Pos1: $11.33, Pos2: $9.06, Pos3: $7.25, Pos4: $5.80, Pos5: $4.64
            #   = only 67% of balance used (vs 100% in BT)
            wallet_balance = float(self._cached_balance or self._cached_available or 100.0)
            available_balance = float(self._cached_available or self._cached_balance or 100.0)
            balance = wallet_balance

            # SOTA SYNC (Jan 2026): Match Backtest Slot Allocation
            # Backtest uses: capital_per_slot = base_balance / max_positions
            # Then: allocated_capital = min(capital_per_slot, available)
            # This ensures each trade uses equal capital slots (institutional "Pod" management)

            capital_per_slot = balance / self.max_positions

            # Safety: Cap by available balance (match BT line 870)
            # Prevents over-allocation when balance is low
            capital_per_slot = min(capital_per_slot, available_balance)

            # SOTA FIX (Jan 2026): Min Notional Parity with Backtest
            # Binance min notional = ~$5. But min_margin = min_notional/leverage
            # With 20x: min_margin = $5/20 = $0.25, not $5.5!
            #
            # PARITY FIX: Match backtest behavior - SKIP signal if notional < $5
            # Previous logic was WRONG - it force scaled up, causing mismatch
            min_notional = 5.0  # Binance requirement
            calculated_notional = capital_per_slot * leverage

            if calculated_notional < min_notional:
                # SKIP signal (match backtest ExecutionSimulator line 365-367)
                self.logger.warning(
                    f"⚠️ Signal SKIPPED: {signal.symbol} | "
                    f"Notional ${calculated_notional:.2f} < ${min_notional} min | "
                    f"Matching backtest behavior"
                )
                return False

            # Calculate position value (notional)
            position_value = capital_per_slot * leverage

            # SOTA: Cap to $50k per position (Binance Tier 1 limit)
            position_value = min(position_value, 50000.0)

            quantity = position_value / float(signal.entry_price) if signal.entry_price > 0 else 0.0

            self.logger.info(
                f"📊 Sizing: wallet=${wallet_balance:.2f} | avail=${available_balance:.2f} | "
                f"slot=${capital_per_slot:.2f} | pos_val=${position_value:.2f} | qty={quantity:.6f}"
            )

        except (ValueError, TypeError) as e:
            self.logger.error(f"❌ Position sizing error: {e} (lev={settings.get('leverage')}, bal={self._cached_available})")
            return False

        # Determine direction
        direction = SignalDirection.LONG if signal.signal_type == SignalType.BUY else SignalDirection.SHORT

        # Add to LocalSignalTracker
        # SOTA (Jan 2026): Use correct TradingSignal attributes
        # - tp_levels is dict: {'tp1': price, 'tp2': price, ...}
        # - Use 'id' not 'signal_id'
        tp_price = 0.0
        if signal.tp_levels:
            tp_price = signal.tp_levels.get('tp1', 0.0) or 0.0

        success = self.signal_tracker.add_signal(
            symbol=signal.symbol.upper(),
            direction=direction,
            target_price=signal.entry_price,
            stop_loss=signal.stop_loss or 0.0,
            take_profit=tp_price,
            quantity=quantity,
            leverage=leverage,
            ttl_minutes=self.order_ttl_minutes,
            signal_id=signal.id,  # Use 'id' not 'signal_id'
            confidence=signal.confidence,
            # SOTA SYNC (Jan 2026): Pass ATR & tp_levels for backtest parity
            metadata={
                'atr': signal.indicators.get('atr', 0) if signal.indicators else 0,
                'tp_levels': signal.tp_levels or {},
                'initial_quantity': quantity  # For 60% partial close
            }
        )

        if success:
            self.logger.info(
                f"📥 Signal added to tracker: {signal.symbol} {direction.value} "
                f"@ ${signal.entry_price:.4f} (conf={signal.confidence:.2f})"
            )
        else:
            self.logger.warning(f"⚠️ Signal not added (duplicate or full?): {signal.symbol}")

        return success

    async def initialize_async(self) -> bool:
        """
        SOTA Lazy Initialization (Jan 2026): Initialize heavy dependencies.

        Call ONCE after event loop is running, e.g., in main.py lifespan.
        This avoids blocking during service creation.

        Returns:
            True if initialization successful
        """
        if self._initialized:
            return True

        if self.mode == TradingMode.PAPER:
            self._initialized = True
            return True

        try:
            self.logger.info("🔧 LiveTradingService async initialization starting...")

            # 1. Create filter service FIRST (fast, no network)
            from ...infrastructure.exchange.exchange_filter_service import ExchangeFilterService
            self.filter_service = ExchangeFilterService(use_testnet=self._use_testnet)

            # 2. Load filters from local cache (fast, non-blocking)
            self.logger.info("📡 Loading exchange filters from local cache...")
            self.filter_service.load_from_file()

            # 3. Create Binance clients and INJECT filter_service for dynamic precision
            # SOTA (Jan 2026): This eliminates need to manually add coin precision
            self.client = BinanceFuturesClient(
                use_testnet=self._use_testnet,
                filter_service=self.filter_service
            )

            from ...infrastructure.api.async_binance_client import AsyncBinanceFuturesClient
            self.async_client = AsyncBinanceFuturesClient(use_testnet=self._use_testnet)

            # Schedule API refresh in background (don't block startup)
            # SOTA FIX (Jan 2026): Use asyncio.to_thread for sync call
            async def refresh_filters_async():
                try:
                    if self.client:
                        await asyncio.to_thread(self.filter_service.load_filters, self.client)
                        self.logger.debug("📡 Exchange filters refreshed from API")
                except Exception as e:
                    self.logger.warning(f"⚠️ Filter refresh failed: {e}")
            asyncio.create_task(refresh_filters_async())

            # 4. Load intelligence service (from file, fast)
            if not self.intelligence_service:
                from ...infrastructure.exchange.market_intelligence_service import MarketIntelligenceService
                self.intelligence_service = MarketIntelligenceService()
                self.intelligence_service.load_from_file()

            # 5. Get initial balance - use async client (non-blocking)
            try:
                self.initial_balance = await self.async_client.get_usdt_balance()
                self.peak_balance = self.initial_balance
                self._cached_balance = self.initial_balance
                self._cached_available = self.initial_balance
            except Exception as e:
                self.logger.warning(f"⚠️ Initial balance fetch failed: {e}")
                self.initial_balance = 0.0

            # 6. Cache sync moved to after _setup_position_monitor (see below)
            # This ensures watermarks are loaded before _restore_position_monitoring

            self._initialized = True
            mode_str = "🧪 TESTNET" if self._use_testnet else "🔴 LIVE"
            self.logger.info(f"✅ {mode_str} LiveTradingService initialized | Balance: ${self.initial_balance:.2f}")

            # SOTA (Jan 2026): Wire SharedBinanceClient to PositionMonitor for trailing stop
            # This enables automatic trailing stop calculation for ALL open positions
            from ...infrastructure.websocket.shared_binance_client import get_shared_binance_client
            try:
                shared_client = get_shared_binance_client()
                self.position_monitor._shared_client = shared_client
                self.logger.info("📡 PositionMonitor connected to SharedBinanceClient for trailing stops")
            except Exception as e:
                self.logger.warning(f"⚠️ SharedBinanceClient not available: {e}")

            # SOTA Local-First (Jan 2026): Setup position monitor callbacks
            self._setup_position_monitor()

            # SOTA (Feb 2026): Register Candle Close Exit Callback
            # Replaces legacy auto-close logic with new "Close on Candle Close" strategy
            self.position_monitor.register_close_callback(self._check_candle_close_exit_adapter)

            # ═══════════════════════════════════════════════════════════════════
            # SOTA (Jan 2026): Initialize Priority Execution Queue and Worker
            # Pattern: NautilusTrader, Two Sigma, Citadel
            # Non-blocking TP/SL execution via background worker
            # ═══════════════════════════════════════════════════════════════════
            try:
                from ...infrastructure.execution.priority_execution_queue import PriorityExecutionQueue
                from ...infrastructure.execution.execution_worker import ExecutionWorker

                # Create queue with 100 capacity (~20x safety margin for 5 positions)
                self._execution_queue = PriorityExecutionQueue(max_size=100)

                # Create worker with callbacks to this service
                self._execution_worker = ExecutionWorker(
                    queue=self._execution_queue,
                    partial_close_callback=self.partial_close_position_async,
                    close_position_callback=self.close_position_async
                )

                # Start worker (background coroutine)
                await self._execution_worker.start()

                # Wire queue to PositionMonitorService
                self.position_monitor.set_execution_queue(self._execution_queue)

                self.logger.info(
                    "🚀 Priority Execution Queue initialized | "
                    f"Queue capacity: 100 | Worker: running"
                )
            except Exception as e:
                self.logger.warning(
                    f"⚠️ Priority Execution Queue init failed: {e}. "
                    f"Falling back to direct execution."
                )
                self._execution_queue = None
                self._execution_worker = None

            # SOTA FIX (Jan 2026): Sync cache BEFORE restoring position monitoring!
            # Race condition fix: _sync_local_cache populates watermarks from DB,
            # which _restore_position_monitoring needs for SL/TP values.
            try:
                await asyncio.to_thread(self._sync_local_cache)
                self.logger.info(f"📦 Cache synced: {len(self._position_watermarks)} watermarks loaded")
            except Exception as e:
                self.logger.warning(f"⚠️ Cache sync failed: {e}")

            # SOTA SAFETY (Jan 2026): Clear stale pending signals on restart
            # This prevents "Ghost Orders" from old sessions triggering unexpected trades
            # Pending signals are LOCAL only (not on exchange), so clearing them is safe.
            if self.signal_tracker:
                pending_count = len(self.signal_tracker.pending_signals)
                if pending_count > 0:
                    self.signal_tracker.pending_signals.clear()
                    self.logger.warning(
                        f"🧹 CLEARED {pending_count} stale pending signals (Safe Mode restart). "
                        f"Fresh signals will be generated by signal engine."
                    )

            # SOTA (Jan 2026): Restore monitoring for existing positions
            # This ensures trailing/SL/TP works for positions from DB
            self._restore_position_monitoring()

            # SOTA FIX (Jan 2026): Startup orphan cleanup
            # Cancel any orphan algo orders from previous sessions
            # This prevents zombie orders from affecting new positions
            try:
                cleanup_results = self._startup_orphan_cleanup()
                if cleanup_results['orphan_algo_cancelled'] > 0:
                    self.logger.info(
                        f"🧹 Startup cleanup: {cleanup_results['orphan_algo_cancelled']} orphan algo orders cancelled"
                    )
            except Exception as e:
                self.logger.warning(f"⚠️ Startup orphan cleanup failed: {e}")

            # SOTA (Feb 2026): Start daily summary scheduler
            try:
                self._daily_summary_task = asyncio.create_task(self._daily_summary_loop())
                self.logger.info("📊 Daily summary scheduler started (00:00 UTC+7)")
            except Exception as e:
                self.logger.warning(f"⚠️ Daily summary scheduler failed to start: {e}")

            # SOTA (Feb 2026): System startup alert
            self._send_system_alert(
                'INFO', 'LiveTradingService',
                f"System started successfully",
                {'mode': self.mode.value, 'balance': f"${self.initial_balance:.2f}",
                 'max_positions': self.max_positions, 'leverage': f"{self.max_leverage}x",
                 'auto_close': f"{self.profitable_threshold_pct}% ROE"}
            )

            return True

        except Exception as e:
            self.logger.error(f"❌ LiveTradingService initialization failed: {e}")
            self._send_system_alert(
                'CRITICAL', 'LiveTradingService',
                f"Initialization FAILED: {e}",
                {'mode': self.mode.value}
            )
            return False

    def _ensure_initialized(self):
        """Guard to ensure service is initialized before use."""
        if not self._initialized and self.mode != TradingMode.PAPER:
            self.logger.warning("⚠️ LiveTradingService not initialized - some features may fail")

    # =========================================================================
    # SOTA: LOCAL CACHE MANAGEMENT (Jan 2026)
    # Eliminates 3 API calls per get_portfolio() by caching locally
    # =========================================================================

    def _sync_local_cache(self):
        """
        SOTA: Initial sync of local cache from Binance.

        Called ONCE on startup. After this, cache is updated via:
        - User Data Stream WebSocket (ORDER_TRADE_UPDATE events)
        - _refresh_positions() during trading operations

        This reduces get_portfolio() from 3 API calls (450ms) to 0 API calls (<1ms).
        """
        if not self.client:
            return

        try:
            self.logger.info("📦 Syncing local cache from Binance...")

            # Fetch open orders (one-time)
            open_orders = self.client.get_open_orders()
            self._cached_open_orders = {}
            for o in open_orders:
                if isinstance(o, dict):
                    order_id = o.get('orderId', o.get('order_id', 0))
                    self._cached_open_orders[order_id] = o
                else:
                    self._cached_open_orders[o.order_id] = {
                        'orderId': o.order_id,
                        'symbol': o.symbol,
                        'side': o.side.value if hasattr(o.side, 'value') else o.side,
                        'type': o.type.value if hasattr(o.type, 'value') else o.type,
                        'status': o.status.value if hasattr(o.status, 'value') else o.status,
                        'price': o.price,
                        'origQty': o.quantity,
                        'executedQty': o.executed_qty,
                    }

            # Fetch positions (one-time)
            self._refresh_positions()
            self._cached_positions_list = list(self.active_positions.values())

            # SOTA Hybrid: Sync TP/SL from exchange orders for existing positions
            self._sync_position_states_from_exchange(open_orders)

            self._local_cache_initialized = True
            self.logger.info(f"📦 Local cache synced: {len(self._cached_open_orders)} orders, {len(self._cached_positions_list)} positions, {len(self._position_watermarks)} TP/SL")

        except Exception as e:
            self.logger.error(f"Failed to sync local cache: {e}")
            self._local_cache_initialized = False # Ensure we know cache is invalid

    # =========================================================================
    # BACKGROUND SYNC WORKER (SOTA)
    # Replaces usage of on-demand API calls for State Mirroring
    # =========================================================================

    async def start_background_sync(self):
        """Start background sync loop."""
        import asyncio
        if not self.client or self.mode == TradingMode.PAPER:
            return

        self._sync_task = asyncio.create_task(self._background_sync_loop())
        self.logger.info("🔄 Background Sync Worker started")

        # SOTA (Jan 2026): Start reconciliation loop for state drift detection
        await self.start_reconciliation_loop()


    async def stop(self):
        """Stop the service and cleanup resources."""
        # ═══════════════════════════════════════════════════════════════════
        # SOTA (Jan 2026): Stop ExecutionWorker first (graceful shutdown)
        # This ensures all pending TP/SL orders are processed before shutdown
        # ═══════════════════════════════════════════════════════════════════
        if self._execution_worker:
            try:
                self.logger.info("🛑 Stopping ExecutionWorker...")
                await self._execution_worker.stop()

                # Log final metrics
                if self._execution_queue:
                    metrics = self._execution_queue.get_metrics()
                    latency = self._execution_worker.get_latency_stats()
                    self.logger.info(
                        f"📊 ExecutionWorker final stats: "
                        f"processed={metrics['total_processed']}, "
                        f"avg_latency={latency['avg_latency_ms']:.1f}ms, "
                        f"max_latency={latency['max_latency_ms']:.1f}ms"
                    )
            except Exception as e:
                self.logger.error(f"❌ ExecutionWorker stop failed: {e}")

        # SOTA FIX (Jan 2026): Stop PositionMonitor
        if hasattr(self, 'position_monitor') and self.position_monitor:
            try:
                self.logger.info("🛑 Stopping PositionMonitor...")
                self.position_monitor.stop_all_monitoring()
            except Exception as e:
                self.logger.error(f"❌ PositionMonitor stop failed: {e}")

        # SOTA (Feb 2026): Stop Daily Summary loop
        if hasattr(self, '_daily_summary_task') and self._daily_summary_task:
            try:
                self.logger.info("🛑 Stopping Daily Summary loop...")
                self._daily_summary_task.cancel()
                try:
                    await self._daily_summary_task
                except asyncio.CancelledError:
                    pass
            except Exception as e:
                self.logger.debug(f"Daily summary stop: {e}")

        # SOTA FIX (Jan 2026): Stop User Data Stream
        if hasattr(self, '_user_data_stream_task') and self._user_data_stream_task:
            try:
                self.logger.info("🛑 Stopping User Data Stream...")
                self._user_data_stream_task.cancel()
                try:
                    await self._user_data_stream_task
                except asyncio.CancelledError:
                    pass
            except Exception as e:
                self.logger.error(f"❌ User Data Stream stop failed: {e}")

        # SOTA FIX (Jan 2026): Clear signal tracker
        if hasattr(self, 'signal_tracker') and self.signal_tracker:
            try:
                self.logger.info("🛑 Clearing signal tracker...")
                self.signal_tracker.pending_signals.clear()
            except Exception as e:
                self.logger.error(f"❌ Signal tracker clear failed: {e}")

        # SOTA FIX (Jan 2026): Persist final state to DB
        if hasattr(self, 'order_repo') and self.order_repo and hasattr(self, '_position_watermarks'):
            try:
                self.logger.info("🛑 Persisting final state to DB...")
                for symbol, wm in self._position_watermarks.items():
                    try:
                        self.order_repo.update_live_position_sl(symbol, wm.get('current_sl', 0))
                    except Exception as e:
                        self.logger.warning(f"⚠️ Failed to persist {symbol} state: {e}")
            except Exception as e:
                self.logger.error(f"❌ Final state persist failed: {e}")

        if hasattr(self, '_sync_task') and self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass

        # SOTA FIX (Jan 2026): Close async client
        if hasattr(self, 'async_client') and self.async_client:
            await self.async_client.close()
            self.logger.info("[OK] LiveTradingService Async Client closed")

        # SOTA (Jan 2026): Cancel reconciliation task
        if hasattr(self, '_reconciliation_task') and self._reconciliation_task:
            self._reconciliation_task.cancel()
            try:
                await self._reconciliation_task
            except asyncio.CancelledError:
                pass
            self.logger.info("[OK] Reconciliation loop stopped")

        # SOTA FIX (Jan 2026): Close sync client
        if hasattr(self, 'client') and self.client:
            self.client = None
            self.logger.info("[OK] LiveTradingService Sync Client closed")

    async def _background_sync_loop(self):
        """
        Periodically sync state with Binance (Balance, Positions).

        SOTA (v2 Async): Uses aiohttp via async_client to prevent GIL blocking.
        Freqtrade-style non-blocking loop.
        """
        import asyncio
        while True:
            try:
                if self.mode == TradingMode.TESTNET or self.mode == TradingMode.LIVE:
                    # Pure Async Call - No Threads!
                    await self._sync_local_cache_async()

            except Exception as e:
                self.logger.error(f"❌ Background sync failed: {e}")

            # Sync every 5 seconds (matching frontend poll rate)
            # NOTE: Do NOT reset _local_cache_initialized here!
            # Watermarks and position state must persist between syncs
            await asyncio.sleep(5)

    # ═══════════════════════════════════════════════════════════════════════════
    # SOTA (Jan 2026): Reconciliation Loop - Detect and Fix State Drift
    # Pattern: Two Sigma, Citadel - Periodic state verification with exchange
    # ═══════════════════════════════════════════════════════════════════════════

    RECONCILIATION_INTERVAL_SECONDS = 60  # 1 minute

    async def start_reconciliation_loop(self):
        """
        Start the reconciliation loop.

        SOTA (Jan 2026): Detects state drift between local cache and exchange.
        Runs every 60 seconds for minimal API overhead.
        """
        import asyncio
        if not self.async_client or self.mode == TradingMode.PAPER:
            return

        self._reconciliation_task = asyncio.create_task(self._reconciliation_loop())
        self.logger.info("🔄 Reconciliation Loop started (60s interval)")

    async def _reconciliation_loop(self):
        """
        ═══════════════════════════════════════════════════════════════════════════
        SOTA (Jan 2026): Periodic reconciliation to detect state drift.

        Problem this solves:
        - WebSocket may miss messages (network lag)
        - Manual closes on Binance app not detected
        - Partial fill delays causing stale local state

        Solution:
        - Every 60 seconds, compare local state vs exchange
        - Detect orphan local positions (exist locally but not on exchange)
        - Detect untracked positions (exist on exchange but not locally)
        - Auto-fix orphan local state (cleanup ghost positions)

        Pattern: Two Sigma, Citadel - "Trust but verify" periodic reconciliation
        ═══════════════════════════════════════════════════════════════════════════
        """
        import asyncio

        # Initial delay - let system stabilize after startup
        await asyncio.sleep(30)

        while True:
            try:
                await self._perform_reconciliation()
            except asyncio.CancelledError:
                self.logger.info("🔄 Reconciliation loop cancelled")
                break
            except Exception as e:
                self.logger.error(f"❌ Reconciliation loop error: {e}", exc_info=True)

            await asyncio.sleep(self.RECONCILIATION_INTERVAL_SECONDS)

    async def _perform_reconciliation(self):
        """
        SOTA (Jan 2026): Single reconciliation cycle.

        Steps:
        1. Get positions from exchange (async, non-blocking)
        2. Compare with local active_positions
        3. Detect orphan local (ghost positions)
        4. Detect untracked exchange positions
        5. Auto-cleanup ghost positions
        6. Alert on untracked positions (may need manual intervention)
        """
        if not self.async_client:
            return

        try:
            # Step 1: Get exchange positions (async)
            exchange_positions = await self.async_client.get_positions()

            # Filter to only open positions (positionAmt != 0)
            exchange_open = {
                p.get('symbol'): float(p.get('positionAmt', 0))
                for p in exchange_positions
                if float(p.get('positionAmt', 0)) != 0
            }
            exchange_symbols = set(exchange_open.keys())

            # Step 2: Get local positions
            local_symbols = set(self.active_positions.keys())

            # Step 3: Detect drift
            orphan_local = local_symbols - exchange_symbols  # Local có nhưng exchange không có
            untracked_exchange = exchange_symbols - local_symbols  # Exchange có nhưng không track

            # Step 4: Log reconciliation status
            if not orphan_local and not untracked_exchange:
                # No drift - quiet debug log
                self.logger.debug(
                    f"🔄 RECONCILIATION OK: {len(local_symbols)} local = {len(exchange_symbols)} exchange"
                )
                return

            # Step 5: Handle orphan local (ghost positions)
            if orphan_local:
                self.logger.warning(
                    f"🔄 RECONCILIATION DRIFT: {len(orphan_local)} ghost local positions: {orphan_local}"
                )

                for symbol in orphan_local:
                    self.logger.info(f"🔄 Cleaning up ghost position: {symbol}")

                    # Cleanup local state
                    if symbol in self.active_positions:
                        del self.active_positions[symbol]

                    if symbol in self._position_watermarks:
                        del self._position_watermarks[symbol]

                    if symbol in self._position_states:
                        del self._position_states[symbol]

                    # Stop monitoring if active
                    if hasattr(self, 'position_monitor') and self.position_monitor:
                        self.position_monitor.stop_monitoring(symbol)

                    # Remove from pending signals if exists
                    if hasattr(self, 'signal_tracker') and self._signal_tracker:
                        if symbol in self._signal_tracker.pending_signals:
                            del self._signal_tracker.pending_signals[symbol]

                    # Cleanup any orphan orders on exchange
                    try:
                        self._cleanup_all_orders_for_symbol(symbol, "RECONCILIATION")
                    except Exception as e:
                        self.logger.warning(f"⚠️ Orphan order cleanup failed for {symbol}: {e}")

                    self.logger.info(f"✅ Ghost position cleaned: {symbol}")

            # Step 6: Alert on untracked exchange positions
            if untracked_exchange:
                self.logger.warning(
                    f"🔄 RECONCILIATION ALERT: {len(untracked_exchange)} untracked exchange positions: {untracked_exchange}"
                )

                for symbol in untracked_exchange:
                    qty = exchange_open.get(symbol, 0)
                    self.logger.warning(
                        f"⚠️ UNTRACKED POSITION: {symbol} qty={qty:.6f} - "
                        f"May need manual intervention or will be picked up on next sync"
                    )

                    # SOTA: Try to auto-add to local cache on next sync
                    # This will be handled by _sync_local_cache_async()
                    # which runs every 5 seconds

            # Step 7: Log summary metrics
            self.logger.info(
                f"🔄 RECONCILIATION COMPLETE: "
                f"ghosts_cleaned={len(orphan_local)}, untracked_alerts={len(untracked_exchange)}"
            )

        except Exception as e:
            self.logger.error(f"❌ Reconciliation failed: {e}", exc_info=True)


    async def _cleanup_zombie_orders(self, symbol: str):
        """
        SOTA: Aggressively clean up ALL orders for a symbol.

        Called when a position is detected as CLOSED (manually or automatically).
        Prevents "Zombie Orders" (Orphaned SL/TP) from triggering later.

        CRITICAL: This must succeed to prevent old SL/TP from closing NEW positions!
        """
        symbol_upper = symbol.upper()
        self.logger.info(f"🧟 Starting zombie cleanup for {symbol_upper}...")

        try:
            # 1. Cancel all standard orders (LIMIT, MARKET)
            open_orders = await self.async_client.get_open_orders(symbol=symbol_upper)
            if open_orders:
                self.logger.info(f"🧟 Found {len(open_orders)} zombie standard orders for {symbol_upper}. Cancelling...")
                for o in open_orders:
                    try:
                        await self.async_client.cancel_order(symbol_upper, order_id=o['orderId'])
                        self.logger.info(f"   ✓ Cancelled standard order {o['orderId']}")
                    except Exception as e:
                        self.logger.warning(f"   ✗ Failed to cancel standard order {o['orderId']}: {e}")

            # 2. Cancel all Algo orders (STOP_MARKET, TAKE_PROFIT_MARKET)
            try:
                algo_response = await self.async_client.get_open_algo_orders(symbol=symbol_upper)

                # SOTA: Handle various response formats from Binance
                # Could be: list directly, or {"orders": [...]}
                algo_orders = []
                if isinstance(algo_response, list):
                    algo_orders = algo_response
                elif isinstance(algo_response, dict):
                    algo_orders = algo_response.get('orders', [])

                if algo_orders:
                    self.logger.info(f"🧟 Found {len(algo_orders)} zombie ALGO orders for {symbol_upper}. Cancelling...")
                    for ao in algo_orders:
                        try:
                            algo_id = ao.get('algoId') or ao.get('orderId')
                            if algo_id:
                                await self.async_client.cancel_algo_order(symbol_upper, algo_id=algo_id)
                                self.logger.info(f"   ✓ Cancelled algo order {algo_id}")
                        except Exception as e:
                            self.logger.warning(f"   ✗ Failed to cancel algo order: {e}")
                else:
                    self.logger.info(f"   No algo orders found for {symbol_upper}")

            except Exception as e:
                self.logger.warning(f"Failed to fetch/cancel algo orders for {symbol_upper}: {e}")

            # 3. Clean up internal state
            if symbol_upper in self._position_states:
                del self._position_states[symbol_upper]

            if symbol_upper in self._position_watermarks:
                del self._position_watermarks[symbol_upper]

            # Also clean LocalSignalTracker if exists
            if self.signal_tracker and symbol_upper in self.signal_tracker.pending_signals:
                del self.signal_tracker.pending_signals[symbol_upper]
                self.logger.info(f"   ✓ Removed pending signal for {symbol_upper}")

            self.logger.info(f"✅ Zombie cleanup complete for {symbol_upper}")

        except Exception as e:
            self.logger.error(f"❌ Error during zombie cleanup for {symbol_upper}: {e}")

    async def _refresh_positions_async(self):
        """Async version of _refresh_positions using aiohttp."""
        if not self.async_client:
            return

        # STEP 1: Get account info for balances
        account_info = await self.async_client.get_account_info()

        # Parse Balances from account_info
        # SOTA FIX (Jan 2026 - Bug #21): Thread-safe balance cache update
        for asset in account_info.get('assets', []):
            if asset['asset'] == 'USDT':
                with self._balance_lock:
                    self._cached_balance = float(asset['walletBalance'])
                    self._cached_available = float(asset['availableBalance'])

        # STEP 2: SOTA FIX - Get positions from /fapi/v2/positionRisk
        # This endpoint includes markPrice, isolatedMargin, etc. that /fapi/v3/account lacks
        position_risk_data = await self.async_client.get_positions()

        # SOTA (Jan 2026): Detect Closed Positions (Anti-Zombie Logic)
        # Capture old active symbols before updating
        old_active_symbols = set(self.active_positions.keys())

        # Parse Positions from positionRisk (has ALL fields)
        self.active_positions.clear()
        current_active_symbols = set()

        for pos_data in position_risk_data:
            amt = float(pos_data.get('positionAmt', 0))
            if amt != 0:
                symbol = pos_data['symbol']
                current_active_symbols.add(symbol)

                position = FuturesPosition(
                    symbol=symbol,
                    position_side=pos_data.get('positionSide', 'BOTH'),
                    position_amt=amt,
                    entry_price=float(pos_data.get('entryPrice', 0)),
                    unrealized_pnl=float(pos_data.get('unRealizedProfit', 0)),  # Note: camelCase differs
                    leverage=int(pos_data.get('leverage', 1)),
                    liquidation_price=float(pos_data.get('liquidationPrice', 0)),
                    margin_type=pos_data.get('marginType', 'isolated'),
                    mark_price=float(pos_data.get('markPrice', 0)),  # Available in positionRisk
                    margin=float(pos_data.get('isolatedMargin', 0)) or float(pos_data.get('initialMargin', 0))
                )
                self.active_positions[symbol] = position
                # self.logger.debug(f"📊 Position loaded: {symbol} entry=${position.entry_price:.2f} mark=${position.mark_price:.2f}")

        # Identify closed positions (in Old but not in New)
        closed_symbols = old_active_symbols - current_active_symbols

        # SOTA: Trigger cleanup for closed positions
        for symbol in closed_symbols:
            self.logger.info(f"🛡️ Position closed detected: {symbol}. Cleaning up zombie orders/state...")
            asyncio.create_task(self._cleanup_zombie_orders(symbol))

        # Update cached positions list
        self._cached_positions_list = list(self.active_positions.values())

        # Calculate used margin
        with self._balance_lock:
            self._used_margin = sum(p.margin for p in self.active_positions.values())

    async def _sync_local_cache_async(self):
        """SOTA Async Cache Sync (aiohttp)."""
        if not self.async_client:
            return

        try:
            # self.logger.debug("📦 Async Sync: Updating cache...")

            # 1. Update Positions & Balance (from Account Info)
            await self._refresh_positions_async()
            self._cached_positions_list = list(self.active_positions.values())

            # 2. Update Open Orders (TODO: Add async_client.get_open_orders if needed)
            # For now, we rely on WebSocket for orders, or keep sync call if infrequent.
            # Ideally: await self.async_client.get_open_orders()

            # ═══════════════════════════════════════════════════════════════════════
            # SOTA FIX (Jan 2026): Auto-register positions for monitoring
            #
            # ROOT CAUSE FIX: Previously, _restore_position_monitoring() was only
            # called in activate_trading(). This meant:
            # - If position existed BEFORE restart
            # - And user didn't click "Bắt Đầu Trade"
            # - Position was NOT monitored → SL/TP/AUTO_CLOSE callbacks FAILED
            #
            # Solution: Call _ensure_positions_monitored() after every position sync
            # This ensures ALL active positions are registered for monitoring.
            # ═══════════════════════════════════════════════════════════════════════
            if self._safe_mode_cleared or self.mode != TradingMode.LIVE:
                self._ensure_positions_monitored()

            self._local_cache_initialized = True

        except Exception as e:
            self.logger.error(f"Async Sync Failed: {e}")
            self._local_cache_initialized = False


    def update_cached_order(self, order_data: Dict, is_closed: bool = False):
        """
        SOTA: Update local order cache from WebSocket event.

        Called by UserDataStreamService when ORDER_TRADE_UPDATE or ALGO_UPDATE is received.
        This keeps local cache in sync without REST API calls.

        SOTA Hybrid (Jan 2026): Also handles OCO bracket cleanup for SL/TP orders.

        Args:
            order_data: Order data from WebSocket event
            is_closed: True if order is FILLED/CANCELED/EXPIRED
        """
        order_id = order_data.get('orderId', order_data.get('i', 0))
        symbol = order_data.get('symbol', order_data.get('s', '')).upper()
        status = order_data.get('status', order_data.get('X', ''))
        order_type = order_data.get('type', order_data.get('o', ''))
        is_algo = order_data.get('is_algo', False)
        algo_status = order_data.get('_algo_status', '')  # Raw Algo status from ALGO_UPDATE

        # SOTA: Determine true "closed" state (for Algo Orders, use terminal statuses)
        if is_algo and algo_status:
            is_closed = algo_status in ['TRIGGERED', 'FINISHED', 'CANCELED', 'REJECTED', 'EXPIRED']
        else:
            is_closed = is_closed or status in ['FILLED', 'CANCELED', 'EXPIRED', 'REJECTED']

        if is_closed:
            self._cached_open_orders.pop(order_id, None)
            self.logger.debug(f"📦 Cache: removed {'algo ' if is_algo else ''}order {order_id}")

            # SOTA Hybrid: When LIMIT entry order FILLED → Initialize position state
            if status == 'FILLED' and order_type == 'LIMIT':
                self._initialize_position_state_on_fill(symbol, order_data)

            # SOTA OCO (Jan 2026): When SL/TP Algo triggers/finishes → Cancel the other side
            # This prevents orphaned orders when one side of the bracket fills
            if is_algo and algo_status in ['TRIGGERED', 'FINISHED']:
                if order_type in ['STOP_MARKET', 'TAKE_PROFIT_MARKET']:
                    self.logger.info(f"🔗 OCO: {order_type} {algo_status} for {symbol}. Triggering bracket cleanup...")
                    # Fire-and-forget cleanup task
                    import asyncio
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(self._cleanup_zombie_orders(symbol))
                    except RuntimeError:
                        # No running loop, schedule for later
                        self.logger.warning(f"⚠️ Cannot create OCO cleanup task (no event loop), will cleanup on next sync")
        else:
            self._cached_open_orders[order_id] = order_data
            self.logger.debug(f"📦 Cache: updated {'algo ' if is_algo else ''}order {order_id}")

        # Invalidate portfolio cache to force refresh on next request
        self._portfolio_cache = None

    def _initialize_position_state_on_fill(self, symbol: str, order_data: Dict):
        """
        SOTA Hybrid: Initialize position tracking when entry order fills.

        This ensures TP/SL display shows correct values from the original signal.
        """
        # Get signal info from pending_orders (memory first, then DB fallback)
        pending_info = self.pending_orders.get(symbol.lower()) or self.pending_orders.get(symbol.upper())

        stop_loss = 0
        take_profit = 0
        db_fallback = False

        if pending_info:
            stop_loss = pending_info.stop_loss
            take_profit = pending_info.take_profit
        elif self.order_repo:
            # SOTA: Fallback to DB if memory pending_orders empty (after restart)
            db_pending = self.order_repo.get_pending_order_by_symbol(symbol)
            if db_pending:
                stop_loss = db_pending.get('stop_loss', 0) or 0
                take_profit = db_pending.get('take_profit', 0) or 0
                db_fallback = True
                self.logger.info(f"📊 Recovered TP/SL from DB: {symbol} SL=${stop_loss:.2f} TP=${take_profit:.2f}")

                # Update pending to open status
                self.order_repo.update_pending_to_open(
                    symbol=symbol,
                    entry_price=float(order_data.get('avgPrice', 0)) or float(order_data.get('price', 0)),
                    quantity=float(order_data.get('executedQty', 0)) or float(order_data.get('origQty', 0))
                )

        if stop_loss == 0 and take_profit == 0:
            self.logger.debug(f"📊 No pending info for {symbol} (memory or DB), skipping position state init")
            return

        # Extract fill info
        entry_price = float(order_data.get('avgPrice', 0)) or float(order_data.get('price', 0))
        quantity = float(order_data.get('executedQty', 0)) or float(order_data.get('origQty', 0))
        side = 'LONG' if order_data.get('side', '') == 'BUY' else 'SHORT'

        # Initialize PositionState
        self._position_states[symbol] = PositionState(
            symbol=symbol,
            entry_price=entry_price,
            quantity=quantity,
            side=side,
            leverage=self.max_leverage,
            initial_sl=stop_loss,
            current_sl=stop_loss,
            initial_tp=take_profit,
            current_tp=take_profit,
            highest_price=entry_price if side == 'LONG' else 0,
            lowest_price=entry_price if side == 'SHORT' else float('inf'),
            entry_time=datetime.now()
        )

        # Also update _position_watermarks for trailing logic compatibility
        # SOTA SYNC (Jan 2026): Added backtest-compatible fields for parity
        # with ExecutionSimulator._update_position_logic
        initial_risk = abs(entry_price - stop_loss) if stop_loss > 0 else entry_price * 0.005  # Fallback 0.5%

        # Get ATR from pending_info if available
        atr_value = 0.0
        tp_levels = {}
        initial_quantity = quantity  # Default: current quantity
        if pending_info:
            atr_value = getattr(pending_info, 'metadata', {}).get('atr', 0.0) if hasattr(pending_info, 'metadata') else 0.0
            tp_levels = getattr(pending_info, 'metadata', {}).get('tp_levels', {'tp1': take_profit}) if hasattr(pending_info, 'metadata') else {'tp1': take_profit}
            # SOTA SYNC (Jan 2026): Get initial_quantity for 60% close (matches backtest)
            initial_quantity = getattr(pending_info, 'metadata', {}).get('initial_quantity', quantity) if hasattr(pending_info, 'metadata') else quantity
        if not tp_levels:
            tp_levels = {'tp1': take_profit}  # Default TP1 = take_profit

        self._position_watermarks[symbol] = {
            # Original fields
            'highest': entry_price if side == 'LONG' else 0,
            'lowest': entry_price if side == 'SHORT' else float('inf'),
            'current_sl': stop_loss,
            'tp_target': take_profit,  # KEY: This makes TP visible in Portfolio

            # SOTA SYNC (Jan 2026): Backtest-compatible fields
            'entry_price': entry_price,                    # For breakeven calculation
            'initial_risk': initial_risk,                  # |entry - SL| for R:R breakeven
            'is_breakeven': False,                         # Flag: SL moved to entry
            'tp_hit_count': 0,                             # Counter: TP1 hit = 1 (for trailing)
            'atr': atr_value,                              # For ATR-based trailing
            'tp_levels': tp_levels,                        # Dict: {'tp1': x, 'tp2': y}
            'initial_size': initial_quantity,              # For 60% close (matches backtest initial_size * 0.6)
            'remaining_size': quantity,                    # Current remaining after partial closes
            'side': side                                   # LONG/SHORT for logic
        }

        # SOTA (Jan 2026): Persist to database for restart recovery
        if self.order_repo and not db_fallback:  # Skip if already loaded from DB
            try:
                self.order_repo.save_live_position(
                    symbol=symbol,
                    side=side,
                    entry_price=entry_price,
                    quantity=quantity,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    leverage=self.max_leverage,
                    signal_id=getattr(pending_info, 'signal_id', None) if pending_info else None
                )
                self.logger.info(f"💾 Saved to DB: {symbol} SL=${stop_loss:.2f} TP=${take_profit:.2f}")
            except Exception as e:
                self.logger.warning(f"⚠️ Failed to save position to DB: {e}")

        # SOTA FIX: Invalidate portfolio cache so next get_portfolio() returns fresh data
        if hasattr(self, '_portfolio_cache'):
            self._portfolio_cache = None
            self.logger.debug(f"🔄 Portfolio cache invalidated for fresh TP/SL data")

        source = "DB" if db_fallback else "memory"
        self.logger.info(f"📊 Position state initialized ({source}): {symbol} {side} @ ${entry_price:.2f} SL=${stop_loss:.2f} TP=${take_profit:.2f}")

    def _sync_position_states_from_exchange(self, open_orders: List):
        """
        SOTA Hybrid: Sync TP/SL from database + exchange for existing positions.

        Priority order:
        1. DATABASE (original signal SL/TP - persisted across restarts)
        2. EXCHANGE orders (STOP_MARKET, TAKE_PROFIT_MARKET if placed)
        3. Leave empty if no data (better than wrong guess)

        Args:
            open_orders: List of open orders from Binance
        """
        # STEP 1: PRIORITY 1 - Load from DATABASE FIRST (original signal values)
        # This ensures watermarks are created even if active_positions hasn't populated yet
        db_loaded_count = 0
        if self.order_repo:
            try:
                # Step 1a: Load OPEN positions from DB
                db_positions = self.order_repo.get_open_live_positions()
                self.logger.info(f"📊 [DB SYNC] Found {len(db_positions)} OPEN positions in DB")

                for db_pos in db_positions:
                    sym = db_pos.get('symbol', '').upper()
                    if not sym:
                        continue

                    db_sl = db_pos.get('stop_loss', 0) or 0
                    db_tp = db_pos.get('take_profit', 0) or 0

                    # SOTA FIX (Jan 2026): Load ALL fields for trailing stop state sync
                    # Required for correct trailing stop behavior after backend restart
                    db_atr = db_pos.get('atr', 0) or 0
                    db_tp_hit_count = db_pos.get('tp_hit_count', 0) or 0
                    db_phase = db_pos.get('phase', 'ENTRY') or 'ENTRY'
                    db_is_breakeven = bool(db_pos.get('is_breakeven', 0))
                    db_entry_price = db_pos.get('entry_price', 0) or 0
                    db_side = db_pos.get('side', 'LONG') or 'LONG'

                    # SOTA DEBUG (Jan 2026): Log exact values being loaded
                    self.logger.info(
                        f"📊 [DB SYNC] Processing {sym}: SL={db_sl:.4f}, TP={db_tp:.4f}, "
                        f"phase={db_phase}, tp_hit={db_tp_hit_count}, atr={db_atr:.6f}, is_be={db_is_breakeven}"
                    )

                    # Create watermark entry from DB if doesn't exist
                    if sym not in self._position_watermarks:
                        self._position_watermarks[sym] = {
                            'highest': db_pos.get('highest_price', 0) or db_entry_price,
                            'lowest': db_pos.get('lowest_price', float('inf')),
                            'current_sl': db_sl,
                            'tp_target': db_tp,
                            # SOTA FIX (Jan 2026): Include ALL fields for state restoration
                            'atr': db_atr,
                            'tp_hit_count': db_tp_hit_count,
                            'phase': db_phase,
                            'is_breakeven': db_is_breakeven,
                            'entry_price': db_entry_price,
                            'initial_risk': abs(db_entry_price - db_sl) if db_sl > 0 else 0,
                            'side': db_side
                        }
                        self.logger.info(
                            f"📊 [DB SYNC] Created watermark: {sym} SL={db_sl:.4f}, TP={db_tp:.4f}, "
                            f"phase={db_phase}, tp_hit={db_tp_hit_count}"
                        )
                    else:
                        # Update existing with DB values (DB has priority)
                        if db_sl > 0:
                            self._position_watermarks[sym]['current_sl'] = db_sl
                        if db_tp > 0:
                            self._position_watermarks[sym]['tp_target'] = db_tp
                        # SOTA FIX (Jan 2026): Always update state fields from DB
                        self._position_watermarks[sym]['atr'] = db_atr
                        self._position_watermarks[sym]['tp_hit_count'] = db_tp_hit_count
                        self._position_watermarks[sym]['phase'] = db_phase
                        self._position_watermarks[sym]['is_breakeven'] = db_is_breakeven
                        self._position_watermarks[sym]['entry_price'] = db_entry_price
                        self._position_watermarks[sym]['side'] = db_side
                        if db_sl > 0:
                            self._position_watermarks[sym]['initial_risk'] = abs(db_entry_price - db_sl)
                        self.logger.info(
                            f"📊 [DB SYNC] Updated watermark: {sym} SL={db_sl:.4f}, TP={db_tp:.4f}, "
                            f"phase={db_phase}, tp_hit={db_tp_hit_count}"
                        )

                    if db_sl > 0 or db_tp > 0:
                        db_loaded_count += 1
                        self.logger.info(f"📊 [DB SYNC] ✅ Loaded: {sym} SL=${db_sl:.2f}, TP=${db_tp:.2f}")

                # Step 1b: Load PENDING orders from DB (for restart recovery)
                db_pending = self.order_repo.get_pending_live_orders()
                self.logger.info(f"📊 Found {len(db_pending)} PENDING orders in DB")

                for pending in db_pending:
                    sym = pending.get('symbol', '').upper()
                    if not sym:
                        continue

                    pending_sl = pending.get('stop_loss', 0) or 0
                    pending_tp = pending.get('take_profit', 0) or 0

                    # Create watermark for pending (will be used when order fills)
                    if sym not in self._position_watermarks:
                        self._position_watermarks[sym] = {
                            'highest': pending.get('entry_price', 0),
                            'lowest': float('inf'),
                            'current_sl': pending_sl,
                            'tp_target': pending_tp
                        }
                    elif self._position_watermarks[sym]['current_sl'] == 0:
                        # Update if not already set
                        if pending_sl > 0:
                            self._position_watermarks[sym]['current_sl'] = pending_sl
                        if pending_tp > 0:
                            self._position_watermarks[sym]['tp_target'] = pending_tp

                    if pending_sl > 0 or pending_tp > 0:
                        db_loaded_count += 1
                        self.logger.info(f"📊 Loaded PENDING from DB: {sym} SL=${pending_sl:.2f}, TP=${pending_tp:.2f}")

            except Exception as e:
                self.logger.warning(f"⚠️ Failed to load from database: {e}")
                import traceback
                traceback.print_exc()

        # STEP 2: Create watermarks from active_positions if not already from DB
        for pos_symbol, position in self.active_positions.items():
            if pos_symbol not in self._position_watermarks:
                self._position_watermarks[pos_symbol] = {
                    'highest': position.entry_price if position.position_amt > 0 else 0,
                    'lowest': position.entry_price if position.position_amt < 0 else float('inf'),
                    'current_sl': 0,
                    'tp_target': 0
                }

        # STEP 3: PRIORITY 2 - Parse exchange orders for SL/TP (supplement)
        # SOTA DEBUG: Log all order types for diagnosis
        order_types_found = {}
        for o in open_orders:
            if isinstance(o, dict):
                ot = o.get('type', 'UNKNOWN')
            else:
                ot = o.type.value if hasattr(o.type, 'value') else str(o.type)
            order_types_found[ot] = order_types_found.get(ot, 0) + 1
        self.logger.info(f"📊 Exchange order types found: {order_types_found}")

        exchange_loaded_count = 0
        for o in open_orders:
            if isinstance(o, dict):
                sym = o.get('symbol', '')
                order_type = o.get('type', '')
                stop_price = float(o.get('stopPrice', 0))
            else:
                sym = o.symbol
                order_type = o.type.value if hasattr(o.type, 'value') else o.type
                stop_price = getattr(o, 'stop_price', 0) or 0

            if sym not in self._position_watermarks:
                continue

            # Only update if NOT already loaded from DB
            watermark = self._position_watermarks[sym]

            if order_type == 'STOP_MARKET' and (not watermark.get('current_sl') or watermark['current_sl'] == 0):
                self._position_watermarks[sym]['current_sl'] = stop_price
                exchange_loaded_count += 1
                self.logger.info(f"📊 Synced SL from exchange: {sym} ${stop_price:.2f}")  # Upgraded to info
            elif order_type == 'TAKE_PROFIT_MARKET' and (not watermark.get('tp_target') or watermark['tp_target'] == 0):
                self._position_watermarks[sym]['tp_target'] = stop_price
                exchange_loaded_count += 1
                self.logger.info(f"📊 Synced TP from exchange: {sym} ${stop_price:.2f}")  # Upgraded to info

        # Log summary
        total_positions = len(self.active_positions)
        total_with_tpsl = sum(1 for w in self._position_watermarks.values() if w.get('current_sl', 0) > 0 or w.get('tp_target', 0) > 0)

        self.logger.info(f"📊 TP/SL sync complete: {total_with_tpsl}/{total_positions} positions | DB={db_loaded_count}, Exchange={exchange_loaded_count}")

        # SOTA DEBUG: Log watermark state for each position
        for sym, wm in list(self._position_watermarks.items()):
            sl = wm.get('current_sl', 0)
            tp = wm.get('tp_target', 0)
            status = "✓" if (sl > 0 or tp > 0) else "❌ ORPHAN"
            self.logger.info(f"  {sym}: SL=${sl:.2f}, TP=${tp:.2f} {status}")

        # ============================================================
        # SOTA FIX (Jan 2026): STALE WATERMARK CLEANUP
        # Remove watermarks loaded from DB if exchange has no matching position
        # This prevents ghost position tracking after manual closes or missed events
        # ============================================================
        stale_watermarks = []
        exchange_symbols = set(self.active_positions.keys())  # Symbols with real positions

        for sym in list(self._position_watermarks.keys()):
            if sym not in exchange_symbols:
                stale_watermarks.append(sym)

        if stale_watermarks:
            self.logger.warning(
                f"🧹 STALE CLEANUP: Removing {len(stale_watermarks)} watermarks with no exchange position: "
                f"{stale_watermarks[:5]}{'...' if len(stale_watermarks) > 5 else ''}"
            )
            # SOTA FIX (Jan 2026 - Bug #23): Comprehensive cleanup of all related state
            for sym in stale_watermarks:
                # 1. Remove watermark
                del self._position_watermarks[sym]

                # 2. Remove position state
                if sym in self._position_states:
                    del self._position_states[sym]
                    self.logger.debug(f"   ✓ Removed position state: {sym}")

                # 3. Remove pending order (check both upper and lower case)
                sym_lower = sym.lower()
                sym_upper = sym.upper()
                if sym_lower in self.pending_orders:
                    del self.pending_orders[sym_lower]
                    self.logger.debug(f"   ✓ Removed pending order: {sym}")
                elif sym_upper in self.pending_orders:
                    del self.pending_orders[sym_upper]
                    self.logger.debug(f"   ✓ Removed pending order: {sym}")

                # 4. Remove from signal tracker
                if self.signal_tracker:
                    if sym in self.signal_tracker.pending_signals:
                        del self.signal_tracker.pending_signals[sym]
                        self.logger.debug(f"   ✓ Removed pending signal: {sym}")
                    elif sym_lower in self.signal_tracker.pending_signals:
                        del self.signal_tracker.pending_signals[sym_lower]
                        self.logger.debug(f"   ✓ Removed pending signal: {sym}")

                # 5. Clean from DB (mark as GHOST_CLOSED so they don't reload on restart)
                if self.order_repo:
                    try:
                        self.order_repo.remove_stale_watermark(sym)
                        self.logger.info(f"   ✓ DB ghost closed: {sym}")
                    except Exception as e:
                        self.logger.warning(f"⚠️ Watermark DB cleanup failed for {sym}: {e}")

        if total_with_tpsl < total_positions:
            missing = total_positions - total_with_tpsl
            self.logger.warning(f"⚠️ {missing} position(s) have no TP/SL data. These were opened before bot started OR testnet doesn't return STOP_MARKET orders.")

    def refresh_cached_positions(self):
        """
        SOTA: Refresh position cache.
        Called after trades or when ACCOUNT_UPDATE is received.
        """
        if self.client:
            self._refresh_positions()
            self._cached_positions_list = list(self.active_positions.values())
            # Invalidate portfolio cache
            self._portfolio_cache = None

    # =========================================================================
    # SIGNAL EXECUTION
    # =========================================================================

    def _try_limit_gtx_order(
        self, symbol: str, side: OrderSide, quantity: float,
        price: float, reduce_only: bool = False
    ) -> Optional[FuturesOrder]:
        """
        v6.6.0: Try LIMIT+GTX (Post-Only) order with sync poll in a WORKER THREAD.

        CRITICAL: Runs in a separate thread via concurrent.futures to avoid blocking
        the asyncio event loop. Without this, SL/TP monitoring freezes for 5s during poll.

        Institutional pattern (Jump Trading, Wintermute):
        1. Place GTX at trigger price -> guaranteed maker fee (0.02%)
        2. If rejected (price crosses book) -> return None -> caller uses MARKET
        3. If placed -> poll every 500ms for up to 5s (in worker thread)
        4. If not filled -> cancel + return None -> caller uses MARKET

        Returns:
            FuturesOrder if filled (maker fee achieved), None if failed/timeout
        """
        # Submit to thread pool so time.sleep() doesn't block event loop
        future = self._gtx_thread_pool.submit(
            self._try_limit_gtx_order_sync, symbol, side, quantity, price, reduce_only
        )
        try:
            return future.result(timeout=10)  # 10s hard timeout (5s poll + margin)
        except Exception as e:
            self.logger.warning(f"GTX thread error: {e} -> MARKET fallback")
            self._limit_stats['error'] += 1
            self._limit_stats['fallback'] += 1
            return None

    def _try_limit_gtx_order_sync(
        self, symbol: str, side: OrderSide, quantity: float,
        price: float, reduce_only: bool = False
    ) -> Optional[FuturesOrder]:
        """Internal sync implementation — safe to call from worker thread."""
        symbol_upper = symbol.upper()
        self._limit_stats['attempted'] += 1

        # v6.6.1: Use best bid/ask for GTX price (fixes 1% fill rate)
        # BUY → post at best_bid (passive side), SELL → post at best_ask
        # This prevents -5022 rejection (price crossing book)
        limit_price = price
        try:
            bid, ask = self.client.get_book_ticker(symbol_upper)
            if side == OrderSide.BUY:
                limit_price = bid
            else:
                limit_price = ask
            self.logger.debug(
                f"GTX bid/ask: {symbol_upper} bid=${bid:.4f} ask=${ask:.4f} "
                f"-> using {'bid' if side == OrderSide.BUY else 'ask'} ${limit_price:.4f}"
            )
        except Exception as e:
            if price <= 0:
                self.logger.warning(f"GTX book_ticker failed and no fallback price: {e} -> MARKET fallback")
                self._limit_stats['error'] += 1
                self._limit_stats['fallback'] += 1
                return None
            self.logger.debug(f"GTX book_ticker failed: {e}, using fallback price=${price:.4f}")

        # Sanitize price to tick size
        if self.filter_service:
            limit_price = self.filter_service.sanitize_price(symbol_upper, limit_price)

        # Step 1: Place GTX (Post-Only) LIMIT order
        try:
            order = self.client.create_order(
                symbol=symbol_upper,
                side=side,
                order_type=OrderType.LIMIT,
                quantity=quantity,
                price=limit_price,
                time_in_force=TimeInForce.GTX,
                reduce_only=reduce_only
            )
        except Exception as e:
            error_msg = str(e)
            # GTX rejection: -5022 "Order would immediately match and trade"
            if '-5022' in error_msg or 'would immediately' in error_msg.lower():
                self.logger.info(
                    f"GTX REJECTED: {symbol_upper} {side.value} @ ${limit_price:.4f} "
                    f"(crosses book) -> MARKET fallback"
                )
                self._limit_stats['rejected'] += 1
            else:
                self.logger.warning(f"GTX ORDER ERROR: {symbol_upper}: {e} -> MARKET fallback")
                self._limit_stats['error'] += 1
            self._limit_stats['fallback'] += 1
            return None

        # Step 2: Check immediate fill
        if hasattr(order, 'status') and order.status == 'FILLED':
            self.logger.info(
                f"GTX FILLED INSTANTLY: {symbol_upper} {side.value} "
                f"@ ${order.avg_price:.4f} (MAKER FEE 0.02%)"
            )
            self._limit_stats['filled'] += 1
            return order

        # Step 3: Sync poll (500ms intervals, max 5s)
        order_id = order.order_id
        poll_max_seconds = min(self.limit_chase_timeout_seconds, 5)
        poll_count = poll_max_seconds * 2  # 500ms intervals

        for i in range(poll_count):
            time.sleep(0.5)
            try:
                status_data = self.client.get_order(symbol_upper, order_id)
                order_status = status_data.get('status', '') if isinstance(status_data, dict) else ''

                if order_status == 'FILLED':
                    avg_price = float(status_data.get('avgPrice', 0))
                    self.logger.info(
                        f"GTX FILLED ({(i+1)*0.5:.1f}s): {symbol_upper} {side.value} "
                        f"@ ${avg_price:.4f} (MAKER FEE 0.02%)"
                    )
                    order.status = 'FILLED'
                    order.avg_price = avg_price
                    order.executed_qty = float(status_data.get('executedQty', quantity))
                    self._limit_stats['filled'] += 1
                    return order

                elif order_status in ('CANCELLED', 'EXPIRED', 'REJECTED'):
                    self.logger.info(f"GTX {order_status}: {symbol_upper} -> MARKET fallback")
                    self._limit_stats['rejected'] += 1
                    self._limit_stats['fallback'] += 1
                    return None

            except Exception as poll_err:
                self.logger.debug(f"GTX poll error (non-fatal): {poll_err}")

        # Step 4: Timeout — cancel and check for partial fills
        filled_qty = 0.0
        try:
            self.client.cancel_order(symbol_upper, order_id)
            # Check if partially filled before cancel completed
            try:
                status_data = self.client.get_order(symbol_upper, order_id)
                if isinstance(status_data, dict):
                    filled_qty = float(status_data.get('executedQty', 0))
                    if status_data.get('status') == 'FILLED':
                        order.status = 'FILLED'
                        order.avg_price = float(status_data.get('avgPrice', 0))
                        order.executed_qty = filled_qty
                        self.logger.info(f"GTX FILLED (race with cancel): {symbol_upper}")
                        self._limit_stats['filled'] += 1
                        return order
            except Exception:
                pass
            self.logger.info(
                f"GTX TIMEOUT ({poll_max_seconds}s): {symbol_upper} {side.value} "
                f"@ ${limit_price:.4f} -> cancelled (partial_fill={filled_qty}) -> MARKET fallback"
            )
            self._limit_stats['timeout'] += 1
        except Exception as cancel_err:
            # Cancel might fail if order filled between last poll and cancel
            try:
                status_data = self.client.get_order(symbol_upper, order_id)
                if isinstance(status_data, dict) and status_data.get('status') == 'FILLED':
                    order.status = 'FILLED'
                    order.avg_price = float(status_data.get('avgPrice', 0))
                    order.executed_qty = float(status_data.get('executedQty', quantity))
                    self.logger.info(f"GTX FILLED (during cancel): {symbol_upper}")
                    self._limit_stats['filled'] += 1
                    return order
                filled_qty = float(status_data.get('executedQty', 0)) if isinstance(status_data, dict) else 0
            except Exception:
                pass
            self.logger.warning(f"GTX CANCEL FAILED: {symbol_upper}: {cancel_err}")

        # Return partial fill info so caller can adjust MARKET quantity
        if filled_qty > 0:
            order.status = 'PARTIALLY_FILLED'
            order.executed_qty = filled_qty
            self._limit_stats['fallback'] += 1
            return order  # Caller checks status != 'FILLED' and adjusts qty

        self._limit_stats['fallback'] += 1
        return None

    def _execute_triggered_signal(self, signal: PendingSignal, current_price: float) -> bool:
        """
        SOTA Callback: Execute MARKET order when LocalSignalTracker triggers.

        SOTA FIX (Jan 2026 - Bug #5): Added retry logic for transient failures.
        Network glitches or rate limits no longer cause signal loss.

        Called by LocalSignalTracker.on_price_update() when price hits target.
        This is the institutional pattern: local tracking → market execution.

        Args:
            signal: The PendingSignal that triggered
            current_price: Current market price that triggered the signal

        Returns:
            True if execution successful, False otherwise
        """
        self.logger.info(
            f"🎯 TRIGGERED: {signal.direction.value} {signal.symbol} "
            f"target=${signal.target_price:.4f} actual=${current_price:.4f}"
        )

        # ═══════════════════════════════════════════════════════════════════════
        # SOTA (Feb 9, 2026): Dead Zone + CB check at EXECUTION TIME
        # Signal may have been queued BEFORE dead zone started (e.g., 08:55).
        # When price triggers at 09:15 (inside dead zone), we MUST block here.
        # This is the LAST GATE before money leaves the account.
        # ═══════════════════════════════════════════════════════════════════════
        if hasattr(self, 'circuit_breaker') and self.circuit_breaker:
            cb_time = datetime.now(timezone.utc)
            signal_side = 'LONG' if signal.direction == SignalDirection.LONG else 'SHORT'

            # Dead Zone check
            is_in_deadzone, deadzone_reason = self.circuit_breaker.is_in_blocked_window(cb_time)
            if is_in_deadzone:
                self.logger.warning(
                    f"🛡️ CB DEAD ZONE (execution gate): {signal.symbol} {signal_side} "
                    f"triggered at ${current_price:.4f} but BLOCKED — {deadzone_reason}"
                )
                try:
                    if self.telegram_service:
                        asyncio.create_task(self.telegram_service.send_message(
                            f"<b>[DEAD ZONE]</b> {signal.symbol} {signal_side} (trigger gate)\n"
                            f"Price: <code>${current_price:.4f}</code>\n"
                            f"Reason: <code>{deadzone_reason}</code>", silent=True))
                except Exception:
                    pass
                return False

            # Per-symbol direction CB check
            if self.circuit_breaker.is_blocked(signal.symbol.upper(), signal_side, cb_time):
                reason = self.circuit_breaker.get_block_reason(signal.symbol.upper(), signal_side, cb_time)
                self.logger.warning(
                    f"🛡️ CB SYMBOL (execution gate): {signal.symbol} {signal_side} "
                    f"triggered at ${current_price:.4f} but BLOCKED — {reason}"
                )
                try:
                    if self.telegram_service:
                        asyncio.create_task(self.telegram_service.send_message(
                            f"<b>[CB BLOCK]</b> {signal.symbol} {signal_side} (trigger gate)\n"
                            f"Price: <code>${current_price:.4f}</code>\n"
                            f"Reason: <code>{reason}</code>", silent=True))
                except Exception:
                    pass
                return False

        # SOTA EMS GUARD (Jan 2026): Safe Mode Enforcement
        # This is the FINAL CHECK before money leaves the account.
        # If trading is disabled (Safe Mode), we catch the triggered signal here and ABORT.
        # This allows signals to sit in "Pending" (OMS) but blocks "Execution" (EMS).
        if not self.enable_trading:
            self.logger.info(
                f"🛡️ SAFE MODE BLOCKED EXECUTION: {signal.symbol} triggered at ${current_price:.4f}, "
                f"but trading is disabled. Signal remains Pending/Queued."
            )
            return False

        # SOTA (Feb 2026): SHORT Direction Check (allow_shorts=True → pass through)
        if not self.allow_shorts and signal.direction == SignalDirection.SHORT:
            self.logger.info(
                f"🚫 BLOCKED SHORT: {signal.symbol} triggered at ${current_price:.4f}, "
                f"but Allow Shorts = False. Skipping."
            )
            return False

        # ═══════════════════════════════════════════════════════════════════════
        # SOTA (Jan 2026): MAX SL Validation - Reject signals with SL too far
        # Sync with Backtest ExecutionSimulator.place_order() logic
        # Formula: max_sl = max_sl_pct or (10% / leverage)
        # ═══════════════════════════════════════════════════════════════════════
        if self.use_max_sl_validation and signal.stop_loss > 0 and signal.target_price > 0:
            # Calculate SL distance percentage
            sl_dist_pct = abs(signal.target_price - signal.stop_loss) / signal.target_price

            # Calculate max allowed SL distance
            if self.max_sl_pct is not None:
                max_sl_dist = self.max_sl_pct / 100.0
            else:
                max_sl_dist = 0.10 / self.max_leverage if self.max_leverage > 0 else 0.02

            if sl_dist_pct > max_sl_dist * 1.001:  # SOTA FIX (Feb 2026): 0.1% tolerance for float precision
                self._max_sl_rejected += 1
                self.logger.warning(
                    f"🚫 MAX SL VALIDATION: {signal.symbol} rejected! "
                    f"SL distance {sl_dist_pct:.2%} > max {max_sl_dist:.2%} for {self.max_leverage}x. "
                    f"Total rejected: {self._max_sl_rejected}"
                )
                return False

        # SOTA SAFETY GUARD (Jan 2026): Prevent Immediate Stop Out
        # If current price has already blown through the SL level, DO NOT EXECUTE.
        # This prevents the "Entry -> Instant SL loop" that drains accounts.
        #
        # Logic:
        # LONG: If Price <= SL -> ABORT
        # SHORT: If Price >= SL -> ABORT
        if signal.stop_loss > 0:
            if signal.direction == SignalDirection.LONG and current_price <= signal.stop_loss:
                self.logger.warning(
                    f"💀 DANGER: LONG signal invalidated! Price ${current_price:.4f} <= SL ${signal.stop_loss:.4f}. "
                    f"Skipping execution to avoid instant loss."
                )
                return False
            elif signal.direction == SignalDirection.SHORT and current_price >= signal.stop_loss:
                self.logger.warning(
                    f"💀 DANGER: SHORT signal invalidated! Price ${current_price:.4f} >= SL ${signal.stop_loss:.4f}. "
                    f"Skipping execution to avoid instant loss."
                )
                return False

        # BroSubSoul Failsafe: Block new entries if guardian heartbeat is missing,
        # invalid, unreadable, or stale beyond the allowed window.
        heartbeat_ok, heartbeat_reason = self._is_bro_heartbeat_healthy()
        if not heartbeat_ok:
            self.logger.warning(
                f"⚠️ BRO SUBSOUL HEARTBEAT UNHEALTHY: {heartbeat_reason}. "
                f"Blocking new entry for {signal.symbol}."
            )
            return False

        # SOTA LIMIT GUARD (Jan 2026): Strict Max Position Check
        # v6.6.0 FIX (L4): Include pending LIMIT entries to prevent race condition
        # Without this, concurrent LIMIT orders could exceed max_positions
        current_positions = len(self.active_positions) + len(self._pending_entry_symbols)
        if current_positions >= self.max_positions:
            self.logger.warning(
                f"🚫 MAX POSITIONS REACHED ({current_positions}/{self.max_positions}, "
                f"pending={len(self._pending_entry_symbols)}). "
                f"Skipping execution for {signal.symbol}."
            )
            return False

        if not self.client:
            self.logger.error("No client available for execution")
            return False

        # ═══════════════════════════════════════════════════════════════════════
        # SOTA FIX (Jan 2026 - Bug #5): Retry Logic for Transient Failures
        #
        # Problem: Network glitch or rate limit → Signal lost forever
        # Solution: Retry up to 3 times with exponential backoff
        #
        # Retry scenarios:
        # - Network timeout
        # - Binance rate limit (418)
        # - Temporary API errors (5xx)
        # ═══════════════════════════════════════════════════════════════════════

        MAX_RETRIES = 3
        RETRY_DELAYS = [1, 2, 4]  # Exponential backoff: 1s, 2s, 4s

        order = None
        last_error = None

        for attempt in range(MAX_RETRIES):
            try:
                # Determine side
                side = OrderSide.BUY if signal.direction == SignalDirection.LONG else OrderSide.SELL

                # SOTA SYNC (Jan 2026): Set ISOLATED margin and leverage BEFORE placing order
                # This matches backtest config: --leverage 20 + isolated margin mode
                if attempt == 0:  # Only set once on first attempt
                    try:
                        # Get leverage from settings or use default
                        leverage = self.max_leverage  # From settings (default 20)

                        # Set leverage for this symbol
                        self.client.set_leverage(symbol=signal.symbol, leverage=leverage)
                        self.logger.info(f"⚙️ Leverage set: {signal.symbol} = {leverage}x")

                        # Set margin type to ISOLATED (safer than CROSS for individual positions)
                        self.client.set_margin_type(symbol=signal.symbol, margin_type="ISOLATED")
                        self.logger.info(f"⚙️ Margin type set: {signal.symbol} = ISOLATED")
                    except Exception as e:
                        # Don't fail the trade if leverage/margin already set (Binance returns error)
                        # Error -4046: "No need to change margin type."
                        msg = str(e)
                        if "No need to change" in msg or "-4046" in msg:
                            self.logger.info(f"ℹ️ {signal.symbol}: Margin type already ISOLATED")
                        elif "-4028" in msg or "not valid" in msg.lower():
                            # SOTA FIX (Jan 2026): Better logging for leverage validation
                            # When leverage setup fails, Binance uses EXISTING leverage (e.g. 10x for BTRUSDT)
                            # This is SAFE: Lower leverage = More margin = Less liquidation risk
                            self.logger.warning(
                                f"⚠️ {signal.symbol}: Cannot set {leverage}x leverage (max likely 10-15x). "
                                f"Using existing leverage. Position will use MORE margin = SAFER. "
                                f"Binance error: {e}"
                            )
                        else:
                            self.logger.warning(f"⚠️ Leverage/margin setup warning: {e}")

                # v6.6.0: LIMIT+GTX entry (maker fee 0.02%) with MARKET fallback
                # Also handles partial fills (L3 fix) and pending entry guard (L4 fix)
                # L4 fix: Mark symbol as pending to prevent concurrent entries exceeding max_positions
                self._pending_entry_symbols.add(signal.symbol)
                order = None
                remaining_qty = signal.quantity
                if self.order_type == 'LIMIT':
                    order = self._try_limit_gtx_order(
                        symbol=signal.symbol,
                        side=side,
                        quantity=signal.quantity,
                        price=current_price,
                        reduce_only=False
                    )
                    # L3 fix: Handle partial fill — only MARKET the remainder
                    if order and hasattr(order, 'status') and order.status == 'PARTIALLY_FILLED':
                        partial_qty = order.executed_qty
                        remaining_qty = signal.quantity - partial_qty
                        self.logger.info(
                            f"GTX PARTIAL: {signal.symbol} filled {partial_qty}, "
                            f"remaining {remaining_qty} -> MARKET"
                        )
                        order = None  # Force MARKET fallback for remainder

                if order is None:
                    # MARKET fallback (default, or GTX failed/timeout/partial)
                    order = self.client.create_order(
                        symbol=signal.symbol,
                        side=side,
                        order_type=OrderType.MARKET,
                        quantity=remaining_qty
                    )

                # SOTA (Jan 2026): Create LOCAL position tracker immediately
                # Capture intended leverage and side for accurate PnL tracking
                # SOTA FIX (Feb 2026): Thread-safe with RLock
                try:
                    local_pos = LocalPosition(
                        symbol=signal.symbol,
                        side=signal.direction.value,  # SOTA FIX: Use .direction enum
                        intended_leverage=leverage,
                        signal_id=getattr(signal, 'signal_id', None),
                        # v5.5.0: Signal metadata for comprehensive CSV
                        signal_confidence=getattr(signal, 'confidence', 0.0),
                        signal_entry_target=signal.target_price,
                        signal_sl=signal.stop_loss,
                        signal_tp1=signal.take_profit,
                        signal_time=getattr(signal, 'created_at', datetime.now()).isoformat(),
                    )
                    with self._local_positions_lock:
                        self._local_positions[signal.symbol] = local_pos
                    self.logger.info(
                        f"📊 LOCAL position tracker created: {signal.symbol} | "
                        f"Side: {local_pos.side} | Intended Leverage: {leverage}x"
                    )
                except Exception as e:
                    self.logger.error(f"❌ Failed to create LocalPosition tracker: {e}")

                if order:
                    # Success! Break retry loop
                    self.logger.info(
                        f"✅ MARKET FILLED: {side.value} {signal.symbol} "
                        f"qty={signal.quantity} @ ${current_price:.4f}"
                        + (f" (attempt {attempt + 1}/{MAX_RETRIES})" if attempt > 0 else "")
                    )
                    break
                else:
                    # Order returned None - retry
                    last_error = "Order returned None"
                    if attempt < MAX_RETRIES - 1:
                        delay = RETRY_DELAYS[attempt]
                        self.logger.warning(
                            f"⚠️ MARKET order returned None for {signal.symbol}. "
                            f"Retrying in {delay}s... (attempt {attempt + 1}/{MAX_RETRIES})"
                        )
                        import time
                        time.sleep(delay)
                    else:
                        self.logger.error(f"❌ MARKET order failed after {MAX_RETRIES} attempts: {signal.symbol}")
                        self._pending_entry_symbols.discard(signal.symbol)
                        return False

            except Exception as e:
                last_error = str(e)
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAYS[attempt]
                    self.logger.warning(
                        f"⚠️ Execute attempt {attempt + 1} failed: {e}. "
                        f"Retrying in {delay}s..."
                    )
                    import time
                    time.sleep(delay)
                else:
                    self.logger.error(
                        f"❌ Execute triggered signal failed after {MAX_RETRIES} attempts: {e}"
                    )
                    self._pending_entry_symbols.discard(signal.symbol)
                    return False

        # v6.6.0 L4 fix: Remove from pending entries regardless of outcome
        self._pending_entry_symbols.discard(signal.symbol)

        # Check if we got an order after retries
        if not order:
            self.logger.error(
                f"❌ Failed to execute {signal.symbol} after {MAX_RETRIES} attempts. "
                f"Last error: {last_error}"
            )
            return False

        # ═══════════════════════════════════════════════════════════════════════
        # SOTA LOCAL-FIRST PATTERN (Jan 2026): Only place backup SL on exchange
        # True SL/TP/Trailing managed locally by PositionMonitorService
        #
        # Benefits:
        # 1. Single order per position (vs 2-3 before)
        # 2. No API calls for trailing (pure local)
        # 3. Hidden true SL/TP from exchange (anti-stop-hunting)
        # 4. Matches Two Sigma, Citadel institutional patterns
        # ═══════════════════════════════════════════════════════════════════════

        position_side = 'LONG' if signal.direction.value.upper() == 'LONG' else 'SHORT'
        atr_value = signal.metadata.get('atr', 0) if hasattr(signal, 'metadata') else 0

        # ═══════════════════════════════════════════════════════════════════════
        # SOTA FIX (Jan 2026): Use signal SL directly BUT enforce minimum buffer
        # Problem: Some signals might have SL extremely close to Entry (failed swing?)
        # Solution: Enforce 0.5% minimum distance safety buffer
        # ═══════════════════════════════════════════════════════════════════════
        actual_stop_loss = signal.stop_loss
        actual_take_profit = signal.take_profit

        # SOTA SAFETY GUARD: Ensure minimum SL distance (1.0%)
        # This prevents immediate stop-out due to spread or noise
        if actual_stop_loss > 0:
            min_dist = current_price * 0.01  # 1.0% buffer

            if signal.direction.value == "LONG":
                max_safe_sl = current_price - min_dist
                if actual_stop_loss > max_safe_sl:
                    self.logger.warning(
                        f"⚠️ SL too tight! Adj {signal.symbol} SL: ${actual_stop_loss:.4f} -> ${max_safe_sl:.4f} (1.0% min dist)"
                    )
                    actual_stop_loss = max_safe_sl
            else: # SHORT
                min_safe_sl = current_price + min_dist
                if actual_stop_loss < min_safe_sl:
                    self.logger.warning(
                        f"⚠️ SL too tight! Adj {signal.symbol} SL: ${actual_stop_loss:.4f} -> ${min_safe_sl:.4f} (1.0% min dist)"
                    )
                    actual_stop_loss = min_safe_sl

        self.logger.info(
            f"📍 SL/TP SET: {signal.symbol} | "
            f"Entry: ${current_price:.4f} | "
            f"SL: ${actual_stop_loss:.4f} | "
            f"TP: ${actual_take_profit:.4f}"
        )

        self._place_backup_sl_only(
            symbol=signal.symbol,
            side=position_side,
            quantity=signal.quantity,
            entry_price=current_price,
            local_sl=actual_stop_loss,     # Use adjusted SL!
            local_tp=actual_take_profit,   # True TP tracked locally
            atr=atr_value                  # For ATR-based trailing
        )

        # Note: Watermarks are now set inside _place_backup_sl_only
        symbol_upper = signal.symbol.upper()

        self.logger.info(
            f"📍 Watermarks set for {symbol_upper}: SL=${actual_stop_loss:.4f} TP=${actual_take_profit:.4f}"
        )

        self.logger.info(
            f"✅ POSITION ACTIVE: {signal.symbol} monitoring STARTED. "
            f"SL=${actual_stop_loss:.4f} TP=${actual_take_profit:.4f}"
        )

        # SOTA FIX (Jan 2026): Broadcast EXECUTION event to Frontend
        # This updates signal status from GENERATED -> EXECUTED on UI
        if hasattr(self, 'event_bus') and self.event_bus:
            try:
                execution_data = {
                    'id': getattr(signal, 'signal_id', None), # PendingSignal uses signal_id
                    'symbol': signal.symbol,
                    'signal_type': signal.direction.value, # 'LONG'/'SHORT'
                    'price': current_price,
                    'executed_at': datetime.now().isoformat(),
                    'order_id': order.order_id if order else 'market_fill',
                    'status': 'EXECUTED'
                }
                self.event_bus.publish_signal_update(execution_data, symbol=signal.symbol)
                self.logger.info(f"📡 EventBus: Published SIGNAL_EXECUTED for {signal.symbol}")
            except Exception as e:
                self.logger.error(f"Failed to publish signal execution event: {e}")

        # Persist to DB if available
        if self.order_repo:
            try:
                # SOTA FIX (Jan 2026): Pass ATR for trailing stop persistence
                atr_value = signal.metadata.get('atr', 0) if hasattr(signal, 'metadata') else 0
                self.order_repo.save_live_position(
                    symbol=signal.symbol,
                    side=signal.direction.value,
                    entry_price=current_price,
                    quantity=signal.quantity,
                    leverage=signal.leverage,
                    stop_loss=actual_stop_loss,    # SOTA FIX: Use adjusted SL!
                    take_profit=actual_take_profit,
                    atr=atr_value  # SOTA: Persist ATR for trailing after restart
                )
            except Exception as e:
                self.logger.warning(f"⚠️ Failed to persist to DB: {e}")

        # SOTA (Jan 2026): Start PositionMonitor for trailing stop
        if self.position_monitor:
            # SOTA FIX: Prevent duplicate handlers
            if self.position_monitor.get_position(signal.symbol):
                 self.logger.info(f"⚠️ {signal.symbol} already being monitored. Skipping duplicate.")
                 return True  # Position already monitored, skip to avoid duplicate handlers

            from .position_monitor_service import MonitoredPosition, PositionMonitorService

            # FIX (Feb 9, 2026): Use actual fill price instead of trigger price
            # Trigger price may differ from fill price due to slippage
            fill_price = current_price  # Default to trigger price
            if order and hasattr(order, 'avg_price') and order.avg_price > 0:
                fill_price = order.avg_price
                if abs(fill_price - current_price) / current_price > 0.001:
                    self.logger.info(
                        f"📊 Fill price differs from trigger: "
                        f"trigger=${current_price:.4f} fill=${fill_price:.4f} "
                        f"slippage={((fill_price - current_price) / current_price * 100):.3f}%"
                    )

            # v6.5.2: Use SIGNAL's SL (matches BT behavior)
            # Signal SL = liquidity zone-based, min 1.0% enforced (line 4382), max 1.2% (max_sl_validation)
            # Before: fixed 1.0% via calculate_local_sl() — ignored signal's optimal SL placement
            # Fallback to fixed 1.2% SL if signal SL is missing/zero
            signal_sl = actual_stop_loss if actual_stop_loss > 0 else PositionMonitorService.calculate_local_sl(fill_price, signal.direction.value)

            monitored_pos = MonitoredPosition(
                symbol=signal.symbol,
                side=signal.direction.value,
                entry_price=fill_price,
                quantity=signal.quantity,
                leverage=signal.leverage,
                initial_sl=signal_sl,         # Signal's SL (matches BT — was fixed 1.0%)
                initial_tp=actual_take_profit,
                atr=atr_value  # ATR from signal metadata
            )
            self.position_monitor.start_monitoring(monitored_pos)

            # NOTE: Dynamic WS subscription is now handled by PositionMonitor.start_monitoring()
            # The old code here only added to _symbols list without sending actual SUBSCRIBE request

        # Refresh positions
        self._refresh_positions()

        return True

    def _place_bracket_orders(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        stop_loss: float,
        take_profit: float
    ):
        """
        SOTA (Jan 2026): Place SL/TP bracket orders on EXCHANGE after entry fill.

        Benefits:
        - Orders live on exchange → execute even if bot offline
        - Freqtrade-style reliability
        - Free to place/cancel (only charged on execution)
        """
        try:
            symbol_upper = symbol.upper()
            # Close side is opposite of entry
            close_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY

            sl_order_id = None
            tp_order_id = None

            # SOTA (Jan 2026): Use Algo Order API for conditional orders
            # Binance deprecated /fapi/v1/order for STOP_MARKET on Dec 9, 2025
            # SOTA (Jan 2026): Use Algo Order API for conditional orders
            # Binance deprecated /fapi/v1/order for STOP_MARKET on Dec 9, 2025
            # OPTIMIZATION: Use close_position=True for Backup SL (Guarantees Full Close)
            if stop_loss > 0:
                sl_order = self.client.create_algo_order(
                    symbol=symbol_upper,
                    side=close_side,
                    order_type=OrderType.STOP_MARKET,
                    quantity=0.0, # Ignored when close_position=True
                    stop_price=stop_loss,
                    reduce_only=False, # Implied
                    close_position=True # SOTA: Close everything
                )
                if sl_order:
                    sl_order_id = sl_order.get('algoId') or sl_order.get('orderId')
                    self.logger.info(f"📍 SL ON EXCHANGE: {symbol_upper} @ ${stop_loss:.4f} (AlgoID: {sl_order_id}) [Auto-Close All]")

            # Place TP order using Algo Order API
            if take_profit > 0:
                tp_order = self.client.create_algo_order(
                    symbol=symbol_upper,
                    side=close_side,
                    order_type=OrderType.TAKE_PROFIT_MARKET,
                    quantity=0.0, # Ignored when close_position=True
                    stop_price=take_profit,
                    reduce_only=False, # Implied
                    close_position=True # SOTA: Close everything
                )
                if tp_order:
                    tp_order_id = tp_order.get('algoId') or tp_order.get('orderId')
                    self.logger.info(f"🎯 TP ON EXCHANGE: {symbol_upper} @ ${take_profit:.4f} (AlgoID: {tp_order_id})")

            # SOTA: Store order IDs in watermarks for Cancel+Replace later
            import time as time_module
            if symbol_upper in self._position_watermarks:
                self._position_watermarks[symbol_upper]['sl_order_id'] = sl_order_id
                self._position_watermarks[symbol_upper]['tp_order_id'] = tp_order_id
                self._position_watermarks[symbol_upper]['last_sl_update'] = time_module.time()
            else:
                self._position_watermarks[symbol_upper] = {
                    'sl_order_id': sl_order_id,
                    'tp_order_id': tp_order_id,
                    'current_sl': stop_loss,
                    'tp_target': take_profit,
                    'last_sl_update': time_module.time()
                }

        except Exception as e:
            self.logger.warning(f"⚠️ Failed to place bracket orders: {e}")

    def _calculate_tp_close_price(
        self,
        entry_price: float,
        side: str,
        threshold_pct: float,
        leverage: int
    ) -> float:
        """
        ═══════════════════════════════════════════════════════════════════════
        SOTA (Feb 2026): Calculate TP_CLOSE trigger price for exchange order.

        Replaces callback-based AUTO_CLOSE with exchange-side execution.

        Formula: entry × (1 ± threshold_pct / leverage / 100)

        Example:
          Entry: $28.47, Leverage: 10x, Threshold: 5.1% ROE
          Price Change = 5.1 / 10 / 100 = 0.0051 (0.51%)
          TP_CLOSE = $28.47 × 1.0051 = $28.62
        ═══════════════════════════════════════════════════════════════════════
        """
        price_change_pct = threshold_pct / leverage / 100

        if side == 'LONG':
            return entry_price * (1 + price_change_pct)
        else:  # SHORT
            return entry_price * (1 - price_change_pct)

    def _place_backup_sl_only(
        self,
        symbol: str,
        side: str,  # 'LONG' or 'SHORT'
        quantity: float,
        entry_price: float,
        local_sl: float,
        local_tp: float,
        atr: float = 0.0
    ) -> str:
        """
        ═══════════════════════════════════════════════════════════════════════
        SOTA Local-First Pattern (Feb 2026): Place backup SL + TP_CLOSE orders.

        Pattern: Two Sigma, Citadel - local TP/SL + exchange safety orders.

        Orders placed on exchange:
        1. STOP_MARKET @ -3% (Disaster SL protection)
        2. TAKE_PROFIT_MARKET @ +profitable_threshold% (TP_CLOSE - NEW!)

        Benefits:
        1. Exchange-side execution = No missed ticks
        2. Works even if backend crashes
        3. OCO-like behavior (one cancels other on fill)
        4. Replaces unreliable callback-based AUTO_CLOSE
        ═══════════════════════════════════════════════════════════════════════

        Args:
            symbol: Trading pair
            side: 'LONG' or 'SHORT'
            quantity: Position size
            entry_price: Entry price for backup SL calculation
            local_sl: True SL (tracked locally, for exit decision)
            local_tp: True TP (tracked locally)
            atr: ATR value for trailing calculation

        Returns:
            Backup SL order ID
        """
        from .position_monitor_service import PositionMonitorService, MonitoredPosition

        symbol_upper = symbol.upper()
        backup_sl_id = None
        tp_close_id = None
        tp_close_price = None  # SOTA FIX (Feb 2026): Initialize to None since calculation block is disabled

        try:
            # Step 1: Calculate backup SL (3% away from entry)
            backup_sl_price = PositionMonitorService.calculate_backup_sl(entry_price, side)

            # Step 2: Place ONLY backup SL on exchange
            close_side = OrderSide.SELL if side == 'LONG' else OrderSide.BUY

            sl_order = self.client.create_algo_order(
                symbol=symbol_upper,
                side=close_side,
                order_type=OrderType.STOP_MARKET,
                quantity=quantity,
                stop_price=backup_sl_price,
                reduce_only=True
            )

            if sl_order:
                backup_sl_id = str(sl_order.get('algoId') or sl_order.get('orderId'))
                self.logger.info(
                    f"🛡️ BACKUP SL PLACED: {symbol_upper} | "
                    f"AlgoID: {backup_sl_id} | Type: STOP_MARKET | "
                    f"TriggerPrice: ${backup_sl_price:.4f} (-2.5% backup) | Qty: {quantity:.6f} | "
                    f"Side: {close_side.value} | LocalSL: ${local_sl:.4f} | LocalTP: ${local_tp:.4f}"
                )

            # ═══════════════════════════════════════════════════════════════════
            # SOTA (Feb 2026): Place TP_CLOSE order (replaces callback AUTO_CLOSE)
            # ═══════════════════════════════════════════════════════════════════
            # ═══════════════════════════════════════════════════════════════════
            # SOTA (Feb 2026): TP_CLOSE order DISABLED
            # Reason: Switched to "Close on Candle Close" strategy (Local Monitor).
            # We no longer place a static TP on exchange. Instead, we monitor 15m candle close.
            # ═══════════════════════════════════════════════════════════════════
            # if self.close_profitable_auto and self.profitable_threshold_pct > 0:
            #     tp_close_price = self._calculate_tp_close_price(
            #         entry_price=entry_price,
            #         side=side,
            #         threshold_pct=self.profitable_threshold_pct,
            #         leverage=self.max_leverage
            #     )
            #
            #     try:
            #         tp_close_order = self.client.create_algo_order(
            #             symbol=symbol_upper,
            #             side=close_side,
            #             order_type=OrderType.TAKE_PROFIT_MARKET,
            #             quantity=quantity,
            #             stop_price=tp_close_price,
            #             reduce_only=True
            #         )
            #
            #         if tp_close_order:
            #             tp_close_id = str(tp_close_order.get('algoId') or tp_close_order.get('orderId'))
            #             self.logger.info(
            #                 f"💰 TP_CLOSE PLACED: {symbol_upper} | "
            #                 f"AlgoID: {tp_close_id} | Type: TAKE_PROFIT_MARKET | "
            #                 f"TriggerPrice: ${tp_close_price:.4f} (+{self.profitable_threshold_pct}% ROE) | "
            #                 f"Qty: {quantity:.6f} | Leverage: {self.max_leverage}x"
            #             )
            #     except Exception as e:
            #         self.logger.warning(f"⚠️ Failed to place TP_CLOSE order: {e}")

            # Step 3: Start LOCAL monitoring (PositionMonitorService)
            from .position_monitor_service import get_position_monitor
            monitor = get_position_monitor()

            # Create monitored position for local tracking
            # Calculate fixed 1.2% LOCAL SL (Layer 1) — fallback for manual/recovery path
            # LOCAL SL < HARD CAP (2%) < BACKUP SL (3%) — correct layering
            fixed_local_sl = PositionMonitorService.calculate_local_sl(entry_price, side)

            pos = MonitoredPosition(
                symbol=symbol_upper,
                side=side,
                entry_price=entry_price,
                quantity=quantity,
                leverage=self.max_leverage,
                initial_sl=fixed_local_sl,  # Fixed 1.2% SL (Layer 1)
                initial_tp=local_tp,        # True TP (tracked locally)
                atr=atr,                    # For ATR-based trailing
            )
            pos.sl_order_id = backup_sl_id  # Track exchange order ID
            pos.tp_close_order_id = tp_close_id  # Track TP_CLOSE order ID (NEW)

            monitor.start_monitoring(pos)

            # Step 4: Update watermarks for consistency
            import time as time_module
            if symbol_upper in self._position_watermarks:
                self._position_watermarks[symbol_upper]['current_sl'] = fixed_local_sl
                self._position_watermarks[symbol_upper]['tp_target'] = local_tp
                self._position_watermarks[symbol_upper]['start_time'] = time_module.time()
                self._position_watermarks[symbol_upper]['sl_order_id'] = backup_sl_id
            else:
                self._position_watermarks[symbol_upper] = {
                    'highest': entry_price if side == 'LONG' else 0,
                    'lowest': entry_price if side == 'SHORT' else float('inf'),
                    'current_sl': fixed_local_sl,
                    'backup_sl': backup_sl_price,
                    'tp_target': local_tp,
                    'entry_price': entry_price,
                    'initial_risk': abs(entry_price - fixed_local_sl),
                    'is_breakeven': False,
                    'tp_hit_count': 0,
                    'atr': atr,
                    'tp_levels': {'tp1': local_tp},
                    'initial_size': quantity,
                    'remaining_size': quantity,
                    'side': side,
                    'sl_order_id': backup_sl_id,
                    'tp_order_id': None,
                    'tp_close_order_id': tp_close_id,
                    'tp_close_price': tp_close_price if self.close_profitable_auto else None,
                    'last_sl_update': time_module.time(),
                    'local_first_mode': True
                }

            return backup_sl_id

        except Exception as e:
            self.logger.error(f"❌ Failed to place backup SL: {e}")
            return None

    def _check_candle_close_exit_adapter(self, symbol: str, price: float) -> None:
        """
        SOTA (Feb 2026): Check if position should auto-close on candle close.
        Matches '0.25h' Exit strategy: Close if Profitable > Threshold at 15m close.

        Callback adapter for PositionMonitorService.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            price: Current close price from PositionMonitor callback
        """
        symbol = symbol.upper()

        # SOTA FIX (Feb 2026): Use LocalPosition tracker, NOT FuturesPosition
        # FuturesPosition is Binance API DTO - doesn't have get_roe_percent()
        # LocalPosition is our domain entity - has accurate PnL calculation
        with self._local_positions_lock:
            tracker = self._local_positions.get(symbol)

        if not tracker:
            self.logger.debug(f"⚠️ No local tracker for {symbol}, skipping candle close check")
            return

        # Check ROE threshold (Default 5% - SYNC: Match backtest)
        # Access config from self.profitable_threshold_pct (LiveTradingService config)
        threshold_pct = getattr(self, 'profitable_threshold_pct', 5.0)

        # Get monitor position for TP hit status check
        monitor_pos = self.position_monitor.get_position(symbol)
        if not monitor_pos:
            return  # Should not happen if confirmed

        # SOTA (Feb 2026): CoT Logic Refinement
        # Conflict: If we hit TP1, we are in TRAILING mode. Auto-close would kill the runner.
        # Solution: TP_CLOSE only applies if TP1 was NOT hit (Fail-safe / Time-limit exit).
        if monitor_pos.tp_hit_count > 0:
            self.logger.debug(f"🏃 SKIPPING CANDLE CLOSE EXIT: {symbol} is trailing (TP1 hit)")
            return

        # FIX (Feb 2026): Use price param directly instead of fetching from monitor
        current_price = price
        roe = tracker.get_roe_percent(current_price)

        # Log check
        self.logger.debug(
            f"🕯️ CANDLE CLOSE CHECK {symbol}: ROE={roe:.2f}% (Threshold={threshold_pct}%)"
        )

        if roe >= threshold_pct:
            self.logger.info(
                f"💰 CANDLE CLOSE EXIT: {symbol} ROE {roe:.2f}% >= {threshold_pct}% | Closing Position..."
            )
            # FIX (Feb 2026): Stop monitoring IMMEDIATELY to prevent ghost watermarks
            # BUG: Without this, PositionMonitor continues receiving ticks for the closed
            # position, triggering breakeven/trailing updates and creating zombie watermarks.
            # The race condition window was 24+ seconds in production logs.
            # STATUS: NOT DEPLOYED (Feb 6, 2026) - kept with 1m AUTO_CLOSE observation period.
            # See: documents/analysis/AUTO-CLOSE-1M-AUDIT-FEB6-2026.md
            if self.position_monitor:
                self.position_monitor.stop_monitoring(symbol)
                self.logger.info(f"🛑 Stopped monitoring {symbol} BEFORE async close (race condition fix)")
            # v6.6.0 FIX: Route through _close_position_market for GTX support
            # OLD: close_position_async() → always MARKET (bypassed GTX completely)
            # NEW: _close_position_market() → tries GTX first for MAKER fee (0.02%)
            summary = tracker.get_summary(price)
            self._close_position_market(
                symbol=symbol,
                quantity=summary['total_quantity'],
                reason="AUTO_CLOSE_PROFITABLE_LOCAL"
            )


    def update_stop_loss(self, symbol: str, new_sl: float, old_order_id: str = None) -> str:
        """
        SOTA FIX (Jan 2026): Update SL order - Place new BEFORE cancel old.

        CRITICAL BUG FIX: Previously cancelled old SL before placing new SL.
        If place failed → position had NO SL protection!

        New logic:
        1. Place new SL first
        2. If success → Cancel old SL
        3. If fail → Keep old SL (don't cancel)

        Called by PositionMonitorService when trailing stop moves.

        Args:
            symbol: Trading pair
            new_sl: New stop loss price
            old_order_id: Order ID to cancel (optional)

        Returns:
            New order ID or None if failed
        """
        if not self.client:
            self.logger.error("No client for SL update")
            return None

        try:
            # Get position info to determine side and quantity
            pos_state = self._position_states.get(symbol)
            if not pos_state:
                self.logger.error(f"No position state for {symbol}")
                return None

            # Determine close side (opposite of position side)
            close_side = OrderSide.SELL if pos_state.side == 'LONG' else OrderSide.BUY
            quantity = pos_state.quantity

            # ═══════════════════════════════════════════════════════════════════════
            # SOTA FIX (Jan 2026): Place new SL FIRST (before cancelling old)
            # This ensures we ALWAYS have SL protection, even if cancel fails
            # ═══════════════════════════════════════════════════════════════════════

            # 1. Place new SL order
            # SOTA (Jan 2026): Use Algo Order API for STOP_MARKET
            # Binance deprecated /fapi/v1/order for conditional orders on Dec 9, 2025
            sl_order = self.client.create_algo_order(
                symbol=symbol,
                side=close_side,
                order_type=OrderType.STOP_MARKET,
                quantity=quantity,
                stop_price=new_sl,
                reduce_only=True
            )

            if not sl_order:
                self.logger.error(f"❌ Failed to place new SL for {symbol}")
                # CRITICAL: Keep old SL, don't cancel!
                return None

            new_id = sl_order.get('algoId') or sl_order.get('orderId')
            self.logger.info(f"✅ NEW SL PLACED: {symbol} @ ${new_sl:.4f} (AlgoID: {new_id})")

            # 2. Cancel old SL order ONLY if new SL placed successfully
            if old_order_id:
                try:
                    self.client.cancel_order(symbol=symbol, order_id=old_order_id)
                    self.logger.debug(f"🗑️ OLD SL CANCELLED: {old_order_id}")
                except Exception as ce:
                    # Not critical - old order may have already filled/cancelled
                    self.logger.warning(f"⚠️ Failed to cancel old SL {old_order_id}: {ce}")

            # 3. Update position state with new SL
            if pos_state:
                pos_state.current_sl = new_sl
                pos_state.sl_order_id = str(new_id) if new_id else None

            return str(new_id) if new_id else None

        except Exception as e:
            self.logger.error(f"❌ Failed to update SL: {e}")
            # CRITICAL: If exception, old SL remains (not cancelled)
            return None

    # NOTE: partial_close_position method is defined at line ~2978 (uses fresh active_positions)
    # The duplicate that was here (using stale _position_states) has been removed.

    def check_pending_signals(self, symbol: str, current_price: float):
        """
        SOTA: Check if price triggers any pending signals.

        Called by SharedBinanceClient or RealtimeService on each price tick.
        This is the WebSocket hook for LocalSignalTracker.

        Args:
            symbol: Trading pair symbol (e.g., 'BTCUSDT')
            current_price: Current market price
        """
        if self.mode == TradingMode.PAPER:
            return  # Paper mode handled by PaperTradingService

        # SOTA FIX (Jan 2026): STARTUP_GRACE_PERIOD
        # Block signal execution for first 30s after restart
        # Prevents instant SL from stale candle data triggering signals immediately
        startup_age = (datetime.now() - self._startup_time).total_seconds()
        if startup_age < self.STARTUP_GRACE_PERIOD_SECONDS:
            # Allow position monitoring but skip signal execution
            symbol_upper = symbol.upper()
            if self.position_monitor and symbol_upper in self.position_monitor._positions:
                self.position_monitor._process_tick(symbol_upper, current_price, current_price, current_price)
            return  # Skip signal execution during startup cooldown

        try:
            # Call LocalSignalTracker's on_price_update
            # If signal triggers, callback executes MARKET order
            triggered = self.signal_tracker.on_price_update(symbol, current_price)

            if triggered:
                self.logger.info(
                    f"🎯 Signal triggered via WebSocket: {symbol} @ ${current_price:.4f}"
                )

            # SOTA (Jan 2026): Forward to PositionMonitor for trailing stop
            # Normalize to UPPER for consistent lookup (WS may send lowercase)
            symbol_upper = symbol.upper()
            if self.position_monitor and symbol_upper in self.position_monitor._positions:
                self.position_monitor._process_tick(symbol_upper, current_price, current_price, current_price)

        except Exception as e:
            self.logger.debug(f"Error checking pending signals: {e}")

    def check_pending_signals_on_candle(self, symbol: str, candle_low: float, candle_high: float):
        """
        SOTA (Jan 2026): Check if candle HIGH/LOW triggers any pending signals.

        Uses pessimistic fill model matching backtest for better parity.
        Called by RealtimeService on each 1m candle close.

        Args:
            symbol: Trading pair symbol (e.g., 'BTCUSDT')
            candle_low: Lowest price in the closed candle
            candle_high: Highest price in the closed candle
        """
        if self.mode == TradingMode.PAPER:
            return  # Paper mode handled by PaperTradingService

        # Skip during startup grace period
        startup_age = (datetime.now() - self._startup_time).total_seconds()
        if startup_age < self.STARTUP_GRACE_PERIOD_SECONDS:
            return

        try:
            # SOTA: Use candle-based fill check with pessimistic buffer
            triggered = self.signal_tracker.on_candle_close(
                symbol,
                candle_low,
                candle_high,
                pessimistic_buffer=0.001  # 0.1% buffer matching backtest
            )

            if triggered:
                self.logger.info(
                    f"🎯 CANDLE FILL: {symbol} low=${candle_low:.4f} high=${candle_high:.4f}"
                )

        except Exception as e:
            self.logger.debug(f"Error checking candle fill: {e}")

    def get_pending_signals_count(self) -> int:
        """Get number of pending signals in tracker."""
        return len(self.signal_tracker)

    def get_pending_signals(self) -> dict:
        """Get all pending signals for display."""
        return {
            sym: {
                'direction': sig.direction.value,
                'target_price': sig.target_price,
                'stop_loss': sig.stop_loss,
                'take_profit': sig.take_profit,
                'quantity': sig.quantity,
                'expires_at': sig.expires_at.isoformat() if sig.expires_at else None
            }
            for sym, sig in self.signal_tracker.get_all_pending().items()
        }

    def get_available_balance(self) -> float:
        """
        SOTA SYNC: Calculate available balance like Backtest (line 117-123).
        Available = Cached Balance - Used Margin (Positions) - Locked (Pending Orders)

        SOTA FIX (Jan 2026 - Bug #7): Added thread lock for race condition protection.
        Prevents incorrect balance calculation during concurrent position/order updates.
        """
        with self._balance_lock:
            return max(0.0, self._cached_available - self._used_margin - self._locked_in_orders)

    # NOTE: _execute_signal_legacy has been removed (Jan 2026)
    # Old LIMIT order flow superseded by LocalSignalTracker + MARKET execution
    # See _execute_triggered_signal() for the current implementation

    # =========================================================================
    # USER DATA STREAM (Order Fill Detection)
    # =========================================================================

    async def start_user_data_stream(self):
        """
        Start listening for order updates from Binance.

        SOTA: Detects when limit orders fill, then places bracket orders.
        """
        if not self.client or self.mode == TradingMode.PAPER:
            self.logger.info("User Data Stream not needed for Paper mode")
            return

        try:
            from ...infrastructure.websocket.binance_user_data_client import (
                BinanceUserDataClient, OrderUpdate
            )

            # Get listen key
            self._listen_key = self.client.get_listen_key()
            if not self._listen_key:
                self.logger.error("Failed to get listen key")
                return

            # Create client
            use_testnet = (self.mode == TradingMode.TESTNET)
            self._user_data_client = BinanceUserDataClient(
                listen_key=self._listen_key,
                use_testnet=use_testnet
            )

            # Set callback
            self._user_data_client.set_order_callback(self._on_order_update)

            # Connect (runs in background)
            import asyncio
            asyncio.create_task(self._user_data_client.connect())

            self.logger.info("✅ User Data Stream started")

        except Exception as e:
            self.logger.error(f"Failed to start User Data Stream: {e}")

    async def stop_user_data_stream(self):
        """Stop User Data Stream."""
        if self._user_data_client:
            await self._user_data_client.disconnect()
            self._user_data_client = None

        if self._listen_key and self.client:
            self.client.close_listen_key()
            self._listen_key = None

        self.logger.info("🔌 User Data Stream stopped")

    # =========================================================================
    # STATE RECONCILIATION (SOTA)
    # =========================================================================

    async def reconcile_state(self) -> Dict[str, Any]:
        """
        SOTA: State Reconciliation - Sync local state with Binance.

        Handles scenarios where local state diverges from exchange:
        1. Orphan positions: Exchange has position we don't know about
        2. Stale tracking: We track position that's been closed
        3. Missing bracket orders: Position without proper SL/TP

        Should be called:
        - On startup (before processing signals)
        - Every 5 minutes (periodic sync)
        - After network reconnect

        Returns:
            Dict with reconciliation results
        """
        if not self.client or self.mode == TradingMode.PAPER:
            return {'skipped': True, 'reason': 'Paper mode or no client'}

        results = {
            'orphan_positions': [],
            'stale_positions': [],
            'missing_brackets': [],
            'actions_taken': [],
            'timestamp': datetime.now().isoformat()
        }

        self.logger.info("🔄 State reconciliation starting...")

        try:
            # 1. FETCH EXCHANGE STATE (SOTA: Async Offloading)
            # Offload heavy blocking I/O to thread pool to prevent event loop freeze
            exchange_positions = await asyncio.to_thread(self.client.get_positions)
            exchange_orders = await asyncio.to_thread(self.client.get_open_orders)

            # SOTA (Jan 2026): Also fetch ALGO orders (backup SL)
            # Regular get_open_orders() doesn't include algo/conditional orders since Dec 2025
            algo_orders = []
            try:
                if hasattr(self.client, 'get_open_algo_orders'):
                    algo_orders = await asyncio.to_thread(self.client.get_open_algo_orders)
                    algo_orders = algo_orders or []

                    # SOTA FIX (Jan 2026): Task 11.3 - Enhanced algo order fetch logging
                    if algo_orders:
                        from ...infrastructure.api.algo_order_parser import AlgoOrderParser
                        algo_symbols = set(AlgoOrderParser.get_symbol(o) for o in algo_orders)
                        algo_types = {}
                        for o in algo_orders:
                            otype = AlgoOrderParser.get_order_type(o)
                            algo_types[otype] = algo_types.get(otype, 0) + 1
                        self.logger.info(
                            f"📋 Algo orders fetched: {len(algo_orders)} orders | "
                            f"Symbols: {', '.join(algo_symbols)} | "
                            f"Types: {algo_types}"
                        )
            except Exception as e:
                self.logger.warning(f"⚠️ Could not fetch algo orders: {e}")

            # Combine regular + algo orders
            all_orders = list(exchange_orders) + list(algo_orders)

            # Build maps
            exch_pos_map = {
                p.symbol: p for p in exchange_positions
                if abs(p.position_amt) > 0
            }

            exch_orders_by_symbol = defaultdict(list)
            for order in all_orders:  # Use all_orders including algo
                # SOTA: Handle dict format from Binance API
                sym = order.get('symbol') if isinstance(order, dict) else order.symbol
                exch_orders_by_symbol[sym].append(order)

            self.logger.info(
                f"📊 Exchange: {len(exch_pos_map)} positions, "
                f"{len(exchange_orders)} open orders + {len(algo_orders)} algo orders"
            )
            self.logger.info(
                f"📊 Local: {len(self._bracket_orders)} tracked positions"
            )

            # 2. DETECT ORPHAN POSITIONS
            for symbol, pos in exch_pos_map.items():
                if symbol not in self._bracket_orders:
                    orphan_info = {
                        'symbol': symbol,
                        'side': 'LONG' if pos.position_amt > 0 else 'SHORT',
                        'size': abs(pos.position_amt),
                        'entry_price': pos.entry_price,
                        'unrealized_pnl': pos.unrealized_pnl
                    }
                    results['orphan_positions'].append(orphan_info)

                    # ACTION: Adopt into tracking
                    orders = exch_orders_by_symbol.get(symbol, [])
                    self._adopt_orphan_position(symbol, pos, orders)
                    results['actions_taken'].append(f"ADOPTED: {symbol}")

            # 3. DETECT STALE TRACKING
            symbols_to_clean = []
            for symbol in list(self._bracket_orders.keys()):
                if symbol not in exch_pos_map:
                    results['stale_positions'].append(symbol)
                    symbols_to_clean.append(symbol)

            # Clean stale
            for symbol in symbols_to_clean:
                self._cleanup_stale_tracking(symbol)
                results['actions_taken'].append(f"CLEANED: {symbol}")

            # SOTA FIX (Jan 2026): Import AlgoOrderParser for unified order parsing
            from ...infrastructure.api.algo_order_parser import AlgoOrderParser

            # 3.5 SOTA FIX (Jan 2026): DETECT ORPHAN ALGO ORDERS
            # Algo orders without corresponding positions should be cancelled
            # This prevents zombie orders from triggering on future positions
            orphan_algo_count = 0
            for algo_order in algo_orders:
                algo_symbol = AlgoOrderParser.get_symbol(algo_order)
                if algo_symbol and algo_symbol not in exch_pos_map:
                    # Orphan algo order detected - no position for this symbol
                    algo_id = AlgoOrderParser.get_order_id(algo_order)
                    algo_type = AlgoOrderParser.get_order_type(algo_order)
                    trigger_price = AlgoOrderParser.get_trigger_price(algo_order)

                    self.logger.warning(
                        f"🧟 ORPHAN ALGO ORDER detected: {algo_symbol} "
                        f"[AlgoID: {algo_id}] Type: {algo_type} Trigger: ${trigger_price:.4f}"
                    )

                    try:
                        self.client.cancel_algo_order(algo_symbol, str(algo_id))
                        orphan_algo_count += 1
                        results['actions_taken'].append(f"CANCELLED_ORPHAN_ALGO: {algo_symbol} [{algo_id}]")
                        self.logger.info(
                            f"🧹 [ORPHAN] Cancelled orphan algo order: {algo_symbol} [AlgoID: {algo_id}]"
                        )
                    except Exception as cancel_err:
                        self.logger.error(f"❌ Failed to cancel orphan algo {algo_id}: {cancel_err}")

            if orphan_algo_count > 0:
                self.logger.info(f"🧹 Cancelled {orphan_algo_count} orphan algo orders")

            # 4. CHECK FOR MISSING/PARTIAL BRACKETS (SOTA Upgrade)
            # SOTA FIX (Jan 2026): Use AlgoOrderParser for unified order parsing
            from ...infrastructure.api.algo_order_parser import AlgoOrderParser

            for symbol, brackets in self._bracket_orders.items():
                if symbol not in exch_pos_map: continue

                pos = exch_pos_map[symbol]
                orders = exch_orders_by_symbol.get(symbol, [])

                # Calculate SL Coverage using AlgoOrderParser
                # SOTA FIX (Jan 2026): Unified parsing for both regular and algo orders
                # Regular orders: type='STOP_MARKET', origQty=quantity
                # Algo orders: orderType='STOP_MARKET' or 'STOP', quantity=quantity
                sl_orders = AlgoOrderParser.filter_sl_orders(orders)
                total_sl_qty = AlgoOrderParser.get_total_sl_quantity(orders)
                pos_qty = abs(pos.position_amt)

                coverage_pct = (total_sl_qty / pos_qty) * 100 if pos_qty > 0 else 0

                # SOTA FIX (Jan 2026): Log algo order details for debugging
                algo_sl_count = sum(1 for o in sl_orders if AlgoOrderParser.is_algo_order(o))
                regular_sl_count = len(sl_orders) - algo_sl_count

                # SOTA FIX (Jan 2026): Detect externally cancelled algo orders
                # Check if we expected an algo order but it's no longer on exchange
                watermark = self._position_watermarks.get(symbol, {})
                expected_sl_order_id = watermark.get('sl_order_id')
                if expected_sl_order_id:
                    # Check if expected SL order still exists
                    current_sl_ids = [AlgoOrderParser.get_order_id(o) for o in sl_orders]
                    if expected_sl_order_id not in current_sl_ids:
                        self.logger.warning(
                            f"⚠️ {symbol}: Expected SL order {expected_sl_order_id} NOT FOUND on exchange! "
                            f"May have been cancelled externally. Current SL orders: {current_sl_ids}"
                        )
                        results['missing_brackets'].append({
                            'symbol': symbol,
                            'issue': 'SL_EXTERNALLY_CANCELLED',
                            'expected_order_id': expected_sl_order_id
                        })

                if total_sl_qty == 0:
                    results['missing_brackets'].append({
                        'symbol': symbol,
                        'issue': 'NO_STOP_LOSS'
                    })
                    self.logger.critical(
                        f"🚨 {symbol} has NO STOP LOSS! "
                        f"(checked {len(orders)} orders: {regular_sl_count} regular, {algo_sl_count} algo)"
                    )
                elif coverage_pct < 99.0:
                    results['missing_brackets'].append({
                        'symbol': symbol,
                        'issue': 'PARTIAL_COVERAGE',
                        'coverage': coverage_pct
                    })
                    self.logger.warning(
                        f"⚠️ {symbol} Partial SL Coverage: {coverage_pct:.1f}% "
                        f"({total_sl_qty}/{pos_qty})"
                    )
                else:
                    # SOTA: Log successful SL detection for debugging
                    self.logger.debug(
                        f"✅ {symbol} SL OK: {len(sl_orders)} orders "
                        f"({regular_sl_count} regular, {algo_sl_count} algo), "
                        f"coverage={coverage_pct:.1f}%"
                    )

            self.logger.info(
                f"✅ Reconciliation complete: "
                f"{len(results['orphan_positions'])} orphans adopted, "
                f"{len(results['stale_positions'])} stale cleaned"
            )

        except Exception as e:
            self.logger.error(f"❌ Reconciliation failed: {e}")
            results['error'] = str(e)

        return results

    def _adopt_orphan_position(
        self,
        symbol: str,
        pos: FuturesPosition,
        orders: List[FuturesOrder]
    ):
        """
        Adopt an orphan position into tracking.

        SOTA Upgrade: Supports Multiple SL/TP Orders (Split Order).
        Collects all matching bracket orders and verifies coverage.

        SOTA FIX (Jan 2026): Uses AlgoOrderParser for unified order parsing.
        Handles both regular orders AND algo orders from Binance API.
        """
        from ...infrastructure.api.algo_order_parser import AlgoOrderParser

        # 1. Collect all valid bracket orders using AlgoOrderParser
        sl_orders = []
        tp_orders = []

        for order in orders:
            is_reduce = AlgoOrderParser.is_reduce_only(order)

            if AlgoOrderParser.is_stop_loss(order) and is_reduce:
                sl_orders.append(order)
            elif AlgoOrderParser.is_take_profit(order) and is_reduce:
                tp_orders.append(order)

        # 2. Store lists of IDs using AlgoOrderParser
        self._bracket_orders[symbol] = {
            'sl_order_ids': [AlgoOrderParser.get_order_id(o) for o in sl_orders],
            'tp_order_ids': [AlgoOrderParser.get_order_id(o) for o in tp_orders]
        }

        # 3. Initialize watermarks (using best available info)
        # For SL, use the highest price among SL orders if Long, lowest if Short
        current_sl = 0.0
        if sl_orders:
            if pos.position_amt > 0:  # Long
                current_sl = max(AlgoOrderParser.get_trigger_price(o) for o in sl_orders)
            else:  # Short
                current_sl = min(AlgoOrderParser.get_trigger_price(o) for o in sl_orders)

        # SOTA Hybrid (Jan 2026): Also track TP locally for accurate display
        # TP is tracked locally to avoid stop hunting but still visible to user
        tp_target = 0.0
        if tp_orders:
            if pos.position_amt > 0:  # Long - TP is above entry
                tp_target = min(AlgoOrderParser.get_trigger_price(o) for o in tp_orders)
            else:  # Short - TP is below entry
                tp_target = max(AlgoOrderParser.get_trigger_price(o) for o in tp_orders)

        # SOTA FIX (Jan 2026): PRESERVE existing watermark values from DB!
        # Don't overwrite DB-loaded SL/TP with exchange values.
        # DB values are the SOURCE OF TRUTH (original signal SL/TP).
        existing_wm = self._position_watermarks.get(symbol, {})
        existing_sl = existing_wm.get('current_sl', 0)
        existing_tp = existing_wm.get('tp_target', 0)

        # Priority: Existing DB values > Exchange values > 0
        final_sl = existing_sl if existing_sl > 0 else current_sl
        final_tp = existing_tp if existing_tp > 0 else tp_target

        # SOTA: Track exchange SL as backup_sl for display
        # current_sl (from Exchange) = the actual STOP_MARKET order on Binance
        backup_sl_price = current_sl if current_sl > 0 else 0
        backup_sl_order_id = None
        if sl_orders:
            # Get the order ID of the first SL order using AlgoOrderParser
            backup_sl_order_id = AlgoOrderParser.get_order_id(sl_orders[0])

        # SOTA FIX (Jan 2026): Log algo order detection for debugging
        algo_sl_count = sum(1 for o in sl_orders if AlgoOrderParser.is_algo_order(o))
        regular_sl_count = len(sl_orders) - algo_sl_count

        self.logger.info(
            f"📊 [ADOPT] {symbol}: DB(SL={existing_sl:.2f}, TP={existing_tp:.2f}) + "
            f"Exchange(SL={current_sl:.2f}, TP={tp_target:.2f}) → "
            f"Final(SL={final_sl:.2f}, TP={final_tp:.2f}, BackupSL={backup_sl_price:.2f}) | "
            f"SL Orders: {regular_sl_count} regular + {algo_sl_count} algo"
        )

        self._position_watermarks[symbol] = {
            'highest': existing_wm.get('highest', pos.entry_price),
            'lowest': existing_wm.get('lowest', pos.entry_price),
            'current_sl': final_sl,
            'tp_target': final_tp,
            'entry_price': pos.entry_price,
            # SOTA Local-First: Track exchange SL as backup
            'backup_sl': backup_sl_price,
            'sl_order_id': backup_sl_order_id,
            'local_first_mode': True  # Mark as locally managed
        }

        # SOTA FIX (Jan 2026): Create LocalPosition tracker for Orphan!
        # Critical for PnL/ROI tracking after restart.
        # SOTA FIX (Feb 2026): Thread-safe with RLock
        with self._local_positions_lock:
            if symbol not in self._local_positions:
                try:
                    # Detect leverage if possible, otherwise default to intended
                    leverage = pos.leverage if hasattr(pos, 'leverage') else self.max_leverage

                    tracker = LocalPosition(
                        symbol=symbol,
                        side='LONG' if pos.position_amt > 0 else 'SHORT',
                        intended_leverage=leverage
                    )

                    # Create synthetic fill to represent existing position
                    # This sets avg_entry = pos.entry_price
                    from datetime import datetime
                    initial_fill = FillRecord(
                        timestamp=datetime.now(),
                        order_id="ORPHAN_ADOPTION",
                        price=pos.entry_price,
                        quantity=abs(pos.position_amt),
                        fee=0.0, # Fee already paid/unknown, start fresh
                        fee_asset='USDT'
                    )
                    tracker.add_entry_fill(initial_fill)
                    tracker.set_actual_leverage(leverage)

                    self._local_positions[symbol] = tracker
                    self.logger.info(f"🧬 Adopted Orphan into Local Tracker: {symbol} @ {pos.entry_price}")

                    # ═══════════════════════════════════════════════════════════════════
                    # CRITICAL FIX (Feb 2026): Register WebSocket handler for Local SL/TP
                    # Without this, orphan positions DO NOT receive price ticks!
                    # This was the ROOT CAUSE of Local SL not triggering for SOLUSDT.
                    # ═══════════════════════════════════════════════════════════════════
                    if self.position_monitor:
                        try:
                            from src.application.services.position_monitor_service import MonitoredPosition, PositionMonitorService
                            orphan_side = 'LONG' if pos.position_amt > 0 else 'SHORT'

                            # SOTA FIX (Feb 2026): Use FIXED 1.2% SL for orphan positions (no signal data)
                            fixed_orphan_sl = PositionMonitorService.calculate_local_sl(pos.entry_price, orphan_side)

                            monitored_pos = MonitoredPosition(
                                symbol=symbol,
                                side=orphan_side,
                                entry_price=pos.entry_price,
                                quantity=abs(pos.position_amt),
                                leverage=pos.leverage if hasattr(pos, 'leverage') and pos.leverage > 0 else self.max_leverage,
                                initial_sl=fixed_orphan_sl,  # Fixed 1.0% SL (Layer 1)
                                initial_tp=final_tp if final_tp > 0 else pos.entry_price * (1.02 if orphan_side == 'LONG' else 0.98),  # 2% TP default if missing
                                # tp_hit_count defaults to 0, is_breakeven defaults to False
                            )

                            self.position_monitor.start_monitoring(monitored_pos)
                            self.logger.info(
                                f"📊 ORPHAN MONITORING STARTED: {symbol} | "
                                f"Entry: ${pos.entry_price:.4f} | SL: ${fixed_orphan_sl:.4f} (FIXED 0.95%) | TP: ${final_tp:.4f}"
                            )
                        except Exception as e:
                            self.logger.error(f"❌ Failed to start monitoring orphan {symbol}: {e}")

                except Exception as e:
                    self.logger.error(f"Failed to create LocalPosition for orphan {symbol}: {e}")

        # 4. SOTA: Risk Coverage Check using AlgoOrderParser
        total_sl_qty = sum(AlgoOrderParser.get_quantity(o) for o in sl_orders)
        pos_qty = abs(pos.position_amt)
        coverage_pct = (total_sl_qty / pos_qty) * 100 if pos_qty > 0 else 0

        side = 'LONG' if pos.position_amt > 0 else 'SHORT'
        sl_info = f"SL: {len(sl_orders)} orders ({coverage_pct:.1f}% covered)"
        tp_info = f"TP: {len(tp_orders)} orders"

        self.logger.warning(
            f"🔄 ADOPTED orphan: {symbol} {side} "
            f"@ {pos.entry_price:.2f} ({sl_info}, {tp_info})"
        )

        # SOTA FIX (Jan 2026): Only warn if NO SL at all (algo or regular)
        # Don't warn about partial coverage if backup SL exists
        if len(sl_orders) == 0:
            self.logger.critical(
                f"🚨 CRITICAL: {symbol} has NO STOP LOSS! "
                f"Neither regular nor algo SL orders found."
            )
        elif coverage_pct < 99.0:
            self.logger.warning(
                f"⚠️ {symbol} partial SL coverage: {coverage_pct:.1f}% "
                f"(Missing {pos_qty - total_sl_qty:.3f})"
            )

        # ═══════════════════════════════════════════════════════════════════
        # SOTA (Feb 2026): TP_CLOSE order DISABLED for orphan positions
        # Reason: Switched to "Close on Candle Close" strategy (Local Monitor).
        # The LOCAL monitor handles TP via 15m candle close, not REALTIME order.
        # Logic: Close if ROE >= +1.01% OR ROE <= -1.01%, else keep position.
        # This is consistent with new position flow (line 3747-3778).
        # ═══════════════════════════════════════════════════════════════════
        # if self.close_profitable_auto and self.profitable_threshold_pct > 0:
        #     ... (removed TP_CLOSE placement for orphans)


    def _cleanup_stale_tracking(self, symbol: str):
        """
        Clean up stale position tracking.

        SOTA FIX (Jan 2026): Also cancel exchange orders to prevent orphaned algo orders.
        """
        symbol_upper = symbol.upper()

        # SOTA FIX (Jan 2026): Cancel ALL exchange orders (regular + algo) FIRST
        # This prevents orphaned algo orders from triggering on future positions
        try:
            self._cleanup_all_orders_for_symbol(symbol_upper, reason="STALE")
        except Exception as e:
            self.logger.warning(f"⚠️ Failed to cancel exchange orders for stale {symbol_upper}: {e}")

        # Then clean local state (some may already be cleaned by unified cleanup)
        if symbol_upper in self._bracket_orders:
            del self._bracket_orders[symbol_upper]

        if symbol_upper in self._position_watermarks:
            del self._position_watermarks[symbol_upper]

        if symbol_upper in self.pending_orders:
            del self.pending_orders[symbol_upper]

        # MEMORY FIX (Feb 8, 2026): Remove stale LocalPosition
        with self._local_positions_lock:
            self._local_positions.pop(symbol_upper, None)

        # SOTA (Jan 2026): Stop PositionMonitor for this symbol
        if self.position_monitor:
            self.position_monitor.stop_monitoring(symbol_upper)

        self.logger.info(f"🧹 Cleaned stale tracking: {symbol_upper}")

    async def _on_order_update(self, order_update):
        """
        Handle order update from Binance.

        SOTA: When limit order fills, place bracket orders.
        """
        symbol = order_update.symbol
        status = order_update.status
        order_id = order_update.order_id

        self.logger.debug(f"📬 Order update: {symbol} #{order_id} -> {status}")

        # SOTA FIX (Jan 2026): Handle BOTH 'FILLED' and 'PARTIALLY_FILLED'
        # Critical Bug: Previous code only checked 'FILLED', leaving partial fills
        # without SL/TP protection. This is a CRITICAL risk exposure.
        if status in ('FILLED', 'PARTIALLY_FILLED'):
            # SOTA (Feb 2026): Set exit notification reason for Algo Orders
            # This ensuring Telegram alerts show "TP_CLOSE" or "STOP_LOSS" instead of "MARKET_FILL"
            order_type = getattr(order_update, 'type', '')
            if order_type == 'TAKE_PROFIT_MARKET':
                with self._pending_exit_reasons_lock:
                    self._pending_exit_reasons[symbol] = 'TP_CLOSE'
                self.logger.info(f"🏷️ Set exit reason (Auto): {symbol} -> TP_CLOSE")
            elif order_type == 'STOP_MARKET':
                with self._pending_exit_reasons_lock:
                    self._pending_exit_reasons[symbol] = 'STOP_LOSS'
                self.logger.info(f"🏷️ Set exit reason (Auto): {symbol} -> STOP_LOSS")

            # v5.5.0 FIX: REMOVED duplicate _record_fill_to_local_tracker call
            # This handler used CUMULATIVE data (z=filled_quantity, ap=average_price)
            # which inflated tracker quantities and broke is_fully_closed detection.
            # user_data_stream.py:658 already calls with CORRECT individual fill data
            # (l=last_filled_qty, L=last_filled_price). Single handler = correct PnL.

            # Check if this is a pending limit order
            if symbol in self.pending_orders:
                pending = self.pending_orders[symbol]

                # Get ACTUAL filled quantity (not pending.quantity)
                actual_filled_qty = order_update.filled_quantity

                # Log fill type
                if status == 'PARTIALLY_FILLED':
                    remaining_qty = pending.quantity - actual_filled_qty
                    self.logger.warning(
                        f"⚠️ PARTIAL FILL: {symbol} @ {order_update.average_price} | "
                        f"Filled: {actual_filled_qty:.6f} / {pending.quantity:.6f} | "
                        f"Remaining: {remaining_qty:.6f}"
                    )
                else:
                    self.logger.info(
                        f"🎯 LIMIT FILLED: {symbol} @ {order_update.average_price} | "
                        f"Qty: {actual_filled_qty:.6f}"
                    )

                # SOTA FIX (Jan 2026): Recalculate SL from actual fill price
                # Institutional Standard (Two Sigma, Renaissance, Citadel):
                # "Stop loss MUST be calculated from ACTUAL fill price, not theoretical signal price"
                #
                # Problem: SL was calculated from signal price, but entry filled at different price
                # due to slippage. This caused SL to be ABOVE entry for LONG (instant stop out).
                #
                # Solution: Recalculate SL from actual fill price, maintaining original risk distance.
                actual_fill_price = order_update.average_price
                original_sl_distance = abs(pending.entry_price - pending.stop_loss)

                if pending.entry_side == 'BUY':  # LONG
                    recalculated_sl = actual_fill_price - original_sl_distance
                else:  # SHORT
                    recalculated_sl = actual_fill_price + original_sl_distance

                # Log recalculation for debugging (only if significant difference)
                if abs(recalculated_sl - pending.stop_loss) > 0.0001:
                    self.logger.info(
                        f"📐 SL Recalculated: {symbol} | "
                        f"Signal SL: {pending.stop_loss:.4f} → New SL: {recalculated_sl:.4f} | "
                        f"Fill: {actual_fill_price:.4f}, Distance: {original_sl_distance:.4f}"
                    )

                # SOTA (Jan 2026): Broadcast position opened event for frontend subscription
                try:
                    event_bus = get_event_bus()
                    event_bus.publish_position_opened({
                        'symbol': symbol,
                        'side': 'LONG' if pending.entry_side == 'BUY' else 'SHORT',
                        'entry_price': order_update.average_price,
                        'quantity': actual_filled_qty,  # Use actual filled qty
                        'stop_loss': recalculated_sl,  # Use recalculated SL
                        'take_profit': pending.take_profit
                    })
                except Exception as e:
                    self.logger.debug(f"Position event broadcast failed: {e}")

                # Place bracket orders (SL/TP) for ACTUAL filled quantity with RECALCULATED SL
                try:
                    bracket_result = self.client.place_bracket_orders(
                        symbol=symbol,
                        entry_side=OrderSide.BUY if pending.entry_side == 'BUY' else OrderSide.SELL,
                        quantity=actual_filled_qty,  # CRITICAL: Use actual filled qty, not pending.quantity
                        stop_loss=recalculated_sl,  # CRITICAL: Use recalculated SL from fill price
                        take_profit=pending.take_profit
                    )

                    # SOTA: Store bracket order IDs for OCO management
                    sl_order = bracket_result.get('sl_order')
                    tp_order = bracket_result.get('tp_order')

                    if sl_order or tp_order:
                        self._bracket_orders[symbol] = {
                            'sl_order_id': sl_order.order_id if sl_order else None,
                            'tp_order_id': tp_order.order_id if tp_order else None
                        }

                        # SOTA Hybrid (Jan 2026): Initialize watermarks for display
                        # Local tracking ensures accurate SL/TP display regardless of cache state
                        self._position_watermarks[symbol] = {
                            'highest': order_update.average_price,
                            'lowest': order_update.average_price,
                            'current_sl': recalculated_sl,  # Use recalculated SL
                            'tp_target': pending.take_profit,
                            'entry_price': order_update.average_price
                        }
                        self.logger.debug(f"📦 Watermarks initialized for {symbol}: SL={recalculated_sl}, TP={pending.take_profit}")

                        # SOTA FIX (Jan 2026): Persist recalculated SL to DB for restart recovery
                        # Critical: Without this, watermarks restored from DB after restart will have OLD SL
                        # This ensures complete fix - exchange SL is correct AND DB has correct SL
                        if self.order_repo:
                            try:
                                # Extract ATR from pending signal metadata (if available)
                                atr_value = 0
                                if hasattr(pending, 'signal') and hasattr(pending.signal, 'metadata'):
                                    atr_value = pending.signal.metadata.get('atr', 0)

                                # Get leverage from active position (just filled)
                                leverage = self.max_leverage  # Default
                                pos = self.active_positions.get(symbol.upper())
                                if pos:
                                    leverage = pos.leverage

                                # Persist position with recalculated SL
                                self.order_repo.save_live_position(
                                    symbol=symbol,
                                    side='LONG' if pending.entry_side == 'BUY' else 'SHORT',
                                    entry_price=actual_fill_price,
                                    quantity=actual_filled_qty,
                                    leverage=leverage,
                                    stop_loss=recalculated_sl,  # ✅ Persist recalculated SL
                                    take_profit=pending.take_profit,
                                    atr=atr_value
                                )
                                self.logger.info(
                                    f"💾 Persisted recalculated SL to DB: {symbol} | "
                                    f"SL: {recalculated_sl:.4f}, Entry: {actual_fill_price:.4f}"
                                )
                            except Exception as e:
                                self.logger.warning(f"⚠️ Failed to persist recalculated SL to DB: {e}")

                    if sl_order:
                        self.logger.info(
                            f"🛡️ SL placed: {pending.stop_loss} (#{sl_order.order_id}) | "
                            f"Qty: {actual_filled_qty:.6f}"
                        )
                    if tp_order:
                        self.logger.info(
                            f"🎯 TP placed: {pending.take_profit} (#{tp_order.order_id}) | "
                            f"Qty: {actual_filled_qty:.6f}"
                        )

                except Exception as e:
                    self.logger.error(f"Failed to place brackets after fill: {e}")

                # SOTA FIX: Handle pending order cleanup based on fill status
                if status == 'FILLED':
                    # Fully filled → Remove from pending
                    del self.pending_orders[symbol]
                    self.logger.debug(f"✅ Pending order fully filled and removed: {symbol}")
                elif status == 'PARTIALLY_FILLED':
                    # Partially filled → Update remaining quantity
                    remaining_qty = pending.quantity - actual_filled_qty
                    pending.quantity = remaining_qty
                    self.logger.debug(
                        f"📝 Pending order updated: {symbol} | "
                        f"Remaining qty: {remaining_qty:.6f}"
                    )

                # Refresh positions
                self._refresh_positions()

            # SOTA: OCO Management - Check if this is a bracket order filling
            elif order_update.is_reduce_only and symbol in self._bracket_orders:
                brackets = self._bracket_orders[symbol]

                # Determine which bracket filled and cancel the other
                if order_id == brackets.get('sl_order_id'):
                    # SL filled → Cancel TP
                    tp_id = brackets.get('tp_order_id')
                    if tp_id:
                        try:
                            self.client.cancel_order(symbol, tp_id)
                            self.logger.info(f"🔄 OCO: SL filled → TP cancelled (#{tp_id})")
                        except Exception as e:
                            self.logger.warning(f"Failed to cancel TP: {e}")

                elif order_id == brackets.get('tp_order_id'):
                    # TP filled → Cancel SL
                    sl_id = brackets.get('sl_order_id')
                    if sl_id:
                        try:
                            self.client.cancel_order(symbol, sl_id)
                            self.logger.info(f"🔄 OCO: TP filled → SL cancelled (#{sl_id})")
                        except Exception as e:
                            self.logger.warning(f"Failed to cancel SL: {e}")

                # Cleanup bracket tracking and watermarks
                del self._bracket_orders[symbol]
                if symbol in self._position_watermarks:
                    del self._position_watermarks[symbol]
                    self.logger.debug(f"🧹 Cleaned up watermarks for {symbol}")

                # Refresh positions
                self._refresh_positions()

        elif status == 'CANCELED':
            # Remove from pending if cancelled
            if symbol in self.pending_orders:
                del self.pending_orders[symbol]
                self.logger.info(f"📝 Pending order removed: {symbol}")

    # =========================================================================
    # POSITION MANAGEMENT
    # =========================================================================

    def close_position(self, symbol: str) -> LiveTradeResult:
        """
        Close an open position with SOTA Order Splitting.

        v5.5.0: FAST/DEFERRED pattern matching close_position_async and _close_position_market.
        Handles positions larger than MAX_QTY by splitting into batch orders.
        """
        # SOTA FIX (Jan 2026 - Bug #20): Move import to top of method
        from ...infrastructure.api.binance_futures_client import FuturesOrder

        if self.mode == TradingMode.PAPER:
            return LiveTradeResult(success=True)

        symbol_upper = symbol.upper()

        # v5.5.0: Mark symbol as closing for ghost prevention
        self._closing_symbols.add(symbol_upper)
        self._closing_symbols_ts[symbol_upper] = time.time()

        try:
            # 1. Refresh & Get Position
            self._refresh_positions()
            pos = self.active_positions.get(symbol_upper)

            if not pos or pos.position_amt == 0:
                self._closing_symbols.discard(symbol_upper)
                self._closing_symbols_ts.pop(symbol_upper, None)
                return LiveTradeResult(success=False, error="No position to close")

            qty = abs(pos.position_amt)
            side = "LONG" if pos.position_amt > 0 else "SHORT"
            close_side = "SELL" if side == "LONG" else "BUY"

            # Set exit reason for deferred path (only if not already set by caller)
            if symbol_upper not in self._pending_exit_reasons:
                self._pending_exit_reasons[symbol_upper] = 'MANUAL'

            # 2. Cancel ALL Open Orders (regular + algo)
            try:
                self._cleanup_all_orders_for_symbol(symbol, reason="MANUAL")
            except Exception as e:
                self.logger.warning(f"Failed to cancel open orders before close: {e}")

            # 3. Split Quantity using MARKET_LOT_SIZE
            qty_chunks = []
            if self.filter_service:
                qty_chunks = self.filter_service.split_quantity_market(symbol, qty)
                self.logger.info(f"🔀 CLOSE SPLIT: {symbol} qty={qty} → {qty_chunks}")
            else:
                qty_chunks = [qty]

            # 4. Execute Batch Close
            batch_payload = []
            for chunk in qty_chunks:
                sanitized_qty = chunk
                if self.filter_service:
                    sanitized_qty = self.filter_service.sanitize_quantity(symbol, chunk)

                order_params = {
                    "symbol": symbol_upper,
                    "side": close_side,
                    "type": "MARKET",
                    "quantity": str(sanitized_qty),
                    "reduceOnly": "true"
                }
                batch_payload.append(order_params)

            BATCH_SIZE = 5
            orders_created = []

            for i in range(0, len(batch_payload), BATCH_SIZE):
                sub_batch = batch_payload[i:i + BATCH_SIZE]
                results = self.client.create_batch_orders(sub_batch)
                orders_created.extend(results)

            self.logger.info(f"🔒 Position closed: {symbol} ({len(qty_chunks)} orders)")

            # Broadcast position closed event
            try:
                event_bus = get_event_bus()
                exit_price = 0
                if orders_created and len(orders_created) > 0:
                    o = orders_created[0]
                    exit_price = float(o.get('avgPrice', 0)) if isinstance(o, dict) else 0
                event_bus.publish_position_closed({
                    'symbol': symbol,
                    'exit_price': exit_price,
                    'reason': 'MANUAL'
                })
            except Exception as e:
                self.logger.debug(f"Position event broadcast failed: {e}")

            # v5.5.0 FIX: FAST vs DEFERRED path based on exit_price
            if exit_price > 0:
                # ── FAST PATH: exit_price available → do everything inline ──
                if symbol_upper in self.active_positions:
                    del self.active_positions[symbol_upper]

                pnl = 0.0
                with self._local_positions_lock:
                    tracker = self._local_positions.get(symbol_upper)
                    if tracker:
                        pnl = tracker.get_realized_pnl(exit_price)

                try:
                    from .position_monitor_service import get_position_monitor
                    monitor = get_position_monitor()
                    monitor.stop_monitoring(symbol)
                except Exception as mon_err:
                    self.logger.debug(f"Stop monitoring cleanup: {mon_err}")

                if self.order_repo:
                    self.order_repo.close_live_position(symbol_upper, exit_price, pnl, 'MANUAL')
                    self.logger.info(f"💾 DB position closed: {symbol_upper} PnL=${pnl:.2f}")

                self._send_exit_notification(symbol_upper, exit_price, pnl, 'MANUAL')

                try:
                    if hasattr(self, 'circuit_breaker') and self.circuit_breaker:
                        self.circuit_breaker.record_trade_with_time(
                            symbol_upper, side, pnl,
                            datetime.now(timezone.utc)
                        )
                        self.logger.debug(f"🛡️ CB updated: {symbol} {side} PnL=${pnl:.2f}")
                except Exception as cb_err:
                    self.logger.warning(f"⚠️ CB update failed (non-critical): {cb_err}")

                # CSV buffer
                with self._local_positions_lock:
                    tracker = self._local_positions.get(symbol_upper)
                if tracker:
                    self._add_to_csv_buffer(symbol_upper, tracker, exit_price, pnl, 'MANUAL')

                # v6.3.0: Analytics collection (fire-and-forget)
                if self._analytics_collector:
                    try:
                        asyncio.create_task(self._analytics_collector.collect_after_close(symbol_upper))
                    except Exception:
                        pass

                with self._local_positions_lock:
                    self._local_positions.pop(symbol_upper, None)

                self._notified_entry_symbols.discard(symbol_upper)
                self._exit_notified_symbols.discard(symbol_upper)
                self._closing_symbols.discard(symbol_upper)
                self._closing_symbols_ts.pop(symbol_upper, None)

                if symbol_upper in self._pending_exit_reasons:
                    del self._pending_exit_reasons[symbol_upper]

            else:
                # ── DEFERRED PATH: exit_price=0 → wait for WebSocket fills ──
                self.logger.warning(
                    f"⚠️ DEFERRED CLOSE: {symbol_upper} exit_price=0, "
                    f"waiting for WebSocket fills to complete CB/DB/notification"
                )
                # Do NOT delete active_positions or _local_positions
                # Do NOT discard from _closing_symbols (deferred path needs it)
                self.logger.info(f"✅ LOCAL EXIT: {symbol} closed via MARKET")

            # Return the first order as representative result
            first_order = None
            if orders_created and isinstance(orders_created[0], dict) and 'orderId' in orders_created[0]:
                o = orders_created[0]
                first_order = FuturesOrder(
                    order_id=o.get('orderId'),
                    client_order_id=o.get('clientOrderId', ''),
                    symbol=o.get('symbol'),
                    side=o.get('side'),
                    type=o.get('type'),
                    status=o.get('status'),
                    price=float(o.get('price', 0)),
                    quantity=float(o.get('origQty', 0)),
                    executed_qty=float(o.get('executedQty', 0)),
                    avg_price=float(o.get('avgPrice', 0)),
                    time_in_force=o.get('timeInForce', ''),
                    reduce_only=True
                )

            return LiveTradeResult(success=True, order=first_order)

        except Exception as e:
            self.logger.error(f"Failed to close position: {e}")
            self._closing_symbols.discard(symbol_upper)
            self._closing_symbols_ts.pop(symbol_upper, None)
            return LiveTradeResult(success=False, error=str(e))

    def partial_close_position(self, symbol: str, price: float, pct: float) -> LiveTradeResult:
        """
        SOTA (Jan 2026): Partial close position - Close percentage of position.

        Used by PositionMonitorService for TP1 60% close.
        Matches Backtest ExecutionSimulator behavior.

        Args:
            symbol: Trading pair
            price: Current price (for logging)
            pct: Percentage to close (0.0 to 1.0, e.g., 0.60 = 60%)

        Returns:
            LiveTradeResult with success/error
        """
        self.logger.info(
            f"🎯 PARTIAL CLOSE CALLED: {symbol} @ ${price:.4f} | "
            f"Close {pct*100}% | Mode: {self.mode.value}"
        )

        if self.mode == TradingMode.PAPER:
            self.logger.info(f"📄 PAPER: Partial close {symbol} {pct*100}%")
            return LiveTradeResult(success=True)

        try:
            # 1. Get current position
            self._refresh_positions()
            pos = self.active_positions.get(symbol.upper())

            if not pos or pos.position_amt == 0:
                self.logger.warning(f"⚠️ PARTIAL CLOSE: No position found for {symbol}")
                return LiveTradeResult(success=False, error="No position to close")

            full_qty = abs(pos.position_amt)
            close_qty = full_qty * pct

            self.logger.info(
                f"📊 PARTIAL CLOSE: {symbol} | Full qty: {full_qty} | "
                f"Close qty: {close_qty} ({pct*100}%)"
            )

            # 2. Validate minimum quantity
            if self.filter_service:
                min_qty = self.filter_service.get_min_quantity(symbol)
                if close_qty < min_qty:
                    self.logger.warning(f"Partial close qty {close_qty} < minQty {min_qty}, closing full position")
                    return self.close_position(symbol)

            side = "LONG" if pos.position_amt > 0 else "SHORT"
            close_side = "SELL" if side == "LONG" else "BUY"

            # 3. Sanitize quantity
            sanitized_qty = close_qty
            if self.filter_service:
                sanitized_qty = self.filter_service.sanitize_quantity(symbol, close_qty)

            self.logger.info(
                f"📤 SENDING PARTIAL CLOSE ORDER: {symbol} {close_side} {sanitized_qty} @ MARKET"
            )

            # 4. Execute MARKET order with reduceOnly
            # Note: OrderSide, OrderType already imported from binance_futures_client at top
            order = self.client.create_order(
                symbol=symbol.upper(),
                side=OrderSide.SELL if close_side == "SELL" else OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=sanitized_qty,
                reduce_only=True
            )

            self.logger.info(
                f"✅ PARTIAL CLOSE SUCCESS: {symbol} {pct*100}% ({sanitized_qty} of {full_qty}) @ ${price:.4f} | "
                f"Order ID: {order.order_id if order else 'N/A'}"
            )

            # ═══════════════════════════════════════════════════════════════════════
            # SOTA FIX (Jan 2026 - Bug #10): Update TP order quantity after partial close
            #
            # Problem: After partial close 60%, TP order still has 100% quantity
            # If TP hits → Binance rejects "Insufficient position size"
            #
            # Solution: Cancel old TP, place new TP with remaining quantity
            # ═══════════════════════════════════════════════════════════════════════

            # Calculate remaining quantity
            remaining_qty = full_qty - sanitized_qty

            self.logger.info(
                f"📊 PARTIAL CLOSE: Remaining qty = {remaining_qty} ({(1-pct)*100}%)"
            )

            # Update TP order if exists (LOCAL-FIRST mode may not have exchange TP)
            # Check watermarks for TP target
            symbol_upper = symbol.upper()
            watermark = self._position_watermarks.get(symbol_upper, {})
            tp_target = watermark.get('tp_target', 0)

            if tp_target > 0:
                self.logger.info(
                    f"🎯 Updating TP order for remaining position: {symbol} "
                    f"qty={remaining_qty} @ ${tp_target:.4f}"
                )

                # Get old TP order ID if exists
                old_tp_order_id = watermark.get('tp_order_id')

                # Cancel old TP order
                if old_tp_order_id:
                    try:
                        self.client.cancel_algo_order(symbol, str(old_tp_order_id))
                        self.logger.info(f"🗑️ OLD TP CANCELLED: {old_tp_order_id}")
                    except Exception as cancel_err:
                        self.logger.warning(f"⚠️ Failed to cancel old TP: {cancel_err}")

                # Place new TP order with remaining quantity
                try:
                    # Determine TP side (opposite of position side)
                    tp_side = OrderSide.SELL if side == "LONG" else OrderSide.BUY

                    # Sanitize remaining quantity
                    sanitized_remaining = remaining_qty
                    if self.filter_service:
                        sanitized_remaining = self.filter_service.sanitize_quantity(symbol, remaining_qty)

                    # Place new TP order
                    new_tp_order = self.client.create_algo_order(
                        symbol=symbol,
                        side=tp_side,
                        order_type=OrderType.TAKE_PROFIT_MARKET,
                        quantity=sanitized_remaining,
                        stop_price=tp_target,
                        reduce_only=True
                    )

                    if new_tp_order:
                        new_tp_id = new_tp_order.get('algoId') or new_tp_order.get('orderId')
                        self.logger.info(
                            f"✅ NEW TP PLACED: {symbol} qty={sanitized_remaining} @ ${tp_target:.4f} "
                            f"(AlgoID: {new_tp_id})"
                        )

                        # Update watermark with new TP order ID
                        if symbol_upper in self._position_watermarks:
                            self._position_watermarks[symbol_upper]['tp_order_id'] = str(new_tp_id)
                    else:
                        self.logger.warning(f"⚠️ Failed to place new TP for {symbol}")

                except Exception as tp_err:
                    self.logger.error(f"❌ Failed to update TP order: {tp_err}")
            else:
                self.logger.debug(f"ℹ️ No TP target for {symbol}, skipping TP update")

            # SOTA FIX (Jan 2026): Update watermark tp_hit_count for state sync
            if symbol_upper in self._position_watermarks:
                self._position_watermarks[symbol_upper]['tp_hit_count'] = \
                    self._position_watermarks[symbol_upper].get('tp_hit_count', 0) + 1
                self.logger.debug(f"📊 Watermark tp_hit_count updated for {symbol_upper}")

            return LiveTradeResult(success=True, order=order)

        except Exception as e:
            self.logger.error(f"❌ PARTIAL CLOSE FAILED: {symbol} | Error: {e}", exc_info=True)
            return LiveTradeResult(success=False, error=str(e))

    async def partial_close_position_async(
        self,
        symbol: str,
        price: float,
        pct: float
    ) -> LiveTradeResult:
        """
        SOTA (Jan 2026): Async partial close for minimal latency.

        Used by PositionMonitorService async handlers for TP1 60% close.
        Uses direct async execution without thread pool overhead.

        Args:
            symbol: Trading pair
            price: Current price (for logging)
            pct: Percentage to close (0.0 to 1.0)

        Returns:
            LiveTradeResult with success/error
        """
        import time
        start_time = time.perf_counter()

        self.logger.info(
            f"🎯 ASYNC PARTIAL CLOSE: {symbol} @ ${price:.4f} | Close {pct*100}%"
        )

        if self.mode == TradingMode.PAPER:
            return LiveTradeResult(success=True)

        try:
            # Get current position
            pos = self.active_positions.get(symbol.upper())

            if not pos or pos.position_amt == 0:
                self.logger.warning(f"⚠️ ASYNC PARTIAL CLOSE: No position for {symbol}")
                return LiveTradeResult(success=False, error="No position to close")

            full_qty = abs(pos.position_amt)
            close_qty = full_qty * pct

            # Validate minimum quantity
            if self.filter_service:
                min_qty = self.filter_service.get_min_quantity(symbol)
                if close_qty < min_qty:
                    self.logger.warning(f"Partial close qty {close_qty} < minQty {min_qty}")
                    return await self.close_position_async(symbol)

            side = "LONG" if pos.position_amt > 0 else "SHORT"
            close_side = "SELL" if side == "LONG" else "BUY"

            # Sanitize quantity
            sanitized_qty = close_qty
            if self.filter_service:
                sanitized_qty = self.filter_service.sanitize_quantity(symbol, close_qty)

            # Execute via async client if available
            if self.async_client:
                order = await self.async_client.create_order(
                    symbol=symbol.upper(),
                    side=close_side,
                    type='MARKET',
                    quantity=sanitized_qty,
                    reduce_only=True
                )
            else:
                # Fallback to sync (not ideal but works)
                order = self.client.create_order(
                    symbol=symbol.upper(),
                    side=OrderSide.SELL if close_side == "SELL" else OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=sanitized_qty,
                    reduce_only=True
                )

            latency_ms = (time.perf_counter() - start_time) * 1000
            self.logger.info(
                f"⚡ ASYNC PARTIAL CLOSE LATENCY: {symbol} = {latency_ms:.1f}ms | "
                f"Closed {pct*100}% ({sanitized_qty})"
            )

            if latency_ms > 100:
                self.logger.warning(f"⚠️ HIGH LATENCY: {symbol} partial close = {latency_ms:.1f}ms")

            return LiveTradeResult(success=True, order=order)

        except Exception as e:
            self.logger.error(f"❌ ASYNC PARTIAL CLOSE FAILED: {symbol} | {e}", exc_info=True)
            return LiveTradeResult(success=False, error=str(e))

    async def close_position_async(self, symbol_or_pos, reason: str = "MANUAL") -> LiveTradeResult:
        """
        SOTA (Jan 2026): Async close position for minimal latency.

        Used by PositionMonitorService async handlers for SL exit.

        SOTA FIX Phase 5 (Jan 2026): Close Mutex
        - Prevent duplicate close attempts for same symbol
        - Use asyncio.Lock for thread-safe close operations
        - Track symbols currently being closed in _closing_symbols set

        SOTA FIX (Feb 2026): Duck Typing - Accept both string and object
        - String: symbol name directly
        - Object: PositionAdapter/MonitoredPosition with .symbol attribute
        """
        import time

        # SOTA FIX (Feb 2026): Duck typing - accept both string and object
        if isinstance(symbol_or_pos, str):
            symbol = symbol_or_pos
        else:
            # Object with .symbol attribute (PositionAdapter, MonitoredPosition)
            symbol = symbol_or_pos.symbol
            # Also extract reason if not provided
            if reason == "MANUAL" and hasattr(symbol_or_pos, 'reason'):
                reason = symbol_or_pos.reason

        start_time = time.perf_counter()

        symbol_upper = symbol.upper()

        # SOTA (Jan 2026): Set exit reason for Telegram
        # FIX P1 (Feb 13, 2026): Use symbol_upper to match WebSocket lookup keys
        if reason and reason != "MANUAL":
            self._pending_exit_reasons[symbol_upper] = reason

        # SOTA FIX Phase 5 (Jan 2026): Close Mutex - Check if already closing
        # v6.1.0 FIX: Add 60s timeout to prevent permanent MUTEX deadlock.
        # OLD BUG: _closing_symbols had no TTL → once set by DEFERRED path,
        # ALL other close attempts blocked forever → zombie position for 27+ min.
        async with self._close_lock:
            if symbol_upper in self._closing_symbols:
                added_time = self._closing_symbols_ts.get(symbol_upper, 0)
                elapsed = time.time() - added_time if added_time > 0 else 0
                if elapsed < 60:
                    self.logger.warning(
                        f"⚠️ CLOSE MUTEX: {symbol_upper} already being closed ({elapsed:.0f}s ago), skipping"
                    )
                    return LiveTradeResult(success=False, error="Already closing")
                else:
                    self.logger.warning(
                        f"⏰ CLOSE MUTEX TIMEOUT: {symbol_upper} stuck for {elapsed:.0f}s, allowing retry"
                    )
                    self._closing_symbols.discard(symbol_upper)
                    self._closing_symbols_ts.pop(symbol_upper, None)

            # Add to closing set with timestamp
            self._closing_symbols.add(symbol_upper)
            self._closing_symbols_ts[symbol_upper] = time.time()

        try:
            self.logger.info(f"🔴 ASYNC CLOSE: {symbol_upper}")

            if self.mode == TradingMode.PAPER:
                return LiveTradeResult(success=True)

            pos = self.active_positions.get(symbol_upper)

            if not pos or pos.position_amt == 0:
                return LiveTradeResult(success=False, error="No position to close")

            qty = abs(pos.position_amt)
            side = "LONG" if pos.position_amt > 0 else "SHORT"
            close_side = "SELL" if side == "LONG" else "BUY"

            # Cancel ALL open orders (regular + algo/backup SL)
            try:
                self._cleanup_all_orders_for_symbol(symbol_upper, reason="ASYNC_CLOSE")
            except Exception as e:
                self.logger.warning(f"⚠️ Failed to cleanup orders before async close {symbol_upper}: {e}")

            # Sanitize quantity
            sanitized_qty = qty
            if self.filter_service:
                sanitized_qty = self.filter_service.sanitize_quantity(symbol_upper, qty)

            # Execute via async client if available
            if self.async_client:
                order = await self.async_client.create_order(
                    symbol=symbol_upper,
                    side=close_side,
                    type='MARKET',
                    quantity=sanitized_qty,
                    reduce_only=True
                )
            else:
                # Fallback to sync
                order = self.client.create_order(
                    symbol=symbol_upper,
                    side=OrderSide.SELL if close_side == "SELL" else OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=sanitized_qty,
                    reduce_only=True
                )

            latency_ms = (time.perf_counter() - start_time) * 1000
            self.logger.info(
                f"⚡ ASYNC CLOSE LATENCY: {symbol_upper} = {latency_ms:.1f}ms"
            )

            if latency_ms > 100:
                self.logger.warning(f"⚠️ HIGH LATENCY: {symbol_upper} close = {latency_ms:.1f}ms")

            # SOTA (Jan 2026): Broadcast position closed event for frontend subscription
            try:
                event_bus = get_event_bus()
                exit_price = 0
                if order:
                    exit_price = float(order.get('avgPrice', 0)) if isinstance(order, dict) else (order.avg_price if hasattr(order, 'avg_price') else 0)
                event_bus.publish_position_closed({
                    'symbol': symbol_upper,
                    'exit_price': exit_price,
                    'reason': 'ASYNC_CLOSE'
                })
            except Exception as e:
                self.logger.debug(f"Position event broadcast failed: {e}")

            # v5.5.0 FIX 2: FAST vs DEFERRED path based on exit_price
            if exit_price > 0:
                # ── FAST PATH: exit_price available → do everything inline ──
                if symbol_upper in self.active_positions:
                    del self.active_positions[symbol_upper]

                pnl = 0.0
                try:
                    if hasattr(self, 'circuit_breaker') and self.circuit_breaker:
                        with self._local_positions_lock:
                            tracker = self._local_positions.get(symbol_upper)
                            if tracker:
                                pnl = tracker.get_realized_pnl(exit_price)
                        self.circuit_breaker.record_trade_with_time(
                            symbol_upper, side, pnl,
                            datetime.now(timezone.utc)
                        )
                        self.logger.debug(f"🛡️ CB updated: {symbol_upper} {side} PnL=${pnl:.2f}")
                except Exception as cb_err:
                    self.logger.warning(f"⚠️ CB update failed (non-critical): {cb_err}")

                try:
                    if self.order_repo:
                        self.order_repo.close_live_position(symbol_upper, exit_price, pnl, reason)
                        self.logger.info(f"💾 DB position closed: {symbol_upper} PnL=${pnl:.2f}")
                except Exception as db_err:
                    self.logger.warning(f"⚠️ DB persist failed (non-critical): {db_err}")

                self._send_exit_notification(symbol_upper, exit_price, pnl, reason)

                try:
                    from .position_monitor_service import get_position_monitor
                    monitor = get_position_monitor()
                    monitor.stop_monitoring(symbol_upper)
                except Exception as mon_err:
                    self.logger.debug(f"Stop monitoring cleanup: {mon_err}")

                # CSV buffer (v5.5.0)
                with self._local_positions_lock:
                    tracker = self._local_positions.get(symbol_upper)
                if tracker:
                    self._add_to_csv_buffer(symbol_upper, tracker, exit_price, pnl, reason)

                # v6.3.0: Analytics collection (fire-and-forget)
                if self._analytics_collector:
                    try:
                        asyncio.create_task(self._analytics_collector.collect_after_close(symbol_upper))
                    except Exception:
                        pass

                with self._local_positions_lock:
                    self._local_positions.pop(symbol_upper, None)

                self._notified_entry_symbols.discard(symbol_upper)
                self._exit_notified_symbols.discard(symbol_upper)

                # Fast path done — release closing mutex
                self._closing_symbols.discard(symbol_upper)
                self._closing_symbols_ts.pop(symbol_upper, None)

            else:
                # ── DEFERRED PATH: exit_price=0 → wait for WebSocket fills ──
                # Only cancel orders. Keep _closing_symbols SET so
                # _record_fill_to_local_tracker → _complete_deferred_close() fires.
                self.logger.warning(
                    f"⚠️ DEFERRED CLOSE: {symbol_upper} exit_price=0, "
                    f"waiting for WebSocket fills to complete CB/DB/notification"
                )
                # Do NOT delete active_positions or _local_positions here
                # Do NOT discard from _closing_symbols (deferred path needs it)

            return LiveTradeResult(success=True, order=order)

        except Exception as e:
            self.logger.error(f"❌ ASYNC CLOSE FAILED: {symbol_upper} | {e}", exc_info=True)
            # On exception, always release the mutex
            self._closing_symbols.discard(symbol_upper)
            self._closing_symbols_ts.pop(symbol_upper, None)
            return LiveTradeResult(success=False, error=str(e))

        finally:
            # v5.5.0: Only discard if NOT in deferred path (deferred path keeps it)
            # Fast path already discarded above; exception path discarded above
            pass

    async def _execute_partial_close_async(
        self,
        symbol: str,
        side: str,
        quantity: float,
        reason: str
    ) -> bool:
        """
        SOTA SYNC (Jan 2026): Async partial close for TP1 60% close.

        Matches ExecutionSimulator._take_partial_profit behavior.

        Args:
            symbol: Trading pair
            side: 'BUY' or 'SELL' (exit side)
            quantity: Amount to close
            reason: e.g., "TAKE_PROFIT_1"

        Returns:
            True if successful
        """
        try:
            if not self.async_client:
                self.logger.warning(f"No async client for partial close")
                return False

            # Sanitize quantity
            sanitized_qty = quantity
            if self.filter_service:
                sanitized_qty = self.filter_service.sanitize_quantity(symbol, quantity)
                min_qty = self.filter_service.get_min_quantity(symbol)
                if sanitized_qty < min_qty:
                    self.logger.warning(f"⚠️ Partial close qty {sanitized_qty} < minQty {min_qty}, skipping")
                    return False

            # Execute MARKET order with reduceOnly
            # SOTA FIX (Jan 2026): Use 'type' not 'order_type' - matches AsyncBinanceFuturesClient.create_order() signature
            order = await self.async_client.create_order(
                symbol=symbol.upper(),
                side=side,
                type='MARKET',
                quantity=sanitized_qty,
                reduce_only=True
            )

            self.logger.info(
                f"🎯 PARTIAL CLOSE ({reason}): {symbol} {side} {sanitized_qty:.6f} @ MARKET"
            )
            return True

        except Exception as e:
            self.logger.error(f"❌ Partial close failed: {e}")
            return False

    def close_all_positions(self, reason: str = "MANUAL") -> List[LiveTradeResult]:
        """Close all open positions."""
        results = []
        for symbol in list(self.active_positions.keys()):
            # SOTA (Jan 2026): Set exit reason for Telegram
            self._pending_exit_reasons[symbol] = reason

            result = self.close_position(symbol)
            results.append(result)
        return results

    def force_close_dead_zone_positions(self):
        """
        v6.5.12: Force-close ALL open positions when inside a Dead Zone.

        LIVE data (Feb 18-23, 117 trades) shows DZ-overlap trades perform terribly:
        - Clean trades: 78.5% WR, +$12.58
        - DZ-overlap: 41.7% WR, -$12.30 (108% of total losses)

        Called by periodic async task (60s interval) in main.py.
        Gate: dz_force_close_enabled setting (default: True).
        """
        # Check if feature is enabled
        if not getattr(self, 'dz_force_close_enabled', True):
            return

        # Check if we have circuit breaker with blocked windows
        if not hasattr(self, 'circuit_breaker') or not self.circuit_breaker:
            return

        # Check if we're in a dead zone
        is_blocked, reason = self.circuit_breaker.is_in_blocked_window(
            datetime.now(timezone.utc)
        )

        if not is_blocked:
            # Reset cooldown tracker when outside DZ
            self._last_dz_force_close_log = None
            return

        # We're in a dead zone — check if there are positions to close
        if not self.active_positions:
            # Log once per DZ window to avoid spam
            if not getattr(self, '_last_dz_force_close_log', None):
                self._last_dz_force_close_log = datetime.now(timezone.utc)
                self.logger.info(f"DZ Force-Close: In dead zone ({reason}), no open positions")
            return

        # Force-close all positions
        position_count = len(self.active_positions)
        symbols_to_close = list(self.active_positions.keys())
        self.logger.warning(
            f"DZ FORCE-CLOSE: Closing {position_count} positions "
            f"(dead zone: {reason}): {symbols_to_close}"
        )

        closed_count = 0
        for symbol in symbols_to_close:
            try:
                self._pending_exit_reasons[symbol.upper()] = "DZ_FORCE_CLOSE"
                self.close_position(symbol)
                closed_count += 1
            except Exception as e:
                self.logger.error(f"DZ Force-Close failed for {symbol}: {e}")

        # Telegram summary
        if self.telegram_service and closed_count > 0:
            try:
                self.telegram_service.send_message(
                    f"DZ Force-Close: Closed {closed_count}/{position_count} positions "
                    f"({reason})",
                    silent=False
                )
            except Exception as e:
                self.logger.warning(f"DZ Force-Close Telegram failed: {e}")

        self._last_dz_force_close_log = datetime.now(timezone.utc)

    async def get_all_positions_async(self) -> List[FuturesPosition]:
        """SOTA: Async wrapper for get_all_positions."""
        import asyncio
        return await asyncio.to_thread(self.get_all_positions)

    def get_all_positions(self) -> List[FuturesPosition]:
        """Get all current positions."""
        if self.mode == TradingMode.PAPER:
            return []
        self._refresh_positions()
        return list(self.active_positions.values())

    def get_blocked_short_count(self) -> int:
        """Get number of blocked SHORT signals this session (Layer 3)."""
        return self._blocked_short_signals

    def get_filter_metrics(
        self,
        signal_generator=None,
        shark_tank_coordinator=None
    ) -> ShortSignalFilterMetrics:
        """
        Get SHORT signal filter metrics from all 3 layers.

        Args:
            signal_generator: SignalGenerator instance (Layer 1)
            shark_tank_coordinator: SharkTankCoordinator instance (Layer 2)

        Returns:
            ShortSignalFilterMetrics with counts from all layers
        """
        layer1_blocked = signal_generator.get_blocked_short_count() if signal_generator else 0
        layer2_blocked = shark_tank_coordinator.get_blocked_short_count() if shark_tank_coordinator else 0
        layer3_blocked = self._blocked_short_signals

        return ShortSignalFilterMetrics(
            layer1_blocked=layer1_blocked,
            layer2_blocked=layer2_blocked,
            layer3_blocked=layer3_blocked,
            total_blocked=layer1_blocked + layer2_blocked + layer3_blocked,
            session_start=datetime.now(timezone.utc),  # TODO: Track actual session start
            mode=self.mode.value
        )

    def update_trailing_stop(
        self,
        symbol: str,
        new_stop_loss: float,
        quantity: Optional[float] = None
    ) -> bool:
        """
        Update stop loss for an open position (trailing stop).

        SOTA: Institutional Grade Execution (Jan 2026).
        - Auto-Splitting: Handles positions > maxQty (e.g. 56.61 TAO -> 50 + 6.61)
        - Batch Execution: Uses batchOrders for atomic-like speed
        - Full Protection: Ensures 100% of the position is covered

        Args:
            symbol: Trading pair
            new_stop_loss: New stop loss price
            quantity: Position quantity (will fetch if not provided)

        Returns:
            True if successful
        """
        if not self.client:
            return False

        try:
            # 1. Cancel ALL existing stop orders for this symbol
            # This is cleaner than tracking individual IDs when orders get split/merged
            open_orders = self.client.get_open_orders(symbol)
            orders_to_cancel = []
            for order in open_orders:
                if order.get('type') in ('STOP_MARKET', 'STOP'):
                    orders_to_cancel.append(order.get('orderId'))

            if orders_to_cancel:
                # SOTA: Batch cancel if supported, or loop
                for oid in orders_to_cancel:
                    self.client.cancel_order(symbol, oid)
                self.logger.info(f"🔄 Cleaned {len(orders_to_cancel)} old SL orders for {symbol}")

            # 2. Get position info
            if quantity is None:
                self._refresh_positions()
                pos = self.active_positions.get(symbol)
                if not pos:
                    return False
                quantity = abs(pos.position_amt)
                entry_side = OrderSide.BUY if pos.position_amt > 0 else OrderSide.SELL
            else:
                # Assume LONG if updating manually
                entry_side = OrderSide.BUY

            # 3. Determine Exit Side
            exit_side = OrderSide.SELL if entry_side == OrderSide.BUY else OrderSide.BUY

            # 4. SOTA: Split Quantity Logic for STOP_MARKET orders
            # Uses MARKET_LOT_SIZE filter which has LOWER maxQty than LOT_SIZE!
            qty_chunks = []
            if self.filter_service:
                # DEBUG: Log market_max_qty being used
                filters = self.filter_service.get_filters(symbol)
                market_max = filters.market_max_qty if filters.market_max_qty else filters.max_qty
                self.logger.info(f"🔀 SPLIT DEBUG: {symbol} qty={quantity}, MARKET_maxQty={market_max}")

                # Use split_quantity_market for STOP_MARKET orders!
                qty_chunks = self.filter_service.split_quantity_market(symbol, quantity)
                self.logger.info(f"🔀 SPLIT RESULT: {symbol} → {qty_chunks}")
            else:
                qty_chunks = [quantity] # Fallback

            # 5. Prepare Batch Orders
            # Binance Batch Limit is 5 orders per request. If we have more, we loop batches.
            batch_payload = []

            # Common parameters
            # SOTA: Round price to exchange precision
            rounded_stop = new_stop_loss
            if self.filter_service:
                rounded_stop = self.filter_service.sanitize_price(symbol, new_stop_loss)

            for chunk in qty_chunks:
                # SOTA FIX: Sanitize qty to proper precision (prevents -1111)
                sanitized_qty = chunk
                if self.filter_service:
                    sanitized_qty = self.filter_service.sanitize_quantity(symbol, chunk)

                order_params = {
                    "symbol": symbol.upper(),
                    "side": exit_side.value,
                    "type": "STOP_MARKET",
                    "quantity": str(sanitized_qty),
                    "stopPrice": str(rounded_stop),
                    "reduceOnly": "true"
                }
                batch_payload.append(order_params)

            # 6. Execute Batches (Chunking by 5)
            # Pythonic way to yield chunks of 5
            BATCH_SIZE = 5
            for i in range(0, len(batch_payload), BATCH_SIZE):
                sub_batch = batch_payload[i:i + BATCH_SIZE]
                self.client.create_batch_orders(sub_batch)

            # SOTA Hybrid (Jan 2026): Update watermarks with new SL for accurate display
            if symbol in self._position_watermarks:
                self._position_watermarks[symbol]['current_sl'] = new_stop_loss
            else:
                # Initialize if missing (shouldn't happen but defensive)
                self._position_watermarks[symbol] = {
                    'current_sl': new_stop_loss,
                    'tp_target': 0.0
                }

            self.logger.info(
                f"🎢 TRAILING STOP updated: {symbol} SL → {new_stop_loss} "
                f"({len(qty_chunks)} orders, total {quantity})"
            )
            return True

        except Exception as e:
            return False

    async def update_trailing_stop_async(
        self,
        symbol: str,
        new_stop_loss: float,
        quantity: Optional[float] = None
    ) -> bool:
        """SOTA ASYNC: Update trailing stop on EXCHANGE (Cancel+Replace pattern)."""
        if not self.async_client:
            return False

        # SOTA (Jan 2026): Cooldown to prevent API spam
        symbol_upper = symbol.upper()
        import time as time_module
        watermark = self._position_watermarks.get(symbol_upper, {})
        last_update = watermark.get('last_sl_update', 0)
        if time_module.time() - last_update < 3.0:  # 3-second cooldown
            self.logger.debug(f"⏳ SL update cooldown: {symbol_upper} (wait 3s)")
            return True  # Not an error, just throttled

            # SOTA LOCAL_FIRST_MODE (Jan 2026): DISABLED entire exchange SL update
            # Backup SL -2% at entry is sufficient. Local SL managed by PositionMonitorService.
            # This prevents duplicate exchange orders from trailing/breakeven updates.
            self.logger.debug(f"🚫 Exchange SL update DISABLED for {symbol} (LOCAL_FIRST_MODE)")
            return True  # Return True to indicate "success" (no action needed)

        try:
            # SOTA (Jan 2026): "Make-before-Break" Pattern
            # 1. Fetch old orders first (to identify what to cancel later)
            # 2. Place NEW SL
            # 3. Only if (2) succeeds, Cancel OLD SL
            # This ensures we NEVER have a "naked" position during the API call window.

            # 1. Identify Old Orders
            open_orders = await self.async_client.get_open_orders(symbol)
            old_sl_orders = []
            for order in open_orders:
                if order.get('type') in ('STOP_MARKET', 'STOP'):
                     # Only track SL orders for this symbol
                     old_sl_orders.append(order.get('orderId'))
            # Also fetch Algo Orders (for the new API)
            try:
                open_algos = await self.async_client.get_open_algo_orders(symbol)

                # SOTA FIX (Jan 2026): Task 11.3 - Enhanced algo order fetch logging
                if open_algos:
                    from ...infrastructure.api.algo_order_parser import AlgoOrderParser
                    algo_types = {}
                    for ao in open_algos:
                        otype = AlgoOrderParser.get_order_type(ao)
                        algo_types[otype] = algo_types.get(otype, 0) + 1
                    self.logger.debug(
                        f"📋 Algo orders for {symbol}: {len(open_algos)} orders | Types: {algo_types}"
                    )

                for ao in open_algos:
                    if ao.get('type') == 'STOP_MARKET' or ao.get('orderType') == 'STOP_MARKET':
                        old_sl_orders.append(ao.get('algoId'))
            except Exception as e:
                self.logger.warning(f"Failed to fetch open algo orders: {e}")

            # 2. Get position info & calculate Qty
            if quantity is None:
                pos = self.active_positions.get(symbol_upper)
                if not pos:
                    await self._refresh_positions_async()
                    pos = self.active_positions.get(symbol_upper)

                if not pos:
                    self.logger.warning(f"⚠️ No position found for {symbol_upper}, cannot update SL")
                    return False
                quantity = abs(pos.position_amt)
            else:
                 # Check side even if qty provided
                 pos = self.active_positions.get(symbol_upper)

            if not pos or pos.position_amt == 0:
                 return False

            entry_side = OrderSide.BUY if pos.position_amt > 0 else OrderSide.SELL
            exit_side = OrderSide.SELL if entry_side == OrderSide.BUY else OrderSide.BUY

            # 3. Place NEW Algo Orders
            # ═══════════════════════════════════════════════════════════════════════
            # SOTA FIX (Jan 2026 - Bug #19): Add rollback mechanism for partial failures
            #
            # Problem: If order 2/3 fails, order 1 is already placed → Duplicate SL
            # Solution: Track placed orders, rollback on failure
            # ═══════════════════════════════════════════════════════════════════════
            qty_chunks = []
            if self.filter_service:
                qty_chunks = self.filter_service.split_quantity_market(symbol, quantity)
            else:
                qty_chunks = [quantity]

            new_order_ids = []  # Track placed orders for rollback

            try:
                for chunk in qty_chunks:
                    # Sanitize
                    sanitized_qty = chunk
                    if self.filter_service:
                        sanitized_qty = self.filter_service.sanitize_quantity(symbol, chunk)

                    # Sanitize Price
                    rounded_stop = new_stop_loss
                    if self.filter_service:
                        rounded_stop = self.filter_service.sanitize_price(symbol, new_stop_loss)

                    try:
                        # SOTA: Use async Algo Order API
                        result = await self.async_client.create_algo_order(
                            symbol=symbol.upper(),
                            side=exit_side.value,
                            order_type="STOP_MARKET",
                            quantity=float(sanitized_qty),
                            stop_price=float(rounded_stop),
                            reduce_only=True
                        )

                        # Track order ID for potential rollback
                        new_order_id = result.get('algoId') if result else None
                        if new_order_id:
                            new_order_ids.append(new_order_id)
                            self.logger.info(f"✅ NEW Trailing SL placed: {symbol} @ {rounded_stop} (AlgoID: {new_order_id})")
                        else:
                            raise Exception("Order returned None or missing algoId")

                    except Exception as place_error:
                        self.logger.error(f"❌ Failed to place NEW SL chunk for {symbol}: {place_error}")

                        # ROLLBACK: Cancel all newly placed orders
                        if new_order_ids:
                            self.logger.warning(f"🔄 ROLLBACK: Cancelling {len(new_order_ids)} newly placed SL orders")
                            for rollback_id in new_order_ids:
                                try:
                                    await self.async_client.cancel_algo_order(symbol, algo_id=rollback_id)
                                    self.logger.info(f"🗑️ ROLLBACK: Cancelled SL {rollback_id}")
                                except Exception as rollback_err:
                                    self.logger.error(f"❌ ROLLBACK failed for {rollback_id}: {rollback_err}")

                        # Return False - old SL remains (Safety First)
                        return False

            except Exception as outer_error:
                # Unexpected error during loop - rollback any placed orders
                self.logger.error(f"❌ Unexpected error placing SL orders: {outer_error}")
                if new_order_ids:
                    self.logger.warning(f"🔄 ROLLBACK: Cancelling {len(new_order_ids)} orders due to error")
                    for rollback_id in new_order_ids:
                        try:
                            await self.async_client.cancel_algo_order(symbol, algo_id=rollback_id)
                        except:
                            pass
                return False

            # 4. Cancel Old Orders (Only if ALL new ones placed successfully)
            if new_order_ids and old_sl_orders:
                self.logger.info(f"🔄 Cancelling {len(old_sl_orders)} old SL orders for {symbol} (Make-before-Break success)")
                cancel_failures = []

                for oid in old_sl_orders:
                    try:
                        # Try to cancel as Algo Order first (most likely for SOTA logic)
                        await self.async_client.cancel_algo_order(symbol, algo_id=oid)
                        self.logger.debug(f"🗑️ Cancelled old SL (algo): {oid}")
                    except Exception as algo_err:
                        # Fallback to standard cancel (for migration)
                        try:
                            await self.async_client.cancel_order(symbol, order_id=oid)
                            self.logger.debug(f"🗑️ Cancelled old SL (regular): {oid}")
                        except Exception as regular_err:
                            # Log failure but don't fail the operation
                            # Old order may have already filled or been cancelled
                            cancel_failures.append((oid, str(regular_err)))

                if cancel_failures:
                    self.logger.warning(
                        f"⚠️ {len(cancel_failures)} old SL orders failed to cancel: {cancel_failures[:3]}"
                    )
                    # Don't fail - new SL is in place (safety priority)

            # Legacy batch placement code removed - replaced by Make-before-Break logic above

            # Update internal watermark with new SL and timestamp
            symbol_upper = symbol.upper()
            import time as time_module
            if symbol_upper in self._position_watermarks:
                self._position_watermarks[symbol_upper]['current_sl'] = new_stop_loss
                self._position_watermarks[symbol_upper]['last_sl_update'] = time_module.time()
            else:
                self._position_watermarks[symbol_upper] = {
                    'current_sl': new_stop_loss,
                    'tp_target': 0.0,
                    'last_sl_update': time_module.time()
                }

            return True

        except Exception as e:
            self.logger.error(f"Failed to update trailing stop (Async): {e}")
            return False

    def get_available_margin(self) -> float:
        """
        Get available margin for new positions.

        SOTA: Uses cached balance (updated by get_portfolio) for instant lookup.
        Avoids API calls during SharkTankCoordinator signal processing.
        Falls back to API only on startup when cache is empty.

        Returns:
            Available balance in USDT
        """
        # SOTA: Use cached value if available (instant, no API call)
        if self._cached_available > 0:
            return self._cached_available

        # Fallback: API call only on startup before first get_portfolio
        if not self.client:
            return 0.0

        try:
            account_info = self.client.get_account_info()
            available = float(account_info.get('availableBalance', 0))
            # Update cache for next time
            self._cached_available = available
            return available
        except Exception as e:
            self.logger.error(f"Failed to get available margin: {e}")
            return 0.0

    async def get_portfolio_async(self) -> dict:
        """
        SOTA v2 (Jan 2026): Request Coalescing for Portfolio.

        Problem: 20+ concurrent requests each making 3 Binance API calls = 50s cascade
        Solution: Use asyncio.Lock so only 1 request fetches, others wait for same result

        Flow:
        1. Fast path: Return cached data if fresh (< 5s)
        2. Acquire lock (blocks other concurrent callers)
        3. Double-check cache (another caller may have fetched while we waited)
        4. Fetch from Binance (only 1 caller does this)
        5. Update cache and release lock
        6. All waiting callers get the same fresh data
        """
        import asyncio
        import time

        # Fast path: cache hit (no lock needed)
        if hasattr(self, '_portfolio_cache') and self._portfolio_cache:
            cache_age = time.time() - self._portfolio_cache_time
            if cache_age < self.PORTFOLIO_CACHE_TTL:
                self.logger.debug(f"📦 Portfolio cache hit (age: {cache_age:.1f}s)")
                return self._portfolio_cache

        # Lazy init lock (must be in async context)
        if self._portfolio_fetch_lock is None:
            self._portfolio_fetch_lock = asyncio.Lock()

        async with self._portfolio_fetch_lock:
            # Double-check after acquiring lock (another thread may have fetched)
            if hasattr(self, '_portfolio_cache') and self._portfolio_cache:
                cache_age = time.time() - self._portfolio_cache_time
                if cache_age < self.PORTFOLIO_CACHE_TTL:
                    self.logger.debug(f"📦 Portfolio cache hit after lock (age: {cache_age:.1f}s)")
                    return self._portfolio_cache

            # Only ONE caller fetches from Binance
            self.logger.info("🔄 Portfolio fetch: acquiring Binance data...")
            result = await asyncio.to_thread(self.get_portfolio)

            # Note: get_portfolio() already updates cache internally
            return result

    def get_portfolio(self) -> dict:
        """
        Get portfolio data from Binance.

        SOTA: Mode-aware portfolio for frontend display.
        Returns real balance, positions, and orders from Binance.

        Returns:
            dict with balance, equity, positions, pending_orders
        """
        # SOTA: Enhanced logging to diagnose position loading issues
        self.logger.info(f"📊 get_portfolio called: mode={self.mode}, client={'OK' if self.client else 'None'}")

        if self.mode == TradingMode.PAPER or not self.client:
            self.logger.warning(f"⚠️ Returning empty portfolio: mode={self.mode}, has_client={bool(self.client)}")
            return {
                'balance': 0,
                'equity': 0,
                'unrealized_pnl': 0,
                'realized_pnl': 0,
                'open_positions_count': 0,
                'open_positions': [],
                'pending_orders': []
            }

        # SOTA FIX (Jan 2026): TTL Cache - Return cached data if fresh
        # Prevents 32s cascading delays when frontend polls every 5s
        import time
        current_time = time.time()
        if hasattr(self, '_portfolio_cache') and self._portfolio_cache:
            cache_age = current_time - self._portfolio_cache_time
            if cache_age < self.PORTFOLIO_CACHE_TTL:
                self.logger.debug(f"📦 Portfolio cache hit (age: {cache_age:.1f}s)")
                return self._portfolio_cache

        try:
            # SOTA FIX v4 (Jan 2026): Use cached balance when available
            # Problem: get_account_info() takes 150-200ms per call
            # Solution: Use _cached_balance (set on init, updated by UserDataStream ACCOUNT_UPDATE)

            # Debug: Log cache state
            self.logger.debug(f"📦 Cache state: init={self._local_cache_initialized}, balance={self._cached_balance:.2f}")

            # Use cache if initialized (balance might be 0 for empty accounts)
            if self._local_cache_initialized:
                # Use cached values - instant response!
                # SOTA FIX (Jan 2026 - Bug #21): Thread-safe cache read
                with self._balance_lock:
                    balance = self._cached_balance
                    available = self._cached_available

                # Calculate unrealized PnL from cached positions
                unrealized_pnl = sum(
                    p.unrealized_pnl if hasattr(p, 'unrealized_pnl') else 0
                    for p in self._cached_positions_list
                )
                equity = balance + unrealized_pnl

                self.logger.debug(f"📦 Using cached balance: ${balance:.2f}")
            else:
                # Fallback: API call only when cache not initialized
                self.logger.info("🔄 Portfolio fetch: acquiring Binance data...")
                account_info = self.client.get_account_info()

                # USDT-M Futures uses USDT as primary currency
                balance = float(account_info.get('totalWalletBalance', 0))
                unrealized_pnl = float(account_info.get('totalUnrealizedProfit', 0))
                equity = float(account_info.get('totalMarginBalance', balance + unrealized_pnl))
                available = float(account_info.get('availableBalance', 0))

                # Update cache for future calls
                # SOTA FIX (Jan 2026 - Bug #21): Thread-safe cache write
                with self._balance_lock:
                    self._cached_balance = balance
                    self._cached_available = available

            # Get positions - use cache if initialized, else refresh
            # SOTA FIX: Check flag ONLY. Do not check if list is truthy (empty list is valid!)
            if self._local_cache_initialized:
                positions = self._cached_positions_list
            else:
                self._refresh_positions()
                positions = list(self.active_positions.values())

            # SOTA FIX v3: Use cached open orders instead of API call
            # This eliminates ~150ms API call per portfolio request
            # Cache is updated via WebSocket ORDER_TRADE_UPDATE events
            if self._local_cache_initialized:
                open_orders = list(self._cached_open_orders.values())

                # SOTA FIX (Jan 2026): Also check watermarks for TP/SL values
                # Algo Orders may not be in _cached_open_orders if ALGO_UPDATE
                # event is not properly caching them. Watermarks are the
                # authoritative local source for SL/TP after signal execution.
                # NOTE: exchange_tpsl_map below will overlay with actual Binance
                # orders if present, so this is just a fallback.

                self.logger.debug(f"📦 Using cached orders: {len(open_orders)} orders")
            else:
                # Fallback to API if cache not initialized
                open_orders = self.client.get_open_orders()
                self.logger.warning("📡 Cache not initialized, using API for orders")

            # ═══════════════════════════════════════════════════════════════════
            # SOTA DUAL TP/SL ARCHITECTURE (Jan 2026)
            # Builds SEPARATE maps for transparency:
            # 1. exchange_tpsl: From actual STOP_MARKET/TAKE_PROFIT_MARKET orders
            # 2. local_tpsl: From our watermarks + DB (signal-based tracking)
            # ═══════════════════════════════════════════════════════════════════

            # Step 1: Build EXCHANGE TP/SL map (actual orders on Binance)
            exchange_tpsl_map = {}
            exchange_order_ids = {}

            # SOTA (Jan 2026): Fetch ALGO orders separately (backup SL)
            # Regular get_open_orders() doesn't include algo/conditional orders since Dec 2025
            algo_orders = []
            try:
                if hasattr(self.client, 'get_open_algo_orders'):
                    algo_orders = self.client.get_open_algo_orders() or []

                    # SOTA FIX (Jan 2026): Task 11.3 - Enhanced algo order fetch logging
                    if algo_orders:
                        from ...infrastructure.api.algo_order_parser import AlgoOrderParser
                        algo_symbols = set(AlgoOrderParser.get_symbol(o) for o in algo_orders)
                        algo_types = {}
                        for o in algo_orders:
                            otype = AlgoOrderParser.get_order_type(o)
                            algo_types[otype] = algo_types.get(otype, 0) + 1
                        self.logger.info(
                            f"📋 Algo orders fetched: {len(algo_orders)} orders | "
                            f"Symbols: {', '.join(algo_symbols)} | "
                            f"Types: {algo_types}"
                        )
                    else:
                        self.logger.debug("📋 No algo orders found")
            except Exception as e:
                self.logger.warning(f"⚠️ Could not fetch algo orders: {e}")

            # Combine regular + algo orders
            all_orders = list(open_orders) + list(algo_orders)

            for o in all_orders:
                # Handle both dict (algo) and FuturesOrder object formats
                if isinstance(o, dict):
                    sym = o.get('symbol', '')
                    order_type = o.get('type', '')
                    # Algo orders use 'triggerprice' instead of 'stopPrice'
                    stop_price = float(o.get('stopPrice', 0) or o.get('triggerprice', 0) or o.get('triggerPrice', 0) or 0)
                    order_id = str(o.get('orderId', '') or o.get('algoId', '') or '')
                else:
                    sym = getattr(o, 'symbol', '')
                    order_type = getattr(o, 'type', '')
                    stop_price = getattr(o, 'stop_price', 0) or 0
                    order_id = str(getattr(o, 'order_id', '') or '')

                if not sym:
                    continue

                if sym not in exchange_tpsl_map:
                    exchange_tpsl_map[sym] = {'stop_loss': None, 'take_profit': None}
                    exchange_order_ids[sym] = {'sl_order_id': None, 'tp_order_id': None}

                if order_type == 'STOP_MARKET':
                    exchange_tpsl_map[sym]['stop_loss'] = stop_price
                    exchange_order_ids[sym]['sl_order_id'] = order_id
                elif order_type == 'TAKE_PROFIT_MARKET':
                    exchange_tpsl_map[sym]['take_profit'] = stop_price
                    exchange_order_ids[sym]['tp_order_id'] = order_id

            # Step 2: Build LOCAL TP/SL map (from watermarks + pending_orders)
            # SOTA Local-First (Jan 2026): Include backup_sl and local_first_mode
            local_tpsl_map = {}
            for symbol, watermark in self._position_watermarks.items():
                local_sl = watermark.get('current_sl', 0) or 0
                local_tp = watermark.get('tp_target', 0) or 0
                backup_sl = watermark.get('backup_sl', 0) or 0  # SOTA: Backup SL on exchange
                local_first = watermark.get('local_first_mode', False)  # SOTA: Local-First mode flag

                local_tpsl_map[symbol] = {
                    'stop_loss': local_sl if local_sl > 0 else None,
                    'take_profit': local_tp if local_tp > 0 else None,
                    'backup_sl': backup_sl if backup_sl > 0 else None,  # SOTA: Exchange backup
                    'local_first_mode': local_first,  # SOTA: Flag for Local-First positions
                    'source': 'watermark'
                }

            # Overlay pending_orders (just-filled positions)
            for symbol, pending_info in self.pending_orders.items():
                if symbol not in local_tpsl_map:
                    local_tpsl_map[symbol] = {'stop_loss': None, 'take_profit': None, 'source': 'pending'}
                if pending_info.stop_loss and pending_info.stop_loss > 0:
                    if not local_tpsl_map[symbol]['stop_loss']:
                        local_tpsl_map[symbol]['stop_loss'] = pending_info.stop_loss
                        local_tpsl_map[symbol]['source'] = 'signal'
                if pending_info.take_profit and pending_info.take_profit > 0:
                    if not local_tpsl_map[symbol]['take_profit']:
                        local_tpsl_map[symbol]['take_profit'] = pending_info.take_profit

            # SOTA LocalSignalTracker: Include pending signals in local_tpsl_map
            # These are signals waiting to trigger (not yet filled)
            if self.signal_tracker:
                for symbol, sig in self.signal_tracker.get_all_pending().items():
                    if symbol not in local_tpsl_map:
                        local_tpsl_map[symbol] = {'stop_loss': None, 'take_profit': None, 'source': 'signal_tracker'}
                    if sig.stop_loss and sig.stop_loss > 0:
                        local_tpsl_map[symbol]['stop_loss'] = sig.stop_loss
                    if sig.take_profit and sig.take_profit > 0:
                        local_tpsl_map[symbol]['take_profit'] = sig.take_profit
                    local_tpsl_map[symbol]['source'] = 'signal_tracker'

            # Format positions for frontend with DUAL TP/SL structure
            formatted_positions = []
            for p in positions:
                # Get from both sources
                local_data = local_tpsl_map.get(p.symbol, {})
                exchange_data = exchange_tpsl_map.get(p.symbol, {})
                order_ids = exchange_order_ids.get(p.symbol, {})

                local_sl = local_data.get('stop_loss')
                local_tp = local_data.get('take_profit')
                exchange_sl = exchange_data.get('stop_loss')
                exchange_tp = exchange_data.get('take_profit')

                # EFFECTIVE TP/SL: Local takes priority (our tracking is source of truth)
                # Exchange overrides only if local is empty OR zero
                # SOTA FIX v2 (Jan 2026): Check local_sl > 0, not just truthy
                # This fixes bug where local_sl=0 (from incomplete watermark) caused fallback to exchange_sl
                effective_sl = local_sl if (local_sl and local_sl > 0) else exchange_sl
                effective_tp = local_tp if (local_tp and local_tp > 0) else exchange_tp

                # SOTA FIX v2 (Jan 2026): Add sl_source metadata for UI
                sl_source = 'local' if (local_sl and local_sl > 0) else ('exchange_backup' if exchange_sl else 'none')
                tp_source = 'local' if (local_tp and local_tp > 0) else ('exchange' if exchange_tp else 'none')

                # Orphan detection: No local tracking AND no exchange orders
                is_orphan = not bool(local_sl or local_tp)

                formatted_positions.append({
                    'id': f"live_{p.symbol}",
                    'symbol': p.symbol,
                    'side': 'LONG' if p.position_amt > 0 else 'SHORT',
                    'size': abs(p.position_amt),
                    'entry_price': p.entry_price,
                    'current_price': p.mark_price,
                    'margin': p.margin,
                    'leverage': p.leverage,
                    'pnl': p.unrealized_pnl,
                    'roe': (p.unrealized_pnl / p.margin * 100) if p.margin > 0 else 0,
                    'liquidation_price': p.liquidation_price,

                    # SOTA DUAL TP/SL: Separate sources for transparency
                    # SOTA Local-First (Jan 2026): Include backup_sl for display
                    'local_tpsl': {
                        'stop_loss': local_sl,
                        'take_profit': local_tp,
                        'backup_sl': local_data.get('backup_sl'),  # SOTA: Exchange backup (-2%)
                        'local_first_mode': local_data.get('local_first_mode', False),
                        'source': local_data.get('source', 'unknown')
                    },
                    'exchange_tpsl': {
                        'stop_loss': exchange_sl,
                        'take_profit': exchange_tp,
                        'sl_order_id': order_ids.get('sl_order_id'),
                        'tp_order_id': order_ids.get('tp_order_id'),
                        'is_backup_only': local_data.get('local_first_mode', False)  # SOTA: Flag that exchange SL is backup
                    },

                    # Legacy fields (backward compatible) - uses effective values
                    'stop_loss': effective_sl,
                    'take_profit': effective_tp,
                    'is_live': True,
                    'is_orphan': is_orphan,
                    'local_first_mode': local_data.get('local_first_mode', False),  # SOTA: Top-level flag
                    # SOTA FIX v2 (Jan 2026): Add source metadata for UI debugging
                    'sl_source': sl_source,
                    'tp_source': tp_source
                })

            # Format pending orders - SOTA: Only show LIMIT orders (not SL/TP brackets)
            # SL/TP orders are shown in the positions table, not as "pending"
            formatted_orders = []
            for o in open_orders:
                # Handle dict format from Binance API
                if isinstance(o, dict):
                    order_type = o.get('type', '')
                    # SOTA: Skip bracket orders (SL/TP) - they're position protection, not pending entry
                    if order_type in ['STOP_MARKET', 'TAKE_PROFIT_MARKET', 'STOP', 'TAKE_PROFIT', 'TRAILING_STOP_MARKET']:
                        continue
                    # Only show LIMIT orders as pending
                    if order_type != 'LIMIT':
                        continue

                    order_id = o.get('orderId', o.get('order_id', ''))
                    symbol = o.get('symbol', '')

                    # Get SL/TP from local pending_orders state if available
                    pending_info = self.pending_orders.get(symbol.lower())
                    stop_loss = pending_info.stop_loss if pending_info else None
                    take_profit = pending_info.take_profit if pending_info else None

                    formatted_orders.append({
                        'id': str(order_id),
                        'signal_id': str(order_id)[:8],
                        'symbol': symbol,
                        'side': o.get('side', ''),
                        'entry_price': float(o.get('price', 0)),
                        'size': float(o.get('origQty', o.get('quantity', 0))),
                        'margin': float(o.get('price', 0)) * float(o.get('origQty', 0)) / 10,
                        'leverage': 10,
                        'is_live': True,
                        'created_at': None,
                        'expires_at': None,
                        'ttl_seconds': 0,
                        'stop_loss': stop_loss,
                        'take_profits': [take_profit] if take_profit else []
                    })
                else:
                    # Handle object format
                    order_type = o.type.value if hasattr(o.type, 'value') else o.type
                    # Skip bracket orders
                    if order_type in ['STOP_MARKET', 'TAKE_PROFIT_MARKET', 'STOP', 'TAKE_PROFIT', 'TRAILING_STOP_MARKET']:
                        continue
                    if order_type != 'LIMIT':
                        continue

                    symbol = o.symbol
                    pending_info = self.pending_orders.get(symbol.lower())
                    stop_loss = pending_info.stop_loss if pending_info else None
                    take_profit = pending_info.take_profit if pending_info else None

                    formatted_orders.append({
                        'id': str(o.order_id),
                        'signal_id': str(o.order_id)[:8],
                        'symbol': symbol,
                        'side': o.side.value if hasattr(o.side, 'value') else o.side,
                        'entry_price': o.price,
                        'size': o.quantity,
                        'margin': o.price * o.quantity / 10,
                        'leverage': 10,
                        'is_live': True,
                        'created_at': None,
                        'expires_at': None,
                        'ttl_seconds': 0,
                        'stop_loss': stop_loss,
                        'take_profits': [take_profit] if take_profit else []
                    })

            result = {
                'balance': balance,
                'equity': equity,
                'available': available,  # USDT available for new positions
                'unrealized_pnl': unrealized_pnl,
                'realized_pnl': 0,  # Would need trade history
                'open_positions_count': len(positions),
                'open_positions': formatted_positions,
                'pending_orders': formatted_orders
            }

            # SOTA FIX: Update cache
            self._portfolio_cache = result
            self._portfolio_cache_time = current_time

            return result

        except Exception as e:
            self.logger.error(f"Failed to get portfolio: {e}")
            return {
                'balance': 0,
                'equity': 0,
                'unrealized_pnl': 0,
                'realized_pnl': 0,
                'open_positions_count': 0,
                'open_positions': [],
                'pending_orders': [],
                'error': str(e)
            }

    async def get_trade_history_async(self, limit: int = 100, symbol: Optional[str] = None) -> dict:
        """SOTA: Async wrapper for get_trade_history."""
        import asyncio
        return await asyncio.to_thread(self.get_trade_history, limit, symbol)

    def get_trade_history(self, limit: int = 100, symbol: Optional[str] = None) -> dict:
        """
        Get trade history from Binance.

        SOTA: Uses income API for realized P&L to match paper trading format.
        Returns formatted trade list with proper entry/exit data.
        """
        if self.mode == TradingMode.PAPER or not self.client:
            return {
                'trades': [],
                'total': 0,
                'page': 1,
                'total_pages': 0,
                'trading_mode': 'PAPER'
            }

        try:
            # SOTA: Use income history for realized P&L (cleaner data)
            income_data = self.client.get_income_history(
                income_type='REALIZED_PNL',
                limit=limit
            )

            # Also get user trades for additional details
            raw_trades = self.client.get_trade_history(symbol=symbol, limit=limit)

            # Build lookup for trade details
            trade_lookup = {}
            for t in raw_trades:
                trade_id = str(t.get('id', ''))
                trade_lookup[trade_id] = t

            # Format trades from income data
            trades = []
            for item in income_data:
                pnl = float(item.get('income', 0) or 0)
                sym = item.get('symbol', 'UNKNOWN')
                trade_time = item.get('time', 0)

                # Try to find matching trade for additional info
                info = item.get('info', '')

                trades.append({
                    'id': str(item.get('tranId', '')),
                    'symbol': sym,
                    'side': 'LONG' if pnl > 0 else 'SHORT',  # Infer from P&L
                    'entry_price': 0,  # Not available from income API
                    'exit_price': 0,   # Not available from income API
                    'quantity': 0,     # Not available from income API
                    'realized_pnl': pnl,
                    'pnl': pnl,
                    'commission': 0,
                    'open_time': trade_time,
                    'close_time': trade_time,
                    'exit_reason': 'REALIZED_PNL',
                    'is_live': True
                })

            # If income data is empty, fallback to user trades
            if not trades and raw_trades:
                for t in raw_trades:
                    price = float(t.get('price', 0) or 0)
                    qty = float(t.get('qty', 0) or 0)
                    pnl = float(t.get('realizedPnl', 0) or 0)

                    trades.append({
                        'id': str(t.get('id', '')),
                        'symbol': t.get('symbol', 'UNKNOWN'),
                        'side': 'LONG' if t.get('side') == 'BUY' else 'SHORT',
                        'entry_price': price,
                        'exit_price': price,
                        'quantity': qty,
                        'realized_pnl': pnl,
                        'pnl': pnl,
                        'commission': float(t.get('commission', 0) or 0),
                        'open_time': t.get('time', 0),
                        'close_time': t.get('time', 0),
                        'exit_reason': 'BINANCE_TRADE',
                        'is_live': True
                    })

            return {
                'trades': trades,
                'total': len(trades),
                'page': 1,
                'total_pages': 1,
                'trading_mode': self.mode.value if hasattr(self.mode, 'value') else 'LIVE'
            }

        except Exception as e:
            self.logger.error(f"Failed to get trade history: {e}")
            return {
                'trades': [],
                'total': 0,
                'page': 1,
                'total_pages': 0,
                'trading_mode': 'LIVE',
                'error': str(e)
            }

    async def get_performance_async(self, days: int = 7) -> dict:
        """SOTA: Async wrapper for get_performance."""
        import asyncio
        return await asyncio.to_thread(self.get_performance, days)

    # NOTE: close_position_async REMOVED - duplicate definition deleted (Feb 2026)
    # The main close_position_async at line ~5369 now handles both string and object via duck typing

    def get_performance(self, days: int = 7) -> dict:
        """
        Calculate performance metrics from Binance trade history.
        SOTA: Returns full analytics matching PAPER mode response format.
        """
        if self.mode == TradingMode.PAPER or not self.client:
            return self._empty_performance('PAPER')

        try:
            # Get income history (realized P&L)
            income = self.client.get_income_history(income_type='REALIZED_PNL', limit=500)

            wins = 0
            losses = 0
            total_profit = 0
            total_loss = 0
            pnl_list = []
            per_symbol: dict = {}

            for item in income:
                pnl = float(item.get('income', 0))
                symbol = item.get('symbol', 'UNKNOWN')
                pnl_list.append(pnl)

                # Per-symbol stats
                if symbol not in per_symbol:
                    per_symbol[symbol] = {'wins': 0, 'losses': 0, 'total_pnl': 0, 'count': 0}
                per_symbol[symbol]['count'] += 1
                per_symbol[symbol]['total_pnl'] += pnl

                if pnl > 0:
                    wins += 1
                    total_profit += pnl
                    per_symbol[symbol]['wins'] += 1
                elif pnl < 0:
                    losses += 1
                    total_loss += abs(pnl)
                    per_symbol[symbol]['losses'] += 1

            total_trades = wins + losses
            win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
            profit_factor = (total_profit / total_loss) if total_loss > 0 else 0
            total_pnl = total_profit - total_loss

            # Calculate expectancy (average P&L per trade)
            expectancy = (total_pnl / total_trades) if total_trades > 0 else 0

            # Calculate average win/loss
            avg_win = (total_profit / wins) if wins > 0 else 0
            avg_loss = (total_loss / losses) if losses > 0 else 0

            # Format per_symbol output
            per_symbol_formatted = {}
            for sym, stats in per_symbol.items():
                sym_win_rate = (stats['wins'] / stats['count'] * 100) if stats['count'] > 0 else 0
                per_symbol_formatted[sym] = {
                    'symbol': sym,
                    'total_trades': stats['count'],
                    'winning_trades': stats['wins'],
                    'losing_trades': stats['losses'],
                    'win_rate': round(sym_win_rate, 2),
                    'total_pnl': round(stats['total_pnl'], 2),
                    'profit_factor': 0,  # Would need more data to calculate
                    'long_trades': 0,
                    'short_trades': 0,
                    'long_win_rate': 0,
                    'short_win_rate': 0,
                    'best_side': '-'
                }

            # Calculate streak stats
            current_streak = 0
            max_wins = 0
            max_losses = 0
            temp_streak = 0

            for pnl in pnl_list:
                if pnl > 0:
                    if temp_streak > 0:
                        temp_streak += 1
                    else:
                        temp_streak = 1
                    max_wins = max(max_wins, temp_streak)
                elif pnl < 0:
                    if temp_streak < 0:
                        temp_streak -= 1
                    else:
                        temp_streak = -1
                    max_losses = max(max_losses, abs(temp_streak))
            current_streak = temp_streak

            return {
                'win_rate': round(win_rate, 2),
                'profit_factor': round(profit_factor, 2),
                'total_pnl': round(total_pnl, 2),
                'total_trades': total_trades,
                'winning_trades': wins,
                'losing_trades': losses,
                'expectancy': round(expectancy, 2),
                'average_win': round(avg_win, 2),
                'average_loss': round(avg_loss, 2),
                'average_rr': round(avg_win / avg_loss, 2) if avg_loss > 0 else 0,
                'max_drawdown': 0,  # Would need equity curve to calculate
                'largest_win': round(max(pnl_list), 2) if pnl_list else 0,
                'largest_loss': round(min(pnl_list), 2) if pnl_list else 0,
                'per_symbol': per_symbol_formatted,
                'risk_metrics': {
                    'sharpe_ratio': 0,
                    'sortino_ratio': 0,
                    'calmar_ratio': 0,
                    'recovery_factor': 0
                },
                'streak_stats': {
                    'current_streak': current_streak,
                    'max_consecutive_wins': max_wins,
                    'max_consecutive_losses': max_losses,
                    'avg_winner_duration_minutes': 0,
                    'avg_loser_duration_minutes': 0
                },
                'exit_reason_stats': {},
                'trading_mode': self.mode.value if hasattr(self.mode, 'value') else 'LIVE'
            }

        except Exception as e:
            self.logger.error(f"Failed to get performance: {e}")
            return self._empty_performance('LIVE', str(e))

    def _empty_performance(self, mode: str, error: str = None) -> dict:
        """Return empty performance metrics with proper structure."""
        result = {
            'win_rate': 0,
            'profit_factor': 0,
            'total_pnl': 0,
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'expectancy': 0,
            'average_win': 0,
            'average_loss': 0,
            'average_rr': 0,
            'max_drawdown': 0,
            'largest_win': 0,
            'largest_loss': 0,
            'per_symbol': {},
            'risk_metrics': {
                'sharpe_ratio': 0,
                'sortino_ratio': 0,
                'calmar_ratio': 0,
                'recovery_factor': 0
            },
            'streak_stats': {
                'current_streak': 0,
                'max_consecutive_wins': 0,
                'max_consecutive_losses': 0,
                'avg_winner_duration_minutes': 0,
                'avg_loser_duration_minutes': 0
            },
            'exit_reason_stats': {},
            'trading_mode': mode
        }
        if error:
            result['error'] = error
        return result

    def _refresh_positions(self):
        """Refresh position cache from exchange."""
        import time  # For TTL-based watermark cleanup

        if not self.client:
            self.logger.warning("⚠️ _refresh_positions: No client available")
            return

        try:
            positions = self.client.get_positions()
            self.logger.debug(f"📈 Fetched {len(positions)} non-zero positions from Binance")

            # SOTA FIX (Jan 2026): Preserve Local Watermarks (TP/SL)
            # Binance API does not return our local TP/SL targets, so we must merge them back
            new_active_positions = {}
            for p in positions:
                self.logger.debug(f"   - {p.symbol}: amt={p.position_amt}, entry=${p.entry_price:.2f}, PnL=${p.unrealized_pnl:.2f}")

                # Check for existing watermark
                if p.symbol in self._position_watermarks:
                     wm = self._position_watermarks[p.symbol]
                     # Inject local metadata into the FuturesPosition object (it has dynamic __dict__)
                     # Note: FuturesPosition is a dataclass, so we can't add arbitrary fields easily unless we set them on the dict
                     # But get_portfolio() below uses _position_watermarks to enrich the display anyway.
                     # The REAL issue is if get_portfolio() logic is correct.
                     pass

                new_active_positions[p.symbol] = p

            self.active_positions = new_active_positions

            # ═══════════════════════════════════════════════════════════════════════
            # SOTA FIX (Jan 2026 - Bug #18): TTL-based watermark cleanup
            #
            # Problem: If PositionMonitor crashes, watermark never gets cleaned → Memory leak
            # Solution: Add TTL (1 hour) - cleanup watermarks older than TTL
            # ═══════════════════════════════════════════════════════════════════════
            WATERMARK_TTL_SECONDS = 3600  # 1 hour

            stale_symbols = []
            current_time = time.time()

            for sym in list(self._position_watermarks.keys()):
                if sym not in self.active_positions:
                    # Double check pending orders - don't delete if it's a pending setup!
                    if sym not in self.pending_orders:
                        # SOTA FIX (Jan 2026): Also check PositionMonitor
                        # Position may be monitored but not yet in active_positions due to API sync delay
                        if self.position_monitor and self.position_monitor.get_position(sym):
                            # Position is being monitored - DO NOT DELETE watermark!
                            self.logger.debug(f"⚠️ Skipping watermark cleanup for {sym} - still being monitored")
                            continue

                        # NEW: TTL-based cleanup for orphaned watermarks
                        watermark = self._position_watermarks[sym]
                        last_update = watermark.get('last_sl_update', 0)
                        age = current_time - last_update

                        if age > WATERMARK_TTL_SECONDS:
                            self.logger.warning(
                                f"🧹 Removing stale watermark for {sym} (TTL expired: {age:.0f}s > {WATERMARK_TTL_SECONDS}s)"
                            )
                            stale_symbols.append(sym)
                        else:
                            # Watermark is recent but position is gone - may be temporary API sync issue
                            # Keep watermark for now, will be cleaned up by TTL later if truly stale
                            self.logger.debug(
                                f"⏳ Keeping watermark for {sym} (age: {age:.0f}s < TTL {WATERMARK_TTL_SECONDS}s)"
                            )

            for sym in stale_symbols:
                self.logger.info(f"🧹 Removing stale TP/SL watermark for {sym} (Position closed)")
                del self._position_watermarks[sym]
                # Also stop monitoring
                if self.position_monitor:
                    self.position_monitor.stop_monitoring(sym)
        except Exception as e:
            self.logger.error(f"❌ Failed to refresh positions: {e}")

    # =========================================================================
    # RISK MANAGEMENT
    # =========================================================================

    def _calculate_position_size(
        self,
        symbol: str,
        entry_price: float,
        stop_loss: float
    ) -> float:
        """
        Calculate position size based on risk.

        SOTA: Now matches backtest ExecutionSimulator.place_order logic:
        1. Slot-based capital allocation (balance / max_positions)
        2. Risk-based sizing OR fixed leverage
        3. Leverage cap per symbol
        4. Min notional pre-check ($5 for Binance Futures)
        """
        if not self.client:
            return 0

        # SOTA: Use cached balance (updated by get_portfolio every 10s)
        # Avoids redundant API calls during signal processing
        # SOTA FIX (Jan 2026 - Bug #21): Thread-safe cache read
        with self._balance_lock:
            wallet_balance = self._cached_balance
            available_balance = self._cached_available

        # Fallback: API call only if cache is empty (first signal before get_portfolio)
        if wallet_balance <= 0:
            try:
                account_info = self.client.get_account_info()
                wallet_balance = float(account_info.get('totalWalletBalance', 0))
                available_balance = float(account_info.get('availableBalance', 0))
                # Update cache
                # SOTA FIX (Jan 2026 - Bug #21): Thread-safe cache write
                with self._balance_lock:
                    self._cached_balance = wallet_balance
                    self._cached_available = available_balance
            except Exception as e:
                self.logger.error(f"Failed to get balance: {e}")
                return 0

        if wallet_balance <= 0:
            return 0

        # SOTA: Slot-based capital allocation (matches backtest)
        # Divide total balance evenly across max positions
        capital_per_slot = wallet_balance / self.max_positions
        allocated_capital = min(capital_per_slot, available_balance)

        if allocated_capital <= 0:
            self.logger.warning(f"⚠️ No available capital for {symbol}")
            return 0

        # Calculate SL distance
        sl_distance = abs(entry_price - stop_loss)
        if sl_distance == 0:
            return 0

        sl_dist_pct = sl_distance / entry_price
        if sl_dist_pct < 0.005:  # SL too tight (< 0.5%)
            self.logger.warning(f"⚠️ {symbol}: SL too tight ({sl_dist_pct:.2%}), skipping")
            return 0

        # Risk-based position sizing
        # Risk 1% of slot capital per trade
        risk_amount = allocated_capital * self.risk_per_trade
        notional = risk_amount / sl_dist_pct

        # Effective leverage from risk-based sizing
        effective_leverage = notional / allocated_capital if allocated_capital > 0 else 0

        # Cap leverage to configured maximum
        if effective_leverage > self.max_leverage:
            notional = allocated_capital * self.max_leverage
            effective_leverage = self.max_leverage

        # SOTA: Per-Symbol Min Notional Check (matches backtest _validate_min_notional)
        # BTC/ETH have higher min_notional requirements from Binance
        symbol_upper = symbol.upper()
        if 'BTC' in symbol_upper:
            min_notional = 100.0  # BTC min_notional = $100
        elif 'ETH' in symbol_upper:
            min_notional = 20.0   # ETH min_notional = $20
        else:
            min_notional = 5.0    # Most altcoins = $5

        if notional < min_notional:
            self.logger.debug(f"⚠️ {symbol}: notional ${notional:.2f} < ${min_notional} min_notional, skipping")
            return 0

        # Pre-check margin requirement
        margin_required = notional / max(effective_leverage, 1.0)
        if margin_required > available_balance:
            self.logger.debug(
                f"⚠️ {symbol}: margin ${margin_required:.2f} > available ${available_balance:.2f}, skipping"
            )
            return 0

        # Convert to quantity
        quantity = notional / entry_price

        # SOTA P0: Use ExchangeFilterService for proper LOT_SIZE compliance
        # OLD (BUGGY):
        # if "BTC" in symbol:
        #     quantity = round(quantity, 3)
        # else:
        #     quantity = round(quantity, 2)

        # NEW: Dynamic sanitization based on exchange filters
        if self.filter_service and self.filter_service.is_loaded:
            quantity = self.filter_service.sanitize_quantity(symbol, quantity)

            # Pre-validate before returning
            is_valid, error = self.filter_service.validate_order(symbol, quantity, entry_price)
            if not is_valid:
                self.logger.warning(f"⚠️ Order validation failed: {error}")
                return 0  # Return 0 to trigger "Position size too small" error

            # SOTA: Second min_notional check AFTER LOT_SIZE rounding (matches backtest)
            # This catches edge cases where rounding reduces notional below minimum
            # Example: BTC @$90k, step=0.001: raw=0.00189 → rounded=0.001 → actual=$90 < min=$100
            actual_notional = quantity * entry_price
            if actual_notional < min_notional:
                self.logger.debug(
                    f"⚠️ {symbol}: actual_notional ${actual_notional:.2f} < ${min_notional} AFTER rounding, skipping"
                )
                return 0
        else:
            # Fallback (shouldn't happen in production)
            self.logger.warning("⚠️ Filter service not loaded, using fallback rounding")
            if "BTC" in symbol:
                quantity = round(quantity, 3)
            else:
                quantity = round(quantity, 2)

        return quantity

    def _check_safety_limits(self) -> bool:
        """Check if trading is within safe limits."""
        if not self.client:
            return True

        try:
            current_balance = self.client.get_usdt_balance()

            # Update peak
            if current_balance > self.peak_balance:
                self.peak_balance = current_balance

            # Check drawdown
            if self.peak_balance > 0:
                drawdown = (self.peak_balance - current_balance) / self.peak_balance
                if drawdown > self.max_drawdown_pct:
                    self.logger.warning(
                        f"⚠️ Max drawdown exceeded: {drawdown:.1%} > {self.max_drawdown_pct:.1%}"
                    )
                    self.enable_trading = False
                    return False

            return True

        except Exception as e:
            self.logger.error(f"Safety check failed: {e}")
            return False

    # =========================================================================
    # STATUS & MONITORING
    # =========================================================================

    def get_status(self) -> Dict[str, Any]:
        """Get current trading status."""
        balance = 0
        if self.client:
            balance = self.client.get_usdt_balance()

        return {
            "mode": self.mode.value,
            "trading_enabled": self.enable_trading,
            "balance": balance,
            "initial_balance": self.initial_balance,
            "peak_balance": self.peak_balance,
            "active_positions": len(self.active_positions),
            "max_positions": self.max_positions,
            "pending_orders": len(self.pending_orders),
            "total_trades": len(self.trade_history),
            "risk_per_trade": self.risk_per_trade,
            "max_leverage": self.max_leverage
        }

    def _get_blacklist_from_db(self) -> list:
        """Read symbol blacklist from DB (for settings response). Returns [] if unavailable."""
        if self.settings_repo:
            try:
                import json
                raw = self.settings_repo.get_setting('symbol_blacklist')
                if raw:
                    return json.loads(raw)
            except Exception:
                pass
        return []

    def get_settings(self) -> Dict[str, Any]:
        """
        SOTA (Jan 2026): Get current trading settings for LIVE mode.

        Returns settings dict compatible with PaperTradingService.get_settings()
        for API parity across all trading modes.

        Returns:
            Dict with all trading settings including auto-close and portfolio target
        """
        return {
            "risk_percent": self.risk_per_trade * 100,  # Convert to percentage
            "max_positions": self.max_positions,
            "leverage": self.max_leverage,
            "auto_execute": self.enable_trading,
            "execution_ttl_minutes": self.order_ttl_minutes,
            "smart_recycling": self.enable_recycling,
            # SOTA (Jan 2026): Auto-Close Profitable Positions
            "close_profitable_auto": self.close_profitable_auto,
            "profitable_threshold_pct": self.profitable_threshold_pct,
            # SOTA (Feb 2026): AUTO_CLOSE interval
            "auto_close_interval": self.auto_close_interval,
            # SOTA (Jan 2026): Portfolio Target
            "portfolio_target_pct": self.portfolio_target_pct,
            # SOTA (Feb 2026): Profit Lock
            "use_profit_lock": self.use_profit_lock,
            "profit_lock_threshold_pct": self.profit_lock_threshold_pct,
            "profit_lock_pct": self.profit_lock_pct,
            # SOTA (Feb 2026): Symbol Blacklist (read-only, managed via /settings/blacklist API)
            "symbol_blacklist": self._get_blacklist_from_db(),
            # v6.5.12: DZ Force-Close
            "dz_force_close_enabled": getattr(self, 'dz_force_close_enabled', True),
            # v6.6.0: Order Type
            "order_type": self.order_type,
            "limit_chase_timeout_seconds": self.limit_chase_timeout_seconds,
            # SOTA (Feb 9, 2026): Circuit Breaker settings (runtime-configurable)
            **(self.circuit_breaker.get_status()['config'] if hasattr(self, 'circuit_breaker') and self.circuit_breaker else {}),
        }

    def update_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        """
        SOTA (Jan 2026): Update trading settings for LIVE mode.

        Updates settings in-memory and persists to DB if settings_repo available.
        Provides API parity with PaperTradingService.update_settings().

        Args:
            settings: Dict of settings to update (only provided keys are updated)

        Returns:
            Updated settings dict
        """
        # Update in-memory settings
        if "risk_percent" in settings:
            self.risk_per_trade = float(settings["risk_percent"]) / 100
            self.logger.info(f"⚙️ risk_per_trade updated to {self.risk_per_trade*100}%")

        if "max_positions" in settings:
            self.max_positions = int(settings["max_positions"])
            # Also update signal tracker if exists
            if hasattr(self, '_signal_tracker') and self._signal_tracker:
                self._signal_tracker.max_pending = self.max_positions
            self.logger.info(f"⚙️ max_positions updated to {self.max_positions}")

        if "leverage" in settings:
            self.max_leverage = int(settings["leverage"])
            self.logger.info(f"⚙️ max_leverage updated to {self.max_leverage}")

        if "auto_execute" in settings:
            self.enable_trading = bool(settings["auto_execute"])
            self.logger.info(f"⚙️ enable_trading updated to {self.enable_trading}")

        if "execution_ttl_minutes" in settings:
            self.order_ttl_minutes = int(settings["execution_ttl_minutes"])
            # Also update signal tracker if exists
            if hasattr(self, '_signal_tracker') and self._signal_tracker:
                self._signal_tracker.default_ttl_minutes = self.order_ttl_minutes
            self.logger.info(f"⚙️ order_ttl_minutes updated to {self.order_ttl_minutes}")

        if "smart_recycling" in settings:
            self.enable_recycling = bool(settings["smart_recycling"])
            # Also update signal tracker if exists
            if hasattr(self, '_signal_tracker') and self._signal_tracker:
                self._signal_tracker.enable_recycling = self.enable_recycling
            self.logger.info(f"⚙️ enable_recycling updated to {self.enable_recycling}")

        # SOTA (Jan 2026): Auto-Close Profitable
        if "close_profitable_auto" in settings:
            self.close_profitable_auto = bool(settings["close_profitable_auto"])
            self.logger.info(f"💰 close_profitable_auto updated to {self.close_profitable_auto}")

        if "profitable_threshold_pct" in settings:
            self.profitable_threshold_pct = float(settings["profitable_threshold_pct"])
            # Validate threshold
            if self.profitable_threshold_pct <= 0 or self.profitable_threshold_pct > 100:
                self.logger.warning(
                    f"⚠️ Invalid profitable_threshold_pct={self.profitable_threshold_pct}. "
                    f"Using default {PRODUCTION_PROFITABLE_THRESHOLD_PCT:.1f}%."
                )
                self.profitable_threshold_pct = PRODUCTION_PROFITABLE_THRESHOLD_PCT
            self.logger.info(f"💰 profitable_threshold_pct updated to {self.profitable_threshold_pct}%")

        # SOTA (Feb 2026): AUTO_CLOSE interval (runtime configurable)
        if "auto_close_interval" in settings:
            new_interval = str(settings["auto_close_interval"]).strip()
            if new_interval in ('1m', '15m'):
                self.auto_close_interval = new_interval
                # Sync to PositionMonitor at runtime
                if hasattr(self, 'position_monitor') and self.position_monitor:
                    self.position_monitor.set_auto_close_interval(new_interval)
                self.logger.info(f"⚙️ auto_close_interval updated to {self.auto_close_interval}")
            else:
                self.logger.warning(f"⚠️ Invalid auto_close_interval '{new_interval}'. Must be '1m' or '15m'.")

        # v6.0.0: Candle-close SL (symmetric execution)
        if "sl_on_candle_close" in settings:
            val = bool(settings["sl_on_candle_close"])
            if hasattr(self, 'position_monitor') and self.position_monitor:
                self.position_monitor.set_sl_on_candle_close(val)
            self.logger.info(f"SL candle-close mode: {'ENABLED' if val else 'DISABLED'}")
        if "sl_check_interval" in settings:
            new_interval = str(settings["sl_check_interval"]).strip()
            if hasattr(self, 'position_monitor') and self.position_monitor:
                self.position_monitor.set_sl_check_interval(new_interval)

        # SOTA (Feb 2026): Profit Lock (ratchet stop)
        if "use_profit_lock" in settings:
            self.use_profit_lock = bool(settings["use_profit_lock"])
            if hasattr(self, 'position_monitor') and self.position_monitor:
                self.position_monitor.use_profit_lock = self.use_profit_lock
                if self.use_profit_lock:
                    self.position_monitor.PROFIT_LOCK_THRESHOLD_ROE = self.profit_lock_threshold_pct / 100.0
                    self.position_monitor.PROFIT_LOCK_ROE = self.profit_lock_pct / 100.0
            self.logger.info(f"🔒 use_profit_lock updated to {self.use_profit_lock}")

        if "profit_lock_threshold_pct" in settings:
            self.profit_lock_threshold_pct = float(settings["profit_lock_threshold_pct"])
            # SOTA FIX (Feb 2026): Always sync to monitor, even when disabled
            # This ensures correct values are ready when profit_lock is enabled later
            if hasattr(self, 'position_monitor') and self.position_monitor:
                self.position_monitor.PROFIT_LOCK_THRESHOLD_ROE = self.profit_lock_threshold_pct / 100.0
            self.logger.info(f"🔒 profit_lock_threshold_pct updated to {self.profit_lock_threshold_pct}%")

        if "profit_lock_pct" in settings:
            self.profit_lock_pct = float(settings["profit_lock_pct"])
            # SOTA FIX (Feb 2026): Always sync to monitor, even when disabled
            if hasattr(self, 'position_monitor') and self.position_monitor:
                self.position_monitor.PROFIT_LOCK_ROE = self.profit_lock_pct / 100.0
            self.logger.info(f"🔒 profit_lock_pct updated to {self.profit_lock_pct}%")

        # SOTA (Jan 2026): Portfolio Target
        if "portfolio_target_pct" in settings:
            self.portfolio_target_pct = float(settings["portfolio_target_pct"])
            # Validate target
            if self.portfolio_target_pct < 0 or self.portfolio_target_pct > 100:
                self.logger.warning(f"⚠️ Invalid portfolio_target_pct={self.portfolio_target_pct}. Must be 0-100. Using default.")
                self.portfolio_target_pct = PRODUCTION_PORTFOLIO_TARGET_PCT

            # Update PositionMonitor if exists
            if hasattr(self, 'position_monitor') and self.position_monitor:
                # SOTA FIX (Jan 2026): Fetch balance if not available
                # This ensures portfolio_target works immediately after settings update
                balance_for_calc = self.initial_balance
                if balance_for_calc <= 0 and self.client:
                    try:
                        account = self.client.get_account_balance()
                        if account and 'availableBalance' in account:
                            balance_for_calc = float(account.get('availableBalance', 0))
                            self.initial_balance = balance_for_calc  # Cache it
                            self.logger.info(f"💰 Fetched balance for portfolio target: ${balance_for_calc:.2f}")
                    except Exception as e:
                        self.logger.warning(f"⚠️ Could not fetch balance for portfolio target: {e}")

                if self.portfolio_target_pct > 0 and balance_for_calc > 0:
                    portfolio_target_usd = balance_for_calc * (self.portfolio_target_pct / 100.0)
                    self.position_monitor.set_portfolio_target(portfolio_target_usd)
                    self.logger.info(f"🎯 portfolio_target updated to {self.portfolio_target_pct}% (${portfolio_target_usd:.2f})")
                else:
                    self.position_monitor.set_portfolio_target(0.0)
                    self.logger.info(f"🎯 portfolio_target DISABLED (balance={balance_for_calc:.2f})")

        # v6.5.12: DZ Force-Close toggle
        if "dz_force_close_enabled" in settings:
            self.dz_force_close_enabled = bool(settings["dz_force_close_enabled"])
            self.logger.info(f"DZ Force-Close: {'ENABLED' if self.dz_force_close_enabled else 'DISABLED'}")

        # v6.6.0: Order Type Configuration (runtime switch, no restart)
        if "order_type" in settings:
            val = str(settings["order_type"]).upper()
            if val in ('MARKET', 'LIMIT'):
                self.order_type = val
                self.logger.info(f"Order type updated to: {self.order_type}")

        if "limit_chase_timeout_seconds" in settings:
            self.limit_chase_timeout_seconds = max(5, min(300, int(settings["limit_chase_timeout_seconds"])))
            self.logger.info(f"LIMIT chase timeout: {self.limit_chase_timeout_seconds}s")

        # SOTA (Feb 9, 2026): Circuit Breaker runtime config via API
        # Forwards CB-specific keys to circuit_breaker.update_params()
        if hasattr(self, 'circuit_breaker') and self.circuit_breaker:
            cb_keys = {
                'max_consecutive_losses', 'cooldown_minutes', 'daily_symbol_loss_limit',
                'blocked_windows', 'blocked_windows_enabled', 'blocked_windows_utc_offset',
                'max_daily_drawdown_pct',
            }
            cb_update = {k: v for k, v in settings.items() if k in cb_keys}
            if cb_update:
                self.circuit_breaker.update_params(**cb_update)
                self.logger.info(f"🛡️ Circuit Breaker updated: {list(cb_update.keys())}")

        # BroSubSoul heartbeat: persist directly to DB (no in-memory attribute needed)
        if "bro_subsoul_last_heartbeat" in settings and self.settings_repo:
            try:
                self.settings_repo.set_setting(
                    "bro_subsoul_last_heartbeat", str(int(settings["bro_subsoul_last_heartbeat"]))
                )
            except Exception as e:
                self.logger.debug(f"BroSubSoul heartbeat persist error: {e}")

        # Persist to DB if settings_repo available
        if self.settings_repo:
            try:
                # Convert back to DB format
                db_settings = {
                    "risk_percent": self.risk_per_trade * 100,
                    "max_positions": self.max_positions,
                    "leverage": self.max_leverage,
                    "auto_execute": self.enable_trading,
                    "execution_ttl_minutes": self.order_ttl_minutes,
                    "smart_recycling": self.enable_recycling,
                    "close_profitable_auto": self.close_profitable_auto,
                    "profitable_threshold_pct": self.profitable_threshold_pct,
                    "portfolio_target_pct": self.portfolio_target_pct,
                    "use_profit_lock": self.use_profit_lock,
                    "profit_lock_threshold_pct": self.profit_lock_threshold_pct,
                    "profit_lock_pct": self.profit_lock_pct,
                    "auto_close_interval": self.auto_close_interval,
                    "dz_force_close_enabled": getattr(self, 'dz_force_close_enabled', True),
                    "order_type": self.order_type,
                    "limit_chase_timeout_seconds": self.limit_chase_timeout_seconds,
                }

                # SOTA (Feb 9, 2026): Persist CB settings if they were updated
                if hasattr(self, 'circuit_breaker') and self.circuit_breaker:
                    cb = self.circuit_breaker
                    db_settings["cb_max_consecutive_losses"] = cb.max_losses
                    db_settings["cb_cooldown_minutes"] = cb.cooldown_hours * 60
                    db_settings["cb_daily_symbol_loss_limit"] = cb.daily_symbol_loss_limit
                    db_settings["cb_blocked_windows_enabled"] = cb.blocked_windows_enabled
                    db_settings["cb_max_daily_drawdown_pct"] = cb.max_daily_drawdown_pct
                    import json
                    db_settings["cb_blocked_windows"] = json.dumps(cb.blocked_windows)

                # Update each setting in DB
                for key, value in db_settings.items():
                    self.settings_repo.set_setting(key, str(value))

                self.logger.info("💾 Settings persisted to DB")
            except Exception as e:
                self.logger.warning(f"⚠️ Failed to persist settings to DB: {e}")

        # Return updated settings
        return self.get_settings()

    # =========================================================================
    # POSITION MONITORING (Matching Paper Trading)
    # =========================================================================

    def process_market_data(
        self,
        symbol: str,
        current_price: float,
        high: float,
        low: float
    ) -> None:
        """
        Process market data for live positions.

        SOTA: Matches Paper Trading behavior.
        - Trailing Stop: ATR-based trailing after TP1
        - Breakeven: Move SL to entry at 1.5R

        Called by RealtimeService on each candle.

        Args:
            symbol: Trading pair
            current_price: Current close price
            high: Candle high
            low: Candle low
        """
        if not self.enable_trading or not self.client:
            return

        # Get position for this symbol
        self._refresh_positions()
        pos = self.active_positions.get(symbol.upper())
        if not pos:
            return

        # Get watermark for this position
        # Try primary key first, then fallback key
        watermark = self._position_watermarks.get(symbol.upper())
        if not watermark:
            watermark = self._position_watermarks.get(f"watermark_{symbol.upper()}")

        if not watermark:
            # Initialize watermark if missing
            is_long = pos.position_amt > 0
            self._position_watermarks[symbol.upper()] = {
                'highest': pos.entry_price if is_long else 0,
                'lowest': pos.entry_price if not is_long else float('inf'),
                'current_sl': 0,
                'tp_target': 0,
                'entry_price': pos.entry_price,
                'initial_risk': pos.entry_price * 0.005,  # Default 0.5%
                'is_breakeven': False,
                'tp_hit_count': 0,
                'atr': 0,
                'tp_levels': {},
                'remaining_size': abs(pos.position_amt),
                'side': 'LONG' if is_long else 'SHORT'
            }
            watermark = self._position_watermarks[symbol.upper()]
            self.logger.warning(f"⚠️ Created missing watermark for {symbol}")

        # Extract position info
        is_long = pos.position_amt > 0
        entry_price = watermark.get('entry_price', pos.entry_price)
        side = watermark.get('side', 'LONG' if is_long else 'SHORT')

        # ============================================================
        # SOTA SYNC (Jan 2026): Backtest-compatible trailing logic
        # Matches ExecutionSimulator._update_position_logic exactly
        # ============================================================

        # CONSTANTS (matching backtest execution_simulator.py)
        BREAKEVEN_TRIGGER_R = 1.5  # Breakeven at 1.5R profit (matching backtest)
        BREAKEVEN_BUFFER = 0.0005  # 0.05% buffer
        TRAILING_STOP_ATR = 4.0    # Trailing = ATR * 4.0 (matching backtest)
        TP1_CLOSE_PCT = 0.60       # Close 60% at TP1 (matching backtest)

        # Step 1: Track Max/Min Price for Trailing
        if is_long and high > watermark.get('highest', 0):
            watermark['highest'] = high
        elif not is_long and low < watermark.get('lowest', float('inf')):
            watermark['lowest'] = low

        new_sl = None

        # Step 2: Check TP1 Hit (if tp_hit_count == 0)
        tp_hit_count = watermark.get('tp_hit_count', 0)
        if tp_hit_count == 0:
            tp_levels = watermark.get('tp_levels', {})
            tp1 = tp_levels.get('tp1', watermark.get('tp_target', 0))

            if tp1 > 0:
                tp_hit = (is_long and current_price >= tp1) or (not is_long and current_price <= tp1)

                if tp_hit:
                    # TP1 HIT! Execute partial close (60%)
                    # SOTA SYNC (Jan 2026): Use initial_size × 0.6 (matches backtest)
                    # Backtest: close_size = min(pos['initial_size'] * pct, pos['remaining_size'])
                    initial_size = watermark.get('initial_size', watermark.get('remaining_size', abs(pos.position_amt)))
                    remaining_size = watermark.get('remaining_size', abs(pos.position_amt))
                    close_qty = min(initial_size * TP1_CLOSE_PCT, remaining_size)

                    self.logger.info(f"🎯 TP1 HIT: {symbol} @ ${current_price:.4f} - Closing {TP1_CLOSE_PCT*100:.0f}% ({close_qty:.4f})")

                    # ═══════════════════════════════════════════════════════════════════════
                    # SOTA FIX (Jan 2026 - Bug #17): Delegate to PositionMonitorService
                    #
                    # Problem: asyncio.create_task() is non-blocking → watermark updated immediately
                    # → Race condition if TP order triggers before partial close completes
                    #
                    # Solution: Let PositionMonitorService handle TP1 execution + watermark update
                    # PositionMonitorService has proper async flow with await
                    # ═══════════════════════════════════════════════════════════════════════

                    # Mark TP1 as hit to prevent re-triggering
                    watermark['tp_hit_count'] = 1

                    # Delegate to PositionMonitorService for proper async execution
                    # PositionMonitorService will:
                    # 1. Execute partial close with await (blocking until complete)
                    # 2. Update watermarks AFTER close confirms
                    # 3. Update TP order with remaining quantity
                    if self.position_monitor:
                        # PositionMonitorService._on_tp1_hit_async() handles the full flow
                        self.logger.info(f"📡 Delegating TP1 execution to PositionMonitorService: {symbol}")
                    else:
                        # Fallback: Fire-and-forget (old behavior, has race condition)
                        try:
                            exit_side = 'SELL' if is_long else 'BUY'
                            asyncio.create_task(self._execute_partial_close_async(symbol, exit_side, close_qty, "TAKE_PROFIT_1"))

                            # Update watermark immediately (race condition risk)
                            watermark['remaining_size'] = remaining_size - close_qty

                            # Set breakeven SL
                            if is_long:
                                new_sl = entry_price * (1 + BREAKEVEN_BUFFER)
                            else:
                                new_sl = entry_price * (1 - BREAKEVEN_BUFFER)
                            watermark['is_breakeven'] = True
                            watermark['current_sl'] = new_sl
                            watermark['tp_target'] = 0
                            self.logger.warning(f"⚠️ TP1 fallback mode (no PositionMonitor): {symbol}")
                        except Exception as e:
                            self.logger.error(f"❌ TP1 partial close failed: {e}")

        # Step 3: Breakeven Trigger (if not already breakeven)
        if not watermark.get('is_breakeven', False):
            initial_risk = watermark.get('initial_risk', 0)

            if initial_risk > 0:
                price_diff = abs(current_price - entry_price)

                # Trigger breakeven when price moves 1.5R in profit direction
                if price_diff >= (initial_risk * BREAKEVEN_TRIGGER_R):
                    # Check profit direction
                    profit_direction = (is_long and current_price > entry_price) or (not is_long and current_price < entry_price)

                    if profit_direction:
                        if is_long:
                            new_sl = entry_price * (1 + BREAKEVEN_BUFFER)
                        else:
                            new_sl = entry_price * (1 - BREAKEVEN_BUFFER)
                        watermark['is_breakeven'] = True
                        self.logger.info(f"🛡️ BREAKEVEN (1.5R): {symbol} SL → ${new_sl:.4f}")

        # Step 4: Trailing Stop Update (ONLY after TP1 hit)
        if watermark.get('tp_hit_count', 0) >= 1:
            atr = watermark.get('atr', 0)

            if atr > 0:
                # ATR-based trailing (matching backtest)
                trail = atr * TRAILING_STOP_ATR

                if is_long:
                    trail_sl = watermark.get('highest', high) - trail
                    if trail_sl > watermark.get('current_sl', 0):
                        new_sl = trail_sl
                        self.logger.info(f"🎢 TRAILING (ATR×4): {symbol} SL → ${new_sl:.4f}")
                else:
                    trail_sl = watermark.get('lowest', low) + trail
                    current_sl = watermark.get('current_sl', 0)
                    if current_sl == 0 or trail_sl < current_sl:
                        new_sl = trail_sl
                        self.logger.info(f"🎢 TRAILING (ATR×4): {symbol} SL → ${new_sl:.4f}")
            else:
                # Fallback: 1.5% trailing if no ATR
                TRAILING_DIST = 0.015
                if is_long:
                    trail_sl = watermark.get('highest', high) * (1 - TRAILING_DIST)
                    if trail_sl > watermark.get('current_sl', 0):
                        new_sl = trail_sl
                else:
                    trail_sl = watermark.get('lowest', low) * (1 + TRAILING_DIST)
                    current_sl = watermark.get('current_sl', 0)
                    if current_sl == 0 or trail_sl < current_sl:
                        new_sl = trail_sl

        # SOTA LOCAL_FIRST_MODE (Jan 2026): DISABLED - Exchange SL update causes duplicate orders
        # Backup SL -2% at entry is sufficient. Local SL managed by PositionMonitorService.
        # Old:
        # if new_sl and new_sl != watermark.get('current_sl', 0):
        #     success = self.update_trailing_stop(symbol, new_sl, abs(pos.position_amt))
        #     ...
        pass  # Exchange SL update DISABLED

    async def process_market_data_async(
        self,
        symbol: str,
        current_price: float,
        high: float,
        low: float
    ) -> None:
        """
        SOTA ASYNC: Process market data for live positions (non-blocking).

        SOTA SYNC (Jan 2026): Matches ExecutionSimulator._update_position_logic exactly.
        """
        if not self.enable_trading or not self.async_client:
            return

        # Get position (from cache first, assume updated by websocket)
        pos = self.active_positions.get(symbol.upper())
        if not pos:
            return

        # Get watermark for this position
        watermark = self._position_watermarks.get(symbol.upper())
        if not watermark:
            watermark = self._position_watermarks.get(f"watermark_{symbol.upper()}")

        if not watermark:
            # Initialize watermark if missing
            is_long = pos.position_amt > 0
            self._position_watermarks[symbol.upper()] = {
                'highest': pos.entry_price if is_long else 0,
                'lowest': pos.entry_price if not is_long else float('inf'),
                'current_sl': 0,
                'tp_target': 0,
                'entry_price': pos.entry_price,
                'initial_risk': pos.entry_price * 0.005,
                'is_breakeven': False,
                'tp_hit_count': 0,
                'atr': 0,
                'tp_levels': {},
                'remaining_size': abs(pos.position_amt),
                'side': 'LONG' if is_long else 'SHORT'
            }
            watermark = self._position_watermarks[symbol.upper()]

        # Extract position info
        is_long = pos.position_amt > 0
        entry_price = watermark.get('entry_price', pos.entry_price)

        if entry_price == 0:
            return

        # ============================================================
        # SOTA SYNC (Jan 2026): Backtest-compatible trailing logic
        # ============================================================

        BREAKEVEN_TRIGGER_R = 1.5
        BREAKEVEN_BUFFER = 0.0005
        TRAILING_STOP_ATR = 4.0
        TP1_CLOSE_PCT = 0.60

        # Step 1: Track Max/Min Price
        if is_long and high > watermark.get('highest', 0):
            watermark['highest'] = high
        elif not is_long and low < watermark.get('lowest', float('inf')):
            watermark['lowest'] = low

        new_sl = None

        # Step 2: Check TP1 Hit
        tp_hit_count = watermark.get('tp_hit_count', 0)
        if tp_hit_count == 0:
            tp_levels = watermark.get('tp_levels', {})
            tp1 = tp_levels.get('tp1', watermark.get('tp_target', 0))

            if tp1 > 0:
                tp_hit = (is_long and current_price >= tp1) or (not is_long and current_price <= tp1)

                if tp_hit:
                    # SOTA SYNC (Jan 2026): Use initial_size × 0.6 (matches backtest)
                    initial_size = watermark.get('initial_size', watermark.get('remaining_size', abs(pos.position_amt)))
                    remaining_size = watermark.get('remaining_size', abs(pos.position_amt))
                    close_qty = min(initial_size * TP1_CLOSE_PCT, remaining_size)

                    self.logger.info(f"🎯 TP1 HIT: {symbol} @ ${current_price:.4f}")

                    try:
                        exit_side = 'SELL' if is_long else 'BUY'
                        await self._execute_partial_close_async(symbol, exit_side, close_qty, "TAKE_PROFIT_1")
                    except Exception as e:
                        self.logger.error(f"❌ TP1 partial close failed: {e}")

                    watermark['tp_hit_count'] = 1
                    watermark['remaining_size'] = remaining_size - close_qty

                    if is_long:
                        new_sl = entry_price * (1 + BREAKEVEN_BUFFER)
                    else:
                        new_sl = entry_price * (1 - BREAKEVEN_BUFFER)
                    watermark['is_breakeven'] = True
                    # SOTA FIX (Jan 2026): Update current_sl in watermark for UI display
                    watermark['current_sl'] = new_sl
                    # SOTA FIX (Jan 2026): Clear tp_target after TP1 hit (TP becomes "--")
                    watermark['tp_target'] = 0

        # Step 3: Breakeven Trigger
        if not watermark.get('is_breakeven', False):
            initial_risk = watermark.get('initial_risk', 0)

            if initial_risk > 0:
                price_diff = abs(current_price - entry_price)

                if price_diff >= (initial_risk * BREAKEVEN_TRIGGER_R):
                    profit_direction = (is_long and current_price > entry_price) or (not is_long and current_price < entry_price)

                    if profit_direction:
                        if is_long:
                            new_sl = entry_price * (1 + BREAKEVEN_BUFFER)
                        else:
                            new_sl = entry_price * (1 - BREAKEVEN_BUFFER)
                        watermark['is_breakeven'] = True

        # Step 4: Trailing Stop (after TP1)
        if watermark.get('tp_hit_count', 0) >= 1:
            atr = watermark.get('atr', 0)

            if atr > 0:
                trail = atr * TRAILING_STOP_ATR

                if is_long:
                    trail_sl = watermark.get('highest', high) - trail
                    if trail_sl > watermark.get('current_sl', 0):
                        new_sl = trail_sl
                else:
                    trail_sl = watermark.get('lowest', low) + trail
                    current_sl = watermark.get('current_sl', 0)
                    if current_sl == 0 or trail_sl < current_sl:
                        new_sl = trail_sl
            else:
                TRAILING_DIST = 0.015
                if is_long:
                    trail_sl = watermark.get('highest', high) * (1 - TRAILING_DIST)
                    if trail_sl > watermark.get('current_sl', 0):
                        new_sl = trail_sl
                else:
                    trail_sl = watermark.get('lowest', low) * (1 + TRAILING_DIST)
                    current_sl = watermark.get('current_sl', 0)
                    if current_sl == 0 or trail_sl < current_sl:
                        new_sl = trail_sl

        # SOTA LOCAL_FIRST_MODE (Jan 2026): DISABLED - Exchange SL update causes duplicate orders
        # Backup SL -2% at entry is sufficient. Local SL managed by PositionMonitorService.
        # Old:
        # if new_sl and new_sl != watermark['current_sl']:
        #     success = await self.update_trailing_stop_async(symbol, new_sl, abs(pos.position_amt))
        #     ...
        pass  # Exchange SL update DISABLED

    def __repr__(self) -> str:
        return f"LiveTradingService(mode={self.mode.value}, enabled={self.enable_trading})"
    # =========================================================================
    # SOTA (Jan 2026): LOCAL PnL Tracking Implementation
    # Pattern: Two Sigma / Citadel - Never trust exchange PnL
    # NOTE: _detect_actual_leverage defined at ~line 1640 (single definition)
    # =========================================================================

    def _check_auto_close_local(
        self,
        symbol: str,
        current_price: float,
        entry_price: float = None,  # Legacy param (unused)
        side: str = None,          # Legacy param (unused)
        quantity: float = None,    # Legacy param (unused)
        leverage: float = None     # Legacy param (unused)
    ) -> bool:
        """
        SOTA v4 (Jan 2026): LOCAL PnL-based AUTO_CLOSE.

        Pattern: Two Sigma, Citadel - Never trust exchange PnL.
        Uses LOCAL position tracker with exact fills and fees.

        Returns:
            True if position should close, False otherwise
        """
        # Check if AUTO_CLOSE enabled
        if not self.close_profitable_auto:
            return False

        # SOTA FIX (Feb 2026): Thread-safe access with RLock
        with self._local_positions_lock:
            tracker = self._local_positions.get(symbol)

        if not tracker:
            # SOTA FIX (Feb 2026): Fallback DISABLED
            # Old code called _check_auto_close_profitable() which doesn't exist.
            # Without LocalPosition tracker, we cannot accurately calculate PnL.
            # Safe behavior: Skip auto-close check for this symbol.
            self.logger.debug(f"⚠️ No local tracker for {symbol}, skipping auto-close check")
            return False

        # Calculate LOCAL PnL and ROE
        local_pnl = tracker.get_unrealized_pnl(current_price)
        local_roe = tracker.get_roe_percent(current_price)

        # Get summary for logging
        summary = tracker.get_summary(current_price)
        margin_value = summary.get('actual_margin') or 0.0
        margin_display = f"${margin_value:.2f}" if margin_value > 0 else "N/A"
        leverage_display = summary.get('actual_leverage') or summary.get('intended_leverage') or 0

        # SOTA FIX (Feb 2026): Log ROE for ALL positions for debugging
        # User requested: "Add logging to print ROE of current positions"
        # This helps debug why auto-close doesn't trigger when expected
        self.logger.info(
            f"📊 LOCAL PnL: {symbol} | "
            f"Entry: ${summary['avg_entry_price']:.6f} | "
            f"Current: ${current_price:.6f} | "
            f"PnL: ${local_pnl:.2f} | "
            f"ROE: {local_roe:.2f}% | "
            f"Threshold: {self.profitable_threshold_pct}% | "
            f"Lev: {leverage_display}x | "
            f"Margin: {margin_display}"
        )

        # Check threshold
        if local_roe >= self.profitable_threshold_pct:
            self.logger.info(
                f"💰 AUTO_CLOSE (LOCAL): {symbol} | "
                f"ROE: {local_roe:.2f}% >= {self.profitable_threshold_pct}% | "
                f"PnL: ${local_pnl:.2f} | "
                f"Fees: ${summary['total_entry_fees']:.2f} | "
                f"Closing position!"
            )

            # Close position
            self._close_position_market(
                 symbol=symbol,
                 quantity=summary['total_quantity'],
                 reason="AUTO_CLOSE_PROFITABLE_LOCAL"
            )
            return True

        return False

    def _close_position_market(self, symbol: str, quantity: float, reason: str = "MANUAL") -> Optional[str]:
        """
        SOTA (Feb 2026): Unified Market Close Logic.

        Used by AUTO_CLOSE (primary exit path, ~70% of all exits).

        Handles:
        1. Side determination (Close opposite of position)
        2. Market Order execution (with reduceOnly)
        3. Order cleanup (Cancel SL/TP)
        4. Circuit Breaker update
        5. Database persist
        6. Full state cleanup (active_positions, _local_positions, stop_monitoring)

        Args:
            symbol: Trading pair
            quantity: Quantity to close (absolute value)
            reason: Reason for logging (e.g., "AUTO_CLOSE", "PORTFOLIO_TARGET")

        Returns:
            Order ID if successful, None otherwise
        """
        symbol_upper = symbol.upper()
        self.logger.info(f"🚨 EXECUTING MARKET CLOSE: {symbol_upper} | Qty: {quantity} | Reason: {reason}")

        # Set exit reason for Telegram notification
        if reason and reason != "MANUAL":
            self._pending_exit_reasons[symbol_upper] = reason

        # v5.5.0: Mark symbol as closing for ghost prevention
        self._closing_symbols.add(symbol_upper)
        self._closing_symbols_ts[symbol_upper] = time.time()

        try:
            # 1. Determine Position Side
            side = None

            # Check Local Tracker first (SOTA)
            with self._local_positions_lock:
                tracker = self._local_positions.get(symbol_upper)
                if tracker:
                    side = tracker.side  # 'LONG' or 'SHORT'

            # Fallback to Exchange Position
            if not side and symbol_upper in self.active_positions:
                pos = self.active_positions[symbol_upper]
                if pos.position_amt > 0:
                    side = 'LONG'
                elif pos.position_amt < 0:
                    side = 'SHORT'

            if not side:
                self.logger.error(f"❌ Cannot close {symbol_upper}: Position direction unknown (not found in trackers)")
                self._closing_symbols.discard(symbol_upper)
                self._closing_symbols_ts.pop(symbol_upper, None)
                return None

            # 2. Determine Order Side (Close = Opposite)
            close_side = OrderSide.SELL if side == 'LONG' else OrderSide.BUY

            # 3. Sanitize Quantity (proper precision for exchange)
            sanitized_qty = quantity
            if self.filter_service:
                sanitized_qty = self.filter_service.sanitize_quantity(symbol_upper, quantity)

            # 4. Execute close order
            # v6.6.0: LIMIT+GTX for profitable exits (AC/PT/TP), MARKET for SL/HC/manual
            order = None
            market_qty = sanitized_qty
            _limit_eligible_reasons = {
                'AUTO_CLOSE', 'AUTO_CLOSE_PROFITABLE_LOCAL', 'AUTO_CLOSE_PROFITABLE',
                'PORTFOLIO_TARGET', 'TAKE_PROFIT'
            }
            if self.order_type == 'LIMIT' and reason.upper() in _limit_eligible_reasons:
                try:
                    # v6.6.1: Skip redundant get_ticker_price — GTX method uses get_book_ticker internally
                    gtx_result = self._try_limit_gtx_order(
                        symbol=symbol_upper,
                        side=close_side,
                        quantity=sanitized_qty,
                        price=0,  # GTX uses bid/ask from book_ticker, no fallback needed
                        reduce_only=True
                    )
                    if gtx_result and hasattr(gtx_result, 'status'):
                        if gtx_result.status == 'FILLED':
                            order = gtx_result
                        elif gtx_result.status == 'PARTIALLY_FILLED':
                            # L3 fix: MARKET only the unfilled remainder
                            market_qty = sanitized_qty - gtx_result.executed_qty
                            self.logger.info(f"GTX PARTIAL exit: {symbol_upper}, remainder {market_qty}")
                except Exception as e:
                    self.logger.warning(f"LIMIT exit failed: {e}")

            if order is None:
                # MARKET fallback (default, or GTX failed, or SL/HC reason)
                order = self.client.create_order(
                    symbol=symbol_upper,
                    side=close_side,
                    order_type=OrderType.MARKET,
                    quantity=market_qty,
                    reduce_only=True
                )

            if order:
                order_id = order.order_id
                exit_price = order.avg_price if hasattr(order, 'avg_price') else 0
                self.logger.info(f"✅ MARKET CLOSE FILLED: {symbol_upper} | ID: {order_id} | Exit: ${exit_price}")

                # 5. Cancel Open Orders (SL/TP cleanup)
                try:
                    self._cleanup_all_orders_for_symbol(symbol_upper, reason=f"CLOSE_{reason}")
                except Exception as e:
                    self.logger.warning(f"⚠️ Cleanup failed after close for {symbol_upper}: {e}")

                # 6. Broadcast Exit Event
                if hasattr(self, 'event_bus') and self.event_bus:
                    try:
                        self.event_bus.publish_signal_update({
                            'symbol': symbol_upper,
                            'status': 'CLOSED',
                            'reason': reason,
                            'order_id': order_id,
                            'price': exit_price
                        }, symbol=symbol_upper)
                    except Exception:
                        pass

                # v5.5.0 FIX 4: FAST vs DEFERRED path based on exit_price
                if exit_price > 0:
                    # ── FAST PATH ──
                    pnl = 0.0
                    with self._local_positions_lock:
                        tracker = self._local_positions.get(symbol_upper)
                        if tracker:
                            pnl = tracker.get_realized_pnl(exit_price)

                    try:
                        if hasattr(self, 'circuit_breaker') and self.circuit_breaker:
                            self.circuit_breaker.record_trade_with_time(
                                symbol_upper, side, pnl,
                                datetime.now(timezone.utc)
                            )
                            self.logger.debug(f"🛡️ CB updated: {symbol_upper} {side} PnL=${pnl:.2f}")
                    except Exception as cb_err:
                        self.logger.warning(f"⚠️ CB update failed (non-critical): {cb_err}")

                    try:
                        if self.order_repo:
                            self.order_repo.close_live_position(symbol_upper, exit_price, pnl, reason)
                            self.logger.info(f"💾 DB position closed: {symbol_upper} PnL=${pnl:.2f}")
                    except Exception as db_err:
                        self.logger.warning(f"⚠️ DB persist failed (non-critical): {db_err}")

                    self._send_exit_notification(symbol_upper, exit_price, pnl, reason)

                    if symbol_upper in self.active_positions:
                        del self.active_positions[symbol_upper]

                    try:
                        from .position_monitor_service import get_position_monitor
                        monitor = get_position_monitor()
                        monitor.stop_monitoring(symbol_upper)
                    except Exception as mon_err:
                        self.logger.debug(f"Stop monitoring cleanup: {mon_err}")

                    # CSV buffer (v5.5.0)
                    with self._local_positions_lock:
                        tracker = self._local_positions.get(symbol_upper)
                    if tracker:
                        self._add_to_csv_buffer(symbol_upper, tracker, exit_price, pnl, reason)

                    with self._local_positions_lock:
                        self._local_positions.pop(symbol_upper, None)

                    self._notified_entry_symbols.discard(symbol_upper)
                    self._exit_notified_symbols.discard(symbol_upper)
                    self._closing_symbols.discard(symbol_upper)
                    self._closing_symbols_ts.pop(symbol_upper, None)

                    if symbol_upper in self._pending_exit_reasons:
                        del self._pending_exit_reasons[symbol_upper]

                else:
                    # ── DEFERRED PATH: exit_price=0 → wait for WebSocket fills ──
                    self.logger.warning(
                        f"⚠️ DEFERRED CLOSE: {symbol_upper} exit_price=0, "
                        f"waiting for WebSocket fills to complete CB/DB/notification"
                    )
                    # Keep _closing_symbols SET for _complete_deferred_close()

                return str(order_id)
            else:
                self.logger.error(f"❌ Market close order returned None for {symbol_upper}")
                self._closing_symbols.discard(symbol_upper)
                self._closing_symbols_ts.pop(symbol_upper, None)
                return None

        except Exception as e:
            self.logger.error(f"❌ Failed to execute market close for {symbol_upper}: {e}")
            self._closing_symbols.discard(symbol_upper)
            self._closing_symbols_ts.pop(symbol_upper, None)
            return None
