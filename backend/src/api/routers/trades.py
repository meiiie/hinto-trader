"""
Trades Router - Trade History and Performance API

**Feature: desktop-trading-dashboard**
**Validates: Requirements 7.1, 7.2, 7.3**

Provides:
- Paginated trade history endpoint
- Performance metrics endpoint
- Portfolio status endpoint
"""

from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

from src.api.dependencies import (
    get_paper_trading_service,
    get_realtime_service,
    get_live_trading_service,
    get_trading_mode,
    get_signal_lifecycle_service  # SOTA: For pending signals
)
from src.application.services.paper_trading_service import PaperTradingService
from src.application.services.realtime_service import RealtimeService
from src.application.services.signal_lifecycle_service import SignalLifecycleService
from src.api.paper_order_enrichment import (
    build_signal_cache,
    calculate_distance_pct,
    enrich_paper_order,
    resolve_paper_order_current_price,
)

router = APIRouter(
    prefix="/trades",
    tags=["trades"]
)

logger = logging.getLogger(__name__)


@router.get("/history")
async def get_trade_history(
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    symbol: Optional[str] = Query(default=None, description="Filter by symbol (e.g., BTCUSDT)"),
    side: Optional[str] = Query(default=None, description="Filter by side (LONG/SHORT)"),
    pnl_filter: Optional[str] = Query(default=None, description="Filter by P&L: 'profit' or 'loss'"),
    paper_service: PaperTradingService = Depends(get_paper_trading_service)
):
    """
    Get paginated trade history with optional filters.

    SOTA: Mode-aware endpoint with 3-way separation.
    - LIVE mode: Returns trades from Binance Mainnet API
    - TESTNET mode: Returns trades from Binance Testnet API
    - PAPER mode: Returns trades from SQLite
    """
    # Check trading mode
    mode = get_trading_mode()

    # LIVE MODE: Get trades from Binance Mainnet
    if mode == "LIVE":
        live_service = get_live_trading_service()
        # SOTA FIX: Offload blocking API call to thread
        import asyncio
        result = await asyncio.to_thread(live_service.get_trade_history, limit=limit * page, symbol=symbol)
        result['trading_mode'] = 'LIVE'
        logger.info(f"🔴 LIVE History: {len(result.get('trades', []))} trades")
        return result

    # TESTNET MODE: Get trades from Binance Testnet
    if mode == "TESTNET":
        live_service = get_live_trading_service()
        # SOTA FIX: Offload blocking API call to thread
        import asyncio
        result = await asyncio.to_thread(live_service.get_trade_history, limit=limit * page, symbol=symbol)
        result['trading_mode'] = 'TESTNET'
        logger.info(f"🧪 TESTNET History: {len(result.get('trades', []))} trades")
        return result

    # PAPER MODE: Get trades from SQLite
    # SOTA FIX: Offload blocking API call to thread
    import asyncio
    result = await asyncio.to_thread(
        paper_service.get_trade_history,
        page=page, limit=limit,
        symbol=symbol, side=side, pnl_filter=pnl_filter
    )
    response = result.to_dict()
    response['trading_mode'] = 'PAPER'
    return response


@router.get("/export")
async def export_trades(
    symbol: Optional[str] = Query(default=None, description="Filter by symbol"),
    side: Optional[str] = Query(default=None, description="Filter by side (LONG/SHORT)"),
    pnl_filter: Optional[str] = Query(default=None, description="Filter by P&L"),
    page_from: int = Query(default=1, ge=1, description="Start page"),
    page_to: Optional[int] = Query(default=None, description="End page (None = all)"),
    paper_service: PaperTradingService = Depends(get_paper_trading_service)
):
    """
    Export trades for CSV download.

    **SOTA Phase 24c: Bulk export with filters**

    Returns all matching trades for the specified page range.
    If page_to is None, returns ALL matching trades (for full export).

    Args:
        symbol: Filter by trading pair
        side: Filter by trade side
        pnl_filter: Filter by result
        page_from: Starting page
        page_to: Ending page (None = all pages)

    Returns:
        List of all matching trades for export
    """
    try:
        def _do_export_sync():
            # Get first page to determine total pages
            first_result = paper_service.get_trade_history(
                page=1, limit=100,
                symbol=symbol, side=side, pnl_filter=pnl_filter
            )

            total_pages = first_result.total_pages
            end_page = page_to if page_to else total_pages

            all_trades = []
            for page in range(page_from, min(end_page + 1, total_pages + 1)):
                result = paper_service.get_trade_history(
                    page=page, limit=100,
                    symbol=symbol, side=side, pnl_filter=pnl_filter
                )
                for trade in result.trades:
                    all_trades.append(trade.to_dict())
            return {
                "trades": all_trades,
                "total": len(all_trades),
                "page_from": page_from,
                "page_to": end_page,
                "filters": {
                    "symbol": symbol,
                    "side": side,
                    "pnl_filter": pnl_filter
                }
            }

        import asyncio
        return await asyncio.to_thread(_do_export_sync)
    except Exception as e:
        logger.error(f"Export trades failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/performance")
async def get_performance_metrics(
    days: int = Query(default=7, ge=1, le=365, description="Number of days to analyze"),
    paper_service: PaperTradingService = Depends(get_paper_trading_service)
):
    """
    Get performance metrics for the specified period.

    SOTA: Mode-aware endpoint with 3-way separation.
    - LIVE mode: Calculate from Binance Mainnet trade history
    - TESTNET mode: Calculate from Binance Testnet trade history
    - PAPER mode: Calculate from SQLite trades
    """
    mode = get_trading_mode()

    # LIVE MODE: Calculate from Binance Mainnet
    if mode == "LIVE":
        live_service = get_live_trading_service()
        # SOTA FIX: Offload blocking API call
        import asyncio
        metrics = await asyncio.to_thread(live_service.get_performance, days=days)
        metrics['trading_mode'] = 'LIVE'
        logger.info(f"🔴 LIVE Performance: {metrics.get('total_trades', 0)} trades")
        return metrics

    # TESTNET MODE: Calculate from Binance Testnet
    if mode == "TESTNET":
        live_service = get_live_trading_service()
        # SOTA FIX: Offload blocking API call
        import asyncio
        metrics = await asyncio.to_thread(live_service.get_performance, days=days)
        metrics['trading_mode'] = 'TESTNET'
        logger.info(f"🧪 TESTNET Performance: {metrics.get('total_trades', 0)} trades")
        return metrics

    # PAPER MODE: Calculate from SQLite
    import asyncio
    metrics = await asyncio.to_thread(paper_service.calculate_performance, days=days)
    response = metrics.to_dict()
    response['trading_mode'] = 'PAPER'
    return response


