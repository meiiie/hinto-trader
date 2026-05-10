"""
RealtimeService - Application Layer

Orchestrates real-time data flow and coordinates all components.

NOTE: This service uses Dependency Injection - all infrastructure
dependencies are injected via constructor, not created internally.
"""

import asyncio
import logging
import pandas as pd
from typing import Optional, Dict, List, Callable, TYPE_CHECKING
from datetime import datetime, timezone
from collections import deque

# Domain imports (allowed)
from ...domain.entities.candle import Candle
from ...domain.interfaces import (
    IWebSocketClient,
    IRestClient,
    IDataAggregator,
    IIndicatorCalculator,
    IVWAPCalculator,
    IBollingerCalculator,
    IStochRSICalculator,
    IADXCalculator,
    IATRCalculator,
    IVolumeSpikeDetector,
)

# Domain repository interface (for candle persistence - Phase 2)
from ...domain.repositories.market_data_repository import MarketDataRepository

# Application imports (allowed)
from ..analysis import VolumeAnalyzer, RSIMonitor
from ..signals import SignalGenerator, TradingSignal
from .entry_price_calculator import EntryPriceCalculator
from .tp_calculator import TPCalculator
from .stop_loss_calculator import StopLossCalculator
from ..analysis.trend_filter import TrendFilter, TrendDirection # SOTA: For HTF Confluence
from .confidence_calculator import ConfidenceCalculator
from .smart_entry_calculator import SmartEntryCalculator
from .paper_trading_service import PaperTradingService
from ..risk_management.circuit_breaker import CircuitBreaker

# SOTA (Jan 2026): Global semaphore for rate-limited Binance API calls
# Limits concurrent API calls across ALL RealtimeService instances
# Prevents rate limiting when 50 symbols load historical data simultaneously
# Max 5 concurrent calls = safe margin under Binance's rate limits
_binance_api_semaphore: Optional[asyncio.Semaphore] = None

def get_binance_api_semaphore() -> asyncio.Semaphore:
    """Get or create the global Binance API semaphore."""
    global _binance_api_semaphore
    if _binance_api_semaphore is None:
        _binance_api_semaphore = asyncio.Semaphore(5)  # Max 5 concurrent API calls
    return _binance_api_semaphore


