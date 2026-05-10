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