@router.get("/portfolio")
async def get_portfolio(
    paper_service: PaperTradingService = Depends(get_paper_trading_service)
):
    """
    Get current portfolio status including pending orders.

    SOTA: Mode-aware endpoint - returns data from appropriate source.
    - LIVE mode: Real data from Binance API
    - PAPER mode: Simulated data from SQLite
    """
    # Check current trading mode
    mode = get_trading_mode()

    if mode in ["LIVE", "TESTNET"]:
        # SOTA: Try cached balance from UserDataStream first (instant)
        from ..dependencies import get_container
        container = get_container()
        stream = container.get_user_data_stream()

        cached_data = None
        if stream and stream.is_connected:
            # SOTA: Use account-level totals for accurate values
            cached_data = {
                "wallet": stream.total_wallet_balance,
                "unrealized_pnl": stream.total_unrealized_pnl,
                "margin": stream.total_margin_balance,
                "available": stream.total_available_balance,
                "source": "stream"
            }

        # SOTA FIX: Use async version to prevent blocking event loop
        # Root cause of 35s lag: sync get_portfolio() blocks asyncio while making API calls
        live_service = get_live_trading_service()

        # SOTA CRITICAL FIX (Jan 2026): Add timeout to prevent testnet delays from blocking UI
        # Problem: Testnet API timeout (10s) x retries (3) = 30-46s total block time
        # Solution: Fail fast with 10s timeout and return fallback data
        import asyncio
        PORTFOLIO_TIMEOUT = 10  # seconds - fail fast

        try:
            portfolio = await asyncio.wait_for(
                live_service.get_portfolio_async(),
                timeout=PORTFOLIO_TIMEOUT
            )
        except asyncio.TimeoutError:
            logger.warning(f"⏱️ Portfolio fetch timed out after {PORTFOLIO_TIMEOUT}s - using fallback")
            # Return minimal fallback data so frontend doesn't break
            portfolio = {
                'balance': 0,
                'equity': 0,
                'unrealized_pnl': 0,
                'realized_pnl': 0,
                'open_positions_count': 0,
                'open_positions': [],
                'pending_orders': [],
                'error': 'timeout',
                'message': f'Binance API timeout after {PORTFOLIO_TIMEOUT}s - please retry'
            }


        # Override wallet/equity from cached data if available (faster response)
        # SOTA FIX (Feb 2026): Do NOT override unrealized_pnl from stream!
        # ACCOUNT_UPDATE 'up' field is STALE (snapshot at order time, not real-time)
        # REST API /fapi/v2/positionRisk returns accurate mark-price-based PnL
        if cached_data and cached_data["wallet"] > 0:
            portfolio['balance'] = cached_data['wallet']
            # portfolio['unrealized_pnl'] = cached_data['unrealized_pnl']  # ← REMOVED: Stale!
            # Keep REST API value for unrealized_pnl (accurate)
            portfolio['equity'] = portfolio['balance'] + portfolio.get('unrealized_pnl', 0)
            portfolio['available_balance'] = cached_data['available']
            portfolio['margin_balance'] = portfolio['equity']
            portfolio['balance_source'] = 'stream+rest'  # hybrid source
        else:
            portfolio['balance_source'] = 'rest'

        # Add trading_mode indicator
        portfolio['trading_mode'] = mode
        portfolio['is_live'] = mode == "LIVE"
        portfolio['is_testnet'] = mode == "TESTNET"
        portfolio['stream_connected'] = stream.is_connected if stream else False

        # SOTA FIX: Add pending_orders from LocalSignalTracker (matches Paper mode format)
        try:
            pending_from_tracker = []
            if live_service.signal_tracker:
                from datetime import datetime

                # ZOMBIE KILLER: Cleanup expired signals BEFORE reading
                live_service.signal_tracker.cleanup_expired()

                for symbol, sig in live_service.signal_tracker.get_all_pending().items():
                    # Calculate TTL remaining
                    ttl_remaining = 0
                    if sig.expires_at:
                        ttl_remaining = max(0, int((sig.expires_at - datetime.now()).total_seconds()))

                    pending_from_tracker.append({
                        "id": sig.signal_id or f"local_{symbol}",
                        "signal_id": (sig.signal_id or symbol)[:8],
                        "symbol": symbol,
                        "side": sig.direction.value,  # LONG/SHORT
                        "entry_price": sig.target_price,
                        "size": sig.quantity,
                        "margin": sig.quantity * sig.target_price / sig.leverage if sig.leverage > 0 else 0,
                        "leverage": sig.leverage,
                        "stop_loss": sig.stop_loss,
                        "take_profits": [sig.take_profit] if sig.take_profit else [],
                        "created_at": sig.created_at.isoformat() if sig.created_at else None,
                        "expires_at": sig.expires_at.isoformat() if sig.expires_at else None,
                        "ttl_seconds": ttl_remaining,
                        "is_live": mode == "LIVE"
                    })
            portfolio['pending_orders'] = pending_from_tracker
        except Exception as e:
            logger.warning(f"Failed to get LocalSignalTracker pending: {e}")
            portfolio['pending_orders'] = []

        # SOTA: Add pending signals to portfolio
        try:
            signal_service = get_signal_lifecycle_service()
            pending_signals = signal_service.get_pending_signals() if signal_service else []
            portfolio['pending_signals'] = [
                {
                    'id': s.id,
                    'symbol': s.symbol,
                    'signal_type': s.signal_type.value,
                    'entry_price': s.entry_price,
                    'stop_loss': s.stop_loss,
                    'confidence': s.confidence,
                    'generated_at': s.generated_at.isoformat() if s.generated_at else None
                }
                for s in pending_signals[:10]  # Limit to 10
            ]
            portfolio['pending_signals_count'] = len(pending_signals)
        except Exception as e:
            logger.warning(f"Failed to get pending signals: {e}")
            portfolio['pending_signals'] = []
            portfolio['pending_signals_count'] = 0

        logger.info(f"{'🔴' if mode == 'LIVE' else '🧪'} {mode} Portfolio: {portfolio.get('open_positions_count', 0)} positions, Balance: ${portfolio.get('balance', 0):.2f}, PnL: ${portfolio.get('unrealized_pnl', 0):.2f} (source: {portfolio.get('balance_source', 'unknown')})")
        return portfolio

    # PAPER MODE: Get simulated data from SQLite
    # SOTA FIX: Cleanup expired pending orders BEFORE fetching
    def _cleanup_and_get_paper_portfolio_sync():
        from datetime import datetime
        TTL_SECONDS = 50 * 60  # SOTA SYNC: 50 min matches backtest default

        # ZOMBIE KILLER: Expire old pending orders
        all_pending = paper_service.repo.get_pending_orders()
        for order in all_pending:
            if order.open_time:
                age_seconds = (datetime.now() - order.open_time).total_seconds()
                if age_seconds > TTL_SECONDS:
                    order.status = 'CANCELLED'
                    order.exit_reason = 'TTL_EXPIRED'
                    order.close_time = datetime.now()
                    paper_service.repo.update_order(order)

                    # Release locked margin
                    paper_service._locked_in_orders -= order.margin
                    paper_service._locked_in_orders = max(0.0, paper_service._locked_in_orders)
                    paper_service._mark_signal_expired(order.signal_id)
                    logger.info(f"⏰ [PORTFOLIO] TTL EXPIRED: {order.symbol} (age={age_seconds/60:.1f}min)")

        # Now get fresh data
        port = paper_service.get_portfolio()
        pos = paper_service.get_positions_with_pnl()
        pending = paper_service.repo.get_pending_orders()  # Fresh after cleanup
        return port, pos, pending

    import asyncio
    portfolio, enriched_positions, pending_orders = await asyncio.to_thread(_cleanup_and_get_paper_portfolio_sync)

    # SOTA FIX: Import datetime at proper scope for ttl_seconds calculation
    from datetime import datetime as dt_now
    from src.config import get_execution_mode, is_paper_real_enabled
    from src.trading_contract import PRODUCTION_ORDER_TTL_MINUTES

    execution_mode = get_execution_mode("paper")
    paper_real = is_paper_real_enabled("paper")
    signal_service = get_signal_lifecycle_service()
    try:
        signal_cache = await asyncio.to_thread(build_signal_cache, pending_orders, signal_service)
    except Exception as e:
        logger.warning(f"Failed to build paper order signal cache: {e}")
        signal_cache = {}

    def _get_paper_order_current_price(order):
        return resolve_paper_order_current_price(order, paper_service.market_data_repo)

    def _get_paper_order_distance_pct(order, current_price):
        return calculate_distance_pct(order.entry_price, current_price)

    def _format_paper_pending_order(order):
        current_price = _get_paper_order_current_price(order)
        return {
            "id": order.id,
            "signal_id": order.id[:8],
            "symbol": order.symbol,
            "side": order.side,
            "entry_price": order.entry_price,
            "size": order.quantity,
            "margin": order.margin,
            "leverage": order.leverage,
            "stop_loss": order.stop_loss,
            "take_profits": [order.take_profit] if order.take_profit else [],
            "created_at": order.open_time.isoformat() if order.open_time else None,
            "expires_at": None,
            "ttl_seconds": max(0, PRODUCTION_ORDER_TTL_MINUTES * 60 - int((dt_now.now() - order.open_time).total_seconds())) if order.open_time else 0,
            "is_live": False,
            "current_price": current_price,
            "distance_pct": _get_paper_order_distance_pct(order, current_price),
            **enrich_paper_order(order, signal_cache)
        }

    # Build response with enriched positions and pending orders
    response = {
        'balance': portfolio.balance,
        'equity': portfolio.equity,
        'unrealized_pnl': portfolio.unrealized_pnl,
        'realized_pnl': portfolio.realized_pnl,
        'open_positions_count': len(enriched_positions),
        'open_positions': enriched_positions,
        'pending_orders': [_format_paper_pending_order(order) for order in pending_orders],
        'trading_mode': 'PAPER',
        'is_live': False,
        'execution_mode': execution_mode,
        'is_paper_real': paper_real,
        'real_ordering_enabled': False,
        'market_data_source': 'binance_mainnet_live' if paper_real else 'local_simulation',
        'execution_venue': 'local_paper_simulator',
    }

    # SOTA: Add pending signals to PAPER portfolio
    try:
        pending_signals = signal_service.get_pending_signals() if signal_service else []
        active_signal_ids = {order.signal_id for order in pending_orders if order.signal_id}

        if signal_service:
            stale_signals = [s for s in pending_signals if s.id not in active_signal_ids]
            for stale in stale_signals:
                signal_service.mark_expired(stale.id)

        pending_signals = [s for s in pending_signals if s.id in active_signal_ids]
        response['pending_signals'] = [
            {
                'id': s.id,
                'symbol': s.symbol,
                'signal_type': s.signal_type.value,
                'entry_price': s.entry_price,
                'stop_loss': s.stop_loss,
                'confidence': s.confidence,
                'generated_at': s.generated_at.isoformat() if s.generated_at else None
            }
            for s in pending_signals[:10]  # Limit to 10
        ]
        response['pending_signals_count'] = len(pending_signals)
    except Exception as e:
        logger.warning(f"Failed to get pending signals: {e}")
        response['pending_signals'] = []
        response['pending_signals_count'] = 0

    logger.info(f"📝 PAPER Portfolio: {len(enriched_positions)} positions, {len(pending_orders)} pending, {len(response.get('pending_signals', []))} signals")

    return response


