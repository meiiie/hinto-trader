from datetime import datetime, timedelta, timezone

from src.application.risk_management.circuit_breaker import CircuitBreaker


def test_low_profit_pair_blocks_both_sides_until_cooldown_expires():
    now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    cb = CircuitBreaker(
        max_consecutive_losses=999,
        daily_symbol_loss_limit=0,
        low_profit_pair_trade_limit=2,
        low_profit_pair_lookback_hours=24,
        low_profit_pair_cooldown_hours=6,
        low_profit_pair_required_pnl=0.0,
    )

    cb.record_trade_with_time("ETHUSDT", "LONG", -0.20, now)
    assert cb.is_blocked("ETHUSDT", "LONG", now + timedelta(minutes=1)) is False

    cb.record_trade_with_time("ETHUSDT", "SHORT", -0.10, now + timedelta(hours=1))

    assert cb.is_blocked("ETHUSDT", "LONG", now + timedelta(hours=2)) is True
    assert cb.is_blocked("ETHUSDT", "SHORT", now + timedelta(hours=2)) is True
    assert "Low-profit pair" in cb.get_block_reason("ETHUSDT", "LONG", now + timedelta(hours=2))
    assert cb.is_blocked("ETHUSDT", "LONG", now + timedelta(hours=8)) is False


def test_low_profit_pair_does_not_block_when_window_pnl_clears_threshold():
    now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    cb = CircuitBreaker(
        max_consecutive_losses=999,
        daily_symbol_loss_limit=0,
        low_profit_pair_trade_limit=2,
        low_profit_pair_lookback_hours=24,
        low_profit_pair_cooldown_hours=6,
        low_profit_pair_required_pnl=0.0,
    )

    cb.record_trade_with_time("BNBUSDT", "LONG", -0.20, now)
    cb.record_trade_with_time("BNBUSDT", "SHORT", 0.30, now + timedelta(hours=1))

    assert cb.is_blocked("BNBUSDT", "LONG", now + timedelta(hours=2)) is False
    assert cb._blocked_by_low_profit_pair == 0