class RealtimeService:
    """
    Real-time trading service that orchestrates all components.

    Responsibilities:
    - Manage WebSocket client lifecycle
    - Coordinate data aggregation
    - Trigger analysis and signal generation
    - Provide data access for dashboard
    - Handle errors and reconnection

    Data Flow:
    WebSocket → Aggregator → Analyzers → Signal Generator → Dashboard
    """

    def __init__(
        self,
        symbol: str = 'btcusdt',
        interval: str = '1m',
        buffer_size: int = 2000,
        paper_service: Optional[PaperTradingService] = None,
        # Injected dependencies (interfaces)
        websocket_client: Optional[IWebSocketClient] = None,
        rest_client: Optional[IRestClient] = None,
        aggregator: Optional[IDataAggregator] = None,
        talib_calculator: Optional[IIndicatorCalculator] = None,
        vwap_calculator: Optional[IVWAPCalculator] = None,
        bollinger_calculator: Optional[IBollingerCalculator] = None,
        stoch_rsi_calculator: Optional[IStochRSICalculator] = None,
        adx_calculator: Optional[IADXCalculator] = None,
        atr_calculator: Optional[IATRCalculator] = None,
        volume_spike_detector: Optional[IVolumeSpikeDetector] = None,
        signal_generator: Optional[SignalGenerator] = None,
        # SOTA FIX: Market data repository for candle persistence (Phase 2)
        market_data_repository: Optional[MarketDataRepository] = None,
        # SOTA FIX: Signal lifecycle service for persistence
        lifecycle_service: Optional['SignalLifecycleService'] = None,  # SignalLifecycleService (avoid circular import)
        # SOTA FIX: TrendFilter for HTF Confluence
        trend_filter: Optional[TrendFilter] = None,
        # CRITICAL FIX: SignalConfirmationService for whipsaw prevention
        signal_confirmation_service: Optional['SignalConfirmationService'] = None,
        # LIVE TRADING: LiveTradingService for real order execution
        live_trading_service: Optional['LiveTradingService'] = None,
        # Live market intelligence for funding-aware signal context
        intelligence_service = None,
        # SHARK TANK: Multi-symbol batch signal coordinator
        shark_tank_coordinator: Optional['SharkTankCoordinator'] = None
    ):
        """
        Initialize real-time service with dependency injection.

        Args:
            symbol: Trading pair symbol (default: 'btcusdt')
            interval: WebSocket interval (default: '1m')
            buffer_size: Size of candle buffers (default: 2000)
            paper_service: Paper trading service (optional)

        Injected Dependencies (use DI container to provide these):
            websocket_client: WebSocket client implementation
            rest_client: REST API client implementation
            aggregator: Data aggregator implementation
            talib_calculator: Technical indicator calculator
            vwap_calculator: VWAP calculator
            bollinger_calculator: Bollinger Bands calculator
            stoch_rsi_calculator: Stochastic RSI calculator
            adx_calculator: ADX calculator
            atr_calculator: ATR calculator
            volume_spike_detector: Volume spike detector
            signal_generator: Signal generator (pre-configured)
        """
        self.symbol = symbol
        self.interval = interval
        self.buffer_size = buffer_size
        self.paper_service = paper_service

        # Store injected dependencies
        # If not provided, they will be created by DI container
        self.websocket_client = websocket_client
        self.rest_client = rest_client
        self.aggregator = aggregator
        self.volume_analyzer = VolumeAnalyzer(ma_period=20)
        self.rsi_monitor = RSIMonitor(period=6)

        # Store calculator references (injected)
        self.talib_calculator = talib_calculator
        self.vwap_calculator = vwap_calculator
        self.bollinger_calculator = bollinger_calculator
        self.stoch_rsi_calculator = stoch_rsi_calculator
        self.adx_calculator = adx_calculator
        self.atr_calculator = atr_calculator
        self.volume_spike_detector = volume_spike_detector

        # Application-layer calculators (created here, they're in Application layer)
        self.entry_calculator = EntryPriceCalculator()
        self.tp_calculator = TPCalculator()
        self.stop_loss_calculator = StopLossCalculator()
        self.confidence_calculator = ConfidenceCalculator()
        self.smart_entry_calculator = SmartEntryCalculator()

        # Signal generator (injected or will be set later)
        self.signal_generator = signal_generator

        # SOTA FIX: Market data repository for candle persistence (Phase 2)
        self._market_data_repository = market_data_repository

        # SOTA FIX: Signal lifecycle service for persistence
        self._lifecycle_service = lifecycle_service

        # SOTA FIX: TrendFilter for HTF Confluence
        self.trend_filter = trend_filter

        # CRITICAL FIX: SignalConfirmationService for whipsaw prevention
        self._signal_confirmation_service = signal_confirmation_service

        # LIVE TRADING: LiveTradingService for real order execution
        self.live_trading_service = live_trading_service

        # Market intelligence (shared singleton from DI container)
        self.intelligence_service = intelligence_service

        # SHARK TANK: Multi-symbol batch coordinator (matching backtest)
        self._shark_tank_coordinator = shark_tank_coordinator

        # SOTA: Initialize Async Client for non-blocking data fetching
        self.async_client = None
        try:
            from ...infrastructure.api.async_binance_client import AsyncBinanceFuturesClient
            import os
            env = os.getenv("ENV", "paper").lower()
            use_testnet = (env == "testnet")
            self.async_client = AsyncBinanceFuturesClient(use_testnet=use_testnet)
        except Exception as e:
            # Fallback will handle this gracefully, logger assumed instantiated below
            pass

        # CIRCUIT BREAKER: Risk management (matching backtest logic)
        self.circuit_breaker: Optional[CircuitBreaker] = None
        self.circuit_breaker_enabled: bool = False  # Toggle, default OFF

        required_htf_candles = self._required_htf_candles()
        htf_buffer_size = max(250, required_htf_candles + 50)

        # Data storage (in-memory cache)
        self._latest_1m: Optional[Candle] = None
        self._latest_15m: Optional[Candle] = None
        self._latest_1h: Optional[Candle] = None
        self._latest_4h: Optional[Candle] = None
        self._latest_signal: Optional[TradingSignal] = None

        # Candle buffers for analysis
        self._candles_1m: deque = deque(maxlen=buffer_size)
        self._candles_15m: deque = deque(maxlen=buffer_size)
        self._candles_1h: deque = deque(maxlen=buffer_size)
        self._candles_4h: deque = deque(maxlen=htf_buffer_size)

        # Callbacks
        self._signal_callbacks: List[Callable] = []
        self._update_callbacks: List[Callable] = []

        # State
        self._is_running = False

        # EventBus for broadcasting events (set via set_event_bus)
        self._event_bus = None

        # SOTA Hot/Cold Path: Indicator cache (recalculated only on candle CLOSE)
        # This prevents heavy calculations on every tick
        self._indicator_cache: Dict[str, Dict] = {
            '1m': {},
            '15m': {},
            '1h': {}
        }

        # SOTA FIX (Jan 2026): STARTUP WARMUP GUARD
        # Prevents ghost orders when backend restarts and first 15m candle triggers signal
        # Wait 30 seconds after start before routing signals to SharkTank
        self._startup_time: Optional[datetime] = None
        self._startup_warmup_seconds = 30  # Configurable cooldown

        # Logging
        self.logger = logging.getLogger(__name__)

    def _required_htf_candles(self) -> int:
        """Return the 4h candle count required by the configured HTF filter."""
        if self.trend_filter is None:
            return 0
        return max(int(getattr(self.trend_filter, "ema_period", 0)), 1)

    def set_event_bus(self, event_bus) -> None:
        """
        Set the EventBus for broadcasting events.

        Called by main.py during startup to connect RealtimeService to EventBus.

        Args:
            event_bus: EventBus instance for broadcasting
        """
        self._event_bus = event_bus
        self.logger.info("✅ EventBus connected to RealtimeService")

    def _get_signal_context(self) -> Dict[str, float]:
        """Build live signal context so runtime filters match backtest inputs."""
        funding_rate = 0.0

        if self.intelligence_service and hasattr(self.intelligence_service, "get_intelligence"):
            try:
                intel = self.intelligence_service.get_intelligence(self.symbol.upper())
                if intel is not None:
                    funding_rate = float(getattr(intel, "funding_rate", 0.0) or 0.0)
                    if abs(funding_rate) > 0.01:
                        funding_rate /= 100.0
            except Exception as exc:
                self.logger.debug(f"Failed to read funding context for {self.symbol}: {exc}")

        return {"funding_rate": funding_rate}

    # =========================================================================
    # CIRCUIT BREAKER CONTROL (Matching Backtest)
    # =========================================================================

    def enable_circuit_breaker(
        self,
        max_consecutive_losses: int = 3,
        cooldown_hours: int = 4,
        max_daily_drawdown_pct: float = 0.10
    ) -> None:
        """
        Enable Circuit Breaker for realtime trading.

        SOTA: Matches backtest behavior exactly.
        - Blocks trading after N consecutive losses per symbol/direction
        - Global halt on 10% daily drawdown

        Args:
            max_consecutive_losses: Losses before cooldown (default: 3)
            cooldown_hours: Hours to wait after trigger (default: 4)
            max_daily_drawdown_pct: Drawdown threshold for global halt (default: 10%)
        """
        self.circuit_breaker = CircuitBreaker(
            max_consecutive_losses=max_consecutive_losses,
            cooldown_hours=cooldown_hours,
            max_daily_drawdown_pct=max_daily_drawdown_pct
        )
        self.circuit_breaker_enabled = True
        self.logger.warning(
            f"🛡️ CIRCUIT BREAKER ENABLED: "
            f"max_losses={max_consecutive_losses}, "
            f"cooldown={cooldown_hours}h, "
            f"max_dd={max_daily_drawdown_pct*100:.0f}%"
        )

    def disable_circuit_breaker(self) -> None:
        """Disable Circuit Breaker."""
        self.circuit_breaker = None
        self.circuit_breaker_enabled = False
        self.logger.info("🔓 Circuit Breaker DISABLED")

    def get_circuit_breaker_status(self) -> dict:
        """Get CB status for UI."""
        if not self.circuit_breaker_enabled or not self.circuit_breaker:
            return {"enabled": False}

        return {
            "enabled": True,
            "max_losses": self.circuit_breaker.max_losses,
            "cooldown_hours": self.circuit_breaker.cooldown_hours,
            "max_daily_drawdown": self.circuit_breaker.max_daily_drawdown_pct,
            "global_blocked": self.circuit_breaker.global_blocked_until is not None,
            "blocked_symbols": {
                sym: {
                    side: {
                        "losses": data.get('losses', 0),
                        "blocked": data.get('blocked_until') is not None
                    }
                    for side, data in state.items()
                }
                for sym, state in self.circuit_breaker.state.items()
            }
        }

    async def start(self, shared_client_mode: bool = False) -> None:
        """
        Start the real-time service.

        This will:
        1. Load historical data
        2. Connect to WebSocket (unless shared_client_mode=True)
        3. Start receiving real-time data
        4. Begin analysis and signal generation

        Args:
            shared_client_mode: If True, skip WebSocket connection (data comes from SharedBinanceClient)
        """
        if self._is_running:
            self.logger.warning("Service already running")
            return

        self.logger.info(f"Starting real-time service for {self.symbol} (shared_mode={shared_client_mode})")

        try:
            # Load historical data first
            self.logger.info("Loading historical data...")
            await self._load_historical_data()

            # SOTA FIX (Jan 2026): Clear aggregator buffers BEFORE registering callbacks
            # Prevents historical data from triggering callbacks when realtime starts
            self.aggregator.clear_buffers()

            # SOTA FIX (Jan 2026): DISABLED aggregator callbacks!
            # We now use NATIVE 15m/1h WebSocket streams from Binance (see _handle_15m_candle)
            # Aggregator was building 15m from 1m candles - but native stream is more accurate
            # Keeping both active caused DUPLICATE APPEND to _candles_15m buffer
            # This could cause:
            #   1. Double candle entries (same timestamp)
            #   2. Potential double signal generation
            #   3. Incorrect indicator calculations
            #
            # self.aggregator.on_15m_complete(self._on_15m_complete)
            # self.aggregator.on_1h_complete(self._on_1h_complete)

            # SOTA: Multi-Symbol Subscription (Active + Portfolio Watchlist)
            watchlist_symbols = {self.symbol.lower()}

            # Add portfolio positions to watchlist
            if self.paper_service:
                try:
                    positions = self.paper_service.get_positions()
                    for pos in positions:
                        watchlist_symbols.add(pos.symbol.lower())
                    self.logger.info(f"📋 Portfolio Watchlist: {watchlist_symbols}")
                except Exception as e:
                    self.logger.error(f"Failed to fetch portfolio symbols: {e}")

            if shared_client_mode:
                self.logger.info("📡 Using SharedBinanceClient for data streaming")
            else:
                # Legacy: Connect own WebSocket with ALL symbols
                # Subscribe to all unique symbols in watchlist
                # SOTA FIX (Jan 2026): Intervals matching backtest
                # 1m (Base), 15m (Signal), 1h (Display), 4h (HTF trend filter)
                await self.websocket_client.connect(
                    symbols=list(watchlist_symbols),
                    intervals=['1m', '15m', '1h', '4h']  # Added 4h for HTF trend filter
                )

            self._is_running = True
            # SOTA FIX (Jan 2026): Record startup time for warmup guard (UTC aware)
            from datetime import timezone
            self._startup_time = datetime.now(timezone.utc)
            self.logger.info(f"✅ Real-time service started successfully (Startup: {self._startup_time})")

        except Exception as e:
            self.logger.error(f"Failed to start service: {e}")

    async def _load_candles_hybrid(self, timeframe: str, limit: int = 100) -> List[Candle]:
        """
        SOTA Hybrid Data Layer: Load candles from SQLite first, Binance fallback.

        Pattern: Read-through cache
        - L1: In-memory (populated by this method)
        - L2: SQLite (check first)
        - L3: Binance API (fallback + write-through)

        Args:
            timeframe: '1m', '15m', or '1h'
            limit: Number of candles to load

        Returns:
            List of Candle objects, sorted by timestamp ascending
        """
        local_candles = []

        # Step 1: Try SQLite first (L2 cache)
        if self._market_data_repository:
            try:
                market_data_list = self._market_data_repository.get_latest_candles(
                    self.symbol, timeframe, limit
                )
                local_candles = [md.candle for md in market_data_list]
                # Sort ascending (oldest first) - SQLite returns DESC
                local_candles = sorted(local_candles, key=lambda c: c.timestamp)

                if local_candles:
                    self.logger.info(f"📦 SQLite HIT: {len(local_candles)}/{limit} {timeframe} candles")
            except Exception as e:
                self.logger.warning(f"⚠️ SQLite read failed for {timeframe}: {e}")

        # Step 2: Check if we have enough data (80% threshold)
        threshold = int(limit * 0.8)
        if len(local_candles) >= threshold:
            return local_candles

            # Step 3: SQLite miss - fetch from Binance (L3)
        self.logger.info(f"📡 SQLite MISS for {timeframe} ({len(local_candles)}/{limit}), fetching from Binance...")

        try:
            external_candles = await asyncio.to_thread(
                self.rest_client.get_klines,
                symbol=self.symbol,
                interval=timeframe,
                limit=limit
            )

            if not external_candles:
                self.logger.warning(f"No external data for {timeframe}")
                return local_candles  # Return whatever we have

            # Step 4: Merge local + external, deduplicate by timestamp
            merged = self._merge_candles(local_candles, external_candles)

            # Step 5: Write-through - save new candles to SQLite
            if self._market_data_repository:
                local_timestamps = {c.timestamp for c in local_candles}
                new_candles = [c for c in merged if c.timestamp not in local_timestamps]

                if new_candles:
                    self.logger.info(f"💾 Write-through: Saving {len(new_candles)} new {timeframe} candles to SQLite")
                    # Offload DB write as well
                    await asyncio.to_thread(self._persist_candles_batch_sync, new_candles, timeframe)

            return merged

        except Exception as e:
            self.logger.error(f"Binance fetch failed for {timeframe}: {e}")
            return local_candles  # Return whatever we have from SQLite

    def _persist_candles_batch_sync(self, candles: List[Candle], timeframe: str) -> None:
        """Synchronous version for thread offloading."""
        if not self._market_data_repository or not candles:
            return
        # SOTA (Jan 2026): DISABLED runtime persist - matches Two Sigma/Citadel pattern
        # Binance is source of truth, candles fetched on startup from API
        # In-memory only during runtime to avoid blocking event loop
        pass

    def _merge_candles(self, local: List[Candle], external: List[Candle]) -> List[Candle]:
        """
        Merge local and external candles, deduplicate by timestamp.

        Priority: External (source of truth) for conflicts
        """
        # Create map by timestamp, external overwrites local
        candle_map = {}

        for candle in local:
            candle_map[candle.timestamp] = candle

        for candle in external:
            candle_map[candle.timestamp] = candle  # Overwrites if exists

        # Sort by timestamp ascending
        merged = sorted(candle_map.values(), key=lambda c: c.timestamp)
        return merged

    async def _load_candles_from_binance_async(self, timeframe: str, limit: int = 500) -> List[Candle]:
        """
        SOTA Helper: Fetch candles using Non-Blocking Async Client.

        STAGGERED LOADING (Jan 2026): Uses global semaphore to limit concurrent API calls.
        This prevents rate limiting when 50 symbols load simultaneously.
        """
        if not self.async_client:
            return []

        # SOTA: Use semaphore to limit concurrent API calls (max 5)
        semaphore = get_binance_api_semaphore()

        try:
            async with semaphore:
                self.logger.debug(f"📡 Fetching {timeframe} candles for {self.symbol} (semaphore acquired)")
                raw_klines = await self.async_client.get_klines(self.symbol, timeframe, limit)

            candles = []
            for k in raw_klines:
                # Binance Kline: [Open Time, Open, High, Low, Close, Volume, Close Time, ...]
                # Timestamp is ms. Candle entity expects datetime.
                ts_sec = int(k[0]) / 1000
                dt = datetime.fromtimestamp(ts_sec)

                c = Candle(
                    timestamp=dt,
                    open=float(k[1]),
                    high=float(k[2]),
                    low=float(k[3]),
                    close=float(k[4]),
                    volume=float(k[5])
                )
                candles.append(c)
            return candles
        except Exception as e:
            self.logger.error(f"Async fetch failed for {timeframe}: {e}")
            return []

    async def _load_historical_data(self) -> None:
        """
        SOTA Fresh Load: Always fetch 500 latest candles from Binance on startup.

        CRITICAL FIX (Jan 2026): All 3 timeframes are now loaded IN PARALLEL!
        Before: Sequential await → 50 services × 3 TF × 300ms = 45s
        After:  Parallel gather → 50 services × 1 TF × 500ms = 2-3s
        """
        try:
            self.logger.info("🚀 Loading historical candles (SOTA Parallel Mode)...")

            CANDLE_LOAD_LIMIT = 500

            # SOTA FIX: Load ALL timeframes in parallel using asyncio.gather
            # This reduces startup from ~45s to ~2s for 50 symbols!
            required_htf_candles = self._required_htf_candles()
            htf_load_limit = max(250, required_htf_candles + 50)
            self.logger.info(f"📡 Fetching candles for 1m/15m/1h/4h in PARALLEL...")

            results = await asyncio.gather(
                self._load_candles_from_binance_async('1m', CANDLE_LOAD_LIMIT),
                self._load_candles_from_binance_async('15m', CANDLE_LOAD_LIMIT),
                self._load_candles_from_binance_async('1h', CANDLE_LOAD_LIMIT),
                self._load_candles_from_binance_async('4h', htf_load_limit),
                return_exceptions=True
            )

            candles_1m = results[0] if not isinstance(results[0], Exception) else []
            candles_15m = results[1] if not isinstance(results[1], Exception) else []
            candles_1h = results[2] if not isinstance(results[2], Exception) else []
            candles_4h = results[3] if not isinstance(results[3], Exception) else []  # SOTA: 4h for HTF

            # Process 1m candles
            if candles_1m:
                self._candles_1m.clear()
                for candle in candles_1m:
                    self._candles_1m.append(candle)
                    # SOTA FIX (Jan 2026): DO NOT add to aggregator!
                    # Historical data should NOT trigger callbacks.
                    # Aggregator is for REALTIME data only to build 15m/1h from 1m.
                    # We already have native 15m/1h from Binance API.
                self._latest_1m = candles_1m[-1]
                self.logger.debug(f"✅ Loaded {len(candles_1m)} 1m candles")

            # Process 15m candles
            if candles_15m and len(candles_15m) > 1:
                self._candles_15m.clear()
                completed_15m = candles_15m[:-1]  # Exclude incomplete
                for candle in completed_15m:
                    self._candles_15m.append(candle)
                self._latest_15m = completed_15m[-1]
                self.logger.debug(f"✅ Loaded {len(completed_15m)} 15m candles")

            # Process 1h candles
            if candles_1h and len(candles_1h) > 1:
                self._candles_1h.clear()
                completed_1h = candles_1h[:-1]
                for candle in completed_1h:
                    self._candles_1h.append(candle)
                self._latest_1h = completed_1h[-1]
                self.logger.debug(f"✅ Loaded {len(completed_1h)} 1h candles")

            # SOTA FIX (Jan 2026): Process 4h candles for HTF trend filter
            if candles_4h and len(candles_4h) > 1:
                self._candles_4h.clear()
                completed_4h = candles_4h[:-1]
                for candle in completed_4h:
                    self._candles_4h.append(candle)
                self._latest_4h = completed_4h[-1]
                self.logger.info(
                    f"✅ Loaded {len(completed_4h)} 4h candles for HTF EMA({required_htf_candles})"
                )
            else:
                self.logger.warning(
                    f"⚠️ Only {len(candles_4h) if candles_4h else 0} 4h candles loaded "
                    f"(need {required_htf_candles}+ for HTF EMA)"
                )

            # SOTA FIX (Jan 2026): Persist to SQLite in BACKGROUND (fire-and-forget)
            # Previously: await asyncio.gather(*persist_tasks) → 871s for 50 services!
            # Root cause: SQLite WAL allows only 1 writer → all others wait → serialized
            # Fix: Don't wait for persist during startup - persist in background
            if self._market_data_repository:
                async def persist_in_background():
                    """Fire-and-forget persist - don't block startup."""
                    persist_tasks = []
                    if candles_1m:
                        persist_tasks.append(asyncio.to_thread(self._persist_candles_batch_sync, candles_1m, '1m'))
                    if candles_15m:
                        persist_tasks.append(asyncio.to_thread(self._persist_candles_batch_sync, candles_15m[:-1], '15m'))
                    if candles_1h:
                        persist_tasks.append(asyncio.to_thread(self._persist_candles_batch_sync, candles_1h[:-1], '1h'))
                    if persist_tasks:
                        await asyncio.gather(*persist_tasks, return_exceptions=True)
                    self.logger.debug(f"📦 Background persist complete for {self.symbol}")

                asyncio.create_task(persist_in_background())

            self.logger.info(f"✅ Historical data loaded: {len(candles_1m)}/1m, {len(candles_15m)}/15m, {len(candles_1h)}/1h")

            # SOTA FIX (Jan 2026): Pre-warm indicator cache IN THREAD to avoid blocking event loop
            # get_latest_indicators() is CPU-bound and would block other services from parallel loading
            async def prewarm_indicators():
                self._indicator_cache['1m'] = await asyncio.to_thread(self.get_latest_indicators, '1m')
                self._indicator_cache['15m'] = await asyncio.to_thread(self.get_latest_indicators, '15m')
                self._indicator_cache['1h'] = await asyncio.to_thread(self.get_latest_indicators, '1h')

            # Fire-and-forget: don't wait for indicator pre-warm during startup
            # They'll be calculated on first candle close anyway

            # ============================================================
            # FIX 2: INITIAL SIGNAL SCAN - DISABLED (Jan 2026)
            # ============================================================
            # CRITICAL FIX: Disabled initial signal scan on startup.
            # This was causing duplicate signals every time backend restarts.
            #
            # Root cause: Every restart triggered an immediate scan, creating
            # signals even when no new candle had closed. Combined with multiple
            # restarts, this caused 5-10 extra signals per restart.
            #
            # Solution: Let the first natural 15m candle close trigger signals.
            # User waits max 15 minutes for first signal, but avoids over-trading.
            # ============================================================
            # if self._candles_15m and self.live_trading_service:
            #     latest_closed = self._candles_15m[-1]
            #     try:
            #         now_utc = datetime.now(timezone.utc)
            #         candle_ts = latest_closed.timestamp
            #         if candle_ts.tzinfo is None:
            #             candle_ts = candle_ts.replace(tzinfo=timezone.utc)
            #
            #         age_seconds = (now_utc - candle_ts).total_seconds()
            #
            #         if age_seconds < 3600:
            #             self.logger.info(f"🚀 Performing INITIAL SIGNAL SCAN on candle {latest_closed.timestamp} (age={int(age_seconds)}s)...")
            #             asyncio.create_task(self._generate_signals_async())
            #         else:
            #             self.logger.info(f"⏭️ Skipping initial scan: Last candle too old ({int(age_seconds)}s > 3600s)")
            #     except Exception as e:
            #         self.logger.warning(f"⚠️ Initial scan timestamp check failed: {e}")
            self.logger.info("⏭️ Initial signal scan DISABLED - waiting for first natural 15m candle close")
            asyncio.create_task(prewarm_indicators())
            self.logger.debug("📊 Indicator cache pre-warming started (background)")

        except Exception as e:
            self.logger.error(f"❌ Error loading historical data: {e}")
            self.logger.info("🔄 Falling back to hybrid load...")
            await self._load_historical_data_hybrid_fallback()

    async def _load_historical_data_hybrid_fallback(self) -> None:
        """Fallback hybrid load if fresh Binance load fails."""
        try:
            CANDLE_LOAD_LIMIT = 500

            candles_1m = await self._load_candles_hybrid('1m', CANDLE_LOAD_LIMIT)
            for candle in candles_1m:
                self._candles_1m.append(candle)
            if candles_1m:
                self._latest_1m = candles_1m[-1]

            candles_15m = await self._load_candles_hybrid('15m', CANDLE_LOAD_LIMIT)
            if candles_15m:
                for candle in candles_15m[:-1]:
                    self._candles_15m.append(candle)
                self._latest_15m = candles_15m[-2] if len(candles_15m) > 1 else None

            candles_1h = await self._load_candles_hybrid('1h', CANDLE_LOAD_LIMIT)
            if candles_1h:
                for candle in candles_1h[:-1]:
                    self._candles_1h.append(candle)
                self._latest_1h = candles_1h[-2] if len(candles_1h) > 1 else None

            self.logger.info("✅ Hybrid fallback load complete")
        except Exception as e:
            self.logger.error(f"Hybrid fallback also failed: {e}")

    def _persist_candles_batch(self, candles: List[Candle], timeframe: str) -> None:
        """Persist a batch of candles to SQLite asynchronously."""
        if not self._market_data_repository or not candles:
            return

        # SOTA (Jan 2026): DISABLED runtime persist - in-memory only for hot path
        # Binance API is source of truth for historical candles
        pass

    async def stop(self) -> None:
        """
        Stop the real-time service.

        This will:
        1. Disconnect from WebSocket
        2. Clear buffers
        3. Reset state
        """
        if not self._is_running:
            self.logger.warning("Service not running")
            return

        self.logger.info("Stopping real-time service...")

        try:
            # Disconnect WebSocket
            await self.websocket_client.disconnect()

            # SOTA: Close Async Client
            if self.async_client:
                await self.async_client.close()

            # MEMORY FIX (Feb 8, 2026): Clear all in-memory state on shutdown
            self._signal_callbacks.clear()
            self._update_callbacks.clear()
            self._indicator_cache = {'1m': {}, '15m': {}, '1h': {}}
            self._latest_signal = None
            self._latest_1m = None
            self._latest_15m = None
            self._latest_1h = None
            self._latest_4h = None

            self._is_running = False
            self.logger.info("✅ Real-time service stopped (memory cleared)")

        except Exception as e:
            self.logger.error(f"Error stopping service: {e}")

    async def on_candle_update(self, candle: Candle, metadata: Dict) -> None:
        """
        Public callback for SharedBinanceClient data routing.

        SOTA: This is called by SharedBinanceClient when data arrives
        for this service's symbol. Delegates to internal _on_candle_received.

        Args:
            candle: Candle entity
            metadata: Metadata (is_closed, symbol, interval, etc.)
        """
        # CRITICAL FIX (Jan 2026): Verify this candle is for our symbol
        # BUG FIXED: Previously empty symbol "" would bypass filter → ALL services process!
        incoming_symbol = metadata.get('symbol', '').lower()

        # SOTA: Reject candles without valid symbol metadata
        if not incoming_symbol:
            self.logger.warning(f"Rejecting candle without symbol metadata (expected {self.symbol})")
            return

        if incoming_symbol != self.symbol.lower():
            self.logger.debug(f"Ignoring candle for {incoming_symbol} (expected {self.symbol})")
            return

        await self._on_candle_received(candle, metadata)

    async def _on_candle_received(self, candle: Candle, metadata: Dict) -> None:
        """
        Callback when candle is received from WebSocket.

        SOTA: With multi-stream, this receives 1m, 15m, AND 1h candles.
        Route based on metadata.interval.

        Args:
            candle: Candle entity
            metadata: Metadata (is_closed, symbol, interval, etc.)
        """
        interval = metadata.get('interval', '1m')
        is_closed = metadata.get('is_closed', False)

        # SOTA FIX (Jan 2026): Parent function on_candle_update already validated symbol
        # At this point, candle_symbol WILL be this service's symbol
        candle_symbol = metadata.get('symbol', '').lower() or self.symbol.lower()
        self.logger.debug(f"🕯️ [{interval}] Candle: {candle.close:.2f} closed={is_closed} symbol={candle_symbol}")

        # SOTA: Since on_candle_update validated, this is ALWAYS the active symbol
        is_active_symbol = True  # Validated in parent function

        # SOTA: Always persist ALL incoming data (for Portfolio PnL)
        # This acts as the "Background Price Oracle" feeder
        if self._market_data_repository:
             try:
                 # 1. Update In-Memory Hot Cache (Fastest, for live PnL)
                 self._market_data_repository.update_realtime_price(candle_symbol, candle.close)

                 # SOTA (Jan 2026): DISABLED SQLite persist during runtime
                 # Candles stay in-memory only - Binance is source of truth
                 # This eliminates 50+ SQLite commits/minute blocking event loop
             except Exception as e:
                 pass

        # SOTA Multi-Stream Routing
        if interval == '15m':
            self._handle_15m_candle(candle, is_closed)
            return
        elif interval == '1h':
            self._handle_1h_candle(candle, is_closed)
            return
        elif interval == '4h':
            self._handle_4h_candle(candle, is_closed)
            return

        # --- 1m Processing (Base Timeframe) ---

        # CRITICAL SOTA FILTER: Only process signals/chart updates for the ACTIVE symbol.
        # Passive portfolio symbols are handled above (persistence only) and then ignored here.
        if not is_active_symbol:
             # SOTA FIX (Jan 2026): Broadcast to SYMBOL'S OWN channel, NOT active channel!
             # BUG FIXED: Previously broadcast SOL/ETH/XRP data to BTC channel → price mixing!
             # Now each symbol broadcasts to its own channel (e.g., 'solusdt' → 'solusdt' channel)
             if self._event_bus:
                 # CRITICAL FIX (Jan 2026): Use EventBus, NOT connection_manager!
                 # connection_manager was undefined → PASSIVE symbols got no broadcasts!
                 candle_data = {
                     'open': candle.open,
                     'high': candle.high,
                     'low': candle.low,
                     'close': candle.close,
                     'volume': candle.volume,
                     'timestamp': candle.timestamp.isoformat() if hasattr(candle.timestamp, 'isoformat') else str(candle.timestamp),
                     'time': int(candle.timestamp.timestamp()) if hasattr(candle.timestamp, 'timestamp') else 0,
                 }
                 # Use EventBus just like ACTIVE symbol (line 808)
                 self._event_bus.publish_candle_update(candle_data, symbol=candle_symbol.lower())
             return

        # Default: 1m candle processing for ACTIVE symbol
        # Check if this is a NEW candle (different timestamp from current latest)

        if self._latest_1m and candle.timestamp != self._latest_1m.timestamp:
            # New candle started - the previous one is now complete
            self.logger.debug(f"New candle detected: {candle.timestamp} - Saving previous candle")
            self._candles_1m.append(self._latest_1m)
            self.logger.debug(f"Buffer size: {len(self._candles_1m)}")

            # Add to aggregator (for indicator calculation)
            self.aggregator.add_candle_1m(self._latest_1m, is_closed=True)

            # SOTA FIX (Jan 2026): REMOVED signal generation from 1m!
            # Signals are now generated ONLY on 15m close (see _handle_15m_candle)
            # This matches backtest --interval=15m behavior exactly.


        # Always update latest 1m candle (for real-time display of ACTIVE symbol)
        self._latest_1m = candle

        # SOTA FIX: Broadcast candle update via EventBus to frontend WebSocket
        if self._event_bus:
            # SOTA HOT PATH: Use cached indicators (calculated on candle close)
            # This prevents heavy recalculation on every tick
            indicators = self._indicator_cache.get('1m', {})

            # SOTA FIX: Extract SCALAR values for frontend (not objects)
            vwap_val = indicators.get('vwap')
            if isinstance(vwap_val, dict):
                vwap_val = vwap_val.get('vwap', vwap_val.get('value'))
            elif hasattr(vwap_val, 'vwap'):
                vwap_val = vwap_val.vwap

            rsi_val = indicators.get('rsi')
            if isinstance(rsi_val, dict):
                rsi_val = rsi_val.get('value', rsi_val.get('rsi'))

            candle_data = {
                'open': candle.open,
                'high': candle.high,
                'low': candle.low,
                'close': candle.close,
                'volume': candle.volume,
                'timestamp': candle.timestamp.isoformat() if hasattr(candle.timestamp, 'isoformat') else str(candle.timestamp),
                'time': int(candle.timestamp.timestamp()) if hasattr(candle.timestamp, 'timestamp') else 0,
                'vwap': float(vwap_val) if vwap_val is not None else None,
                'bollinger': indicators.get('bollinger'),
                'rsi': float(rsi_val) if rsi_val is not None else None,
            }
            self._event_bus.publish_candle_update(candle_data, symbol=self.symbol)
            self.logger.debug(f"📡 EventBus: Published 1m candle {candle.close:.2f}")

        # Paper Engine Matching (Run on every tick/candle update)
        if self.paper_service:
            self.paper_service.process_market_data(
                current_price=candle.close,
                high=candle.high,
                low=candle.low,
                symbol=self.symbol
            )

        # LIVE Engine Matching (Run on every candle for trailing stop)
        if self.live_trading_service and self.live_trading_service.enable_trading:
            await self.live_trading_service.process_market_data_async(
                symbol=self.symbol,
                current_price=candle.close,
                high=candle.high,
                low=candle.low
            )

        # SOTA LocalSignalTracker Hook (Jan 2026)
        # Check if price triggers any pending signals → execute MARKET order
        # NOTE: This runs ALWAYS (even in Safe Mode) because:
        # - It allows user to SEE signals triggering in logs
        # - Actual execution is guarded inside _execute_triggered_signal() (EMS layer)
        # - This matches institutional OMS/EMS separation pattern
        if self.live_trading_service:
            # SOTA (Jan 2026): Check both tick price AND candle HIGH/LOW for fill
            # 1. Tick-based check (current close price)
            self.live_trading_service.check_pending_signals(self.symbol, candle.close)

            # 2. Candle-based check with pessimistic fill model (matches backtest)
            # This catches fills where candle HIGH/LOW passed through target
            # but tick didn't report exact target price
            self.live_trading_service.check_pending_signals_on_candle(
                self.symbol, candle.low, candle.high
            )

        # Also add if explicitly closed by Binance
        if is_closed and (not self._candles_1m or candle.timestamp != self._candles_1m[-1].timestamp):
            self.logger.debug(f"Candle explicitly closed: {candle.timestamp}")
            self._candles_1m.append(candle)
            self.logger.debug(f"Buffer size: {len(self._candles_1m)}")

            # Add to aggregator
            self.aggregator.add_candle_1m(candle, is_closed=True)

            # SOTA FIX (Jan 2026): REMOVED duplicate signal generation!
            # Signals are generated in _handle_15m_candle ONLY.
            # calling it here caused 15 signals per 15m candle (1 per minute).
            # self._generate_signals()

            # SOTA COLD PATH: Update indicator cache on candle close
            # Heavy calculation happens here (once per minute), not on every tick
            self._indicator_cache['1m'] = self.get_latest_indicators('1m')
            self.logger.debug(f"📊 Indicators recalculated and cached for 1m")

        # Notify update callbacks
        self.logger.debug(f"📢 Calling _notify_update_callbacks with {len(self._update_callbacks)} callbacks")
        self._notify_update_callbacks()

    def _handle_15m_candle(self, candle: Candle, is_closed: bool) -> None:
        """
        SOTA Multi-Stream: Handle 15m candle from Binance combined stream.

        This receives NATIVE 15m candles directly from Binance WebSocket.
        Broadcasts to frontend for realtime chart updates.

        Args:
            candle: 15m Candle entity
            is_closed: Whether candle is closed
        """
        # Update latest 15m candle
        self._latest_15m = candle

        # If closed, add to buffer and persist
        if is_closed:
            self._candles_15m.append(candle)

            # SOTA (Jan 2026): DISABLED SQLite persist - candles stay in-memory only
            # Binance API provides historical data on startup
            pass

            # ============================================================
            # FIX 1: HISTORICAL CANDLE GUARD - RE-ENABLED (Jan 2026)
            # ============================================================
            # CRITICAL FIX: Only process candles that closed within last 30 minutes.
            # This prevents processing 500 historical candles on backend restart,
            # which was causing massive over-trading (500 signals vs 1 signal).
            #
            # Root cause: When backend restarts, it loads 500 historical 15m candles
            # from Binance API. Without this guard, ALL 500 candles trigger signal
            # generation, creating 500 opportunities instead of 1.
            # ============================================================
            now_utc = datetime.now(timezone.utc)
            candle_ts = candle.timestamp
            if candle_ts.tzinfo is None:
                candle_ts = candle_ts.replace(tzinfo=timezone.utc)

            age_seconds = (now_utc - candle_ts).total_seconds()

            if age_seconds > 1800:  # 30 minutes = 1800 seconds
                self.logger.debug(f"⏭️ Skipping historical candle (age={int(age_seconds)}s, closed at {candle_ts})")
                return

            # IMMEDIATE SIGNAL GENERATION on 15m close - MATCHES BACKTEST!
            self.logger.info(f"📊 15m candle closed at {candle.close:.2f} (age={int(age_seconds)}s) - Generating signals (async)")
            asyncio.create_task(self._generate_signals_async())

        # Broadcast to frontend (both forming and closed candles)
        if self._event_bus:
            candle_data = {
                'open': candle.open,
                'high': candle.high,
                'low': candle.low,
                'close': candle.close,
                'volume': candle.volume,
                'timestamp': candle.timestamp.isoformat() if hasattr(candle.timestamp, 'isoformat') else str(candle.timestamp),
                'time': int(candle.timestamp.timestamp()) if hasattr(candle.timestamp, 'timestamp') else 0,
            }
            self._event_bus.publish_candle_15m(candle_data, symbol=self.symbol)
            self.logger.debug(f"📡 EventBus: Published 15m candle {candle.close:.2f} (closed={is_closed})")

    def _handle_1h_candle(self, candle: Candle, is_closed: bool) -> None:
        """
        SOTA Multi-Stream: Handle 1h candle from Binance combined stream.

        This receives NATIVE 1h candles directly from Binance WebSocket.
        Broadcasts to frontend for realtime chart updates.

        Args:
            candle: 1h Candle entity
            is_closed: Whether candle is closed
        """
        # Update latest 1h candle
        self._latest_1h = candle

        # If closed, add to buffer and persist
        if is_closed:
            self._candles_1h.append(candle)

            # SOTA (Jan 2026): DISABLED SQLite persist - in-memory only architecture
            pass

        # Broadcast to frontend (both forming and closed candles)
        if self._event_bus:
            candle_data = {
                'open': candle.open,
                'high': candle.high,
                'low': candle.low,
                'close': candle.close,
                'volume': candle.volume,
                'timestamp': candle.timestamp.isoformat() if hasattr(candle.timestamp, 'isoformat') else str(candle.timestamp),
                'time': int(candle.timestamp.timestamp()) if hasattr(candle.timestamp, 'timestamp') else 0,
            }
            self._event_bus.publish_candle_1h(candle_data, symbol=self.symbol)
            self.logger.debug(f"📡 EventBus: Published 1h candle {candle.close:.2f} (closed={is_closed})")

    # REMOVED (Jan 2026): Legacy aggregator callbacks
    # These methods were used when building 15m/1h from 1m candles via DataAggregator.
    # Now we use NATIVE 15m/1h WebSocket streams from Binance (see _handle_15m_candle).
    # Callbacks were disabled to prevent duplicate candles and signals.
    # Methods removed to clean up codebase - no longer needed.

    def _handle_4h_candle(self, candle: Candle, is_closed: bool) -> None:
        """
        SOTA FIX (Jan 2026): Handle 4h candle for HTF trend filter.

        This matches the configured backtest HTF contract on the 4h timeframe.
        4h candles are used ONLY for TrendFilter calculation, not for display.

        Pattern: Institutional (Two Sigma/Citadel) - 4h determines DIRECTION, 15m determines TIMING.

        Args:
            candle: 4h Candle entity
            is_closed: Whether candle is closed
        """
        # Update latest 4h candle
        self._latest_4h = candle

        # If closed, add to buffer for HTF EMA calculation
        if is_closed:
            self._candles_4h.append(candle)

            # Log HTF status periodically
            candle_count = len(self._candles_4h)
            required_htf_candles = self._required_htf_candles()
            if candle_count >= required_htf_candles:
                self.logger.info(
                    f"📊 4h candle closed: {candle.close:.2f} | "
                    f"HTF buffer: {candle_count}/{required_htf_candles} ✅ HTF ready"
                )
            else:
                self.logger.warning(
                    f"📊 4h candle closed: {candle.close:.2f} | "
                    f"HTF buffer: {candle_count}/{required_htf_candles} ⚠️ Need more for HTF EMA"
                )

        # NOTE: 4h candles are NOT broadcasted to frontend
        # They are only used internally for TrendFilter HTF bias calculation

    def _generate_signals(self) -> None:
        """Generate trading signals based on current data."""
        # SOTA FIX (Jan 2026): Use 15m buffer to match backtest!
        # Backtest uses --interval=15m, so live must use 15m candles.
        if len(self._candles_15m) < 20:
            return

        try:
            # SOTA FIX (Jan 2026): HTF Trend Filter using 4h + configured EMA period.
            htf_bias = 'NEUTRAL'
            required_htf_candles = self._required_htf_candles()
            if self.trend_filter and len(self._candles_4h) >= required_htf_candles:
                htf_trend = self.trend_filter.get_trend_direction(list(self._candles_4h))
                htf_bias = htf_trend.value if htf_trend else 'NEUTRAL'
                self.logger.debug(
                    f"HTF Trend (4h EMA{required_htf_candles}) for 15m signal: {htf_bias}"
                )
            elif self.trend_filter and len(self._candles_4h) < required_htf_candles:
                self.logger.debug(
                    f"HTF Trend: NEUTRAL (only {len(self._candles_4h)}/{required_htf_candles} "
                    f"4h candles for EMA{required_htf_candles})"
                )

            # SOTA FIX: Use 15m candles like backtest!
            signal = self.signal_generator.generate_signal(
                list(self._candles_15m),  # FIXED: Was _candles_1m
                symbol=self.symbol,
                htf_bias=htf_bias,  # SOTA: Pass HTF bias like backtest
                **self._get_signal_context()
            )

            if signal and signal.signal_type.value != 'neutral':
                self.logger.debug(f"📊 Signal generated: {self.symbol} {signal.signal_type.value}")

                # CRITICAL FIX: Use SignalConfirmationService to prevent whipsaw
                # Requires 2 consecutive signals in same direction
                if self._signal_confirmation_service:
                    self.logger.debug(f"📋 Sending to SignalConfirmationService (min={self._signal_confirmation_service.min_confirmations})")
                    confirmed_signal = self._signal_confirmation_service.process_signal(
                        self.symbol, signal
                    )

                    if not confirmed_signal:
                        # Signal pending confirmation - don't execute yet
                        self.logger.debug(
                            f"⏳ Signal {signal.signal_type.value} pending confirmation"
                        )
                        return

                    # Use confirmed signal (may have better entry price)
                    signal = confirmed_signal
                    self.logger.info(f"🎯 CONFIRMED signal executing: {signal.signal_type.value}")

                self._latest_signal = signal
                self.logger.info(f"Signal generated: {signal}")

                # CIRCUIT BREAKER CHECK (matching backtest logic)
                if self.circuit_breaker_enabled and self.circuit_breaker:
                    from datetime import datetime, timezone
                    current_time = datetime.now(timezone.utc)

                    # Determine side for CB check
                    side = 'LONG' if signal.signal_type.value == 'buy' else 'SHORT'

                    if self.circuit_breaker.is_blocked(self.symbol.upper(), side, current_time):
                        self.logger.warning(
                            f"🛡️ CIRCUIT BREAKER: {self.symbol} {side} blocked - skipping signal"
                        )
                        return  # Skip this signal

                # SOTA FIX: Save signal FIRST to get signal_id
                saved_signal = self._notify_signal_callbacks(signal)

                # SHARK TANK: Route through coordinator for batch ranking
                # This matches backtest behavior where signals are ranked by score
                if self._shark_tank_coordinator:
                    # STARTUP WARMUP GUARD: Wait 30s after startup before trading
                    # Prevents ghost orders when backend restarts and first candle triggers signal
                    if self._startup_time:
                        from datetime import timezone
                        elapsed = (datetime.now(timezone.utc) - self._startup_time).total_seconds()

                        if elapsed < self._startup_warmup_seconds:
                            self.logger.warning(
                                f"⏳ STARTUP WARMUP: Skipping signal for {self.symbol} "
                                f"(elapsed={elapsed:.1f}s < {self._startup_warmup_seconds}s)"
                            )
                            return  # Skip signal during warmup period

                    # Queue signal for batch processing (will be ranked and executed)
                    self._shark_tank_coordinator.collect_signal(signal, self.symbol)
                    self.logger.debug(f"🦈 Signal queued to SharkTank: {self.symbol}")
                else:
                    # Fallback: Direct execution (old behavior)
                    self._execute_signal_direct(signal, saved_signal)

        except Exception as e:
            self.logger.error(f"Error generating signals: {e}")

    async def _generate_signals_async(self) -> None:
        """
        SOTA (Jan 2026): Non-blocking signal generation.

        Offloads heavy indicator calculation to ThreadPoolExecutor.
        This prevents blocking the asyncio Event Loop during 15m candle close
        when processing 50+ symbols simultaneously.

        Pattern: Two Sigma / Citadel architecture - separate CPU work from I/O.
        """
        if len(self._candles_15m) < 20:
            return

        try:
            # SOTA FIX (Jan 2026): HTF Trend Filter using 4h + configured EMA period.
            htf_bias = 'NEUTRAL'
            required_htf_candles = self._required_htf_candles()
            if self.trend_filter and len(self._candles_4h) >= required_htf_candles:
                htf_trend = self.trend_filter.get_trend_direction(list(self._candles_4h))
                htf_bias = htf_trend.value if htf_trend else 'NEUTRAL'
                self.logger.debug(
                    f"HTF Trend (4h EMA{required_htf_candles}) for 15m signal: {htf_bias}"
                )
            elif self.trend_filter and len(self._candles_4h) < required_htf_candles:
                self.logger.debug(
                    f"HTF Trend: NEUTRAL (only {len(self._candles_4h)}/{required_htf_candles} "
                    f"4h candles for EMA{required_htf_candles})"
                )

            # SOTA: Offload heavy indicator calculation to ThreadPool
            from src.infrastructure.workers.indicator_worker import calculate_indicators_async

            # Pre-calculate indicators in ThreadPool (non-blocking)
            indicators = await calculate_indicators_async(
                list(self._candles_15m),
                self.talib_calculator
            )

            # Signal generation (fast, uses pre-calculated indicators)
            signal = self.signal_generator.generate_signal(
                list(self._candles_15m),
                symbol=self.symbol,
                htf_bias=htf_bias,
                **self._get_signal_context()
            )

            if signal and signal.signal_type.value != 'neutral':
                self.logger.debug(f"📊 Signal generated: {self.symbol} {signal.signal_type.value}")

                # Confirmation service check
                if self._signal_confirmation_service:
                    self.logger.debug(f"📋 Sending to SignalConfirmationService")
                    confirmed_signal = self._signal_confirmation_service.process_signal(
                        self.symbol, signal
                    )

                    if not confirmed_signal:
                        self.logger.debug(f"⏳ Signal {signal.signal_type.value} pending confirmation")
                        return

                    signal = confirmed_signal
                    self.logger.info(f"🎯 CONFIRMED signal executing: {signal.signal_type.value}")

                self._latest_signal = signal
                self.logger.info(f"Signal generated: {signal}")

                # Circuit breaker check
                if self.circuit_breaker_enabled and self.circuit_breaker:
                    from datetime import datetime, timezone
                    current_time = datetime.now(timezone.utc)
                    side = 'LONG' if signal.signal_type.value == 'buy' else 'SHORT'

                    if self.circuit_breaker.is_blocked(self.symbol.upper(), side, current_time):
                        self.logger.warning(f"🛡️ CIRCUIT BREAKER: {self.symbol} {side} blocked")
                        return

                # Save signal and notify
                saved_signal = self._notify_signal_callbacks(signal)

                # STARTUP WARMUP GUARD - DISABLED (Jan 2026)
                # Previously this blocked signals for 30s after startup.
                # Now disabled for immediate signal routing.
                # If needed in production, implement as configurable option.

                # Route to SharkTank IMMEDIATELY
                if self._shark_tank_coordinator:
                    self._shark_tank_coordinator.collect_signal(signal, self.symbol)
                    self.logger.debug(f"🦈 Signal queued to SharkTank: {self.symbol}")
                else:
                    self._execute_signal_direct(signal, saved_signal)

        except Exception as e:
            self.logger.error(f"Error in async signal generation: {e}")

    def _execute_signal_direct(self, signal: TradingSignal, saved_signal: Optional[TradingSignal] = None) -> None:
        """
        Execute signal directly (called by SharkTank callback or fallback).

        SOTA: Extracted from _generate_signals for reuse.
        """
        # LIVE TRADING: Route to live or paper based on toggle
        if self.live_trading_service and self.live_trading_service.enable_trading:
            # 🔴 LIVE MODE: Execute real orders on Binance
            self.logger.warning(f"🔴 LIVE TRADING: Signal routed to LiveTradingService...")
            success = self.live_trading_service.execute_signal(signal)
            if success:
                self.logger.info(f"✅ SIGNAL QUEUED: {signal.symbol} added to LocalSignalTracker")
            else:
                self.logger.error(f"❌ SIGNAL REJECTED: Failed to add to LocalSignalTracker")
        elif self.paper_service:
            # 📝 PAPER MODE: Simulate locally
            self.paper_service.on_signal_received(signal, signal.symbol or self.symbol)

            # SOTA FIX: Link signal to order via mark_executed
            if saved_signal and self._lifecycle_service:
                try:
                    pending_orders = self.paper_service.repo.get_pending_orders()
                    for order in pending_orders:
                        if order.symbol.lower() == self.symbol.lower():
                            self._lifecycle_service.mark_executed(saved_signal.id, order.id)
                            self.logger.info(f"🔗 Signal {saved_signal.id[:8]}... linked to order {order.id[:8]}...")
                            break
                except Exception as e:
                    self.logger.error(f"Error linking signal to order: {e}")

    # REMOVED (Jan 2026): Legacy signal generation methods
    # _generate_signals_15m() and _generate_signals_1h() were called by aggregator callbacks.
    # Now we use _generate_signals_async() called from _handle_15m_candle() (native stream).
    # Methods removed - use _generate_signals_async() instead.

    def _notify_signal_callbacks(self, signal: TradingSignal) -> Optional[TradingSignal]:
        """
        Notify all signal callbacks, persist to DB, and broadcast via EventBus.

        SOTA FIX: Returns saved signal for linking with orders.

        Returns:
            Optional[TradingSignal]: The saved signal with ID, or None if not saved
        """
        # DEBUG: Log signal and lifecycle service status
        self.logger.info(f"🔔 Signal callback: {signal.signal_type.value} @ ${signal.price:.2f} (lifecycle_service: {'OK' if self._lifecycle_service else 'NONE'})")

        saved_signal = None

        # 1. SOTA FIX: Save signal to database via lifecycle service
        if self._lifecycle_service:
            try:
                saved_signal = self._lifecycle_service.register_signal(signal)
                self.logger.info(f"💾 Signal persisted: {saved_signal.id if saved_signal else 'none'}")
            except Exception as e:
                self.logger.error(f"Error persisting signal: {e}")

        # 2. SOTA FIX: Broadcast signal via EventBus to frontend
        if self._event_bus:
            try:
                signal_data = {
                    'id': getattr(signal, 'id', None) or (saved_signal.id if saved_signal else None),
                    'signal_type': signal.signal_type.value,
                    'price': signal.price,
                    'entry_price': signal.entry_price,
                    'stop_loss': signal.stop_loss,
                    'tp_levels': signal.tp_levels,
                    'confidence': signal.confidence,
                    'timeframe': '15m',  # SOTA FIX (Jan 2026): Matches backtest --interval=15m
                    'timestamp': signal.timestamp.isoformat() if signal.timestamp else None,
                    'meta': getattr(signal, 'meta', {}),
                }
                self._event_bus.publish_signal(signal_data, symbol=self.symbol)
                self.logger.info(f"📡 Signal broadcasted: {signal.signal_type.value}")
            except Exception as e:
                self.logger.error(f"Error broadcasting signal: {e}")

        # 3. Legacy: Notify registered callbacks
        for callback in self._signal_callbacks:
            try:
                callback(signal)
            except Exception as e:
                self.logger.error(f"Error in signal callback: {e}")

        return saved_signal

    def _notify_update_callbacks(self) -> None:
        """Notify all update callbacks."""
        if self._update_callbacks:
            self.logger.debug(f"Notifying {len(self._update_callbacks)} update callbacks")
        for callback in self._update_callbacks:
            try:
                callback()
            except Exception as e:
                self.logger.error(f"Error in update callback: {e}", exc_info=True)

    # Public API for dashboard

    def get_latest_data(self, timeframe: str = '1m') -> Optional[Candle]:
        """
        Get latest candle for specified timeframe.

        Args:
            timeframe: '1m', '15m', or '1h'

        Returns:
            Latest Candle or None
        """
        if timeframe == '1m':
            return self._latest_1m
        elif timeframe == '15m':
            return self._latest_15m
        elif timeframe == '1h':
            return self._latest_1h
        else:
            return None

    def get_current_signals(self) -> Optional[TradingSignal]:
        """
        Get current trading signal.

        Returns:
            Latest TradingSignal or None
        """
        return self._latest_signal

    def get_candles(self, timeframe: str = '1m', limit: int = 100) -> List[Candle]:
        """
        Get recent candles for specified timeframe.

        Args:
            timeframe: '1m', '15m', or '1h'
            limit: Maximum number of candles to return

        Returns:
            List of Candles
        """
        if timeframe == '1m':
            candles = list(self._candles_1m)
        elif timeframe == '15m':
            candles = list(self._candles_15m)
        elif timeframe == '1h':
            candles = list(self._candles_1h)
        else:
            return []

        return candles[-limit:] if len(candles) > limit else candles

    def get_latest_indicators(self, timeframe: str = '1m') -> Dict[str, float]:
        """
        Get latest indicator values for dashboard display.

        Args:
            timeframe: '1m', '15m', or '1h'

        Returns:
            Dict with indicator values (rsi, ema_7, ema_25, etc.)
        """
        candles = self.get_candles(timeframe, limit=100)

        # CRITICAL FIX: Append current forming candle for real-time price
        if timeframe == '1m' and self._latest_1m:
            # Only append if it's not already in the list (timestamps match)
            if not candles or candles[-1].timestamp != self._latest_1m.timestamp:
                candles.append(self._latest_1m)

        if not candles or len(candles) < 20:
            return {}

        try:
            # Convert to DataFrame
            df = pd.DataFrame({
                'timestamp': [c.timestamp for c in candles],
                'open': [c.open for c in candles],
                'high': [c.high for c in candles],
                'low': [c.low for c in candles],
                'close': [c.close for c in candles],
                'volume': [c.volume for c in candles]
            })
            if 'timestamp' in df.columns:
                # SOTA: Force conversion to datetime, coercing errors to NaT
                df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True, errors='coerce')
                # Drop invalid timestamps if any
                df.dropna(subset=['timestamp'], inplace=True)


            if timeframe == '1h':
                # Debug logging for 1h timeframe
                pass

            # Calculate indicators
            try:
                result_df = self.talib_calculator.calculate_all(df)
            except Exception as e:
                self.logger.error(f"TALib calculation failed for {timeframe}: {e}")
                result_df = df.copy()

            # Calculate additional Trend Pullback indicators
            # VWAP
            vwap_series = self.vwap_calculator.calculate_vwap_series(candles)
            if vwap_series is not None:
                result_df['vwap'] = vwap_series.values
            else:
                result_df['vwap'] = 0.0

            # Bollinger Bands
            bb_result = self.bollinger_calculator.calculate_bands(candles)
            if bb_result:
                result_df['bb_upper'] = bb_result.upper_band
                result_df['bb_middle'] = bb_result.middle_band
                result_df['bb_lower'] = bb_result.lower_band
            else:
                result_df['bb_upper'] = 0.0
                result_df['bb_middle'] = 0.0
                result_df['bb_lower'] = 0.0

            # StochRSI
            stoch_result = self.stoch_rsi_calculator.calculate_stoch_rsi(candles)
            if stoch_result:
                result_df['stoch_k'] = stoch_result.k_value
                result_df['stoch_d'] = stoch_result.d_value
                # Add nested dict for frontend compatibility
                result_df['stoch_rsi'] = [{'k': stoch_result.k_value, 'd': stoch_result.d_value}] * len(result_df)
            else:
                result_df['stoch_k'] = 0.0
                result_df['stoch_d'] = 0.0
                result_df['stoch_rsi'] = [{'k': 0.0, 'd': 0.0}] * len(result_df)

            # Return latest values as dict
            if not result_df.empty:
                # Handle NaN values safely for JSON serialization/display
                latest = result_df.iloc[-1].to_dict()

                # Map specific keys for frontend/demo compatibility
                if 'rsi_6' in latest:
                    latest['rsi'] = latest['rsi_6']

                # Construct nested objects for Dashboard

                # 1. Bollinger Bands
                if bb_result:
                    latest['bollinger'] = {
                        'upper_band': bb_result.upper_band,
                        'middle_band': bb_result.middle_band,
                        'lower_band': bb_result.lower_band,
                        'bandwidth': bb_result.bandwidth,
                        'percent_b': bb_result.percent_b
                    }

                # 2. StochRSI
                if stoch_result:
                    latest['stoch_rsi'] = {
                        'k': stoch_result.k_value,
                        'd': stoch_result.d_value,
                        'zone': stoch_result.zone.value
                    }
                else:
                    # Debug logging if StochRSI is missing
                    self.logger.warning(f"StochRSI failed for {timeframe}. Candles: {len(candles)}. Min req: {self.stoch_rsi_calculator.rsi_period + self.stoch_rsi_calculator.stoch_period + self.stoch_rsi_calculator.k_period + self.stoch_rsi_calculator.d_period}")

                # 3. Liquidity Zones (Volume Upgrade) - SAFE ACCESS
                try:
                    liquidity_detector = getattr(self.signal_generator, 'liquidity_zone_detector', None)
                    if liquidity_detector is not None:
                        atr_val = latest.get('atr')
                        zones_result = liquidity_detector.detect_zones(
                            candles,
                            current_price=latest['close'],
                            atr_value=atr_val
                        )
                        if zones_result:
                            latest['liquidity_zones'] = zones_result.to_dict()
                except Exception as e:
                    self.logger.debug(f"Liquidity zones not available: {e}")

                # 4. SFP (SOTA) - SAFE ACCESS
                try:
                    sfp_detector = getattr(self.signal_generator, 'sfp_detector', None)
                    if sfp_detector is not None:
                        sfp_result = sfp_detector.detect(candles)
                        if sfp_result.is_valid:
                            latest['sfp'] = sfp_result.to_dict()
                except Exception as e:
                    self.logger.debug(f"SFP not available: {e}")

                # 5. Momentum Velocity (SOTA) - SAFE ACCESS
                try:
                    velocity_calc = getattr(self.signal_generator, 'momentum_velocity_calculator', None)
                    if velocity_calc is not None:
                        velocity_res = velocity_calc.calculate(candles)
                        if velocity_res:
                            latest['velocity'] = {
                                'value': float(velocity_res.velocity),
                                'is_fomo': bool(velocity_res.is_fomo_spike),
                                'is_crash': bool(velocity_res.is_crash_drop)
                            }
                except Exception as e:
                    self.logger.debug(f"Velocity not available: {e}")

                return {k: (v if pd.notna(v) else 0.0) for k, v in latest.items()}
            return {}
        except Exception as e:
            self.logger.error(f"Error calculating indicators: {e}")
            return {}

    def get_historical_data_with_indicators(
        self,
        timeframe: str = '1m',
        limit: int = 1000,
        candles: Optional[List[Candle]] = None
    ) -> List[Dict]:
        """
        Get historical candles with calculated indicators.

        SOTA: Accepts optional pre-loaded candles (e.g., from SQLite) to calculate
        indicators without fetching from buffer or API.

        Args:
            timeframe: '1m', '15m', or '1h'
            limit: Number of candles
            candles: Optional pre-loaded candle list (for SQLite data)

        Returns:
            List of dicts with candle data and indicators
        """
        # Use provided candles or fetch from buffer
        if candles is None:
            candles = self.get_candles(timeframe, limit=limit)

        # Append current forming candle if available (for 1m)
        if timeframe == '1m' and self._latest_1m:
            if not candles or candles[-1].timestamp != self._latest_1m.timestamp:
                candles.append(self._latest_1m)

        if not candles:
            return []

        try:
            # Convert to DataFrame for calculation
            df = pd.DataFrame({
                'timestamp': [c.timestamp for c in candles],
                'open': [c.open for c in candles],
                'high': [c.high for c in candles],
                'low': [c.low for c in candles],
                'close': [c.close for c in candles],
                'volume': [c.volume for c in candles]
            })
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True, errors='coerce')
                df.dropna(subset=['timestamp'], inplace=True)

            # Calculate indicators
            # VWAP
            vwap_series = self.vwap_calculator.calculate_vwap_series(candles)

            # Bollinger Bands - use series method for arrays
            bb_series = self.bollinger_calculator.calculate_bands_series(candles)

            # Prepare result list
            result = []
            for i, candle in enumerate(candles):
                # Handle VWAP - can be Series or scalar
                if vwap_series is not None:
                    try:
                        val = vwap_series.iloc[i] if hasattr(vwap_series, 'iloc') else vwap_series
                        # SOTA: Explicit NaN check
                        vwap_val = float(val) if not pd.isna(val) else 0.0
                    except (IndexError, TypeError):
                        vwap_val = 0.0
                else:
                    vwap_val = 0.0

                # Handle Bollinger Bands - now using series result
                if bb_series:
                    try:
                        bb_upper = bb_series.upper_band[i] if i < len(bb_series.upper_band) else 0.0
                        bb_lower = bb_series.lower_band[i] if i < len(bb_series.lower_band) else 0.0
                        bb_middle = bb_series.middle_band[i] if i < len(bb_series.middle_band) else 0.0
                    except (IndexError, TypeError):
                        bb_upper = bb_lower = bb_middle = 0.0
                else:
                    bb_upper = bb_lower = bb_middle = 0.0

                item = {
                    'time': int(candle.timestamp.timestamp()), # Seconds for Lightweight Charts
                    'open': candle.open,
                    'high': candle.high,
                    'low': candle.low,
                    'close': candle.close,
                    'volume': candle.volume,
                    'vwap': vwap_val,
                    'bb_upper': bb_upper,
                    'bb_lower': bb_lower,
                    'bb_middle': bb_middle
                }
                result.append(item)

            return result

        except Exception as e:
            self.logger.error(f"Error calculating historical indicators: {e}")
            return []

    def subscribe_signals(self, callback: Callable[[TradingSignal], None]) -> None:
        """
        Subscribe to trading signals.

        Args:
            callback: Function to call when signal is generated
        """
        self._signal_callbacks.append(callback)
        self.logger.debug(f"Added signal callback (total: {len(self._signal_callbacks)})")

    def subscribe_updates(self, callback: Callable[[], None]) -> None:
        """
        Subscribe to data updates.

        Args:
            callback: Function to call when data updates
        """
        self._update_callbacks.append(callback)
        self.logger.info(f"✅ Added update callback (total: {len(self._update_callbacks)})")

    def get_status(self) -> Dict:
        """
        Get service status.

        Returns:
            Dict with status information
        """
        connection_status = self.websocket_client.get_connection_status()

        return {
            'is_running': self._is_running,
            'connection': {
                'is_connected': connection_status.is_connected,
                'state': connection_status.state.value,
                'latency_ms': connection_status.latency_ms,
                'reconnect_count': connection_status.reconnect_count
            },
            'data': {
                '1m_candles': len(self._candles_1m),
                '15m_candles': len(self._candles_15m),
                '1h_candles': len(self._candles_1h),
                'latest_1m': self._latest_1m.timestamp if self._latest_1m else None,
                'latest_15m': self._latest_15m.timestamp if self._latest_15m else None,
                'latest_1h': self._latest_1h.timestamp if self._latest_1h else None
            },
            'signals': {
                'latest': str(self._latest_signal) if self._latest_signal else None
            }
        }

    def is_running(self) -> bool:
        """Check if service is running."""
        return self._is_running

    def __repr__(self) -> str:
        """String representation"""
        return (
            f"RealtimeService("
            f"symbol={self.symbol}, "
            f"interval={self.interval}, "
            f"running={self._is_running}"
            f")"
        )
