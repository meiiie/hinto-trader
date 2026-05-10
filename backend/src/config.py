"""
Configuration module for Binance Data Pipeline.

Handles loading and validation of environment variables and application settings.

Expert Feedback 3 Update:
- Added BookTickerConfig for configurable stale data threshold
- Added SafetyConfig for HALTED state behavior
- Added TRADING_MODE for paper/real switching
"""

import os
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv


def _ensure_env_loaded() -> None:
    """
    SOTA (Jan 2026): Ensure .env is loaded using centralized config_loader pattern.

    This function is critical for Tauri compatibility:
    - Development: Loads from project root (.env)
    - Production (Tauri sidecar): Loads from AppData/Hinto/.env

    The config_loader.get_config_path() function handles the path resolution
    automatically based on sys.frozen (PyInstaller bundle detection).
    """
    try:
        # Use centralized config_loader for consistent path resolution
        from src.config_loader import get_config_path
        config_path = get_config_path()

        if config_path.exists():
            load_dotenv(dotenv_path=str(config_path), override=True)
            logging.info(f"📦 Config: Loaded .env from {config_path}")
        else:
            logging.warning(f"⚠️ Config: No .env found at {config_path}")
    except ImportError:
        # Fallback for edge cases where config_loader isn't available
        logging.warning("📦 Config: config_loader not available, using fallback paths")
        _fallback_paths = [
            Path(__file__).parent.parent.parent / ".env",  # Project root
            Path(__file__).parent.parent / ".env",          # Backend folder
            Path.cwd() / ".env",                            # CWD
            Path.cwd().parent / ".env",                     # Parent of CWD
        ]
        for _path in _fallback_paths:
            if _path.exists():
                load_dotenv(dotenv_path=str(_path), override=True)
                logging.info(f"📦 Config (fallback): Loaded .env from {_path}")
                break


# Load environment on module import
_ensure_env_loaded()


# Default values
DEFAULT_MAX_BOOK_TICKER_AGE_SECONDS = 2.0
DEFAULT_TRADING_MODE = "PAPER"

# Multi-token configuration
DEFAULT_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "TAOUSDT",
    "FETUSDT",
    "ONDOUSDT",
]


def get_trading_db_path(env: Optional[str] = None, base_dir: Optional[Path] = None) -> Path:
    """Return the environment-aware trading DB path used by runtime services."""
    resolved_env = (env or os.getenv("ENV", "paper")).lower().strip()
    if resolved_env not in {"paper", "testnet", "live"}:
        resolved_env = "paper"

    if base_dir is None:
        base_dir = Path(__file__).resolve().parent.parent

    return base_dir / "data" / resolved_env / "trading_system.db"


