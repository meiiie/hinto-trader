"""
Live Trading API Router

Endpoints for controlling live trading from the frontend.
Provides start/stop, status, position management.

SAFETY: All endpoints check for testnet mode and require confirmation for production.
"""

import asyncio
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, List
import os
import logging

from src.config.runtime import (
    get_execution_mode,
    get_runtime_env,
    is_exchange_ordering_enabled,
    is_real_ordering_enabled,
)
from ...application.services.live_trading_service import (
    LiveTradingService,
    TradingMode,
    LiveTradeResult
)
from ...infrastructure.api.binance_futures_client import BinanceFuturesClient
from ..dependencies import get_container
from src.api.paper_order_enrichment import (
    build_signal_cache,
    calculate_distance_pct,
    enrich_paper_order,
    resolve_paper_order_current_price,
)

router = APIRouter(prefix="/live", tags=["Live Trading"])
logger = logging.getLogger(__name__)

# Global service instance (singleton pattern)
_trading_service: Optional[LiveTradingService] = None


def _get_live_trading_service() -> LiveTradingService:
    """
    Get LiveTradingService from DI Container.

    This ensures the same instance is used across the entire system
    (RealtimeService signal routing uses the same instance).
    """
    container = get_container()
    return container.get_live_trading_service()


def _get_regime_state_service():
    """Get observe-only regime state service from DI container."""
    container = get_container()
    return container.get_regime_state_service()


# ============================================================================
# Request/Response Models
# ============================================================================

class StartTradingRequest(BaseModel):
    mode: str = Field("testnet", description="Trading mode: paper, testnet, live")
    risk_per_trade: float = Field(0.01, ge=0.001, le=0.05, description="Risk per trade (0.01 = 1%)")
    max_positions: int = Field(5, ge=1, le=10, description="Maximum concurrent positions")
    max_leverage: int = Field(10, ge=1, le=20, description="Maximum leverage")
    confirm_production: bool = Field(False, description="Must be true for live mode")


class TradingStatusResponse(BaseModel):
    mode: str
    trading_enabled: bool
    balance: float
    initial_balance: float
    peak_balance: float
    active_positions: int
    max_positions: int
    pending_orders: int
    total_trades: int
    risk_per_trade: float
    max_leverage: int


class PositionResponse(BaseModel):
    symbol: str
    side: str
    size: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    margin: float
    roe_pct: float
    leverage: int
    liquidation_price: float


class ClosePositionRequest(BaseModel):
    symbol: str


class RegimeStateResponse(BaseModel):
    observed_at_utc: str
    as_of_utc: str
    cache_age_seconds: float
    router_version: str
    observe_only: bool
    preset: str
    reason: str
    live_policy: str
    would_trade: bool
    btc_trend_ema20: str
    btc_spread_pct: float
    regime_15m: str
    regime_confidence: float
    eligible_count: int
    ranked_universe_top: int
    recommended_universe_top: int
    eligible_symbols: List[str]
    recommended_symbol_side_blocks: List[str]


# ============================================================================
# Endpoints
# ============================================================================

