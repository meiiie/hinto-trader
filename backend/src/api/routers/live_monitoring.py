"""
Live Trading Monitoring API Router

Provides REST API endpoints and WebSocket for real-time monitoring of Live Trading System.

Endpoints:
- GET /api/live/shark-tank - Shark Tank state
- GET /api/live/pending-orders - Pending orders
- GET /api/live/positions - Open positions
- GET /api/live/system-health - System health metrics
- GET /api/live/events - Recent events
- WS /ws/live/updates - Real-time WebSocket updates
"""

import logging
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import JSONResponse


logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/api/live", tags=["live-monitoring"])

# Event buffer (last 100 events)
event_buffer = deque(maxlen=100)

# Active WebSocket connections
active_connections: List[WebSocket] = []

# Reference to LiveTradingRunner (will be set by main)
live_runner: Optional[Any] = None


def set_live_runner(runner):
    """Set reference to LiveTradingRunner for data access"""
    global live_runner
    live_runner = runner
    logger.info("✅ Live runner reference set for monitoring API")


def add_event(event_type: str, data: Dict[str, Any]):
    """
    Add event to buffer and broadcast to WebSocket clients.

    Args:
        event_type: Event type (signal_generated, order_placed, etc)
        data: Event data
    """
    event = {
        'type': event_type,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'data': data
    }

    event_buffer.append(event)

    # Broadcast to WebSocket clients
    import asyncio
    asyncio.create_task(broadcast_event('event_log', event))


async def broadcast_event(event_type: str, data: Any):
    """
    Broadcast event to all connected WebSocket clients.

    Args:
        event_type: Event type
        data: Event data
    """
    if not active_connections:
        return

    message = {
        'type': event_type,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'data': data
    }

    # Send to all connections
    disconnected = []
    for connection in active_connections:
        try:
            await connection.send_json(message)
        except Exception as e:
            logger.warning(f"Failed to send to WebSocket client: {e}")
            disconnected.append(connection)

    # Remove disconnected clients
    for conn in disconnected:
        if conn in active_connections:
            active_connections.remove(conn)


# ============================================================================
# REST API Endpoints
# ============================================================================

@router.get("/shark-tank")
async def get_shark_tank_status():
    """
    Get current Shark Tank state.

    Returns:
        {
            "total_signals": int,
            "accepted_count": int,
            "rejected_count": int,
            "signals": [
                {
                    "symbol": str,
                    "side": str,
                    "confidence": float,
                    "entry_price": float,
                    "timestamp": str,
                    "status": str  # "pending", "accepted", "rejected"
                }
            ],
            "proximity_alerts": [
                {
                    "symbol": str,
                    "distance_pct": float
                }
            ]
        }
    """
    if not live_runner or not live_runner.shark_tank:
        return JSONResponse(
            status_code=503,
            content={"error": "Live trading system not running"}
        )

    shark_tank = live_runner.shark_tank

    # Get signals from Shark Tank
    signals = []
    for signal in shark_tank.signal_queue:
        signals.append({
            'symbol': signal.symbol,
            'side': signal.signal_type.value,
            'confidence': signal.confidence,
            'entry_price': signal.entry_price,
            'timestamp': signal.generated_at.isoformat(),
            'status': 'pending'
        })

    # Get proximity alerts
    proximity_alerts = []
    if hasattr(shark_tank, 'proximity_sentry') and shark_tank.proximity_sentry:
        for symbol, distance in shark_tank.proximity_sentry.items():
            if distance < 0.005:  # Within 0.5%
                proximity_alerts.append({
                    'symbol': symbol,
                    'distance_pct': distance * 100
                })

    return {
        'total_signals': len(signals),
        'accepted_count': getattr(shark_tank, 'accepted_count', 0),
        'rejected_count': getattr(shark_tank, 'rejected_count', 0),
        'signals': signals,
        'proximity_alerts': proximity_alerts
    }


