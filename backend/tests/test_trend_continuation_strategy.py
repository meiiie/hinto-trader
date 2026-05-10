from datetime import datetime, timedelta
from types import SimpleNamespace

from src.application.services.stop_loss_calculator import StopLossCalculator
from src.application.services.tp_calculator import TPCalculator
from src.application.signals.signal_generator import SignalGenerator
from src.application.signals.strategies.trend_continuation import TrendContinuationStrategy
from src.application.signals.strategy_ids import TREND_RUNNER_STRATEGY_ID
from src.domain.entities.candle import Candle
from src.domain.entities.trading_signal import SignalType
from src.infrastructure.indicators.atr_calculator import ATRCalculator
from src.infrastructure.indicators.bollinger_calculator import BollingerCalculator
from src.infrastructure.indicators.stoch_rsi_calculator import StochRSICalculator
from src.infrastructure.indicators.vwap_calculator import VWAPCalculator


def _candle(index: int, open_: float, high: float, low: float, close: float) -> Candle:
    return Candle(
        timestamp=datetime(2026, 1, 1) + timedelta(minutes=15 * index),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1_000.0,
    )


def _base_candles(count: int = 60) -> list[Candle]:
    candles = []
    for i in range(count):
        price = 100.0 + i * 0.02
        candles.append(_candle(i, price, price + 1.0, price - 0.6, price + 0.2))
    return candles


def _ctx(candles: list[Candle]) -> SimpleNamespace:
    return SimpleNamespace(
        candles=candles,
        current_candle=candles[-1],
        current_price=candles[-1].close,
        atr_result=SimpleNamespace(atr_value=1.0),
        indicators={},
    )


def test_trend_runner_generates_long_after_sweep_reclaim():
    candles = _base_candles()
    candles[-21:-1] = [
        _candle(39 + i, 100.6, 101.4, 100.0, 100.8)
        for i in range(20)
    ]
    candles[-1] = _candle(60, 99.8, 101.0, 99.6, 100.6)

    signal = TrendContinuationStrategy().generate(_ctx(candles), "BTCUSDT", htf_bias="BULLISH")

    assert signal is not None
    assert signal.signal_type == SignalType.BUY
    assert signal.is_limit_order is False
    assert signal.stop_loss < signal.entry_price
    assert signal.tp_levels["tp1"] > signal.entry_price
    assert signal.risk_reward_ratio == 3.0
    assert signal.indicators["strategy_id"] == TREND_RUNNER_STRATEGY_ID
    assert signal.indicators["research_exit_profile"]["profile_name"] == "trend_runner_3r"


def test_trend_runner_generates_short_after_sweep_reclaim():
    candles = _base_candles()
    candles[-21:-1] = [
        _candle(39 + i, 100.6, 101.4, 100.0, 100.8)
        for i in range(20)
    ]
    candles[-1] = _candle(60, 101.2, 101.8, 100.4, 100.7)

    signal = TrendContinuationStrategy().generate(_ctx(candles), "ETHUSDT", htf_bias="BEARISH")

    assert signal is not None
    assert signal.signal_type == SignalType.SELL
    assert signal.stop_loss > signal.entry_price
    assert signal.tp_levels["tp1"] < signal.entry_price
    assert signal.risk_reward_ratio == 3.0


def test_trend_runner_rejects_oversized_stop():
    candles = _base_candles()
    candles[-21:-1] = [
        _candle(39 + i, 100.6, 101.4, 100.0, 100.8)
        for i in range(20)
    ]
    candles[-1] = _candle(60, 98.0, 101.0, 95.0, 100.6)

    signal = TrendContinuationStrategy().generate(_ctx(candles), "BTCUSDT", htf_bias="BULLISH")

    assert signal is None


def test_signal_generator_can_select_trend_runner_strategy():
    candles = _base_candles()
    candles[-21:-1] = [
        _candle(39 + i, 100.6, 101.4, 100.0, 100.8)
        for i in range(20)
    ]
    candles[-1] = _candle(60, 99.8, 101.0, 99.6, 100.6)

    generator = SignalGenerator(
        vwap_calculator=VWAPCalculator(),
        bollinger_calculator=BollingerCalculator(),
        stoch_rsi_calculator=StochRSICalculator(),
        atr_calculator=ATRCalculator(),
        tp_calculator=TPCalculator(),
        stop_loss_calculator=StopLossCalculator(),
        strategy_id=TREND_RUNNER_STRATEGY_ID,
    )

    signal = generator.generate_signal(candles, "BTCUSDT", htf_bias="BULLISH")

    assert signal is not None
    assert signal.indicators["strategy_id"] == TREND_RUNNER_STRATEGY_ID
    assert signal.risk_reward_ratio == 3.0
