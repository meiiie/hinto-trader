"""
SettingsProvider - centralized runtime configuration service.

Values are read from SQLite on demand so live/testnet/paper UIs can reflect
the same source of truth.
"""

import logging
import time
from typing import Any, Dict, List, Optional

from src.trading_contract import (
    PRODUCTION_LEVERAGE,
    PRODUCTION_LIMIT_CHASE_TIMEOUT_SECONDS,
    PRODUCTION_MAX_POSITIONS,
    PRODUCTION_ORDER_TTL_MINUTES,
    PRODUCTION_ORDER_TYPE,
    PRODUCTION_RISK_PER_TRADE,
)

logger = logging.getLogger(__name__)


class SettingsProvider:
    """Centralized Settings Provider."""

    DEFAULTS = {
        "leverage": PRODUCTION_LEVERAGE,
        "max_positions": PRODUCTION_MAX_POSITIONS,
        "ttl_minutes": PRODUCTION_ORDER_TTL_MINUTES,
        "risk_per_trade": PRODUCTION_RISK_PER_TRADE,
        "max_order_value": 50000,
        "enable_recycling": False,
        "auto_execute": True,
        "order_type": PRODUCTION_ORDER_TYPE,
        "limit_chase_timeout_seconds": PRODUCTION_LIMIT_CHASE_TIMEOUT_SECONDS,
    }

    CACHE_TTL_SECONDS = 5

    _instance: Optional["SettingsProvider"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, order_repository=None):
        if self._initialized:
            if order_repository is not None:
                self._repo = order_repository
            return

        self._initialized = True
        self._repo = order_repository
        self._cache: Dict[str, Any] = {}
        self._cache_time: float = 0
        logger.info("SettingsProvider initialized")

    def _get_all_settings(self) -> Dict[str, Any]:
        """Get all settings from database with a short TTL cache."""
        now = time.time()

        if self._cache and (now - self._cache_time) < self.CACHE_TTL_SECONDS:
            return self._cache

        if self._repo:
            try:
                self._cache = self._repo.get_all_settings()
                self._cache_time = now
            except Exception as exc:
                logger.warning(f"Failed to load settings from DB: {exc}")
                self._cache = {}
        else:
            self._cache = {}

        return self._cache

    @staticmethod
    def _as_bool(value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() == "true"
        return bool(value)

    @staticmethod
    def _get_first(settings: Dict[str, Any], *keys: str, default: Any) -> Any:
        for key in keys:
            if key in settings and settings[key] not in (None, ""):
                return settings[key]
        return default

    def invalidate_cache(self) -> None:
        """Force cache invalidation after settings updates."""
        self._cache = {}
        self._cache_time = 0
        logger.debug("Settings cache invalidated")

    def get_leverage(self) -> int:
        settings = self._get_all_settings()
        return int(settings.get("leverage", self.DEFAULTS["leverage"]))

    def get_max_positions(self) -> int:
        settings = self._get_all_settings()
        return int(settings.get("max_positions", self.DEFAULTS["max_positions"]))

    def get_ttl_minutes(self) -> int:
        settings = self._get_all_settings()
        value = self._get_first(
            settings,
            "execution_ttl_minutes",
            "ttl_minutes",
            default=self.DEFAULTS["ttl_minutes"],
        )
        return int(value)

    def get_risk_per_trade(self) -> float:
        settings = self._get_all_settings()
        value = self._get_first(
            settings,
            "risk_per_trade",
            "risk_percent",
            default=self.DEFAULTS["risk_per_trade"],
        )
        numeric = float(value)
        return numeric / 100.0 if numeric > 1 else numeric

    def get_max_order_value(self) -> float:
        settings = self._get_all_settings()
        return float(settings.get("max_order_value", self.DEFAULTS["max_order_value"]))

    def is_recycling_enabled(self) -> bool:
        settings = self._get_all_settings()
        value = self._get_first(
            settings,
            "smart_recycling",
            "enable_recycling",
            default=self.DEFAULTS["enable_recycling"],
        )
        return self._as_bool(value)

    def is_auto_execute_enabled(self) -> bool:
        settings = self._get_all_settings()
        return self._as_bool(settings.get("auto_execute", self.DEFAULTS["auto_execute"]))

    def get_order_type(self) -> str:
        settings = self._get_all_settings()
        value = self._get_first(
            settings,
            "order_type",
            default=self.DEFAULTS["order_type"],
        )
        return str(value).upper()

    def get_limit_chase_timeout_seconds(self) -> int:
        settings = self._get_all_settings()
        value = self._get_first(
            settings,
            "limit_chase_timeout_seconds",
            default=self.DEFAULTS["limit_chase_timeout_seconds"],
        )
        return int(value)

    def get_watched_symbols(self) -> List[str]:
        """Get the symbol watchlist from DB, falling back to MultiTokenConfig."""
        settings = self._get_all_settings()

        enabled_tokens_str = settings.get("enabled_tokens", "")
        if enabled_tokens_str:
            return [token.strip().upper() for token in enabled_tokens_str.split(",") if token.strip()]

        try:
            from src.config import MultiTokenConfig

            return list(MultiTokenConfig().symbols)
        except ImportError:
            logger.warning("MultiTokenConfig not available, using default symbols")
            return ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]

    def get_watched_symbols_short(self) -> List[str]:
        return [symbol.replace("USDT", "") for symbol in self.get_watched_symbols()]

    def get_all(self) -> Dict[str, Any]:
        settings = self._get_all_settings()
        result = {**self.DEFAULTS}
        result.update(settings)
        return result

    def get_status_dict(self) -> Dict[str, Any]:
        return {
            "leverage": self.get_leverage(),
            "max_positions": self.get_max_positions(),
            "ttl_minutes": self.get_ttl_minutes(),
            "risk_per_trade": self.get_risk_per_trade(),
            "enable_recycling": self.is_recycling_enabled(),
            "auto_execute": self.is_auto_execute_enabled(),
            "order_type": self.get_order_type(),
            "limit_chase_timeout_seconds": self.get_limit_chase_timeout_seconds(),
            "watched_symbols_count": len(self.get_watched_symbols()),
        }

    def __repr__(self) -> str:
        return (
            f"SettingsProvider("
            f"leverage={self.get_leverage()}, "
            f"max_pos={self.get_max_positions()}, "
            f"ttl={self.get_ttl_minutes()}m, "
            f"symbols={len(self.get_watched_symbols())})"
        )


_settings_provider: Optional[SettingsProvider] = None


def get_settings_provider() -> SettingsProvider:
    """Get global SettingsProvider instance."""
    global _settings_provider
    if _settings_provider is None:
        _settings_provider = SettingsProvider()
    return _settings_provider


def init_settings_provider(order_repository) -> SettingsProvider:
    """Initialize SettingsProvider with repository."""
    global _settings_provider
    _settings_provider = SettingsProvider(order_repository)
    return _settings_provider
