"""
Analytics API Router — v6.3.0

REST endpoints for institutional analytics.
All data sourced from Binance truth (binance_trades table).
"""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional
import logging
import os

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _get_analytics_services():
    """Lazy-load analytics services from DI container."""
    from ..dependencies import get_container
    container = get_container()

    engine = container.get_analytics_engine()
    session = container.get_session_analyzer()
    symbols = container.get_symbol_alpha_tracker()
    direction = container.get_direction_analyzer()
    collector = container.get_binance_trade_collector()
    report = container.get_analytics_report_service()

    return engine, session, symbols, direction, collector, report


@router.get("/summary")
async def get_analytics_summary(
    version: Optional[str] = Query(default=None, description="Filter by version tag"),
    days: Optional[int] = Query(default=None, description="Filter to last N days"),
):
    """Full analytics report (WR, PF, R:R, edge, Sharpe, equity curve, significance)."""
    try:
        engine, *_ = _get_analytics_services()
        return engine.get_full_report(version_tag=version, days=days)
    except Exception as e:
        logger.error(f"Analytics summary failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions")
async def get_session_heatmap(
    version: Optional[str] = Query(default=None),
):
    """Session performance heatmap (30-min slots, hourly, dead zone analysis)."""
    try:
        _, session_analyzer, *_ = _get_analytics_services()
        return session_analyzer.get_session_heatmap(version_tag=version)
    except Exception as e:
        logger.error(f"Session heatmap failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/symbols")
async def get_symbol_decomposition(
    version: Optional[str] = Query(default=None),
):
    """Per-symbol alpha decomposition (ALPHA+/NEUTRAL/TOXIC)."""
    try:
        _, _, symbol_tracker, *_ = _get_analytics_services()
        return symbol_tracker.get_symbol_decomposition(version_tag=version)
    except Exception as e:
        logger.error(f"Symbol decomposition failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/directions")
async def get_direction_split(
    version: Optional[str] = Query(default=None),
):
    """LONG vs SHORT performance split."""
    try:
        _, _, _, direction_analyzer, *_ = _get_analytics_services()
        return direction_analyzer.get_direction_split(version_tag=version)
    except Exception as e:
        logger.error(f"Direction split failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/equity")
async def get_equity_curve(
    version: Optional[str] = Query(default=None),
    days: Optional[int] = Query(default=None),
):
    """Equity curve data points."""
    try:
        engine, *_ = _get_analytics_services()
        report = engine.get_full_report(version_tag=version, days=days)
        return {
            "equity_curve": report.get("equity_curve", []),
            "total_trades": report.get("total_trades", 0),
        }
    except Exception as e:
        logger.error(f"Equity curve failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/significance")
async def get_statistical_significance(
    version: Optional[str] = Query(default=None),
):
    """Statistical edge test (Z-test p-value)."""
    try:
        engine, *_ = _get_analytics_services()
        report = engine.get_full_report(version_tag=version)
        return report.get("significance", {})
    except Exception as e:
        logger.error(f"Significance test failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dead-zones")
async def get_dead_zone_analysis(
    version: Optional[str] = Query(default=None),
):
    """Dead zone effectiveness and recommendations."""
    try:
        _, session_analyzer, *_ = _get_analytics_services()
        data = session_analyzer.get_session_heatmap(version_tag=version)
        return data.get("dead_zone_analysis", {})
    except Exception as e:
        logger.error(f"Dead zone analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reconcile")
async def trigger_reconciliation():
    """Manually trigger Binance trade reconciliation."""
    env = os.getenv("ENV", "paper").lower()
    if env not in ("live", "testnet"):
        return {"error": "Reconciliation only available in LIVE/TESTNET mode"}

    try:
        _, _, _, _, collector, _ = _get_analytics_services()
        result = await collector.reconcile()
        return result
    except Exception as e:
        logger.error(f"Reconciliation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/daily-report")
async def trigger_daily_report():
    """Manually trigger daily analytics report (reconcile + compute + Telegram)."""
    try:
        _, _, _, _, _, report_service = _get_analytics_services()
        result = await report_service.generate_daily_report()
        return result
    except Exception as e:
        logger.error(f"Daily report failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/today")
async def get_today_metrics():
    """Quick metrics for today (UTC+7)."""
    try:
        engine, *_ = _get_analytics_services()
        return engine.get_today_metrics()
    except Exception as e:
        logger.error(f"Today metrics failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/snapshots")
async def get_snapshots(
    days: int = Query(default=30, description="Number of days of snapshots"),
):
    """Historical daily analytics snapshots."""
    try:
        engine, *_ = _get_analytics_services()
        return {"snapshots": engine.repo.get_snapshots(days=days)}
    except Exception as e:
        logger.error(f"Snapshots failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