@router.post("/close/{position_id}")
async def close_position(
    position_id: str,
    service: RealtimeService = Depends(get_realtime_service),
    paper_service: PaperTradingService = Depends(get_paper_trading_service)
):
    """
    Manually close a position.

    SOTA: Mode-aware endpoint.
    - LIVE/TESTNET mode: Closes real position on Binance
    - PAPER mode: Closes simulated position in SQLite

    Args:
        position_id: ID of the position to close (or symbol for LIVE mode)

    Returns:
        Success status
    """
    mode = get_trading_mode()

    # LIVE/TESTNET MODE: Close real position on Binance
    if mode in ["LIVE", "TESTNET"]:
        live_service = get_live_trading_service()

        # For LIVE mode, position_id is formatted as "live_{symbol}"
        if position_id.startswith("live_"):
            symbol = position_id.replace("live_", "")
        else:
            symbol = position_id.upper()

        try:
            # SOTA FIX: Use LiveTradingService.close_position() which has MARKET_LOT_SIZE split logic
            # Direct client.close_position() bypasses quantity splitting for large orders
            result = live_service.close_position(symbol)

            if result.success:
                logger.info(f"🔴 LIVE position closed: {symbol} | Result: {result}")
                return {
                    "success": True,
                    "message": f"Position closed: {symbol}",
                    "trading_mode": mode
                }
            else:
                logger.error(f"❌ Failed to close position: {result.error}")
                return {"success": False, "error": result.error}

        except Exception as e:
            logger.error(f"❌ Failed to close position: {e}")
            return {"success": False, "error": str(e)}

    # PAPER MODE: Close simulated position
    # SOTA FIX: Use repo.get_order() - the same method close_position_by_id uses internally
    position = paper_service.repo.get_order(position_id)
    if not position or position.status != 'OPEN':
        return {"success": False, "error": "Position not found or not open"}

    # Get current price for this specific symbol
    current_price = 0.0

    # 1. Try Market Data Repo (Primary Source - correct symbol pricing)
    if paper_service.market_data_repo:
        current_price = paper_service.market_data_repo.get_realtime_price(position.symbol)

    # 2. Fallback: RealtimeService ONLY if symbols match (avoid cross-contamination)
    if current_price == 0.0 and service.symbol == position.symbol:
        latest_candle = service.get_latest_data('1m')
        current_price = latest_candle.close if latest_candle else 0.0

    # 3. Final check
    if current_price <= 0:
        return {"success": False, "error": f"Cannot determine current price for {position.symbol}"}

    success = paper_service.close_position_by_id(position_id, current_price, "MANUAL_CLOSE")

    return {
        "success": success,
        "message": "Position closed" if success else "Position not found or already closed",
        "trading_mode": "PAPER"
    }