@dataclass
class MultiTokenConfig:
    """
    Multi-token support configuration.

    SOTA Phase: Dynamic token loading from watchlist file.

    Priority order:
    1. SQLite watchlist / enabled_tokens (persists across deploys)
    2. ENV variable SYMBOLS (bootstrap fallback)
    3. DEFAULT_SYMBOLS fallback

    Example:
        SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT
    """
    symbols: list = None
    db_path_override: Optional[str] = None

    def __post_init__(self):
        """Load symbols from DB first, then ENV bootstrap, then defaults."""
        if self.symbols is None:
            env_symbols = os.getenv("SYMBOLS", "")
            watchlist_symbols, has_persisted_watchlist = self._load_from_watchlist()

            if has_persisted_watchlist:
                self.symbols = watchlist_symbols
                logging.info("📊 MultiToken: Using DB watchlist")
            elif env_symbols:
                self.symbols = [s.strip().upper() for s in env_symbols.split(",") if s.strip()]
                logging.info("📊 MultiToken: Using ENV SYMBOLS fallback")
            else:
                self.symbols = watchlist_symbols

        # SOTA (Jan 2026): Validate symbols for Binance Futures
        # Only requirement: Must end with USDT
        # Note: Unicode symbols like 币安人生USDT are valid on Binance Futures
        valid_symbols = []
        invalid_symbols = []
        for symbol in self.symbols:
            # Check USDT suffix only
            if not symbol.endswith("USDT"):
                invalid_symbols.append((symbol, "must end with USDT"))
                continue
            valid_symbols.append(symbol)

        # Log invalid symbols
        if invalid_symbols:
            logging.warning(f"⚠️ Filtered {len(invalid_symbols)} invalid symbols:")
            for sym, reason in invalid_symbols[:5]:  # Show first 5
                logging.warning(f"   - {sym}: {reason}")
            if len(invalid_symbols) > 5:
                logging.warning(f"   ... and {len(invalid_symbols) - 5} more")

        self.symbols = valid_symbols
        logging.info(f"📊 MultiToken: {len(self.symbols)} symbols configured: {', '.join(self.symbols)}")

    def _load_from_watchlist(self) -> tuple[list, bool]:
        """
        SOTA: Load enabled tokens from SQLite database.

        Reads from the same location where Settings API saves custom tokens.
        Falls back to DEFAULT_SYMBOLS if database not accessible.
        """
        import sqlite3
        db_path = (
            Path(self.db_path_override)
            if self.db_path_override
            else get_trading_db_path()
        )

        try:
            if db_path.exists():
                conn = sqlite3.connect(str(db_path))
                cursor = conn.cursor()

                # Get custom tokens
                cursor.execute("SELECT value FROM settings WHERE key = 'custom_tokens'")
                custom_row = cursor.fetchone()
                custom_tokens = set(custom_row[0].split(',')) if custom_row and custom_row[0] else set()
                logging.info(f"📊 DEBUG: custom_tokens from DB = {custom_tokens}")

                # Get enabled tokens
                cursor.execute("SELECT value FROM settings WHERE key = 'enabled_tokens'")
                enabled_row = cursor.fetchone()
                if enabled_row and enabled_row[0]:
                    enabled_tokens = set(enabled_row[0].split(','))
                else:
                    # No enabled_tokens setting - use all defaults + custom
                    enabled_tokens = set(DEFAULT_SYMBOLS) | custom_tokens
                logging.info(f"📊 DEBUG: enabled_tokens from DB = {enabled_tokens}")

                conn.close()

                # Combine default + custom tokens that are enabled
                all_available = set(DEFAULT_SYMBOLS) | custom_tokens
                logging.info(f"📊 DEBUG: DEFAULT_SYMBOLS = {DEFAULT_SYMBOLS}")
                logging.info(f"📊 DEBUG: all_available = {all_available}")

                result = [t for t in all_available if t in enabled_tokens]
                logging.info(f"📊 DEBUG: result = {result}")

                has_explicit_watchlist = bool(
                    (enabled_row and enabled_row[0]) or (custom_row and custom_row[0])
                )

                if result:
                    logging.info(f"📊 MultiToken: Loaded {len(result)} tokens from database "
                               f"(default: {len(DEFAULT_SYMBOLS)}, custom: {len(custom_tokens)})")
                    return result, has_explicit_watchlist
                else:
                    logging.warning("📊 MultiToken: No enabled tokens, using defaults")
                    return DEFAULT_SYMBOLS.copy(), False
            else:
                logging.info("📊 MultiToken: Database not found, using defaults")
                return DEFAULT_SYMBOLS.copy(), False
        except Exception as e:
            logging.error(f"📊 MultiToken: Error reading database: {e}, using defaults")
            return DEFAULT_SYMBOLS.copy(), False


