"""
Dependency Injection Container - Infrastructure Layer

Container for managing dependencies and providing instances.

Production Readiness Update:
- Added BookTickerClient for real spread data
- Added TradingStateMachine for state management
- Added WarmupManager for cold start
- Added HardFilters with BookTickerClient injection
- Added StateRecoveryService for startup recovery
- Added RealtimeService with all dependencies
"""

from typing import Optional, Dict, Any
import logging
import os

from .persistence.sqlite_market_data_repository import SQLiteMarketDataRepository
from .persistence.sqlite_state_repository import SQLiteStateRepository
from .persistence.sqlite_order_repository import SQLiteOrderRepository
from .api.binance_client import BinanceClient
from .api.binance_rest_client import BinanceRestClient
from .exchange.paper_exchange_service import PaperExchangeService
# NOTE: Deprecated - uses ccxt. Live trading uses LiveTradingService + BinanceFuturesClient
# from .exchange.binance_exchange_service import BinanceExchangeService
from ..domain.interfaces.i_exchange_service import IExchangeService
from .indicators.talib_calculator import TALibCalculator
from .indicators.vwap_calculator import VWAPCalculator
from .indicators.bollinger_calculator import BollingerCalculator
from .indicators.stoch_rsi_calculator import StochRSICalculator
from .indicators.adx_calculator import ADXCalculator
from .indicators.atr_calculator import ATRCalculator
from .indicators.volume_spike_detector import VolumeSpikeDetector
from .indicators.regime_detector import RegimeDetector  # SOTA: For Layer 0 filtering
from .indicators.sfp_detector import SFPDetector  # SOTA: Phase 1 SFP
from .indicators.momentum_velocity_calculator import MomentumVelocityCalculator # SOTA: Phase 2 Velocity
from .websocket.binance_websocket_client import BinanceWebSocketClient
from .websocket.binance_book_ticker_client import BinanceBookTickerClient
from .aggregation.data_aggregator import DataAggregator
from ..application.use_cases.fetch_market_data import FetchMarketDataUseCase
from ..application.use_cases.calculate_indicators import CalculateIndicatorsUseCase
from ..application.use_cases.validate_data import ValidateDataUseCase
from ..application.use_cases.export_data import ExportDataUseCase
from ..application.services.pipeline_service import PipelineService
from ..application.services.dashboard_service import DashboardService
from ..application.services.trading_state_machine import TradingStateMachine
from ..application.services.warmup_manager import WarmupManager
from ..application.services.hard_filters import HardFilters
from ..application.services.state_recovery_service import StateRecoveryService
from ..config.market_mode import MarketMode
from ..application.services.smart_entry_calculator import SmartEntryCalculator
from ..application.analysis.trend_filter import TrendFilter # SOTA: For HTF Confluence
from ..application.services.settings_provider import SettingsProvider  # SOTA: Centralized config
from ..application.services.reconciliation_service import ReconciliationService  # SOTA: Exchange sync
from .monitoring.profit_chart_generator import ProfitChartGenerator  # SOTA: Telegram profit charts
from ..config.runtime import get_runtime_env, get_trading_db_path
from ..trading_contract import (
    PRODUCTION_MAX_SL_PCT,
    PRODUCTION_MTF_EMA_PERIOD,
    PRODUCTION_SNIPER_LOOKBACK,
    PRODUCTION_SNIPER_PROXIMITY,
    PRODUCTION_USE_DELTA_DIVERGENCE,
    PRODUCTION_USE_MAX_SL_VALIDATION,
    PRODUCTION_USE_MTF_TREND,
    get_production_blocked_windows,
)