@router.get("/pending")
async def get_pending_orders(
    paper_service: PaperTradingService = Depends(get_paper_trading_service)
):
    """
    Get all pending (unfilled) orders.

    SOTA: Mode-aware endpoint.
    - LIVE mode: Returns open orders from Binance
    - PAPER mode: Returns pending orders from SQLite
    """
    mode = get_trading_mode()

    if mode in ["LIVE", "TESTNET"]:
        live_service = get_live_trading_service()
        if live_service.client:
            # SOTA FIX: Wrap blocking API call in asyncio.to_thread
            import asyncio
            open_orders = await asyncio.to_thread(live_service.client.get_open_orders)
            from datetime import datetime
            formatted = [
                {
                    "id": str(o.get('orderId') if isinstance(o, dict) else o.order_id),
                    "symbol": o.get('symbol') if isinstance(o, dict) else o.symbol,
                    "side": o.get('side') if isinstance(o, dict) else o.side,
                    "status": o.get('status') if isinstance(o, dict) else o.status,
                    "entry_price": float(o.get('price', 0)) if isinstance(o, dict) else o.price,
                    "quantity": float(o.get('origQty', 0)) if isinstance(o, dict) else o.quantity,
                    "margin": (float(o.get('price', 0)) if isinstance(o, dict) else o.price) *
                              (float(o.get('origQty', 0)) if isinstance(o, dict) else o.quantity) / 10,
                    # SOTA FIX: Add timestamp for pending order display
                    "open_time": datetime.fromtimestamp(
                        (o.get('time') if isinstance(o, dict) else getattr(o, 'time', 0)) / 1000
                    ).isoformat() if (o.get('time') if isinstance(o, dict) else getattr(o, 'time', 0)) else None,
                    # SOTA FIX: Add SL/TP from stopPrice (for STOP_MARKET orders)
                    "stop_loss": float(o.get('stopPrice', 0)) if isinstance(o, dict) else getattr(o, 'stop_price', 0),
                    "take_profit": 0,  # TP not directly on order
                    "is_live": True
                }
                for o in open_orders
            ]
            logger.info(f"{'🔴' if mode == 'LIVE' else '🧪'} {mode} Pending: {len(formatted)} orders")
            return {"count": len(formatted), "orders": formatted, "trading_mode": mode}
        return {"count": 0, "orders": [], "trading_mode": mode}

    # PAPER MODE
    import asyncio
    pending_orders = await asyncio.to_thread(paper_service.repo.get_pending_orders)
    signal_service = get_signal_lifecycle_service()
    try:
        signal_cache = await asyncio.to_thread(build_signal_cache, pending_orders, signal_service)
    except Exception as e:
        logger.warning(f"Failed to build pending order signal cache: {e}")
        signal_cache = {}

    def _get_pending_current_price(order):
        return resolve_paper_order_current_price(order, paper_service.market_data_repo)

    def _get_pending_distance_pct(order, current_price):
        return calculate_distance_pct(order.entry_price, current_price)

    def _format_pending_order(order):
        current_price = _get_pending_current_price(order)
        return {
            "id": order.id,
            "symbol": order.symbol,
            "side": order.side,
            "status": order.status,
            "entry_price": order.entry_price,
            "quantity": order.quantity,
            "margin": order.margin,
            "stop_loss": order.stop_loss,
            "take_profit": order.take_profit,
            "open_time": order.open_time.isoformat() if order.open_time else None,
            "size_usd": order.quantity * order.entry_price,
            "is_live": False,
            "current_price": current_price,
            "distance_pct": _get_pending_distance_pct(order, current_price),
            **enrich_paper_order(order, signal_cache)
        }

    return {
        "count": len(pending_orders),
        "orders": [_format_pending_order(order) for order in pending_orders],
        "trading_mode": "PAPER"
    }


