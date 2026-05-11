from datetime import datetime, timezone

import pandas as pd

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


def test_coverage_report_marks_internal_cache_gap(monkeypatch, tmp_path):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc)
    cache_path = tmp_path / "1m.parquet"
    pd.DataFrame(
        {
            "timestamp": [
                datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
                datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
                datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc),
            ]
        }
    ).to_parquet(cache_path, index=False)

    class FakeLoaderWithPath:
        def get_cache_coverage(self, symbol, interval):
            return {"start": start, "end": end, "count": 3}

        def _get_cache_path(self, symbol, interval):
            return cache_path

    monkeypatch.setattr("scripts.check_backtest_coverage.HistoricalDataLoader", FakeLoaderWithPath)

    report = check_coverage(["BTCUSDT"], ["1m"], start, end)

    assert report["ok"] is False
    assert report["rows"][0]["covers"] is False
    assert report["rows"][0]["internal_gap_count"] == 1
    assert report["rows"][0]["max_gap_seconds"] == 120


def test_coverage_report_requires_window_data_to_reach_end(monkeypatch, tmp_path):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc)
    cache_path = tmp_path / "1m.parquet"
    pd.DataFrame(
        {
            "timestamp": [
                datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
                datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
                datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc),
                datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc),
            ]
        }
    ).to_parquet(cache_path, index=False)

    class FakeLoaderWithPath:
        def get_cache_coverage(self, symbol, interval):
            return {"start": start, "end": datetime(2026, 1, 2, tzinfo=timezone.utc), "count": 4}

        def _get_cache_path(self, symbol, interval):
            return cache_path

    monkeypatch.setattr("scripts.check_backtest_coverage.HistoricalDataLoader", FakeLoaderWithPath)

    report = check_coverage(["BTCUSDT"], ["1m"], start, end)

    assert report["ok"] is False
    assert report["rows"][0]["covers"] is False
    assert report["rows"][0]["internal_gap_count"] == 0
    assert report["rows"][0]["window_covers"] is False
    assert report["rows"][0]["window_cache_end"] == "2026-01-01T00:02:00+00:00"