@router.get("/pending-orders")
async def get_pending_orders():
    """
    Get all pending orders.

    Returns:
        {
            "count": int,
            "orders": [
                {
                    "symbol": str,
                    "side": str,
                    "target_price": float,
                    "current_price": float,
                    "fill_progress_pct": float,
                    "size": float,
                    "notional": float,
                    "margin_locked": float,
                    "ttl_remaining_minutes": float,
                    "confidence": float,
                    "created_at": str
                }
            ]
        }
    """
    if not live_runner or not live_runner.execution_adapter:
        return JSONResponse(
            status_code=503,
            content={"error": "Live trading system not running"}
        )

    execution_adapter = live_runner.execution_adapter

    orders = []
    for symbol, order in execution_adapter.pending_orders.items():
        # Get current price for fill progress
        current_price = 0.0
        if live_runner.data_manager:
            candles = live_runner.data_manager.get_candles(symbol, '15m')
            if candles:
                current_price = candles[-1].close

        # Calculate fill progress
        target = order['target_price']
        fill_progress = 0.0
        if current_price > 0:
            if order['side'] == 'LONG':
                # LONG: Progress when price drops toward target
                fill_progress = max(0, min(100, (1 - (current_price / target)) * 100))
            else:
                # SHORT: Progress when price rises toward target
                fill_progress = max(0, min(100, ((current_price / target) - 1) * 100))

        # Calculate TTL remaining
        created_at = order.get('timestamp', datetime.now(timezone.utc))
        age_seconds = (datetime.now(timezone.utc) - created_at).total_seconds()
        ttl_minutes = live_runner.config.get('ttl_minutes', 50)
        ttl_remaining = max(0, ttl_minutes - (age_seconds / 60))

        orders.append({
            'symbol': symbol,
            'side': order['side'],
            'target_price': target,
            'current_price': current_price,
            'fill_progress_pct': fill_progress,
            'size': order['initial_size'],
            'notional': order['notional'],
            'margin_locked': order['locked_margin'],
            'ttl_remaining_minutes': ttl_remaining,
            'confidence': order.get('confidence'),
            'created_at': created_at.isoformat()
        })

    return {
        'count': len(orders),
        'orders': orders
    }


@router.get("/positions")
async def get_positions():
    """
    Get all open positions.

    Returns:
        {
            "count": int,
            "positions": [
                {
                    "symbol": str,
                    "side": str,
                    "entry_price": float,
                    "current_price": float,
                    "size": float,
                    "pnl": float,
                    "pnl_pct": float,
                    "tp_levels": dict,
                    "stop_loss": float,
                    "is_breakeven": bool,
                    "tp_hit_count": int,
                    "entry_time": str
                }
            ]
        }
    """
    if not live_runner or not live_runner.execution_adapter:
        return JSONResponse(
            status_code=503,
            content={"error": "Live trading system not running"}
        )

    execution_adapter = live_runner.execution_adapter

    positions = []
    for symbol, pos in execution_adapter.positions.items():
        # Get current price
        current_price = 0.0
        if live_runner.data_manager:
            candles = live_runner.data_manager.get_candles(symbol, '15m')
            if candles:
                current_price = candles[-1].close

        # Calculate P&L
        pnl = 0.0
        pnl_pct = 0.0
        if current_price > 0:
            entry = pos.entry_price
            size = pos.remaining_size

            if pos.side == 'LONG':
                pnl = (current_price - entry) * size
            else:  # SHORT
                pnl = (entry - current_price) * size

            pnl_pct = (pnl / pos.margin) * 100 if pos.margin > 0 else 0

        positions.append({
            'symbol': symbol,
            'side': pos.side,
            'entry_price': pos.entry_price,
            'current_price': current_price,
            'size': pos.remaining_size,
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'tp_levels': pos.tp_levels,
            'stop_loss': pos.stop_loss,
            'is_breakeven': pos.is_breakeven,
            'tp_hit_count': pos.tp_hit_count,
            'entry_time': pos.entry_time.isoformat()
        })

    return {
        'count': len(positions),
        'positions': positions
    }


