"""
Live Trading Runner - Backtest-Mode Live Trading System

Entry point for live trading using EXACTLY the same logic as backtest engine.

Core Principle: "If it works in backtest, it should work in live"

Usage:
    python run_live_trading.py --top 50 --balance 34 --leverage 10 --max-pos 5 --zombie-killer --full-tp --ttl 50
    python run_live_trading.py --dry-run --top 5  # Test mode
"""

import asyncio
import argparse
import logging
import signal
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from src.application.backtest_live.core.realtime_data_manager import RealTimeDataManager
from src.application.backtest_live.core.execution_adapter import ExecutionAdapter
from src.application.backtest_live.core.position_monitor import PositionMonitor
from src.application.backtest_live.core.shark_tank_coordinator import SharkTankCoordinator
from src.application.backtest_live.core.order_manager import OrderManager
from src.application.backtest_live.core.frequency_limiter import FrequencyLimiter
from src.application.backtest_live.core.performance_monitor import PerformanceMonitor
from src.application.signals.signal_generator import SignalGenerator
from src.infrastructure.websocket.shared_binance_client import SharedBinanceClient
from src.infrastructure.persistence.live_trade_repository import LiveTradeRepository
from src.config_loader import load_config


class LiveTradingRunner:
    """
    Live Trading Runner.

    Orchestrates real-time data ingestion, signal generation, and order execution.
    """

    def __init__(self, config: dict):
        """
        Initialize Live Trading Runner.

        Args:
            config: Configuration dict with trading parameters
        """
        self.config = config
        self.logger = logging.getLogger(__name__)

        # Components (will be initialized in start())
        self.data_manager: Optional[RealTimeDataManager] = None
        self.signal_generator: Optional[SignalGenerator] = None
        self.shark_tank: Optional[SharkTankCoordinator] = None
        self.execution_adapter: Optional[ExecutionAdapter] = None
        self.order_manager: Optional[OrderManager] = None
        self.position_monitor: Optional[PositionMonitor] = None
        self.frequency_limiter: Optional[FrequencyLimiter] = None
        self.performance_monitor: Optional[PerformanceMonitor] = None
        self.binance_client: Optional[SharedBinanceClient] = None
        self.trade_repository: Optional[LiveTradeRepository] = None

        # State
        self._is_running = False
        self._shutdown_requested = False

        # Monitoring state
        self._last_status_report = None
        self._last_hourly_report = None
        self._last_buffer_save = None
        self._status_report_interval = 900  # 15 minutes in seconds
        self._hourly_report_interval = 3600  # 1 hour in seconds
        self._buffer_save_interval = 60  # 1 minute in seconds

    async def start(self):
        """
        Start live trading system.

        Flow:
        1. Initialize components
        2. Start real-time data ingestion
        3. Process signals and execute orders
        4. Monitor positions and TP/SL
        """
        self.logger.info("=" * 80)
        self.logger.info("🚀 BACKTEST-MODE LIVE TRADING SYSTEM")
        self.logger.info("=" * 80)

        # Dry-run mode warning (prominent)
        if self.config.get('dry_run'):
            self.logger.warning("=" * 80)
            self.logger.warning("🧪 DRY RUN MODE ACTIVE")
            self.logger.warning("=" * 80)
            self.logger.warning("⚠️  Orders will be SIMULATED, not executed on exchange")
            self.logger.warning("⚠️  Real-time data will be fetched from Binance")
            self.logger.warning("⚠️  All trading logic will run normally")
            self.logger.warning("⚠️  Use this mode to test before live trading")
            self.logger.warning("=" * 80)

        # Log configuration
        self._log_config()

        # Initialize components
        await self._initialize_components()

        # Start data manager
        await self.data_manager.start()

        self._is_running = True
        self.logger.info("✅ Live trading system started successfully")

        # Initialize monitoring timestamps
        self._last_status_report = datetime.now(timezone.utc)
        self._last_hourly_report = datetime.now(timezone.utc)
        self._last_buffer_save = datetime.now(timezone.utc)

        # Keep running until shutdown
        try:
            while self._is_running and not self._shutdown_requested:
                await asyncio.sleep(1)

                # Check if should print status report (every 15 minutes)
                await self._check_status_report()

                # Check if should print hourly summary (every 1 hour)
                await self._check_hourly_report()

                # Check if should save candle buffers (every 1 minute)
                await self._check_buffer_save()

        except KeyboardInterrupt:
            self.logger.info("⚠️ Keyboard interrupt received (Ctrl+C)")
        finally:
            # Check if emergency stop was requested via --emergency-stop flag
            emergency_close = self.config.get('emergency_stop', False)
            await self.stop(emergency_close_positions=emergency_close)

    async def stop(self, emergency_close_positions: bool = False):
        """
        Stop live trading system gracefully.

        Flow:
        1. Stop data ingestion
        2. Close all positions (if emergency stop)
        3. Cancel all pending orders
        4. Save state to disk
        5. Flush logs and database
        6. Close WebSocket connections
        7. Print summary report

        Args:
            emergency_close_positions: If True, close all open positions before shutdown
        """
        if not self._is_running:
            return

        self.logger.info("=" * 80)
        self.logger.info("🛑 GRACEFUL SHUTDOWN INITIATED")
        self.logger.info("=" * 80)

        self._is_running = False

        try:
            # Step 1: Stop data ingestion (prevent new signals)
            self.logger.info("1️⃣ Stopping data ingestion...")
            if self.data_manager:
                try:
                    await self.data_manager.stop()
                    self.logger.info("  ✓ Data manager stopped")
                except Exception as e:
                    self.logger.error(f"  ❌ Error stopping data manager: {e}")

            # Step 2: Close all positions (if emergency stop)
            if emergency_close_positions:
                self.logger.warning("2️⃣ Emergency closing all positions...")
                try:
                    await self._emergency_close_all_positions()
                    self.logger.info("  ✓ All positions closed")
                except Exception as e:
                    self.logger.error(f"  ❌ Error closing positions: {e}")
            else:
                self.logger.info("2️⃣ Skipping position closure (normal shutdown)")
                if self.execution_adapter and hasattr(self.execution_adapter, 'positions'):
                    positions = self.execution_adapter.positions
                    if positions and len(positions) > 0:
                        self.logger.warning(f"  ⚠️ {len(positions)} positions remain open")

            # Step 3: Cancel all pending orders
            self.logger.info("3️⃣ Cancelling all pending orders...")
            if self.order_manager and self.order_manager.pending_orders:
                try:
                    await self._cancel_all_pending_orders()
                    self.logger.info("  ✓ All pending orders cancelled")
                except Exception as e:
                    self.logger.error(f"  ❌ Error cancelling orders: {e}")
            else:
                self.logger.info("  ✓ No pending orders to cancel")

            # Step 4: Save state to disk
            self.logger.info("4️⃣ Saving state to disk...")
            try:
                await self._save_state()
                self.logger.info("  ✓ State saved successfully")
            except Exception as e:
                self.logger.error(f"  ❌ Error saving state: {e}")

            # Step 5: Stop position monitoring
            self.logger.info("5️⃣ Stopping position monitor...")
            if self.position_monitor:
                try:
                    await self.position_monitor.stop()
                    self.logger.info("  ✓ Position monitor stopped")
                except Exception as e:
                    self.logger.error(f"  ❌ Error stopping position monitor: {e}")

            # Step 6: Flush database
            self.logger.info("6️⃣ Flushing database...")
            if self.trade_repository:
                try:
                    # Export trades to CSV
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    csv_path = f'backend/live_trades_{timestamp}.csv'
                    self.trade_repository.export_to_csv(csv_path)
                    self.logger.info(f"  ✓ Trades exported to: {csv_path}")

                    # Close database connection
                    self.trade_repository.close()
                    self.logger.info("  ✓ Database connection closed")
                except Exception as e:
                    self.logger.error(f"  ❌ Error flushing database: {e}")

            # Step 7: Close WebSocket connections
            self.logger.info("7️⃣ Closing WebSocket connections...")
            if self.binance_client:
                try:
                    await self.binance_client.disconnect()
                    self.logger.info("  ✓ WebSocket connections closed")
                except Exception as e:
                    self.logger.error(f"  ❌ Error closing WebSocket: {e}")

            # Step 8: Print summary report
            self.logger.info("8️⃣ Generating summary report...")
            try:
                self._print_summary()
            except Exception as e:
                self.logger.error(f"  ❌ Error generating summary: {e}")

            # Step 9: Flush logs
            self.logger.info("9️⃣ Flushing logs...")
            try:
                logging.shutdown()
            except Exception as e:
                # Can't log this since logging is shutting down
                pass

            self.logger.info("=" * 80)
            self.logger.info("✅ GRACEFUL SHUTDOWN COMPLETED SUCCESSFULLY")
            self.logger.info("=" * 80)

        except Exception as e:
            self.logger.error(f"❌ Error during graceful shutdown: {e}", exc_info=True)
            raise

    async def _initialize_components(self):
        """Initialize all components"""
        self.logger.info("🔧 Initializing components...")

        # Initialize Trade Repository (first, for state recovery)
        self.trade_repository = LiveTradeRepository()
        self.logger.info("  ✓ Trade Repository initialized")

        # Initialize Binance client FIRST (needed for balance fetching)
        self.binance_client = SharedBinanceClient()
        await self.binance_client.connect()
        self.logger.info("  ✓ Binance Client connected")

        # SOTA: Fetch balance from Binance API (NOT from CLI in LIVE mode)
        if not self.config.get('dry_run'):
            # LIVE mode: Fetch from Binance Futures wallet
            try:
                self.logger.info("💰 Fetching balance from Binance Futures wallet...")
                account_info = await self.binance_client.client.futures_account()

                for asset in account_info.get('assets', []):
                    if asset['asset'] == 'USDT':
                        balance = float(asset['walletBalance'])
                        available = float(asset['availableBalance'])
                        self.config['balance'] = balance
                        self.logger.info(
                            f"  ✅ Balance fetched from Binance: ${balance:.2f} "
                            f"(Available: ${available:.2f})"
                        )
                        break
                else:
                    # USDT not found, fallback to CLI arg
                    self.logger.warning(
                        f"  ⚠️ USDT balance not found in Binance account. "
                        f"Using CLI arg: ${self.config['balance']:.2f}"
                    )
            except Exception as e:
                self.logger.error(f"  ❌ Failed to fetch balance from Binance: {e}")
                self.logger.warning(
                    f"  ⚠️ Falling back to CLI arg: ${self.config['balance']:.2f}"
                )
        else:
            # DRY-RUN mode: Use CLI arg
            self.logger.info(f"  🧪 DRY-RUN: Using CLI balance: ${self.config['balance']:.2f}")

        # Get symbols (dynamic top N by volume)
        symbols = self._get_symbols()
        self.logger.info(f"  Symbols: {len(symbols)} ({', '.join(symbols[:5])}...)")

        # Cache symbols for later use (avoid re-fetching)
        self._cached_symbols = symbols

        # Load exchange rules from Binance API
        exchange_rules = await self._load_exchange_rules(symbols)
        self.logger.info(f"  ✓ Exchange rules loaded for {len(exchange_rules)} symbols")

        # Initialize signal generator with required calculators
        from src.infrastructure.indicators.vwap_calculator import VWAPCalculator
        from src.infrastructure.indicators.bollinger_calculator import BollingerCalculator
        from src.infrastructure.indicators.stoch_rsi_calculator import StochRSICalculator
        from src.infrastructure.indicators.atr_calculator import ATRCalculator
        from src.infrastructure.indicators.sfp_detector import SFPDetector

        self.signal_generator = SignalGenerator(
            vwap_calculator=VWAPCalculator(),
            bollinger_calculator=BollingerCalculator(),
            stoch_rsi_calculator=StochRSICalculator(),
            atr_calculator=ATRCalculator(),
            sfp_detector=SFPDetector()
        )
        self.logger.info("  ✓ Signal Generator initialized")

        # Initialize Frequency Limiter (CRITICAL - prevent cost death spiral)
        # NOTE: Can be disabled for testing with --no-frequency-limit flag
        if self.config.get('enable_frequency_limit', True):
            self.frequency_limiter = FrequencyLimiter(
                max_daily=10,  # Hard limit: 10 trades/day
                max_monthly=100,  # Hard limit: 100 trades/month
                alert_threshold=0.8  # Alert at 80%
            )
            self.logger.info("  ✓ Frequency Limiter initialized (ENABLED)")
        else:
            self.frequency_limiter = None
            self.logger.warning("  ⚠️ Frequency Limiter DISABLED (for testing only)")

        # Initialize Shark Tank Coordinator
        self.shark_tank = SharkTankCoordinator(
            max_positions=self.config.get('max_positions', 5),
            enable_smart_recycling=self.config.get('zombie_killer', False)
        )
        self.logger.info("  ✓ Shark Tank Coordinator initialized")

        # Initialize Order Manager
        self.order_manager = OrderManager(
            binance_client=self.binance_client,
            default_ttl_minutes=self.config.get('ttl_minutes', 50),
            enable_backup_sl=True
        )
        self.logger.info("  ✓ Order Manager initialized")

        # Initialize Execution Adapter
        self.execution_adapter = ExecutionAdapter(
            binance_client=self.binance_client,
            initial_balance=self.config.get('balance', 34.0),
            fixed_leverage=self.config.get('leverage', 10),
            max_positions=self.config.get('max_positions', 5),
            spread_cost_pct=self.config.get('spread_cost_pct', 0.02) if self.config.get('enable_spread_cost', True) else 0.0,
            symbol_rules=exchange_rules,
            dry_run=self.config.get('dry_run', False)
        )

        if self.config.get('enable_spread_cost', True):
            self.logger.info("  ✓ Execution Adapter initialized (spread cost ENABLED)")
        else:
            self.logger.warning("  ⚠️ Execution Adapter initialized (spread cost DISABLED for testing)")

        # Initialize Performance Monitor (Task 10.3)
        self.performance_monitor = PerformanceMonitor(
            initial_balance=self.config.get('balance', 34.0),
            backtest_annual_return=0.452,  # 45.2% from backtest
            expected_degradation=0.25  # Expect 25% degradation
        )
        self.logger.info("  ✓ Performance Monitor initialized")

        # Initialize Position Monitor
        self.position_monitor = PositionMonitor(
            binance_client=self.binance_client,
            execution_adapter=self.execution_adapter,
            full_tp_at_tp1=self.config.get('full_tp', False),
            dry_run=self.config.get('dry_run', False)
        )

        # CRITICAL: Hook performance monitor to position monitor
        self.position_monitor.on_position_close = self._on_position_close

        self.logger.info("  ✓ Position Monitor initialized")

        # Initialize data manager (last, as it starts WebSocket)
        self.data_manager = RealTimeDataManager(
            symbols=symbols,
            on_candle_close=self._on_candle_close
        )
        self.logger.info("  ✓ Real-Time Data Manager initialized")

        self.logger.info("✅ All components initialized")

    async def _on_candle_close(self, symbol: str, timeframe: str, candle, htf_bias: str):
        """
        Called when candle closes.

        Triggers signal generation and order execution.

        Args:
            symbol: Symbol (e.g., 'btcusdt')
            timeframe: Timeframe (e.g., '15m')
            candle: Candle entity
            htf_bias: HTF bias ('BULLISH'/'BEARISH'/'NEUTRAL')
        """
        try:
            # Log candle close
            self.logger.info(
                f"🕐 CANDLE CLOSE: {symbol} {timeframe} | "
                f"O:{candle.open:.4f} H:{candle.high:.4f} L:{candle.low:.4f} C:{candle.close:.4f} | "
                f"HTF:{htf_bias} | Time:{candle.timestamp}"
            )

            # Only process 15m candles for signal generation
            if timeframe != '15m':
                return

            # Get candle history
            candles = self.data_manager.get_candles(symbol, timeframe)

            # Generate signal
            signal = self.signal_generator.generate_signal(
                candles=candles,
                symbol=symbol,
                htf_bias=htf_bias
            )

            if signal and signal.signal_type.value != 'neutral':
                # Enhanced signal logging with safe attribute access
                tp1 = signal.tp_levels.get('tp1') if signal.tp_levels else None
                atr = signal.indicators.get('atr') if signal.indicators else None

                # Format TP1 and ATR with proper handling
                tp1_str = f"{tp1:.4f}" if tp1 is not None else "N/A"
                atr_str = f"{atr:.2f}" if atr is not None else "N/A"

                self.logger.info(
                    f"📊 SIGNAL GENERATED: {symbol} {signal.signal_type.value.upper()} | "
                    f"Entry:{signal.entry_price:.4f} SL:{signal.stop_loss:.4f} TP1:{tp1_str} | "
                    f"Confidence:{signal.confidence:.2f} ATR:{atr_str} | "
                    f"HTF:{htf_bias}"
                )

                # Add signal to Shark Tank for batch processing
                self.shark_tank.add_signal(signal)

                # Check if should process batch
                if self.shark_tank.should_process(datetime.now(timezone.utc)):
                    await self._process_signal_batch()
            else:
                self.logger.debug(f"📊 No signal: {symbol} (neutral or invalid)")

        except Exception as e:
            self.logger.error(
                f"❌ Error processing candle close for {symbol}: {e}",
                exc_info=True
            )

    async def _on_price_update(self, symbol: str, price: float):
        """
        Called on price updates.

        Updates Shark Tank proximity sentry and Position Monitor.

        Args:
            symbol: Symbol (e.g., 'btcusdt')
            price: Current price
        """
        try:
            # Update Shark Tank for Proximity Sentry
            self.shark_tank.update_price(symbol, price)

            # Update Position Monitor for TP/SL checks
            if self.position_monitor:
                await self.position_monitor.on_price_update(symbol, price)
        except Exception as e:
            self.logger.error(
                f"❌ Error processing price update for {symbol}: {e}",
                exc_info=True
            )

    def _on_position_close(self, position, exit_price: float, pnl: float, exit_reason: str, exit_time):
        """
        Called when a position closes.

        Records trade in PerformanceMonitor for gap analysis.

        Args:
            position: LivePosition that closed
            exit_price: Exit price
            pnl: Net P&L (after fees)
            exit_reason: Exit reason (TP/SL/etc)
            exit_time: Exit timestamp
        """
        try:
            if self.performance_monitor:
                self.performance_monitor.record_trade(
                    symbol=position.symbol,
                    side=position.side,
                    entry_price=position.entry_price,
                    exit_price=exit_price,
                    pnl=pnl,
                    exit_reason=exit_reason,
                    entry_time=position.entry_time,
                    exit_time=exit_time
                )

                self.logger.debug(
                    f"📊 Trade recorded in PerformanceMonitor: {position.symbol} "
                    f"P&L=${pnl:+.2f} Reason={exit_reason}"
                )
        except Exception as e:
            self.logger.error(
                f"❌ Error recording trade in PerformanceMonitor: {e}",
                exc_info=True
            )

    async def _process_signal_batch(self):
        """
        Process batched signals through Shark Tank.

        Flow:
        1. Check frequency limits (CRITICAL) - if enabled
        2. Get signals to execute from Shark Tank
        3. Execute each signal via Execution Adapter
        4. Start position monitoring
        """
        try:
            # CRITICAL: Check frequency limits BEFORE processing signals (if enabled)
            if self.frequency_limiter and not self.frequency_limiter.can_trade():
                self.logger.warning("⚠️ Trading paused due to frequency limits")
                return

            # Get current state
            current_positions = self.execution_adapter.positions
            pending_orders = self.order_manager.pending_orders

            # Process signals through Shark Tank
            signals_to_execute = self.shark_tank.process_signals(
                current_positions=current_positions,
                pending_orders=pending_orders,
                current_time=datetime.now(timezone.utc)
            )

            # Execute each signal
            for signal in signals_to_execute:
                # Check frequency limit before each trade (if enabled)
                if self.frequency_limiter and not self.frequency_limiter.can_trade():
                    self.logger.warning(
                        f"⚠️ Skipping {signal.symbol}: Frequency limit reached"
                    )
                    break

                success = await self._execute_signal(signal)

                # Record trade if successful (if frequency limiter enabled)
                if success and self.frequency_limiter:
                    self.frequency_limiter.record_trade()

        except Exception as e:
            # Log error but continue (don't crash)
            self.logger.error(f"❌ Error processing signal batch: {e}", exc_info=True)

    def _alert_critical_error(self, message: str):
        """
        Alert on critical error.

        Args:
            message: Error message
        """
        self.logger.critical("=" * 80)
        self.logger.critical("🚨 CRITICAL ERROR ALERT 🚨")
        self.logger.critical("=" * 80)
        self.logger.critical(f"Message: {message}")
        self.logger.critical(f"Time: {datetime.now(timezone.utc)}")
        self.logger.critical(f"Balance: ${self.execution_adapter.balance:.2f}" if self.execution_adapter else "N/A")
        self.logger.critical(f"Open Positions: {len(self.execution_adapter.positions)}" if self.execution_adapter else "N/A")
        self.logger.critical("=" * 80)

        # TODO: Add additional alerting (email, SMS, webhook)
        # For now, just log to console and file

    async def _handle_critical_error(self, error: Exception):
        """
        Handle critical error that requires emergency shutdown.

        Flow:
        1. Log critical error
        2. Close all open positions (MARKET orders)
        3. Cancel all pending orders
        4. Save state to disk
        5. Alert user
        6. Exit with error code

        Args:
            error: The critical error
        """
        self._alert_critical_error(f"Critical error: {error}")

        try:
            # 1. Close all open positions
            if self.execution_adapter and self.execution_adapter.positions:
                self.logger.critical("🚨 Closing all open positions...")
                await self._emergency_close_all_positions()

            # 2. Cancel all pending orders
            if self.order_manager and self.order_manager.pending_orders:
                self.logger.critical("🚨 Cancelling all pending orders...")
                await self._cancel_all_pending_orders()

            # 3. Save state
            self.logger.critical("🚨 Saving state...")
            await self._save_state()

            # 4. Flush logs
            logging.shutdown()

        except Exception as e:
            self.logger.critical(f"❌ Emergency shutdown failed: {e}", exc_info=True)

        finally:
            # Exit with error code
            import sys
            sys.exit(1)

    async def _emergency_close_all_positions(self):
        """
        Emergency close all open positions with MARKET orders.

        Used during critical error shutdown.
        """
        if not self.execution_adapter:
            return

        positions = list(self.execution_adapter.positions.items())

        for symbol, position in positions:
            try:
                # Determine side for closing
                close_side = 'SELL' if position.side == 'LONG' else 'BUY'

                # Place MARKET order to close
                if not self.config.get('dry_run'):
                    self.binance_client.futures_create_order(
                        symbol=symbol,
                        side=close_side,
                        type='MARKET',
                        quantity=position.remaining_size
                    )

                self.logger.critical(f"🚨 Emergency closed: {symbol} {position.side} @ MARKET")

            except Exception as e:
                self.logger.critical(f"❌ Failed to emergency close {symbol}: {e}")

    async def _cancel_all_pending_orders(self):
        """
        Cancel all pending orders.

        Used during critical error shutdown.
        """
        if not self.order_manager:
            return

        pending = list(self.order_manager.pending_orders.keys())

        for symbol in pending:
            try:
                await self.order_manager.cancel_order(symbol, reason="EMERGENCY_SHUTDOWN")
                self.logger.critical(f"🚨 Cancelled pending order: {symbol}")
            except Exception as e:
                self.logger.critical(f"❌ Failed to cancel order for {symbol}: {e}")

    async def _execute_signal(self, signal):
        """
        Execute a single signal.

        Args:
            signal: TradingSignal to execute

        Returns:
            True if order placed successfully, False otherwise
        """
        try:
            # Dry-run indicator
            dry_run_prefix = "🧪 [DRY RUN] " if self.config.get('dry_run') else ""

            # Log order placement attempt
            self.logger.info(
                f"{dry_run_prefix}📤 PLACING ORDER: {signal.symbol} {signal.signal_type.value.upper()} | "
                f"Entry:{signal.entry_price:.4f} SL:{signal.stop_loss:.4f} | "
                f"Confidence:{signal.confidence:.2f}"
            )

            # Execute via Execution Adapter
            # NOTE: ExecutionAdapter.place_order() returns bool, not dict
            success = self.execution_adapter.place_order(signal)

            if success:
                # Log successful order placement
                self.logger.info(
                    f"{dry_run_prefix}✅ ORDER PLACED: {signal.symbol} {signal.signal_type.value.upper()} | "
                    f"Entry:${signal.entry_price:.4f} SL:${signal.stop_loss:.4f}"
                )

                return True
            else:
                # Log order failure
                self.logger.warning(
                    f"{dry_run_prefix}⚠️ ORDER FAILED: {signal.symbol} | Check logs for details"
                )
                return False

        except Exception as e:
            self.logger.error(
                f"❌ ERROR EXECUTING SIGNAL: {signal.symbol} | Error: {e}",
                exc_info=True
            )
            return False

    def _get_symbols(self) -> list:
        """
        Get list of symbols to trade.

        SOTA: Fetches top N symbols by 24h volume from Binance API.
        Matches backtest logic for consistency.

        Returns:
            List of symbols (e.g., ['btcusdt', 'ethusdt'])
        """
        top_n = self.config.get('top', 5)

        try:
            # Fetch top N by 24h volume from Binance
            self.logger.info(f"🔍 Fetching top {top_n} symbols by 24h volume from Binance...")

            # Use binance.client directly (python-binance library)
            from binance.client import Client

            # Create temporary client for API calls (not WebSocket)
            api_key = self.config.get('binance_api_key', '')
            api_secret = self.config.get('binance_api_secret', '')

            if not api_key or not api_secret:
                self.logger.warning("⚠️ No API keys found, using fallback symbols")
                raise Exception("No API keys")

            temp_client = Client(api_key, api_secret)

            # Get 24h ticker data
            tickers = temp_client.futures_ticker()

            # Filter USDT perpetual pairs only
            usdt_pairs = []
            for t in tickers:
                symbol = t['symbol']
                # Include only USDT perpetual contracts (exclude delivery contracts)
                if symbol.endswith('USDT') and not symbol.endswith('_USDT'):
                    usdt_pairs.append(t)

            # Sort by volume (quoteVolume = volume in USDT)
            sorted_pairs = sorted(
                usdt_pairs,
                key=lambda x: float(x.get('quoteVolume', 0)),
                reverse=True
            )

            # Get top N
            symbols = [p['symbol'].lower() for p in sorted_pairs[:top_n]]

            self.logger.info(
                f"✅ Selected top {len(symbols)} symbols by volume: "
                f"{', '.join(symbols[:10])}{'...' if len(symbols) > 10 else ''}"
            )

            return symbols

        except Exception as e:
            self.logger.error(f"❌ Failed to fetch top symbols from Binance: {e}", exc_info=True)
            self.logger.warning("⚠️ Falling back to safe default symbols...")

            # Fallback to safe defaults (high liquidity pairs)
            default_symbols = ['btcusdt', 'ethusdt', 'bnbusdt', 'solusdt', 'adausdt']
            self.logger.info(f"  Using defaults: {', '.join(default_symbols)}")

            return default_symbols

    async def _load_exchange_rules(self, symbols: list) -> dict:
        """
        Load exchange rules từ Binance API.

        Args:
            symbols: List of symbols to load rules for

        Returns:
            Dict of symbol -> rules (step_size, min_qty, min_notional, max_leverage, qty_precision)
        """
        rules = {}

        try:
            self.logger.info(f"📋 Loading exchange rules for {len(symbols)} symbols...")

            # Use binance.client directly (python-binance library)
            from binance.client import Client

            # Create temporary client for API calls
            api_key = self.config.get('binance_api_key', '')
            api_secret = self.config.get('binance_api_secret', '')

            if not api_key or not api_secret:
                self.logger.warning("⚠️ No API keys found, using fallback rules")
                raise Exception("No API keys")

            temp_client = Client(api_key, api_secret)

            # Fetch exchange info từ Binance
            exchange_info = temp_client.futures_exchange_info()

            # Extract rules for each symbol
            for symbol_info in exchange_info['symbols']:
                symbol = symbol_info['symbol'].lower()

                # Skip if not in our symbol list
                if symbol not in symbols:
                    continue

                # Extract filters
                filters = {f['filterType']: f for f in symbol_info['filters']}

                # Extract LOT_SIZE filter
                lot_size = filters.get('LOT_SIZE', {})
                step_size = float(lot_size.get('stepSize', 0.001))
                min_qty = float(lot_size.get('minQty', 0.001))

                # Extract MIN_NOTIONAL filter
                min_notional_filter = filters.get('MIN_NOTIONAL', {})
                min_notional = float(min_notional_filter.get('notional', 5.0))

                # Extract max leverage
                max_leverage = int(symbol_info.get('maxLeverage', 10))

                # Extract quantity precision
                qty_precision = int(symbol_info.get('quantityPrecision', 3))

                rules[symbol] = {
                    'step_size': step_size,
                    'min_qty': min_qty,
                    'min_notional': min_notional,
                    'max_leverage': max_leverage,
                    'qty_precision': qty_precision
                }

            self.logger.info(f"✅ Loaded exchange rules for {len(rules)} symbols")

            # Log sample rules
            if rules:
                sample_symbol = list(rules.keys())[0]
                sample_rules = rules[sample_symbol]
                self.logger.info(
                    f"📋 Sample rules ({sample_symbol}): "
                    f"step={sample_rules['step_size']}, "
                    f"min_qty={sample_rules['min_qty']}, "
                    f"min_notional=${sample_rules['min_notional']}, "
                    f"max_lev={sample_rules['max_leverage']}x"
                )

            return rules

        except Exception as e:
            self.logger.error(f"❌ Failed to load exchange rules from Binance API: {e}", exc_info=True)
            self.logger.warning("⚠️ Falling back to default rules...")

            # Fallback to default rules
            default_rules = {}
            for symbol in symbols:
                symbol_upper = symbol.upper()

                # Smart defaults based on symbol type
                if 'BTC' in symbol_upper:
                    default_rules[symbol] = {
                        'step_size': 0.001,
                        'min_qty': 0.001,
                        'min_notional': 100.0,
                        'max_leverage': 10,
                        'qty_precision': 3
                    }
                elif 'ETH' in symbol_upper:
                    default_rules[symbol] = {
                        'step_size': 0.01,
                        'min_qty': 0.01,
                        'min_notional': 20.0,
                        'max_leverage': 10,
                        'qty_precision': 2
                    }
                else:
                    default_rules[symbol] = {
                        'step_size': 0.1,
                        'min_qty': 0.1,
                        'min_notional': 5.0,
                        'max_leverage': 10,
                        'qty_precision': 1
                    }

            self.logger.info(f"⚠️ Using default rules for {len(default_rules)} symbols")
            return default_rules

    async def _check_status_report(self):
        """Check if should print 15-minute status report"""
        if not self._last_status_report:
            return

        elapsed = (datetime.now(timezone.utc) - self._last_status_report).total_seconds()

        if elapsed >= self._status_report_interval:
            self._print_status_report()
            self._last_status_report = datetime.now(timezone.utc)

    async def _check_hourly_report(self):
        """Check if should print hourly summary report"""
        if not self._last_hourly_report:
            return

        elapsed = (datetime.now(timezone.utc) - self._last_hourly_report).total_seconds()

        if elapsed >= self._hourly_report_interval:
            self._print_hourly_summary()
            self._last_hourly_report = datetime.now(timezone.utc)

    async def _check_buffer_save(self):
        """Check if should save candle buffers to disk (every 1 minute)"""
        if not self._last_buffer_save:
            return

        elapsed = (datetime.now(timezone.utc) - self._last_buffer_save).total_seconds()

        if elapsed >= self._buffer_save_interval:
            await self._save_candle_buffers()
            self._last_buffer_save = datetime.now(timezone.utc)

    async def _save_candle_buffers(self):
        """Save candle buffers to disk"""
        if not self.data_manager or not self.trade_repository:
            return

        try:
            # Use cached symbols (avoid re-fetching from Binance API)
            symbols = getattr(self, '_cached_symbols', None)
            if not symbols:
                # Fallback: get from data_manager if cache not available
                symbols = self.data_manager.symbols if self.data_manager else []

            if not symbols:
                self.logger.warning("⚠️ No symbols available for buffer save")
                return

            for symbol in symbols:
                # Save 15m candles
                candles_15m = self.data_manager.get_candles(symbol, '15m')
                if candles_15m:
                    # Convert candles to dict format with ISO timestamp
                    candles_dict = [
                        {
                            'timestamp': c.timestamp.isoformat() if hasattr(c.timestamp, 'isoformat') else str(c.timestamp),
                            'open': c.open,
                            'high': c.high,
                            'low': c.low,
                            'close': c.close,
                            'volume': c.volume
                        }
                        for c in candles_15m
                    ]
                    self.trade_repository.save_candle_buffer(symbol, '15m', candles_dict)

                # Save 4h candles
                candles_4h = self.data_manager.get_candles(symbol, '4h')
                if candles_4h:
                    candles_dict = [
                        {
                            'timestamp': c.timestamp.isoformat() if hasattr(c.timestamp, 'isoformat') else str(c.timestamp),
                            'open': c.open,
                            'high': c.high,
                            'low': c.low,
                            'close': c.close,
                            'volume': c.volume
                        }
                        for c in candles_4h
                    ]
                    self.trade_repository.save_candle_buffer(symbol, '4h', candles_dict)

            self.logger.debug(f"💾 Saved candle buffers for {len(symbols)} symbols")

        except Exception as e:
            self.logger.error(f"❌ Error saving candle buffers: {e}", exc_info=True)

    async def _save_state(self):
        """Save system state to disk"""
        if not self.trade_repository:
            return

        try:
            # Save balance
            if self.execution_adapter:
                self.trade_repository.save_balance(self.execution_adapter.balance)
                self.logger.info(f"💾 Saved balance: ${self.execution_adapter.balance:.2f}")

            # Save candle buffers
            await self._save_candle_buffers()

            # Save open trades
            if self.execution_adapter:
                positions = self.execution_adapter.positions
                for symbol, pos in positions.items():
                    trade = {
                        'id': pos.get('id', f"trade_{symbol}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"),
                        'symbol': symbol,
                        'side': pos['side'],
                        'entry_price': pos['entry_price'],
                        'quantity': pos['remaining_size'],
                        'leverage': pos.get('leverage', 10),
                        'margin': pos.get('margin', 0),
                        'notional': pos.get('notional', 0),
                        'initial_sl': pos.get('initial_sl', 0),
                        'initial_tp': pos.get('initial_tp', 0),
                        'final_sl': pos.get('stop_loss', 0),
                        'entry_time': pos.get('entry_time', datetime.now(timezone.utc)).isoformat(),
                        'confidence': pos.get('confidence', 0),
                        'atr': pos.get('atr', 0),
                        'status': 'OPEN'
                    }
                    self.trade_repository.save_trade(trade)

            # Save pending orders
            if self.order_manager:
                for symbol, order in self.order_manager.pending_orders.items():
                    order_dict = {
                        'id': order.order_id,
                        'symbol': symbol,
                        'side': order.side,
                        'target_price': order.target_price,
                        'quantity': order.quantity,
                        'leverage': 10,
                        'stop_loss': order.stop_loss if hasattr(order, 'stop_loss') else 0,
                        'take_profit': order.take_profit if hasattr(order, 'take_profit') else 0,
                        'confidence': order.confidence,
                        'atr': order.atr if hasattr(order, 'atr') else 0,
                        'created_at': order.created_at.isoformat(),
                        'ttl_minutes': order.ttl_minutes,
                        'expires_at': (order.created_at + timedelta(minutes=order.ttl_minutes)).isoformat(),
                        'status': 'PENDING'
                    }
                    self.trade_repository.save_pending_order(order_dict)

            self.logger.info("✅ State saved successfully")

        except Exception as e:
            self.logger.error(f"❌ Error saving state: {e}", exc_info=True)

    def _print_status_report(self):
        """Print 15-minute status report"""
        self.logger.info("=" * 80)
        self.logger.info("📊 STATUS REPORT (15-minute update)")
        self.logger.info("=" * 80)

        # Frequency limiter stats
        if self.frequency_limiter:
            freq_stats = self.frequency_limiter.get_stats()
            self.logger.info(f"🚦 Frequency Limits:")
            self.logger.info(
                f"  Daily: {freq_stats['daily_count']}/{freq_stats['daily_limit']} "
                f"({freq_stats['daily_usage_pct']:.0f}% used, {freq_stats['daily_remaining']} remaining)"
            )
            self.logger.info(
                f"  Monthly: {freq_stats['monthly_count']}/{freq_stats['monthly_limit']} "
                f"({freq_stats['monthly_usage_pct']:.0f}% used, {freq_stats['monthly_remaining']} remaining)"
            )

            # Current balance and positions
        if self.execution_adapter:
            balance = self.execution_adapter.balance
            positions = self.execution_adapter.positions
            pending = len(self.order_manager.pending_orders) if self.order_manager else 0

            self.logger.info(f"💰 Balance: ${balance:.2f}")
            self.logger.info(f"📈 Open Positions: {len(positions)}")
            self.logger.info(f"⏳ Pending Orders: {pending}")

            # List open positions
            if positions:
                self.logger.info("  Open Positions:")
                for symbol, pos in positions.items():
                    side = pos.get('side', 'UNKNOWN')
                    entry = pos.get('entry_price', 0)
                    size = pos.get('remaining_size', 0)
                    sl = pos.get('stop_loss', 0)
                    self.logger.info(
                        f"    {symbol}: {side} | Entry:${entry:.4f} Size:{size:.4f} SL:${sl:.4f}"
                    )

            # List pending orders
            if pending > 0:
                self.logger.info("  Pending Orders:")
                for symbol, order in self.order_manager.pending_orders.items():
                    side = order.side
                    target = order.target_price
                    conf = order.confidence
                    age = order.age_minutes
                    self.logger.info(
                        f"    {symbol}: {side} | Target:${target:.4f} Conf:{conf:.2f} Age:{age:.1f}min"
                    )

        # Performance stats (Task 10.3)
        if self.performance_monitor:
            perf_stats = self.performance_monitor.get_stats()
            if perf_stats['total_trades'] > 0:
                self.logger.info(f"📊 Performance:")
                self.logger.info(f"  Total P&L: ${perf_stats['total_pnl']:+.2f}")
                self.logger.info(f"  Win Rate: {perf_stats['win_rate']:.1%}")
                self.logger.info(f"  Trades (30d): {perf_stats['trades_last_30_days']}")

        self.logger.info("=" * 80)

    def _print_hourly_summary(self):
        """Print hourly summary report with trades, PnL, win rate"""
        self.logger.info("=" * 80)
        self.logger.info("📈 HOURLY SUMMARY REPORT")
        self.logger.info("=" * 80)

        # Performance Monitor report (Task 10.3)
        if self.performance_monitor:
            self.performance_monitor.print_performance_report()

            # Check performance gap
            gap_analysis = self.performance_monitor.calculate_performance_gap()
            if gap_analysis and gap_analysis['status'] != 'insufficient_data':
                # Already logged in calculate_performance_gap
                pass
        else:
            # Fallback to basic stats if no performance monitor
            if self.execution_adapter:
                balance = self.execution_adapter.balance
                initial = self.config.get('balance', 34.0)
                pnl = balance - initial
                pnl_pct = (pnl / initial) * 100

                self.logger.info(f"💰 Current Balance: ${balance:.2f}")
                self.logger.info(f"📊 P&L: ${pnl:+.2f} ({pnl_pct:+.2f}%)")

            if self.order_manager:
                self.logger.info(f"📤 Orders Placed: {self.order_manager._orders_placed}")
                self.logger.info(f"✅ Orders Filled: {self.order_manager._orders_filled}")
                self.logger.info(f"🚫 Orders Cancelled: {self.order_manager._orders_cancelled}")
                self.logger.info(f"⏰ Orders Expired: {self.order_manager._orders_expired}")

            if self.position_monitor:
                stats = self.position_monitor.get_stats()
                closed = stats.get('positions_closed', 0)
                tp_hits = stats.get('tp_hits', 0)
                sl_hits = stats.get('sl_hits', 0)

                self.logger.info(f"🔒 Positions Closed: {closed}")
                self.logger.info(f"🎯 TP Hits: {tp_hits}")
                self.logger.info(f"🛑 SL Hits: {sl_hits}")

                if closed > 0:
                    win_rate = (tp_hits / closed) * 100
                    self.logger.info(f"📊 Win Rate: {win_rate:.1f}%")

        self.logger.info("=" * 80)

    def _log_config(self):
        """Log configuration"""
        self.logger.info("📋 Configuration:")
        self.logger.info(f"  Mode: {'DRY RUN' if self.config.get('dry_run') else 'LIVE'}")
        self.logger.info(f"  Balance: ${self.config.get('balance', 34)}")
        self.logger.info(f"  Leverage: {self.config.get('leverage', 10)}x")
        self.logger.info(f"  Max Positions: {self.config.get('max_positions', 5)}")
        self.logger.info(f"  Risk per Trade: {self.config.get('risk_percent', 1.0)}%")
        self.logger.info(f"  Order TTL: {self.config.get('ttl_minutes', 50)} minutes")
        self.logger.info(f"  Smart Recycling: {'ON' if self.config.get('zombie_killer') else 'OFF'}")
        self.logger.info(f"  Full TP: {'ON' if self.config.get('full_tp') else 'OFF'}")

    def _print_summary(self):
        """Print summary report"""
        self.logger.info("=" * 80)
        self.logger.info("📊 SUMMARY REPORT")
        self.logger.info("=" * 80)

        # Data Manager stats
        if self.data_manager:
            stats = self.data_manager.get_stats()
            self.logger.info(f"  Symbols: {stats['symbols']}")
            self.logger.info(f"  Candles Processed: {stats['total_candles_processed']}")
            self.logger.info(f"  15m Candles: {stats['candles_15m']}")
            self.logger.info(f"  4h Candles: {stats['candles_4h']}")

        # Order Manager stats
        if self.order_manager:
            self.logger.info(f"  Orders Placed: {self.order_manager._orders_placed}")
            self.logger.info(f"  Orders Filled: {self.order_manager._orders_filled}")
            self.logger.info(f"  Orders Cancelled: {self.order_manager._orders_cancelled}")
            self.logger.info(f"  Orders Expired: {self.order_manager._orders_expired}")

        # Execution Adapter stats
        if self.execution_adapter:
            self.logger.info(f"  Current Balance: ${self.execution_adapter.balance:.2f}")
            self.logger.info(f"  Open Positions: {len(self.execution_adapter.positions)}")
            self.logger.info(f"  Pending Orders: {len(self.order_manager.pending_orders)}")

        # Position Monitor stats
        if self.position_monitor:
            stats = self.position_monitor.get_stats()
            self.logger.info(f"  Positions Closed: {stats.get('positions_closed', 0)}")
            self.logger.info(f"  TP Hits: {stats.get('tp_hits', 0)}")
            self.logger.info(f"  SL Hits: {stats.get('sl_hits', 0)}")

        # Trade Repository stats
        if self.trade_repository:
            stats = self.trade_repository.get_stats()
            self.logger.info(f"  Total Trades: {stats['total_trades']}")
            self.logger.info(f"  Win Rate: {stats['win_rate']:.1f}%")
            self.logger.info(f"  Total P&L: ${stats['total_pnl']:.2f}")

        self.logger.info("=" * 80)