@router.delete("/pending/{order_id}")
async def cancel_pending_order(
    order_id: str,
    paper_service: PaperTradingService = Depends(get_paper_trading_service)
):
    """
    Cancel a single pending order.

    SOTA: Removes the pending order from the system without executing.

    Args:
        order_id: ID of the pending order to cancel

    Returns:
        Success status and cancelled order details
    """
    # Find the pending order
    pending_orders = paper_service.repo.get_pending_orders()
    target_order = None

    for order in pending_orders:
        if order.id == order_id:
            target_order = order
            break

    if not target_order:
        raise HTTPException(status_code=404, detail=f"Pending order not found: {order_id}")

    # Mark as CANCELLED (or delete from DB)
    target_order.status = 'CANCELLED'
    target_order.exit_reason = 'USER_CANCELLED'
    paper_service.repo.update_order(target_order)

    # SOTA FIX: Release locked margin (don't add to balance - it was never subtracted)
    paper_service._locked_in_orders -= target_order.margin
    paper_service._locked_in_orders = max(0.0, paper_service._locked_in_orders)

    logger.info(f"🚫 CANCELLED pending order: {target_order.side} {target_order.symbol} @ {target_order.entry_price:.2f}")

    return {
        "success": True,
        "message": "Pending order cancelled",
        "order_id": order_id,
        "symbol": target_order.symbol,
        "side": target_order.side,
        "refunded_margin": target_order.margin
    }


@router.delete("/pending")
async def cancel_all_pending_orders(
    paper_service: PaperTradingService = Depends(get_paper_trading_service)
):
    """
    Cancel all pending orders at once.

    SOTA: Bulk cancel for portfolio cleanup.

    Returns:
        Number of orders cancelled and total refunded margin
    """
    pending_orders = paper_service.repo.get_pending_orders()

    if not pending_orders:
        return {"success": True, "message": "No pending orders to cancel", "count": 0}

    total_refund = 0.0
    cancelled_count = 0

    for order in pending_orders:
        order.status = 'CANCELLED'
        order.exit_reason = 'USER_CANCELLED_ALL'
        paper_service.repo.update_order(order)
        total_refund += order.margin
        cancelled_count += 1

    # SOTA FIX: Release all locked margin (don't add to balance - it was never subtracted)
    paper_service._locked_in_orders -= total_refund
    paper_service._locked_in_orders = max(0.0, paper_service._locked_in_orders)

    logger.info(f"🚫 CANCELLED ALL {cancelled_count} pending orders, refunded ${total_refund:.2f}")

    return {
        "success": True,
        "message": f"Cancelled {cancelled_count} pending orders",
        "count": cancelled_count,
        "refunded_margin": total_refund
    }


@router.get("/open")
async def get_open_positions(
    paper_service: PaperTradingService = Depends(get_paper_trading_service)
):
    """
    Get all open (filled) positions.

    SOTA: Mode-aware endpoint.
    - LIVE mode: Returns positions from Binance
    - PAPER mode: Returns positions from SQLite
    """
    mode = get_trading_mode()

    if mode == "LIVE":
        live_service = get_live_trading_service()
        # SOTA FIX: wrap blocking call
        import asyncio
        positions = await asyncio.to_thread(live_service.get_all_positions)

        # SOTA FIX (Feb 2026): Merge Local SL/TP from PositionMonitor
        local_positions = {}
        if live_service.position_monitor:
            # We access the internal dict directly or via a getter if available.
            # Assuming get_all_positions() returns a dict of MonitoredPosition
            local_positions = live_service.position_monitor.get_all_positions()

        formatted = []
        for p in positions:
            symbol_key = p.symbol.lower()
            monitored = local_positions.get(symbol_key) or local_positions.get(p.symbol)

            formatted.append({
                "id": f"live_{p.symbol}",
                "symbol": p.symbol,
                "side": "LONG" if p.position_amt > 0 else "SHORT",
                "size": abs(p.position_amt),
                "entry_price": p.entry_price,
                "current_price": p.mark_price,
                "pnl": p.unrealized_pnl,
                "leverage": p.leverage,
                # SOTA FIX: Inject Local SL/TP
                "stop_loss": monitored.current_sl if monitored else 0,
                "take_profit": monitored.initial_tp if monitored else 0,
                "backup_sl": monitored.backup_sl if monitored and hasattr(monitored, 'backup_sl') else 0,
                "is_live": True
            })

        logger.info(f"🔴 LIVE Positions: {len(formatted)} open")
        return {"count": len(formatted), "positions": formatted, "trading_mode": "LIVE"}

    # PAPER MODE
    import asyncio
    positions_enriched = await asyncio.to_thread(paper_service.get_positions_with_pnl)

    return {
        "count": len(positions_enriched),
        "positions": positions_enriched,
        "trading_mode": "PAPER"
    }


@router.post("/reset")
async def reset_account(
    paper_service: PaperTradingService = Depends(get_paper_trading_service)
):
    """
    Reset paper trading account.

    Clears all trades and resets balance to initial value.
    """
    paper_service.reset_account()
    return {"success": True, "message": "Account reset to $10,000"}