class DIContainer:
    """
    Dependency Injection Container.

    This container manages the creation and lifecycle of all dependencies
    in the application. It implements the Singleton pattern for shared
    instances and provides factory methods for creating services.

    SOTA: Per-environment instance caching.
    - Each environment (paper/testnet/live) has its own service instances
    - Switching mode doesn't destroy other environment's cache
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the DI container.

        Args:
            config: Configuration dictionary with settings
        """
        self.config = config or {}

        # SOTA: Per-environment instance caching
        # Each environment maintains its own service instances
        self._env_instances: Dict[str, Dict[str, Any]] = {
            'paper': {},
            'testnet': {},
            'live': {}
        }

        self.logger = logging.getLogger(__name__)

        # SOTA: Current environment from ENV variable
        # CRITICAL: .strip() to remove any trailing whitespace from ENV
        self._env = get_runtime_env()
        self._trading_db_path = self._get_env_db_path()

    @property
    def _instances(self) -> Dict[str, Any]:
        """Get current environment's instance cache."""
        # CRITICAL: Always return a reference stored in _env_instances
        # Never return a new dict, or modifications will be lost
        if self._env not in self._env_instances:
            self._env_instances[self._env] = {}
        return self._env_instances[self._env]

    def refresh_env(self):
        """Refresh environment from ENV variable (call after mode switch)."""
        self._env = get_runtime_env()
        self._trading_db_path = self._get_env_db_path()
        self.logger.info(f"🔄 DI Container refreshed for ENV={self._env}")

    def _get_env_db_path(self) -> str:
        """
        Get environment-aware trading database path.

        SOTA: Database isolation per environment (paper/testnet/live).
        Uses absolute path to avoid working directory issues.
        """
        db_path = get_trading_db_path(self._env)

        # Ensure directory exists
        db_path.parent.mkdir(parents=True, exist_ok=True)

        return str(db_path)

    def get_config(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value.

        Args:
            key: Configuration key
            default: Default value if key not found

        Returns:
            Configuration value
        """
        return self.config.get(key, default)

    def get_binance_client(self) -> BinanceClient:
        """
        Get BinanceClient instance (singleton).

        Returns:
            BinanceClient instance
        """
        if 'binance_client' not in self._instances:
            api_key = self.get_config('BINANCE_API_KEY')
            api_secret = self.get_config('BINANCE_API_SECRET')

            self._instances['binance_client'] = BinanceClient(
                api_key=api_key,
                api_secret=api_secret
            )
            self.logger.debug("Created BinanceClient instance")

        return self._instances['binance_client']

    def get_indicator_calculator(self) -> TALibCalculator:
        """
        Get TALibCalculator instance (singleton).

        Returns:
            TALibCalculator instance
        """
        if 'indicator_calculator' not in self._instances:
            self._instances['indicator_calculator'] = TALibCalculator()
            self.logger.debug("Created TALibCalculator instance")

        return self._instances['indicator_calculator']

    def get_market_data_repository(self) -> SQLiteMarketDataRepository:
        """
        Get SQLiteMarketDataRepository instance (singleton).

        Returns:
            SQLiteMarketDataRepository instance
        """
        if 'market_data_repository' not in self._instances:
            # SOTA: Store databases in data/ folder for clean project structure
            db_path = self.get_config('DATABASE_PATH', 'data/market_data.db')

            self._instances['market_data_repository'] = SQLiteMarketDataRepository(
                db_path=db_path
            )
            self.logger.debug(f"Created SQLiteMarketDataRepository with db: {db_path}")

        return self._instances['market_data_repository']

    def get_data_retention_service(self):
        """
        Get DataRetentionService instance (singleton).

        SOTA: Automatic database cleanup with rolling window policy.

        Returns:
            DataRetentionService instance
        """
        if 'data_retention_service' not in self._instances:
            # Lazy import to avoid circular dependency
            from ..application.services.data_retention_service import DataRetentionService

            self._instances['data_retention_service'] = DataRetentionService(
                repository=self.get_market_data_repository()
            )
            self.logger.debug("Created DataRetentionService")

        return self._instances['data_retention_service']

    def get_fetch_market_data_use_case(self) -> FetchMarketDataUseCase:
        """
        Get FetchMarketDataUseCase instance.

        Returns:
            FetchMarketDataUseCase instance
        """
        binance_client = self.get_binance_client()
        return FetchMarketDataUseCase(binance_client)

    def get_calculate_indicators_use_case(self) -> CalculateIndicatorsUseCase:
        """
        Get CalculateIndicatorsUseCase instance.

        Returns:
            CalculateIndicatorsUseCase instance
        """
        calculator = self.get_indicator_calculator()
        return CalculateIndicatorsUseCase(calculator)

    def get_validate_data_use_case(self) -> ValidateDataUseCase:
        """
        Get ValidateDataUseCase instance.

        Returns:
            ValidateDataUseCase instance
        """
        repository = self.get_market_data_repository()
        return ValidateDataUseCase(repository)

    def get_export_data_use_case(self) -> ExportDataUseCase:
        """
        Get ExportDataUseCase instance.

        Returns:
            ExportDataUseCase instance
        """
        repository = self.get_market_data_repository()
        return ExportDataUseCase(repository)

    def get_pipeline_service(self) -> PipelineService:
        """
        Get PipelineService instance.

        Returns:
            PipelineService instance with all dependencies injected
        """
        fetch_use_case = self.get_fetch_market_data_use_case()
        calculate_use_case = self.get_calculate_indicators_use_case()
        repository = self.get_market_data_repository()

        return PipelineService(
            fetch_use_case=fetch_use_case,
            calculate_use_case=calculate_use_case,
            repository=repository
        )

    def get_dashboard_service(self) -> DashboardService:
        """
        Get DashboardService instance.

        Returns:
            DashboardService instance with all dependencies injected
        """
        market_data_repo = self.get_market_data_repository()
        export_use_case = self.get_export_data_use_case()
        validate_use_case = self.get_validate_data_use_case()

        return DashboardService(
            market_data_repo=market_data_repo,
            export_use_case=export_use_case,
            validate_use_case=validate_use_case
        )

    # ==================== Production Readiness Methods ====================

    def get_book_ticker_client(self) -> BinanceBookTickerClient:
        """
        Get BinanceBookTickerClient instance (singleton).

        Returns:
            BinanceBookTickerClient for real bid/ask data
        """
        if 'book_ticker_client' not in self._instances:
            self._instances['book_ticker_client'] = BinanceBookTickerClient()
            self.logger.debug("Created BinanceBookTickerClient instance")

        return self._instances['book_ticker_client']

    def get_trading_state_machine(self, symbol: str = "btcusdt") -> TradingStateMachine:
        """
        Get TradingStateMachine instance (singleton per symbol).

        Args:
            symbol: Trading symbol

        Returns:
            TradingStateMachine instance
        """
        key = f'trading_state_machine_{symbol}'
        if key not in self._instances:
            self._instances[key] = TradingStateMachine(symbol=symbol)
            self.logger.debug(f"Created TradingStateMachine for {symbol}")

        return self._instances[key]

    def get_warmup_manager(self) -> WarmupManager:
        """
        Get WarmupManager instance (singleton).

        Returns:
            WarmupManager instance
        """
        if 'warmup_manager' not in self._instances:
            rest_client = self.get_rest_client()
            vwap_calculator = self.get_vwap_calculator()
            stoch_rsi_calculator = self.get_stoch_rsi_calculator()
            adx_calculator = self.get_adx_calculator()

            self._instances['warmup_manager'] = WarmupManager(
                rest_client=rest_client,
                vwap_calculator=vwap_calculator,
                stoch_rsi_calculator=stoch_rsi_calculator,
                adx_calculator=adx_calculator
            )
            self.logger.debug("Created WarmupManager instance")

        return self._instances['warmup_manager']

    def get_settings_provider(self) -> SettingsProvider:
        """
        Get SettingsProvider instance (singleton).

        SOTA: Centralized configuration provider.
        All services should use this for runtime settings.

        Returns:
            SettingsProvider instance
        """
        if 'settings_provider' not in self._instances:
            # Use order_repository for Settings DB access
            order_repo = self.get_order_repository()
            self._instances['settings_provider'] = SettingsProvider(order_repo)
            self.logger.info("📊 Created SettingsProvider instance")

        return self._instances['settings_provider']

    def get_hard_filters(self) -> HardFilters:
        """
        Get HardFilters instance with BookTickerClient and Config injection (singleton).

        Expert Feedback 3: Now injects Config for configurable thresholds

        Returns:
            HardFilters instance with real spread data capability
        """
        if 'hard_filters' not in self._instances:
            book_ticker_client = self.get_book_ticker_client()
            config = self.get_config_instance()

            self._instances['hard_filters'] = HardFilters(
                book_ticker_client=book_ticker_client,
                config=config
            )
            self.logger.debug("Created HardFilters with BookTickerClient and Config")

        return self._instances['hard_filters']

    def get_config_instance(self):
        """
        Get Config instance (singleton).

        Expert Feedback 3: Centralized config management

        Returns:
            Config instance with all settings
        """
        if 'config_instance' not in self._instances:
            from ..config import Config
            self._instances['config_instance'] = Config()
            self.logger.debug("Created Config instance")

        return self._instances['config_instance']

    # NOTE: get_order_repository() defined below (~line 948) — env-aware version
    # Removed duplicate here (was dead code — Python uses last definition)

    def get_exchange_service(self) -> IExchangeService:
        """
        Get IExchangeService instance based on TRADING_MODE config (singleton).

        Factory method that returns:
        - PaperExchangeService when TRADING_MODE="PAPER" (default)
        - BinanceExchangeService when TRADING_MODE="REAL"

        Returns:
            IExchangeService implementation
        """
        if 'exchange_service' not in self._instances:
            trading_mode = self.get_config('TRADING_MODE', 'PAPER').upper()

            if trading_mode == 'PAPER':
                order_repository = self.get_order_repository()
                self._instances['exchange_service'] = PaperExchangeService(
                    order_repository=order_repository
                )
                self.logger.info("Created PaperExchangeService (PAPER mode)")
            elif trading_mode == 'REAL':
                # NOTE: BinanceExchangeService deprecated (uses ccxt)
                # Live trading uses LiveTradingService + BinanceFuturesClient directly
                # For IExchangeService interface, we use Paper as fallback
                order_repository = self.get_order_repository()
                self._instances['exchange_service'] = PaperExchangeService(
                    order_repository=order_repository
                )
                self.logger.warning(
                    "REAL mode: IExchangeService uses Paper fallback. "
                    "Actual trading via LiveTradingService."
                )
            else:
                # Default to paper trading for safety
                self.logger.warning(
                    f"Unknown TRADING_MODE '{trading_mode}', defaulting to PAPER"
                )
                order_repository = self.get_order_repository()
                self._instances['exchange_service'] = PaperExchangeService(
                    order_repository=order_repository
                )

        return self._instances['exchange_service']

    def get_state_repository(self) -> SQLiteStateRepository:
        """
        Get SQLiteStateRepository instance (singleton).

        Returns:
            SQLiteStateRepository for state persistence
        """
        if 'state_repository' not in self._instances:
            db_path = self.get_config('DATABASE_PATH', 'data/trading_system.db')
            self._instances['state_repository'] = SQLiteStateRepository(db_path=db_path)
            self.logger.debug(f"Created SQLiteStateRepository with db: {db_path}")

        return self._instances['state_repository']

    def get_state_recovery_service(self) -> StateRecoveryService:
        """
        Get StateRecoveryService instance (singleton).

        Expert Feedback 3: Now uses IExchangeService instead of IRestClient

        Returns:
            StateRecoveryService for startup recovery
        """
        if 'state_recovery_service' not in self._instances:
            state_repository = self.get_state_repository()
            exchange_service = self.get_exchange_service()

            self._instances['state_recovery_service'] = StateRecoveryService(
                state_repository=state_repository,
                exchange_service=exchange_service
            )
            self.logger.debug(
                f"Created StateRecoveryService with {exchange_service.get_exchange_type()} exchange"
            )

        return self._instances['state_recovery_service']

    def get_rest_client(self) -> BinanceRestClient:
        """
        Get BinanceRestClient instance (singleton).

        Returns:
            BinanceRestClient instance
        """
        if 'rest_client' not in self._instances:
            self._instances['rest_client'] = BinanceRestClient()
            self.logger.debug("Created BinanceRestClient instance")

        return self._instances['rest_client']

    def get_websocket_client(self) -> BinanceWebSocketClient:
        """
        Get BinanceWebSocketClient instance (singleton).

        Returns:
            BinanceWebSocketClient instance
        """
        if 'websocket_client' not in self._instances:
            self._instances['websocket_client'] = BinanceWebSocketClient()
            self.logger.debug("Created BinanceWebSocketClient instance")

        return self._instances['websocket_client']

    def get_data_aggregator(self) -> DataAggregator:
        """
        Get DataAggregator instance (Transient).

        CRITICAL FIX (Phase 6): Must be transient (new instance per call) because
        it stores stateful buffers (_candles_1m, _buffer_15m). Sharing it across
        RealtimeServices causes data mixing between symbols (e.g., BTC data
        polluting ETH 15m candles).

        Returns:
            New DataAggregator instance
        """
        # SOTA: Return new instance every time (Transient Scope)
        instance = DataAggregator()
        self.logger.debug(f"Created new isolated DataAggregator instance: {id(instance)}")
        return instance

    def get_vwap_calculator(self) -> VWAPCalculator:
        """Get VWAPCalculator instance (singleton)."""
        if 'vwap_calculator' not in self._instances:
            self._instances['vwap_calculator'] = VWAPCalculator()
        return self._instances['vwap_calculator']

    def get_bollinger_calculator(self) -> BollingerCalculator:
        """Get BollingerCalculator instance (singleton)."""
        if 'bollinger_calculator' not in self._instances:
            self._instances['bollinger_calculator'] = BollingerCalculator()
        return self._instances['bollinger_calculator']

    def get_stoch_rsi_calculator(self) -> StochRSICalculator:
        """Get StochRSICalculator instance (singleton)."""
        if 'stoch_rsi_calculator' not in self._instances:
            self._instances['stoch_rsi_calculator'] = StochRSICalculator()
        return self._instances['stoch_rsi_calculator']

    def get_adx_calculator(self) -> ADXCalculator:
        """Get ADXCalculator instance (singleton)."""
        if 'adx_calculator' not in self._instances:
            self._instances['adx_calculator'] = ADXCalculator()
        return self._instances['adx_calculator']

    def get_atr_calculator(self) -> ATRCalculator:
        """Get ATRCalculator instance (singleton)."""
        if 'atr_calculator' not in self._instances:
            self._instances['atr_calculator'] = ATRCalculator()
        return self._instances['atr_calculator']

    def get_volume_spike_detector(self) -> VolumeSpikeDetector:
        """Get VolumeSpikeDetector instance (singleton)."""
        if 'volume_spike_detector' not in self._instances:
            self._instances['volume_spike_detector'] = VolumeSpikeDetector()
        return self._instances['volume_spike_detector']

    def get_swing_point_detector(self):
        """Get SwingPointDetector instance (singleton)."""
        if 'swing_point_detector' not in self._instances:
            from .indicators.swing_point_detector import SwingPointDetector
            self._instances['swing_point_detector'] = SwingPointDetector(lookback=5)
        return self._instances['swing_point_detector']

    def get_tp_calculator(self):
        """Get TPCalculator instance (singleton) with SwingPointDetector injected."""
        if 'tp_calculator' not in self._instances:
            from ..application.services.tp_calculator import TPCalculator
            swing_detector = self.get_swing_point_detector()
            self._instances['tp_calculator'] = TPCalculator(swing_detector=swing_detector)
        return self._instances['tp_calculator']

    # ==================== Volume Upgrade Plan (Expert Feedback) ====================

    def get_volume_profile_calculator(self):
        """
        Get VolumeProfileCalculator instance (singleton).

        SOTA: Volume Profile approximation from OHLC + VWAP data.
        Identifies POC, VAH, VAL for institutional trading zones.

        Returns:
            VolumeProfileCalculator for Volume Profile analysis
        """
        if 'volume_profile_calculator' not in self._instances:
            from .indicators.volume_profile_calculator import VolumeProfileCalculator

            self._instances['volume_profile_calculator'] = VolumeProfileCalculator(
                num_bins=50,
                value_area_pct=0.70,
                vwap_calculator=self.get_vwap_calculator()
            )
            self.logger.info("Created VolumeProfileCalculator (Volume Upgrade Phase 1)")

        return self._instances['volume_profile_calculator']

    def get_volume_delta_calculator(self):
        """
        Get VolumeDeltaCalculator instance (singleton).

        SOTA: Approximates buy/sell volume from candle structure.
        Includes divergence detection for reversal signals.

        Returns:
            VolumeDeltaCalculator for Order Flow approximation
        """
        if 'volume_delta_calculator' not in self._instances:
            from .indicators.volume_delta_calculator import VolumeDeltaCalculator

            self._instances['volume_delta_calculator'] = VolumeDeltaCalculator(
                divergence_lookback=14
            )
            self.logger.info("Created VolumeDeltaCalculator (Volume Upgrade Phase 2)")

        return self._instances['volume_delta_calculator']

    def get_liquidity_zone_detector(self):
        """
        Get LiquidityZoneDetector instance (singleton).

        SOTA: Detects SL clusters, TP zones, and breakout zones.
        Optimizes stop loss and take profit placement.

        Returns:
            LiquidityZoneDetector for risk management optimization
        """
        if 'liquidity_zone_detector' not in self._instances:
            from ..application.risk_management.liquidity_zone_detector import LiquidityZoneDetector

            self._instances['liquidity_zone_detector'] = LiquidityZoneDetector(
                atr_calculator=self.get_atr_calculator(),
                vwap_calculator=self.get_vwap_calculator(),
                swing_lookback=5,
                zone_atr_multiplier=0.5
            )
            self.logger.info("Created LiquidityZoneDetector (Volume Upgrade Phase 3)")

        return self._instances['liquidity_zone_detector']

    def get_regime_detector(self) -> RegimeDetector:
        """
        Get RegimeDetector instance (singleton).

        SOTA: Injects ADX threshold from StrategyConfig.

        Returns:
            RegimeDetector for Layer 0 market regime classification
        """
        if 'regime_detector' not in self._instances:
            config = self.get_config_instance()
            strategy_config = config.strategy

            self._instances['regime_detector'] = RegimeDetector(
                adx_trending_threshold=strategy_config.adx_trending_threshold
            )
            self.logger.debug(
                f"Created RegimeDetector with ADX threshold: {strategy_config.adx_trending_threshold}"
            )
        return self._instances['regime_detector']

    def get_sfp_detector(self) -> SFPDetector:
        """
        Get SFPDetector instance (singleton).

        SOTA: Phase 1 SFP Integration.
        """
        if 'sfp_detector' not in self._instances:
            self._instances['sfp_detector'] = SFPDetector()
            self.logger.info("Created SFPDetector")
        return self._instances['sfp_detector']

    def get_momentum_velocity_calculator(self) -> MomentumVelocityCalculator:
        """
        Get MomentumVelocityCalculator instance (singleton).

        SOTA: Phase 2 Momentum Velocity (FOMO Filter).
        """
        if 'momentum_velocity_calculator' not in self._instances:
            self._instances['momentum_velocity_calculator'] = MomentumVelocityCalculator()
            self.logger.info("Created MomentumVelocityCalculator")
        return self._instances['momentum_velocity_calculator']

    def get_order_block_detector(self):
        """Get OrderBlockDetector instance (singleton)."""
        if 'order_block_detector' not in self._instances:
            from .indicators.order_block_detector import OrderBlockDetector
            self._instances['order_block_detector'] = OrderBlockDetector()
        return self._instances['order_block_detector']

    def get_fvg_detector(self):
        """Get FVGDetector instance (singleton)."""
        if 'fvg_detector' not in self._instances:
            from .indicators.fvg_detector import FVGDetector
            self._instances['fvg_detector'] = FVGDetector()
        return self._instances['fvg_detector']

    def get_signal_generator(self, use_btc_filter: bool = False, use_adx_regime_filter: bool = False, use_htf_filter: bool = False,
                               use_adx_max_filter: bool = False, adx_max_threshold: float = 40.0,
                               use_bb_filter: bool = False, use_stochrsi_filter: bool = False,
                               sniper_lookback: int = 20, sniper_proximity: float = 0.015,
                               fix_vwap_scoring: bool = False, use_volume_confirm: bool = False,
                               use_bounce_confirm: bool = False, use_ema_regime_filter: bool = False,
                               use_atr_sl: bool = False, use_funding_filter: bool = False,
                               use_delta_divergence: bool = False, use_mtf_trend: bool = False,
                               mtf_ema_period: int = 50,
                               strategy_id: Optional[str] = None):
        """
        Get SignalGenerator instance with all dependencies (singleton).

        SOTA: Now injects StrategyConfig for centralized parameter management.
        SOTA (Jan 2026): Accepts use_btc_filter parameter for BTC trend filtering.
        INSTITUTIONAL (Feb 2026): Accepts use_adx_regime_filter for ADX regime filtering.

        Args:
            use_btc_filter: Enable BTC trend filter for altcoin signals
            use_adx_regime_filter: Enable ADX regime filter (ADX<20=block, 20-25=penalty)
            use_htf_filter: Enable HTF trend alignment filter (block counter-trend signals)

        Returns:
            SignalGenerator with injected calculators and config
        """
        cache_key = (
            'signal_generator',
            use_btc_filter,
            use_adx_regime_filter,
            use_htf_filter,
            use_adx_max_filter,
            round(adx_max_threshold, 6),
            use_bb_filter,
            use_stochrsi_filter,
            sniper_lookback,
            round(sniper_proximity, 6),
            fix_vwap_scoring,
            use_volume_confirm,
            use_bounce_confirm,
            use_ema_regime_filter,
            use_atr_sl,
            use_funding_filter,
            use_delta_divergence,
            use_mtf_trend,
            mtf_ema_period,
            strategy_id,
        )

        if cache_key not in self._instances:
            # Lazy import to avoid circular dependency
            from ..application.signals.signal_generator import SignalGenerator

            # SOTA: Get strategy config from centralized Config
            config = self.get_config_instance()
            strategy_config = config.strategy

            self._instances[cache_key] = SignalGenerator(
                vwap_calculator=self.get_vwap_calculator(),
                bollinger_calculator=self.get_bollinger_calculator(),
                stoch_rsi_calculator=self.get_stoch_rsi_calculator(),
                tp_calculator=self.get_tp_calculator(),  # SOTA: Inject TP calculator with Swing Detector
                smart_entry_calculator=SmartEntryCalculator(),
                volume_spike_detector=self.get_volume_spike_detector(),
                volume_delta_calculator=self.get_volume_delta_calculator(),
                liquidity_zone_detector=self.get_liquidity_zone_detector(),
                sfp_detector=self.get_sfp_detector(),
                momentum_velocity_calculator=self.get_momentum_velocity_calculator(),
                adx_calculator=self.get_adx_calculator(),
                atr_calculator=self.get_atr_calculator(),
                talib_calculator=self.get_indicator_calculator(),
                # SOTA: Inject RegimeDetector for Layer 0 filtering
                regime_detector=self.get_regime_detector(),
                # SOTA: Inject config-based parameters instead of hardcoded
                use_filters=True,
                strict_mode=strategy_config.strict_mode,
                use_regime_filter=strategy_config.use_regime_filter,
                strategy_config=strategy_config,  # Full config object
                # SOTA (Jan 2026): BTC Trend Filter
                use_btc_filter=use_btc_filter,
                # INSTITUTIONAL (Feb 2026): ADX Regime Filter
                use_adx_regime_filter=use_adx_regime_filter,
                # EXPERIMENTAL: HTF Trend Alignment Filter
                use_htf_filter=use_htf_filter,
                # Mean-reversion indicator filters
                use_adx_max_filter=use_adx_max_filter,
                adx_max_threshold=adx_max_threshold,
                use_bb_filter=use_bb_filter,
                use_stochrsi_filter=use_stochrsi_filter,
                sniper_lookback=sniper_lookback,
                sniper_proximity=sniper_proximity,
                # SOTA (Feb 2026): Signal quality improvement flags
                fix_vwap_scoring=fix_vwap_scoring,
                use_volume_confirm=use_volume_confirm,
                use_bounce_confirm=use_bounce_confirm,
                use_ema_regime_filter=use_ema_regime_filter,
                use_atr_sl=use_atr_sl,
                use_funding_filter=use_funding_filter,
                # Phase 1 Strategy Filters (Feb 2026)
                use_delta_divergence=use_delta_divergence,
                use_mtf_trend=use_mtf_trend,
                mtf_ema_period=mtf_ema_period,
                strategy_id=strategy_id,
            )
            self.logger.info(
                f"Created SignalGenerator with SOTA config: "
                f"strict_mode={strategy_config.strict_mode}, "
                f"regime_mode={strategy_config.regime_filter_mode}, "
                f"btc_filter={use_btc_filter}, "
                f"adx_regime_filter={use_adx_regime_filter}, "
                f"htf_filter={use_htf_filter}, "
                f"funding_filter={use_funding_filter}, "
                f"delta_divergence={use_delta_divergence}, "
                f"mtf_trend={use_mtf_trend}, "
                f"strategy_id={strategy_id or 'default'}"
            )

        return self._instances[cache_key]

    def get_paper_trading_service(self):
        """
        Get PaperTradingService instance (singleton).

        SOTA FIX: This was MISSING - signals were generated but never
        reached trade execution because paper_service was not injected.

        Returns:
            PaperTradingService for paper trading execution
        """
        if 'paper_trading_service' not in self._instances:
            # Lazy import to avoid circular dependency
            from ..application.services.paper_trading_service import PaperTradingService

            order_repository = self.get_order_repository()
            # SOTA FIX: Inject MarketDataRepository for multi-symbol pricing
            market_data_repository = self.get_market_data_repository()

            self._instances['paper_trading_service'] = PaperTradingService(
                repository=order_repository,
                market_data_repository=market_data_repository
            )
            self.logger.info("Created PaperTradingService with order repository")

        return self._instances['paper_trading_service']

    # NOTE: get_signal_lifecycle_service() defined below (~line 918) — env-aware version
    # Removed duplicate here (was dead code — Python uses last definition)

    def get_signal_confirmation_service(self):
        """
        Get SignalConfirmationService instance (singleton).

        SOTA FIX: Prevents whipsaw by requiring 2 consecutive signals
        in the same direction before execution.

        Returns:
            SignalConfirmationService for signal confirmation
        """
        if 'signal_confirmation_service' not in self._instances:
            # Lazy import to avoid circular dependency
            from ..application.services.signal_confirmation_service import SignalConfirmationService

            # Get config for confirmation settings
            config = self.get_config_instance()
            strategy_config = config.strategy

            # Default: 2 confirmations, 3 minute timeout
            # SOTA: Prevents whipsaw by requiring consecutive signals
            min_confirmations = 2
            max_wait_seconds = 180

            self._instances['signal_confirmation_service'] = SignalConfirmationService(
                min_confirmations=min_confirmations,
                max_wait_seconds=max_wait_seconds
            )
            self.logger.info(
                f"Created SignalConfirmationService: "
                f"min_confirmations={min_confirmations}, max_wait={max_wait_seconds}s"
            )

        return self._instances['signal_confirmation_service']

    def get_trend_filter(self) -> TrendFilter:
        """Get TrendFilter instance (singleton)."""
        if 'trend_filter' not in self._instances:
            self._instances['trend_filter'] = TrendFilter(
                ema_period=PRODUCTION_MTF_EMA_PERIOD
            )
        return self._instances['trend_filter']

    def get_market_intelligence_service(self):
        """
        Get MarketIntelligenceService instance (singleton).

        SOTA: Centralized intelligence provider.
        """
        if 'market_intelligence_service' not in self._instances:
            from .exchange.market_intelligence_service import MarketIntelligenceService
            service = MarketIntelligenceService()
            if not service.load_from_file():
                self.logger.info("📊 Intelligence file not found — scheduler will fetch from Binance on startup")
            self._instances['market_intelligence_service'] = service
            self.logger.debug("Created MarketIntelligenceService")

        return self._instances['market_intelligence_service']

    def get_shark_tank_coordinator(self):
        """
        Get SharkTankCoordinator instance (singleton).

        SOTA: Central coordinator for multi-symbol signal batching.
        Matches backtest Shark Tank behavior:
        - Collects signals from all symbols within batch window
        - Ranks by confidence score
        - Executes best N based on max_positions

        Returns:
            SharkTankCoordinator for batch signal processing
        """
        if 'shark_tank_coordinator' not in self._instances:
            from ..application.services.shark_tank_coordinator import SharkTankCoordinator

            # Get config for max positions
            paper_service = self.get_paper_trading_service()
            max_positions = paper_service.MAX_POSITIONS if paper_service else 3

            coordinator = SharkTankCoordinator(
                max_positions=max_positions,
                batch_interval_seconds=5.0  # 5 seconds batch window
            )

            # SOTA (Feb 2026): Wire Symbol Quality Filter
            coordinator.symbol_quality_filter = self.get_symbol_quality_filter()

            # SOTA (Feb 9, 2026): Wire Circuit Breaker for schedule + per-symbol blocking
            coordinator.circuit_breaker = self.get_circuit_breaker()

            self._instances['shark_tank_coordinator'] = coordinator
            self.logger.info(
                f"🦈 Created SharkTankCoordinator: max_positions={max_positions}, "
                f"quality_filter=wired, circuit_breaker=wired"
            )

        return self._instances['shark_tank_coordinator']

    def get_signal_lifecycle_service(self):
        """
        Get SignalLifecycleService instance (singleton per environment).

        SOTA: Signal persistence service for tracking signal lifecycle.
        Uses ENV-aware database path.

        Returns:
            SignalLifecycleService for signal persistence
        """
        # SOTA: ENV-aware caching - different instance per environment
        key = f'signal_lifecycle_service_{self._env}'

        if key not in self._instances:
            from .repositories.sqlite_signal_repository import SQLiteSignalRepository
            from ..application.services.signal_lifecycle_service import SignalLifecycleService

            # Use environment-aware DB path
            db_path = self._trading_db_path
            self.logger.info(f"📁 Creating SignalLifecycleService for {self._env}: {db_path}")

            # Create repository with correct DB path
            signal_repo = SQLiteSignalRepository(db_path=db_path)

            # Create lifecycle service
            self._instances[key] = SignalLifecycleService(signal_repository=signal_repo)
            self.logger.info(f"✅ SignalLifecycleService created for {self._env}")

        return self._instances[key]

    def get_order_repository(self, env: str = None):
        """
        Get SQLiteOrderRepository instance (singleton per environment).

        SOTA (Jan 2026): Used for persisting live position TP/SL data.

        Args:
            env: Environment name (paper/testnet/live). Defaults to current ENV.

        Returns:
            SQLiteOrderRepository instance
        """
        if env is None:
            env = self._env

        key = f'order_repository_{env}'
        if key not in self._instances:
            db_path = get_trading_db_path(env)

            # Ensure directory exists
            db_path.parent.mkdir(parents=True, exist_ok=True)

            self.logger.info(f"📁 Creating SQLiteOrderRepository for {env}: {db_path}")
            self._instances[key] = SQLiteOrderRepository(db_path=str(db_path))

        return self._instances[key]


    def get_symbol_quality_filter(self, market_mode=None):
        """
        Get SymbolQualityFilter instance (singleton).

        SOTA (Feb 2026): Filters out exotic/meme/low-liquidity symbols.

        Returns:
            SymbolQualityFilter instance
        """
        key_suffix = market_mode.value if market_mode is not None else "default"
        cache_key = f"symbol_quality_filter_{key_suffix}"

        if cache_key not in self._instances:
            from ..application.services.symbol_quality_filter import SymbolQualityFilter
            from .data.historical_data_loader import HistoricalDataLoader
            from .data.historical_volume_service import HistoricalVolumeService

            if market_mode is None:
                try:
                    binance_client = self.get_rest_client()
                except Exception:
                    binance_client = None
            else:
                binance_client = BinanceRestClient(market_mode=market_mode)

            history_provider = HistoricalDataLoader(
                rest_client=binance_client,
                market_mode=market_mode,
            )
            historical_volume_provider = HistoricalVolumeService(
                market_mode=market_mode or MarketMode.FUTURES,
            )

            self._instances[cache_key] = SymbolQualityFilter(
                min_24h_volume_usd=50_000_000.0,
                max_spread_pct=0.3,
                binance_client=binance_client,
                historical_volume_provider=historical_volume_provider,
                settings_repo=self.get_order_repository(),
                history_provider=history_provider,
            )
            self.logger.info(
                "Created SymbolQualityFilter: min_vol=$50M, min_history=30d/1m, blacklist=DB-persisted"
            )

        return self._instances[cache_key]

    def get_regime_state_service(self, market_mode=None):
        """
        Get observe-only regime state service (singleton per market mode).

        This mirrors the current research router without changing live execution.
        """
        mode = market_mode or MarketMode.FUTURES
        cache_key = f"regime_state_service_{mode.value}"

        if cache_key not in self._instances:
            from ..application.services.regime_state_service import RegimeStateService
            from .data.historical_data_loader import HistoricalDataLoader
            from .data.historical_volume_service import HistoricalVolumeService

            self._instances[cache_key] = RegimeStateService(
                loader=HistoricalDataLoader(market_mode=mode),
                volume_service=HistoricalVolumeService(market_mode=mode),
                quality_filter=self.get_symbol_quality_filter(market_mode=mode),
                trend_filter=TrendFilter(ema_period=20),
                regime_detector=RegimeDetector(adx_trending_threshold=25.0),
                ranked_universe_top=40,
                cache_ttl_seconds=60,
            )
            self.logger.info(
                "Created RegimeStateService: observe_only=True, router=v6, ranked_top=40"
            )

        return self._instances[cache_key]

    def get_circuit_breaker(self):
        """
        Get CircuitBreaker instance (singleton).

        DATA-DRIVEN (Feb 7, 2026):
        Backtest shows per-symbol CB HURTS performance (-36% return).
        Solution: Set max_consecutive_losses=100 (effectively disabled per-symbol block)
        but keep global drawdown protection at 20% for catastrophic safety.

        Returns:
            CircuitBreaker instance
        """
        if 'circuit_breaker' not in self._instances:
            from ..application.risk_management.circuit_breaker import CircuitBreaker

            # SOTA (Feb 9, 2026): Per-symbol CB + Trading Schedule ENABLED
            # LIVE data shows 50% WR (vs 78.5% backtest) due to revenge-trading on losing symbols.
            # Two new layers: (1) Per-symbol direction cooldown, (2) Dead zone time windows.
            # v6.4.0: Per-symbol CB DISABLED — statistical research proves CB
            # blocks profitable recovery trades (serial correlation r=-0.17, p=0.04).
            # After a loss, next trade is MORE likely to win → CB is counterproductive.
            # Keep ONLY: global 30% DD halt + DZ 06-08+19-21
            self._instances['circuit_breaker'] = CircuitBreaker(
                max_consecutive_losses=999,          # Effectively disabled (never triggers)
                cooldown_hours=0.0,                  # No cooldown
                max_daily_drawdown_pct=0.30,         # Global: halt at 30% DD — raised for $11 balance (25.9% MaxDD expected)
                daily_symbol_loss_limit=0,           # DISABLED
                blocked_windows=get_production_blocked_windows(),
                blocked_windows_utc_offset=7,       # UTC+7 (Vietnam timezone)
                # F1: Escalating CB — DISABLED (blocks recovery trades)
                use_escalating_cooldown=False,
                escalating_schedule_str="2:0.5,3:2,4:8,5:24",
                # F2: Direction Block — DISABLED (research shows no benefit with correct BT)
                use_direction_block=False,
                direction_block_threshold=4,
                direction_block_window_hours=2.0,
                direction_block_cooldown_hours=4.0,
            )
            dz_str = ", ".join(f"{w['start']}-{w['end']}" for w in self._instances['circuit_breaker'].blocked_windows)
            self.logger.info(
                f"Created CircuitBreaker: per-symbol=OFF, daily_limit=OFF, "
                f"dead_zones=[{dz_str} UTC+7], global_dd=30%, "
                f"escalating_cb=OFF, direction_block=OFF"
            )

        return self._instances['circuit_breaker']

    def get_live_trading_service(self):
        """
        Get LiveTradingService instance (singleton per environment).

        SOTA FIX: ENV-aware caching - different instance per environment.
        Ensures correct Binance client (TESTNET vs LIVE) is used.

        Returns:
            LiveTradingService for real trading execution
        """
        # Lazy import to avoid circular dependency
        from ..application.services.live_trading_service import LiveTradingService, TradingMode
        import os
        # Note: load_dotenv removed - config loaded centrally via config_loader at startup

        # SOTA: Use ENV variable (already loaded by config_loader)
        env = os.getenv("ENV", "paper").lower().strip()

        # SOTA FIX: Cache key includes ENV to ensure correct mode per environment
        cache_key = f'live_trading_service_{env}'

        if cache_key not in self._instances:
            # Debug logging
            self.logger.info(f"🔧 ENV={env}")

            # Map ENV to TradingMode
            if env == "live":
                mode = TradingMode.LIVE
            elif env == "testnet":
                mode = TradingMode.TESTNET
            else:
                mode = TradingMode.PAPER

            # SOTA (Jan 2026): Load auto_execute from settings DB for LIVE mode
            # This ensures toggle persists across restarts
            settings_repo = self.get_order_repository(env)
            enable_trading_default = (env == "testnet")  # Testnet: always on, Live: check DB

            if env == "live" and settings_repo:
                try:
                    settings = settings_repo.get_all_settings()
                    ae_val = settings.get('auto_execute', True)  # Default True for Live
                    enable_trading_default = str(ae_val).lower() == 'true' if isinstance(ae_val, str) else bool(ae_val)
                    self.logger.info(f"📊 Loaded auto_execute from DB: {enable_trading_default}")
                except Exception as e:
                    self.logger.warning(f"⚠️ Failed to load auto_execute: {e}")

            service = LiveTradingService(
                mode=mode,
                enable_trading=enable_trading_default,
                intelligence_service=self.get_market_intelligence_service(),
                # SOTA (Jan 2026): Inject settings_repo for risk/max_pos/leverage sync
                settings_repo=settings_repo,
                # SOTA (Jan 2026): Inject order_repo for live position TP/SL persistence
                order_repo=settings_repo,
                # SOTA SYNC (Jan 2026): MAX SL Validation - Reject signals with SL > 1.0%
                # Matches optimization: --max-sl-validation --max-sl-pct 1.0
                use_max_sl_validation=(
                    PRODUCTION_USE_MAX_SL_VALIDATION and mode in (TradingMode.LIVE, TradingMode.TESTNET)
                ),
                max_sl_pct=1.2,  # 1.2% max SL distance — v6.5.0: wider SL unlocks +75% more trades
                # SOTA (Jan 2026): Inject Telegram Service
                telegram_service=self.get_telegram_service()
            )

            # SOTA (Feb 2026): Wire Circuit Breaker for risk management
            service.circuit_breaker = self.get_circuit_breaker()

            # v6.3.0: Wire Analytics (fire-and-forget, passive)
            try:
                service._analytics_collector = self.get_binance_trade_collector()
                service._analytics_report_service = self.get_analytics_report_service()
                self.logger.info("📊 Analytics wired to LiveTradingService")
            except Exception as e:
                self.logger.warning(f"⚠️ Analytics wiring failed (non-critical): {e}")

            self._instances[cache_key] = service
            self.logger.info(
                f"Created LiveTradingService for {env}: mode={mode.value}, enabled={enable_trading_default}, CB=wired"
            )

        return self._instances[cache_key]


    def get_telegram_service(self):
        """
        Get TelegramService instance (singleton).
        """
        if 'telegram_service' not in self._instances:
            from src.infrastructure.notifications.telegram_service import TelegramService
            config = self.get_config_instance()

            # Helper to get env var if not in config object
            token = os.getenv("TELEGRAM_BOT_TOKEN")
            chat_id = os.getenv("TELEGRAM_CHAT_ID")
            enabled = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"

            self._instances['telegram_service'] = TelegramService(
                bot_token=token,
                chat_id=chat_id,
                enabled=enabled
            )
            self.logger.info(f"Created TelegramService (Enabled: {enabled})")

        return self._instances['telegram_service']


    def get_realtime_service(self, symbol: str = "btcusdt"):
        """
        Get RealtimeService instance with all dependencies (singleton per symbol).

        NOTE: Import RealtimeService here to avoid circular import.

        Args:
            symbol: Trading symbol

        Returns:
            RealtimeService with all dependencies injected
        """
        # Lazy import to avoid circular dependency
        from ..application.services.realtime_service import RealtimeService

        key = f'realtime_service_{symbol}'
        if key not in self._instances:
            self._instances[key] = RealtimeService(
                symbol=symbol,
                websocket_client=self.get_websocket_client(),
                rest_client=self.get_rest_client(),
                aggregator=self.get_data_aggregator(),
                talib_calculator=self.get_indicator_calculator(),
                vwap_calculator=self.get_vwap_calculator(),
                bollinger_calculator=self.get_bollinger_calculator(),
                stoch_rsi_calculator=self.get_stoch_rsi_calculator(),
                adx_calculator=self.get_adx_calculator(),
                atr_calculator=self.get_atr_calculator(),
                volume_spike_detector=self.get_volume_spike_detector(),
                signal_generator=self.get_signal_generator(
                    use_delta_divergence=PRODUCTION_USE_DELTA_DIVERGENCE,
                    use_mtf_trend=PRODUCTION_USE_MTF_TREND,
                    mtf_ema_period=PRODUCTION_MTF_EMA_PERIOD,
                    sniper_lookback=15,      # v6.5.1: LB15 (was 20) — +59% PnL, +3.5pp WR
                    sniper_proximity=0.025,  # v6.5.1: P2.5 (was 2.0) — PF 1.92, MaxDD -8.5%
                ),
                # SOTA FIX: Inject market data repository for candle persistence
                market_data_repository=self.get_market_data_repository(),
                # CRITICAL FIX: Inject paper_service for trade execution!
                paper_service=self.get_paper_trading_service(),
                # SOTA FIX: Inject lifecycle_service for signal persistence!
                lifecycle_service=self.get_signal_lifecycle_service(),
                # SOTA FIX: Inject trend_filter for HTF Confluence (Phase 12)
                trend_filter=self.get_trend_filter(),
                # SIGNAL CONFIRMATION: Disabled by default to match Backtest behavior!
                # Backtest does NOT use confirmation (signals execute immediately).
                # To enable: change None to self.get_signal_confirmation_service()
                signal_confirmation_service=None,  # OFF = match backtest
                # LIVE TRADING: Inject live_trading_service for real order execution!
                live_trading_service=self.get_live_trading_service(),
                intelligence_service=self.get_market_intelligence_service(),
                # SHARK TANK: Inject coordinator for batch signal ranking!
                shark_tank_coordinator=self.get_shark_tank_coordinator(),
            )
            self.logger.info(f"✅ Created RealtimeService for {symbol} with all services injected!")

        return self._instances[key]

    def cleanup(self):
        """
        Cleanup resources.

        Should be called when shutting down the application.
        """
        # Close BinanceClient session if exists
        if 'binance_client' in self._instances:
            try:
                self._instances['binance_client'].close()
                self.logger.debug("Closed BinanceClient")
            except Exception as e:
                self.logger.warning(f"Error closing BinanceClient: {e}")

        # Stop UserDataStream if exists (async cleanup handled separately)
        if 'user_data_stream' in self._instances:
            self.logger.debug("UserDataStream cleanup requested - call stop() explicitly for async cleanup")

        # Clear all instances
        self._instances.clear()
        self.logger.info("DI Container cleaned up")

    def get_user_data_stream(self):
        """
        Get UserDataStreamService instance (singleton per environment).

        SOTA: Real-time balance/position updates via Binance WebSocket.
        Only available in TESTNET or LIVE modes.

        Returns:
            UserDataStreamService or None if paper mode
        """
        if self._env == "paper":
            self.logger.debug("UserDataStream not available in paper mode")
            return None

        if 'user_data_stream' not in self._instances:
            from .api.user_data_stream import UserDataStreamService

            use_testnet = self._env == "testnet"

            # SOTA FIX v3 (Jan 2026): Wire order update callback to LiveTradingService
            # This enables real-time cache sync, eliminating API calls in get_portfolio()
            def on_order_update_handler(order_data):
                """Update LiveTradingService local cache when order status changes."""
                try:
                    live_service = self.get_live_trading_service()
                    if hasattr(live_service, 'update_cached_order'):
                        is_closed = order_data.get('_is_closed', False)
                        live_service.update_cached_order(order_data, is_closed=is_closed)
                except Exception as e:
                    self.logger.warning(f"Failed to update order cache: {e}")

            # SOTA: Position update callback
            def on_position_update_handler(positions):
                """Refresh LiveTradingService position cache when positions change."""
                try:
                    live_service = self.get_live_trading_service()
                    if hasattr(live_service, 'refresh_cached_positions'):
                        live_service.refresh_cached_positions()
                except Exception as e:
                    self.logger.warning(f"Failed to refresh position cache: {e}")

            self._instances['user_data_stream'] = UserDataStreamService(
                use_testnet=use_testnet,
                on_order_update=on_order_update_handler,
                on_position_update=on_position_update_handler
            )
            self.logger.info(f"Created UserDataStreamService for {self._env} with cache sync callbacks")

        return self._instances['user_data_stream']

    def get_reconciliation_service(self) -> ReconciliationService:
        """
        Get ReconciliationService instance (singleton).

        SOTA (Feb 2026): Periodic sync of local state with exchange.

        Returns:
            ReconciliationService instance
        """
        if 'reconciliation_service' not in self._instances:
            live_service = self.get_live_trading_service()
            position_monitor = getattr(live_service, 'position_monitor', None)
            telegram = self.get_telegram_service() if hasattr(self, 'get_telegram_service') else None
            async_client = getattr(live_service, 'async_client', None)

            self._instances['reconciliation_service'] = ReconciliationService(
                exchange_client=async_client,
                position_monitor=position_monitor,
                live_trading_service=live_service,
                telegram_service=telegram,
                interval_seconds=60,
                enabled=True
            )
            self.logger.info("Created ReconciliationService for position sync")

        return self._instances['reconciliation_service']

    def get_profit_chart_generator(self) -> ProfitChartGenerator:
        """
        Get ProfitChartGenerator instance (singleton).

        SOTA (Feb 2026): Generates profit charts every 5 hours.

        Returns:
            ProfitChartGenerator instance
        """
        if 'profit_chart_generator' not in self._instances:
            order_repo = self.get_order_repository()
            telegram = self.get_telegram_service() if hasattr(self, 'get_telegram_service') else None

            self._instances['profit_chart_generator'] = ProfitChartGenerator(
                order_repo=order_repo,
                telegram_service=telegram,
                interval_hours=5.0,
                output_dir="data/charts",
                enabled=True
            )
            self.logger.info("Created ProfitChartGenerator for equity curve charts")

        return self._instances['profit_chart_generator']

    # ===================================================================
    # v6.3.0: Analytics Services
    # ===================================================================

    def get_analytics_repository(self):
        """Get AnalyticsRepository (singleton, same DB as order repo)."""
        if 'analytics_repository' not in self._instances:
            from .persistence.analytics_repository import AnalyticsRepository
            self._instances['analytics_repository'] = AnalyticsRepository(
                db_path=self._trading_db_path
            )
            self.logger.info("Created AnalyticsRepository")
        return self._instances['analytics_repository']

    def get_binance_trade_collector(self):
        """Get BinanceTradeCollector (singleton)."""
        if 'binance_trade_collector' not in self._instances:
            from ..application.analytics.binance_trade_collector import BinanceTradeCollector
            self._instances['binance_trade_collector'] = BinanceTradeCollector(
                analytics_repo=self.get_analytics_repository()
            )
            self.logger.info("Created BinanceTradeCollector")
        return self._instances['binance_trade_collector']

    def get_analytics_engine(self):
        """Get AnalyticsEngine (singleton)."""
        if 'analytics_engine' not in self._instances:
            from ..application.analytics.analytics_engine import AnalyticsEngine
            self._instances['analytics_engine'] = AnalyticsEngine(
                analytics_repo=self.get_analytics_repository()
            )
            self.logger.info("Created AnalyticsEngine")
        return self._instances['analytics_engine']

    def get_session_analyzer(self):
        """Get SessionAnalyzer (singleton)."""
        if 'session_analyzer' not in self._instances:
            from ..application.analytics.session_analyzer import SessionAnalyzer
            self._instances['session_analyzer'] = SessionAnalyzer(
                analytics_repo=self.get_analytics_repository()
            )
            self.logger.info("Created SessionAnalyzer")
        return self._instances['session_analyzer']

    def get_symbol_alpha_tracker(self):
        """Get SymbolAlphaTracker (singleton)."""
        if 'symbol_alpha_tracker' not in self._instances:
            from ..application.analytics.symbol_alpha_tracker import SymbolAlphaTracker
            self._instances['symbol_alpha_tracker'] = SymbolAlphaTracker(
                analytics_repo=self.get_analytics_repository()
            )
            self.logger.info("Created SymbolAlphaTracker")
        return self._instances['symbol_alpha_tracker']

    def get_direction_analyzer(self):
        """Get DirectionAnalyzer (singleton)."""
        if 'direction_analyzer' not in self._instances:
            from ..application.analytics.direction_analyzer import DirectionAnalyzer
            self._instances['direction_analyzer'] = DirectionAnalyzer(
                analytics_repo=self.get_analytics_repository()
            )
            self.logger.info("Created DirectionAnalyzer")
        return self._instances['direction_analyzer']

    def get_analytics_chart_generator(self):
        """Get AnalyticsChartGenerator (singleton)."""
        if 'analytics_chart_generator' not in self._instances:
            from .monitoring.analytics_chart_generator import AnalyticsChartGenerator
            self._instances['analytics_chart_generator'] = AnalyticsChartGenerator()
            self.logger.info("Created AnalyticsChartGenerator")
        return self._instances['analytics_chart_generator']

    def get_analytics_report_service(self):
        """Get AnalyticsReportService (singleton)."""
        if 'analytics_report_service' not in self._instances:
            from ..application.analytics.analytics_report_service import AnalyticsReportService
            self._instances['analytics_report_service'] = AnalyticsReportService(
                collector=self.get_binance_trade_collector(),
                engine=self.get_analytics_engine(),
                session_analyzer=self.get_session_analyzer(),
                symbol_tracker=self.get_symbol_alpha_tracker(),
                direction_analyzer=self.get_direction_analyzer(),
                chart_generator=self.get_analytics_chart_generator(),
                analytics_repo=self.get_analytics_repository(),
                telegram_service=self.get_telegram_service(),
            )
            self.logger.info("Created AnalyticsReportService")
        return self._instances['analytics_report_service']

    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.cleanup()