def setup_logging(verbose: bool = False):
    """Setup logging configuration with file and console handlers"""
    level = logging.DEBUG if verbose else logging.INFO

    # Create logs directory if not exists
    log_dir = Path(__file__).parent / 'logs'
    log_dir.mkdir(exist_ok=True)

    # Generate log filename with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = log_dir / f'live_trading_{timestamp}.log'

    # Create formatters
    console_formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    file_formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)-30s | %(funcName)-20s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # CRITICAL: Clear all existing handlers first (prevents duplicate/default handlers)
    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(console_formatter)

    # File handler (always DEBUG level for detailed logs)
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_formatter)

    # Critical error file handler (separate file for critical errors)
    critical_log_file = log_dir / f'live_trading_critical_{timestamp}.log'
    critical_handler = logging.FileHandler(critical_log_file, encoding='utf-8')
    critical_handler.setLevel(logging.CRITICAL)
    critical_handler.setFormatter(file_formatter)

    # Configure root logger
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(critical_handler)

    # Reduce noise from libraries
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('websockets').setLevel(logging.WARNING)

    # CRITICAL: Reduce WebSocket spam (50 symbols × 3 timeframes = 150 streams)
    logging.getLogger('src.infrastructure.websocket').setLevel(logging.INFO)
    logging.getLogger('src.infrastructure.websocket.message_parser').setLevel(logging.WARNING)
    logging.getLogger('src.infrastructure.websocket.binance_websocket_client').setLevel(logging.INFO)

    # Reduce event bus warnings during startup (normal behavior)
    logging.getLogger('src.api.event_bus').setLevel(logging.ERROR)

    # Log file locations
    logger = logging.getLogger(__name__)
    logger.info(f"📝 Log file: {log_file}")
    logger.info(f"🚨 Critical log file: {critical_log_file}")


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='Live Trading Runner - Backtest-Mode Live Trading System',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Live trading with 50 symbols
  python run_live_trading.py --top 50 --balance 34 --leverage 10 --max-pos 5 --zombie-killer --full-tp --ttl 50

  # Dry-run mode (paper trading)
  python run_live_trading.py --dry-run --top 5

  # Emergency stop (close all positions and exit)
  python run_live_trading.py --emergency-stop
        """
    )

    # Trading parameters (matching backtest)
    parser.add_argument('--top', type=int, default=5, help='Number of top symbols by volume (default: 5)')
    parser.add_argument('--balance', type=float, default=34.0, help='Initial balance in USD (default: 34). NOTE: In LIVE mode, balance is fetched from Binance API. This arg is only used for DRY-RUN mode.')
    parser.add_argument('--leverage', type=int, default=10, help='Leverage (default: 10)')
    parser.add_argument('--max-pos', type=int, default=5, help='Max concurrent positions (default: 5)')
    parser.add_argument('--risk', type=float, default=1.0, help='Risk per trade in percent (default: 1.0)')
    parser.add_argument('--ttl', type=int, default=50, help='Order TTL in minutes (default: 50)')

    # Features
    parser.add_argument('--zombie-killer', action='store_true', help='Enable Smart Recycling')
    parser.add_argument('--full-tp', action='store_true', help='Close 100 percent at TP1 (default: 60 percent)')
    parser.add_argument('--circuit-breaker', action='store_true', help='Enable Circuit Breaker')

    # Phase 10 features (can be disabled for testing)
    parser.add_argument('--no-frequency-limit', action='store_true', help='Disable frequency limits (for testing only)')
    parser.add_argument('--no-spread-cost', action='store_true', help='Disable spread cost modeling (for testing only)')

    # Modes
    parser.add_argument('--dry-run', action='store_true', help='Paper trading mode (no real orders)')
    parser.add_argument('--emergency-stop', action='store_true', help='Close all positions and exit')

    # Logging
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose logging (DEBUG level)')

    return parser.parse_args()


async def main():
    """Main entry point"""
    # Parse arguments
    args = parse_args()

    # Setup logging
    setup_logging(verbose=args.verbose)
    logger = logging.getLogger(__name__)

    # Emergency stop mode
    if args.emergency_stop:
        logger.error("=" * 80)
        logger.error("⚠️ EMERGENCY STOP MODE")
        logger.error("=" * 80)
        logger.error("⚠️ This will:")
        logger.error("⚠️   1. Close ALL open positions at MARKET price")
        logger.error("⚠️   2. Cancel ALL pending orders")
        logger.error("⚠️   3. Save state and exit")
        logger.error("⚠️")
        logger.error("⚠️ Press Ctrl+C within 5 seconds to cancel")
        logger.error("=" * 80)

        try:
            await asyncio.sleep(5)
        except KeyboardInterrupt:
            logger.info("✅ Emergency stop cancelled by user")
            return

        # Build minimal config for emergency stop
        config = {
            'balance': args.balance,
            'leverage': args.leverage,
            'max_positions': args.max_pos,
            'risk_percent': args.risk,
            'ttl_minutes': args.ttl,
            'zombie_killer': args.zombie_killer,
            'full_tp': args.full_tp,
            'circuit_breaker': args.circuit_breaker,
            'dry_run': args.dry_run,
            'emergency_stop': True  # Flag for emergency stop
        }

        # Load additional config from .env
        try:
            env_config = load_config()
            config.update(env_config)
        except Exception as e:
            logger.warning(f"Failed to load .env config: {e}")

        # Create runner and execute emergency stop
        runner = LiveTradingRunner(config)

        try:
            # Initialize components (needed to access positions/orders)
            await runner._initialize_components()

            # Execute emergency stop
            logger.error("🚨 Executing emergency stop...")
            await runner.stop(emergency_close_positions=True)

            logger.info("✅ Emergency stop completed successfully")
            sys.exit(0)

        except Exception as e:
            logger.error(f"❌ Emergency stop failed: {e}", exc_info=True)
            sys.exit(1)

    # Dry-run mode warning
    if args.dry_run:
        logger.warning("=" * 80)
        logger.warning("⚠️ DRY RUN MODE - NO REAL ORDERS WILL BE EXECUTED")
        logger.warning("=" * 80)

    # Build config
    config = {
        'top': args.top,
        'balance': args.balance,
        'leverage': args.leverage,
        'max_positions': args.max_pos,
        'risk_percent': args.risk,
        'ttl_minutes': args.ttl,
        'zombie_killer': args.zombie_killer,
        'full_tp': args.full_tp,
        'circuit_breaker': args.circuit_breaker,
        'dry_run': args.dry_run,
        'emergency_stop': False,
        # Phase 10 features (can be disabled for testing)
        'enable_frequency_limit': not args.no_frequency_limit,
        'enable_spread_cost': not args.no_spread_cost
    }

    # Load additional config from .env (API keys, etc.)
    try:
        env_config = load_config()

        # Extract API keys from environment variables (loaded by load_config)
        import os
        api_key = os.getenv('BINANCE_API_KEY', '')
        api_secret = os.getenv('BINANCE_API_SECRET', '')

        if api_key and api_secret:
            config['binance_api_key'] = api_key
            config['binance_api_secret'] = api_secret
            logger.info("✅ Loaded API keys from .env")
        else:
            logger.warning("⚠️ No API keys found in .env - will use fallback symbols")

    except Exception as e:
        logger.warning(f"⚠️ Failed to load .env config: {e}")
        # Will use fallback symbols if no API keys

    # Create runner
    runner = LiveTradingRunner(config)

    # Setup signal handlers for graceful shutdown
    def signal_handler(sig, frame):
        logger.info(f"⚠️ Received signal {sig}, initiating graceful shutdown...")
        runner._shutdown_requested = True

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start runner
    try:
        await runner.start()
        logger.info("✅ Live trading system exited successfully")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())