@router.post("/toggle", summary="Toggle live trading on/off")
async def toggle_live_trading(enable: bool = Query(..., description="Enable or disable live trading")):
    """
    Toggle live trading on/off.

    This uses the DI Container's LiveTradingService which is shared
    with RealtimeService for signal routing.

    SAFETY: Requires explicit enable=true to turn on.
    """
    service = _get_live_trading_service()
    env = get_runtime_env()
    exchange_ordering = is_exchange_ordering_enabled(env)
    real_ordering = is_real_ordering_enabled(env)

    if enable:
        if not exchange_ordering:
            service.enable_trading = False
            logger.info("Paper mode requested /live/toggle enable; exchange execution remains disabled")
            return {
                "success": True,
                "enabled": False,
                "mode": service.mode.value,
                "execution_mode": get_execution_mode(env),
                "exchange_ordering_enabled": False,
                "real_ordering_enabled": False,
                "message": "Paper mode uses the local simulator; exchange order submission stays disabled.",
                "status": service.get_status()
            }

        # Safety check — use ENV variable (not legacy BINANCE_USE_TESTNET)
        if real_ordering:
            # Extra warning for production
            logger.warning("🔴 PRODUCTION LIVE TRADING ENABLED!")

        service.enable_trading = True
        logger.info(f"🟢 Live trading ENABLED (mode={service.mode.value})")
    else:
        service.enable_trading = False
        logger.info("🔴 Live trading DISABLED")

    return {
        "success": True,
        "enabled": service.enable_trading,
        "mode": service.mode.value,
        "execution_mode": get_execution_mode(env),
        "exchange_ordering_enabled": exchange_ordering,
        "real_ordering_enabled": real_ordering,
        "status": service.get_status()
    }


@router.get("/toggle-status", summary="Get current toggle status")
async def get_toggle_status():
    """Get whether live trading is currently enabled."""
    service = _get_live_trading_service()

    env = get_runtime_env()
    return {
        "enabled": service.enable_trading,
        "mode": service.mode.value,
        "execution_mode": get_execution_mode(env),
        "exchange_ordering_enabled": is_exchange_ordering_enabled(env),
        "real_ordering_enabled": is_real_ordering_enabled(env),
    }


# ════════════════════════════════════════════════════════════════════════════
# SOTA SAFE MODE ENDPOINTS (Jan 2026)
# Pattern: Two Sigma, Citadel - explicit user confirmation before trading
# Prevents ghost orders after backend restart
# ════════════════════════════════════════════════════════════════════════════

@router.get("/safe-mode/status", summary="Get SAFE MODE status")
async def get_safe_mode_status():
    """
    Get current SAFE MODE status for frontend modal.

    Frontend should call this on page load to check if modal should show.

    Returns:
        - safe_mode: True if in monitoring-only mode
        - enable_trading: True if trading is active
        - mode: "TRADING" or "SAFE_MODE"
        - pending_signals: Count of pending signals
        - active_positions: Count of open positions
    """
    service = _get_live_trading_service()
    status = service.get_trading_status()

    return {
        **status,
        "trading_mode": service.mode.value  # paper/testnet/live
    }


@router.post("/safe-mode/activate", summary="Activate trading from SAFE MODE")
async def activate_trading_from_safe_mode(
    clear_old_data: bool = Query(True, description="Clear old pending signals to prevent ghost orders")
):
    """
    Activate trading from SAFE MODE.

    Called when user clicks "Bắt Đầu Trade" button in frontend modal.

    SOTA Pattern (Two Sigma, Citadel):
    - After backend restart, system is in SAFE MODE (monitoring only)
    - User must explicitly activate trading
    - Old pending signals are cleared to prevent ghost orders

    Args:
        clear_old_data: If True, clear old pending signals and watermarks (recommended)

    Returns:
        Activation status with cleared data count
    """
    service = _get_live_trading_service()

    # Activate trading
    result = service.activate_trading(clear_old_data=clear_old_data)

    logger.info(f"🚀 SAFE MODE deactivated by user: {result}")

    return result


@router.post("/safe-mode/deactivate", summary="Enter SAFE MODE (pause trading)")
async def deactivate_to_safe_mode():
    """
    Deactivate trading and enter SAFE MODE.

    Use when you want to pause trading without stopping the backend.
    """
    service = _get_live_trading_service()
    result = service.deactivate_trading()

    logger.info(f"🛡️ Entered SAFE MODE by user request: {result}")

    return result


