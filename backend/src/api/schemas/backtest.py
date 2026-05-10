from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from ...trading_contract import (
    PRODUCTION_AC_THRESHOLD_EXIT,
    PRODUCTION_BLOCKED_WINDOWS_STR,
    PRODUCTION_CB_COOLDOWN_HOURS,
    PRODUCTION_CB_MAX_CONSECUTIVE_LOSSES,
    PRODUCTION_CB_MAX_DAILY_DRAWDOWN_PCT,
    PRODUCTION_CLOSE_PROFITABLE_AUTO,
    PRODUCTION_HARD_CAP_PCT,
    PRODUCTION_LEVERAGE,
    PRODUCTION_MAX_POSITIONS,
    PRODUCTION_MAX_SL_PCT,
    PRODUCTION_MTF_EMA_PERIOD,
    PRODUCTION_ORDER_TTL_MINUTES,
    PRODUCTION_PORTFOLIO_TARGET_PCT,
    PRODUCTION_PROFITABLE_THRESHOLD_PCT,
    PRODUCTION_RISK_PER_TRADE,
    PRODUCTION_SL_ON_CANDLE_CLOSE,
    PRODUCTION_SNIPER_LOOKBACK,
    PRODUCTION_SNIPER_PROXIMITY,
    PRODUCTION_USE_1M_MONITORING,
    PRODUCTION_USE_DELTA_DIVERGENCE,
    PRODUCTION_USE_MAX_SL_VALIDATION,
    PRODUCTION_USE_MTF_TREND,
)


