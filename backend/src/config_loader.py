"""
Centralized Config Loader - SOTA Pattern

This module provides a SINGLE entry point for loading application configuration.
Following Discord/Binance/Slack desktop app patterns for deterministic config loading.

Key Principles:
1. SINGLE SOURCE OF TRUTH - One location for config per environment
2. DETERMINISTIC - Same path every time based on sys.frozen
3. FAIL FAST - No config = first_run mode, not silent defaults

Usage:
    from src.config_loader import load_config, get_config

    config = load_config()
    if config.first_run:
        # Trigger setup wizard via health endpoint
        pass
"""

import os
import sys
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ConfigResult:
    """Result of config loading attempt."""
    first_run: bool
    config_path: Path
    env_mode: str
    api_key_present: bool
    testnet_key_present: bool
    telegram_token: Optional[str]
    telegram_chat_id: Optional[str]
    telegram_enabled: bool
    error: Optional[str] = None


# Global singleton
_config_result: Optional[ConfigResult] = None


def get_config_dir() -> Path:
    """
    Get the config directory based on runtime environment.

    SOTA: Different paths for production vs development.
    """
    if getattr(sys, 'frozen', False):
        # Production mode (PyInstaller bundle): Use AppData
        if os.name == 'nt':  # Windows
            app_data = os.environ.get('APPDATA', str(Path.home()))
            return Path(app_data) / "Hinto"
        else:  # Linux/Mac
            return Path.home() / ".config" / "Hinto"
    else:
        # Development mode: Use project root or backend folder
        # Check multiple locations in order of priority
        candidates = [
            Path.cwd() / ".env",                           # Current dir (e.g., project root)
            Path.cwd().parent / ".env",                    # Parent of CWD (e.g., if running from backend/)
            Path.cwd() / "backend" / ".env",               # backend subfolder
            Path(__file__).parent.parent / ".env",         # Relative to this file (backend/)
            Path(__file__).parent.parent.parent / ".env",  # Relative to this file (project root)
        ]
        for candidate in candidates:
            if candidate.is_file():
                logger.info(f"[ConfigLoader] Found .env at: {candidate}")
                return candidate.parent

        # Default to current working directory if no .env found
        return Path.cwd()


def get_config_path() -> Path:
    """Get the full path to .env file."""
    return get_config_dir() / ".env"


def load_config(force_reload: bool = False) -> ConfigResult:
    """
    Load configuration from the appropriate location.

    SOTA Pattern:
    - In production: ONLY load from AppData
    - In development: Load from project root
    - If no config found: Return first_run=True (don't use defaults!)

    Args:
        force_reload: If True, reload config even if already loaded

    Returns:
        ConfigResult with loading status and config info
    """
    global _config_result

    # Return cached result if already loaded
    if _config_result is not None and not force_reload:
        return _config_result

    config_path = get_config_path()

    logger.info(f"[ConfigLoader] sys.frozen: {getattr(sys, 'frozen', False)}")
    logger.info(f"[ConfigLoader] Config path: {config_path}")
    logger.info(f"[ConfigLoader] Config exists: {config_path.exists()}")

    # First-run detection
    if not config_path.exists():
        logger.warning(f"[ConfigLoader] No config found at {config_path} - FIRST RUN MODE")
        _config_result = ConfigResult(
            first_run=True,
            config_path=config_path,
            env_mode="paper",  # Safe default
            api_key_present=False,
            testnet_key_present=False,
            telegram_token=None,
            telegram_chat_id=None,
            telegram_enabled=False
        )
        return _config_result

    # Load the config file
    try:
        from dotenv import load_dotenv

        # EXPLICIT path loading - no searching!
        load_dotenv(dotenv_path=str(config_path), override=True)
        logger.info(f"[ConfigLoader] Loaded config from: {config_path}")

        # Extract key info
        env_mode = os.getenv("ENV", "paper").lower().strip()
        api_key = os.getenv("BINANCE_API_KEY", "")
        api_secret = os.getenv("BINANCE_API_SECRET", "")
        testnet_key = os.getenv("BINANCE_TESTNET_API_KEY", "")
        testnet_secret = os.getenv("BINANCE_TESTNET_API_SECRET", "")

        # Telegram Config
        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        telegram_enabled = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"

        _config_result = ConfigResult(
            first_run=False,
            config_path=config_path,
            env_mode=env_mode,
            api_key_present=bool(api_key and api_secret),
            testnet_key_present=bool(testnet_key and testnet_secret),
            telegram_token=telegram_token,
            telegram_chat_id=telegram_chat_id,
            telegram_enabled=telegram_enabled
        )

        logger.info(f"[ConfigLoader] ENV mode: {env_mode}")
        logger.info(f"[ConfigLoader] API key present: {_config_result.api_key_present}")
        logger.info(f"[ConfigLoader] Testnet key present: {_config_result.testnet_key_present}")

        return _config_result

    except Exception as e:
        logger.error(f"[ConfigLoader] Failed to load config: {e}")
        _config_result = ConfigResult(
            first_run=True,
            config_path=config_path,
            env_mode="paper",
            api_key_present=False,
            testnet_key_present=False,
            telegram_token=None,
            telegram_chat_id=None,
            telegram_enabled=False,
            error=str(e),
        )
        return _config_result


def get_config() -> ConfigResult:
    """
    Get the current config (load if not already loaded).

    Convenience function for getting config without explicit load.
    """
    if _config_result is None:
        return load_config()
    return _config_result


def is_first_run() -> bool:
    """Check if this is a first-run (no config) state."""
    return get_config().first_run


def get_env_mode() -> str:
    """Get the current environment mode (paper/testnet/live)."""
    return get_config().env_mode
