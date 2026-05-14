from datetime import datetime, timedelta
from types import SimpleNamespace

from src.application.services.stop_loss_calculator import StopLossCalculator
from src.application.services.tp_calculator import TPCalculator
from src.application.signals.signal_generator import SignalGenerator
from src.application.signals.strategies.donchian_breakout import DonchianBreakoutStrategy
from src.application.signals.strategy_ids import DONCHIAN_BREAKOUT_STRATEGY_ID
from src.domain.entities.candle import Candle
from src.domain.entities.strategy_contract import DONCHIAN_BREAKOUT_RUNNER
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


def _trend_candles(count: int = 150) -> list[Candle]:
    candles = []
    for i in range(count):
        price = 100.0 + i * 0.03
        candles.append(_candle(i, price, price + 0.4, price - 0.4, price + 0.1))
    return candles


def _ctx(candles: list[Candle], atr: float = 0.35) -> SimpleNamespace:
    return SimpleNamespace(
        candles=candles,
        current_candle=candles[-1],
        current_price=candles[-1].close,
        atr_result=SimpleNamespace(atr_value=atr),
        indicators={},
    )


def test_donchian_breakout_contract_is_positive_skew():
    assert DONCHIAN_BREAKOUT_RUNNER.strategy_id == DONCHIAN_BREAKOUT_STRATEGY_ID
    assert DONCHIAN_BREAKOUT_RUNNER.is_positive_skew_candidate


def test_donchian_breakout_generates_long_on_volume_confirmed_breakout():
    strategy = DonchianBreakoutStrategy(
        lookback=20,
        ema_fast=8,
        ema_slow=21,
        volume_lookback=20,
        min_volume_ratio=1.2,
    )
    candles = _trend_candles(60)
    previous_high = max(c.high for c in candles[-21:-1])
    candles[-1] = _candle(60, previous_high + 0.1, previous_high + 0.9, previous_high - 0.2, previous_high + 0.7, 2_000.0)

    signal = strategy.generate(_ctx(candles), "BTCUSDT", htf_bias="BULLISH")

    assert signal is not None
    assert signal.signal_type == SignalType.BUY
    assert signal.is_limit_order is False
    assert signal.stop_loss < signal.entry_price
    assert signal.tp_levels["tp1"] > signal.entry_price
    assert signal.risk_reward_ratio == 3.2
    assert signal.indicators["strategy_id"] == DONCHIAN_BREAKOUT_STRATEGY_ID
    assert signal.indicators["research_exit_profile"]["profile_name"] == "donchian_breakout_3p2r_strict"


def test_donchian_breakout_rejects_low_volume_breakout():
    strategy = DonchianBreakoutStrategy(
        lookback=20,
        ema_fast=8,
        ema_slow=21,
        volume_lookback=20,
        min_volume_ratio=2.0,
    )
    candles = _trend_candles(60)
    previous_high = max(c.high for c in candles[-21:-1])
    candles[-1] = _candle(60, previous_high + 0.1, previous_high + 0.9, previous_high - 0.2, previous_high + 0.7, 1_100.0)

    assert strategy.generate(_ctx(candles), "BTCUSDT", htf_bias="BULLISH") is None


def test_signal_generator_can_select_donchian_breakout_strategy():
    candles = _trend_candles(220)
    previous_high = max(c.high for c in candles[-193:-1])
    candles[-1] = _candle(220, previous_high + 0.1, previous_high + 1.1, previous_high - 0.2, previous_high + 0.8, 2_000.0)

    generator = SignalGenerator(
        vwap_calculator=VWAPCalculator(),
        bollinger_calculator=BollingerCalculator(),
        stoch_rsi_calculator=StochRSICalculator(),
        atr_calculator=ATRCalculator(),
        tp_calculator=TPCalculator(),
        stop_loss_calculator=StopLossCalculator(),
        strategy_id=DONCHIAN_BREAKOUT_STRATEGY_ID,
    )

    signal = generator.generate_signal(candles, "BTCUSDT", htf_bias="BULLISH")

    assert signal is not None
    assert signal.indicators["strategy_id"] == DONCHIAN_BREAKOUT_STRATEGY_ID
