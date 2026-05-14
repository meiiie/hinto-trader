from datetime import datetime, timedelta
from types import SimpleNamespace

from src.application.services.stop_loss_calculator import StopLossCalculator
from src.application.services.tp_calculator import TPCalculator
from src.application.signals.signal_generator import SignalGenerator
from src.application.signals.strategies.liquidity_sweep_reversal import (
    LiquiditySweepReversalStrategy,
)
from src.application.signals.strategy_ids import LIQUIDITY_SWEEP_REVERSAL_STRATEGY_ID
from src.domain.entities.candle import Candle
from src.domain.entities.strategy_contract import LIQUIDITY_SWEEP_REVERSAL
from src.domain.entities.trading_signal import SignalType
from src.infrastructure.indicators.atr_calculator import ATRCalculator
from src.infrastructure.indicators.bollinger_calculator import BollingerCalculator
from src.infrastructure.indicators.stoch_rsi_calculator import StochRSICalculator
from src.infrastructure.indicators.vwap_calculator import VWAPCalculator


def _candle(index: int, open_: float, high: float, low: float, close: float, volume: float = 1_000.0) -> Candle:
    return Candle(
        timestamp=datetime(2026, 1, 1) + timedelta(minutes=15 * index),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def _range_candles(count: int = 170) -> list[Candle]:
    candles = []
    for i in range(count - 1):
        wobble = 0.12 if i % 2 == 0 else -0.12
        close = 100.0 + wobble * 0.2
        open_ = 100.0 - wobble * 0.1
        high = max(open_, close) + 0.22
        low = min(open_, close) - 0.22
        candles.append(_candle(i, open_, high, low, close))
    candles.append(_candle(count - 1, 99.92, 100.15, 99.35, 100.08, 1_550.0))
    return candles


def _ctx(candles: list[Candle], atr: float = 0.35) -> SimpleNamespace:
    return SimpleNamespace(
        candles=candles,
        current_candle=candles[-1],
        current_price=candles[-1].close,
        atr_result=SimpleNamespace(atr_value=atr),
        vwap_result=SimpleNamespace(vwap=100.0),
        indicators={},
    )


def test_liquidity_sweep_contract_is_research_positive_skew():
    assert LIQUIDITY_SWEEP_REVERSAL.strategy_id == LIQUIDITY_SWEEP_REVERSAL_STRATEGY_ID
    assert LIQUIDITY_SWEEP_REVERSAL.is_positive_skew_candidate


def test_liquidity_sweep_reversal_generates_long_reclaim():
    strategy = LiquiditySweepReversalStrategy()

    signal = strategy.generate(_ctx(_range_candles()), "BTCUSDT", htf_bias="NEUTRAL")

    assert signal is not None
    assert signal.signal_type == SignalType.BUY
    assert signal.stop_loss < signal.entry_price
    assert signal.tp_levels["tp1"] > signal.entry_price
    assert signal.risk_reward_ratio == 1.8
    assert signal.indicators["strategy_id"] == LIQUIDITY_SWEEP_REVERSAL_STRATEGY_ID
    assert signal.indicators["research_exit_profile"]["profile_name"] == "liquidity_sweep_reversal_1p8r"


def test_liquidity_sweep_reversal_rejects_unreclaimed_sweep():
    strategy = LiquiditySweepReversalStrategy()
    candles = _range_candles()
    candles[-1] = _candle(len(candles) - 1, 99.92, 100.00, 99.35, 99.55, 1_550.0)

    assert strategy.generate(_ctx(candles), "BTCUSDT", htf_bias="NEUTRAL") is None


def test_signal_generator_can_select_liquidity_sweep_strategy():
    generator = SignalGenerator(
        vwap_calculator=VWAPCalculator(),
        bollinger_calculator=BollingerCalculator(),
        stoch_rsi_calculator=StochRSICalculator(),
        atr_calculator=ATRCalculator(),
        tp_calculator=TPCalculator(),
        stop_loss_calculator=StopLossCalculator(),
        strategy_id=LIQUIDITY_SWEEP_REVERSAL_STRATEGY_ID,
    )

    signal = generator.generate_signal(_range_candles(), "BTCUSDT", htf_bias="NEUTRAL")

    assert signal is not None
    assert signal.indicators["strategy_id"] == LIQUIDITY_SWEEP_REVERSAL_STRATEGY_ID