@dataclass
class BookTickerConfig:
    """
    BookTicker stream configuration.

    Controls how stale data is detected and handled.

    Attributes:
        max_age_seconds: Maximum age in seconds before data is considered stale.
                        Default is 2.0 seconds per expert recommendation.
    """
    max_age_seconds: float = DEFAULT_MAX_BOOK_TICKER_AGE_SECONDS

    def __post_init__(self):
        """Validate and correct invalid values."""
        if self.max_age_seconds <= 0:
            logging.warning(
                f"Invalid MAX_BOOK_TICKER_AGE_SECONDS: {self.max_age_seconds}. "
                f"Using default: {DEFAULT_MAX_BOOK_TICKER_AGE_SECONDS}"
            )
            self.max_age_seconds = DEFAULT_MAX_BOOK_TICKER_AGE_SECONDS


@dataclass
class SafetyConfig:
    """
    Safety and recovery configuration.

    Controls behavior during critical states like HALTED.

    Attributes:
        allow_auto_resume_from_halted: If False (default), system stays HALTED
                                       after restart and requires manual intervention.
    """
    allow_auto_resume_from_halted: bool = False


@dataclass
class ExchangeConfig:
    """
    Exchange service configuration.

    Controls which exchange implementation to use.

    Attributes:
        trading_mode: 'PAPER' for paper trading, 'REAL' for live trading
    """
    trading_mode: str = DEFAULT_TRADING_MODE

    def __post_init__(self):
        """Validate trading mode."""
        valid_modes = ('PAPER', 'REAL', 'LIVE', 'TESTNET')  # SOTA: Support all modes
        if self.trading_mode.upper() not in valid_modes:
            logging.warning(
                f"Invalid TRADING_MODE: {self.trading_mode}. "
                f"Using default: {DEFAULT_TRADING_MODE}"
            )
            self.trading_mode = DEFAULT_TRADING_MODE
        else:
            self.trading_mode = self.trading_mode.upper()

    @property
    def is_paper_trading(self) -> bool:
        """Check if running in paper trading mode."""
        return self.trading_mode == "PAPER"

    @property
    def is_real_trading(self) -> bool:
        """Check if running in real trading mode."""
        return self.trading_mode == "REAL"