@router.get("/shark-tank/status", summary="Get Shark Tank coordinator status")
async def get_shark_tank_status():
    """
    Get Shark Tank coordinator status for Portfolio dashboard.

    SOTA: Mode-aware endpoint - returns data from appropriate source.

    Returns:
        - max_positions: Maximum allowed positions
        - current_positions: Currently open positions
        - pending_signals: Signals waiting in batch queue
        - available_margin: Current available margin
        - batch_interval: Seconds between batch executions
        - last_batch_time: Timestamp of last batch execution
        - trading_mode: Current trading mode (PAPER/TESTNET/LIVE)
    """
    import os

    container = get_container()
    shark_tank = container.get_shark_tank_coordinator()

    # Get SharkTank status
    status = shark_tank.get_status()

    # SOTA: Mode-aware position and margin retrieval
    mode = os.getenv("ENV", "paper").lower()

    if mode in ["testnet", "live"]:
        # TESTNET/LIVE: Use LiveTradingService
        service = _get_live_trading_service()
        current_positions = len(service.active_positions) if service else 0

        # SOTA FIX: Use cached balance to prevent blocking API call
        # _cached_balance is updated by get_portfolio() which runs in background
        available_margin = service._cached_balance if service else 0.0

        # SOTA FIX (Jan 2026): Use signal_tracker for pending count
        pending_count = len(service.signal_tracker) if (service and service.signal_tracker) else 0
        current_positions += pending_count

        trading_mode = "LIVE" if mode == "live" else "TESTNET"

        # SOTA: Use SettingsProvider for consistent config
        settings_provider = container.get_settings_provider()
        leverage = settings_provider.get_leverage()
        watched_tokens = settings_provider.get_watched_symbols_short()
    else:
        # PAPER: Use same DI container instance for consistency
        paper_service = container.get_paper_trading_service()
        current_positions = len(paper_service.get_positions()) + len(paper_service.repo.get_pending_orders())
        # SOTA FIX: Use get_available_balance() for correct margin calculation
        # Available = Wallet Balance - Used Margin (same logic as Live mode)
        available_margin = paper_service.get_available_balance(current_price=0)
        trading_mode = "PAPER"

        # SOTA (Jan 2026): Use SettingsProvider for consistent config across all modes
        settings_provider = container.get_settings_provider()
        leverage = settings_provider.get_leverage()
        watched_tokens = settings_provider.get_watched_symbols_short()

    # SOTA: Override max_positions from SettingsProvider for consistent slot display
    settings_provider = container.get_settings_provider()
    max_positions = settings_provider.get_max_positions()

    # SOTA (Jan 2026): Enhanced response for Shark Tank Watchlist UI
    # Extract detailed position and pending order info
    position_symbols = []
    pending_symbols = []

    if mode in ["testnet", "live"]:
        # TESTNET/LIVE: Extract from LiveTradingService
        if service:
            # Open positions - FuturesPosition is a dataclass, use attribute access
            for sym, pos in service.active_positions.items():
                # Determine side from position_amt (positive = LONG, negative = SHORT)
                side = "LONG" if pos.position_amt > 0 else "SHORT"

                # SOTA FIX (Jan 2026): Get MonitoredPosition for breakeven display
                monitored = None
                if service.position_monitor:
                    monitored = service.position_monitor.get_position(sym)

                position_symbols.append({
                    "symbol": sym.replace("USDT", ""),
                    "side": side,
                    "pnl": pos.unrealized_pnl if hasattr(pos, 'unrealized_pnl') else 0,
                    # SOTA (Jan 2026): Add entry_price and quantity for realtime PnL calculation
                    "entry_price": pos.entry_price if hasattr(pos, 'entry_price') else 0,
                    "quantity": abs(pos.position_amt) if hasattr(pos, 'position_amt') else 0,
                    # SOTA FIX (Jan 2026): Breakeven display fields
                    "current_sl": monitored.current_sl if monitored else 0,
                    "initial_sl": monitored.initial_sl if monitored else 0,
                    "phase": monitored.phase.value if monitored else "unknown",
                    "is_breakeven": monitored.is_breakeven if monitored else False
                })

            # SOTA FIX (Jan 2026): Read pending from LocalSignalTracker, NOT service.pending_orders
            # LocalSignalTracker is the single source of truth for pending signals
            if hasattr(service, 'signal_tracker') and service.signal_tracker:
                # Sort by confidence for ranking display
                pending_list = list(service.signal_tracker.get_all_pending().items())
                pending_list.sort(key=lambda x: x[1].confidence, reverse=True)

                for rank, (sym, signal) in enumerate(pending_list, start=1):
                    current_price = signal.last_known_price or service._cached_prices.get(sym, 0)
                    target_price = signal.target_price
                    distance_pct = abs(current_price - target_price) / target_price * 100 if target_price > 0 else 0
                    is_locked = distance_pct < 0.2  # PROXIMITY SENTRY: 0.2% threshold

                    pending_symbols.append({
                        "symbol": sym.replace("USDT", ""),
                        "side": "BUY" if signal.direction.value == "LONG" else "SELL",
                        "entry_price": target_price,
                        "distance_pct": round(distance_pct, 2),
                        "locked": is_locked,
                        "confidence": round(signal.confidence, 2),  # NEW: For ranking display
                        "rank": rank  # NEW: Position in confidence ranking
                    })
    else:
        # PAPER: Extract from PaperTradingService
        for pos in paper_service.get_positions():
            position_symbols.append({
                "symbol": pos.symbol.replace("USDT", ""),
                "side": pos.side,
                "pnl": pos.unrealized_pnl if hasattr(pos, 'unrealized_pnl') else 0,
                # SOTA (Jan 2026): Add entry_price and quantity for realtime PnL calculation
                "entry_price": pos.entry_price if hasattr(pos, 'entry_price') else 0,
                "quantity": pos.quantity if hasattr(pos, 'quantity') else (pos.size if hasattr(pos, 'size') else 0)
            })

        pending_orders = paper_service.repo.get_pending_orders()
        signal_cache = build_signal_cache(pending_orders, container.get_signal_lifecycle_service())
        pending_with_metadata = [
            (order, enrich_paper_order(order, signal_cache))
            for order in pending_orders
        ]
        pending_with_metadata.sort(
            key=lambda item: item[1].get("confidence") or 0,
            reverse=True
        )

        for rank, (order, metadata) in enumerate(pending_with_metadata, start=1):
            current_price = resolve_paper_order_current_price(order, paper_service.market_data_repo)
            distance_pct = calculate_distance_pct(order.entry_price, current_price)

            pending_symbols.append({
                "symbol": order.symbol.replace("USDT", ""),
                "side": order.side,
                "entry_price": order.entry_price,
                "current_price": current_price,
                "distance_pct": round(distance_pct, 2) if distance_pct is not None else None,
                "locked": distance_pct is not None and distance_pct < 0.2,
                "confidence": metadata.get("confidence"),
                "confidence_level": metadata.get("confidence_level"),
                "risk_reward_ratio": metadata.get("risk_reward_ratio"),
                "rank": rank
            })

    return {
        **status,
        "max_positions": max_positions,  # SOTA: Override from provider
        "current_positions": current_positions,
        "available_slots": max(0, max_positions - current_positions),
        "available_margin": available_margin,
        "trading_mode": trading_mode,
        "leverage": leverage,
        "watched_tokens": watched_tokens,
        # SOTA (Jan 2026): Enhanced data for Shark Tank Watchlist UI
        "position_symbols": position_symbols,
        "pending_symbols": pending_symbols
    }


