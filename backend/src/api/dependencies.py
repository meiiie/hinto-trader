from functools import lru_cache  # Used by get_container (DIContainer is ENV-aware internally)
from src.infrastructure.di_container import DIContainer
from src.application.services.realtime_service import RealtimeService
from src.application.services.paper_trading_service import PaperTradingService
from src.application.services.signal_lifecycle_service import SignalLifecycleService
from src.infrastructure.persistence.sqlite_order_repository import SQLiteOrderRepository
from src.infrastructure.persistence.sqlite_market_data_repository import SQLiteMarketDataRepository
from src.infrastructure.repositories.sqlite_signal_repository import SQLiteSignalRepository

# SOTA: Import environment-aware settings
import os
import logging

logger = logging.getLogger(__name__)


def _get_trading_db_path() -> str:
    """
    Get environment-aware trading database path.

    SOTA: Database isolation per environment.
    Note: Config loaded centrally via config_loader at startup.
    """
    # Note: load_dotenv removed - config loaded centrally

    env = os.getenv("ENV", "paper").lower().strip()
    db_path = f"data/{env}/trading_system.db"

    # Ensure directory exists
    from pathlib import Path
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"[DB] Using path: {db_path} (ENV={env})")
    return db_path


# SOTA FIX: Replace @lru_cache with ENV-aware caching
# @lru_cache ignores ENV changes - must use dict keyed by ENV
_cached_instances: dict = {}


def _get_current_env() -> str:
    """Get current environment (config already loaded by config_loader)."""
    # Note: load_dotenv removed - config loaded centrally
    return os.getenv("ENV", "paper").lower().strip()


@lru_cache()
def get_container() -> DIContainer:
    """Get singleton instance of DI Container."""
    return DIContainer()


def reset_all_caches():
    """
    SOTA (Jan 2026): Reset ALL cached singletons for fresh initialization.

    Call at backend startup to ensure:
    - Fresh API credentials are loaded
    - No stale sessions from previous runs
    - Clean state after configuration changes

    Critical for:
    - IP whitelist changes on Binance
    - API key rotation
    - Environment switching (paper → testnet → live)

    Usage in main.py lifespan:
        from src.api.dependencies import reset_all_caches
        reset_all_caches()
    """
    global _cached_instances

    logger.info("🔄 Resetting ALL cached singletons...")

    # 1. Clear dependencies module cache
    _cached_instances.clear()

    # 2. Clear lru_cache decorators
    get_container.cache_clear()
    get_realtime_service.cache_clear()
    get_market_data_repository.cache_clear()

    # 3. Clear DI Container internal caches (if already created)
    try:
        container = DIContainer()
        if hasattr(container, '_env_instances'):
            # Clear binance client entries to force recreation
            for env_cache in container._env_instances.values():
                keys_to_remove = [
                    k for k in env_cache.keys()
                    if 'binance' in k.lower() or 'live_trading' in k.lower()
                ]
                for k in keys_to_remove:
                    del env_cache[k]
                    logger.info(f"   Cleared cached: {k}")
    except Exception as e:
        logger.warning(f"DI Container reset warning: {e}")

    logger.info("✅ All caches reset - fresh initialization pending")


def get_order_repository() -> SQLiteOrderRepository:
    """
    Get singleton instance of SQLiteOrderRepository.

    SOTA FIX: ENV-aware caching - different instance per environment.
    """
    env = _get_current_env()
    cache_key = f"order_repository_{env}"

    if cache_key not in _cached_instances:
        db_path = _get_trading_db_path()
        logger.info(f"📁 Creating Order Repository for {env}: {db_path}")
        _cached_instances[cache_key] = SQLiteOrderRepository(db_path=db_path)

    return _cached_instances[cache_key]


def get_signal_repository() -> SQLiteSignalRepository:
    """
    Get singleton instance of SQLiteSignalRepository.

    SOTA FIX: ENV-aware caching - different instance per environment.
    """
    env = _get_current_env()
    cache_key = f"signal_repository_{env}"

    if cache_key not in _cached_instances:
        db_path = _get_trading_db_path()
        logger.info(f"📁 Creating Signal Repository for {env}: {db_path}")
        _cached_instances[cache_key] = SQLiteSignalRepository(db_path=db_path)

    return _cached_instances[cache_key]


def get_signal_lifecycle_service() -> SignalLifecycleService:
    """
    Get singleton instance of SignalLifecycleService.

    SOTA FIX: ENV-aware caching.
    """
    env = _get_current_env()
    cache_key = f"signal_lifecycle_{env}"

    if cache_key not in _cached_instances:
        repo = get_signal_repository()
        logger.info(f"📁 Creating SignalLifecycleService for {env}")
        _cached_instances[cache_key] = SignalLifecycleService(signal_repository=repo)

    return _cached_instances[cache_key]


def get_paper_trading_service() -> PaperTradingService:
    """
    Get singleton instance of PaperTradingService.

    SOTA FIX: ENV-aware caching - different instance per environment.
    Fixes bug where @lru_cache ignored ENV changes during mode switching.
    """
    env = _get_current_env()
    cache_key = f"paper_trading_service_{env}"

    if cache_key not in _cached_instances:
        repo = get_order_repository()
        market_data_repo = get_market_data_repository()
        logger.info(f"📁 Creating PaperTradingService for {env}")
        _cached_instances[cache_key] = PaperTradingService(
            repository=repo,
            market_data_repository=market_data_repo
        )

    return _cached_instances[cache_key]


def get_realtime_service_for_symbol(symbol: str = 'btcusdt') -> RealtimeService:
    """
    Get RealtimeService for a specific symbol.

    SOTA Multi-Token: Returns service for the requested symbol.
    """
    container = get_container()
    return container.get_realtime_service(symbol=symbol.lower())


@lru_cache()
def get_realtime_service() -> RealtimeService:
    """
    Get default RealtimeService (BTCUSDT).
    DEPRECATED: Use get_realtime_service_for_symbol for multi-token support.
    """
    container = get_container()
    return container.get_realtime_service(symbol='btcusdt')


@lru_cache()
def get_market_data_repository() -> SQLiteMarketDataRepository:
    """
    SOTA Phase 3: Get MarketDataRepository for hybrid data source.
    SQLite first, Binance fallback.
    """
    container = get_container()
    return container.get_market_data_repository()


def get_live_trading_service():
    """
    Get LiveTradingService singleton from DI container.

    SOTA: Mode-aware trading - same instance used across the system.
    """
    container = get_container()
    return container.get_live_trading_service()


def get_trading_mode() -> str:
    """
    Get current trading mode: 'LIVE', 'TESTNET', or 'PAPER'.

    SOTA: Uses ENV variable for mode determination.
    - ENV=live: Returns 'LIVE' (real Binance)
    - ENV=testnet: Returns 'TESTNET' (Binance testnet)
    - ENV=paper: Returns 'PAPER' (local SQLite)
    """
    env = os.getenv("ENV", "paper").lower()

    if env == "live":
        return "LIVE"
    elif env == "testnet":
        return "TESTNET"
    else:
        return "PAPER"


from src.infrastructure.notifications.telegram_service import TelegramService
from src.config_loader import get_config

@lru_cache()
def get_telegram_service() -> TelegramService:
    """
    Get singleton instance of TelegramService (SOTA Jan 2026).
    """
    config = get_config()
    service = TelegramService(
        bot_token=config.telegram_token,
        chat_id=config.telegram_chat_id,
        enabled=config.telegram_enabled
    )
    return service
