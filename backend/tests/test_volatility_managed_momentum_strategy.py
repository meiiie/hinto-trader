from datetime import datetime, timedelta
from types import SimpleNamespace

from src.application.services.stop_loss_calculator import StopLossCalculator
from src.application.services.tp_calculator import TPCalculator
from src.application.signals.signal_generator import SignalGenerator
from src.application.signals.strategies.volatility_managed_momentum import (
    VolatilityManagedMomentumStrategy,
)
from src.application.signals.strategy_ids import VOLATILITY_MANAGED_MOMENTUM_STRATEGY_ID
from src.domain.entities.candle import Candle
from src.domain.entities.strategy_contract import VOLATILITY_MANAGED_MOMENTUM
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


def _low_vol_momentum_candles(count: int = 430) -> list[Candle]:
    candles = []
    price = 96.0
    for i in range(count - 55):
        wobble = 0.22 if i % 2 == 0 else -0.18
        price += 0.018 + wobble
        close = price
        open_ = close - 0.04
        candles.append(_candle(i, open_, close + 0.45, close - 0.45, close))

    for i in range(count - 55, count - 2):
        price += 0.035
        close = price + (0.015 if i % 2 == 0 else -0.015)
        open_ = close - 0.03
        candles.append(_candle(i, open_, close + 0.12, close - 0.12, close))

    previous = candles[-1].close - 0.80
    candles.append(_candle(count - 2, previous + 0.05, previous + 0.12, previous - 0.10, previous, 1_050.0))
    current = previous + 0.70
    candles.append(_candle(count - 1, previous - 0.04, current + 0.10, previous - 0.08, current, 1_300.0))
    return candles


def _ctx(candles: list[Candle], atr: float = 0.28) -> SimpleNamespace:
    return SimpleNamespace(
        candles=candles,
        current_candle=candles[-1],
        current_price=candles[-1].close,
        atr_result=SimpleNamespace(atr_value=atr),
        vwap_result=SimpleNamespace(vwap=candles[-1].close * 0.998),
        indicators={},
    )


def test_volatility_managed_momentum_contract_is_positive_skew():
    assert VOLATILITY_MANAGED_MOMENTUM.strategy_id == VOLATILITY_MANAGED_MOMENTUM_STRATEGY_ID
    assert VOLATILITY_MANAGED_MOMENTUM.is_positive_skew_candidate


def test_volatility_managed_momentum_generates_long_reclaim():
    strategy = VolatilityManagedMomentumStrategy()

    signal = strategy.generate(_ctx(_low_vol_momentum_candles()), "BTCUSDT", htf_bias="BULLISH")

    assert signal is not None
    assert signal.signal_type == SignalType.BUY
    assert signal.stop_loss < signal.entry_price
    assert signal.tp_levels["tp1"] > signal.entry_price
    assert signal.risk_reward_ratio == 2.2
    assert signal.indicators["strategy_id"] == VOLATILITY_MANAGED_MOMENTUM_STRATEGY_ID
    assert signal.indicators["research_exit_profile"]["profile_name"] == "vol_managed_momentum_2p2r"


def test_volatility_managed_momentum_rejects_high_recent_volatility():
    strategy = VolatilityManagedMomentumStrategy(
        ema_fast=12,
        ema_slow=40,
        momentum_bars=30,
        vol_short_bars=12,
        vol_long_bars=80,
        swing_lookback=8,
        max_vol_ratio=0.60,
        min_momentum_pct=0.002,
    )
    candles = _low_vol_momentum_candles()
    for idx in range(len(candles) - 14, len(candles) - 2):
        candle = candles[idx]
        offset = 0.75 if idx % 2 == 0 else -0.75
        close = candle.close + offset
        candles[idx] = _candle(idx, close - offset, close + 0.30, close - 0.30, close)

    assert strategy.generate(_ctx(candles), "BTCUSDT", htf_bias="BULLISH") is None


def test_signal_generator_can_select_volatility_managed_momentum_strategy():
    generator = SignalGenerator(
        vwap_calculator=VWAPCalculator(),
        bollinger_calculator=BollingerCalculator(),
        stoch_rsi_calculator=StochRSICalculator(),
        atr_calculator=ATRCalculator(),
        tp_calculator=TPCalculator(),
        stop_loss_calculator=StopLossCalculator(),
        strategy_id=VOLATILITY_MANAGED_MOMENTUM_STRATEGY_ID,
    )

    signal = generator.generate_signal(_low_vol_momentum_candles(), "BTCUSDT", htf_bias="BULLISH")

    assert signal is not None
    assert signal.indicators["strategy_id"] == VOLATILITY_MANAGED_MOMENTUM_STRATEGY_ID