@router.post("/start", summary="Start live trading")
async def start_trading(request: StartTradingRequest):
    """
    Start live trading service.

    Modes:
    - paper: Internal simulation (no real orders)
    - testnet: Binance testnet (demo money)
    - live: Production (REAL MONEY - requires confirmation)
    """
    global _trading_service

    # Parse mode
    try:
        mode = TradingMode(request.mode.lower())
    except ValueError:
        raise HTTPException(400, f"Invalid mode: {request.mode}. Use: paper, testnet, live")

    # Safety check for production
    if mode == TradingMode.LIVE:
        if not request.confirm_production:
            raise HTTPException(
                400,
                "⚠️ PRODUCTION MODE requires confirm_production=true. "
                "This will use REAL MONEY!"
            )

        # Double-check env variable — use ENV (not legacy BINANCE_USE_TESTNET)
        env_mode = os.getenv("ENV", "paper").lower()
        use_testnet = (env_mode == "testnet")
        if use_testnet:
            raise HTTPException(
                400,
                "ENV=testnet in .env. Change to 'live' for production."
            )

    try:
        # Get order_repo from container for TP/SL persistence
        container = get_container()
        env = request.mode.lower()
        order_repo = container.get_order_repository(env if env != "paper" else "testnet")

        _trading_service = LiveTradingService(
            mode=mode,
            risk_per_trade=request.risk_per_trade,
            max_positions=request.max_positions,
            max_leverage=request.max_leverage,
            order_repo=order_repo  # SOTA (Jan 2026): For TP/SL persistence
        )

        return {
            "success": True,
            "message": f"Trading started in {mode.value} mode",
            "status": _trading_service.get_status()
        }

    except Exception as e:
        logger.error(f"Failed to start trading: {e}")
        raise HTTPException(500, str(e))


