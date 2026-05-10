"""
Signals Router - Signal History and Lifecycle API

Provides endpoints for:
- Signal history (paginated)
- Pending signals
- Signal execution
- Signal details

**Feature: signal-lifecycle-tracking**
"""

from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional
from datetime import datetime
import logging

from src.api.dependencies import get_signal_lifecycle_service, get_realtime_service
from src.application.services.signal_lifecycle_service import SignalLifecycleService
from src.application.services.realtime_service import RealtimeService

router = APIRouter(
    prefix="/signals",
    tags=["signals"]
)

logger = logging.getLogger(__name__)


@router.get("/history")
async def get_signal_history(
    days: int = Query(default=7, ge=1, le=90, description="Number of days"),
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    # SOTA Phase 25: Server-side filtering for signal analysis
    symbol: Optional[str] = Query(default=None, description="Filter by symbol (e.g., BTCUSDT)"),
    signal_type: Optional[str] = Query(default=None, description="Filter by type: buy or sell"),
    status: Optional[str] = Query(default=None, description="Filter by status: generated, pending, executed, expired"),
    min_confidence: Optional[float] = Query(default=None, ge=0.0, le=1.0, description="Minimum confidence"),
    lifecycle_service: SignalLifecycleService = Depends(get_signal_lifecycle_service)
):
    """
    Get paginated signal history with optional filters.

    Returns all signals generated in the last N days with pagination.

    Args:
        days: Number of days to look back (default: 7, max: 90)
        page: Page number (1-indexed)
        limit: Items per page (max: 100)
        symbol: Filter by trading symbol (optional)
        signal_type: Filter by buy/sell (optional)
        status: Filter by signal status (optional)
        min_confidence: Minimum confidence threshold (optional)

    Returns:
        Paginated signal history with signal details
    """
    offset = (page - 1) * limit

    # SOTA FIX: Offload blocking DB calls
    def _get_signals_sync():
        data = lifecycle_service.get_filtered_signal_history(
            days=days,
            limit=limit,
            offset=offset,
            symbol=symbol.upper() if symbol else None,
            signal_type=signal_type.lower() if signal_type else None,
            status=status.lower() if status else None,
            min_confidence=min_confidence
        )
        count = lifecycle_service.get_filtered_count(
            days=days,
            symbol=symbol.upper() if symbol else None,
            signal_type=signal_type.lower() if signal_type else None,
            status=status.lower() if status else None,
            min_confidence=min_confidence
        )
        return data, count

    import asyncio
    signals, total = await asyncio.to_thread(_get_signals_sync)

    total_pages = (total + limit - 1) // limit if total > 0 else 1

    return {
        "signals": [s.to_dict() for s in signals],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": total_pages
        }
    }


@router.get("/pending")
async def get_pending_signals(
    lifecycle_service: SignalLifecycleService = Depends(get_signal_lifecycle_service)
):
    """
    Get all pending signals.

    Returns signals that are waiting for execution.

    Returns:
        List of pending signals
    """
    import asyncio
    signals = await asyncio.to_thread(lifecycle_service.get_pending_signals)

    return {
        "pending_signals": [s.to_dict() for s in signals],
        "count": len(signals)
    }


@router.get("/export")
async def export_signals(
    days: int = Query(default=30, ge=1, le=90, description="Number of days"),
    symbol: Optional[str] = Query(default=None, description="Filter by symbol"),
    signal_type: Optional[str] = Query(default=None, description="Filter by type: buy or sell"),
    status: Optional[str] = Query(default=None, description="Filter by status"),
    min_confidence: Optional[float] = Query(default=None, ge=0.0, le=1.0, description="Minimum confidence"),
    format: str = Query(default="csv", description="Export format: csv or json"),
    lifecycle_service: SignalLifecycleService = Depends(get_signal_lifecycle_service)
):
    """
    Export filtered signals to CSV or JSON.

    SOTA Phase 25: Bulk export for signal analysis and research.

    Args:
        days: Number of days to export (max: 90)
        symbol: Filter by symbol (optional)
        signal_type: Filter by buy/sell (optional)
        status: Filter by status (optional)
        min_confidence: Minimum confidence (optional)
        format: Export format - csv or json

    Returns:
        List of signal records for export
    """
    from fastapi.responses import Response
    import csv
    import io

    # Get all filtered signals (no pagination limit for export)
    def _get_signals_sync():
        return lifecycle_service.get_filtered_signal_history(
            days=days,
            limit=10000,  # Max export limit
            offset=0,
            symbol=symbol.upper() if symbol else None,
            signal_type=signal_type.lower() if signal_type else None,
            status=status.lower() if status else None,
            min_confidence=min_confidence
        )

    import asyncio
    signals = await asyncio.to_thread(_get_signals_sync)

    if format.lower() == "json":
        return {
            "signals": [s.to_dict() for s in signals],
            "total": len(signals),
            "exported_at": datetime.now().isoformat()
        }

    # CSV export
    output = io.StringIO()
    writer = csv.writer(output)

    # Header row
    writer.writerow([
        "ID", "Symbol", "Type", "Status", "Confidence",
        "Price", "Entry", "StopLoss", "TP1", "TP2", "TP3",
        "R:R Ratio", "Generated At", "Executed At",
        "Order ID", "Indicators", "Reasons"
    ])

    # Data rows
    for s in signals:
        tp = s.tp_levels or {}
        writer.writerow([
            s.id,
            s.symbol,
            s.signal_type.value,
            s.status.value,
            f"{s.confidence:.2%}",
            s.price,
            s.entry_price,
            s.stop_loss,
            tp.get('tp1'),
            tp.get('tp2'),
            tp.get('tp3'),
            s.risk_reward_ratio,
            s.generated_at.isoformat() if s.generated_at else None,
            s.executed_at.isoformat() if s.executed_at else None,
            s.order_id,
            str(s.indicators),
            "; ".join(s.reasons) if s.reasons else ""
        ])

    csv_content = output.getvalue()

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=signals_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        }
    )


