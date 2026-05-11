"""Check cached candle coverage before running paper-like backtests."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.infrastructure.data.historical_data_loader import HistoricalDataLoader


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone(timedelta(hours=7))).astimezone(timezone.utc)


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
            covers = bool(start and end and start <= start_time and end >= end_time)
            ok = ok and covers
            rows.append(
                {
                    "symbol": symbol,
                    "interval": interval,
                    "covers": covers,
                    "cache_start": start.isoformat() if start else None,
                    "cache_end": end.isoformat() if end else None,
                    "count": coverage.get("count", 0),
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