@router.post("/execute/{position_id}")
async def execute_pending(
    position_id: str,
    service: RealtimeService = Depends(get_realtime_service),
    paper_service: PaperTradingService = Depends(get_paper_trading_service)
):
    """
    Manually execute a PENDING order at CURRENT market price.

    This is a MARKET ORDER - fills immediately at current price,
    not at the original limit entry price.

    Use case: User sees PENDING order and wants to enter NOW
    instead of waiting for limit price to be hit.

    Args:
        position_id: ID of the PENDING order to execute

    Returns:
        Execution result with fill price
    """
    from datetime import datetime

    # Get current price
    latest_candle = service.get_latest_data('1m')
    if not latest_candle or latest_candle.close <= 0:
        return {"success": False, "error": "Cannot determine current price"}

    current_price = latest_candle.close

    # Find the pending order
    pending_orders = paper_service.repo.get_pending_orders()
    target_order = None

    for order in pending_orders:
        if order.id == position_id:
            target_order = order
            break

    if not target_order:
        return {
            "success": False,
            "error": f"PENDING order not found: {position_id}"
        }

    # Execute at CURRENT price (market order)
    original_entry = target_order.entry_price
    target_order.entry_price = current_price  # Fill at market price
    target_order.status = 'OPEN'
    target_order.open_time = datetime.now()

    # Recalculate liquidation price
    if target_order.side == 'LONG':
        target_order.liquidation_price = current_price - (target_order.margin / target_order.quantity)
    else:
        target_order.liquidation_price = current_price + (target_order.margin / target_order.quantity)

    paper_service.repo.update_order(target_order)

    logger.info(
        f"✅ MARKET FILLED {target_order.side} {target_order.symbol} @ {current_price:.2f} "
        f"(was PENDING @ {original_entry:.2f})"
    )

    # Trigger state machine callback
    if paper_service.on_order_filled:
        try:
            paper_service.on_order_filled(target_order.id)
        except Exception as e:
            logger.error(f"Error in on_order_filled callback: {e}")

    return {
        "success": True,
        "message": f"Order filled at market price",
        "order_id": target_order.id,
        "side": target_order.side,
        "original_entry": original_entry,
        "fill_price": current_price,
        "size_usd": target_order.quantity * current_price
    }


@router.post("/simulate")
async def simulate_signal(
    signal_data: dict,
    service: RealtimeService = Depends(get_realtime_service),
    paper_service: PaperTradingService = Depends(get_paper_trading_service)
):
    """
    Simulate a BUY/SELL signal for testing purposes.

    This is a DEBUG endpoint to test the trade execution flow
    without waiting for real signals from the strategy.

    Args:
        signal_data: {"signal_type": "BUY" | "SELL"}

    Returns:
        Trade execution result
    """
    from datetime import datetime
    from src.domain.entities.trading_signal import TradingSignal, SignalType

    signal_type = signal_data.get("signal_type", "BUY").upper()

    if signal_type not in ["BUY", "SELL"]:
        return {"success": False, "error": "Invalid signal type. Use BUY or SELL"}

    # Get current price
    latest_candle = service.get_latest_data('1m')
    if not latest_candle or latest_candle.close <= 0:
        return {"success": False, "error": "Cannot determine current price"}

    current_price = latest_candle.close

    # Calculate SL/TP based on default risk settings
    # Default: 1.5% risk, 1.5 R:R ratio
    risk_percent = 0.015  # 1.5%
    rr_ratio = 1.5

    if signal_type == "BUY":
        stop_loss = current_price * (1 - risk_percent)
        take_profit = current_price * (1 + risk_percent * rr_ratio)
        sig_type = SignalType.BUY
    else:
        stop_loss = current_price * (1 + risk_percent)
        take_profit = current_price * (1 - risk_percent * rr_ratio)
        sig_type = SignalType.SELL

    # Create TradingSignal object (required by execute_trade)
    trading_signal = TradingSignal(
        signal_type=sig_type,
        confidence=0.75,  # Default confidence for test
        generated_at=datetime.now(),  # FIX: Use correct field name
        price=current_price,
        entry_price=current_price,
        stop_loss=stop_loss,
        tp_levels={'tp1': take_profit},
        indicators={},
        reasons=[f"SIMULATED_{signal_type}_SIGNAL"]
    )

    # Execute the simulated trade
    try:
        position_id = paper_service.execute_trade(
            signal=trading_signal,
            symbol="BTCUSDT"
        )

        if position_id:
            return {
                "success": True,
                "trade_id": position_id,
                "entry_price": current_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "side": "LONG" if signal_type == "BUY" else "SHORT"
            }
        else:
            return {"success": False, "error": "Trade execution returned None (position limit or insufficient balance)"}

    except Exception as e:
        logger.error(f"Simulate signal error: {e}")
        return {"success": False, "error": str(e)}