@router.get("/system-health")
async def get_system_health():
    """
    Get system health metrics.

    Returns:
        {
            "balance": float,
            "used_margin": float,
            "locked_in_orders": float,
            "available_balance": float,
            "open_positions": int,
            "pending_orders": int,
            "total_slots": int,
            "available_slots": int,
            "websocket_status": {
                "connected": bool,
                "streams": int
            },
            "frequency_limiter": {
                "daily_count": int,
                "daily_limit": int,
                "monthly_count": int,
                "monthly_limit": int
            }
        }
    """
    if not live_runner:
        return JSONResponse(
            status_code=503,
            content={"error": "Live trading system not running"}
        )

    # Get execution adapter stats
    stats = {}
    if live_runner.execution_adapter:
        stats = live_runner.execution_adapter.get_stats()

    # Get WebSocket status
    websocket_status = {
        'connected': False,
        'streams': 0
    }
    if live_runner.data_manager:
        websocket_status['connected'] = live_runner.data_manager._is_running
        websocket_status['streams'] = len(live_runner.data_manager.symbols) * 3  # 3 timeframes per symbol

    # Get frequency limiter stats
    frequency_stats = {}
    if live_runner.frequency_limiter:
        freq = live_runner.frequency_limiter.get_stats()
        frequency_stats = {
            'daily_count': freq['daily_count'],
            'daily_limit': freq['daily_limit'],
            'monthly_count': freq['monthly_count'],
            'monthly_limit': freq['monthly_limit']
        }

    return {
        **stats,
        'websocket_status': websocket_status,
        'frequency_limiter': frequency_stats
    }


@router.get("/short-filter-metrics")
async def get_short_filter_metrics():
    """
    Get SHORT signal filter metrics (3-layer defense).

    SOTA (Jan 2026): Block SHORT signals in LIVE mode.

    Returns:
        {
            "layer1_blocked": int,  # SignalGenerator
            "layer2_blocked": int,  # SharkTankCoordinator
            "layer3_blocked": int,  # LiveTradingService
            "total_blocked": int,
            "session_start": str,
            "mode": str
        }
    """
    if not live_runner:
        return JSONResponse(
            status_code=503,
            content={"error": "Live trading system not running"}
        )

    # Get metrics from all 3 layers
    signal_generator = getattr(live_runner, 'signal_generator', None)
    shark_tank = getattr(live_runner, 'shark_tank_coordinator', None)
    live_service = getattr(live_runner, 'live_trading_service', None)

    if not live_service:
        return JSONResponse(
            status_code=503,
            content={"error": "Live trading service not available"}
        )

    metrics = live_service.get_filter_metrics(
        signal_generator=signal_generator,
        shark_tank_coordinator=shark_tank
    )

    return {
        'layer1_blocked': metrics.layer1_blocked,
        'layer2_blocked': metrics.layer2_blocked,
        'layer3_blocked': metrics.layer3_blocked,
        'total_blocked': metrics.total_blocked,
        'session_start': metrics.session_start.isoformat(),
        'mode': metrics.mode
    }


@router.get("/events")
async def get_events(limit: int = Query(default=100, le=100)):
    """
    Get recent events.

    Args:
        limit: Maximum number of events to return (max 100)

    Returns:
        {
            "count": int,
            "events": [
                {
                    "type": str,
                    "timestamp": str,
                    "data": dict
                }
            ]
        }
    """
    events = list(event_buffer)[-limit:]

    return {
        'count': len(events),
        'events': events
    }


# ============================================================================
# WebSocket Endpoint
# ============================================================================

@router.websocket("/ws/updates")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time updates.

    Sends events:
    - shark_tank_update
    - pending_order_update
    - position_update
    - system_health_update (every 5s)
    - event_log
    """
    await websocket.accept()
    active_connections.append(websocket)

    logger.info(f"✅ WebSocket client connected (total: {len(active_connections)})")

    try:
        # Send initial data
        await websocket.send_json({
            'type': 'connected',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'data': {'message': 'Connected to Live Trading Monitor'}
        })

        # Keep connection alive
        while True:
            # Wait for messages from client (ping/pong)
            data = await websocket.receive_text()

            # Echo back (heartbeat)
            if data == 'ping':
                await websocket.send_text('pong')

    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected (remaining: {len(active_connections) - 1})")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
    finally:
        if websocket in active_connections:
            active_connections.remove(websocket)