@dataclass
class StrategyConfig:
    """
    SOTA: Centralized strategy configuration for signal generation.

    Based on: Two Sigma's parameter management, Binance's configurable trading bots.

    This allows tuning entry conditions without code changes, following
    institutional best practices for algorithm parameter management.

    Attributes:
        # Mode settings
        strict_mode: If True, requires 4/5 conditions. If False, 3/5.
        use_regime_filter: Enable/disable regime-based filtering.

        # Entry zone thresholds
        bb_near_threshold_pct: % distance to consider "near" Bollinger Band
        vwap_near_threshold_pct: % distance to consider "near" VWAP

        # Regime filter settings
        adx_trending_threshold: ADX value above which market is "trending"
        regime_filter_mode: "block" (hard reject) or "penalty" (reduce confidence)
        regime_penalty_pct: Confidence reduction when in ranging market

        # Confluence scoring
        min_confluence_score: Minimum weighted score to generate signal (0-1)
        use_weighted_confluence: Use weighted scoring instead of condition count

        # StochRSI thresholds
        stoch_oversold_threshold: K value below which is "oversold"
        stoch_overbought_threshold: K value above which is "overbought"
    """
    # Mode settings
    strict_mode: bool = False  # SOTA: Default to flexible for more signals
    use_regime_filter: bool = True

    # Entry zone thresholds (percentage) - WIDENED from original
    bb_near_threshold_pct: float = 0.025  # 2.5% (was 1.5%)
    vwap_near_threshold_pct: float = 0.020  # 2.0% (was 1.0%)

    # Regime filter settings - FIXED for whipsaw prevention
    adx_trending_threshold: float = 20.0  # Lowered from 25 for more opportunities
    regime_filter_mode: str = "block"  # CRITICAL FIX: "block" prevents trading in ranging markets
    regime_penalty_pct: float = 0.30  # 30% confidence reduction (only used in penalty mode)

    # Confluence scoring - TUNED for quality
    min_confluence_score: float = 0.70  # INCREASED from 0.60 to reduce false signals
    use_weighted_confluence: bool = True

    # Confluence condition weights (must sum to 1.0)
    weight_trend_alignment: float = 0.25  # Price vs VWAP
    weight_pullback_zone: float = 0.30    # Near BB/VWAP (most important)
    weight_momentum_trigger: float = 0.25  # StochRSI cross
    weight_candle_confirmation: float = 0.10  # Green/Red candle
    weight_volume_confirmation: float = 0.10  # Volume spike

    # StochRSI thresholds - EXPANDED zones
    stoch_oversold_threshold: float = 30.0  # Expanded from 20
    stoch_overbought_threshold: float = 70.0  # Expanded from 80

    # Risk management
    min_risk_reward_ratio: float = 0.8  # Minimum R:R to accept signal
    max_volume_ratio: float = 4.0  # Maximum volume ratio (climax filter)

    # SOTA: Trade execution settings
    cooldown_seconds: int = 300  # 5 minutes cooldown after closing a position
    allow_flip: bool = True  # Allow position flip (close + open opposite direction)

    def __post_init__(self):
        """Validate configuration values."""
        # Validate regime filter mode
        valid_modes = ('block', 'penalty')
        if self.regime_filter_mode.lower() not in valid_modes:
            logging.warning(
                f"Invalid regime_filter_mode: {self.regime_filter_mode}. "
                f"Using default: penalty"
            )
            self.regime_filter_mode = "penalty"
        else:
            self.regime_filter_mode = self.regime_filter_mode.lower()

        # Validate weights sum to 1.0
        total_weight = (
            self.weight_trend_alignment +
            self.weight_pullback_zone +
            self.weight_momentum_trigger +
            self.weight_candle_confirmation +
            self.weight_volume_confirmation
        )
        if abs(total_weight - 1.0) > 0.01:
            logging.warning(
                f"Confluence weights sum to {total_weight:.2f}, not 1.0. "
                f"Results may be unexpected."
            )

    def get_confluence_weights(self) -> dict:
        """Get condition weights as dictionary."""
        return {
            'trend_alignment': self.weight_trend_alignment,
            'pullback_zone': self.weight_pullback_zone,
            'momentum_trigger': self.weight_momentum_trigger,
            'candle_confirmation': self.weight_candle_confirmation,
            'volume_confirmation': self.weight_volume_confirmation,
        }


