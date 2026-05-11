"""Backfill Binance Futures candle cache for backtest research windows."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.check_backtest_coverage import check_coverage
from src.infrastructure.data.historical_data_loader import HistoricalDataLoader
from src.trading_contract import get_production_symbol_blacklist


BINANCE_FUTURES_BASE_URL = "https://fapi.binance.com/fapi/v1"
DEFAULT_EXCLUDED_SYMBOLS = ("ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")
SAIGON_TZ = timezone(timedelta(hours=7))


def parse_local_date(value: str) -> datetime:
    """Parse YYYY-MM-DD as Asia/Saigon midnight, then convert to UTC."""
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=SAIGON_TZ).astimezone(timezone.utc)


def is_clean_symbol(symbol: str, min_base_length: int) -> bool:
    """Keep symbols that are easy to handle in runtime logs, config, and reports."""
    if not symbol.isascii() or not symbol.endswith("USDT"):
        return False
    if not all(char.isalnum() for char in symbol):
        return False
    return len(symbol[:-4]) >= min_base_length


def fetch_ranked_symbols(
    *,
    count: int,
    start_time: datetime,
    exclude_symbols: set[str],
    min_quote_volume_usd: float,
    min_base_length: int,
) -> list[str]:
    exchange_info = requests.get(f"{BINANCE_FUTURES_BASE_URL}/exchangeInfo", timeout=30)
    exchange_info.raise_for_status()
    ticker_24h = requests.get(f"{BINANCE_FUTURES_BASE_URL}/ticker/24hr", timeout=30)
    ticker_24h.raise_for_status()

    meta: dict[str, dict[str, Any]] = {
        item["symbol"]: item for item in exchange_info.json().get("symbols", [])
    }
    blacklist = set(get_production_symbol_blacklist())
    excluded = {symbol.upper() for symbol in exclude_symbols} | blacklist
    start_ms = int(start_time.timestamp() * 1000)

    tradable: set[str] = set()
    for symbol, item in meta.items():
        onboard_date = item.get("onboardDate")
        if onboard_date is not None and int(onboard_date) > start_ms:
            continue
        if (
            item.get("status") == "TRADING"
            and item.get("contractType") == "PERPETUAL"
            and item.get("quoteAsset") == "USDT"
            and symbol not in excluded
            and is_clean_symbol(symbol, min_base_length=min_base_length)
        ):
            tradable.add(symbol)

    ranked: list[tuple[float, str]] = []
    for item in ticker_24h.json():
        symbol = item.get("symbol", "")
        if symbol not in tradable:
            continue
        quote_volume = float(item.get("quoteVolume") or 0.0)
        if quote_volume >= min_quote_volume_usd:
            ranked.append((quote_volume, symbol))

    ranked.sort(reverse=True)
    symbols = [symbol for _, symbol in ranked[:count]]
    if len(symbols) < count:
        raise RuntimeError(f"Only found {len(symbols)} eligible symbols; requested {count}.")
    return symbols


def safe_delete_cache_file(loader: HistoricalDataLoader, symbol: str, interval: str) -> bool:
    cache_root = loader.CACHE_DIR.resolve()
    cache_path = loader._get_cache_path(symbol, interval).resolve()
    if not cache_path.is_relative_to(cache_root):
        raise RuntimeError(f"Refusing to delete cache outside cache root: {cache_path}")
    if cache_path.exists():
        cache_path.unlink()
        return True
    return False


async def backfill_symbols(
    *,
    symbols: list[str],
    intervals: list[str],
    start_time: datetime,
    end_time: datetime,
) -> list[dict[str, Any]]:
    loader = HistoricalDataLoader()
    rows: list[dict[str, Any]] = []
    total = len(symbols) * len(intervals)
    completed = 0

    for symbol in symbols:
        for interval in intervals:
            completed += 1
            print(f"[{completed}/{total}] Backfill {symbol} {interval}", flush=True)
            candles = await loader.load_candles(symbol, interval, start_time, end_time)
            rows.append(
                {
                    "symbol": symbol,
                    "interval": interval,
                    "candles": len(candles),
                    "first": candles[0].timestamp.isoformat() if candles else None,
                    "last": candles[-1].timestamp.isoformat() if candles else None,
                }
            )
    return rows


async def rebuild_failed_rows(
    *,
    rows: list[dict[str, Any]],
    start_time: datetime,
    end_time: datetime,
) -> list[dict[str, Any]]:
    loader = HistoricalDataLoader()
    rebuilt: list[dict[str, Any]] = []
    for row in rows:
        symbol = row["symbol"]
        interval = row["interval"]
        deleted = safe_delete_cache_file(loader, symbol, interval)
        print(f"[rebuild] {symbol} {interval} deleted={deleted}", flush=True)
        candles = await loader.load_candles(symbol, interval, start_time, end_time)
        rebuilt.append(
            {
                "symbol": symbol,
                "interval": interval,
                "deleted": deleted,
                "candles": len(candles),
                "first": candles[0].timestamp.isoformat() if candles else None,
                "last": candles[-1].timestamp.isoformat() if candles else None,
            }
        )
    return rebuilt


def coverage_failures(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in report["rows"] if not row["covers"]]


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="Backfill Hinto backtest candle cache.")
    parser.add_argument("--symbol-count", type=int, default=50)
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD in Asia/Saigon.")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD in Asia/Saigon.")
    parser.add_argument("--intervals", default="15m,1m")
    parser.add_argument("--exclude-symbols", default=",".join(DEFAULT_EXCLUDED_SYMBOLS))
    parser.add_argument("--min-quote-volume-usd", type=float, default=50_000_000.0)
    parser.add_argument("--min-base-length", type=int, default=3)
    parser.add_argument("--rebuild-failed", action="store_true")
    parser.add_argument("--output-json")
    args = parser.parse_args()

    start_time = parse_local_date(args.start)
    end_time = parse_local_date(args.end)
    intervals = [interval.strip() for interval in args.intervals.split(",") if interval.strip()]
    exclude_symbols = {symbol.strip().upper() for symbol in args.exclude_symbols.split(",") if symbol.strip()}

    symbols = fetch_ranked_symbols(
        count=args.symbol_count,
        start_time=start_time,
        exclude_symbols=exclude_symbols,
        min_quote_volume_usd=args.min_quote_volume_usd,
        min_base_length=args.min_base_length,
    )
    print(f"Selected {len(symbols)} symbols:", ",".join(symbols), flush=True)
    print(f"Window UTC: {start_time.isoformat()} -> {end_time.isoformat()}", flush=True)

    backfill_rows = await backfill_symbols(
        symbols=symbols,
        intervals=intervals,
        start_time=start_time,
        end_time=end_time,
    )

    coverage = check_coverage(symbols, intervals, start_time, end_time)
    rebuilt_rows: list[dict[str, Any]] = []
    failures = coverage_failures(coverage)
    if failures and args.rebuild_failed:
        print(f"Coverage failures after backfill: {len(failures)}. Rebuilding failed caches.", flush=True)
        rebuilt_rows = await rebuild_failed_rows(rows=failures, start_time=start_time, end_time=end_time)
        coverage = check_coverage(symbols, intervals, start_time, end_time)
        failures = coverage_failures(coverage)

    report = {
        "symbols": symbols,
        "intervals": intervals,
        "start_time_utc": start_time.isoformat(),
        "end_time_utc": end_time.isoformat(),
        "backfill_rows": backfill_rows,
        "rebuilt_rows": rebuilt_rows,
        "coverage": coverage,
    }

    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Coverage ok: {coverage['ok']}", flush=True)
    if failures:
        print("Remaining failures:", json.dumps(failures[:20], indent=2), flush=True)
        return 1
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