@router.get("/equity-curve")
async def get_equity_curve(
    days: int = Query(default=7, ge=1, le=365, description="Number of days"),
    resolution: str = Query(default="trade", description="Resolution: 'trade' (per-trade) or 'daily'"),
    paper_service: PaperTradingService = Depends(get_paper_trading_service)
):
    """
    Get equity curve data for charting.

    **Validates: Requirements 7.3 - Performance visualization**

    Returns equity values based on trade history.
    Resolution can be 'trade' (per-trade, recommended for 15m strategy) or 'daily'.

    Args:
        days: Number of days to include (default: 7)
        resolution: 'trade' for per-trade updates, 'daily' for daily aggregation

    Returns:
        List of {time, equity, pnl, trade_id?} points
    """
    from datetime import datetime, timedelta

    # Get all trades for the period
    result = paper_service.get_trade_history(page=1, limit=1000)
    trades = result.trades

    # Calculate equity curve
    initial_balance = 10000.0
    equity_curve = []

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    if resolution == "trade":
        # TRADE-BY-TRADE RESOLUTION (New - for 15m strategy monitoring)
        # Each point represents equity after a trade closes

        # Filter trades within the period and sort by exit_time
        period_trades = [
            t for t in trades
            if t.exit_time and t.exit_time >= start_date
        ]
        period_trades.sort(key=lambda t: t.exit_time)

        # Start with initial balance point
        equity_curve.append({
            "time": start_date.strftime('%Y-%m-%dT%H:%M:%S'),
            "equity": initial_balance,
            "pnl": 0.0,
            "trade_id": None
        })

        cumulative_pnl = 0.0

        # Add a point for each closed trade
        for trade in period_trades:
            if trade.pnl is not None:
                cumulative_pnl += trade.pnl
                current_equity = initial_balance + cumulative_pnl

                equity_curve.append({
                    "time": trade.exit_time.strftime('%Y-%m-%dT%H:%M:%S'),
                    "equity": round(current_equity, 2),
                    "pnl": round(trade.pnl, 2),
                    "trade_id": trade.id,
                    "side": trade.side,
                    "result": "WIN" if trade.pnl > 0 else "LOSS"
                })

        # Add current point (latest equity)
        if equity_curve:
            equity_curve.append({
                "time": end_date.strftime('%Y-%m-%dT%H:%M:%S'),
                "equity": equity_curve[-1]["equity"],
                "pnl": 0.0,
                "trade_id": None
            })
    else:
        # DAILY RESOLUTION (Original)
        current_equity = initial_balance
        cumulative_pnl = 0.0

        # Group trades by date
        trades_by_date = {}
        for trade in trades:
            if trade.exit_time:
                trade_date = trade.exit_time.strftime('%Y-%m-%d')
                if trade_date not in trades_by_date:
                    trades_by_date[trade_date] = []
                trades_by_date[trade_date].append(trade)

        # Build equity curve day by day
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')

            # Add PnL from trades closed on this day
            daily_pnl = 0.0
            if date_str in trades_by_date:
                for trade in trades_by_date[date_str]:
                    if trade.pnl is not None:
                        daily_pnl += trade.pnl

            cumulative_pnl += daily_pnl
            current_equity = initial_balance + cumulative_pnl

            equity_curve.append({
                "time": date_str,
                "equity": round(current_equity, 2),
                "pnl": round(daily_pnl, 2)
            })

            current_date += timedelta(days=1)

    # Include current portfolio balance for consistency check
    return {
        "equity_curve": equity_curve,
        "resolution": resolution,
        "initial_balance": initial_balance,
        "current_equity": equity_curve[-1]["equity"] if equity_curve else initial_balance
    }


@router.post("/positions/{symbol}/set-tpsl")
async def set_position_tpsl(
    symbol: str,
    stop_loss: float = Query(default=0, description="Stop loss price"),
    take_profit: float = Query(default=0, description="Take profit price")
):
    """
    SOTA: Manually set TP/SL for orphan positions.

    Use this for positions opened before bot start or manual trades.
    Updates local tracking only (does NOT place orders on exchange).

    Args:
        symbol: Trading pair (e.g., BTCUSDT)
        stop_loss: Stop loss price (0 = no change)
        take_profit: Take profit price (0 = no change)
    """
    mode = get_trading_mode()

    if mode not in ["LIVE", "TESTNET"]:
        return {"success": False, "error": "Only available in LIVE/TESTNET mode"}

    live_service = get_live_trading_service()
    symbol_upper = symbol.upper()

    # Update local watermarks
    if symbol_upper not in live_service._position_watermarks:
        live_service._position_watermarks[symbol_upper] = {
            'highest': 0,
            'lowest': float('inf'),
            'current_sl': 0,
            'tp_target': 0
        }

    if stop_loss > 0:
        live_service._position_watermarks[symbol_upper]['current_sl'] = stop_loss
    if take_profit > 0:
        live_service._position_watermarks[symbol_upper]['tp_target'] = take_profit

    # Also save to database for persistence
    if live_service.order_repo:
        try:
            # Check if position exists in DB
            db_pos = live_service.order_repo.get_live_position_by_symbol(symbol_upper)
            if db_pos:
                if stop_loss > 0:
                    live_service.order_repo.update_live_position_sl(symbol_upper, stop_loss)
            else:
                # Create new DB entry for this orphan position
                live_service.order_repo.save_live_position(
                    symbol=symbol_upper,
                    side='UNKNOWN',  # We don't know from here
                    entry_price=0,
                    quantity=0,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    leverage=10
                )
        except Exception as e:
            logger.warning(f"Failed to persist TP/SL: {e}")

    # Invalidate cache
    live_service._portfolio_cache = None

    logger.info(f"📝 Manual TP/SL set: {symbol_upper} SL=${stop_loss:.2f} TP=${take_profit:.2f}")

    return {
        "success": True,
        "symbol": symbol_upper,
        "stop_loss": stop_loss if stop_loss > 0 else None,
        "take_profit": take_profit if take_profit > 0 else None,
        "message": "TP/SL updated (local tracking only, no exchange orders placed)"
    }


@router.post("/cancel-all-orders")
async def cancel_all_pending_orders(
    live_service = Depends(get_live_trading_service)
):
    """
    SOTA: Cancel ALL pending LIMIT orders on Binance.

    Useful for cleanup after zombie order accumulation.
    Only cancels LIMIT orders, not SL/TP orders.
    """
    mode = get_trading_mode()

    if mode == "PAPER":
        return {"success": False, "error": "Paper mode - no real orders to cancel"}

    cancelled = []
    failed = []

    try:
        # Get all open orders from Binance
        open_orders = live_service.client.get_open_orders()

        for order in open_orders:
            if isinstance(order, dict):
                order_type = order.get('type', '')
                symbol = order.get('symbol', '')
                order_id = order.get('orderId', 0)
            else:
                order_type = order.type.value if hasattr(order.type, 'value') else order.type
                symbol = order.symbol
                order_id = order.order_id

            # Only cancel LIMIT entry orders (not SL/TP)
            if order_type == 'LIMIT':
                try:
                    live_service.client.cancel_order(symbol=symbol, order_id=order_id)
                    cancelled.append({"symbol": symbol, "order_id": order_id})
                    logger.info(f"🗑️ Cancelled LIMIT order: {symbol} (ID: {order_id})")
                except Exception as e:
                    failed.append({"symbol": symbol, "order_id": order_id, "error": str(e)})

        # Clear memory and DB pending orders too
        live_service.pending_orders.clear()
        if live_service.order_repo:
            try:
                # Remove all pending from DB
                for item in cancelled:
                    live_service.order_repo.remove_pending_order(item["symbol"])
            except:
                pass

        # Clear cache
        live_service._cached_open_orders = {}

        return {
            "success": True,
            "cancelled_count": len(cancelled),
            "failed_count": len(failed),
            "cancelled": cancelled,
            "failed": failed,
            "message": f"Cancelled {len(cancelled)} LIMIT orders"
        }

    except Exception as e:
        logger.error(f"Failed to cancel orders: {e}")
        return {"success": False, "error": str(e)}


