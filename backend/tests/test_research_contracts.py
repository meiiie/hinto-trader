"""Tests for research contracts and broker capability gates."""

from src.domain.entities.broker_capabilities import (
    binance_futures_capabilities,
    vietnam_derivatives_manual_capabilities,
    vietnam_equities_manual_capabilities,
)
from src.domain.entities.strategy_contract import (
    MEAN_REVERSION_SCALPER,
    TREND_CONTINUATION_RUNNER,
    PayoffShape,
)
from src.trading_contract import (
    PRODUCTION_ADX_MAX_THRESHOLD,
    PRODUCTION_BLOCKED_WINDOWS_STR,
    PRODUCTION_CLOSE_PROFITABLE_AUTO,
    PRODUCTION_MAX_SL_PCT,
    PRODUCTION_PORTFOLIO_TARGET_PCT,
    PRODUCTION_PROFITABLE_THRESHOLD_PCT,
    PRODUCTION_USE_ADX_MAX_FILTER,
)


def test_binance_futures_is_automation_ready_for_current_scalper():
    broker = binance_futures_capabilities()

    assert broker.is_automation_ready is True
    assert MEAN_REVERSION_SCALPER.validate_for_broker(broker) == ()


def test_vietnam_equities_manual_profile_blocks_automation_and_short_scalping():
    broker = vietnam_equities_manual_capabilities("mbs")

    blockers = MEAN_REVERSION_SCALPER.validate_for_broker(broker)

    assert broker.is_automation_ready is False
    assert "no official live trading API" in blockers
    assert "manual OTP/order confirmation required" in blockers
    assert "strategy requires short selling" in blockers
    assert "strategy requires leverage" in blockers
    assert "strategy requires intraday round trips" in blockers


def test_vietnam_derivatives_manual_profile_still_blocks_open_source_bot_execution():
    broker = vietnam_derivatives_manual_capabilities("mbs")

    blockers = TREND_CONTINUATION_RUNNER.validate_for_broker(broker)

    assert broker.is_automation_ready is False
    assert "no official live trading API" in blockers
    assert "manual OTP/order confirmation required" in blockers
    assert "strategy requires streaming market data" in blockers


def test_trend_runner_contract_is_positive_skew_track():
    assert TREND_CONTINUATION_RUNNER.payoff_shape == PayoffShape.POSITIVE_SKEW
    assert TREND_CONTINUATION_RUNNER.is_positive_skew_candidate is True
    assert MEAN_REVERSION_SCALPER.is_positive_skew_candidate is False


def test_production_contract_keeps_paper_defaults_conservative():
    assert PRODUCTION_CLOSE_PROFITABLE_AUTO is False
    assert PRODUCTION_PROFITABLE_THRESHOLD_PCT >= 40.0
    assert "03:00-05:00" in PRODUCTION_BLOCKED_WINDOWS_STR
    assert PRODUCTION_USE_ADX_MAX_FILTER is True
    assert PRODUCTION_ADX_MAX_THRESHOLD == 40.0
    assert PRODUCTION_MAX_SL_PCT == 1.2
    assert PRODUCTION_PORTFOLIO_TARGET_PCT == 10.0
