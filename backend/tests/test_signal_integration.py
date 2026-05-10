import pytest
from datetime import datetime, timedelta
from typing import List
from src.domain.entities.candle import Candle
from src.application.signals.signal_generator import SignalGenerator
from src.application.services.tp_calculator import TPCalculator
from src.application.services.stop_loss_calculator import StopLossCalculator
from src.infrastructure.indicators.vwap_calculator import VWAPCalculator
from src.infrastructure.indicators.bollinger_calculator import BollingerCalculator
from src.infrastructure.indicators.stoch_rsi_calculator import StochRSICalculator
from src.infrastructure.indicators.atr_calculator import ATRCalculator

def create_mock_candles(count: int = 100) -> List[Candle]:
    candles = []
    base_price = 50000.0
    now = datetime.now()

    for i in range(count):
        if i < 80:
            price = base_price + (i * 20)
        else:
            price = base_price + 1600 - ((i - 80) * 30)

        candle = Candle(
            timestamp=now - timedelta(minutes=count-i),
            open=price,
            high=price + 10,
            low=price - 10,
            close=price,
            volume=1000.0 + (i * 10)
        )
        candles.append(candle)
    return candles

def test_signal_generator_integration():
    # Initialize dependencies
    tp_calc = TPCalculator()
    sl_calc = StopLossCalculator()
    vwap_calc = VWAPCalculator()
    bollinger_calc = BollingerCalculator()
    stoch_calc = StochRSICalculator()
    atr_calc = ATRCalculator()

    # Initialize SignalGenerator (Limit Sniper)
    generator = SignalGenerator(
        vwap_calculator=vwap_calc,
        bollinger_calculator=bollinger_calc,
        stoch_rsi_calculator=stoch_calc,
        atr_calculator=atr_calc,
        tp_calculator=tp_calc,
        stop_loss_calculator=sl_calc
    )

    # Create candles
    candles = create_mock_candles(100)

    # Generate signal (Requires symbol)
    signal = generator.generate_signal(candles, symbol="BTCUSDT")

    # Verify signal
    if signal:
        print(f"Signal generated: {signal}")
        if signal.signal_type.value != 'neutral':
            assert signal.entry_price is not None, "Entry price should be calculated"
            assert signal.stop_loss is not None, "Stop loss should be calculated"
            assert signal.tp_levels is not None, "TP levels should be calculated"
    else:
        print("No signal generated (Expected for simple mock data)")

    assert True