@router.get("/{signal_id}")
async def get_signal_by_id(
    signal_id: str,
    lifecycle_service: SignalLifecycleService = Depends(get_signal_lifecycle_service)
):
    """
    Get signal by ID.

    Args:
        signal_id: UUID of the signal

    Returns:
        Signal details
    """
    signal = lifecycle_service.get_signal_by_id(signal_id)

    if not signal:
        raise HTTPException(status_code=404, detail=f"Signal not found: {signal_id}")

    return signal.to_dict()


@router.post("/{signal_id}/execute")
async def execute_signal(
    signal_id: str,
    lifecycle_service: SignalLifecycleService = Depends(get_signal_lifecycle_service),
    realtime_service: RealtimeService = Depends(get_realtime_service)
):
    """
    Execute a pending signal.

    Creates an order from the signal and links them.

    Args:
        signal_id: UUID of the signal to execute

    Returns:
        Execution result with order_id
    """
    from src.api.dependencies import get_paper_trading_service

    # Get the signal
    signal = lifecycle_service.get_signal_by_id(signal_id)

    if not signal:
        raise HTTPException(status_code=404, detail=f"Signal not found: {signal_id}")

    if not signal.is_actionable:
        raise HTTPException(
            status_code=400,
            detail=f"Signal is not actionable (status: {signal.status.value})"
        )

    # Get current price
    latest_candle = realtime_service.get_latest_data('1m')
    if not latest_candle or latest_candle.close <= 0:
        raise HTTPException(status_code=503, detail="Cannot determine current price")

    # Execute via PaperTradingService - get from realtime_service's paper_service
    paper_service = realtime_service.paper_service
    if not paper_service:
        raise HTTPException(status_code=503, detail="Paper trading service not available")

    try:
        # Execute the trade
        order_id = paper_service.execute_trade(signal=signal, symbol="BTCUSDT")

        if order_id:
            # Link signal to order
            lifecycle_service.mark_executed(signal_id, order_id)

            return {
                "success": True,
                "signal_id": signal_id,
                "order_id": order_id,
                "message": "Signal executed successfully"
            }
        else:
            return {
                "success": False,
                "signal_id": signal_id,
                "error": "Order execution failed (position limit or insufficient balance)"
            }

    except Exception as e:
        logger.error(f"Error executing signal {signal_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{signal_id}/mark-pending")
async def mark_signal_pending(
    signal_id: str,
    lifecycle_service: SignalLifecycleService = Depends(get_signal_lifecycle_service)
):
    """
    Mark a signal as pending (shown to user).

    Args:
        signal_id: UUID of the signal

    Returns:
        Updated signal
    """
    signal = lifecycle_service.mark_pending(signal_id)

    if not signal:
        raise HTTPException(status_code=404, detail=f"Signal not found or not actionable: {signal_id}")

    return signal.to_dict()


@router.post("/{signal_id}/expire")
async def expire_signal(
    signal_id: str,
    lifecycle_service: SignalLifecycleService = Depends(get_signal_lifecycle_service)
):
    """
    Manually expire a signal.

    Args:
        signal_id: UUID of the signal

    Returns:
        Updated signal
    """
    signal = lifecycle_service.mark_expired(signal_id)

    if not signal:
        raise HTTPException(status_code=404, detail=f"Signal not found or not actionable: {signal_id}")

    return signal.to_dict()


@router.post("/expire-stale")
async def expire_stale_signals(
    lifecycle_service: SignalLifecycleService = Depends(get_signal_lifecycle_service)
):
    """
    Expire all stale signals (older than TTL).

    Returns:
        Count of expired signals
    """
    count = lifecycle_service.expire_stale_signals()

    return {
        "expired_count": count,
        "message": f"Expired {count} stale signals"
    }


@router.post("/flush", summary="Flush all pending signals")
async def flush_pending_signals():
    """Clear all pending signals from LocalSignalTracker.

    Called by BroSubSoul when pausing entries to prevent stale signals
    from executing after resume. Safe operation — only affects pending
    signals, not open positions.
    """
    import os
    env = os.getenv("ENV", "paper").lower()

    if env in ["live", "testnet"]:
        from src.api.dependencies import get_container
        container = get_container()
        live_service = container.get_live_trading_service()
        if live_service and hasattr(live_service, '_signal_tracker') and live_service._signal_tracker:
            count = len(live_service._signal_tracker.pending_signals)
            live_service._signal_tracker.clear_all()
            return {"success": True, "cleared": count}
        return {"success": True, "cleared": 0}

    return {"success": True, "cleared": 0, "detail": "paper mode"}


@router.get("/order/{order_id}")
async def get_signal_for_order(
    order_id: str,
    lifecycle_service: SignalLifecycleService = Depends(get_signal_lifecycle_service)
):
    """
    Get the signal that created an order.

    Args:
        order_id: UUID of the order

    Returns:
        Signal linked to the order
    """
    signal = lifecycle_service.get_signal_for_order(order_id)

    if not signal:
        raise HTTPException(status_code=404, detail=f"No signal found for order: {order_id}")

    return signal.to_dict()
