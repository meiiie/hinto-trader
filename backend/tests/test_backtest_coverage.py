from datetime import datetime, timezone

from scripts.check_backtest_coverage import check_coverage


class FakeLoader:
    def __init__(self, coverage):
        self.coverage = coverage

    def get_cache_coverage(self, symbol, interval):
        return self.coverage[(symbol, interval)]


def test_coverage_report_marks_missing_interval(monkeypatch):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 2, tzinfo=timezone.utc)
    fake = FakeLoader(
        {
            ("BTCUSDT", "15m"): {"start": start, "end": end, "count": 10},
            ("BTCUSDT", "1m"): {"start": start, "end": datetime(2026, 1, 1, 12, tzinfo=timezone.utc), "count": 10},
        }
    )

    monkeypatch.setattr("scripts.check_backtest_coverage.HistoricalDataLoader", lambda: fake)

    report = check_coverage(["BTCUSDT"], ["15m", "1m"], start, end)

    assert report["ok"] is False
    assert report["rows"][0]["covers"] is True
    assert report["rows"][1]["covers"] is False
