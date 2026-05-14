from datetime import datetime, timedelta
from types import SimpleNamespace

from src.application.services.stop_loss_calculator import StopLossCalculator
from src.application.services.tp_calculator import TPCalculator
from src.application.signals.signal_generator import SignalGenerator
from src.application.signals.strategies.volatility_squeeze_breakout import (
    VolatilitySqueezeBreakoutStrategy,
)
from src.application.signals.strategy_ids import VOLATILITY_SQUEEZE_STRATEGY_ID
from src.domain.entities.candle import Candle
from src.domain.entities.strategy_contract import VOLATILITY_SQUEEZE_RUNNER
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


def _squeeze_breakout_candles(count: int = 260) -> list[Candle]:
    candles = []
    for i in range(count - 45):
        price = 100.0 + i * 0.035
        candles.append(_candle(i, price, price + 0.35, price - 0.35, price + 0.04))
    base = candles[-1].close
    for i in range(count - 45, count - 1):
        wobble = 0.03 if i % 2 == 0 else -0.03
        price = base + (i - (count - 45)) * 0.01 + wobble
        candles.append(_candle(i, price, price + 0.08, price - 0.08, price + 0.01))
    previous = candles[-1].close
    candles.append(_candle(count - 1, previous + 0.05, previous + 1.05, previous, previous + 0.95, 1_800.0))
    return candles


def _ctx(candles: list[Candle], atr: float = 0.35) -> SimpleNamespace:
    return SimpleNamespace(
        candles=candles,
        current_candle=candles[-1],
        current_price=candles[-1].close,
        atr_result=SimpleNamespace(atr_value=atr),
        indicators={},
    )


def test_volatility_squeeze_contract_is_positive_skew():
    assert VOLATILITY_SQUEEZE_RUNNER.strategy_id == VOLATILITY_SQUEEZE_STRATEGY_ID
    assert VOLATILITY_SQUEEZE_RUNNER.is_positive_skew_candidate


def test_volatility_squeeze_generates_long_breakout():
    strategy = VolatilitySqueezeBreakoutStrategy(
        width_lookback=80,
        ema_fast=20,
        ema_slow=80,
        volume_lookback=20,
        min_volume_ratio=1.1,
    )

    signal = strategy.generate(_ctx(_squeeze_breakout_candles()), "BTCUSDT", htf_bias="BULLISH")

    assert signal is not None
    assert signal.signal_type == SignalType.BUY
    assert signal.stop_loss < signal.entry_price
    assert signal.tp_levels["tp1"] > signal.entry_price
    assert signal.risk_reward_ratio == 2.2
    assert signal.indicators["strategy_id"] == VOLATILITY_SQUEEZE_STRATEGY_ID
    assert signal.indicators["research_exit_profile"]["profile_name"] == "vol_squeeze_structure_2p2r"


def test_volatility_squeeze_rejects_breakout_without_squeeze():
    strategy = VolatilitySqueezeBreakoutStrategy(
        width_lookback=80,
        ema_fast=20,
        ema_slow=80,
        volume_lookback=20,
        min_volume_ratio=1.1,
    )
    candles = _squeeze_breakout_candles()
    for i in range(len(candles) - 45, len(candles) - 1):
        price = candles[i].close
        candles[i] = _candle(i, price, price + 1.0, price - 1.0, price + (0.3 if i % 2 == 0 else -0.3))

    assert strategy.generate(_ctx(candles), "BTCUSDT", htf_bias="BULLISH") is None


def test_signal_generator_can_select_volatility_squeeze_strategy():
    generator = SignalGenerator(
        vwap_calculator=VWAPCalculator(),
        bollinger_calculator=BollingerCalculator(),
        stoch_rsi_calculator=StochRSICalculator(),
        atr_calculator=ATRCalculator(),
        tp_calculator=TPCalculator(),
        stop_loss_calculator=StopLossCalculator(),
        strategy_id=VOLATILITY_SQUEEZE_STRATEGY_ID,
    )

    signal = generator.generate_signal(_squeeze_breakout_candles(), "BTCUSDT", htf_bias="BULLISH")

    assert signal is not None
    assert signal.indicators["strategy_id"] == VOLATILITY_SQUEEZE_STRATEGY_ID
