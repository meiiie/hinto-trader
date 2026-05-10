"""
Environment-Aware Configuration System

SOTA: Pydantic-based configuration with strict validation.
Supports: paper, testnet, live environments.

Usage:
    from config.settings import get_settings
    settings = get_settings()  # Reads ENV variable
"""

import os
import logging
from pathlib import Path
from typing import Literal, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class TradingSettings(BaseSettings):
    """
    Validated trading configuration.

    SOTA: All settings are validated at startup.
    Environment is determined by ENV variable and is immutable.
    """

    # =========================================================================
    # ENVIRONMENT (REQUIRED)
    # =========================================================================

    env: Literal["paper", "testnet", "live"] = Field(
        default="paper",
        description="Trading environment (paper/testnet/live)"
    )

    # =========================================================================
    # API CONFIGURATION
    # =========================================================================

    binance_api_key: str = Field(default="", description="Binance API Key")
    binance_api_secret: str = Field(default="", description="Binance API Secret")
    binance_testnet_api_key: str = Field(default="", description="Binance Testnet API Key")
    binance_testnet_api_secret: str = Field(default="", description="Binance Testnet API Secret")

    # =========================================================================
    # DATABASE PATHS (Auto-set based on env)
    # =========================================================================

    db_base_path: str = Field(default="data", description="Base path for databases")

    @property
    def trading_db_path(self) -> str:
        """Get environment-specific trading database path."""
        return f"{self.db_base_path}/{self.env}/trading_system.db"

    @property
    def market_db_path(self) -> str:
        """Market data is shared across environments (read-only)."""
        return f"{self.db_base_path}/market_data.db"

    # =========================================================================
    # TRADING PARAMETERS
    # =========================================================================

    risk_per_trade: float = Field(default=0.01, ge=0.001, le=0.05)
    max_positions: int = Field(default=4, ge=1, le=20)
    max_leverage: int = Field(default=20, ge=1, le=125)
    max_order_value: float = Field(default=10000.0, description="Max notional per order")

    # =========================================================================
    # SAFETY FLAGS
    # =========================================================================

    enable_trading_on_startup: bool = Field(
        default=False,
        description="Auto-enable trading on startup (dangerous for live!)"
    )
    require_confirmation: bool = Field(
        default=True,
        description="Require confirmation for production orders"
    )

    # =========================================================================
    # VALIDATORS
    # =========================================================================

    @field_validator('env')
    @classmethod
    def validate_env(cls, v):
        """Environment must be valid."""
        if v not in ["paper", "testnet", "live"]:
            raise ValueError(f"Invalid environment: {v}")
        return v

    def get_api_credentials(self) -> tuple[str, str]:
        """
        Get appropriate API credentials based on environment.

        Returns:
            Tuple of (api_key, api_secret)
        """
        if self.env == "paper":
            return "", ""  # Paper doesn't need real keys
        elif self.env == "testnet":
            return self.binance_testnet_api_key, self.binance_testnet_api_secret
        else:  # live
            return self.binance_api_key, self.binance_api_secret

    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.env == "live"

    def validate_keys_for_env(self) -> bool:
        """
        Validate that correct keys are used for environment.

        SAFETY: Prevents using testnet keys in live mode.
        """
        api_key, _ = self.get_api_credentials()

        if self.env == "live":
            # Live mode should NOT use testnet-looking keys
            if "testnet" in api_key.lower() or not api_key:
                logger.error("❌ SAFETY: Live mode requires production API key!")
                return False

        return True

    class Config:
        env_prefix = ""  # Read env vars without prefix
        case_sensitive = False


# Singleton instance
_settings: Optional[TradingSettings] = None


def get_settings(env: Optional[str] = None) -> TradingSettings:
    """
    Get or create settings singleton.

    Args:
        env: Override environment (for testing)

    Returns:
        Validated TradingSettings instance
    """
    global _settings

    if _settings is None:
        # Determine environment
        environment = env or os.getenv("ENV", "paper")

        logger.info(f"🔧 Loading configuration for environment: {environment}")

        # Create settings with environment
        _settings = TradingSettings(env=environment)

        # Ensure database directory exists
        db_dir = Path(_settings.trading_db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        # Log configuration
        logger.info(f"📁 Trading DB: {_settings.trading_db_path}")
        logger.info(f"⚙️ Risk: {_settings.risk_per_trade*100}%")
        logger.info(f"📊 Max Positions: {_settings.max_positions}")

        # Validate keys
        if not _settings.validate_keys_for_env():
            raise ValueError("API key validation failed!")

    return _settings


def reset_settings():
    """Reset settings singleton (for testing)."""
    global _settings
    _settings = None
