"""Shared production trading contract for Hinto runtime and parity checks."""

from __future__ import annotations

from typing import Dict, List

PRODUCTION_LEVERAGE = 20
PRODUCTION_MAX_POSITIONS = 4
PRODUCTION_ORDER_TTL_MINUTES = 50
PRODUCTION_RISK_PER_TRADE = 0.01

PRODUCTION_SNIPER_LOOKBACK = 15
PRODUCTION_SNIPER_PROXIMITY = 0.025
PRODUCTION_USE_DELTA_DIVERGENCE = True
PRODUCTION_USE_MTF_TREND = True
PRODUCTION_MTF_EMA_PERIOD = 20
PRODUCTION_USE_ADX_MAX_FILTER = True
PRODUCTION_ADX_MAX_THRESHOLD = 40.0

PRODUCTION_CLOSE_PROFITABLE_AUTO = False
PRODUCTION_PROFITABLE_THRESHOLD_PCT = 40.0
PRODUCTION_AUTO_CLOSE_INTERVAL = "1m"
PRODUCTION_PORTFOLIO_TARGET_PCT = 10.0
PRODUCTION_USE_MAX_SL_VALIDATION = True
PRODUCTION_MAX_SL_PCT = 1.2
PRODUCTION_SL_ON_CANDLE_CLOSE = True
PRODUCTION_HARD_CAP_PCT = 2.0
PRODUCTION_USE_1M_MONITORING = True
PRODUCTION_AC_THRESHOLD_EXIT = True
PRODUCTION_MIN_SYMBOL_HISTORY_DAYS = 30

PRODUCTION_ORDER_TYPE = "LIMIT"
PRODUCTION_LIMIT_CHASE_TIMEOUT_SECONDS = 5

PRODUCTION_CB_MAX_CONSECUTIVE_LOSSES = 2
PRODUCTION_CB_COOLDOWN_HOURS = 0.5
PRODUCTION_CB_DAILY_SYMBOL_LOSS_LIMIT = 3
PRODUCTION_CB_MAX_DAILY_DRAWDOWN_PCT = 0.30

PRODUCTION_BLOCKED_WINDOWS_STR = (
    "03:00-05:00,06:00-08:00,14:00-15:00,18:00-21:00,23:00-00:00"
)

_PRODUCTION_BLOCKED_WINDOWS: tuple[Dict[str, str], ...] = (
    {
        "start": "03:00",
        "end": "05:00",
        "reason": "Backtest risk window: repeated continuation stops in late US session",
    },
    {
        "start": "06:00",
        "end": "08:00",
        "reason": "Funding rate 00:00 UTC + low liquidity",
    },
    {
        "start": "14:00",
        "end": "15:00",
        "reason": "Pre-London open, Asian-EU handoff",
    },
    {
        "start": "18:00",
        "end": "21:00",
        "reason": "EU lunch + pre-US manipulation + false breakouts",
    },
    {
        "start": "23:00",
        "end": "00:00",
        "reason": "US market reversal, crypto follows stocks",
    },
)

PRODUCTION_SYMBOL_BLACKLIST: tuple[str, ...] = (
    "1000BONKUSDT",
    "ALPACAUSDT",
    "ALPHAUSDT",
    "ARCUSDT",
    "ASTERUSDT",
    "BNXUSDT",
    "BULLAUSDT",
    "CYSUSDT",
    "DENTUSDT",
    "DUSKUSDT",
    "HIPPOUSDT",
    "KAVAUSDT",
    "LEVERUSDT",
    "PAXGUSDT",
    "PORT3USDT",
    "RIVERUSDT",
    "SIRENUSDT",
    "STABLEUSDT",
    "STEEMUSDT",
    "SYNUSDT",
    "UXLINKUSDT",
    "VIDTUSDT",
    "XAGUSDT",
    "XAUUSDT",
    "XMRUSDT",
    "ZECUSDT",
    "ZILUSDT",
)


def get_production_blocked_windows() -> List[Dict[str, str]]:
    """Return a copy of production blocked windows for mutation-safe wiring."""
    return [dict(window) for window in _PRODUCTION_BLOCKED_WINDOWS]


def get_production_symbol_blacklist() -> List[str]:
    """Return the production blacklist used by deploy/runtime safety layers."""
    return list(PRODUCTION_SYMBOL_BLACKLIST)


def parse_blocked_windows(blocked_windows: str) -> List[Dict[str, str]]:
    """Parse a blocked-window string into TimeFilter/CircuitBreaker format."""
    parsed: List[Dict[str, str]] = []
    for raw_window in blocked_windows.split(","):
        window = raw_window.strip()
        if not window:
            continue
        if "-" not in window:
            raise ValueError(f"Invalid blocked window '{window}'")
        start, end = [part.strip() for part in window.split("-", 1)]
        if not start or not end:
            raise ValueError(f"Invalid blocked window '{window}'")
        parsed.append({"start": start, "end": end, "reason": window})
    return parsed