@router.post("/stop", summary="Stop live trading")
async def stop_trading(close_positions: bool = Query(False, description="Close all positions before stopping")):
    """Stop live trading and optionally close all positions."""
    global _trading_service

    if not _trading_service:
        raise HTTPException(400, "Trading service not running")

    try:
        if close_positions:
            results = _trading_service.close_all_positions()
            closed_count = sum(1 for r in results if r.success)
            logger.info(f"Closed {closed_count} positions")

        _trading_service.enable_trading = False

        status = _trading_service.get_status()
        _trading_service = None

        return {
            "success": True,
            "message": "Trading stopped",
            "final_status": status
        }

    except Exception as e:
        logger.error(f"Error stopping trading: {e}")
        raise HTTPException(500, str(e))


@router.get("/status", response_model=TradingStatusResponse, summary="Get trading status")
async def get_status():
    """Get current trading service status."""
    if not _trading_service:
        return TradingStatusResponse(
            mode="stopped",
            trading_enabled=False,
            balance=0,
            initial_balance=0,
            peak_balance=0,
            active_positions=0,
            max_positions=0,
            pending_orders=0,
            total_trades=0,
            risk_per_trade=0,
            max_leverage=0
        )

    status = _trading_service.get_status()
    return TradingStatusResponse(**status)


@router.get("/regime-state", response_model=RegimeStateResponse, summary="Get observe-only regime state")
async def get_regime_state(
    force_refresh: bool = Query(False, description="Bypass the 60s cache and recompute now"),
):
    """
    Return the shared observe-only regime snapshot used for research parity.

    This endpoint does not change live execution. It exposes the same state
    contract that BroSubSoul can later consume instead of inferring market
    direction independently.
    """
    service = _get_regime_state_service()
    snapshot = await service.get_snapshot(force_refresh=force_refresh)
    return RegimeStateResponse(**snapshot)


@router.get("/positions", response_model=List[PositionResponse], summary="Get open positions")
async def get_positions():
    """Get all open positions."""
    # Use DI Container service (works with /toggle)
    service = _get_live_trading_service()
    if not service.client:
        raise HTTPException(400, "Trading service not connected to Binance")

    # SOTA: Use async non-blocking call to prevent Event Loop freeze
    positions = await service.get_all_positions_async()

    return [
        PositionResponse(
            symbol=p.symbol,
            side="LONG" if p.position_amt > 0 else "SHORT",
            size=abs(p.position_amt),
            entry_price=p.entry_price,
            current_price=p.mark_price,
            unrealized_pnl=p.unrealized_pnl,
            margin=p.margin,
            roe_pct=(p.unrealized_pnl / p.margin * 100) if p.margin > 0 else 0.0,
            leverage=p.leverage,
            liquidation_price=p.liquidation_price
        )
        for p in positions
    ]


