from datetime import datetime, timedelta
from types import SimpleNamespace

from src.application.services.stop_loss_calculator import StopLossCalculator
from src.application.services.tp_calculator import TPCalculator
from src.application.signals.signal_generator import SignalGenerator
from src.application.signals.strategies.momentum_pullback import MomentumPullbackStrategy
from src.application.signals.strategy_ids import MOMENTUM_PULLBACK_STRATEGY_ID
from src.domain.entities.candle import Candle
from src.domain.entities.strategy_contract import MOMENTUM_PULLBACK_RUNNER
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


def _trend_pullback_candles(count: int = 220) -> list[Candle]:
    candles = []
    for i in range(count):
        price = 100.0 + i * 0.05
        candles.append(_candle(i, price, price + 0.35, price - 0.35, price + 0.08))

    fast_area = 100.0 + (count - 20) * 0.05
    for i in range(count - 20, count - 2):
        price = fast_area + (i - (count - 20)) * 0.015
        candles[i] = _candle(i, price, price + 0.22, price - 0.16, price + 0.04)
    candles[-2] = _candle(count - 2, fast_area - 0.55, fast_area + 0.05, fast_area - 0.60, fast_area - 0.45)
    candles[-1] = _candle(count - 1, fast_area + 0.06, fast_area + 0.82, fast_area + 0.01, fast_area + 0.70, 1_600.0)
    return candles


def _ctx(candles: list[Candle], atr: float = 0.30) -> SimpleNamespace:
    return SimpleNamespace(
        candles=candles,
        current_candle=candles[-1],
        current_price=candles[-1].close,
        atr_result=SimpleNamespace(atr_value=atr),
        indicators={},
    )


def test_momentum_pullback_contract_is_positive_skew():
    assert MOMENTUM_PULLBACK_RUNNER.strategy_id == MOMENTUM_PULLBACK_STRATEGY_ID
    assert MOMENTUM_PULLBACK_RUNNER.is_positive_skew_candidate


def test_momentum_pullback_generates_long_reclaim():
    strategy = MomentumPullbackStrategy(
        ema_fast=12,
        ema_slow=48,
        momentum_short_bars=12,
        momentum_long_bars=48,
        volume_lookback=20,
    )
    signal = strategy.generate(_ctx(_trend_pullback_candles()), "BTCUSDT", htf_bias="BULLISH")

    assert signal is not None
    assert signal.signal_type == SignalType.BUY
    assert signal.is_limit_order is False
    assert signal.stop_loss < signal.entry_price
    assert signal.tp_levels["tp1"] > signal.entry_price
    assert signal.risk_reward_ratio == 2.4
    assert signal.indicators["strategy_id"] == MOMENTUM_PULLBACK_STRATEGY_ID
    assert signal.indicators["research_exit_profile"]["profile_name"] == "momentum_pullback_2p4r"


def test_momentum_pullback_rejects_counter_htf_bias():
    strategy = MomentumPullbackStrategy(
        ema_fast=12,
        ema_slow=48,
        momentum_short_bars=12,
        momentum_long_bars=48,
        volume_lookback=20,
    )

    assert strategy.generate(_ctx(_trend_pullback_candles()), "BTCUSDT", htf_bias="BEARISH") is None


def test_signal_generator_can_select_momentum_pullback_strategy():
    generator = SignalGenerator(
        vwap_calculator=VWAPCalculator(),
        bollinger_calculator=BollingerCalculator(),
        stoch_rsi_calculator=StochRSICalculator(),
        atr_calculator=ATRCalculator(),
        tp_calculator=TPCalculator(),
        stop_loss_calculator=StopLossCalculator(),
        strategy_id=MOMENTUM_PULLBACK_STRATEGY_ID,
    )

    signal = generator.generate_signal(_trend_pullback_candles(), "BTCUSDT", htf_bias="BULLISH")

    assert signal is not None
    assert signal.indicators["strategy_id"] == MOMENTUM_PULLBACK_STRATEGY_ID
