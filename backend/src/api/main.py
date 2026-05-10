from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import asyncio
import logging

from src.api.routers import system, market, settings, trades, signals, backtest, shark_tank, live_trading, config, live_monitoring, analytics
from src.api.routers.market import market_router
from src.api.routers.config import config_router
from src.api.dependencies import get_realtime_service, get_container
from src.api.event_bus import get_event_bus
from src.api.websocket_manager import get_websocket_manager
from src.config import MultiTokenConfig
from src.infrastructure.websocket.shared_binance_client import get_shared_binance_client
from src.infrastructure.services.scheduler_service import get_scheduler

# Configure logging - SOTA: Force console output even with uvicorn
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()  # Ensure console output
    ]
)
logger = logging.getLogger(__name__)

# Multi-token configuration (loaded from env or defaults)
multi_token_config = MultiTokenConfig()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    SOTA Non-Blocking Lifespan (Discord/Binance Pattern - Jan 2026)

    Key Principle: Yield FIRST, init AFTER
    - Server starts immediately (<100ms)
    - Heavy operations run in background task
    - Health check returns multi-level status

    Benefits:
    - No startup timeout
    - Splash shows real progress
    - Graceful degradation if services fail
    """
    # ===========================================
    # PHASE 1: FAST STARTUP (before yield)
    # Only local operations, NO network I/O!
    # ===========================================
    logger.info("[STARTUP] Starting Hinto Trader Pro API...")

    # SOTA (Jan 2026): Reset async client singleton to ensure fresh credentials
    # This is critical when backend restarts but Python process persists (uvicorn reload)
    # Without this, cached aiohttp session may have stale API key headers
    from src.infrastructure.api.async_binance_client import AsyncBinanceFuturesClient
    AsyncBinanceFuturesClient.reset_singleton()

    # SOTA (Jan 2026): Reset ALL dependency caches including DI Container
    # This clears cached BinanceFuturesClient instances that may have stale sessions
    from src.api.dependencies import reset_all_caches
    reset_all_caches()

    # Load config (local file, instant)
    from src.config_loader import get_config
    config = get_config()

    # Initialize startup state (for multi-level health check)
    app.state.startup_status = "initializing"
    app.state.services_ready = False
    app.state.config = config
    app.state.init_error = None
    app.state.realtime_services = []
    app.state.shared_client = None

    # First-run mode: Skip heavy init
    if config.first_run:
        app.state.startup_status = "setup_required"
        logger.warning("[STARTUP] First-run detected - minimal init")
        yield
        return

    # SOTA FIX: Schedule background task for PyInstaller compatibility
    # In frozen mode, asyncio.create_task() before yield may not work properly
    # Use asyncio.get_event_loop().create_task() explicitly
    app.state.startup_status = "connecting"
    logger.info("[STARTUP] Scheduling background init task...")

    try:
        loop = asyncio.get_event_loop()
        init_task = loop.create_task(_background_heavy_init(app))
        app.state.init_task = init_task
        logger.info("[STARTUP] Background task scheduled successfully")
    except Exception as e:
        logger.error(f"[STARTUP] Failed to create background task: {e}")
        app.state.startup_status = "error"
        app.state.init_error = str(e)

    logger.info("[STARTUP] Server starting... (services connecting in background)")

    # ===========================================
    # YIELD - Uvicorn starts HERE (fast!)
    # ===========================================
    try:
        yield
    finally:
        # ===========================================
        # SHUTDOWN SEQUENCE
        # ===========================================
        logger.info("[SHUTDOWN] Starting cleanup sequence...")

        # Cancel background init if still running
        if hasattr(app.state, 'init_task') and not app.state.init_task.done():
            app.state.init_task.cancel()
            try:
                await app.state.init_task
            except asyncio.CancelledError:
                pass

        # Stop TTL Scheduler
        if hasattr(app.state, 'ttl_scheduler') and app.state.ttl_scheduler:
            await app.state.ttl_scheduler.stop()

        # Stop Scheduler
        if hasattr(app.state, 'scheduler') and app.state.scheduler:
            await app.state.scheduler.stop()

        # Stop Realtime Services
        if app.state.realtime_services:
            logger.info(f"Stopping {len(app.state.realtime_services)} Realtime Services...")
            stop_tasks = [s.stop() for s in app.state.realtime_services]
            await asyncio.gather(*stop_tasks, return_exceptions=True)

        # Stop UserDataStream
        if hasattr(app.state, 'user_data_stream') and app.state.user_data_stream:
            await app.state.user_data_stream.stop()

        # Stop LiveTradingService
        if hasattr(app.state, 'live_trading_service') and app.state.live_trading_service:
            await app.state.live_trading_service.stop()

        # Stop Infrastructure
        if hasattr(app.state, 'retention_service') and app.state.retention_service:
            await app.state.retention_service.stop()
        if app.state.shared_client:
            await app.state.shared_client.disconnect()
        if hasattr(app.state, 'event_bus') and app.state.event_bus:
            await app.state.event_bus.stop_worker()

        # SOTA (Jan 2026): Shutdown IndicatorWorker ThreadPool
        try:
            from src.infrastructure.workers.indicator_worker import shutdown_workers
            shutdown_workers()
        except Exception as e:
            logger.warning(f"Worker shutdown warning: {e}")

        # ===========================================
        # SOTA (Jan 2026): PROFESSIONAL SESSION DIAGNOSTICS
        # Print comprehensive report on Ctrl+C for audit/debug
        # ===========================================
        try:
            from src.infrastructure.diagnostics.session_diagnostics import get_session_diagnostics
            import os

            diag = get_session_diagnostics()
            report = diag.generate_report()

            env_mode = os.getenv("ENV", "paper").upper()

            print("\n")
            print("=" * 70)
            print(f"  🔴 SHUTDOWN REPORT - {env_mode} MODE")
            print("=" * 70)

            # Session Info
            print(f"\n📊 SESSION STATISTICS:")
            print(f"   Duration:        {report.get('session_duration', 'N/A')}")
            print(f"   API Calls:       {report.get('total_api_calls', 0)}")
            print(f"   Avg Latency:     {report.get('avg_latency_ms', 0):.0f}ms")
            print(f"   Error Rate:      {report.get('error_rate', 0):.1%}")

            # Trading Summary
            if hasattr(app.state, 'live_trading_service') and app.state.live_trading_service:
                lts = app.state.live_trading_service
                print(f"\n💰 TRADING SUMMARY:")
                print(f"   Mode:            {lts.mode.value.upper()}")
                print(f"   Initial Balance: ${lts.initial_balance:.2f}")
                print(f"   Final Balance:   ${lts._cached_balance:.2f}")
                print(f"   Open Positions:  {len(lts.active_positions)}")
                if lts.signal_tracker:
                    print(f"   Pending Signals: {len(lts.signal_tracker)}")

            # Configuration
            print(f"\n⚙️  CONFIGURATION:")
            print(f"   ENV:             {env_mode}")
            print(f"   Symbols:         {len(multi_token_config.symbols)}")
            print(f"   Port:            8000")

            # Warnings
            if report.get('warnings'):
                print(f"\n⚠️  WARNINGS:")
                for warn in report.get('warnings', [])[:5]:
                    print(f"   - {warn}")

            print("\n" + "=" * 70)
            print("  ✅ Shutdown complete. All resources released.")
            print("=" * 70 + "\n")

        except Exception as e:
            logger.warning(f"Diagnostics report error: {e}")

        logger.info("[SHUTDOWN] Complete - all resources released")


async def _background_heavy_init(app: FastAPI):
    """
    SOTA: Heavy initialization in background (doesn't block server startup)

    This runs AFTER Uvicorn starts, so health check is always available.
    Updates app.state.startup_status as progress is made.

    Instrumented with StartupMonitor for Realtime FE Feedback.
    """
    import os
    from src.infrastructure.monitoring.startup_monitor import get_startup_monitor

    monitor = get_startup_monitor()

    # SOTA GUARD: Prevent double initialization (causes duplicate signals)
    if getattr(app.state, '_init_started', False):
        logger.warning("[BACKGROUND] Init already started, skipping to prevent duplicates")
        return
    app.state._init_started = True

    try:
        print("[BACKGROUND] Starting heavy initialization...")
        logger.info("[BACKGROUND] Starting heavy initialization...")
        await monitor.emit_progress(0, 100, "Starting system initialization...")

        # Step 1: Get singletons
        await monitor.emit_progress(5, 100, "Loading core services...")
        event_bus = get_event_bus()
        ws_manager = get_websocket_manager()
        container = get_container()
        retention_service = container.get_data_retention_service()
        shared_client = get_shared_binance_client()

        # Store references for shutdown
        app.state.event_bus = event_bus
        app.state.retention_service = retention_service
        app.state.shared_client = shared_client

        # Step 2: Start EventBus broadcast worker
        await monitor.emit_progress(10, 100, "Starting internal event bus...")
        await event_bus.start_worker(ws_manager)
        logger.info("[BACKGROUND] EventBus started")

        # Step 2.5: SOTA Sync
        await monitor.emit_progress(15, 100, "Syncing configuration...")
        try:
            paper_service = container.get_paper_trading_service()
            settings = paper_service.repo.get_all_settings()
            persisted_watchlist = str(settings.get('enabled_tokens', '') or '').strip()
            env_symbols = str(os.getenv('SYMBOLS', '') or '').strip()

            if not persisted_watchlist and env_symbols:
                seed_symbols = ",".join(multi_token_config.symbols)
                paper_service.repo.set_setting('enabled_tokens', seed_symbols)
                logger.info(
                    f"💾 Startup Sync: Seeded DB 'enabled_tokens' from .env ({len(multi_token_config.symbols)} symbols)"
                )
                await monitor.emit_log(f"Seeded watchlist from .env ({len(multi_token_config.symbols)} symbols)")
            else:
                logger.info("💾 Startup Sync: Keeping persisted DB watchlist as source of truth")
                await monitor.emit_log("Watchlist source: persisted DB")
        except Exception as e:
            logger.error(f"❌ Failed to sync .env symbols to DB: {e}")
            await monitor.emit_progress(15, 100, "Sync warning: DB update failed", level="warning")

        # Step 3: Create and start RealtimeServices per symbol
        services = []
        start_tasks = []

        total_symbols = len(multi_token_config.symbols)
        await monitor.emit_progress(20, 100, f"Initializing {total_symbols} market data streams...")

        for idx, symbol in enumerate(multi_token_config.symbols):
            service = container.get_realtime_service(symbol.lower())
            service.set_event_bus(event_bus)
            shared_client.register_handler(symbol.lower(), service.on_candle_update)
            services.append(service)
            start_tasks.append(service.start(shared_client_mode=True))
            logger.info(f"[BACKGROUND] Registered handler for {symbol}")

        if start_tasks:
            logger.info(f"[BACKGROUND] Starting {len(start_tasks)} services in PARALLEL...")
            await monitor.emit_log(f"Parallel loading: {len(start_tasks)} services")

            # SOTA (Jan 2026): True Parallel Loading
            # Test showed 50 symbols load in 0.7s with asyncio.gather (vs 20s with batched)
            # Binance rate limit is 2400 req/min = 40 req/sec, we're well under
            await monitor.emit_progress(25, 100, f"Loading {len(start_tasks)} market data streams (parallel)...")

            t0 = asyncio.get_event_loop().time()

            # Run ALL service.start() in parallel
            results = await asyncio.gather(*start_tasks, return_exceptions=True)

            load_time = asyncio.get_event_loop().time() - t0

            # Count successes and failures
            success_count = sum(1 for r in results if r is not True and not isinstance(r, Exception))
            failed = [i for i, r in enumerate(results) if isinstance(r, Exception)]

            if failed:
                logger.warning(f"⚠️ {len(failed)} services failed to start")
                for idx in failed[:5]:  # Log first 5 failures
                    logger.warning(f"   - {multi_token_config.symbols[idx]}: {results[idx]}")

            logger.info(f"✅ [BACKGROUND] All RealtimeServices started in {load_time:.1f}s")
            await monitor.emit_progress(70, 100, f"All {len(start_tasks) - len(failed)} streams active ({load_time:.1f}s)")

            # SOTA (Jan 2026): Set data_ready flag - Frontend should wait for this before chart render
            # This ensures all symbol buffers are populated before users can interact with charts
            app.state.data_ready = True
            app.state.ready_symbols = [s.lower() for s in multi_token_config.symbols]
            print(f"✅ [BACKGROUND] Data ready flag set - {len(app.state.ready_symbols)} symbols available")
            logger.info(f"✅ [BACKGROUND] Data ready flag set - {len(app.state.ready_symbols)} symbols available")

        app.state.realtime_services = services

        # Step 4: Setup SharkTankCoordinator callbacks
        await monitor.emit_progress(75, 100, "Configuring Shark Tank Logic...")
        shark_tank = container.get_shark_tank_coordinator()
        paper_service = container.get_paper_trading_service()
        live_trading_service = container.get_live_trading_service()

        # SOTA (Jan 2026): Lazy initialization - call initialize_async() after event loop running
        if hasattr(live_trading_service, 'initialize_async'):
            await live_trading_service.initialize_async()

        app.state.live_trading_service = live_trading_service

        _env = os.getenv("ENV", "paper").lower().strip()

        def execute_signal_callback(signal):
            logger.info(f"🔧 execute_signal_callback: {signal.symbol} in {_env} mode")
            if _env in ["testnet", "live"]:
                if live_trading_service:
                    # DEBUG: Check signal_tracker status AND instance id
                    tracker_ok = hasattr(live_trading_service, 'signal_tracker') and live_trading_service.signal_tracker is not None
                    logger.info(f"🔧 signal_tracker OK: {tracker_ok}, service_id={id(live_trading_service)}")
                    # SOTA FIX: Let execute_signal() handle auto_execute check dynamically from settings
                    live_trading_service.execute_signal(signal)
                else:
                    logger.warning(f"⚠️ live_trading_service not available")
            else:
                if paper_service:
                    paper_service.on_signal_received(signal, signal.symbol)

        def get_open_positions_callback():
            """Get total used slots (positions + pending signals)."""
            if _env in ["testnet", "live"] and live_trading_service:
                # SOTA FIX (Jan 2026): Use signal_tracker for pending count, NOT deprecated pending_orders
                pending_count = len(live_trading_service.signal_tracker) if live_trading_service.signal_tracker else 0
                return len(live_trading_service.active_positions) + pending_count
            elif paper_service:
                return len(paper_service.get_positions()) + len(paper_service.repo.get_pending_orders())
            return 0

        def get_available_margin_callback():
            if _env in ["testnet", "live"] and live_trading_service:
                return live_trading_service.get_available_margin()
            elif paper_service:
                return paper_service.get_wallet_balance()
            return 0.0

        def get_pending_orders_callback():
            """Get list of pending orders with confidence for recycling."""
            if _env in ["testnet", "live"] and live_trading_service:
                # SOTA FIX (Jan 2026): Use signal_tracker, NOT deprecated pending_orders
                if not live_trading_service.signal_tracker:
                    return []
                return [
                    {
                        'symbol': symbol,
                        'confidence': signal.confidence,
                        'target_price': signal.target_price,
                        'entry_price': signal.target_price
                    }
                    for symbol, signal in live_trading_service.signal_tracker.get_all_pending().items()
                ]
            elif paper_service:
                return [
                    {
                        'symbol': order.get('symbol', ''),
                        'confidence': order.get('confidence', 0.5),
                        'target_price': order.get('entry_price', order.get('target_price', 0)),
                        'entry_price': order.get('entry_price', 0)
                    }
                    for order in paper_service.repo.get_pending_orders()
                ]
            return []

        def get_current_prices_callback():
            """Get current prices for PROXIMITY SENTRY check."""
            # SOTA FIX (Jan 2026): Use cached prices from live_trading_service
            if _env in ["testnet", "live"] and live_trading_service:
                return live_trading_service._cached_prices
            return {}

        def cancel_order_callback(symbol: str):
            """Cancel a pending signal for Smart Recycling."""
            logger.info(f"♻️ SMART RECYCLE: Cancelling pending signal for {symbol}")
            if _env in ["testnet", "live"] and live_trading_service:
                # SOTA FIX (Jan 2026): Use signal_tracker, NOT deprecated pending_orders
                try:
                    if live_trading_service.signal_tracker:
                        live_trading_service.signal_tracker.cancel_signal(symbol)
                        return True
                    return False
                except Exception as e:
                    logger.error(f"Failed to cancel {symbol}: {e}")
                    return False
            elif paper_service:
                # PaperTradingService: Just remove from local tracking
                try:
                    paper_service.repo.cancel_pending_order(symbol)
                    return True
                except Exception as e:
                    logger.error(f"Failed to cancel {symbol}: {e}")
                    return False
            return False

        # SOTA FIX (Jan 2026): New callback to get symbols with open positions
        # CRITICAL: This matches backtest filter logic exactly
        # Backtest: candidates = [s for s in signals if s.symbol not in self.positions ...]
        def get_position_symbols_callback():
            """Get set of symbols that have open positions."""
            symbols = set()
            if _env in ["testnet", "live"] and live_trading_service:
                # Get symbols from active_positions dict
                for symbol in live_trading_service.active_positions.keys():
                    symbols.add(symbol.upper())
            elif paper_service:
                # Get symbols from paper positions
                for pos in paper_service.get_positions():
                    if hasattr(pos, 'symbol'):
                        symbols.add(pos.symbol.upper())
                    elif isinstance(pos, dict):
                        symbols.add(pos.get('symbol', '').upper())
            return symbols

        shark_tank.set_callbacks(
            execute_signal_callback,
            get_open_positions_callback,
            get_available_margin_callback,
            get_pending_orders_callback,
            get_current_prices_callback,
            cancel_order_callback,
            get_position_symbols_callback  # SOTA FIX: New callback for position filter
        )
        logger.info(f"[BACKGROUND] SharkTank callbacks configured for {_env} mode (SMART RECYCLING enabled)")

        # Step 5: Live/Testnet specific setup
        if _env in ["testnet", "live"]:
            await monitor.emit_progress(80, 100, f"Connecting to Binance {_env.upper()}...")
            # State Reconciliation
            try:
                recon_result = await live_trading_service.reconcile_state()
                if recon_result.get('orphan_positions'):
                    logger.warning(f"[BACKGROUND] Adopted {len(recon_result['orphan_positions'])} orphan positions")
                    await monitor.emit_log(f"Reconciled {len(recon_result['orphan_positions'])} orphaned positions")
            except Exception as e:
                logger.error(f"[BACKGROUND] Reconciliation failed: {e}")
                await monitor.emit_progress(80, 100, "Reconciliation failed", level="error")

            # Start User Data Stream
            user_data_stream = container.get_user_data_stream()
            if user_data_stream:
                await user_data_stream.start()
                app.state.user_data_stream = user_data_stream
                logger.info("[BACKGROUND] User Data Stream started")

            await live_trading_service.start_user_data_stream()
            await live_trading_service.start_background_sync()

            # Keep-alive task
            async def listen_key_keepalive():
                while True:
                    await asyncio.sleep(30 * 60)
                    if live_trading_service.client:
                        live_trading_service.client.keep_alive_listen_key()
            asyncio.create_task(listen_key_keepalive())

            # Periodic reconciliation
            async def periodic_reconciliation():
                while True:
                    await asyncio.sleep(5 * 60)
                    try:
                        await live_trading_service.reconcile_state()
                    except Exception as e:
                        logger.error(f"Periodic reconciliation error: {e}")
            asyncio.create_task(periodic_reconciliation())

            logger.info("[BACKGROUND] Live trading services started")

        # Step 6: Connect shared WebSocket
        await monitor.emit_progress(85, 100, "Establishing Realtime WebSocket Feed...")
        try:
            # DEBUG (Jan 2026): Log symbols before connect to verify registration
            logger.info(f"🔍 DEBUG: SharedClient._symbols = {len(shared_client._symbols)} symbols")
            logger.info(f"🔍 DEBUG: First 5 symbols: {shared_client._symbols[:5]}")
            logger.info(f"🔍 DEBUG: SharedClient._handlers keys = {list(shared_client._handlers.keys())[:5]}...")

            await shared_client.connect()
            logger.info(f"[BACKGROUND] Combined Streams connected ({len(multi_token_config.symbols)} symbols)")
            await monitor.emit_log(f"WS Connected for {len(multi_token_config.symbols)} symbols")

            # FIX P0 (Feb 13, 2026): Ensure restored positions have active subscriptions
            # Positions restored during initialize_async() add symbols to _symbols list
            # but the actual WebSocket subscription only happens in connect().
            # This call verifies/forces subscription for all monitored positions.
            if live_trading_service and live_trading_service.position_monitor:
                await live_trading_service.position_monitor.ensure_all_subscriptions()
        except Exception as e:
            logger.error(f"[BACKGROUND] SharedClient connect failed: {e}")
            await monitor.emit_progress(85, 100, "WebSocket Connection Failed", level="error")

        # Step 7: Start DataRetentionService
        await monitor.emit_progress(90, 100, "Starting Data Retention Service...")
        await retention_service.start()
        logger.info("[BACKGROUND] DataRetentionService started")

        # Step 8: Start Scheduler
        await monitor.emit_progress(92, 100, "Starting Background Schedulers...")
        scheduler = get_scheduler()
        await scheduler.start()
        app.state.scheduler = scheduler

        # Step 9: Start TTL Scheduler
        from src.application.services.ttl_scheduler import init_ttl_scheduler

        def paper_cleanup_callback():
            """Cleanup expired Paper mode pending orders."""
            if not paper_service:
                return 0
            from datetime import datetime
            TTL_SECONDS = 50 * 60  # SOTA SYNC: 50 min matches backtest default
            cleaned = 0
            for order in paper_service.repo.get_pending_orders():
                if order.open_time:
                    age = (datetime.now() - order.open_time).total_seconds()
                    if age > TTL_SECONDS:
                        order.status = 'CANCELLED'
                        order.exit_reason = 'TTL_EXPIRED'
                        order.close_time = datetime.now()
                        paper_service.repo.update_order(order)
                        paper_service._locked_in_orders = max(0, paper_service._locked_in_orders - order.margin)
                        cleaned += 1
            return cleaned

        def live_cleanup_callback():
            """Cleanup expired Testnet/Live signals."""
            if live_trading_service and live_trading_service.signal_tracker:
                return live_trading_service.signal_tracker.cleanup_expired()
            return 0

        ttl_scheduler = init_ttl_scheduler(
            paper_cleanup_callback=paper_cleanup_callback if _env == "paper" else None,
            live_cleanup_callback=live_cleanup_callback if _env in ["testnet", "live"] else None
        )
        await ttl_scheduler.start()
        app.state.ttl_scheduler = ttl_scheduler
        logger.info(f"[BACKGROUND] TTLScheduler started for {_env} mode")

        # Step 10: Start SharkTank periodic flush
        await monitor.emit_progress(95, 100, "Starting Signal Processor...")
        async def shark_tank_flush_loop():
            """Periodically flush SharkTank to execute queued signals."""
            while True:
                await asyncio.sleep(3.0)  # 3 second flush interval
                try:
                    pending = shark_tank.get_pending_count()
                    if pending > 0:
                        logger.info(f"🦈 SharkTank flush: Processing {pending} queued signals")
                        shark_tank.force_process()
                except Exception as e:
                    logger.error(f"SharkTank flush error: {e}")

        asyncio.create_task(shark_tank_flush_loop())
        logger.info("[BACKGROUND] SharkTank flush loop started (3s interval)")

        # Step 10.5: DZ Force-Close periodic check (v6.5.12)
        async def dz_force_close_loop():
            """Periodically check if we're in a dead zone and force-close positions."""
            while True:
                await asyncio.sleep(60.0)
                try:
                    if live_trading_service and hasattr(live_trading_service, 'circuit_breaker'):
                        await asyncio.to_thread(live_trading_service.force_close_dead_zone_positions)
                except Exception as e:
                    logger.error(f"DZ force-close error: {e}")

        if _env in ["testnet", "live"]:
            asyncio.create_task(dz_force_close_loop())
            logger.info("[BACKGROUND] DZ force-close loop started (60s interval)")

        # Complete
        await monitor.emit_progress(100, 100, "System Ready", level="success")
        app.state.services_ready = True
        app.state.startup_status = "ready"
        logger.info("[BACKGROUND] ✅ All services ready!")

    except Exception as e:
        print(f"❌ [BACKGROUND] Initialization failed: {e}")
        logger.error(f"[BACKGROUND] Initialization failed: {e}")
        app.state.startup_status = "error"
        app.state.init_error = str(e)
        import traceback
        traceback.print_exc()
        if 'monitor' in locals():
            await monitor.emit_progress(0, 100, f"Critical Error: {str(e)}", level="error")

app = FastAPI(
    title="Hinto Trader Pro API",
    description="Backend API for Hinto Trader Pro Desktop App",
    version="0.1.0",
    lifespan=lifespan
)

# Configure CORS
# SOTA: Explicit origins required when allow_credentials=True
# Per CORS spec, wildcard (*) is incompatible with credentials
# Tauri v2 uses https://tauri.localhost, splash uses http://tauri.localhost
origins = [
    "http://localhost:1420",        # Tauri dev
    "http://127.0.0.1:1420",
    "http://localhost:5173",        # Vite dev server
    "http://127.0.0.1:5173",
    "tauri://localhost",            # Tauri v1 protocol
    "https://tauri.localhost",      # Tauri v2 production
    "http://tauri.localhost",       # Tauri v2 splash (no SSL in splash)
    "null",                         # File:// origin (local HTML)
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# SOTA: Session Diagnostics Middleware - auto-instruments all API calls
# Records latency, errors, and generates report on shutdown (Ctrl+C)
from src.api.middleware.diagnostics_middleware import DiagnosticsMiddleware
from src.infrastructure.diagnostics.session_diagnostics import get_session_diagnostics

# Initialize diagnostics singleton at startup
_diagnostics = get_session_diagnostics()
app.add_middleware(DiagnosticsMiddleware)

# SOTA DEBUG: Deep Profiler (Enable with DEBUG_PROFILE=1)
from src.api.middleware.request_profiler import RequestProfilerMiddleware
import os
import asyncio
import time
is_profiler_enabled = os.getenv("DEBUG_PROFILE", "0") == "1"
app.add_middleware(RequestProfilerMiddleware, enabled=is_profiler_enabled)

if is_profiler_enabled:
    # SOTA DEBUG: Event Loop Lag Monitor
    async def monitor_event_loop_lag():
        logger.info("🕵️ Event Loop Monitor STARTED")
        while True:
            start = time.perf_counter()
            await asyncio.sleep(0.1)  # Should take 100ms
            duration = (time.perf_counter() - start) * 1000
            lag = duration - 100
            if lag > 50:  # >50ms lag is noticeable
                logger.warning(f"🐢 EVENT LOOP LAG: +{lag:.2f}ms")

    # We can start this in lifespan, but defining it here is fine.
    # To run it, we hook into lifespan.
    pass

# We need to inject the monitor task into lifespan.
# Since lifespan is a generator, we can't easily patch it from outside without editing it.
# I will edit lifespan function directly.

# SOTA FIX: Custom exception handler to ensure CORS headers on error responses
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Custom HTTP exception handler that maintains CORS headers."""
    origin = request.headers.get("origin", "")
    headers = {}
    if origin in origins:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"

    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc.detail)},
        headers=headers
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Catch-all exception handler that maintains CORS headers."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    origin = request.headers.get("origin", "")
    headers = {}
    if origin in origins:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"

    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
        headers=headers
    )

# Include Routers
app.include_router(system.router)
app.include_router(market.router)
app.include_router(market_router)  # /market/* endpoints
app.include_router(settings.router)
app.include_router(trades.router)
app.include_router(signals.router)  # Signal lifecycle tracking
app.include_router(backtest.router) # Backtest endpoint
app.include_router(shark_tank.router) # Shark Tank Dashboard
app.include_router(live_trading.router) # Live Trading API
app.include_router(config_router)  # Config Management API
app.include_router(live_monitoring.router)  # Live Monitoring Dashboard API
app.include_router(analytics.router)  # v6.3.0: Institutional Analytics API

# Mount static files for monitoring dashboard
from pathlib import Path
static_dir = Path(__file__).parent.parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    logger.info(f"✅ Static files mounted at /static from {static_dir}")

@app.get("/")
async def root():
    """Simple root for backward compatibility."""
    return {"message": "Hinto API is running", "status": "ok"}


@app.get("/health")
async def health_check(request: Request):
    """
    SOTA Multi-Level Health Check (Jan 2026)

    Levels:
    - server_ready: True if server is responding (always true if this returns)
    - services_ready: True if background init complete (Binance connected, data loaded)
    - startup_status: "initializing" | "connecting" | "ready" | "setup_required" | "error"

    Error codes:
    - MISSING_ENV: No .env file found
    - MISSING_API_KEY: API keys not configured
    - INVALID_API_KEY: Binance rejected credentials
    - NETWORK_ERROR: Cannot reach Binance API
    - BINANCE_ERROR: Exchange returned error
    """
    import os
    from pathlib import Path

    # Get app state for multi-level status
    app = request.app

    # SOTA: Use centralized config_loader for deterministic config detection
    from src.config_loader import get_config
    config = get_config()

    env_file = config.config_path
    env_example_src = Path(__file__).parent.parent / ".env.example"

    # SOTA: Multi-level health response
    response = {
        "status": "healthy",
        "version": "3.2.0",
        # Multi-level readiness (key for splash screen)
        "server_ready": True,  # Always true if this endpoint responds
        "services_ready": getattr(app.state, 'services_ready', False),
        "startup_status": getattr(app.state, 'startup_status', 'unknown'),
        "init_error": getattr(app.state, 'init_error', None),
        # Legacy fields
        "config_valid": True,
        "env_mode": config.env_mode,
        "binance_connected": False,
        "error_code": None,
        "message": None,
        "action": None,
        "config_path": str(env_file),
    }

    # Check 1: .env file exists (SOTA: use config_loader's first_run detection)
    if config.first_run:
        # Try to create config directory for user convenience
        config_dir = env_file.parent
        try:
            config_dir.mkdir(parents=True, exist_ok=True)

            # Copy .env.example if it exists
            if env_example_src.exists():
                import shutil
                shutil.copy(env_example_src, config_dir / ".env.example")
                logger.info(f"[Config] Created config directory: {config_dir}")
        except Exception as e:
            logger.warning(f"Could not create config directory: {e}")

        response["status"] = "error"
        response["config_valid"] = False
        response["error_code"] = "MISSING_ENV"
        response["message"] = "Configuration required for first-time setup"
        response["action"] = f"Create .env file at:\\n{env_file}\\n\\nYou can copy from .env.example in the same folder."
        response["config_path"] = str(config_dir)
        return response

    # Check 2: Required API keys present based on ENV mode
    env_mode = os.getenv("ENV", "paper").lower()

    if env_mode == "live":
        if not os.getenv("BINANCE_API_KEY") or not os.getenv("BINANCE_API_SECRET"):
            response["status"] = "error"
            response["config_valid"] = False
            response["error_code"] = "MISSING_API_KEY"
            response["message"] = "Live mode requires BINANCE_API_KEY and BINANCE_API_SECRET"
            response["action"] = "Add production API keys to your .env file"
            return response
    elif env_mode == "testnet":
        if not os.getenv("BINANCE_TESTNET_API_KEY") or not os.getenv("BINANCE_TESTNET_API_SECRET"):
            response["status"] = "error"
            response["config_valid"] = False
            response["error_code"] = "MISSING_API_KEY"
            response["message"] = "Testnet mode requires BINANCE_TESTNET_API_KEY and BINANCE_TESTNET_API_SECRET"
            response["action"] = "Add testnet API keys to your .env file"
            return response
    # Paper mode doesn't require API keys

    # Check 3: Test Binance connection (only for live/testnet)
    if env_mode in ["live", "testnet"]:
        try:
            from src.api.dependencies import get_container
            container = get_container()
            live_service = container.get_live_trading_service()

            if live_service and live_service.client:
                # Try to verify Binance connection (use balance check)
                try:
                    # SOTA: Use our custom BinanceFuturesClient.get_account_balance()
                    balance = live_service.client.get_account_balance()
                    if balance:
                        response["binance_connected"] = True
                except Exception as e:
                    error_str = str(e)

                    # Parse Binance error codes
                    if "-2015" in error_str or "Invalid API" in error_str:
                        response["status"] = "error"
                        response["error_code"] = "INVALID_API_KEY"
                        response["message"] = "Binance rejected API credentials"
                        response["binance_error"] = error_str[:200]
                        response["action"] = "Check: 1) API key permissions 2) IP whitelist 3) Key not expired"
                        return response
                    elif "-1021" in error_str or "Timestamp" in error_str:
                        response["status"] = "error"
                        response["error_code"] = "TIME_SYNC_ERROR"
                        response["message"] = "System clock out of sync with Binance"
                        response["action"] = "Synchronize your computer's clock with internet time"
                        return response
                    elif "ConnectError" in error_str or "Connection" in error_str:
                        response["status"] = "error"
                        response["error_code"] = "NETWORK_ERROR"
                        response["message"] = "Cannot reach Binance API"
                        response["action"] = "Check your internet connection"
                        return response
                    else:
                        response["status"] = "warning"
                        response["error_code"] = "BINANCE_ERROR"
                        response["message"] = f"Binance connection issue: {error_str[:100]}"
                        response["action"] = "Exchange may be under maintenance. Try again in a few minutes."
            else:
                # No client initialized yet (paper mode or startup in progress)
                response["binance_connected"] = False
                response["message"] = "Binance client not initialized (paper mode or loading)"

        except Exception as e:
            logger.warning(f"Health check Binance test failed: {e}")
            response["binance_connected"] = False
    else:
        # Paper mode - no Binance connection needed
        response["binance_connected"] = None  # N/A for paper mode
        response["message"] = "Paper trading mode - no exchange connection required"

    return response