class Config:
    """
    Configuration manager for the Binance Data Pipeline.

    Loads API credentials from .env file and provides centralized
    access to all configuration parameters.

    Attributes:
        api_key (str): Binance API key
        api_secret (str): Binance API secret
        db_path (str): Path to SQLite database file
        base_url (str): Binance API base URL
    """

    def __init__(self, env_file: str = ".env"):
        """
        Initialize configuration by loading environment variables.

        Args:
            env_file (str): Path to .env file (default: ".env")
        """
        # Load environment variables from .env file
        env_path = Path(env_file)
        if env_path.exists():
            load_dotenv(dotenv_path=env_path, override=True)
        # Note: Don't fallback to default .env for testing isolation

        # Load API credentials
        self.api_key = os.getenv("BINANCE_API_KEY")
        self.api_secret = os.getenv("BINANCE_API_SECRET")

        # Load optional configuration with defaults
        self.db_path = os.getenv("DB_PATH", "crypto_data.db")
        self.base_url = os.getenv("BASE_URL", "https://api.binance.com/api/v3")

        # Expert Feedback 3: New configuration sections
        self._load_book_ticker_config()
        self._load_safety_config()
        self._load_exchange_config()
        self._load_strategy_config()  # SOTA: Strategy parameters

    def _load_strategy_config(self) -> None:
        """
        Load Strategy configuration from environment.

        SOTA: Allows runtime tuning of signal generation parameters
        without code changes. Follows Two Sigma/Binance patterns.
        """
        # Load optional overrides from environment
        strict_mode = os.getenv("STRATEGY_STRICT_MODE", "false").lower() in ("true", "1", "yes")
        use_regime_filter = os.getenv("STRATEGY_USE_REGIME_FILTER", "true").lower() in ("true", "1", "yes")
        regime_filter_mode = os.getenv("STRATEGY_REGIME_FILTER_MODE", "block")  # Default to block

        # Parse numeric values with defaults
        def parse_float(key: str, default: float) -> float:
            try:
                return float(os.getenv(key, str(default)))
            except ValueError:
                logging.warning(f"Invalid {key}, using default: {default}")
                return default

        bb_threshold = parse_float("STRATEGY_BB_THRESHOLD_PCT", 0.025)
        vwap_threshold = parse_float("STRATEGY_VWAP_THRESHOLD_PCT", 0.020)
        adx_threshold = parse_float("STRATEGY_ADX_THRESHOLD", 20.0)
        min_confluence = parse_float("STRATEGY_MIN_CONFLUENCE_SCORE", 0.70)  # Increased for quality

        self.strategy = StrategyConfig(
            strict_mode=strict_mode,
            use_regime_filter=use_regime_filter,
            regime_filter_mode=regime_filter_mode,
            bb_near_threshold_pct=bb_threshold,
            vwap_near_threshold_pct=vwap_threshold,
            adx_trending_threshold=adx_threshold,
            min_confluence_score=min_confluence,
        )

    def _load_book_ticker_config(self) -> None:
        """Load BookTicker configuration from environment."""
        max_age_str = os.getenv("MAX_BOOK_TICKER_AGE_SECONDS", str(DEFAULT_MAX_BOOK_TICKER_AGE_SECONDS))
        try:
            max_age = float(max_age_str)
        except ValueError:
            logging.warning(
                f"Invalid MAX_BOOK_TICKER_AGE_SECONDS value: {max_age_str}. "
                f"Using default: {DEFAULT_MAX_BOOK_TICKER_AGE_SECONDS}"
            )
            max_age = DEFAULT_MAX_BOOK_TICKER_AGE_SECONDS

        self.book_ticker = BookTickerConfig(max_age_seconds=max_age)

    def _load_safety_config(self) -> None:
        """Load Safety configuration from environment."""
        allow_resume_str = os.getenv("ALLOW_AUTO_RESUME_FROM_HALTED", "false")
        allow_resume = allow_resume_str.lower() in ("true", "1", "yes")

        self.safety = SafetyConfig(allow_auto_resume_from_halted=allow_resume)

    def _load_exchange_config(self) -> None:
        """Load Exchange configuration from environment."""
        trading_mode = os.getenv("TRADING_MODE", DEFAULT_TRADING_MODE)
        self.exchange = ExchangeConfig(trading_mode=trading_mode)

    def validate(self) -> None:
        """
        Validate that all required configuration is present.

        Raises:
            ValueError: If required configuration is missing
        """
        missing_fields = []

        if not self.api_key:
            missing_fields.append("BINANCE_API_KEY")

        if not self.api_secret:
            missing_fields.append("BINANCE_API_SECRET")

        if missing_fields:
            raise ValueError(
                f"Missing required API credentials in .env file: {', '.join(missing_fields)}\n"
                f"Please create a .env file with:\n"
                f"BINANCE_API_KEY=your_api_key_here\n"
                f"BINANCE_API_SECRET=your_api_secret_here"
            )

    def __repr__(self) -> str:
        """
        String representation of Config (hides sensitive data).

        Returns:
            str: Safe string representation
        """
        return (
            f"Config("
            f"api_key={'***' if self.api_key else 'None'}, "
            f"api_secret={'***' if self.api_secret else 'None'}, "
            f"db_path='{self.db_path}', "
            f"base_url='{self.base_url}', "
            f"trading_mode='{self.exchange.trading_mode}', "
            f"max_book_ticker_age={self.book_ticker.max_age_seconds}s, "
            f"allow_auto_resume_from_halted={self.safety.allow_auto_resume_from_halted}"
            f")"
        )
