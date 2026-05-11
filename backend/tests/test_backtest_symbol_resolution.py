from argparse import Namespace
from datetime import datetime, timezone

from run_backtest import _resolve_symbols
from src.config.market_mode import MarketMode


class _QualityFilter:
    def is_eligible(self, symbol, as_of=None):
        return True, ""


def test_top_argument_overrides_fixed_env_symbols(monkeypatch):
    monkeypatch.setenv("USE_FIXED_SYMBOLS", "true")
    monkeypatch.setenv("BACKTEST_SYMBOLS", "BTCUSDT,ETHUSDT,BNBUSDT")

    class FakeHistoricalVolumeService:
        def __init__(self, market_mode):
            self.market_mode = market_mode

        def get_top_symbols_at_date(self, date, limit):
            return ["SOLUSDT", "XRPUSDT", "DOGEUSDT"][:limit]

    from src.infrastructure.data import historical_volume_service

    monkeypatch.setattr(
        historical_volume_service,
        "HistoricalVolumeService",
        FakeHistoricalVolumeService,
    )

    args = Namespace(
        symbol=None,
        symbols=None,
        top=2,
        fill_top_eligible=False,
    )

    symbols = _resolve_symbols(
        args,
        datetime(2026, 5, 6, tzinfo=timezone.utc),
        MarketMode.FUTURES,
        _QualityFilter(),
    )

    assert symbols == ["SOLUSDT", "XRPUSDT"]
