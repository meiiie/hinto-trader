import pytest

from src.application.backtest.execution_simulator import ExecutionSimulator
from src.domain.entities.trading_signal import SignalType, TradingSignal


def test_backtest_fixed_leverage_is_capped_by_account_risk():
    simulator = ExecutionSimulator(
        initial_balance=100.0,
        risk_per_trade=0.01,
        max_positions=4,
        fixed_leverage=20.0,
        max_order_value=1_000_000.0,
        symbol_rules={
            "TESTUSDT": {
                "max_leverage": 20.0,
                "min_qty": 1.0,
                "step_size": 1.0,
                "min_notional": 5.0,
            }
        },
    )
    signal = TradingSignal(
        symbol="TESTUSDT",
        signal_type=SignalType.BUY,
        confidence=0.9,
        price=100.0,
        entry_price=100.0,
        stop_loss=99.0,
        tp_levels={"tp1": 102.0},
        is_limit_order=True,
    )

    simulator.place_order(signal)

    order = simulator.pending_orders["TESTUSDT"]
    intended_loss_at_stop = abs(order["target_price"] - order["stop_loss"]) * order["initial_size"]

    assert order["notional"] == pytest.approx(100.0)
    assert order["locked_margin"] == pytest.approx(5.0)
    assert order["leverage_used"] == pytest.approx(20.0)
    assert intended_loss_at_stop <= 1.0 + 1e-9