@router.post("/signals/cancel/{symbol}")
async def cancel_pending_signal(
    symbol: str,
    paper_service: PaperTradingService = Depends(get_paper_trading_service),
    live_service = Depends(get_live_trading_service)
):
    """
    SOTA Mode-Aware: Cancel a pending signal/order.

    - PAPER: Cancels from SQLite pending orders
    - TESTNET/LIVE: Cancels from LocalSignalTracker (no Binance API needed)
    """
    mode = get_trading_mode()
    symbol = symbol.upper()

    # PAPER MODE: Cancel from SQLite
    if mode == "PAPER":
        try:
            pending_orders = paper_service.repo.get_pending_orders()
            cancelled = False
            for order in pending_orders:
                if order.symbol.upper() == symbol:
                    order.status = 'CANCELLED'
                    order.exit_reason = 'MANUAL_CANCEL'
                    from datetime import datetime
                    order.close_time = datetime.now()
                    paper_service.repo.update_order(order)

                    # Release locked margin
                    paper_service._locked_in_orders -= order.margin
                    paper_service._locked_in_orders = max(0.0, paper_service._locked_in_orders)

                    cancelled = True
                    logger.info(f"🗑️ [PAPER] Cancelled pending order: {symbol}")
                    break

            if cancelled:
                return {"success": True, "symbol": symbol, "mode": "PAPER"}
            else:
                return {"success": False, "error": f"No pending order for {symbol}"}
        except Exception as e:
            logger.error(f"Failed to cancel paper order: {e}")
            return {"success": False, "error": str(e)}

    # TESTNET/LIVE MODE: Cancel from LocalSignalTracker
    if not live_service:
        return {"success": False, "error": "Live trading service not available"}

    if not hasattr(live_service, 'signal_tracker') or not live_service.signal_tracker:
        return {"success": False, "error": "Signal tracker not initialized"}

    try:
        removed = live_service.signal_tracker.remove_signal(symbol)
        if removed:
            logger.info(f"🗑️ [{mode}] Cancelled pending signal: {symbol}")
            return {"success": True, "symbol": symbol, "mode": mode}
        else:
            return {"success": False, "error": f"No pending signal for {symbol}"}
    except Exception as e:
        logger.error(f"Failed to cancel signal: {e}")
        return {"success": False, "error": str(e)}


@router.get("/signals/pending")
async def get_pending_signals(
    live_service = Depends(get_live_trading_service)
):
    """
    SOTA LocalSignalTracker: Get all pending signals from local tracker.

    Returns signals waiting to trigger (price hasn't hit target yet).
    These are LOCAL only - not orders on exchange.
    """
    mode = get_trading_mode()

    if mode == "PAPER":
        # Paper mode uses PaperTradingService pending orders
        return {"pending_signals": [], "count": 0, "mode": "PAPER"}

    if not live_service:
        return {"pending_signals": [], "count": 0, "error": "Service not available"}

    if not hasattr(live_service, 'signal_tracker'):
        return {"pending_signals": [], "count": 0}

    try:
        signals = live_service.get_pending_signals()
        return {
            "pending_signals": [
                {
                    "symbol": sym,
                    "direction": data.get('direction'),
                    "target_price": data.get('target_price'),
                    "stop_loss": data.get('stop_loss'),
                    "take_profit": data.get('take_profit'),
                    "quantity": data.get('quantity'),
                    "expires_at": data.get('expires_at')
                }
                for sym, data in signals.items()
            ],
            "count": len(signals),
            "mode": mode
        }
    except Exception as e:
        logger.error(f"Failed to get pending signals: {e}")
        return {"pending_signals": [], "count": 0, "error": str(e)}


@router.delete("/pending")
async def cancel_all_pending(
    paper_service: PaperTradingService = Depends(get_paper_trading_service),
    live_service = Depends(get_live_trading_service)
):
    """
    SOTA Mode-Aware: Cancel all pending orders/signals.

    - PAPER: Cancels all from SQLite pending orders
    - TESTNET/LIVE: Clears all from LocalSignalTracker
    """
    mode = get_trading_mode()
    cancelled_count = 0

    if mode == "PAPER":
        try:
            pending_orders = paper_service.repo.get_pending_orders()
            from datetime import datetime
            for order in pending_orders:
                order.status = 'CANCELLED'
                order.exit_reason = 'MANUAL_CANCEL_ALL'
                order.close_time = datetime.now()
                paper_service.repo.update_order(order)

                # Release locked margin
                paper_service._locked_in_orders -= order.margin
                cancelled_count += 1

            paper_service._locked_in_orders = max(0.0, paper_service._locked_in_orders)
            logger.info(f"🗑️ [PAPER] Cancelled all {cancelled_count} pending orders")
            return {"success": True, "cancelled": cancelled_count, "mode": "PAPER"}
        except Exception as e:
            logger.error(f"Failed to cancel all paper orders: {e}")
            return {"success": False, "error": str(e)}

    # TESTNET/LIVE: Clear LocalSignalTracker
    if live_service and hasattr(live_service, 'signal_tracker') and live_service.signal_tracker:
        try:
            cancelled_count = len(live_service.signal_tracker)
            live_service.signal_tracker.clear_all()
            logger.info(f"🗑️ [{mode}] Cancelled all {cancelled_count} pending signals")
            return {"success": True, "cancelled": cancelled_count, "mode": mode}
        except Exception as e:
            logger.error(f"Failed to cancel all signals: {e}")
            return {"success": False, "error": str(e)}

    return {"success": False, "error": "No signal tracker available"}
