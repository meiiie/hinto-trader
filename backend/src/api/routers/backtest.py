import logging

from fastapi import APIRouter, HTTPException

from ..schemas.backtest import BacktestRequest, BacktestResponse
from ...application.analysis.trend_filter import TrendFilter
from ...application.backtest.backtest_engine import BacktestEngine
from ...application.backtest.execution_simulator import ExecutionSimulator
from ...application.backtest.time_filter import TimeFilter
from ...application.risk_management.circuit_breaker import CircuitBreaker
from ...config.market_mode import MarketMode
from ...infrastructure.data.historical_data_loader import HistoricalDataLoader
from ...infrastructure.di_container import DIContainer
from ...trading_contract import parse_blocked_windows

router = APIRouter(
    prefix="/backtest",
    tags=["Backtest"],
)

logger = logging.getLogger(__name__)


@router.post("/run", response_model=BacktestResponse)
async def run_backtest(request: BacktestRequest):
    """
    Run a portfolio backtest using the same signal and risk contract used by live mode.
    """
    try:
        logger.info(f"Received backtest request for {request.symbols} [Mode: {request.market_mode}]")

        market_mode = MarketMode.FUTURES if request.market_mode == "futures" else MarketMode.SPOT

        container = DIContainer()
        signal_generator = container.get_signal_generator(
            use_btc_filter=request.use_btc_filter,
            sniper_lookback=request.sniper_lookback,
            sniper_proximity=request.sniper_proximity_pct / 100.0,
            use_delta_divergence=request.use_delta_divergence,
            use_mtf_trend=request.use_mtf_trend,
            mtf_ema_period=request.mtf_ema_period,
        )
        loader = HistoricalDataLoader(market_mode=market_mode)

        simulator = ExecutionSimulator(
            initial_balance=request.initial_balance,
            risk_per_trade=request.risk_per_trade,
            fixed_leverage=request.leverage,
            mode="SHARK_TANK",
            max_leverage=max(5.0, request.leverage),
            max_positions=request.max_positions,
            max_order_value=request.max_order_value,
            maintenance_margin_rate=request.maintenance_margin_rate,
            order_ttl_minutes=request.order_ttl_minutes,
            enable_time_based_exit=request.enable_time_based_exit,
            time_based_exit_duration_hours=request.time_based_exit_duration_hours,
            use_fixed_profit_3usd=request.use_fixed_profit_3usd,
            portfolio_target_pct=request.portfolio_target_pct,
            close_profitable_auto=request.close_profitable_auto,
            profitable_threshold_pct=request.profitable_threshold_pct,
            use_max_sl_validation=request.use_max_sl_validation,
            max_sl_pct=request.max_sl_pct,
            sl_on_close_only=request.sl_on_close_only,
            hard_cap_pct=request.hard_cap_pct / 100.0,
            use_1m_monitoring=request.use_1m_monitoring,
            ac_threshold_exit=request.ac_threshold_exit,
        )

        trend_filter = TrendFilter(ema_period=request.mtf_ema_period)

        circuit_breaker = None
        if request.enable_circuit_breaker:
            circuit_breaker = CircuitBreaker(
                max_consecutive_losses=request.max_consecutive_losses,
                cooldown_hours=request.cb_cooldown_hours,
                max_daily_drawdown_pct=request.cb_drawdown_limit,
            )

        time_filter = None
        if request.blocked_windows:
            time_filter = TimeFilter(
                timezone_offset_hours=7,
                blocked_windows=parse_blocked_windows(request.blocked_windows),
            )

        engine = BacktestEngine(
            signal_generator=signal_generator,
            loader=loader,
            simulator=simulator,
            trend_filter=trend_filter,
            circuit_breaker=circuit_breaker,
            symbol_quality_filter=container.get_symbol_quality_filter(market_mode=market_mode),
            time_filter=time_filter,
        )

        result = await engine.run_portfolio(
            symbols=request.symbols,
            interval=request.interval,
            start_time=request.start_time,
            end_time=request.end_time,
        )

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        return result

    except HTTPException:
        raise
    except ValueError as exc:
        logger.error(f"Backtest request validation failed: {exc}")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(f"Backtest failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