class BacktestRequest(BaseModel):
    symbols: List[str] = Field(
        ...,
        json_schema_extra={"example": ["BTCUSDT", "ETHUSDT"]},
    )
    interval: str = Field("15m", json_schema_extra={"example": "15m"})
    market_mode: Literal["spot", "futures"] = Field(
        "futures",
        description="Market mode: spot or futures",
    )
    start_time: datetime = Field(
        ...,
        json_schema_extra={"example": "2024-01-01T00:00:00"},
    )
    end_time: Optional[datetime] = Field(
        None,
        json_schema_extra={"example": "2024-02-01T00:00:00"},
    )
    initial_balance: float = Field(10000.0, gt=0)
    risk_per_trade: float = Field(PRODUCTION_RISK_PER_TRADE, gt=0, le=1.0)
    enable_circuit_breaker: bool = Field(True, description="Enable circuit breaker")
    max_positions: int = Field(
        PRODUCTION_MAX_POSITIONS,
        ge=1,
        description="Max concurrent positions (Shark Tank mode)",
    )
    leverage: float = Field(PRODUCTION_LEVERAGE, description="Fixed leverage")
    max_order_value: float = Field(50000.0, description="Liquidity cap")
    maintenance_margin_rate: float = Field(0.004, description="Maintenance margin rate")
    max_consecutive_losses: int = Field(
        PRODUCTION_CB_MAX_CONSECUTIVE_LOSSES,
        description="Circuit breaker max same-direction losses",
    )
    cb_cooldown_hours: float = Field(
        PRODUCTION_CB_COOLDOWN_HOURS,
        description="Circuit breaker cooldown hours",
    )
    cb_drawdown_limit: float = Field(
        PRODUCTION_CB_MAX_DAILY_DRAWDOWN_PCT,
        description="Circuit breaker portfolio drawdown limit",
    )
    order_ttl_minutes: int = Field(
        PRODUCTION_ORDER_TTL_MINUTES,
        ge=0,
        description="Pending-order TTL in minutes",
    )
    close_profitable_auto: bool = Field(
        PRODUCTION_CLOSE_PROFITABLE_AUTO,
        description="Auto-close positions when ROE threshold is reached",
    )
    profitable_threshold_pct: float = Field(
        PRODUCTION_PROFITABLE_THRESHOLD_PCT,
        description="ROE threshold for auto-close",
    )
    portfolio_target_pct: float = Field(
        PRODUCTION_PORTFOLIO_TARGET_PCT,
        ge=0.0,
        le=100.0,
        description="Portfolio target as percent of starting balance",
    )
    use_max_sl_validation: bool = Field(
        PRODUCTION_USE_MAX_SL_VALIDATION,
        description="Reject signals whose SL distance exceeds the configured cap",
    )
    max_sl_pct: float = Field(
        PRODUCTION_MAX_SL_PCT,
        gt=0.0,
        description="Maximum allowed SL distance in percent",
    )
    sl_on_close_only: bool = Field(
        PRODUCTION_SL_ON_CANDLE_CLOSE,
        description="Only trigger SL on candle close",
    )
    hard_cap_pct: float = Field(
        PRODUCTION_HARD_CAP_PCT,
        ge=0.0,
        description="Tick-level hard cap loss in percent",
    )
    use_1m_monitoring: bool = Field(
        PRODUCTION_USE_1M_MONITORING,
        description="Use 1m candles for SL/AC monitoring",
    )
    ac_threshold_exit: bool = Field(
        PRODUCTION_AC_THRESHOLD_EXIT,
        description="Exit AC at threshold price instead of candle close",
    )
    use_delta_divergence: bool = Field(
        PRODUCTION_USE_DELTA_DIVERGENCE,
        description="Enable delta divergence filter",
    )
    use_mtf_trend: bool = Field(
        PRODUCTION_USE_MTF_TREND,
        description="Enable 4h EMA trend filter",
    )
    mtf_ema_period: int = Field(
        PRODUCTION_MTF_EMA_PERIOD,
        ge=1,
        description="4h EMA period for MTF trend filter",
    )
    sniper_lookback: int = Field(
        PRODUCTION_SNIPER_LOOKBACK,
        ge=1,
        description="Swing-point lookback period",
    )
    sniper_proximity_pct: float = Field(
        PRODUCTION_SNIPER_PROXIMITY * 100.0,
        gt=0.0,
        description="Swing proximity threshold in percent",
    )
    blocked_windows: Optional[str] = Field(
        PRODUCTION_BLOCKED_WINDOWS_STR,
        description="Dead-zone windows in UTC+7, comma separated",
    )
    enable_time_based_exit: bool = Field(
        False,
        description="Enable time-based exit for long-duration losing trades",
    )
    time_based_exit_duration_hours: float = Field(
        2.0,
        description="Exit threshold in hours for time-based exit",
    )
    use_btc_filter: bool = Field(
        False,
        description="Filter altcoin signals based on BTC trend",
    )
    use_fixed_profit_3usd: bool = Field(
        False,
        description="Enable fixed $3 profit exit strategy",
    )


class BacktestTradeResponse(BaseModel):
    trade_id: str
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    pnl_usd: float
    pnl_pct: float
    exit_reason: str
    position_size: float
    leverage_at_entry: float
    quantity: Optional[float] = None
    notional_value: Optional[float] = None
    margin_used: Optional[float] = None
    funding_cost: Optional[float] = None


class BacktestStatsResponse(BaseModel):
    initial_balance: float
    final_balance: float
    net_return_usd: float
    net_return_pct: float
    total_trades: int
    win_rate: float
    winning_trades: int
    losing_trades: int


class EquityPoint(BaseModel):
    time: datetime
    balance: float


class CandleData(BaseModel):
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class BlockedInterval(BaseModel):
    symbol: str
    start_time: datetime
    end_time: datetime
    reason: str


class BacktestResponse(BaseModel):
    symbols: List[str]
    stats: BacktestStatsResponse
    trades: List[BacktestTradeResponse]
    equity: List[EquityPoint]
    candles: Dict[str, List[CandleData]]
    indicators: Dict[str, Dict[str, List[Optional[float]]]]
    blocked_periods: List[BlockedInterval] = []