@router.post("/close", summary="Close a position")
async def close_position(request: ClosePositionRequest):
    """Close a specific position."""
    service = _get_live_trading_service()
    if not service or not service.client:
        raise HTTPException(400, "Trading service not connected")

    # SOTA FIX: Run blocking close operation in thread pool
    result = await asyncio.to_thread(service.close_position, request.symbol)

    if result.success:
        return {"success": True, "message": f"Position {request.symbol} closed"}
    else:
        raise HTTPException(400, result.error or "Failed to close position")


@router.post("/close-all", summary="Close all positions")
async def close_all_positions():
    """Emergency close all positions."""
    service = _get_live_trading_service()
    if not service or not service.client:
        raise HTTPException(400, "Trading service not connected")

    # SOTA FIX: Run blocking close operation in thread pool
    results = await asyncio.to_thread(service.close_all_positions)

    requested = len(results)
    closed = sum(1 for r in results if r.success)
    failed = sum(1 for r in results if not r.success)

    if requested == 0:
        detail = "no open positions"
        success = True
    elif failed == 0:
        detail = f"closed {closed}/{requested} positions"
        success = True
    elif closed == 0:
        detail = f"failed to close all {requested} positions"
        success = False
    else:
        detail = f"partial close: {closed}/{requested} positions closed, {failed} failed"
        success = False

    return {
        "success": success,
        "requested": requested,
        "closed": closed,
        "failed": failed,
        "detail": detail,
    }


@router.get("/balance", summary="Get account balance")
async def get_balance():
    """Get current account balance from the active execution venue."""
    try:
        # Use ENV variable (not legacy BINANCE_USE_TESTNET which defaults to testnet)
        env_mode = get_runtime_env()
        if not is_exchange_ordering_enabled(env_mode):
            container = get_container()
            paper_service = container.get_paper_trading_service()
            wallet = paper_service.get_wallet_balance()
            return {
                "usdt_available": wallet,
                "all_assets": [
                    {
                        "asset": "USDT",
                        "wallet_balance": wallet,
                        "available_balance": paper_service.get_available_balance(0),
                    }
                ],
                "execution_mode": get_execution_mode(env_mode),
                "exchange_ordering_enabled": False,
                "real_ordering_enabled": False,
            }

        use_testnet = (env_mode == "testnet")

        # SOTA FIX: Run blocking API calls in thread pool to prevent event loop freeze
        def fetch_balance():
            client = BinanceFuturesClient(use_testnet=use_testnet)
            balances = client.get_account_balance()
            usdt = client.get_usdt_balance()
            return balances, usdt

        balances, usdt = await asyncio.to_thread(fetch_balance)

        return {
            "usdt_available": usdt,
            "all_assets": [
                {
                    "asset": b.asset,
                    "wallet_balance": b.wallet_balance,
                    "available_balance": b.available_balance
                }
                for b in balances
            ]
        }

    except Exception as e:
        logger.error(f"Failed to get balance: {e}")
        raise HTTPException(500, str(e))


@router.get("/test-connection", summary="Test exchange connection")
async def test_connection():
    """Test connection to Binance API."""
    try:
        # Use ENV variable (not legacy BINANCE_USE_TESTNET which defaults to testnet)
        env_mode = os.getenv("ENV", "paper").lower()
        use_testnet = (env_mode == "testnet")
        client = BinanceFuturesClient(use_testnet=use_testnet)

        ping = client.ping()
        server_time = client.get_server_time()
        btc_price = client.get_ticker_price("BTCUSDT")

        return {
            "success": True,
            "testnet": use_testnet,
            "ping": ping,
            "server_time": server_time,
            "btc_price": btc_price
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
