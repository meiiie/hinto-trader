"""Strategy contract models for research-first development.

These contracts describe how a strategy is expected to make money before it is
connected to backtests or live execution. They are intentionally small and do
not change current runtime behavior.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Tuple

from .broker_capabilities import BrokerCapabilities


class StrategyFamily(str, Enum):
    """High-level strategy families."""

    MEAN_REVERSION_SCALP = "mean_reversion_scalp"
    TREND_CONTINUATION = "trend_continuation"


class PayoffShape(str, Enum):
    """Expected payoff distribution."""

    HIGH_WIN_RATE_SMALL_WIN = "high_win_rate_small_win"
    POSITIVE_SKEW = "positive_skew"


@dataclass(frozen=True)
class StrategyContract:
    """Research contract for a strategy variant."""

    strategy_id: str
    family: StrategyFamily
    payoff_shape: PayoffShape
    min_reward_to_risk: float
    max_loss_r: float = 1.0
    requires_short_selling: bool = False
    requires_leverage: bool = False
    requires_intraday_round_trip: bool = True
    requires_market_data_stream: bool = True
    min_out_of_sample_trades: int = 1000
    validation_notes: Tuple[str, ...] = ()

    @property
    def is_positive_skew_candidate(self) -> bool:
        """True when the contract aims for winners larger than losers."""

        return (
            self.payoff_shape == PayoffShape.POSITIVE_SKEW
            and self.min_reward_to_risk > self.max_loss_r
        )

    def validate_for_broker(self, broker: BrokerCapabilities) -> Tuple[str, ...]:
        """Return blockers that prevent this strategy from running on a broker."""

        blockers = list(broker.automation_blockers())
        if self.requires_short_selling and not broker.supports_short_selling:
            blockers.append("strategy requires short selling")
        if self.requires_leverage and not broker.supports_leverage:
            blockers.append("strategy requires leverage")
        if self.requires_intraday_round_trip and not broker.supports_intraday_round_trip:
            blockers.append("strategy requires intraday round trips")
        if self.requires_market_data_stream and not broker.supports_market_data_stream:
            blockers.append("strategy requires streaming market data")
        return tuple(blockers)


MEAN_REVERSION_SCALPER = StrategyContract(
    strategy_id="liquidity_sniper_mean_reversion",
    family=StrategyFamily.MEAN_REVERSION_SCALP,
    payoff_shape=PayoffShape.HIGH_WIN_RATE_SMALL_WIN,
    min_reward_to_risk=0.8,
    max_loss_r=1.0,
    requires_short_selling=True,
    requires_leverage=True,
    validation_notes=(
        "legacy/scalping profile; must prove expectancy after fees and slippage",
        "do not promote based on win rate alone",
    ),
)


TREND_CONTINUATION_RUNNER = StrategyContract(
    strategy_id="liquidity_reclaim_trend_runner",
    family=StrategyFamily.TREND_CONTINUATION,
    payoff_shape=PayoffShape.POSITIVE_SKEW,
    min_reward_to_risk=1.5,
    max_loss_r=1.0,
    requires_short_selling=True,
    requires_leverage=False,
    validation_notes=(
        "new research track: cut failed breakouts quickly, trail successful moves",
        "optimize for R-multiple distribution, not headline win rate",
    ),
)


DONCHIAN_BREAKOUT_RUNNER = StrategyContract(
    strategy_id="donchian_breakout_trend_runner",
    family=StrategyFamily.TREND_CONTINUATION,
    payoff_shape=PayoffShape.POSITIVE_SKEW,
    min_reward_to_risk=2.0,
    max_loss_r=1.0,
    requires_short_selling=True,
    requires_leverage=False,
    validation_notes=(
        "research track: enter confirmed channel breakouts with ATR-based risk",
        "must be tested on pre-registered universes and multiple regimes",
        "designed for low win rate / larger winner distributions",
    ),
)


MOMENTUM_PULLBACK_RUNNER = StrategyContract(
    strategy_id="adaptive_momentum_pullback",
    family=StrategyFamily.TREND_CONTINUATION,
    payoff_shape=PayoffShape.POSITIVE_SKEW,
    min_reward_to_risk=1.8,
    max_loss_r=1.0,
    requires_short_selling=True,
    requires_leverage=False,
    validation_notes=(
        "research track: time-series momentum with pullback/reclaim entry",
        "avoid raw breakout chasing; require multi-horizon trend first",
        "must survive fixed-universe and out-of-sample tests before paper use",
    ),
)
