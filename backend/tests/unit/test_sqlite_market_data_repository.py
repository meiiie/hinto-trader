from datetime import datetime, timedelta

from src.domain.entities.candle import Candle
from src.domain.entities.indicator import Indicator
from src.infrastructure.persistence.sqlite_market_data_repository import SQLiteMarketDataRepository


def test_symbol_starting_with_digit_round_trips_and_cleans_up(tmp_path):
    repo = SQLiteMarketDataRepository(db_path=str(tmp_path / "market.db"))
    timestamp = datetime(2026, 1, 15, 12, 0, 0)
    candle = Candle(
        timestamp=timestamp,
        open=0.001,
        high=0.0012,
        low=0.0009,
        close=0.0011,
        volume=12345.0,
    )
    indicator = Indicator(ema_7=0.00105, rsi_6=55.0, volume_ma_20=10000.0)

    repo.save_candle(candle, indicator, "1m", symbol="1000BONKUSDT")

    candles = repo.get_latest_candles("1000BONKUSDT", "1m", limit=5)
    assert len(candles) == 1
    assert candles[0].candle.close == candle.close
    assert repo.get_record_count("1m", symbol="1000BONKUSDT") == 1

    deleted = repo.delete_candles_before(
        "1m",
        timestamp + timedelta(minutes=1),
        symbol="1000BONKUSDT",
    )

    assert deleted == 1
    assert repo.get_record_count("1m", symbol="1000BONKUSDT") == 0


def test_delete_candles_before_missing_symbol_table_returns_zero(tmp_path):
    repo = SQLiteMarketDataRepository(db_path=str(tmp_path / "market.db"))

    deleted = repo.delete_candles_before(
        "1m",
        datetime(2026, 1, 15, 12, 0, 0),
        symbol="NEWTOKENUSDT",
    )

    assert deleted == 0
