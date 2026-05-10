"""
Config Package - SOTA Unified Configuration

Re-exports:
- Config: Main configuration class from src/config.py
- MarketMode, MarketConfig: Market mode configuration

This package allows both:
- from src.config import Config (backward compatible)
- from src.config.market_mode import MarketMode (new)
"""

# Re-export Config from parent config.py for backward compatibility
# Note: src/config.py is loaded as src.config module when src/config/ doesn't exist
# Since we have both, we need to explicitly import from the .py file
import sys
import os

# Import from config.py file directly
_config_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.py')
import importlib.util
_spec = importlib.util.spec_from_file_location("config_module", _config_file)
_config_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_config_module)

# Re-export
Config = _config_module.Config
BookTickerConfig = _config_module.BookTickerConfig
SafetyConfig = _config_module.SafetyConfig
# Re-export constants and other classes
DEFAULT_SYMBOLS = _config_module.DEFAULT_SYMBOLS
DEFAULT_TRADING_MODE = _config_module.DEFAULT_TRADING_MODE
DEFAULT_MAX_BOOK_TICKER_AGE_SECONDS = _config_module.DEFAULT_MAX_BOOK_TICKER_AGE_SECONDS
MultiTokenConfig = _config_module.MultiTokenConfig
get_trading_db_path = _config_module.get_trading_db_path
get_runtime_env = _config_module.get_runtime_env
get_execution_mode = _config_module.get_execution_mode
is_paper_real_enabled = _config_module.is_paper_real_enabled
is_real_ordering_enabled = _config_module.is_real_ordering_enabled

# Also export our new market mode
from .market_mode import MarketMode, MarketConfig, get_market_config, get_default_market_mode
