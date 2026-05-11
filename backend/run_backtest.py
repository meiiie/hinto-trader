"""
Hinto Stock Backtest Runner (Portfolio Edition)

CLI tool to run backtests on multiple pairs with SHARED CAPITAL.
Usage:
  python run_backtest.py --symbols "BTCUSDT,BNBUSDT" --days 30 --balance 10000 --leverage 10
  python run_backtest.py --top 10 --days 30 --leverage 10 --no-cb
"""

import asyncio
import argparse
import logging
import csv
import hashlib
import json
from datetime import datetime, timedelta, timezone
import os
import subprocess
import sys
from typing import Any, List, Dict, Tuple, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Load .env for BACKTEST_SYMBOLS / USE_FIXED_SYMBOLS
from dotenv import load_dotenv
_env_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.isdir(_env_dir):
    load_dotenv(os.path.join(_env_dir, ".env"))
else:
    load_dotenv(_env_dir)

# Add src to path (Robust approach)
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from src.infrastructure.di_container import DIContainer
from src.application.backtest.backtest_engine import BacktestEngine
from src.infrastructure.api.binance_rest_client import BinanceRestClient
from src.application.backtest.execution_simulator import ExecutionSimulator
try:
    from src.application.analysis.backtest_report import (
        calculate_max_drawdown_pct,
        write_equity_curve_csv,
    )
except ModuleNotFoundError as exc:
    if exc.name != "src.application.analysis.backtest_report":
        raise

    def calculate_max_drawdown_pct(equity_curve: List[Dict[str, Any]]) -> float:
        peak = 0.0
        max_drawdown = 0.0
        for point in equity_curve:
            balance = float(point.get("balance", 0.0) or 0.0)
            peak = max(peak, balance)
            if peak > 0:
                drawdown = ((peak - balance) / peak) * 100.0
                max_drawdown = max(max_drawdown, drawdown)
        return max_drawdown

    def write_equity_curve_csv(
        path: str,
        equity_curve: List[Dict[str, Any]],
        *,
        tz_offset_hours: int = 7,
    ) -> None:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Time", "Balance"])
            for point in equity_curve:
                ts = point.get("time")
                if isinstance(ts, datetime):
                    ts = ts + timedelta(hours=tz_offset_hours)
                    ts = ts.strftime("%Y-%m-%d %H:%M:%S")
                writer.writerow([ts, point.get("balance", 0.0)])
from src.application.signals.strategy_ids import DEFAULT_STRATEGY_ID, SUPPORTED_STRATEGY_IDS
from src.application.analysis.trend_filter import TrendFilter
from src.infrastructure.data.historical_data_loader import HistoricalDataLoader
from src.config.market_mode import MarketMode, get_market_config
from src.trading_contract import (
    PRODUCTION_AC_THRESHOLD_EXIT,
    PRODUCTION_ADX_MAX_THRESHOLD,
    PRODUCTION_BLOCKED_WINDOWS_STR,
    PRODUCTION_CLOSE_PROFITABLE_AUTO,
    PRODUCTION_HARD_CAP_PCT,
    PRODUCTION_MAX_SL_PCT,
    PRODUCTION_ORDER_TTL_MINUTES,
    PRODUCTION_PORTFOLIO_TARGET_PCT,
    PRODUCTION_PROFITABLE_THRESHOLD_PCT,
    PRODUCTION_SL_ON_CANDLE_CLOSE,
    PRODUCTION_SNIPER_LOOKBACK,
    PRODUCTION_SNIPER_PROXIMITY,
    PRODUCTION_USE_1M_MONITORING,
    PRODUCTION_USE_ADX_MAX_FILTER,
    PRODUCTION_USE_DELTA_DIVERGENCE,
    PRODUCTION_USE_MAX_SL_VALIDATION,
    PRODUCTION_USE_MTF_TREND,
)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=current_dir,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return "unknown"


def _stable_config_hash(config: Dict[str, Any]) -> str:
    payload = json.dumps(config, sort_keys=True, default=_json_default, ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]

