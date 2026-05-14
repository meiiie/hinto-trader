"""Check cached candle coverage before running paper-like backtests."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.infrastructure.data.historical_data_loader import HistoricalDataLoader


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone(timedelta(hours=7))).astimezone(timezone.utc)


def _interval_delta(interval: str) -> timedelta:
    unit = interval[-1]
    value = int(interval[:-1])
    if unit == "m":
        return timedelta(minutes=value)
    if unit == "h":
        return timedelta(hours=value)
    if unit == "d":
        return timedelta(days=value)
    raise ValueError(f"Unsupported interval: {interval}")


def _find_internal_gaps(
    loader: HistoricalDataLoader,
    symbol: str,
    interval: str,
    start_time: datetime,
    end_time: datetime,
) -> dict:
    empty = {
        "gap_count": 0,
        "max_gap_seconds": 0,
        "first_gap": None,
        "window_start": None,
        "window_end": None,
        "window_covers": None,
    }
    cache_path_getter = getattr(loader, "_get_cache_path", None)
    if not callable(cache_path_getter):
        return empty

    cache_path = cache_path_getter(symbol, interval)
    if not cache_path.exists():
        return empty

    try:
        df = pd.read_parquet(cache_path, columns=["timestamp"])
    except Exception:
        return empty

    if df.empty:
        return empty

    ts = pd.to_datetime(df["timestamp"], utc=True).sort_values().drop_duplicates()
    window_ts = ts[(ts >= pd.Timestamp(start_time)) & (ts <= pd.Timestamp(end_time))]
    if window_ts.empty:
        return {**empty, "window_covers": False}

    window_start = window_ts.min().to_pydatetime()
    window_end = window_ts.max().to_pydatetime()
    window_covers = window_start <= start_time and window_end >= end_time
    if len(window_ts) < 2:
        return {
            **empty,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "window_covers": window_covers,
        }

    expected_delta = _interval_delta(interval)
    diffs = window_ts.diff().dropna()
    gaps = diffs[diffs > expected_delta]
    if gaps.empty:
        return {
            **empty,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "window_covers": window_covers,
        }

    first_gap_index = gaps.index[0]
    first_gap_pos = window_ts.index.get_loc(first_gap_index)
    before = window_ts.iloc[first_gap_pos - 1].to_pydatetime()
    after = window_ts.iloc[first_gap_pos].to_pydatetime()
    max_gap = max(gaps.dt.total_seconds())
    return {
        "gap_count": int(len(gaps)),
        "max_gap_seconds": int(max_gap),
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "window_covers": window_covers,
        "first_gap": {
            "after": before.isoformat(),
            "before": after.isoformat(),
        },
    }


def check_coverage(
    symbols: list[str],
    intervals: list[str],
    start_time: datetime,
    end_time: datetime,
) -> dict:
    loader = HistoricalDataLoader()
    rows = []
    ok = True
    for symbol in symbols:
        for interval in intervals:
            coverage = loader.get_cache_coverage(symbol, interval)
            start = coverage.get("start")
            end = coverage.get("end")
            internal_gaps = _find_internal_gaps(loader, symbol, interval, start_time, end_time)
            covers = bool(
                start
                and end
                and start <= start_time
                and end >= end_time
                and internal_gaps["gap_count"] == 0
                and internal_gaps["window_covers"] is not False
            )
            ok = ok and covers
            rows.append(
                {
                    "symbol": symbol,
                    "interval": interval,
                    "covers": covers,
                    "cache_start": start.isoformat() if start else None,
                    "cache_end": end.isoformat() if end else None,
                    "count": coverage.get("count", 0),
                    "internal_gap_count": internal_gaps["gap_count"],
                    "max_gap_seconds": internal_gaps["max_gap_seconds"],
                    "window_cache_start": internal_gaps["window_start"],
                    "window_cache_end": internal_gaps["window_end"],
                    "window_covers": internal_gaps["window_covers"],
                    "first_gap": internal_gaps["first_gap"],
                }
            )
    return {
        "ok": ok,
        "start_time_utc": start_time.isoformat(),
        "end_time_utc": end_time.isoformat(),
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Hinto backtest cache coverage.")
    parser.add_argument("--symbols", required=True, help="Comma-separated symbols.")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD in UTC+7.")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD in UTC+7.")
    parser.add_argument("--intervals", default="15m,1m", help="Comma-separated intervals. Default: 15m,1m")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if any interval is not fully covered.")
    args = parser.parse_args()

    report = check_coverage(
        [s.strip().upper() for s in args.symbols.split(",") if s.strip()],
        [i.strip() for i in args.intervals.split(",") if i.strip()],
        _parse_date(args.start),
        _parse_date(args.end),
    )
    print(json.dumps(report, indent=2))
    if args.strict and not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
