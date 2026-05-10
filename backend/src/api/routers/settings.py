"""
Settings API Router

Handles trading settings configuration.
Requirements: 6.3

SOTA Phase 26: Token Watchlist for per-token signal enable/disable
SOTA (Jan 2026): Mode-aware settings - uses LiveTradingService in LIVE/TESTNET mode
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
from src.api.dependencies import get_paper_trading_service
from src.application.services.paper_trading_service import PaperTradingService
from src.config import DEFAULT_SYMBOLS
from src.trading_contract import (
    PRODUCTION_BLOCKED_WINDOWS_STR,
    PRODUCTION_CB_MAX_DAILY_DRAWDOWN_PCT,
    PRODUCTION_LIMIT_CHASE_TIMEOUT_SECONDS,
    PRODUCTION_ORDER_TTL_MINUTES,
    PRODUCTION_ORDER_TYPE,
    PRODUCTION_PORTFOLIO_TARGET_PCT,
    PRODUCTION_CLOSE_PROFITABLE_AUTO,
    PRODUCTION_PROFITABLE_THRESHOLD_PCT,
)
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/settings",
    tags=["settings"]
)


class SettingsUpdate(BaseModel):
    """Request model for updating settings"""
    risk_percent: Optional[float] = Field(None, ge=0.1, le=10.0, description="Risk per trade (0.1-10%)")
    # NOTE: rr_ratio removed - backtest uses SL/TP from strategy signal
    max_positions: Optional[int] = Field(None, ge=1, le=10, description="Max concurrent positions")
    leverage: Optional[int] = Field(None, ge=1, le=20, description="Leverage (1-20x)")
    auto_execute: Optional[bool] = Field(None, description="Auto-execute signals")
    execution_ttl_minutes: Optional[int] = Field(
        None,
        ge=1,
        le=1440,
        description=f"Order TTL in minutes (default {PRODUCTION_ORDER_TTL_MINUTES})",
    )
    smart_recycling: Optional[bool] = Field(None, description="Enable Zombie Killer (Smart Recycling)")
    # SOTA (Jan 2026): Auto-Close Profitable Positions
    close_profitable_auto: Optional[bool] = Field(None, description="Auto-close positions when profitable")
    profitable_threshold_pct: Optional[float] = Field(None, ge=1.0, le=50.0, description="Profit threshold % (1-50%)")
    # SOTA (Feb 2026): AUTO_CLOSE check interval
    auto_close_interval: Optional[str] = Field(None, description="AUTO_CLOSE check interval: '1m' (recommended) or '15m'")
    # SOTA (Jan 2026): Portfolio Target
    portfolio_target_pct: Optional[float] = Field(None, ge=0.0, le=100.0, description="Portfolio profit target % (0-100%, 0=disabled)")
    # SOTA (Feb 2026): Profit Lock (ratchet stop)
    use_profit_lock: Optional[bool] = Field(None, description="Enable profit lock (ratchet stop to protect gains)")
    profit_lock_threshold_pct: Optional[float] = Field(None, ge=1.0, le=50.0, description="ROE % threshold to trigger profit lock")
    profit_lock_pct: Optional[float] = Field(None, ge=0.5, le=49.0, description="ROE % to lock when threshold hit (buffer from threshold)")
    # SOTA (Feb 9, 2026): Circuit Breaker runtime config
    max_consecutive_losses: Optional[int] = Field(None, ge=1, le=20, description="Block after N consecutive same-direction losses")
    cooldown_minutes: Optional[int] = Field(None, ge=1, le=1440, description="Per-symbol cooldown in minutes after CB triggers")
    daily_symbol_loss_limit: Optional[int] = Field(None, ge=0, le=20, description="Max losses per symbol per day (0=disabled)")
    blocked_windows: Optional[str] = Field(
        None,
        description=f"Dead zone windows, e.g. '{PRODUCTION_BLOCKED_WINDOWS_STR}'",
    )
    blocked_windows_enabled: Optional[bool] = Field(None, description="Enable/disable trading schedule")
    max_daily_drawdown_pct: Optional[float] = Field(
        None,
        ge=0.01,
        le=1.0,
        description="Global drawdown halt threshold (0.30 = 30%)",
    )
    # v6.5.12: DZ Force-Close
    dz_force_close_enabled: Optional[bool] = Field(None, description="Force-close all positions when entering a dead zone")
    # v6.6.0: Order Type Configuration (MARKET→LIMIT migration)
    order_type: Optional[str] = Field(None, description="Order type: 'MARKET' or 'LIMIT'")
    limit_chase_timeout_seconds: Optional[int] = Field(None, ge=5, le=300, description="LIMIT chase timeout before escalating to MARKET (5-300s)")
    # BroSubSoul heartbeat (pushed by GCP guardian every 60s)
    bro_subsoul_last_heartbeat: Optional[int] = Field(None, description="BroSubSoul last heartbeat Unix timestamp")


class SettingsResponse(BaseModel):
    """Response model for settings"""
    risk_percent: float
    max_positions: int
    leverage: int
    auto_execute: bool
    execution_ttl_minutes: int
    smart_recycling: bool
    # SOTA (Jan 2026): Auto-Close Profitable Positions
    close_profitable_auto: bool = PRODUCTION_CLOSE_PROFITABLE_AUTO
    profitable_threshold_pct: float = PRODUCTION_PROFITABLE_THRESHOLD_PCT
    # SOTA (Feb 2026): AUTO_CLOSE check interval
    auto_close_interval: str = '1m'  # Default: 1m (institutional standard)
    # SOTA (Jan 2026): Portfolio Target
    portfolio_target_pct: float = PRODUCTION_PORTFOLIO_TARGET_PCT
    # SOTA (Feb 2026): Profit Lock (ratchet stop)
    use_profit_lock: bool = False
    profit_lock_threshold_pct: float = 5.0
    profit_lock_pct: float = 4.0
    # SOTA (Feb 2026): Symbol Blacklist (read-only in settings, managed via /settings/blacklist)
    symbol_blacklist: List[str] = []
    # SOTA (Feb 9, 2026): Circuit Breaker config (read from CB singleton)
    max_consecutive_losses: int = 2
    cooldown_minutes: float = 30.0
    daily_symbol_loss_limit: int = 3
    blocked_windows: Optional[list] = []
    blocked_windows_enabled: bool = True
    blocked_windows_utc_offset: int = 7
    max_daily_drawdown_pct: float = PRODUCTION_CB_MAX_DAILY_DRAWDOWN_PCT
    # v6.5.12: DZ Force-Close
    dz_force_close_enabled: bool = True
    # v6.6.0: Order Type Configuration
    order_type: str = PRODUCTION_ORDER_TYPE
    limit_chase_timeout_seconds: int = PRODUCTION_LIMIT_CHASE_TIMEOUT_SECONDS


# SOTA Phase 26: Token Watchlist Models
class TokenWatchlistItem(BaseModel):
    """Single token in watchlist"""
    symbol: str
    enabled: bool = True
    alias: Optional[str] = None  # Display name e.g., "Bitcoin"


class TokenWatchlistUpdate(BaseModel):
    """Request model for updating token watchlist"""
    tokens: List[TokenWatchlistItem]


class TokenWatchlistResponse(BaseModel):
    """Response model for token watchlist"""
    tokens: List[TokenWatchlistItem]


@router.get("", response_model=SettingsResponse)
async def get_settings(
    paper_service: PaperTradingService = Depends(get_paper_trading_service)
):
    """
    Get current trading settings.

    Returns all configurable trading parameters.
    SOTA (Jan 2026): Mode-aware - uses LiveTradingService in LIVE/TESTNET mode.
    """
    # SOTA (Jan 2026): Mode-aware settings retrieval
    import os
    env = os.getenv("ENV", "paper").lower()

    if env in ["live", "testnet"]:
        # Use LiveTradingService for LIVE/TESTNET mode
        from ..dependencies import get_container
        container = get_container()
        live_service = container.get_live_trading_service()
        if live_service:
            settings = live_service.get_settings()
            return SettingsResponse(**settings)
        else:
            # Fallback to paper service if live service not available
            logger.warning(f"⚠️ LiveTradingService not available in {env} mode, using PaperTradingService")
            settings = paper_service.get_settings()
            return SettingsResponse(**settings)
    else:
        # Use PaperTradingService for PAPER mode
        settings = paper_service.get_settings()
        return SettingsResponse(**settings)


@router.post("", response_model=SettingsResponse)
async def update_settings(
    settings_update: SettingsUpdate,
    paper_service: PaperTradingService = Depends(get_paper_trading_service)
):
    """
    Update trading settings.

    Persists settings to SQLite and applies them to subsequent signals.
    SOTA: Syncs max_positions to SharkTankCoordinator for realtime effect.
    SOTA (Jan 2026): Mode-aware - uses LiveTradingService in LIVE/TESTNET mode.
    """
    # Filter out None values
    update_dict = {k: v for k, v in settings_update.model_dump().items() if v is not None}

    if not update_dict:
        raise HTTPException(status_code=400, detail="No settings provided to update")

    # SOTA (Jan 2026): Mode-aware settings update
    import os
    env = os.getenv("ENV", "paper").lower()

    if env in ["live", "testnet"]:
        # Use LiveTradingService for LIVE/TESTNET mode
        from ..dependencies import get_container
        container = get_container()
        live_service = container.get_live_trading_service()

        if live_service:
            # Update LiveTradingService settings
            updated = live_service.update_settings(update_dict)

            # SOTA: Also sync to SharkTankCoordinator for realtime effect
            if 'max_positions' in update_dict:
                shark_tank = container.get_shark_tank_coordinator()
                shark_tank.max_positions = update_dict['max_positions']
                logger.info(f"⚙️ SharkTankCoordinator max_positions synced to: {update_dict['max_positions']}")

            return SettingsResponse(**updated)
        else:
            # Fallback to paper service if live service not available
            logger.warning(f"⚠️ LiveTradingService not available in {env} mode, using PaperTradingService")
            updated = paper_service.update_settings(update_dict)
            return SettingsResponse(**updated)
    else:
        # Use PaperTradingService for PAPER mode
        # Update PaperService settings (persisted to SQLite)
        updated = paper_service.update_settings(update_dict)

        # SOTA: Sync max_positions to SharkTankCoordinator (realtime effect)
        if 'max_positions' in update_dict:
            from ..dependencies import get_container
            container = get_container()
            shark_tank = container.get_shark_tank_coordinator()
            shark_tank.max_positions = update_dict['max_positions']

            # SOTA (Jan 2026): Also sync to LiveTradingService for safe execution guard
            import os
            _env = os.getenv("ENV", "paper").lower()
            if _env in ["testnet", "live"]:
                live_service = container.get_live_trading_service()
                if live_service:
                    live_service.max_positions = update_dict['max_positions']
                    import logging
                    logging.getLogger(__name__).info(
                        f"⚙️ LiveTradingService max_positions synced to: {update_dict['max_positions']}"
                    )

            # Also update PaperService constant for consistency
            paper_service.MAX_POSITIONS = update_dict['max_positions']

        # SOTA (Jan 2026): Sync auto_execute to LiveTradingService (realtime effect)
        if 'auto_execute' in update_dict:
            from ..dependencies import get_container
            import os
            _env = os.getenv("ENV", "paper").lower()
            if _env in ["testnet", "live"]:
                container = get_container()
                live_service = container.get_live_trading_service()
                if live_service:
                    live_service.enable_trading = update_dict['auto_execute']
                    import logging
                    logging.getLogger(__name__).info(
                        f"⚙️ Live trading enable_trading set to: {update_dict['auto_execute']}"
                    )

        # SOTA (Jan 2026): Sync smart_recycling to LiveTradingService + LocalSignalTracker (realtime effect)
        if 'smart_recycling' in update_dict:
            from ..dependencies import get_container
            import os
            _env = os.getenv("ENV", "paper").lower()
            if _env in ["testnet", "live"]:
                container = get_container()
                live_service = container.get_live_trading_service()
                if live_service:
                    live_service.enable_recycling = update_dict['smart_recycling']
                    # Also update LocalSignalTracker if it exists
                    if hasattr(live_service, '_signal_tracker') and live_service._signal_tracker:
                        live_service._signal_tracker.enable_recycling = update_dict['smart_recycling']
                    import logging
                    logging.getLogger(__name__).info(
                        f"♻️ Smart Recycling (Zombie Killer) set to: {update_dict['smart_recycling']}"
                    )

        # SOTA FIX (Jan 2026): Sync leverage to LiveTradingService (realtime effect)
        if 'leverage' in update_dict:
            from ..dependencies import get_container
            import os
            _env = os.getenv("ENV", "paper").lower()
            if _env in ["testnet", "live"]:
                container = get_container()
                live_service = container.get_live_trading_service()
                if live_service:
                    live_service.max_leverage = update_dict['leverage']
                    import logging
                    logging.getLogger(__name__).info(
                        f"⚙️ LiveTradingService max_leverage synced to: {update_dict['leverage']}"
                    )

            # Also update PaperService constant for consistency
            paper_service.LEVERAGE = update_dict['leverage']

        # SOTA FIX (Jan 2026): Sync risk_percent to LiveTradingService (realtime effect)
        if 'risk_percent' in update_dict:
            from ..dependencies import get_container
            import os
            _env = os.getenv("ENV", "paper").lower()
            if _env in ["testnet", "live"]:
                container = get_container()
                live_service = container.get_live_trading_service()
                if live_service:
                    live_service.risk_per_trade = update_dict['risk_percent'] / 100
                    import logging
                    logging.getLogger(__name__).info(
                        f"⚙️ LiveTradingService risk_per_trade synced to: {update_dict['risk_percent']}%"
                    )

            # Also update PaperService constant for consistency
            paper_service.RISK_PER_TRADE = update_dict['risk_percent'] / 100

        # SOTA FIX (Jan 2026): Sync execution_ttl_minutes to LiveTradingService (realtime effect)
        if 'execution_ttl_minutes' in update_dict:
            from ..dependencies import get_container
            import os
            _env = os.getenv("ENV", "paper").lower()
            if _env in ["testnet", "live"]:
                container = get_container()
                live_service = container.get_live_trading_service()
                if live_service:
                    live_service.order_ttl_minutes = update_dict['execution_ttl_minutes']
                    # Also update LocalSignalTracker if it exists
                    if hasattr(live_service, '_signal_tracker') and live_service._signal_tracker:
                        live_service._signal_tracker.default_ttl_minutes = update_dict['execution_ttl_minutes']
                    import logging
                    logging.getLogger(__name__).info(
                        f"⏱️ LiveTradingService order_ttl_minutes synced to: {update_dict['execution_ttl_minutes']}m"
                    )

        # SOTA (Jan 2026): Sync close_profitable_auto to LiveTradingService (realtime effect)
        if 'close_profitable_auto' in update_dict:
            from ..dependencies import get_container
            import os
            _env = os.getenv("ENV", "paper").lower()
            if _env in ["testnet", "live"]:
                container = get_container()
                live_service = container.get_live_trading_service()
                if live_service:
                    live_service.close_profitable_auto = update_dict['close_profitable_auto']
                    import logging
                    logging.getLogger(__name__).info(
                        f"💰 LiveTradingService close_profitable_auto synced to: {update_dict['close_profitable_auto']}"
                    )

        # SOTA (Jan 2026): Sync profitable_threshold_pct to LiveTradingService (realtime effect)
        if 'profitable_threshold_pct' in update_dict:
            from ..dependencies import get_container
            import os
            _env = os.getenv("ENV", "paper").lower()
            if _env in ["testnet", "live"]:
                container = get_container()
                live_service = container.get_live_trading_service()
                if live_service:
                    live_service.profitable_threshold_pct = update_dict['profitable_threshold_pct']
                    import logging
                    logging.getLogger(__name__).info(
                        f"💰 LiveTradingService profitable_threshold_pct synced to: {update_dict['profitable_threshold_pct']}%"
                    )

        # SOTA (Jan 2026): Sync portfolio_target_pct to LiveTradingService (realtime effect)
        if 'portfolio_target_pct' in update_dict:
            from ..dependencies import get_container
            import os
            _env = os.getenv("ENV", "paper").lower()
            if _env in ["testnet", "live"]:
                container = get_container()
                live_service = container.get_live_trading_service()
                if live_service:
                    live_service.portfolio_target_pct = update_dict['portfolio_target_pct']
                    # Also update PositionMonitor if it exists
                    if hasattr(live_service, 'position_monitor') and live_service.position_monitor:
                        # Recalculate portfolio_target_usd from percentage
                        if live_service.initial_balance > 0:
                            portfolio_target_usd = live_service.initial_balance * (update_dict['portfolio_target_pct'] / 100.0)
                            live_service.position_monitor.set_portfolio_target(portfolio_target_usd)
                    import logging
                    logging.getLogger(__name__).info(
                        f"🎯 LiveTradingService portfolio_target_pct synced to: {update_dict['portfolio_target_pct']}%"
                    )

        return SettingsResponse(**updated)


# SOTA Phase 26: Token Watchlist Endpoints

# Token alias mapping for display
TOKEN_ALIASES = {
    "BTCUSDT": "Bitcoin",
    "ETHUSDT": "Ethereum",
    "SOLUSDT": "Solana",
    "BNBUSDT": "BNB",
    "TAOUSDT": "Bittensor",
    "FETUSDT": "Fetch.ai",
    "ONDOUSDT": "Ondo",
}


@router.get("/tokens", response_model=TokenWatchlistResponse)
async def get_token_watchlist(
    paper_service: PaperTradingService = Depends(get_paper_trading_service)
):
    """
    Get token watchlist with enabled/disabled status.

    SOTA Phase 26b: Includes both default and custom tokens
    """
    settings = paper_service.repo.get_all_settings()

    # Get enabled tokens
    enabled_tokens_str = settings.get('enabled_tokens', '')
    if enabled_tokens_str:
        enabled_tokens = set(enabled_tokens_str.split(','))
    else:
        enabled_tokens = set(DEFAULT_SYMBOLS)

    # Get custom tokens
    custom_tokens_str = settings.get('custom_tokens', '')
    custom_tokens = set(custom_tokens_str.split(',')) if custom_tokens_str else set()
    custom_tokens.discard('')  # Remove empty string
    custom_tokens.update(t for t in enabled_tokens if t and t not in DEFAULT_SYMBOLS)

    # Build response: Default tokens first, then custom tokens
    tokens = []

    # Default tokens (marked as is_default for frontend)
    for symbol in DEFAULT_SYMBOLS:
        tokens.append(TokenWatchlistItem(
            symbol=symbol,
            enabled=symbol in enabled_tokens,
            alias=TOKEN_ALIASES.get(symbol)
        ))

    # Custom tokens
    for symbol in sorted(custom_tokens):
        tokens.append(TokenWatchlistItem(
            symbol=symbol,
            enabled=symbol in enabled_tokens,
            alias=TOKEN_ALIASES.get(symbol, symbol.replace('USDT', ''))
        ))

    return TokenWatchlistResponse(tokens=tokens)


@router.post("/tokens", response_model=TokenWatchlistResponse)
async def update_token_watchlist(
    watchlist: TokenWatchlistUpdate,
    paper_service: PaperTradingService = Depends(get_paper_trading_service)
):
    """
    Update token watchlist - enable/disable signal generation per token.

    SOTA Phase 26: Per-token signal enable/disable
    """
    # Extract enabled tokens
    enabled_tokens = [t.symbol for t in watchlist.tokens if t.enabled]

    # Store as comma-separated string
    paper_service.repo.set_setting('enabled_tokens', ','.join(enabled_tokens))

    # Preserve non-default submitted symbols as custom tokens, otherwise they
    # disappear from GET /settings/tokens after being enabled.
    existing_custom = str(paper_service.repo.get_all_settings().get('custom_tokens', '') or '')
    custom_tokens = {t for t in existing_custom.split(',') if t}
    custom_tokens.update(t.symbol for t in watchlist.tokens if t.symbol not in DEFAULT_SYMBOLS)
    paper_service.repo.set_setting('custom_tokens', ','.join(sorted(custom_tokens)))

    # Return updated watchlist
    return await get_token_watchlist(paper_service)


# ==================== Symbol Blacklist Management ====================


class BlacklistAddRequest(BaseModel):
    """Request model for adding a symbol to blacklist"""
    symbol: str = Field(..., description="Symbol to blacklist (e.g., CYSUSDT)")
    reason: Optional[str] = Field(None, description="Reason for blacklisting")


class BlacklistResponse(BaseModel):
    """Response model for blacklist operations"""
    blacklist: List[str]
    count: int


@router.get("/blacklist", response_model=BlacklistResponse)
async def get_blacklist():
    """Get current symbol blacklist."""
    from ..dependencies import get_container
    container = get_container()
    quality_filter = container.get_symbol_quality_filter()
    bl = quality_filter.get_blacklist()
    return BlacklistResponse(blacklist=bl, count=len(bl))


@router.post("/blacklist", response_model=BlacklistResponse)
async def add_to_blacklist(request: BlacklistAddRequest):
    """Add a symbol to the blacklist. Persisted to DB (survives restart)."""
    symbol = request.symbol.upper().strip()
    if not symbol.endswith("USDT"):
        raise HTTPException(status_code=400, detail="Symbol must end with USDT")

    from ..dependencies import get_container
    container = get_container()
    quality_filter = container.get_symbol_quality_filter()

    quality_filter.add_to_blacklist(symbol)
    reason_msg = f" (reason: {request.reason})" if request.reason else ""
    logger.info(f"Blacklisted {symbol}{reason_msg}")

    bl = quality_filter.get_blacklist()
    return BlacklistResponse(blacklist=bl, count=len(bl))


@router.delete("/blacklist/{symbol}", response_model=BlacklistResponse)
async def remove_from_blacklist(symbol: str):
    """Remove a symbol from the blacklist. Change persisted to DB."""
    symbol = symbol.upper().strip()

    from ..dependencies import get_container
    container = get_container()
    quality_filter = container.get_symbol_quality_filter()

    if symbol not in quality_filter.get_blacklist():
        raise HTTPException(status_code=404, detail=f"{symbol} not in blacklist")

    quality_filter.remove_from_blacklist(symbol)
    logger.info(f"Removed {symbol} from blacklist")

    bl = quality_filter.get_blacklist()
    return BlacklistResponse(blacklist=bl, count=len(bl))


@router.get("/strategy")
async def get_strategy_parameters():
    """
    Get current strategy parameters (read-only).

    Returns VWAP, Bollinger Bands, and StochRSI configuration.
    Requirements: 6.4
    """
    return {
        "vwap": {
            "enabled": True,
            "description": "Volume Weighted Average Price"
        },
        "bollinger_bands": {
            "period": 20,
            "std_dev": 2.0,
            "description": "Bollinger Bands (20, 2)"
        },
        "stoch_rsi": {
            "rsi_period": 14,
            "stoch_period": 14,
            "k_period": 3,
            "d_period": 3,
            "description": "Stochastic RSI (3, 3, 14, 14)"
        }
    }


# SOTA Phase 26b: Add/Remove Custom Tokens

class AddTokenRequest(BaseModel):
    """Request to add a new token"""
    symbol: str = Field(..., description="Trading symbol (e.g., XRPUSDT)")
    alias: Optional[str] = Field(None, description="Display name (e.g., Ripple)")


class ValidateTokenResponse(BaseModel):
    """Response for token validation"""
    symbol: str
    valid: bool
    message: str


@router.get("/tokens/validate", response_model=ValidateTokenResponse)
async def validate_token(symbol: str):
    """
    Validate if a token symbol is supported by Binance Futures.

    SOTA Phase 26b: Binance API validation
    """
    import httpx

    symbol = symbol.upper().strip()

    # Format check
    if not symbol.endswith("USDT"):
        return ValidateTokenResponse(
            symbol=symbol,
            valid=False,
            message="Symbol must end with USDT (e.g., BTCUSDT)"
        )

    # Binance API validation
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://fapi.binance.com/fapi/v1/exchangeInfo",
                timeout=10.0
            )
            if response.status_code == 200:
                data = response.json()
                valid_symbols = [s["symbol"] for s in data.get("symbols", [])]
                if symbol in valid_symbols:
                    return ValidateTokenResponse(
                        symbol=symbol,
                        valid=True,
                        message="Token exists on Binance Futures"
                    )
                else:
                    return ValidateTokenResponse(
                        symbol=symbol,
                        valid=False,
                        message=f"Token {symbol} not found on Binance Futures"
                    )
    except Exception as e:
        # Fallback to format check only if Binance API fails
        return ValidateTokenResponse(
            symbol=symbol,
            valid=True,  # Allow if format OK but API unreachable
            message=f"Could not validate with Binance API. Format OK."
        )


class SearchTokensResponse(BaseModel):
    """Response for token search"""
    symbols: List[str]
    total: int


@router.get("/tokens/search")
async def search_binance_tokens(q: str = "", limit: int = 20):
    """
    Search Binance Futures symbols for autocomplete.

    SOTA Phase 26b: Token search feature
    """
    import httpx

    q = q.upper().strip()

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://fapi.binance.com/fapi/v1/exchangeInfo",
                timeout=10.0
            )
            if response.status_code == 200:
                data = response.json()
                all_symbols = [s["symbol"] for s in data.get("symbols", [])
                              if s["symbol"].endswith("USDT") and s.get("status") == "TRADING"]

                # Filter by search query
                if q:
                    matched = [s for s in all_symbols if q in s]
                else:
                    matched = all_symbols

                return SearchTokensResponse(
                    symbols=matched[:limit],
                    total=len(matched)
                )
            else:
                # Fallback for non-200 response
                return SearchTokensResponse(symbols=[], total=0)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Token search error: {e}")
        return SearchTokensResponse(symbols=[], total=0)


@router.post("/tokens/add", response_model=TokenWatchlistResponse)
async def add_token(
    request: AddTokenRequest,
    paper_service: PaperTradingService = Depends(get_paper_trading_service)
):
    """
    Add a new token to the watchlist.

    SOTA Phase 26b: Dynamic token management
    """
    symbol = request.symbol.upper().strip()

    # Validate format
    if not symbol.endswith("USDT"):
        raise HTTPException(status_code=400, detail="Symbol must end with USDT")

    # Get current custom tokens
    settings = paper_service.repo.get_all_settings()
    custom_tokens_str = settings.get('custom_tokens', '')
    custom_tokens = set(custom_tokens_str.split(',')) if custom_tokens_str else set()

    # Check if already exists
    if symbol in DEFAULT_SYMBOLS or symbol in custom_tokens:
        raise HTTPException(status_code=400, detail=f"Token {symbol} already exists")

    # Add to custom tokens
    custom_tokens.add(symbol)
    paper_service.repo.set_setting('custom_tokens', ','.join(custom_tokens))

    # Also enable it by default
    enabled_tokens_str = settings.get('enabled_tokens', '')
    enabled_tokens = set(enabled_tokens_str.split(',')) if enabled_tokens_str else set(DEFAULT_SYMBOLS)
    enabled_tokens.add(symbol)
    paper_service.repo.set_setting('enabled_tokens', ','.join(enabled_tokens))

    # Update TOKEN_ALIASES if alias provided
    if request.alias:
        TOKEN_ALIASES[symbol] = request.alias

    return await get_token_watchlist(paper_service)


@router.delete("/tokens/{symbol}", response_model=TokenWatchlistResponse)
async def remove_token(
    symbol: str,
    paper_service: PaperTradingService = Depends(get_paper_trading_service)
):
    """
    Remove a custom token from the watchlist.

    SOTA Phase 26b: Can only remove custom tokens, not default ones.
    """
    symbol = symbol.upper().strip()

    # Cannot remove default tokens
    if symbol in DEFAULT_SYMBOLS:
        raise HTTPException(status_code=400, detail=f"Cannot remove default token {symbol}")

    # Get current custom tokens
    settings = paper_service.repo.get_all_settings()
    custom_tokens_str = settings.get('custom_tokens', '')
    custom_tokens = set(custom_tokens_str.split(',')) if custom_tokens_str else set()

    # Check if exists
    if symbol not in custom_tokens:
        raise HTTPException(status_code=404, detail=f"Token {symbol} not found in custom tokens")

    # Remove from custom tokens
    custom_tokens.discard(symbol)
    paper_service.repo.set_setting('custom_tokens', ','.join(custom_tokens))

    # Also remove from enabled tokens
    enabled_tokens_str = settings.get('enabled_tokens', '')
    if enabled_tokens_str:
        enabled_tokens = set(enabled_tokens_str.split(','))
        enabled_tokens.discard(symbol)
        paper_service.repo.set_setting('enabled_tokens', ','.join(enabled_tokens))

    return await get_token_watchlist(paper_service)
