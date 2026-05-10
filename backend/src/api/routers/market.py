"""
Market Router - WebSocket and REST endpoints for market data

**Feature: desktop-trading-dashboard**
**Validates: Requirements 1.1, 1.2, 5.2, 5.3, 5.4**

Provides:
- WebSocket streaming for real-time candle data (via EventBus)
- Historical data API with indicators
- Graceful disconnect handling

Architecture:
- EventBus handles all broadcasting (decoupled from this router)
- This router only manages WebSocket connections and initial snapshots
- No more sync/async callback issues!
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from typing import List, Optional
import json
import asyncio
import logging

from src.api.dependencies import get_realtime_service, get_realtime_service_for_symbol, get_market_data_repository
from src.api.websocket_manager import get_websocket_manager, WebSocketManager
from src.api.event_bus import get_event_bus
from src.api.websocket.client_subscription_manager import get_subscription_manager, SubscriptionMode
from src.application.services.realtime_service import RealtimeService
from src.infrastructure.persistence.sqlite_market_data_repository import SQLiteMarketDataRepository

router = APIRouter(
    prefix="/ws",
    tags=["market"]
)

# Additional router for /market prefix (for frontend compatibility)
market_router = APIRouter(
    prefix="/market",
    tags=["market-rest"]
)

logger = logging.getLogger(__name__)


# NOTE: Service bridge has been REMOVED!
# Broadcasting is now handled by EventBus (see event_bus.py and main.py lifespan)
# This eliminates the async/sync callback mismatch problem


@router.websocket("/stream/{symbol}")
async def websocket_stream(
    websocket: WebSocket,
    symbol: str,
):
    """
    WebSocket endpoint for real-time market data streaming.

    **Validates: Requirements 1.1, 1.2, 5.2, 5.3**

    SOTA FIX (Jan 2026): Wait for data_ready before serving data.
    This fixes race condition where frontend connects before background init completes.

    Features:
    - Real-time candle data with indicators (VWAP, BB, StochRSI)
    - Signal notifications (via EventBus broadcast)
    - Graceful disconnect handling

    Args:
        symbol: Trading pair symbol (e.g., 'btcusdt')
    """
    manager = get_websocket_manager()

    # Connect client to WebSocketManager first
    connection = await manager.connect(websocket, symbol.lower())

    try:
        # SOTA FIX (Jan 2026): Wait for data_ready before serving data
        # This fixes race condition where frontend connects before background init
        from starlette.requests import Request
        app = websocket.app

        max_wait = 60  # Maximum 60 seconds
        waited = 0
        while not getattr(app.state, 'data_ready', False):
            if waited >= max_wait:
                logger.warning(f"⚠️ Timeout waiting for data_ready for {symbol}")
                break

            # Send status update to frontend
            await websocket.send_json({
                "type": "status",
                "status": "initializing",
                "message": f"Loading market data... ({waited}s)",
                "symbol": symbol.lower()
            })
            await asyncio.sleep(1)
            waited += 1

        # Now get service (guaranteed to have data if data_ready is True)
        service = get_realtime_service_for_symbol(symbol)
        logger.info(f"✅ WebSocket ready for {symbol}, data_ready={getattr(app.state, 'data_ready', False)}")

        # SOTA FIX: Helper to sanitize Pandas objects for JSON serialization
        def sanitize_for_json(obj):
            """Convert Pandas/numpy types to JSON-serializable Python types."""
            import pandas as pd
            import numpy as np

            if isinstance(obj, dict):
                return {k: sanitize_for_json(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [sanitize_for_json(v) for v in obj]
            elif isinstance(obj, pd.Timestamp):
                return obj.isoformat()
            elif isinstance(obj, (np.integer, np.floating)):
                return float(obj)
            elif isinstance(obj, np.ndarray):
                return obj.tolist()
            elif hasattr(obj, 'isoformat'):  # datetime-like
                return obj.isoformat()
            elif pd.isna(obj):
                return None
            return obj

        # Send initial data snapshot
        raw_indicators = service.get_latest_indicators(timeframe='1m')
        sanitized_indicators = sanitize_for_json(raw_indicators)

        initial_data = {
            'type': 'snapshot',
            'symbol': symbol.lower(),
            'data': sanitized_indicators
        }

        latest_candle = service.get_latest_data('1m')
        if latest_candle:
            initial_data['candle'] = {
                'timestamp': latest_candle.timestamp.isoformat() if hasattr(latest_candle.timestamp, 'isoformat') else str(latest_candle.timestamp),
                'open': latest_candle.open,
                'high': latest_candle.high,
                'low': latest_candle.low,
                'close': latest_candle.close,
                'volume': latest_candle.volume
            }

        # Include current signal if available
        current_signal = service.get_current_signals()
        if current_signal and current_signal.signal_type.value != 'neutral':
            initial_data['signal'] = {
                'type': current_signal.signal_type.value,
                'price': current_signal.price,
                'entry_price': getattr(current_signal, 'entry_price', current_signal.price),
                'stop_loss': getattr(current_signal, 'stop_loss', None),
                'take_profit': getattr(current_signal, 'take_profit', None),
                'confidence': current_signal.confidence,
                'risk_reward_ratio': getattr(current_signal, 'risk_reward_ratio', None),
                'timestamp': current_signal.timestamp.isoformat() if hasattr(current_signal, 'timestamp') and hasattr(current_signal.timestamp, 'isoformat') else str(current_signal.timestamp) if hasattr(current_signal, 'timestamp') else None
            }

        await websocket.send_text(json.dumps(initial_data))
        logger.info(f"Client {connection.client_id} connected, initial snapshot sent")

        # Keep connection alive and handle client messages
        # Actual data updates are pushed by EventBus broadcast worker
        while True:
            try:
                # Wait for client messages (ping/pong, subscription changes)
                data = await websocket.receive_text()

                # Handle client commands
                try:
                    msg = json.loads(data)
                    msg_type = msg.get('type')

                    if msg_type == 'ping':
                        await websocket.send_text(json.dumps({'type': 'pong'}))

                    elif msg_type == 'subscribe':
                        # SOTA (Jan 2026): Multi-position realtime prices
                        # Support both legacy and new multi-mode format
                        # New format: { symbols: ['btcusdt'], priceOnly: ['ethusdt'] }
                        # Legacy: { symbol: 'btcusdt' } or { symbols: ['btcusdt'] }

                        subscription_manager = get_subscription_manager()
                        sub = await subscription_manager.update_subscription(connection.client_id, msg)

                        # Also update WebSocketManager for backward compatibility
                        all_symbols = list(sub.get_all_symbols())
                        await manager.update_subscription(connection.client_id, all_symbols)

                        # Send confirmation with mode info
                        await websocket.send_text(json.dumps({
                            'type': 'subscribed',
                            'symbols': list(sub.full_symbols),
                            'priceOnly': list(sub.price_only_symbols)
                        }))
                        logger.info(f"Client {connection.client_id} subscribed: full={list(sub.full_symbols)}, priceOnly={list(sub.price_only_symbols)}")

                except json.JSONDecodeError:
                    # Not JSON - might be a simple ping
                    pass

            except asyncio.TimeoutError:
                # No message received - that's fine, just keep waiting
                continue

    except WebSocketDisconnect:
        # Client disconnected gracefully
        logger.debug(f"Client {connection.client_id} disconnected gracefully")

    except Exception as e:
        # Unexpected error - log but don't crash
        logger.error(f"WebSocket error for {connection.client_id}: {e}")

    finally:
        # Always clean up connection
        await manager.disconnect(connection)


@router.websocket("/market/{symbol}")
async def websocket_market_legacy(
    websocket: WebSocket,
    symbol: str,
):
    """
    Legacy WebSocket endpoint (for backward compatibility).
    Redirects to /stream/{symbol}.
    """
    # SOTA Multi-Token FIX: Get service for the requested symbol
    service = get_realtime_service_for_symbol(symbol)
    await websocket_stream(websocket, symbol)


@router.get("/history/{symbol}")
async def get_market_history(
    symbol: str,
    timeframe: str = Query(default='15m', pattern='^(1m|15m|1h)$'),
    limit: int = Query(default=100, ge=1, le=1000),
    repo: SQLiteMarketDataRepository = Depends(get_market_data_repository)
):
    """
    Get historical market data with hybrid data source.

    SOTA Multi-Token: Returns data for the requested symbol.

    SOTA FIX (Jan 2026): Wait for data_ready before returning data.

    **Validates: Requirements 5.4, 2.1**
    """
    # SOTA FIX (Jan 2026): Wait for data_ready before serving
    from fastapi import Request
    from starlette.requests import Request as StarletteRequest
    import asyncio

    # Access app state via module-level app reference
    try:
        from src.api.main import app
        max_wait = 30  # Maximum 30 seconds for REST endpoint
        waited = 0
        while not getattr(app.state, 'data_ready', False):
            if waited >= max_wait:
                logger.warning(f"⚠️ Timeout waiting for data_ready for history/{symbol}")
                break
            await asyncio.sleep(0.5)
            waited += 0.5
    except Exception as e:
        logger.warning(f"Could not check data_ready: {e}")

    # SOTA: Get service for the specific symbol
    service = get_realtime_service_for_symbol(symbol)

    # SOTA FIX (Jan 2026): Skip SQLite - use IN-MEMORY buffers directly
    # Matches Two Sigma/Citadel pattern: runtime data from memory, not disk
    # SQLite persist disabled for performance - Binance is source of truth

    # Step 1: Try in-memory buffer first (FAST!)
    try:
        import asyncio
        candles = await asyncio.to_thread(service.get_candles, timeframe, limit)
        if candles and len(candles) >= limit * 0.5:  # 50% threshold
            logger.debug(f"📦 In-Memory hit: {len(candles)} candles for {symbol}/{timeframe}")
            return await asyncio.to_thread(service.get_historical_data_with_indicators, timeframe, limit, candles)
    except Exception as e:
        logger.warning(f"In-memory query failed: {e}")

    # Step 2: Fallback to Binance REST API (for cold start or missing data)
    logger.debug(f"📡 In-memory miss, falling back to Binance for {symbol}/{timeframe}")
    return await asyncio.to_thread(service.get_historical_data_with_indicators, timeframe, limit)


@router.get("/status")
async def get_websocket_status():
    """
    Get WebSocket manager status and statistics.

    Returns:
        Connection statistics and active subscriptions
    """
    manager = get_websocket_manager()
    event_bus = get_event_bus()

    return {
        'websocket': manager.get_statistics(),
        'event_bus': event_bus.get_statistics()
    }


@router.get("/connections")
async def get_active_connections():
    """
    Get list of active WebSocket connections.

    Returns:
        List of connection info
    """
    manager = get_websocket_manager()
    return manager.get_all_connections_info()


# ============ /market/* endpoints for frontend compatibility ============

@market_router.get("/history")
async def get_market_history_rest(
    symbol: str = Query(default='btcusdt'),
    timeframe: str = Query(default='15m', pattern='^(1m|15m|1h)$'),
    limit: int = Query(default=100, ge=1, le=1000),
    repo: SQLiteMarketDataRepository = Depends(get_market_data_repository)
):
    """
    Get historical market data (REST endpoint for frontend).

    SOTA Phase 3: SQLite first, Binance fallback.

    SOTA Multi-Token: Now correctly uses symbol-specific service.

    Used by useMarketData hook for data gap filling after reconnect.

    Args:
        symbol: Trading pair symbol (default: btcusdt)
        timeframe: Candle timeframe (default: 15m)
        limit: Number of candles to return (max 1000)

    Returns:
        List of candles with indicators
    """
    # SOTA Multi-Token FIX: Get service for the requested symbol
    service = get_realtime_service_for_symbol(symbol)

    # SOTA FIX (Jan 2026): Skip SQLite - use IN-MEMORY buffers directly
    # Matches Two Sigma/Citadel pattern: runtime data from memory, not disk

    # Step 1: Try in-memory buffer first (FAST!)
    try:
        candles = service.get_candles(timeframe, limit)
        if candles and len(candles) >= limit * 0.5:  # 50% threshold
            logger.debug(f"📦 In-Memory hit: {len(candles)} candles for {timeframe}")
            return service.get_historical_data_with_indicators(timeframe, limit, candles)
    except Exception as e:
        logger.warning(f"In-memory query failed: {e}")

    # Step 2: Fallback to Binance REST API (for cold start or missing data)
    logger.debug(f"📡 In-memory miss, falling back to Binance for {timeframe}")
    return service.get_historical_data_with_indicators(timeframe, limit)


@market_router.get("/symbols")
async def get_supported_symbols():
    """
    Get list of supported trading symbols.

    SOTA Single Source of Truth: Uses same data source as /settings/tokens.
    Now trusts 'enabled_tokens' from DB/ENV as the definitive list.

    Returns:
        List of symbol info with name and base currency
    """
    from src.config import DEFAULT_SYMBOLS
    from src.api.dependencies import get_paper_trading_service

    # SOTA: Use same data source as /settings/tokens
    paper_service = get_paper_trading_service()
    settings = paper_service.repo.get_all_settings()

    # 1. Source of Truth: DB 'enabled_tokens' (synced from .env on startup)
    enabled_tokens_str = settings.get('enabled_tokens', '')

    if enabled_tokens_str:
        # DB has specific config -> Use strictly this list
        active_symbols = sorted(list(set(enabled_tokens_str.split(','))))
        source = "database/env"
    else:
        # Fallback to defaults if DB empty
        active_symbols = sorted(list(DEFAULT_SYMBOLS))
        source = "defaults"

    # SOTA Visibility: Log exactly what's being returned
    logger.info(f"🔎 Symbol Load: source={source}, count={len(active_symbols)}")
    if len(active_symbols) > 10:
        logger.info(f"📋 Symbols (first 10): {', '.join(active_symbols[:10])}...")
    else:
        logger.info(f"📋 Symbols: {', '.join(active_symbols)}")

    # Map symbols to displayable info
    symbol_info = []
    for symbol in active_symbols:
        base = symbol.replace("USDT", "")
        symbol_info.append({
            "symbol": symbol.lower(),
            "display": symbol,
            "base": base,
            "quote": "USDT",
            "name": _get_token_name(base),
        })

    return {
        "symbols": symbol_info,
        "count": len(symbol_info),
        "default": active_symbols[0].lower() if active_symbols else "btcusdt",
        "source": source
    }


# ============ SOTA: Top Volume Tokens (Shark Tank Mode) ============
# Cache for top tokens (TTL 5 minutes to reduce API calls)
_top_tokens_cache = {
    "data": [],
    "timestamp": 0
}
_TOP_TOKENS_TTL = 300  # 5 minutes


@market_router.get("/top-tokens")
async def get_top_volume_tokens(
    limit: int = Query(default=10, ge=1, le=100),
    quote_asset: str = Query(default="USDT"),
    min_volume_usd: float = Query(default=10_000_000, ge=0, description="Minimum 24h volume"),
    max_volatility_pct: float = Query(default=50, ge=5, le=100, description="Max daily range %")
):
    """
    Get top trading pairs by 24h quote volume from Binance Futures.

    SOTA Shark Tank Mode: Dynamically fetch top volume tokens for multi-symbol trading.

    Features:
    - Fetches from Binance Futures API (fapi.binance.com)
    - Caches results for 5 minutes (TTL)
    - Filters by quote asset (USDT default)
    - Excludes stablecoin pairs (USDC, FDUSD)
    - SOTA P2: Minimum volume filter (liquidity)
    - SOTA P2: Maximum volatility filter (risk control)

    Args:
        limit: Number of top tokens to return (default: 10 for Shark Tank)
        quote_asset: Filter by quote asset (default: USDT)
        min_volume_usd: Minimum 24h volume in USD (default: 10M)
        max_volatility_pct: Maximum daily price range % (default: 50%)

    Returns:
        List of top volume symbols with metadata
    """
    import time
    import requests

    current_time = time.time()

    # Check cache
    if (
        _top_tokens_cache["data"]
        and current_time - _top_tokens_cache["timestamp"] < _TOP_TOKENS_TTL
        and len(_top_tokens_cache["data"]) >= limit
    ):
        logger.debug(f"📦 Cache hit: returning top {limit} tokens")
        return {
            "tokens": _top_tokens_cache["data"][:limit],
            "count": len(_top_tokens_cache["data"][:limit]),
            "source": "cache",
            "ttl_remaining": int(_TOP_TOKENS_TTL - (current_time - _top_tokens_cache["timestamp"]))
        }

    # Fetch from Binance Futures API
    try:
        def _fetch_sync():
            logger.info("📡 Fetching top volume tokens from Binance Futures...")

            # Use Futures API for more accurate volume data
            url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
            response = requests.get(url, timeout=10)
            response.raise_for_status()

            data = response.json()

            # SOTA P2: Comprehensive filtering
            filtered = []
            blacklisted = []

            for item in data:
                symbol = item['symbol']

                # 1. Base filters
                if not symbol.endswith(quote_asset):
                    continue
                if symbol.startswith(('USDC', 'FDUSD', 'BUSD', 'EUR', 'GBP', 'DAI')):
                    continue

                volume = float(item.get('quoteVolume', 0))

                # 2. Volume filter (liquidity)
                if volume < min_volume_usd:
                    blacklisted.append({'symbol': symbol, 'reason': 'LOW_VOLUME', 'value': volume})
                    continue

                # 3. Volatility filter (risk control)
                high = float(item.get('highPrice', 0))
                low = float(item.get('lowPrice', 0))
                last = float(item.get('lastPrice', 0))

                if last > 0 and high > 0 and low > 0:
                    daily_range_pct = ((high - low) / last) * 100
                    if daily_range_pct > max_volatility_pct:
                        blacklisted.append({'symbol': symbol, 'reason': 'HIGH_VOLATILITY', 'value': daily_range_pct})
                        continue

                filtered.append(item)

            if blacklisted:
                logger.debug(f"🚫 Blacklisted {len(blacklisted)} tokens")

            # Sort by quoteVolume (descending)
            sorted_pairs = sorted(
                filtered,
                key=lambda x: float(x.get('quoteVolume', 0)),
                reverse=True
            )

            # Build result with metadata
            top_tokens = []
            for i, item in enumerate(sorted_pairs[:100]):  # Cache top 100
                base = item['symbol'].replace(quote_asset, '')
                top_tokens.append({
                    "rank": i + 1,
                    "symbol": item['symbol'],
                    "base": base,
                    "quote": quote_asset,
                    "name": _get_token_name(base),
                    "volume_24h": float(item.get('quoteVolume', 0)),
                    "price_change_pct": float(item.get('priceChangePercent', 0)),
                    "last_price": float(item.get('lastPrice', 0)),
                })

            return top_tokens

        import asyncio
        top_tokens = await asyncio.to_thread(_fetch_sync)

        # Update cache (Main Thread - Thread Safe)
        _top_tokens_cache["data"] = top_tokens
        _top_tokens_cache["timestamp"] = current_time

        logger.info(f"✅ Fetched {len(top_tokens)} top volume tokens")

        return {
            "tokens": top_tokens[:limit],
            "count": len(top_tokens[:limit]),
            "source": "binance_futures",
            "ttl_remaining": _TOP_TOKENS_TTL
        }

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch top tokens: {e}")

        # Return cached data if available (stale)
        if _top_tokens_cache["data"]:
            return {
                "tokens": _top_tokens_cache["data"][:limit],
                "count": len(_top_tokens_cache["data"][:limit]),
                "source": "cache_stale",
                "error": str(e)
            }

        # Fallback to hardcoded top 10 (Shark Tank defaults)
        fallback = [
            {"rank": 1, "symbol": "BTCUSDT", "base": "BTC", "quote": "USDT", "name": "Bitcoin"},
            {"rank": 2, "symbol": "ETHUSDT", "base": "ETH", "quote": "USDT", "name": "Ethereum"},
            {"rank": 3, "symbol": "SOLUSDT", "base": "SOL", "quote": "USDT", "name": "Solana"},
            {"rank": 4, "symbol": "BNBUSDT", "base": "BNB", "quote": "USDT", "name": "BNB"},
            {"rank": 5, "symbol": "XRPUSDT", "base": "XRP", "quote": "USDT", "name": "Ripple"},
            {"rank": 6, "symbol": "DOGEUSDT", "base": "DOGE", "quote": "USDT", "name": "Dogecoin"},
            {"rank": 7, "symbol": "ADAUSDT", "base": "ADA", "quote": "USDT", "name": "Cardano"},
            {"rank": 8, "symbol": "AVAXUSDT", "base": "AVAX", "quote": "USDT", "name": "Avalanche"},
            {"rank": 9, "symbol": "LINKUSDT", "base": "LINK", "quote": "USDT", "name": "Chainlink"},
            {"rank": 10, "symbol": "DOTUSDT", "base": "DOT", "quote": "USDT", "name": "Polkadot"},
        ]
        return {
            "tokens": fallback[:limit],
            "count": len(fallback[:limit]),
            "source": "fallback",
            "error": str(e)
        }


def _get_token_name(base: str) -> str:
    """Get full name for token base currency."""
    # SOTA: Extended token name mapping
    names = {
        "BTC": "Bitcoin",
        "ETH": "Ethereum",
        "SOL": "Solana",
        "BNB": "BNB",
        "TAO": "Bittensor",
        "FET": "Fetch.ai",
        "ONDO": "Ondo Finance",
        "XRP": "Ripple",
        "ADA": "Cardano",
        "DOGE": "Dogecoin",
        "SOMI": "SOMI",
        "XLM": "Stellar",
        "LINK": "Chainlink",
        "DOT": "Polkadot",
        "AVAX": "Avalanche",
        "MATIC": "Polygon",
        "NEAR": "NEAR Protocol",
        "ATOM": "Cosmos",
        "UNI": "Uniswap",
        "LTC": "Litecoin",
        "TRX": "TRON",
        "SHIB": "Shiba Inu",
        "APT": "Aptos",
        "ARB": "Arbitrum",
        "OP": "Optimism",
        "SUI": "Sui",
        "SEI": "Sei",
    }
    return names.get(base, base)


# ============================================================================
# Cache Stats Endpoint (Smart Local Data Warehouse)
# ============================================================================

@market_router.get("/cache/stats")
async def get_cache_stats():
    """
    Get cache statistics for the Smart Local Data Warehouse.

    Returns:
        Dict with cache info: total size, symbols cached, last sync times
    """
    from src.infrastructure.data.historical_data_loader import HistoricalDataLoader

    loader = HistoricalDataLoader()
    stats = loader.get_cache_stats()

    return {
        "status": "ok",
        "cache": stats
    }


@market_router.delete("/cache/clear")
async def clear_cache(symbol: Optional[str] = None, interval: Optional[str] = None):
    """
    Clear cache for specific symbol/interval or all.

    Args:
        symbol: Optional symbol to clear (e.g., 'BTCUSDT')
        interval: Optional interval to clear (e.g., '15m')

    Returns:
        Confirmation message
    """
    from src.infrastructure.data.historical_data_loader import HistoricalDataLoader

    loader = HistoricalDataLoader()
    loader.clear_cache(symbol=symbol, interval=interval)

    return {
        "status": "ok",
        "message": f"Cache cleared: symbol={symbol or 'ALL'}, interval={interval or 'ALL'}"
    }


# ============================================================================
# DYNAMIC BLACKLIST (SOTA P2)
# ============================================================================

# In-memory blacklist (persisted via settings)
_symbol_blacklist: set = set()

@market_router.get("/blacklist")
async def get_blacklist():
    """
    Get current symbol blacklist.

    SOTA P2: Symbols in blacklist are excluded from trading.
    """
    return {
        "blacklist": list(_symbol_blacklist),
        "count": len(_symbol_blacklist)
    }


@market_router.post("/blacklist/{symbol}")
async def add_to_blacklist(symbol: str, reason: str = Query(default="MANUAL")):
    """
    Add symbol to blacklist.

    Args:
        symbol: Symbol to blacklist (e.g., BTCUSDT)
        reason: Reason for blacklisting
    """
    symbol = symbol.upper()
    _symbol_blacklist.add(symbol)
    logger.warning(f"🚫 Added to blacklist: {symbol} (reason: {reason})")

    return {
        "status": "ok",
        "symbol": symbol,
        "reason": reason,
        "blacklist_count": len(_symbol_blacklist)
    }


@market_router.delete("/blacklist/{symbol}")
async def remove_from_blacklist(symbol: str):
    """
    Remove symbol from blacklist.
    """
    symbol = symbol.upper()
    _symbol_blacklist.discard(symbol)
    logger.info(f"✅ Removed from blacklist: {symbol}")

    return {
        "status": "ok",
        "symbol": symbol,
        "blacklist_count": len(_symbol_blacklist)
    }


def is_symbol_blacklisted(symbol: str) -> bool:
    """Check if symbol is blacklisted."""
    return symbol.upper() in _symbol_blacklist


# ============================================================================
# EXCHANGE FILTERS (SOTA P0)
# ============================================================================

@market_router.get("/filters/{symbol}")
async def get_exchange_filters(symbol: str):
    """
    Get exchange filters for a symbol.

    SOTA P0: Returns LOT_SIZE, PRICE_FILTER, MIN_NOTIONAL info.
    Useful for debugging order sizing issues.

    Note: Binance /fapi/v1/exchangeInfo doesn't support symbol filtering,
    so we fetch all and filter client-side.
    """
    try:
        def _fetch_info():
            from src.infrastructure.api.binance_futures_client import BinanceFuturesClient

            # Use Live client to check filters (standard across testnet/live usually)
            client = BinanceFuturesClient(use_testnet=False)
            # Fetch ALL exchange info (Binance doesn't support symbol param for filtering)
            return client.get_exchange_info()

        import asyncio
        exchange_info = await asyncio.to_thread(_fetch_info)

        if not exchange_info or not exchange_info.get('symbols'):
            return {
                "error": "Failed to fetch exchange info",
                "status": "error"
            }

        # Find the target symbol in the list
        target_symbol = symbol.upper()
        symbol_info = None

        for sym in exchange_info['symbols']:
            if sym.get('symbol') == target_symbol:
                symbol_info = sym
                break

        if not symbol_info:
            return {
                "error": f"Symbol {target_symbol} not found",
                "status": "error"
            }

        filters = {f['filterType']: f for f in symbol_info.get('filters', [])}

        lot_size = filters.get('LOT_SIZE', {})
        price_filter = filters.get('PRICE_FILTER', {})
        min_notional = filters.get('MIN_NOTIONAL', {})

        return {
            "symbol": target_symbol,
            "lot_size": {
                "minQty": lot_size.get('minQty'),
                "maxQty": lot_size.get('maxQty'),
                "stepSize": lot_size.get('stepSize')
            },
            "price_filter": {
                "minPrice": price_filter.get('minPrice'),
                "maxPrice": price_filter.get('maxPrice'),
                "tickSize": price_filter.get('tickSize')
            },
            "min_notional": {
                "notional": min_notional.get('notional', '5')
            },
            "precision": {
                "quantity": symbol_info.get('quantityPrecision'),
                "price": symbol_info.get('pricePrecision')
            }
        }

    except Exception as e:
        logger.error(f"Failed to get filters for {symbol}: {e}")
        return {
            "error": str(e),
            "status": "error"
        }


# ============================================================================
# MARKET INTELLIGENCE (SOTA P1)
# ============================================================================

@market_router.get("/intelligence")
async def get_market_intelligence():
    """
    Get market intelligence summary for all symbols.

    SOTA P1: Returns funding rates, leverage limits, and direction hints.
    """
    try:
        from src.infrastructure.exchange.market_intelligence_service import MarketIntelligenceService

        service = MarketIntelligenceService()
        if not service.load_from_file():
            return {
                "error": "Intelligence file not found. Run: python backend/scripts/get_market_intelligence.py",
                "status": "error"
            }

        return {
            "status": "ok",
            "stats": service.get_stats(),
            "symbols": service.get_funding_summary()
        }

    except Exception as e:
        logger.error(f"Failed to get intelligence: {e}")
        return {
            "error": str(e),
            "status": "error"
        }


@market_router.get("/intelligence/{symbol}")
async def get_symbol_intelligence(symbol: str):
    """
    Get intelligence for a specific symbol.
    """
    try:
        from src.infrastructure.exchange.market_intelligence_service import MarketIntelligenceService

        service = MarketIntelligenceService()
        if not service.load_from_file():
            return {"error": "Intelligence file not found", "status": "error"}

        intel = service.get_intelligence(symbol.upper())

        if not intel:
            return {"error": f"No intelligence for {symbol}", "status": "error"}

        return {
            "symbol": intel.symbol,
            "funding_rate": intel.funding_rate,
            "direction_hint": service.get_funding_direction_hint(symbol),
            "max_leverage": intel.max_leverage,
            "mark_price": intel.mark_price,
            "next_funding_time": intel.next_funding_time,
            "rules": {
                "min_qty": intel.min_qty,
                "step_size": intel.step_size,
                "min_notional": intel.min_notional
            }
        }

    except Exception as e:
        logger.error(f"Failed to get intelligence for {symbol}: {e}")
        return {"error": str(e), "status": "error"}


@market_router.get("/top-volume")
async def get_top_volume_pairs(
    limit: int = Query(default=10, ge=1, le=50, description="Number of top pairs"),
    quote_asset: str = Query(default="USDT", description="Quote asset filter")
):
    """
    SOTA: Get current top N trading pairs by 24h volume from Binance.

    Use this to check trending tokens and update your .env SYMBOLS list weekly.

    Example Response:
    ```json
    {
        "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", ...],
        "env_format": "SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT,...",
        "fetched_at": "2026-01-05T03:00:00Z"
    }
    ```

    Args:
        limit: Number of top pairs to return (default: 10, max: 50)
        quote_asset: Filter by quote asset (default: USDT)

    Returns:
        Current top N volume pairs with ready-to-copy ENV format
    """
    try:
        from datetime import datetime, timezone
        from src.infrastructure.api.binance_rest_client import BinanceRestClient
        from src.config.market_mode import MarketMode

        client = BinanceRestClient(market_mode=MarketMode.FUTURES)
        symbols = client.get_top_volume_pairs(limit=limit, quote_asset=quote_asset)

        if not symbols:
            return {
                "error": "Failed to fetch top volume pairs",
                "status": "error"
            }

        # Create ready-to-copy ENV format
        env_format = f"SYMBOLS={','.join(symbols)}"

        return {
            "symbols": symbols,
            "count": len(symbols),
            "env_format": env_format,
            "quote_asset": quote_asset,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "recommendation": "Copy env_format value to your .env file and restart backend"
        }

    except Exception as e:
        logger.error(f"Failed to fetch top volume pairs: {e}")
        return {
            "error": str(e),
            "status": "error"
        }
