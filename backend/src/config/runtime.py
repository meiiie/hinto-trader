"""Runtime environment helpers shared by API and infrastructure wiring."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


VALID_RUNTIME_ENVS = {"paper", "testnet", "live"}
DEFAULT_RUNTIME_ENV = "paper"


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def normalize_runtime_env(env: Optional[str]) -> str:
    """Normalize external ENV input into a supported runtime environment."""
    resolved = (env or DEFAULT_RUNTIME_ENV).lower().strip()
    if resolved not in VALID_RUNTIME_ENVS:
        return DEFAULT_RUNTIME_ENV
    return resolved


def get_runtime_env() -> str:
    """Return the active runtime environment from ENV."""
    return normalize_runtime_env(os.getenv("ENV", DEFAULT_RUNTIME_ENV))


def is_paper_real_enabled(env: Optional[str] = None) -> bool:
    """Paper-real uses live market data with local-only simulated execution."""
    resolved_env = normalize_runtime_env(env) if env is not None else get_runtime_env()
    return resolved_env == "paper" and _env_flag("HINTO_PAPER_REAL", True)


def get_execution_mode(env: Optional[str] = None) -> str:
    """Return the execution profile shown to operators and UI."""
    resolved_env = normalize_runtime_env(env) if env is not None else get_runtime_env()
    if is_paper_real_enabled(resolved_env):
        return "paper_real"
    return resolved_env


def is_real_ordering_enabled(env: Optional[str] = None) -> bool:
    """Only ENV=live may send production orders."""
    resolved_env = normalize_runtime_env(env) if env is not None else get_runtime_env()
    return resolved_env == "live"


def is_exchange_ordering_enabled(env: Optional[str] = None) -> bool:
    """Return whether the runtime may submit orders to any Binance venue."""
    resolved_env = normalize_runtime_env(env) if env is not None else get_runtime_env()
    return resolved_env in {"testnet", "live"}


def get_trading_mode_label(env: Optional[str] = None) -> str:
    """Return the public trading mode label used by API responses."""
    resolved_env = normalize_runtime_env(env) if env is not None else get_runtime_env()
    return resolved_env.upper()


def get_trading_db_path(env: Optional[str] = None, base_dir: Optional[Path] = None) -> Path:
    """Return the absolute DB path for the selected runtime environment."""
    resolved_env = normalize_runtime_env(env) if env is not None else get_runtime_env()

    if base_dir is None:
        # runtime.py lives at backend/src/config/runtime.py.
        base_dir = Path(__file__).resolve().parents[2]

    return base_dir / "data" / resolved_env / "trading_system.db"