# Setup logging
logging.basicConfig(
    level=logging.INFO, # Reveal Data Loader progress
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("BacktestRunner")
logger.setLevel(logging.INFO)


def _load_adaptive_router_components():
    try:
        from src.application.analysis.adaptive_regime_router import (
            AdaptiveRegimeRouter,
            AdaptiveRouterFeatures,
            BEARISH_TOXIC_SHORT_BLACKLIST,
            RollingRouterState,
            get_router_research_exit_profile,
            get_router_recommended_symbol_side_blocks,
        )
    except ModuleNotFoundError as exc:
        if exc.name == "src.application.analysis.adaptive_regime_router":
            raise RuntimeError(
                "Adaptive regime router is an optional research module and is not "
                "available in this checkout. Run without adaptive router flags, or "
                "restore that module before using --adaptive-regime-router or "
                "--rolling-adaptive-router."
            ) from exc
        raise

    return (
        AdaptiveRegimeRouter,
        AdaptiveRouterFeatures,
        BEARISH_TOXIC_SHORT_BLACKLIST,
        RollingRouterState,
        get_router_research_exit_profile,
        get_router_recommended_symbol_side_blocks,
    )


def _parse_symbol_side_blacklist(raw: str) -> List[Tuple[str, str]]:
    parsed: List[Tuple[str, str]] = []
    if not raw:
        return parsed

    for item in raw.split(","):
        token = item.strip().upper()
        if not token:
            continue
        if ":" not in token:
            raise ValueError(
                f"Invalid symbol-side blacklist entry '{item}'. Expected SYMBOL:SIDE, e.g. ETHUSDT:LONG"
            )
        symbol, side = [part.strip().upper() for part in token.split(":", 1)]
        if not symbol:
            raise ValueError(f"Invalid empty symbol in '{item}'.")
        if side not in {"LONG", "SHORT"}:
            raise ValueError(
                f"Invalid side '{side}' in '{item}'. Allowed values: LONG, SHORT."
            )
        parsed.append((symbol, side))
    return parsed


def _resolve_global_drawdown_pct(enable_global_cb: bool, drawdown_pct: float) -> float:
    if enable_global_cb:
        return drawdown_pct
    return float("inf")


def _apply_router_research_contract_defaults(args: argparse.Namespace) -> None:
    args.no_compound = True
    args.m1_monitoring = True
    args.ac_threshold_exit = True
    args.max_sl_validation = True
    args.delta_divergence = True
    args.mtf_trend = True

    override = getattr(args, "gb_runner_override", None)
    if override == "no_ac_trail3":
        args.close_profitable_auto = False
        args.trailing_atr = 3.0
    else:
        args.close_profitable_auto = True
        if override == "pt20":
            if args.profitable_threshold_pct < 20.0:
                args.profitable_threshold_pct = 20.0
        elif args.profitable_threshold_pct == 5.0:
            args.profitable_threshold_pct = 15.0

    if args.max_sl_pct is None:
        args.max_sl_pct = 1.2
    if args.mtf_ema == 50:
        args.mtf_ema = 20
    if args.max_pos > 4:
        args.max_pos = 4
    if args.ttl == 45:
        args.ttl = 50
    if args.fill_buffer == 0.1:
        args.fill_buffer = 0.0
    if not args.blocked_windows and not args.live_dz:
        args.blocked_windows = "06:00-08:00,14:00-15:00,18:00-21:00,23:00-00:00"


def _resolve_symbols(
    args: argparse.Namespace,
    start_time: datetime,
    market_mode: MarketMode,
    quality_filter,
    *,
    top_override: Optional[int] = None,
) -> List[str]:
    requested_top = top_override if top_override is not None else args.top
    symbols: List[str] = []

    if args.symbol:
        symbols = [args.symbol.upper()]
    elif args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
    elif requested_top:
        use_fixed = os.getenv("USE_FIXED_SYMBOLS", "false").lower() == "true"

        if use_fixed:
            print("ðŸ”’ Loading FIXED symbol list from .env (USE_FIXED_SYMBOLS=true)...")
            backtest_symbols_str = os.getenv("BACKTEST_SYMBOLS", "")

            if backtest_symbols_str:
                symbols = [s.strip().upper() for s in backtest_symbols_str.split(",")]
                symbols = symbols[:requested_top]
                print(f"ðŸ“‹ Fixed symbols ({len(symbols)}): {symbols[:5]}...")
            else:
                print("âš ï¸ BACKTEST_SYMBOLS is empty in .env, falling back to dynamic mode")
                use_fixed = False

        if not use_fixed:
            print(f"ðŸ” Calculating top {requested_top} volume pairs at START DATE (dynamic mode)...")

            from src.infrastructure.data.historical_volume_service import HistoricalVolumeService

            volume_service = HistoricalVolumeService(market_mode=market_mode)
            if args.fill_top_eligible:
                candidate_limit = max(requested_top * 5, 100)
                symbols, rejected_candidates = volume_service.get_top_eligible_symbols_at_date(
                    date=start_time,
                    limit=requested_top,
                    eligibility_fn=lambda sym: quality_filter.is_eligible(sym, as_of=start_time),
                    candidate_limit=candidate_limit,
                )
            else:
                rejected_candidates = []
                symbols = volume_service.get_top_symbols_at_date(
                    date=start_time,
                    limit=requested_top,
                )

            if not symbols:
                print("âš ï¸ Historical volume fetch failed, using current top pairs...")
                client = BinanceRestClient(market_mode=market_mode)
                symbols = client.get_top_volume_pairs(limit=requested_top, quote_asset="USDT")
            else:
                if args.fill_top_eligible:
                    rejected_count = len(rejected_candidates)
                    print(
                        f"ðŸ“Š Top eligible {len(symbols)}/{requested_top} at {start_time.date()}: {symbols[:5]}..."
                    )
                    if rejected_count > 0:
                        print(
                            f"ðŸ§¹ Preselection filter: scanned {min(candidate_limit, max(len(symbols) + rejected_count, 0))} "
                            f"ranked symbols | rejected {rejected_count}"
                        )
                else:
                    print(f"ðŸ“Š Top {requested_top} at {start_time.date()}: {symbols[:5]}...")
    else:
        symbols = ["BTCUSDT"]

    return sorted(list(set(symbols)))


def _router_ema(values: List[float], period: int) -> float:
    if not values:
        return 0.0
    k = 2 / (period + 1)
    ema_value = values[0]
    for value in values[1:]:
        ema_value = (value * k) + (ema_value * (1 - k))
    return ema_value


def _build_adaptive_router(args: argparse.Namespace) -> Any:
    AdaptiveRegimeRouter = _load_adaptive_router_components()[0]
    return AdaptiveRegimeRouter(
        neutral_breadth_threshold=args.router_neutral_breadth_threshold,
        neutral_spread_floor_pct=args.router_neutral_spread_floor_pct,
        bearish_trend_spread_pct=args.router_bearish_spread_pct,
        bearish_top50_breadth_threshold=args.router_bearish_breadth_threshold,
        moderate_bear_spread_pct=args.router_moderate_bear_spread_pct,
        moderate_bear_breadth_threshold=args.router_moderate_bear_breadth_threshold,
        strong_spread_breadth_threshold=args.router_strong_spread_breadth_threshold,
        strong_spread_pct=args.router_strong_spread_pct,
    )


async def _build_rolling_router_schedule(
    *,
    start_time: datetime,
    end_time: datetime,
    market_mode: MarketMode,
    quality_filter,
    default_top: int,
    router: Any,
    step_hours: int,
) -> tuple[Dict[str, Any], List[str], Dict[str, datetime], int, int]:
    """
    Research-only rolling router.

    Approximation by design:
    - recompute BTC regime on a fixed schedule
    - refresh breadth and tradable universe on the same schedule
    - constrain daily ranking to a research candidate universe built from
      start/mid/end historical rankings so the pass stays computationally viable

    This is still cheaper than a fully intraday adaptive router, but it removes
    the biggest false-negative source in v0: a stale regime snapshot taken only
    at the window start.
    """
    from src.infrastructure.data.historical_volume_service import HistoricalVolumeService
    from src.infrastructure.indicators.regime_detector import RegimeDetector

    (
        _AdaptiveRegimeRouter,
        AdaptiveRouterFeatures,
        _BEARISH_TOXIC_SHORT_BLACKLIST,
        RollingRouterState,
        _get_router_research_exit_profile,
        get_router_recommended_symbol_side_blocks,
    ) = _load_adaptive_router_components()

    volume_service = HistoricalVolumeService(market_mode=market_mode)
    router_loader = HistoricalDataLoader(market_mode=market_mode)
    trend_filter = TrendFilter(ema_period=20)
    regime_detector = RegimeDetector(adx_trending_threshold=25.0)

    def _is_fast_eligible(symbol: str, as_of: datetime) -> bool:
        symbol_upper = symbol.upper()
        if getattr(quality_filter, "block_non_ascii", False):
            has_non_ascii = getattr(quality_filter, "_has_non_ascii", None)
            if callable(has_non_ascii) and has_non_ascii(symbol_upper):
                return False
        blacklist = getattr(quality_filter, "_blacklist", set())
        if symbol_upper in blacklist:
            return False
        history_error = quality_filter._check_history_depth(symbol_upper, as_of=as_of)
        return history_error is None

    seed_limit = max(120, max(default_top, 50) * 3)
    mid_time = start_time + ((end_time - start_time) / 2)
    candidate_seed = set(
        volume_service.get_top_symbols_at_date(date=start_time, limit=seed_limit)
    )
    candidate_seed.update(
        volume_service.get_top_symbols_at_date(date=mid_time, limit=seed_limit)
    )
    candidate_seed.update(
        volume_service.get_top_symbols_at_date(date=end_time, limit=seed_limit)
    )
    ranking_seed_universe = sorted(candidate_seed)

    start_ranked_raw = volume_service.get_top_symbols_at_date(
        date=start_time,
        limit=50,
        universe=ranking_seed_universe,
    )
    start_top40_raw = start_ranked_raw[:default_top]
    start_top50_raw = start_ranked_raw[:50]
    start_top40_eligible = [
        sym for sym in start_top40_raw if _is_fast_eligible(sym, as_of=start_time)
    ]
    start_top50_eligible = [
        sym for sym in start_top50_raw if _is_fast_eligible(sym, as_of=start_time)
    ]

    btc_4h = await router_loader.load_candles(
        "BTCUSDT",
        "4h",
        start_time - timedelta(days=60),
        end_time,
    )
    btc_15m = await router_loader.load_candles(
        "BTCUSDT",
        "15m",
        start_time - timedelta(days=14),
        end_time,
    )
    btc_4h = sorted(btc_4h, key=lambda candle: candle.timestamp)
    btc_15m = sorted(btc_15m, key=lambda candle: candle.timestamp)

    utc7 = timezone(timedelta(hours=7))
    start_local_date = start_time.astimezone(utc7).date()
    end_local_date = end_time.astimezone(utc7).date()
    slot_local = datetime.combine(start_local_date, datetime.min.time(), tzinfo=utc7)
    end_local_exclusive = datetime.combine(
        end_local_date + timedelta(days=1),
        datetime.min.time(),
        tzinfo=utc7,
    )

    schedule: Dict[str, Any] = {}
    union_symbols: set[str] = set()
    active_from: Dict[str, datetime] = {}

    while slot_local < end_local_exclusive:
        session_start = slot_local.astimezone(timezone.utc)
        btc_4h_slice = [c for c in btc_4h if c.timestamp <= session_start]
        btc_15m_slice = [c for c in btc_15m if c.timestamp <= session_start]
        daily_ranked_raw = volume_service.get_top_symbols_at_date(
            date=session_start,
            limit=50,
            universe=ranking_seed_universe,
        )
        daily_top40_raw = daily_ranked_raw[:default_top]
        daily_top50_raw = daily_ranked_raw[:50]
        daily_top40_eligible = [
            sym for sym in daily_top40_raw if _is_fast_eligible(sym, as_of=session_start)
        ]
        daily_top50_eligible = [
            sym for sym in daily_top50_raw if _is_fast_eligible(sym, as_of=session_start)
        ]

        trend_bias = trend_filter.calculate_bias(btc_4h_slice[-100:]) if btc_4h_slice else "NEUTRAL"
        closes_4h = [c.close for c in btc_4h_slice]
        ema20 = _router_ema(closes_4h[-100:], 20) if closes_4h else 0.0
        btc_spread_pct = ((closes_4h[-1] - ema20) / ema20) * 100.0 if ema20 and closes_4h else 0.0
        regime_result = regime_detector.detect_regime(btc_15m_slice[-200:]) if len(btc_15m_slice) >= 50 else None
        regime_15m = regime_result.regime.value if regime_result else "ranging"
        regime_confidence = float(regime_result.confidence) if regime_result else 0.0

        features = AdaptiveRouterFeatures(
            eligible_count=len(daily_top40_eligible),
            btc_trend_ema20=trend_bias,
            btc_spread_pct=btc_spread_pct,
            regime_15m=regime_15m,
            regime_confidence=regime_confidence,
        )
        decision = router.decide(features)

        if decision.preset == "short_only_bounce_daily_pt15_maker_top50_toxicblk":
            allowed_symbols = frozenset(sym.upper() for sym in daily_top50_eligible)
            blocked_sides = tuple(get_router_recommended_symbol_side_blocks(decision.preset))
        elif decision.preset == "shield":
            allowed_symbols = frozenset()
            blocked_sides = tuple()
        else:
            allowed_symbols = frozenset(sym.upper() for sym in daily_top40_eligible)
            blocked_sides = tuple(get_router_recommended_symbol_side_blocks(decision.preset))

        state = RollingRouterState(
            session_start_utc=session_start,
            session_date_utc7=slot_local.isoformat(),
            preset=decision.preset,
            reason=decision.reason,
            features=features,
            allowed_symbols=allowed_symbols,
            blocked_symbol_sides=blocked_sides,
        )
        schedule[session_start.isoformat()] = state

        for symbol in allowed_symbols:
            union_symbols.add(symbol)
            active_from[symbol] = min(active_from.get(symbol, session_start), session_start)

        slot_local += timedelta(hours=step_hours)

    return (
        schedule,
        sorted(union_symbols),
        active_from,
        len(start_top40_eligible),
        len(start_top50_eligible),
    )

def print_table(headers: List[str], rows: List[List[str]]):
    """Simple ASCII table printer."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))

    header_row = " | ".join(h.ljust(w) for h, w in zip(headers, widths))
    separator = "-+- ".join("-" * w for w in widths)

    print(header_row)
    print(separator)
    for row in rows:
        print(" | ".join(str(c).ljust(w) for c, w in zip(row, widths)))

async def main():
    parser = argparse.ArgumentParser(description="Hinto Stock Portfolio Backtest")
    parser.add_argument("--symbol", type=str, help="Single trading pair")
    parser.add_argument("--symbols", type=str, help="Comma-separated list of pairs")
    parser.add_argument("--top", type=int, help="Run on top N volume pairs")
    parser.add_argument("--extra-blacklist", type=str,
                       help="[RESEARCH] Comma-separated symbols to blacklist for this run only. Does not persist to DB.")
    parser.add_argument("--extra-blacklist-sides", type=str,
                       help="[RESEARCH] Comma-separated SYMBOL:SIDE pairs to block for this run only. Use *:LONG or *:SHORT for a global side block.")
    parser.add_argument("--fill-top-eligible", action="store_true",
                       help="[EXPERIMENTAL] When using --top dynamic mode, keep scanning ranked symbols until N eligible symbols are found. Default: OFF")
    parser.add_argument("--interval", type=str, default="15m", help="Timeframe")
    parser.add_argument("--days", type=int, help="Days to backtest (if start/end not provided)")
    parser.add_argument("--start", type=str, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", type=str, help="End date YYYY-MM-DD")
    parser.add_argument("--balance", type=float, default=10000.0, help="Initial Shared Balance")
    parser.add_argument("--risk", type=float, default=0.01, help="Risk per trade. Example: 0.01")
    parser.add_argument("--leverage", type=float, default=0.0, help="Fixed Leverage. Example: 5.0. If 0, use risk-based.")
    parser.add_argument("--cb", action="store_true", help="Enable Circuit Breaker. Default: disabled")
    parser.add_argument("--max-losses", type=int, default=5, help="Max consecutive losses before block. Default: 5")
    parser.add_argument("--cooldown", type=float, default=4, help="Cooldown hours after max losses. Default: 4")
    parser.add_argument("--drawdown", type=float, default=0.15, help="Max daily portfolio drawdown. Example: 0.15 for 15 percent")
    parser.add_argument("--max-pos", type=int, default=10, help="Max open positions in Shark Tank mode. Default: 10")
    parser.add_argument("--max-order", type=float, default=50000.0, help="Max notional value per order. Default: 50000")
    parser.add_argument("--mm-rate", type=float, default=0.004, help="Maintenance Margin Rate. Default: 0.004")
    parser.add_argument("--mode", type=str, default="futures", choices=["spot", "futures"],
                       help="Market mode: spot or futures. Default: futures")
    parser.add_argument("--confirm", action="store_true",
                       help="Enable Signal Confirmation - require 2 consecutive signals. Default: OFF")
    parser.add_argument("--no-cb", action="store_true", help="Disable Circuit Breaker. Shorthand for not using --cb")
    parser.add_argument("--zombie-killer", action="store_true",
                       help="[OPTIONAL] Replace pending orders with new signals. Default: OFF (TTL45 preferred)")
    parser.add_argument("--ttl", type=int, default=PRODUCTION_ORDER_TTL_MINUTES,
                       help=f"Order TTL in minutes. 0=GTC. Default: {PRODUCTION_ORDER_TTL_MINUTES}")
    parser.add_argument("--time-filter", action="store_true",
                       help="[LEGACY] Binary time filter. Blocks 4 Death Hours (VN: 00, 05, 11, 22)")
    parser.add_argument("--tiered-time", action="store_true",
                       help="[SOTA] Tiered time filter. Adjusts position size by hour (100/50/30/0%%%%)")
    parser.add_argument("--block-but-full", action="store_true",
                       help="[SOTA] Block Tier 4 (05-13h) but use 100%%%% size for all other hours")
    parser.add_argument("--live-dz", action="store_true",
                       help="[LIVE PARITY] Exact LIVE dead zones: 05-06, 09-14, 19-21:30, 22-23:30 UTC+7")
    parser.add_argument("--blocked-windows", type=str, default=PRODUCTION_BLOCKED_WINDOWS_STR,
                       help=f"Custom blocked windows (UTC+7). Default: '{PRODUCTION_BLOCKED_WINDOWS_STR}'")
    parser.add_argument("--full-tp", action="store_true",
                       help="[OPTIONAL] Close 100%%%% position at TP1 (instead of default 60%%%%)")
    parser.add_argument("--block-short-early", action="store_true",
                       help="[EXPERIMENTAL] Block SHORT signals early (Layer 1+2) like LIVE OLD. For testing hypothesis only.")
    parser.add_argument("--time-exit", action="store_true",
                       help="[INSTITUTIONAL] Enable time-based exit for long-duration losing trades. Default: OFF")
    parser.add_argument("--time-exit-hours", type=float, default=2.0,
                       help="[INSTITUTIONAL] Exit threshold in hours for time-based exit. Default: 2.0h")
    parser.add_argument("--use-btc-filter", action="store_true",
                       help="[INSTITUTIONAL] Filter altcoin signals based on BTC trend (EMA 50/200 crossover). Default: OFF")
    parser.add_argument("--use-fixed-profit-3usd", action="store_true",
                       help="[EXPERIMENTAL] Enable fixed $3 profit exit strategy (backtest only). Default: OFF")
    parser.add_argument("--portfolio-target", type=float, default=0.0,
                       help="[INSTITUTIONAL] Portfolio profit target in USD. Exit all positions when total PnL >= target. 0=disabled. Example: 7.0")
    parser.add_argument("--portfolio-target-pct", type=float, default=PRODUCTION_PORTFOLIO_TARGET_PCT,
                       help=f"[INSTITUTIONAL] Portfolio profit target as %% of capital. Default: {PRODUCTION_PORTFOLIO_TARGET_PCT}")
    parser.add_argument("--signal-reversal-exit", action="store_true",
                       help="[INSTITUTIONAL] Exit positions on high-confidence opposite signals. Default: OFF")
    parser.add_argument("--reversal-confidence", type=float, default=0.90,
                       help="[INSTITUTIONAL] Minimum confidence for signal reversal exit. Default: 0.90 (90%%)")
    parser.add_argument("--visual", action="store_true",
                       help="[SOTA 2026] Generate Replay Data for UI Visualizer. Default: OFF")
    parser.add_argument("--use-optimized-exits", action="store_true",
                       help="[OPTIMIZATION] Use optimized exit parameters: 0.8R breakeven (was 1.5R), 2.5 ATR trailing (was 4.0). Default: OFF")
    parser.add_argument("--breakeven-r", type=float, default=None,
                       help="[TUNING] Custom breakeven trigger in R-multiple. Example: 0.8 for 0.8R. Default: 1.5 (or 0.8 if --use-optimized-exits)")
    parser.add_argument("--trailing-atr", type=float, default=None,
                       help="[TUNING] Custom trailing stop in ATR multiple. Example: 2.5 for ATR*2.5. Default: 4.0 (or 2.5 if --use-optimized-exits)")
    parser.add_argument("--close-profitable-auto", action=argparse.BooleanOptionalAction,
                       default=PRODUCTION_CLOSE_PROFITABLE_AUTO,
                       help=f"[EXPERIMENTAL] Auto-close positions when ROE > threshold. Default: {PRODUCTION_CLOSE_PROFITABLE_AUTO}")
    parser.add_argument("--profitable-threshold-pct", type=float, default=PRODUCTION_PROFITABLE_THRESHOLD_PCT,
                       help=f"[EXPERIMENTAL] ROE threshold for auto-close (%%). Default: {PRODUCTION_PROFITABLE_THRESHOLD_PCT}")
    parser.add_argument("--profitable-check-interval", type=int, default=1,
                       help="[EXPERIMENTAL] Check auto-close every N candles. Default: 1 (every candle)")
    parser.add_argument("--max-sl-validation", action=argparse.BooleanOptionalAction,
                       default=PRODUCTION_USE_MAX_SL_VALIDATION,
                       help=f"[RISK] Enable MAX SL validation - reject signals with SL > max-sl-pct. Default: {PRODUCTION_USE_MAX_SL_VALIDATION}")
    parser.add_argument("--max-sl-pct", type=float, default=PRODUCTION_MAX_SL_PCT,
                       help=f"[RISK] Custom MAX SL percentage. Example: 1.5 for 1.5%%. Default: {PRODUCTION_MAX_SL_PCT}")
    parser.add_argument("--profit-lock", action="store_true",
                       help="[SOTA] Enable Profit Lock - when ROE >= threshold, move SL up to lock profit. Default: OFF")
    parser.add_argument("--profit-lock-threshold", type=float, default=5.0,
                       help="[SOTA] ROE threshold to trigger profit lock (%%). Default: 5.0")
    parser.add_argument("--profit-lock-pct", type=float, default=4.0,
                       help="[SOTA] ROE to lock when threshold hit (%%). Default: 4.0 (1%% buffer from 5%% threshold)")
    parser.add_argument("--no-compound", action="store_true",
                       help="[REALISTIC] Disable compounding - use fixed position size based on initial balance. Default: OFF (compounding enabled)")
    parser.add_argument("--daily-symbol-loss-limit", type=int, default=0,
                       help="[RISK] Block symbol after N total losses in a UTC day (both directions). 0=disabled. Default: 0")
    parser.add_argument("--daily-loss-cooldown-hours", type=float, default=0,
                       help="[RISK] Cooldown hours after daily loss limit hit. 0=block until end of day. Default: 0")
    parser.add_argument("--daily-loss-size-penalty", type=float, default=0.0,
                       help="[RISK] Reduce position size by N%% per daily loss (Freqtrade style). Example: 0.25 = -25%%/loss. 0=disabled. Default: 0")
    parser.add_argument("--symbol-side-loss-limit", type=int, default=0,
                       help="[RISK] Block symbol+side after N losses within rolling window. 0=disabled. Default: 0")
    parser.add_argument("--symbol-side-loss-window", type=float, default=72.0,
                       help="[RISK] Rolling window in hours for symbol+side loss quarantine. Default: 72")
    parser.add_argument("--symbol-side-cooldown", type=float, default=72.0,
                       help="[RISK] Cooldown hours after symbol+side rolling loss limit hit. Default: 72")
    # INSTITUTIONAL (Feb 2026): 3 New Strategies for A/B Testing
    parser.add_argument("--adx-regime-filter", action="store_true",
                       help="[INSTITUTIONAL] Filter signals by ADX regime. ADX<20=block, 20-25=penalty. Default: OFF")
    parser.add_argument("--vol-sizing", action="store_true",
                       help="[INSTITUTIONAL] Volatility-adjusted position sizing. ATR-scaled. Default: OFF")
    parser.add_argument("--dynamic-tp", action="store_true",
                       help="[INSTITUTIONAL] ATR-scaled dynamic TP/SL/AUTO_CLOSE. Default: OFF")
    parser.add_argument("--sl-on-close-only", action=argparse.BooleanOptionalAction,
                       default=PRODUCTION_SL_ON_CANDLE_CLOSE,
                       help=f"[v6.0.0] Only check SL on candle CLOSE (matches LIVE candle-close mode). Default: {PRODUCTION_SL_ON_CANDLE_CLOSE}")
    parser.add_argument("--hard-cap-pct", type=float, default=PRODUCTION_HARD_CAP_PCT,
                       help=f"[v6.2.0] Hard cap loss %% (tick-level). 0=disabled. Default: {PRODUCTION_HARD_CAP_PCT}")
    # EXPERIMENTAL (Feb 2026): R:R Improvement & Risk Management
    parser.add_argument("--partial-close-ac", action="store_true",
                       help="[EXPERIMENTAL] Partial close 50%% at AC threshold, trail remaining 50%%. Default: OFF")
    parser.add_argument("--partial-close-ac-pct", type=float, default=0.5,
                       help="[EXPERIMENTAL] Fraction to close at AC threshold when --partial-close-ac is enabled. Example: 0.8 = close 80%%, trail 20%%.")
    parser.add_argument("--max-same-direction", type=int, default=0,
                       help="[RISK] Max positions in same direction (LONG or SHORT). 0=disabled. Example: 3")
    parser.add_argument("--volume-filter", action="store_true",
                       help="[EXPERIMENTAL] Only enter when signal candle volume > threshold x avg. Default: OFF")
    parser.add_argument("--volume-filter-threshold", type=float, default=1.5,
                       help="[EXPERIMENTAL] Volume filter threshold multiplier. Default: 1.5")
    parser.add_argument("--htf-filter", action="store_true",
                       help="[EXPERIMENTAL] Block counter-trend signals (LONG vs BEARISH 4H, SHORT vs BULLISH 4H). Default: OFF")
    # Mean-reversion indicator filters (Feb 2026)
    parser.add_argument("--adx-max-filter", action=argparse.BooleanOptionalAction,
                       default=PRODUCTION_USE_ADX_MAX_FILTER,
                       help=f"[FILTER] Block when ADX > threshold (too trendy for mean-reversion). Default: {PRODUCTION_USE_ADX_MAX_FILTER}")
    parser.add_argument("--adx-max-threshold", type=float, default=PRODUCTION_ADX_MAX_THRESHOLD,
                       help=f"[FILTER] ADX max threshold. Default: {PRODUCTION_ADX_MAX_THRESHOLD}")
    parser.add_argument("--bb-filter", action="store_true",
                       help="[FILTER] Bollinger Bands: BUY near lower band, SELL near upper band. Default: OFF")
    parser.add_argument("--stochrsi-filter", action="store_true",
                       help="[FILTER] StochRSI: BUY when oversold (<30), SELL when overbought (>70). Default: OFF")
    # Entry parameter tuning
    parser.add_argument("--sniper-lookback", type=int, default=PRODUCTION_SNIPER_LOOKBACK,
                       help=f"[ENTRY] Swing point lookback period (candles). Default: {PRODUCTION_SNIPER_LOOKBACK}")
    parser.add_argument("--sniper-proximity", type=float, default=PRODUCTION_SNIPER_PROXIMITY * 100.0,
                       help=f"[ENTRY] Proximity threshold %% to swing point. Default: {PRODUCTION_SNIPER_PROXIMITY * 100.0}")
    parser.add_argument("--strategy-id", type=str, choices=SUPPORTED_STRATEGY_IDS,
                       default=os.getenv("HINTO_STRATEGY_ID", DEFAULT_STRATEGY_ID),
                       help="[RESEARCH] Signal strategy: default mean-reversion sniper or positive-skew reclaim runner.")
    parser.add_argument("--volume-slippage", action="store_true",
                       help="[SOTA] Volume-adjusted slippage (Almgren-Chriss sqrt-vol model). Default: OFF")
    parser.add_argument("--1m-monitoring", action=argparse.BooleanOptionalAction, default=PRODUCTION_USE_1M_MONITORING, dest="m1_monitoring",
                       help=f"[SOTA] Monitor positions using 1m candles (matches LIVE SL on 1m close). Default: {PRODUCTION_USE_1M_MONITORING}")
    parser.add_argument("--adversarial-path", action="store_true",
                       help="[SOTA] Adversarial intra-bar path: always check SL direction first (De Prado). Default: OFF")
    parser.add_argument("--ac-tick-level", action="store_true",
                       help="[v6.3.5] AC tick-level: check AUTO_CLOSE at every tick (HIGH/LOW), not just candle CLOSE. Default: OFF")
    # SOTA (Feb 2026): Signal quality improvement flags
    parser.add_argument("--fix-vwap", action="store_true",
                       help="[SOTA] Fix inverted VWAP scoring — reward closeness to VWAP. Default: OFF")
    parser.add_argument("--volume-confirm", action="store_true",
                       help="[SOTA] Volume confirmation — require Z-score >= 1.0 (84th pct). Default: OFF")
    parser.add_argument("--bounce-confirm", action="store_true",
                       help="[SOTA] Bounce confirmation — require pin bar / rejection candle. Default: OFF")
    parser.add_argument("--regime-filter", action="store_true",
                       help="[SOTA] EMA regime filter — block counter-trend via EMA 9/21 crossover. Default: OFF")
    parser.add_argument("--atr-sl", action="store_true",
                       help="[SOTA] ATR-based stop loss — 2x ATR(14), capped 0.5-2.0%%. Default: OFF (uses fixed 1%%)")
    parser.add_argument("--funding-filter", action="store_true",
                       help="[SOTA] Funding rate filter — block overcrowded directions (>0.05%%). Default: OFF")
    # Phase 1 Strategy Filters (Feb 2026): Volume Delta + MTF Trend
    parser.add_argument("--delta-divergence", action=argparse.BooleanOptionalAction, default=PRODUCTION_USE_DELTA_DIVERGENCE,
                       help=f"[STRATEGY] Volume Delta Divergence filter — block signals contradicted by volume delta. Default: {PRODUCTION_USE_DELTA_DIVERGENCE}")
    parser.add_argument("--mtf-trend", action=argparse.BooleanOptionalAction, default=PRODUCTION_USE_MTF_TREND,
                       help=f"[STRATEGY] MTF Trend filter — block counter-trend using faster EMA on 4H. Default: {PRODUCTION_USE_MTF_TREND}")
    parser.add_argument("--mtf-ema", type=int, default=20,
                       help="[STRATEGY] MTF trend EMA period on 4H candles (50=~8 days, 20=~3.3 days). Default: 20")
    # BTC Regime Filter (Feb 2026): Block counter-trend based on BTC 4H trend
    parser.add_argument("--btc-regime-filter", action="store_true",
                       help="[REGIME] Block counter-trend signals based on BTC 4H EMA cross + momentum. Default: OFF")
    parser.add_argument("--btc-regime-ema-fast", type=int, default=5,
                       help="[REGIME] Fast EMA period on BTC 4H candles (5 = ~20h). Default: 5")
    parser.add_argument("--btc-regime-ema-slow", type=int, default=12,
                       help="[REGIME] Slow EMA period on BTC 4H candles (12 = ~48h). Default: 12")
    parser.add_argument("--btc-regime-momentum-threshold", type=float, default=0.5,
                       help="[REGIME] BTC 4H momentum threshold %% for STRONG regime. Default: 0.5")
    parser.add_argument("--btc-impulse-filter", action="store_true",
                       help="[RESEARCH] Block counter-trend signals using BTC LTF impulse at signal time. Default: OFF")
    parser.add_argument("--btc-impulse-lookback-bars", type=int, default=4,
                       help="[RESEARCH] BTC LTF lookback bars for impulse filter. Default: 4")
    parser.add_argument("--btc-impulse-threshold-pct", type=float, default=0.5,
                       help="[RESEARCH] BTC LTF impulse threshold %% to block counter-trend side. Default: 0.5")
    # F1: Escalating CB Cooldown
    parser.add_argument("--escalating-cb", action="store_true",
                       help="[RISK] Escalating CB cooldown: longer blocks after more consecutive losses. Default: OFF")
    parser.add_argument("--escalating-cb-schedule", type=str, default="2:0.5,3:2,4:8,5:24",
                       help="[RISK] Escalating schedule as 'losses:hours' pairs. Default: '2:0.5,3:2,4:8,5:24'")
    # F2: Direction Block (cross-symbol directional awareness)
    parser.add_argument("--direction-block", action="store_true",
                       help="[RISK] Block direction when N unique symbols lose same direction in window. Default: OFF")
    parser.add_argument("--direction-block-threshold", type=int, default=4,
                       help="[RISK] Unique symbols needed to trigger direction block. Default: 4")
    parser.add_argument("--direction-block-window", type=float, default=2.0,
                       help="[RISK] Window in hours to count direction losses. Default: 2.0")
    parser.add_argument("--direction-block-cooldown", type=float, default=4.0,
                       help="[RISK] Hours to block direction after trigger. Default: 4.0")
    # LIKE-LIVE (Feb 2026): Fix all BT biases to match LIVE behavior
    parser.add_argument("--like-live", action="store_true",
                       help="[LIKE-LIVE] Enable all BT bias fixes: AC threshold exit + N+1 fill + 1m monitoring + SL on close + hard cap 2%%. Default: OFF")
    parser.add_argument("--ac-threshold-exit", action=argparse.BooleanOptionalAction,
                       default=PRODUCTION_AC_THRESHOLD_EXIT,
                       help=f"[LIKE-LIVE] AC exits at threshold price (not candle close). Fixes +8-12pp WR inflation. Default: {PRODUCTION_AC_THRESHOLD_EXIT}")
    parser.add_argument("--n1-fill", action="store_true",
                       help="[LIKE-LIVE] N+1 fill rule: signals from candle N fill on N+1. Fixes +5-8pp WR inflation. Default: OFF")
    # REALISTIC FILLS (Feb 2026): Fill at target price, not candle extreme
    # v6.5.12: DZ Force-Close (matches LIVE behavior)
    parser.add_argument("--dz-force-close", action="store_true",
                       help="[v6.5.12] Force-close ALL positions when dead zone starts (matches LIVE). Default: OFF")
    parser.add_argument("--no-realistic-fills", action="store_true",
                       help="[FILL] Disable realistic fills (revert to legacy: fill at candle LOW/HIGH). Default: realistic fills ON")
    parser.add_argument("--fill-buffer", type=float, default=0.0,
                       help="[FILL] Pessimistic fill buffer %%: price must overshoot target by this %% for fill. 0=no buffer (LIVE-like). Default: 0.0")
    # F3: Gradual Position Sizing (Balance Ramp)
    parser.add_argument("--balance-ramp", action="store_true",
                       help="[RISK] Gradual position sizing after large balance changes. Only with compounding (no --no-compound). Default: OFF")
    parser.add_argument("--balance-ramp-rate", type=float, default=0.20,
                       help="[RISK] Ramp convergence rate (0-1). 0.20 = 20%% per trade toward actual balance. Default: 0.20")
    parser.add_argument("--balance-ramp-threshold", type=float, default=0.30,
                       help="[RISK] Balance change threshold to trigger ramp. 0.30 = 30%% change. Default: 0.30")
    # v6.6.0: Maker fee simulation
    parser.add_argument("--maker-orders", action="store_true",
                       help="[v6.6.0] Use maker fee (0.02%%) for entries + TP exits (simulates LIMIT orders). SL always taker. Default: OFF")
    parser.add_argument("--no-limit-chase-parity", action="store_true",
                       help="[LIKE-LIVE] Disable conservative LIMIT trigger -> close/fallback entry model. Default: ON")
    parser.add_argument("--adaptive-regime-router", action="store_true",
                       help="[RESEARCH] Session-level preset router: baseline | baseline_cb | bounce_daily | shield.")
    parser.add_argument("--rolling-adaptive-router", action="store_true",
                       help="[RESEARCH] Approximate daily rolling router using fixed start-window breadth/universe and daily BTC regime updates.")
    parser.add_argument("--rolling-adaptive-router-step-hours", type=int, default=24,
                       help="[RESEARCH] Refresh cadence for rolling adaptive router. Default: 24")
    parser.add_argument("--rolling-router-bear-overlay-step-hours", type=int, default=0,
                       help="[RESEARCH] Guarded-bear rescue overlay cadence; only active when baseline router shields. Default: 0 (disabled)")
    parser.add_argument("--gb-runner-override", type=str, choices=["pt20", "no_ac_trail3"],
                       help="[RESEARCH] Override guarded bear contract inside router.")
    parser.add_argument("--router-neutral-breadth-threshold", type=int, default=8,
                       help="[RESEARCH] Adaptive router neutral breadth threshold. Default: 8")
    parser.add_argument("--router-neutral-spread-floor-pct", type=float, default=0.0,
                       help="[RESEARCH] Adaptive router neutral positive spread floor. Default: 0.0")
    parser.add_argument("--router-bearish-spread-pct", type=float, default=-3.0,
                       help="[RESEARCH] Adaptive router decisive bear spread threshold. Default: -3.0")
    parser.add_argument("--router-bearish-breadth-threshold", type=int, default=15,
                       help="[RESEARCH] Adaptive router decisive bear breadth threshold. Default: 15")
    parser.add_argument("--router-moderate-bear-spread-pct", type=float, default=-1.5,
                       help="[RESEARCH] Adaptive router moderate bear spread threshold. Default: -1.5")
    parser.add_argument("--router-moderate-bear-breadth-threshold", type=int, default=16,
                       help="[RESEARCH] Adaptive router moderate bear breadth threshold. Default: 16")
    parser.add_argument("--router-strong-spread-breadth-threshold", type=int, default=13,
                       help="[RESEARCH] Adaptive router strong-spread breadth threshold. Default: 13")
    parser.add_argument("--router-strong-spread-pct", type=float, default=-4.0,
                       help="[RESEARCH] Adaptive router strong-spread threshold. Default: -4.0")

    args = parser.parse_args()
    if args.adaptive_regime_router and args.rolling_adaptive_router:
        logger.error("Choose only one of --adaptive-regime-router or --rolling-adaptive-router.")
        return
    if args.rolling_adaptive_router and args.rolling_adaptive_router_step_hours <= 0:
        logger.error("--rolling-adaptive-router-step-hours must be > 0.")
        return
    if args.rolling_router_bear_overlay_step_hours < 0:
        logger.error("--rolling-router-bear-overlay-step-hours must be >= 0.")
        return

    # LIKE-LIVE: Auto-enable all bias fixes
    if args.like_live:
        args.ac_threshold_exit = True
        args.n1_fill = True
        args.m1_monitoring = True
        args.sl_on_close_only = True
        if args.hard_cap_pct == 2.0:  # Only override if still at default
            pass  # Already 2.0 (default)
        # hard_cap_pct default is already 2.0, so no change needed

    # SOTA: Validate auto-close configuration
    if args.close_profitable_auto:
        if args.profitable_threshold_pct <= 0:
            logger.error(f"profitable_threshold_pct must be > 0, got {args.profitable_threshold_pct}")
            return

    # SOTA: Parse market mode
    market_mode = MarketMode.FUTURES if args.mode == "futures" else MarketMode.SPOT
    market_config = get_market_config(market_mode)
    print(f"🌐 Market Mode: {market_mode.value.upper()} ({market_config.rest_base_url})")
    container = DIContainer()
    quality_filter = container.get_symbol_quality_filter(market_mode=market_mode)
    if args.extra_blacklist:
        extra_blacklist = [s.strip().upper() for s in args.extra_blacklist.split(",") if s.strip()]
        if extra_blacklist:
            quality_filter.extend_blacklist(extra_blacklist, persist=False)
            print(f"ðŸ§ª Extra Blacklist (session): {extra_blacklist}")

    blocked_symbol_sides: List[Tuple[str, str]] = []
    if args.extra_blacklist_sides:
        try:
            blocked_symbol_sides = _parse_symbol_side_blacklist(args.extra_blacklist_sides)
        except ValueError as exc:
            logger.error(str(exc))
            return
        if blocked_symbol_sides:
            rendered = [f"{symbol}:{side}" for symbol, side in blocked_symbol_sides]
            print(f"🧪 Extra Symbol-Side Blacklist (session): {rendered}")

    # Time range is needed early for dynamic universe selection and adaptive routing.
    utc7 = timezone(timedelta(hours=7))
    if args.start:
        try:
            start_time = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=utc7).astimezone(timezone.utc)
            if args.end:
                end_time = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=utc7).astimezone(timezone.utc)
            else:
                end_time = datetime.now(timezone.utc)
        except ValueError as e:
            logger.error(f"Invalid date format. Use YYYY-MM-DD: {e}")
            return
    else:
        days = args.days or 7
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(days=days)

    # 1. Determine Symbols
    symbols = []
    if args.symbol:
        symbols = [args.symbol.upper()]
    elif args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
    elif args.top:
        # SOTA: Check if USE_FIXED_SYMBOLS is enabled in .env
        use_fixed = os.getenv("USE_FIXED_SYMBOLS", "false").lower() == "true"

        if use_fixed:
            # Load from BACKTEST_SYMBOLS in .env (avoids look-ahead bias)
            print(f"🔒 Loading FIXED symbol list from .env (USE_FIXED_SYMBOLS=true)...")
            backtest_symbols_str = os.getenv("BACKTEST_SYMBOLS", "")

            if backtest_symbols_str:
                symbols = [s.strip().upper() for s in backtest_symbols_str.split(",")]
                symbols = symbols[:args.top]  # Limit to requested top N
                print(f"📋 Fixed symbols ({len(symbols)}): {symbols[:5]}...")
            else:
                print("⚠️ BACKTEST_SYMBOLS is empty in .env, falling back to dynamic mode")
                use_fixed = False

        if not use_fixed:
            # SOTA FIX: Use historical volume at START DATE (not current)
            # This eliminates look-ahead bias in symbol selection
            print(f"🔍 Calculating top {args.top} volume pairs at START DATE (dynamic mode)...")

            # SOTA: Fetch historical volume at start_date
            from src.infrastructure.data.historical_volume_service import HistoricalVolumeService
            volume_service = HistoricalVolumeService(market_mode=market_mode)
            if args.fill_top_eligible:
                candidate_limit = max(args.top * 5, 100)
                symbols, rejected_candidates = volume_service.get_top_eligible_symbols_at_date(
                    date=start_time,
                    limit=args.top,
                    eligibility_fn=lambda sym: quality_filter.is_eligible(sym, as_of=start_time),
                    candidate_limit=candidate_limit,
                )
            else:
                rejected_candidates = []
                symbols = volume_service.get_top_symbols_at_date(
                    date=start_time,
                    limit=args.top,
                )

            if not symbols:
                # Fallback to current top if historical fetch fails
                print("⚠️ Historical volume fetch failed, using current top pairs...")
                client = BinanceRestClient(market_mode=market_mode)
                symbols = client.get_top_volume_pairs(limit=args.top, quote_asset="USDT")
            else:
                if args.fill_top_eligible:
                    rejected_count = len(rejected_candidates)
                    print(
                        f"📊 Top eligible {len(symbols)}/{args.top} at {start_time.date()}: {symbols[:5]}..."
                    )
                    if rejected_count > 0:
                        print(
                            f"🧹 Preselection filter: scanned {min(candidate_limit, max(len(symbols) + rejected_count, 0))} "
                            f"ranked symbols | rejected {rejected_count}"
                        )
                else:
                    print(f"📊 Top {args.top} at {start_time.date()}: {symbols[:5]}...")
    else:
        symbols = ["BTCUSDT"]


    # Deduplicate and SORT for deterministic BT results
    # set() has non-deterministic iteration order (PYTHONHASHSEED varies per run)
    # Without sorted(), symbol processing order varies → different signal batch order
    # → different tiebreaking when confidence scores are equal → different trades
    symbols = sorted(list(set(symbols)))

    if args.adaptive_regime_router or args.rolling_adaptive_router:
        _apply_router_research_contract_defaults(args)

    rolling_router_schedule: Optional[Dict[str, Any]] = None
    rolling_router_exit_profiles: Optional[Dict[str, Dict[str, Any]]] = None
    rolling_router_overlay_schedule: Optional[Dict[str, Any]] = None
    rolling_router_overlay_exit_profiles: Optional[Dict[str, Dict[str, Any]]] = None
    rolling_router_symbol_active_from: Optional[Dict[str, datetime]] = None
    engine_quality_filter = quality_filter

    if args.adaptive_regime_router:
        try:
            (
                _AdaptiveRegimeRouter,
                AdaptiveRouterFeatures,
                _BEARISH_TOXIC_SHORT_BLACKLIST,
                _RollingRouterState,
                _get_router_research_exit_profile,
                get_router_recommended_symbol_side_blocks,
            ) = _load_adaptive_router_components()
        except RuntimeError as exc:
            logger.error(str(exc))
            return
        from src.infrastructure.indicators.regime_detector import RegimeDetector

        async def _load_router_features():
            router_loader = HistoricalDataLoader(market_mode=market_mode)
            eligible_symbols = []
            for sym in symbols:
                eligible, _ = quality_filter.is_eligible(sym, as_of=start_time)
                if eligible:
                    eligible_symbols.append(sym)

            btc_4h = await router_loader.load_candles(
                "BTCUSDT",
                "4h",
                start_time - timedelta(days=60),
                start_time,
            )
            btc_15m = await router_loader.load_candles(
                "BTCUSDT",
                "15m",
                start_time - timedelta(days=14),
                start_time,
            )
            return eligible_symbols, btc_4h, btc_15m

        def _ema(values, period):
            if not values:
                return 0.0
            k = 2 / (period + 1)
            ema_value = values[0]
            for value in values[1:]:
                ema_value = (value * k) + (ema_value * (1 - k))
            return ema_value

        eligible_symbols, btc_4h, btc_15m = await _load_router_features()
        router_trend_filter = TrendFilter(ema_period=20)
        # Research router uses a stricter ADX trend threshold than the default
        # app-wide detector to avoid over-classifying choppy sessions as trending.
        router_detector = RegimeDetector(adx_trending_threshold=25.0)
        trend_bias = router_trend_filter.calculate_bias(btc_4h[-100:]) if btc_4h else "NEUTRAL"
        closes_4h = [c.close for c in btc_4h]
        ema20 = _ema(closes_4h[-100:], 20) if closes_4h else 0.0
        btc_spread_pct = ((closes_4h[-1] - ema20) / ema20) * 100.0 if ema20 and closes_4h else 0.0
        regime_result = router_detector.detect_regime(btc_15m[-200:]) if len(btc_15m) >= 50 else None
        regime_15m = regime_result.regime.value if regime_result else "ranging"
        regime_conf = regime_result.confidence if regime_result else 0.0

        router = _build_adaptive_router(args)
        router_features = AdaptiveRouterFeatures(
            eligible_count=len(eligible_symbols),
            btc_trend_ema20=trend_bias,
            btc_spread_pct=btc_spread_pct,
            regime_15m=regime_15m,
            regime_confidence=regime_conf,
        )
        router_decision = router.decide(router_features)
        print(
            f"Adaptive Router: {router_decision.preset} | "
            f"eligible={router_features.eligible_count}, trend={router_features.btc_trend_ema20}, "
            f"spread={router_features.btc_spread_pct:.2f}%, regime15m={router_features.regime_15m}"
        )
        print(f"  Reason: {router_decision.reason}")

        if router_decision.preset == "baseline_cb":
            args.cb = True
            args.max_losses = min(args.max_losses, 2)
            args.cooldown = 12
            args.drawdown = min(args.drawdown, 0.15)
            args.symbol_side_loss_limit = max(args.symbol_side_loss_limit, 3)
            args.symbol_side_loss_window = max(args.symbol_side_loss_window, 72)
            args.symbol_side_cooldown = max(args.symbol_side_cooldown, 72)
        elif router_decision.preset == "bounce_daily":
            args.bounce_confirm = True
            args.daily_symbol_loss_limit = max(args.daily_symbol_loss_limit, 2)
        elif router_decision.preset == "bounce_daily_pt15_maker":
            args.bounce_confirm = True
            args.daily_symbol_loss_limit = max(args.daily_symbol_loss_limit, 2)
            if not getattr(args, "gb_runner_override", None):
                args.profitable_threshold_pct = min(args.profitable_threshold_pct, 15.0)
            args.maker_orders = True
            if args.max_same_direction <= 0 or args.max_same_direction > 3:
                args.max_same_direction = 3
        elif router_decision.preset == "short_only_bounce_daily_pt15_maker":
            args.bounce_confirm = True
            args.daily_symbol_loss_limit = max(args.daily_symbol_loss_limit, 2)
            if not getattr(args, "gb_runner_override", None):
                args.profitable_threshold_pct = min(args.profitable_threshold_pct, 15.0)
            args.maker_orders = True
            if args.max_same_direction <= 0 or args.max_same_direction > 3:
                args.max_same_direction = 3
            blocked_symbol_sides.extend(
                get_router_recommended_symbol_side_blocks(router_decision.preset)
            )
        elif router_decision.preset == "short_only_bounce_daily_pt15_maker_top50_toxicblk":
            args.bounce_confirm = True
            args.daily_symbol_loss_limit = max(args.daily_symbol_loss_limit, 2)
            if not getattr(args, "gb_runner_override", None):
                args.profitable_threshold_pct = min(args.profitable_threshold_pct, 15.0)
            args.maker_orders = True
            if args.max_same_direction <= 0 or args.max_same_direction > 3:
                args.max_same_direction = 3
            args.fill_top_eligible = False
            blocked_symbol_sides.extend(
                get_router_recommended_symbol_side_blocks(router_decision.preset)
            )

            if args.top and not args.symbol and not args.symbols:
                if args.top != 50:
                    print(
                        "Adaptive Router Universe Override: switching to dynamic top50 for "
                        "the deep-bear short-side branch."
                    )
                args.top = 50
                symbols = _resolve_symbols(
                    args,
                    start_time,
                    market_mode,
                    quality_filter,
                    top_override=50,
                )
            else:
                print(
                    "Adaptive Router Note: deep-bear branch keeps the caller-provided symbol set; "
                    "top50 override only applies in dynamic --top mode."
                )
        elif router_decision.preset == "baseline":
            args.symbol_side_loss_limit = max(args.symbol_side_loss_limit, 3)
            args.symbol_side_loss_window = max(args.symbol_side_loss_window, 72)
            args.symbol_side_cooldown = max(args.symbol_side_cooldown, 72)
        elif router_decision.preset == "shield":
            print("=" * 60)
            print("ADAPTIVE SHIELD REPORT")
            print("=" * 60)
            print(f"Reason: {router_decision.reason}")
            print(f"Window Start (UTC): {start_time.isoformat()}")
            print(f"Initial Balance: ${args.balance:.2f}")
            print(f"Final Balance:   ${args.balance:.2f}")
            print("Net Return:      0.00% ($0.00)")
            print("Total Trades:    0")
            print("Action:          Shield mode - no new entries")
            return
    if args.rolling_adaptive_router:
        try:
            get_router_research_exit_profile = _load_adaptive_router_components()[4]
        except RuntimeError as exc:
            logger.error(str(exc))
            return
        if not end_time:
            logger.error("--rolling-adaptive-router requires a bounded --end date.")
            return
        (
            rolling_router_schedule,
            rolling_router_symbols,
            rolling_router_symbol_active_from,
            start_top40_eligible_count,
            start_top50_eligible_count,
        ) = await _build_rolling_router_schedule(
            start_time=start_time,
            end_time=end_time,
            market_mode=market_mode,
            quality_filter=quality_filter,
            default_top=args.top or 40,
            router=_build_adaptive_router(args),
            step_hours=args.rolling_adaptive_router_step_hours,
        )
        rolling_router_exit_profiles = {}
        for preset in {state.preset for state in rolling_router_schedule.values()}:
            exit_profile = get_router_research_exit_profile(
                preset,
                guarded_bear_override=args.gb_runner_override,
            )
            if exit_profile:
                rolling_router_exit_profiles[preset] = exit_profile
        if args.rolling_router_bear_overlay_step_hours > 0:
            (
                overlay_schedule_raw,
                overlay_symbols,
                overlay_active_from,
                _overlay_start_top40,
                _overlay_start_top50,
            ) = await _build_rolling_router_schedule(
                start_time=start_time,
                end_time=end_time,
                market_mode=market_mode,
                quality_filter=quality_filter,
                default_top=args.top or 40,
                router=_build_adaptive_router(args),
                step_hours=args.rolling_router_bear_overlay_step_hours,
            )
            rolling_router_overlay_schedule = {
                key: state
                for key, state in overlay_schedule_raw.items()
                if state.preset == "short_only_bounce_daily_pt15_maker_top50_toxicblk"
            }
            if rolling_router_overlay_schedule:
                rolling_router_overlay_exit_profiles = {}
                for preset in {state.preset for state in rolling_router_overlay_schedule.values()}:
                    exit_profile = get_router_research_exit_profile(
                        preset,
                        guarded_bear_override=args.gb_runner_override,
                    )
                    if exit_profile:
                        rolling_router_overlay_exit_profiles[preset] = exit_profile
                overlay_symbol_set = set(overlay_symbols)
                symbols = sorted(set(rolling_router_symbols) | overlay_symbol_set)
                if rolling_router_symbol_active_from is None:
                    rolling_router_symbol_active_from = {}
                for symbol, activation in overlay_active_from.items():
                    rolling_router_symbol_active_from[symbol] = min(
                        rolling_router_symbol_active_from.get(symbol, activation),
                        activation,
                    )
            else:
                symbols = rolling_router_symbols
        else:
            symbols = rolling_router_symbols
        engine_quality_filter = None
        args.bounce_confirm = True
        args.daily_symbol_loss_limit = max(args.daily_symbol_loss_limit, 2)
        args.maker_orders = True
        if not getattr(args, "gb_runner_override", None):
            args.profitable_threshold_pct = min(args.profitable_threshold_pct, 15.0)
        if not symbols:
            print("=" * 60)
            print("ROLLING ADAPTIVE SHIELD REPORT")
            print("=" * 60)
            print("Reason: no trade-eligible days found under the rolling router approximation.")
            print(f"Window Start (UTC): {start_time.isoformat()}")
            print(f"Window End (UTC):   {end_time.isoformat()}")
            print(f"Initial Balance: ${args.balance:.2f}")
            print(f"Final Balance:   ${args.balance:.2f}")
            print("Net Return:      0.00% ($0.00)")
            print("Total Trades:    0")
            print("Action:          Shield mode - no new entries")
            return
        if args.max_same_direction <= 0 or args.max_same_direction > 3:
            args.max_same_direction = 3
        print(
            "Rolling Adaptive Router (research-only): "
            f"{len(rolling_router_schedule)} states @ {args.rolling_adaptive_router_step_hours}h | "
            f"start eligible top40={start_top40_eligible_count} | "
            f"start eligible top50={start_top50_eligible_count} | "
            f"union symbols={len(symbols)}"
        )
        if rolling_router_overlay_schedule:
            print(
                "  Bear rescue overlay: "
                f"{len(rolling_router_overlay_schedule)} guarded-bear states @ "
                f"{args.rolling_router_bear_overlay_step_hours}h"
            )
        if rolling_router_exit_profiles:
            rendered_profiles = ", ".join(
                f"{preset}=>{profile['profile_name']}"
                for preset, profile in sorted(rolling_router_exit_profiles.items())
            )
            print(f"  Exit profiles: {rendered_profiles}")
        for state in list(rolling_router_schedule.values())[:5]:
            print(
                f"  {state.session_date_utc7}: {state.preset} | "
                f"trend={state.features.btc_trend_ema20} | "
                f"spread={state.features.btc_spread_pct:.2f}% | "
                f"regime15m={state.features.regime_15m}"
            )
    print(f"🚀 Starting PORTFOLIO Backtest: {len(symbols)} pairs | {args.days} days")
    print(f"💰 Capital: ${args.balance} | Risk: {args.risk*100}% | Leverage: {args.leverage}x")
    print(f"🛡️ Global Circuit Breaker: {'ENABLED' if args.cb else 'DISABLED'}")
    if not args.cb and (
        args.daily_symbol_loss_limit > 0
        or args.daily_loss_size_penalty > 0
        or args.symbol_side_loss_limit > 0
        or args.escalating_cb
        or args.direction_block
    ):
        print("   Local loss guards remain active without enabling portfolio-level drawdown halts.")
    if args.daily_symbol_loss_limit > 0:
        cooldown_desc = f"{args.daily_loss_cooldown_hours}h cooldown" if args.daily_loss_cooldown_hours > 0 else "block rest of day"
        print(f"🚫 Daily Symbol Loss Limit: {args.daily_symbol_loss_limit} losses/symbol/day → {cooldown_desc}")
    if args.symbol_side_loss_limit > 0:
        print(
            f"Symbol-Side Quarantine: {args.symbol_side_loss_limit} losses/{args.symbol_side_loss_window}h "
            f"-> {args.symbol_side_cooldown}h block"
        )
    if args.daily_loss_size_penalty > 0:
        print(f"📉 Daily Loss Size Penalty: -{args.daily_loss_size_penalty*100:.0f}%/loss (0 loss=100%, 1={100-args.daily_loss_size_penalty*100:.0f}%, 2={max(0,100-args.daily_loss_size_penalty*200):.0f}%, 3={max(0,100-args.daily_loss_size_penalty*300):.0f}%, 4={max(0,100-args.daily_loss_size_penalty*400):.0f}%)")
    print(f"📋 Signal Confirmation: {'ENABLED (2x)' if args.confirm else 'DISABLED'}")
    print(f"💀 Zombie Killer: {'ENABLED' if args.zombie_killer else 'DISABLED'}")
    ttl_str = "GTC (unlimited)" if args.ttl == 0 else f"{args.ttl} min ({args.ttl/60:.1f}h)"
    print(f"⏰ Order TTL: {ttl_str}")

    # SOTA (Jan 2026): Time-Based Exit Status
    if args.time_exit:
        print(f"⏰ Time-Based Exit: ENABLED (>{args.time_exit_hours}h AND losing)")
        print(f"   Based on: Renaissance Technologies, Two Sigma, Citadel research")
    else:
        print(f"⏰ Time-Based Exit: DISABLED")

    # SOTA (Jan 2026): BTC Filter Status
    if args.use_btc_filter:
        print(f"📊 BTC Filter: ENABLED (Altcoins follow BTC trend)")
        print(f"   Logic: EMA 50/200 crossover (Golden/Death Cross)")
        print(f"   Based on: Renaissance Technologies, Two Sigma, Citadel research")
    else:
        print(f"📊 BTC Filter: DISABLED")

    # BTC Regime Filter Status (Feb 2026)
    if args.btc_regime_filter:
        print(f"🌐 BTC Regime Filter: ENABLED")
        print(f"   EMA({args.btc_regime_ema_fast}/{args.btc_regime_ema_slow}) on BTC 4H | Momentum > {args.btc_regime_momentum_threshold}%")
        print(f"   BULL → block SHORT | BEAR → block LONG | NEUTRAL → trade both")

    if args.btc_impulse_filter:
        print(f"BTC Impulse Filter: ENABLED")
        print(f"   BTC {args.interval} lookback: {args.btc_impulse_lookback_bars} bars | Threshold: {args.btc_impulse_threshold_pct}%")
        print(f"   Positive BTC impulse -> block SHORT | Negative BTC impulse -> block LONG")

    # OPTIMIZATION (Jan 2026): Optimized Exit Parameters Status
    # Priority: --breakeven-r/--trailing-atr > --use-optimized-exits > defaults
    actual_breakeven = args.breakeven_r if args.breakeven_r is not None else (0.8 if args.use_optimized_exits else 1.5)
    actual_trailing = args.trailing_atr if args.trailing_atr is not None else (2.5 if args.use_optimized_exits else 4.0)

    if args.breakeven_r is not None or args.trailing_atr is not None:
        print(f"🎚️ Custom Exit Params: Breakeven={actual_breakeven}R, Trailing=ATR×{actual_trailing}")
    elif args.use_optimized_exits:
        print(f"🚀 Optimized Exits: ENABLED")
        print(f"   Breakeven Trigger: 0.8R (was 1.5R) - Lock in profits earlier")
        print(f"   Trailing Stop: ATR×2.5 (was ×4.0) - Tighter trailing for better R:R")
    else:
        print(f"🚀 Optimized Exits: DISABLED (using defaults: {actual_breakeven}R breakeven, ATR×{actual_trailing})")

    # EXPERIMENTAL (Jan 2026): Auto-Close Profitable Status
    if args.close_profitable_auto:
        ac_mode = "TICK-LEVEL (every tick)" if args.ac_tick_level else "CANDLE CLOSE"
        print(f"💰 Auto-Close Profitable: ENABLED (ROE > {args.profitable_threshold_pct}%) [{ac_mode}]")
        print(f"   Strategy: Take profits early, let losses recover")
    else:
        print(f"💰 Auto-Close Profitable: DISABLED")

    # RISK (Jan 2026): MAX SL Validation Status
    if args.max_sl_validation:
        if args.max_sl_pct is not None:
            max_sl_pct = args.max_sl_pct
            print(f"🛡️ MAX SL Validation: ENABLED (custom max {max_sl_pct:.2f}%)")
        else:
            max_sl_pct = 10.0 / args.leverage if args.leverage > 0 else 0.5
            print(f"🛡️ MAX SL Validation: ENABLED (max {max_sl_pct:.2f}% = 10%/{args.leverage}x)")
    else:
        print(f"🛡️ MAX SL Validation: DISABLED")

    # SOTA (Jan 2026): Profit Lock Status
    if args.profit_lock:
        print(f"🔒 Profit Lock: ENABLED (threshold {args.profit_lock_threshold}% → lock {args.profit_lock_pct}%)")
        print(f"   Strategy: Move SL to lock profit, keep position open for more gains")
    else:
        print(f"🔒 Profit Lock: DISABLED")

    # REALISTIC (Jan 2026): No-Compound Mode
    if args.no_compound:
        print(f"📊 Compounding: DISABLED (Fixed position size = ${args.balance}/{args.max_pos} = ${args.balance/args.max_pos:.2f}/slot)")
        print(f"   Realistic mode: Position size stays constant regardless of balance growth")
    else:
        print(f"📊 Compounding: ENABLED (Position size grows with balance)")

    # INSTITUTIONAL (Feb 2026): 3 New Strategies Status
    if args.adx_regime_filter:
        print(f"📊 ADX Regime Filter: ENABLED (ADX<20=block, 20-25=penalty -15%)")
    else:
        print(f"📊 ADX Regime Filter: DISABLED")

    if args.vol_sizing:
        print(f"📊 Vol-Adjusted Sizing: ENABLED (ATR-scaled position size)")
    else:
        print(f"📊 Vol-Adjusted Sizing: DISABLED")

    if args.dynamic_tp:
        print(f"📊 Dynamic TP/SL: ENABLED (ATR-scaled TP/SL/AUTO_CLOSE)")
    else:
        print(f"📊 Dynamic TP/SL: DISABLED")

    # EXPERIMENTAL (Feb 2026): R:R Improvement Flags
    if args.partial_close_ac:
        print(f"📊 Partial Close AC: ENABLED (50% close at AC, trail rest)")
    if args.max_same_direction > 0:
        print(f"📊 Max Same Direction: {args.max_same_direction} (limit correlated positions)")
    if args.volume_filter:
        print(f"📊 Volume Filter: ENABLED (threshold: {args.volume_filter_threshold}x avg)")
    if args.htf_filter:
        print(f"📊 HTF Filter: ENABLED (block counter-trend signals)")
    if args.volume_slippage:
        print(f"📊 Volume-Adjusted Slippage: ENABLED (Almgren-Chriss sqrt-vol model)")
    if args.m1_monitoring:
        print(f"📊 1m Position Monitoring: ENABLED (SL/TP/AC on 1m candle close, matches LIVE)")
    if args.adversarial_path:
        print(f"📊 Adversarial Path: ENABLED (De Prado — SL direction first, no look-ahead)")
    if not args.no_realistic_fills:
        print(f"📊 Realistic Fills: ON (fill at target price) | Fill Buffer: {args.fill_buffer}%")
    else:
        print(f"📊 Realistic Fills: OFF (legacy: fill at candle extreme) | Fill Buffer: {args.fill_buffer}%")
    if args.maker_orders:
        print(f"📊 Fee Model: MAKER/LIMIT (entry+TP: 0.02%, SL: 0.05%)")

    # LIKE-LIVE (Feb 2026): All BT bias fixes
    if args.like_live:
        print(f"🎯 LIKE-LIVE MODE: ALL bias fixes enabled")
        print(f"   Fix A: AC threshold exit (exit at threshold price, not candle close)")
        print(f"   Fix B: N+1 fill rule (signals fill on next candle)")
        print(f"   Fix C: Portfolio target on 1m (not just 15m)")
        print(f"   + 1m monitoring + SL on close + hard cap {args.hard_cap_pct}%")
    else:
        if args.ac_threshold_exit:
            print(f"📊 AC Threshold Exit: ENABLED (exit at threshold price)")
        if args.n1_fill:
            print(f"📊 N+1 Fill Rule: ENABLED (signals fill on next candle)")

    # SOTA (Feb 2026): Signal quality improvement flags
    sota_flags = []
    if args.fix_vwap:
        sota_flags.append("Fix VWAP (closeness)")
    if args.volume_confirm:
        sota_flags.append("Volume Z≥1.0")
    if args.bounce_confirm:
        sota_flags.append("Bounce (pin bar)")
    if args.regime_filter:
        sota_flags.append("Regime (EMA 9/21)")
    if args.atr_sl:
        sota_flags.append("ATR SL (2x, 0.5-2%)")
    if args.funding_filter:
        sota_flags.append("Funding (>0.05%)")
    if sota_flags:
        print(f"🔬 SOTA Signal Flags: {' | '.join(sota_flags)}")
    else:
        print(f"🔬 SOTA Signal Flags: NONE (baseline)")

    # Phase 1 Strategy Filters (Feb 2026)
    if args.delta_divergence:
        print(f"📊 Delta Divergence: ENABLED (block signals contradicted by volume delta)")
    if args.mtf_trend:
        print(f"📊 MTF Trend: ENABLED (EMA {args.mtf_ema} on 4H, block counter-trend)")
    if args.dz_force_close:
        print(f"📊 DZ Force-Close: ENABLED (close ALL positions when DZ starts)")

    # SOTA: Time-based filter (avoids death hours)
    time_filter = None
    if args.blocked_windows:
        from src.application.backtest.time_filter import TimeFilter
        windows = []
        for w in args.blocked_windows.split(","):
            start, end = w.strip().split("-")
            windows.append({"start": start.strip(), "end": end.strip()})
        time_filter = TimeFilter(
            timezone_offset_hours=7,
            blocked_windows=windows,
        )
        print(f"⏰ Custom Dead Zones (UTC+7): {args.blocked_windows}")
    elif args.live_dz:
        from src.application.backtest.time_filter import TimeFilter
        # EXACT LIVE dead zones (Feb 2026) — minute-level precision
        live_blocked_windows = [
            {"start": "05:00", "end": "06:00"},   # CME maintenance
            {"start": "09:00", "end": "14:00"},   # Asian sideway
            {"start": "19:00", "end": "21:30"},   # EU/US overlap whipsaw
            {"start": "22:00", "end": "23:30"},   # Pre-funding positioning
        ]
        time_filter = TimeFilter(
            timezone_offset_hours=7,
            blocked_windows=live_blocked_windows,
        )
        print(f"⏰ LIVE DEAD ZONES (exact match):")
        print(f"   DZ0: 05:00-06:00 | DZ1: 09:00-14:00 | DZ2: 19:00-21:30 | DZ3: 22:00-23:30 UTC+7")
        print(f"   Total blocked: 10h/day, Active: 14h/day")
    elif args.tiered_time:
        from src.application.backtest.time_filter import TimeFilter
        time_filter = TimeFilter(timezone_offset_hours=7, use_tiered_sizing=True)
        print(f"⏰ Time Filter: TIERED MODE (SOTA)")
        print(f"   Tier 1 (100%): 20-23h VN | Tier 2 (50%): 15-19h, 00-04h VN")
        print(f"   Tier 3 (30%): 14h VN | Tier 4 (BLOCK): 05-13h VN")
    elif args.block_but_full:
        from src.application.backtest.time_filter import TimeFilter
        time_filter = TimeFilter(timezone_offset_hours=7, use_tiered_sizing=True, block_but_full_size=True)
        print(f"⏰ Time Filter: BLOCK BUT FULL SIZE (SOTA)")
        print(f"   Tier 1-3 (100%): 14-04h VN")
        print(f"   Tier 4 (BLOCK): 05-13h VN")
    elif args.time_filter:
        from src.application.backtest.time_filter import TimeFilter
        time_filter = TimeFilter(timezone_offset_hours=7, use_tiered_sizing=False)
        print(f"🕐 Time Filter: LEGACY MODE (Binary Block)")
        print(f"   Blocked (VN time): 00, 05, 11, 22")

    # 2. Initialize System (Shared Simulator - Shark Tank)
    signal_gen = container.get_signal_generator(
        use_btc_filter=args.use_btc_filter,  # SOTA (Jan 2026): BTC Filter
        use_adx_regime_filter=args.adx_regime_filter,  # INSTITUTIONAL (Feb 2026): ADX Regime Filter
        use_htf_filter=args.htf_filter,  # EXPERIMENTAL: HTF Trend Alignment
        use_adx_max_filter=args.adx_max_filter,  # Mean-reversion: Block ADX > threshold
        adx_max_threshold=args.adx_max_threshold,
        use_bb_filter=args.bb_filter,  # Mean-reversion: BB proximity
        use_stochrsi_filter=args.stochrsi_filter,  # Mean-reversion: StochRSI O/S-O/B
        sniper_lookback=args.sniper_lookback,
        sniper_proximity=args.sniper_proximity / 100.0,  # Convert % to decimal
        # SOTA (Feb 2026): Signal quality improvement flags
        fix_vwap_scoring=args.fix_vwap,
        use_volume_confirm=args.volume_confirm,
        use_bounce_confirm=args.bounce_confirm,
        use_ema_regime_filter=args.regime_filter,
        use_atr_sl=args.atr_sl,
        use_funding_filter=args.funding_filter,
        # Phase 1 Strategy Filters (Feb 2026)
        use_delta_divergence=args.delta_divergence,
        use_mtf_trend=args.mtf_trend,
        mtf_ema_period=args.mtf_ema,
        strategy_id=args.strategy_id,
    )

    # SOTA: Initialize FundingHistoryLoader for historical funding rates
    from src.infrastructure.data.funding_history_loader import FundingHistoryLoader
    funding_loader = FundingHistoryLoader()

    # SOTA: Load market intelligence (funding rates, symbol rules)
    funding_rates = {}
    symbol_rules = {}  # Per-symbol exchange rules
    try:
        import json
        intel_path = os.path.join(os.path.dirname(__file__), "data", "market_intelligence.json")
        if os.path.exists(intel_path):
            with open(intel_path, 'r') as f:
                intel_data = json.load(f)
                for sym, data in intel_data.items():
                    # Funding rate as fallback
                    funding_rates[sym] = data.get('market', {}).get('funding_rate', 0.01) / 100.0

                    # SOTA: Extract per-symbol exchange rules
                    rules = data.get('rules', {})
                    risk = data.get('risk', {})
                    symbol_rules[sym] = {
                        'max_leverage': risk.get('max_leverage', 20),  # Some tokens only allow 2x, 5x
                        'min_qty': rules.get('min_qty', 0.001),
                        'step_size': rules.get('step_size', 0.001),
                        'min_notional': rules.get('min_notional', 5.0),
                        'qty_precision': rules.get('qty_precision', 3),
                        'price_precision': rules.get('price_precision', 2)
                    }
            logger.info(f"📊 Loaded rules for {len(symbol_rules)} symbols (leverage caps, step_size, min_notional)")
    except Exception as e:
        logger.warning(f"⚠️ Could not load market intelligence: {e}")

    # SOTA: Execution Simulator Configuration with historical funding
    simulator = ExecutionSimulator(
        initial_balance=args.balance,
        risk_per_trade=args.risk,
        fixed_leverage=args.leverage, # Pass CLI leverage override
        mode="SHARK_TANK",
        max_leverage=max(5.0, args.leverage), # Ensure max cap respects override
        max_positions=args.max_pos, # Shark Tank limit from CLI
        max_order_value=args.max_order,
        maintenance_margin_rate=args.mm_rate,
        # SOTA: Historical funding rate simulation
        enable_funding_rate=True,
        funding_rates=funding_rates,  # Static fallback
        funding_loader=funding_loader,  # Historical loader (uses cache)
        # SOTA: Per-symbol exchange rules
        symbol_rules=symbol_rules,  # Leverage caps, step_size, min_notional
        # SOTA: Zombie Killer (optional, matches Paper/Live behavior)
        use_zombie_killer=args.zombie_killer,
        # SOTA (Jan 2026): Configurable TTL for testing
        order_ttl_minutes=args.ttl,  # 0=GTC, or specify minutes
        # SOTA: Full Take Profit at TP1 (Optional)
        full_tp_at_tp1=args.full_tp,
        # EXPERIMENTAL (Jan 2026): Block SHORT signals early (Layer 1+2) for hypothesis testing
        block_short_early=args.block_short_early,
        # SOTA (Jan 2026): Time-Based Exit (Institutional Approach)
        # Based on research: Renaissance Technologies, Two Sigma, Citadel
        enable_time_based_exit=args.time_exit,
        time_based_exit_duration_hours=args.time_exit_hours,
        # SOTA (Jan 2026): Fixed Profit Per Trade (Experimental)
        # Exit when profit reaches $3.00 per trade
        use_fixed_profit_3usd=args.use_fixed_profit_3usd,
        # SOTA (Jan 2026): Portfolio Profit Target (Institutional)
        # Exit all positions when total PnL reaches target
        # Renaissance (0.5-1% daily), Two Sigma, Citadel
        portfolio_target=args.portfolio_target,
        portfolio_target_pct=args.portfolio_target_pct,
        # SOTA (Jan 2026): Signal Reversal Exit (Institutional)
        # Exit on high-confidence opposite signals
        # Jane Street (85-95%), Citadel, Jump Trading
        enable_reversal_exit=args.signal_reversal_exit,
        reversal_confidence=args.reversal_confidence,
        # SOTA (Jan 2026): Backtest Replay Visualizer
        capture_events=args.visual,
        # OPTIMIZATION (Jan 2026): Optimized Exit Parameters for better R:R
        # Priority: --breakeven-r/--trailing-atr > --use-optimized-exits > defaults
        breakeven_trigger_r=args.breakeven_r if args.breakeven_r is not None else (0.8 if args.use_optimized_exits else 1.5),
        trailing_stop_atr=args.trailing_atr if args.trailing_atr is not None else (2.5 if args.use_optimized_exits else 4.0),
        # EXPERIMENTAL (Jan 2026): Auto-Close Profitable Positions
        # Strategy: "Take profits early, let losses recover"
        close_profitable_auto=args.close_profitable_auto,
        profitable_threshold_pct=args.profitable_threshold_pct,
        profitable_check_interval=args.profitable_check_interval,
        # RISK (Jan 2026): MAX SL Validation
        # Reject signals with SL > max_sl_pct (custom or 10%/leverage)
        use_max_sl_validation=args.max_sl_validation,
        max_sl_pct=args.max_sl_pct,
        # SOTA (Jan 2026): Profit Lock
        # Move SL to lock profit when ROE >= threshold
        use_profit_lock=args.profit_lock,
        profit_lock_threshold_pct=args.profit_lock_threshold,
        profit_lock_pct=args.profit_lock_pct,
        # REALISTIC (Jan 2026): No-Compound Mode
        # Fixed position size based on initial balance, not current balance
        no_compound=args.no_compound,
        # INSTITUTIONAL (Feb 2026): Volatility-Adjusted Position Sizing
        use_vol_sizing=args.vol_sizing,
        # INSTITUTIONAL (Feb 2026): Dynamic TP/SL based on ATR
        use_dynamic_tp=args.dynamic_tp,
        # v6.0.0: Only check SL on candle CLOSE (matches LIVE candle-close mode)
        sl_on_close_only=args.sl_on_close_only,
        hard_cap_pct=args.hard_cap_pct / 100.0,
        # EXPERIMENTAL (Feb 2026): R:R Improvement & Risk Management
        partial_close_ac=args.partial_close_ac,
        partial_close_ac_pct=args.partial_close_ac_pct,
        max_same_direction=args.max_same_direction,
        use_volume_filter=args.volume_filter,
        volume_filter_threshold=args.volume_filter_threshold,
        # SOTA (Feb 2026): Volume-Adjusted Slippage (Almgren-Chriss)
        use_volume_slippage=args.volume_slippage,
        # SOTA (Feb 2026): 1m candle monitoring (matches LIVE SL on 1m close)
        use_1m_monitoring=args.m1_monitoring,
        # SOTA (Feb 2026): Adversarial path (De Prado)
        use_adversarial_path=args.adversarial_path,
        # v6.3.5: AC tick-level (check at HIGH/LOW, not just CLOSE)
        ac_tick_level=args.ac_tick_level,
        # F3: Gradual Position Sizing (Balance Ramp)
        use_balance_ramp=args.balance_ramp,
        balance_ramp_rate=args.balance_ramp_rate,
        balance_ramp_threshold=args.balance_ramp_threshold,
        # REALISTIC FILLS (Feb 2026): Fill at target price, not candle extreme
        use_realistic_fills=not args.no_realistic_fills,
        pessimistic_fill_buffer_pct=args.fill_buffer / 100.0,
        # LIKE-LIVE (Feb 2026): AC threshold exit + N+1 fill rule
        ac_threshold_exit=args.ac_threshold_exit,
        n1_fill=args.n1_fill,
        # v6.5.12: DZ Force-Close (matches LIVE)
        dz_force_close=args.dz_force_close,
        # v6.6.0: Maker fee simulation (LIMIT orders)
        use_maker_fee_entries=args.maker_orders,
        use_limit_chase_parity=not args.no_limit_chase_parity,
    )

    # 3. Enhanced Analyzers (SOTA Filters)
    # Use faster EMA for MTF trend filter (default 50 on 4H = ~8 days vs 200 = ~33 days)
    trend_ema_period = args.mtf_ema if args.mtf_trend else 200
    trend_filter = TrendFilter(ema_period=trend_ema_period)
    loader = HistoricalDataLoader()

    circuit_breaker = None
    if args.cb or args.daily_symbol_loss_limit > 0 or args.daily_loss_size_penalty > 0 or args.symbol_side_loss_limit > 0 or args.escalating_cb or args.direction_block:
        from src.application.risk_management.circuit_breaker import CircuitBreaker
        circuit_breaker = CircuitBreaker(
            max_consecutive_losses=args.max_losses if args.cb else 999,
            cooldown_hours=args.cooldown,
            max_daily_drawdown_pct=_resolve_global_drawdown_pct(args.cb, args.drawdown),
            daily_symbol_loss_limit=args.daily_symbol_loss_limit,
            daily_loss_cooldown_hours=args.daily_loss_cooldown_hours,
            daily_loss_size_penalty=args.daily_loss_size_penalty,
            symbol_side_loss_limit=args.symbol_side_loss_limit,
            symbol_side_loss_window_hours=args.symbol_side_loss_window,
            symbol_side_cooldown_hours=args.symbol_side_cooldown,
            # F1: Escalating CB Cooldown
            use_escalating_cooldown=args.escalating_cb,
            escalating_schedule_str=args.escalating_cb_schedule,
            # F2: Direction Block
            use_direction_block=args.direction_block,
            direction_block_threshold=args.direction_block_threshold,
            direction_block_window_hours=args.direction_block_window,
            direction_block_cooldown_hours=args.direction_block_cooldown,
        )

    engine = BacktestEngine(
        signal_generator=signal_gen,
        loader=loader,
        simulator=simulator,
        trend_filter=trend_filter,
        circuit_breaker=circuit_breaker,
        symbol_quality_filter=engine_quality_filter,
        blocked_symbol_sides=set(blocked_symbol_sides),
        rolling_router_schedule=rolling_router_schedule,
        rolling_router_exit_profiles=rolling_router_exit_profiles,
        rolling_router_overlay_schedule=rolling_router_overlay_schedule,
        rolling_router_overlay_exit_profiles=rolling_router_overlay_exit_profiles,
        rolling_router_symbol_active_from=rolling_router_symbol_active_from,
        use_signal_confirmation=args.confirm,  # SOTA: Optional 2x confirmation
        time_filter=time_filter,  # SOTA: Time-based death hour filter
        # BTC Regime Filter (Feb 2026)
        use_btc_regime_filter=args.btc_regime_filter,
        btc_regime_ema_fast=args.btc_regime_ema_fast,
        btc_regime_ema_slow=args.btc_regime_ema_slow,
        btc_regime_momentum_threshold=args.btc_regime_momentum_threshold,
        use_btc_impulse_filter=args.btc_impulse_filter,
        btc_impulse_lookback_bars=args.btc_impulse_lookback_bars,
        btc_impulse_threshold_pct=args.btc_impulse_threshold_pct,
    )

    # 4. Run Portfolio
    try:
        result = await engine.run_portfolio(
            symbols=symbols,
            interval=args.interval,
            start_time=start_time,
            end_time=end_time
        )
    except Exception as e:
        logger.error(f"Backtest failed: {e}", exc_info=True)
        return
    if "error" in result:
        logger.error(f"Backtest failed: {result['error']}")
        return

    # 5. Report Generation
    stats = result.get('stats', {})
    trades = result.get('trades', [])
    equity_curve = result.get('equity', [])

    print("\n" + "="*60)
    print("📊 PORTFOLIO PERFORMANCE REPORT")
    print("="*60)

    # Portfolio Stats
    print(f"💰 Initial Balance: ${stats.get('initial_balance', 0):.2f}")
    print(f"🏁 Final Balance:   ${stats.get('final_balance', 0):.2f}")
    print(f"📈 Net Return:      {stats.get('net_return_pct', 0):.2f}% (${stats.get('net_return_usd', 0):.2f})")
    print(f"🔢 Total Trades:    {stats.get('total_trades', 0)}")
    print(f"🎯 Win Rate:        {stats.get('win_rate', 0):.2f}%")
    if equity_curve:
        print(f"ðŸ“‰ Max Equity DD:   {calculate_max_drawdown_pct(equity_curve):.2f}%")
    quality_rejections = int(stats.get('quality_filter_rejections', 0) or 0)
    if quality_rejections > 0:
        print(
            f"🧹 Quality Filter:  {len(result.get('symbols', []))} eligible "
            f"| {quality_rejections} rejected"
        )
    if stats.get('termination_reason'):
        terminated_at = stats.get('terminated_early_at')
        print(f"🛑 Termination:     {stats['termination_reason']} @ {terminated_at}")
    if stats.get('capital_exhausted'):
        print(
            f"💸 Capital Floor:   exhausted | slot=${stats.get('no_compound_slot_size', 0):.2f} "
            f"| available=${stats.get('available_balance', 0):.2f}"
        )
    if stats.get("research_symbol_side_blocks"):
        print(f"🧪 Symbol-Side Blacklist Blocks: {stats['research_symbol_side_blocks']}")
    coverage_warnings = stats.get("coverage_warnings") or []
    for warning in coverage_warnings:
        print(f"⚠ Coverage:        {warning}")

    # SOTA: Funding rate metrics
    funding_net = stats.get('funding_net', 0)
    funding_paid = stats.get('funding_paid', 0)
    funding_received = stats.get('funding_received', 0)
    if funding_paid > 0 or funding_received > 0:
        funding_symbol = "+" if funding_net >= 0 else ""
        print(f"💸 Funding Net:     {funding_symbol}${funding_net:.2f} (Paid: ${funding_paid:.2f}, Received: ${funding_received:.2f})")

    # Per-Symbol Breakdown
    print("\n--- Symbol Breakdown ---")
    headers = ["Symbol", "Trades", "PnL ($", "Win Rate"]
    symbol_stats = {}
    for t in trades:
        sym = t['symbol']
        if sym not in symbol_stats:
            symbol_stats[sym] = {'count': 0, 'pnl': 0.0, 'wins': 0}

        symbol_stats[sym]['count'] += 1

        # v6.6.0 FIX (B3): Use actual taker fee rate (0.05%), was hardcoded 0.02%
        entry_fee = t['notional_value'] * 0.0005
        net_net_pnl = t['pnl_usd'] - entry_fee

        symbol_stats[sym]['pnl'] += net_net_pnl
        if net_net_pnl > 0:
            symbol_stats[sym]['wins'] += 1

    rows = []
    # Sort by PnL desc
    sorted_syms = sorted(symbol_stats.items(), key=lambda x: x[1]['pnl'], reverse=True)

    for sym, s in sorted_syms:
        wr = (s['wins'] / s['count'] * 100) if s['count'] > 0 else 0
        rows.append([sym, str(s['count']), f"${s['pnl']:.2f}", f"{wr:.1f}%"])

    print_table(headers, rows)

    # MFE (Maximum Favorable Excursion) Distribution
    if simulator.trades:
        mfe_values = [t.peak_roe_pct for t in simulator.trades]
        print("\n--- MFE Distribution (Peak ROE % before close) ---")
        brackets = [
            ("Never profitable (0%)", 0, 0.01),
            ("0-3% ROE", 0.01, 3),
            ("3-5% ROE", 3, 5),
            ("5-7% ROE", 5, 7),
            ("7-10% ROE", 7, 10),
            ("10-15% ROE", 10, 15),
            ("15-20% ROE", 15, 20),
            ("20%+ ROE", 20, 999),
        ]
        for label, lo, hi in brackets:
            count = sum(1 for m in mfe_values if lo <= m < hi)
            pct = count / len(mfe_values) * 100
            # Show how many of these became wins vs losses
            trades_in_bracket = [t for t in simulator.trades if lo <= t.peak_roe_pct < hi]
            wins = sum(1 for t in trades_in_bracket if t.pnl_usd > 0)
            losses = len(trades_in_bracket) - wins
            bar = "#" * int(pct / 2)
            print(f"  {label:>25s}: {count:3d} ({pct:5.1f}%) {wins}W/{losses}L  {bar}")
        avg_mfe = sum(mfe_values) / len(mfe_values)
        median_mfe = sorted(mfe_values)[len(mfe_values) // 2]
        # Key question: what % of trades that reach 7% also reach 10%?
        reached_7 = [t for t in simulator.trades if t.peak_roe_pct >= 7]
        reached_10 = [t for t in simulator.trades if t.peak_roe_pct >= 10]
        reached_15 = [t for t in simulator.trades if t.peak_roe_pct >= 15]
        reached_20 = [t for t in simulator.trades if t.peak_roe_pct >= 20]
        print(f"\n  Avg MFE: {avg_mfe:.1f}% | Median MFE: {median_mfe:.1f}%")
        print(f"  Reached  7% ROE: {len(reached_7):3d}/{len(simulator.trades)} ({len(reached_7)/len(simulator.trades)*100:.1f}%)")
        print(f"  Reached 10% ROE: {len(reached_10):3d}/{len(simulator.trades)} ({len(reached_10)/len(simulator.trades)*100:.1f}%)")
        print(f"  Reached 15% ROE: {len(reached_15):3d}/{len(simulator.trades)} ({len(reached_15)/len(simulator.trades)*100:.1f}%)")
        print(f"  Reached 20% ROE: {len(reached_20):3d}/{len(simulator.trades)} ({len(reached_20)/len(simulator.trades)*100:.1f}%)")
        if reached_7:
            pct_7_to_10 = len(reached_10) / len(reached_7) * 100
            print(f"\n  KEY: Of trades reaching 7%: {pct_7_to_10:.1f}% also reach 10%")
            if reached_10:
                pct_10_to_15 = len(reached_15) / len(reached_10) * 100
                print(f"  KEY: Of trades reaching 10%: {pct_10_to_15:.1f}% also reach 15%")
                if reached_15:
                    pct_15_to_20 = len(reached_20) / len(reached_15) * 100
                    print(f"  KEY: Of trades reaching 15%: {pct_15_to_20:.1f}% also reach 20%")

    # Experimental Flags Stats
    exp_stats = []
    if args.partial_close_ac:
        exp_stats.append(
            f"  Partial AC Exits: {simulator._partial_ac_exits} "
            f"(close {args.partial_close_ac_pct * 100:.0f}%)"
        )
    if args.max_same_direction > 0:
        exp_stats.append(f"  Direction Filter Blocks: {simulator._direction_filter_blocks}")
    if args.volume_filter:
        exp_stats.append(f"  Volume Filter Blocks: {simulator._volume_filter_blocks}")
    if args.htf_filter:
        exp_stats.append(f"  HTF Filter Blocks: {signal_gen.get_blocked_by_htf_filter_count()}")
    if exp_stats:
        print("\n--- Experimental Flags ---")
        for s in exp_stats:
            print(s)

    # SOTA (Feb 2026): Signal quality improvement stats
    sota_stats = []
    if args.volume_confirm:
        sota_stats.append(f"  Volume Confirm Blocks: {signal_gen.get_blocked_by_volume_confirm_count()}")
    if args.bounce_confirm:
        sota_stats.append(f"  Bounce Confirm Blocks: {signal_gen.get_blocked_by_bounce_confirm_count()}")
    if args.regime_filter:
        sota_stats.append(f"  Regime Filter Blocks: {signal_gen.get_blocked_by_ema_regime_filter_count()}")
    if args.funding_filter:
        sota_stats.append(f"  Funding Filter Blocks: {signal_gen.get_blocked_by_funding_filter_count()}")
    if args.delta_divergence:
        sota_stats.append(f"  Delta Divergence Blocks: {signal_gen.get_blocked_by_delta_divergence_count()}")
    if args.mtf_trend:
        sota_stats.append(f"  MTF Trend Blocks: {signal_gen.get_blocked_by_mtf_trend_count()}")
    if simulator._dead_zone_fill_blocks > 0:
        sota_stats.append(f"  Dead Zone Fill Blocks: {simulator._dead_zone_fill_blocks}")
    if simulator._dz_force_close_count > 0:
        sota_stats.append(f"  DZ Force-Close Exits: {simulator._dz_force_close_count}")
    limit_triggers = int(stats.get('limit_entry_triggers', 0) or 0)
    if limit_triggers > 0:
        sota_stats.append(
            "  Limit Entry Parity: "
            f"triggers={limit_triggers}, "
            f"maker={int(stats.get('limit_entry_maker_fills', 0) or 0)}, "
            f"fallback={int(stats.get('limit_entry_market_fallbacks', 0) or 0)}"
        )
    if sota_stats:
        print("\n--- SOTA Signal Quality ---")
        for s in sota_stats:
            print(s)

    # F1/F2/F3: CB Enhancement Stats
    risk_stats = []
    if args.escalating_cb and circuit_breaker:
        risk_stats.append(f"  Escalating CB Triggers: {circuit_breaker._escalating_cb_triggers}")
        risk_stats.append(f"  Schedule: {args.escalating_cb_schedule}")
    if args.direction_block and circuit_breaker:
        risk_stats.append(f"  Direction Block Triggers: {circuit_breaker._blocked_by_direction}")
        risk_stats.append(f"  Threshold: {args.direction_block_threshold} syms / {args.direction_block_window}h → {args.direction_block_cooldown}h block")
    if args.symbol_side_loss_limit > 0 and circuit_breaker:
        risk_stats.append(f"  Symbol-Side Quarantines: {circuit_breaker._blocked_by_symbol_side_window}")
        risk_stats.append(
            f"  Threshold: {args.symbol_side_loss_limit} losses / {args.symbol_side_loss_window}h -> {args.symbol_side_cooldown}h block"
        )
    if args.balance_ramp:
        risk_stats.append(f"  Balance Ramp Adjustments: {simulator._ramp_adjustments}")
        risk_stats.append(f"  Rate: {args.balance_ramp_rate}, Threshold: {args.balance_ramp_threshold}")
    if args.btc_regime_filter:
        risk_stats.append(f"  BTC Regime Blocks: {engine._btc_regime_blocks}")
        risk_stats.append(f"  EMA({args.btc_regime_ema_fast}/{args.btc_regime_ema_slow}) on 4H | Momentum > {args.btc_regime_momentum_threshold}%")
    if args.btc_impulse_filter:
        risk_stats.append(f"  BTC Impulse Blocks: {engine._btc_impulse_blocks}")
        risk_stats.append(
            f"  BTC {args.interval} impulse: {args.btc_impulse_lookback_bars} bars | Threshold: {args.btc_impulse_threshold_pct}%"
        )
    if risk_stats:
        print("\n--- Risk Enhancement Stats ---")
        for s in risk_stats:
            print(s)

    print("="*60 + "\n")

    # 6. Export to CSV. Include microseconds so parallel research runs do not
    # overwrite each other, and reuse the same stamp for all artifacts.
    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    csv_filename = f"portfolio_backtest_{run_stamp}.csv"
    equity_filename = f"equity_curve_{run_stamp}.csv" if equity_curve else None
    replay_filename = f"replay_data_{run_stamp}.json" if args.visual and result.get("replay_data") else None
    metadata_filename = f"experiment_{run_stamp}.json"

    # SOTA: Load timezone offset from .env (default: 7 for Vietnam)
    try:
        tz_offset_hours = int(os.getenv("BACKTEST_TIMEZONE_OFFSET", "7"))
    except ValueError:
        tz_offset_hours = 7
        logger.warning("Invalid BACKTEST_TIMEZONE_OFFSET, using default: 7 (Vietnam)")

    # Create timezone label for CSV header
    if tz_offset_hours == 0:
        tz_label = "UTC"
    elif tz_offset_hours > 0:
        tz_label = f"UTC+{tz_offset_hours}"
    else:
        tz_label = f"UTC{tz_offset_hours}"

    try:
        # SOTA FIX: UTF-8 encoding for Chinese/special characters in symbol names
        with open(csv_filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            # SOTA: Added Margin column for balance tracking
            # SOTA: Enhanced AI-Friendly Headers with timezone info
            writer.writerow([
                "Trade ID", "Symbol", "Side", f"Entry Time ({tz_label})", f"Exit Time ({tz_label})", "Hold Duration (h)",
                "Entry Price", "Exit Price", "Size", "Notional ($)", "Margin ($)",
                "Leverage", "Entry Fee ($)", "Exit Fee ($)", "Entry Liquidity", "Exit Liquidity",
                "PnL ($)", "PnL (%)", "ROI (%)", "Funding ($)",
                "Reason", "Account Balance"
            ])

            for t in trades:
                # SOTA: Use 10 decimal places for small-price tokens (PEPE, SHIB, etc.)
                entry_price = t['entry_price']
                exit_price = t['exit_price']

                if entry_price < 0.001:
                    price_format = "{:.10f}"
                elif entry_price < 1:
                    price_format = "{:.8f}"
                else:
                    price_format = "{:.4f}"

                # Metrics Calculation
                margin = t.get('margin_at_entry', 0)

                entry_fee = t.get('entry_fee_paid', 0.0)
                exit_fee = t.get('exit_fee_paid', 0.0)
                pnl = t['pnl_usd']

                roi = (pnl / margin * 100) if margin > 0 else 0

                duration = t['exit_time'] - t['entry_time']
                duration_hours = duration.total_seconds() / 3600

                # SOTA: Convert UTC timestamps to local timezone
                entry_time_local = t['entry_time'] + timedelta(hours=tz_offset_hours)
                exit_time_local = t['exit_time'] + timedelta(hours=tz_offset_hours)

                writer.writerow([
                    t['trade_id'],
                    t['symbol'],
                    t['side'],
                    entry_time_local.strftime('%Y-%m-%d %H:%M:%S'),
                    exit_time_local.strftime('%Y-%m-%d %H:%M:%S'),
                    f"{duration_hours:.2f}",
                    price_format.format(entry_price),
                    price_format.format(exit_price),
                    f"{t['position_size']:.6f}",
                    f"{t['notional_value']:.2f}",
                    f"{margin:.2f}",
                    f"{t['leverage_at_entry']:.1f}x",
                    f"{entry_fee:.4f}",
                    f"{exit_fee:.4f}",
                    t.get('entry_liquidity', ''),
                    t.get('exit_liquidity', ''),
                    f"{pnl:.4f}",
                    f"{t['pnl_pct']:.2f}%",  # Price Move %
                    f"{roi:.2f}%",           # Real ROI on Margin
                    f"{t.get('funding_cost', 0):.4f}",
                    t['exit_reason'],
                    f"${t.get('balance_at_exit', 0):.2f}" # Balance snapshot if available (engine needs to provide this)
                ])
        print(f"💾 Detailed trade log saved to: {csv_filename}")
        if equity_curve:
            write_equity_curve_csv(equity_filename, equity_curve, tz_offset_hours=tz_offset_hours)
            print(f"💾 Equity curve saved to: {equity_filename}")

        # SOTA (Jan 2026): Export Replay Data JSON if enabled
        if args.visual and 'replay_data' in result and result['replay_data']:
            json_filename = f"replay_data_{run_stamp}.json"
            try:
                import json
                with open(json_filename, 'w', encoding='utf-8') as f:
                    json.dump(result['replay_data'], f, indent=4, default=str)
                print(f"📽️  UI Replay Data saved to: {json_filename}")
            except Exception as e:
                logger.error(f"Failed to save Replay JSON: {e}")

        experiment_config = {
            "argv": sys.argv[1:],
            "args": vars(args),
            "symbols": symbols,
            "blocked_symbol_sides": blocked_symbol_sides,
            "start_time_utc": start_time,
            "end_time_utc": end_time,
            "market_mode": market_mode.value,
            "git_commit": _git_commit(),
        }
        metadata = {
            "run_stamp": run_stamp,
            "config_hash": _stable_config_hash(experiment_config),
            "created_at_utc": datetime.now(timezone.utc),
            "experiment_config": experiment_config,
            "artifacts": {
                "trades_csv": csv_filename,
                "equity_csv": equity_filename,
                "replay_json": replay_filename,
            },
            "summary": {
                "initial_balance": stats.get("initial_balance"),
                "final_balance": stats.get("final_balance"),
                "net_return_pct": stats.get("net_return_pct"),
                "net_return_usd": stats.get("net_return_usd"),
                "total_trades": stats.get("total_trades"),
                "win_rate": stats.get("win_rate"),
                "max_drawdown_pct": calculate_max_drawdown_pct(equity_curve) if equity_curve else None,
                "quality_filter_rejections": stats.get("quality_filter_rejections"),
                "termination_reason": stats.get("termination_reason"),
            },
        }
        with open(metadata_filename, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, default=_json_default, ensure_ascii=False)
        print(f"Experiment metadata saved to: {metadata_filename}")

    except Exception as e:
        logger.error(f"Failed to save CSV: {e}")

if __name__ == "__main__":
    asyncio.run(main())
