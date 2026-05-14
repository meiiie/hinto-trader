"""Apply a non-rejected research checkpoint to a local paper .env file."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.trading_contract import clamp_runtime_leverage


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PAPER_DB = REPO_ROOT / "backend" / "data" / "paper" / "trading_system.db"
ALLOWED_KEYS = {
    "ENV",
    "TRADING_MODE",
    "HINTO_PAPER_REAL",
    "HINTO_STRATEGY_ID",
    "SYMBOLS",
    "BACKTEST_SYMBOLS",
    "USE_FIXED_SYMBOLS",
    "PAPER_START_BALANCE",
    "PAPER_RISK_PERCENT",
    "PAPER_LEVERAGE",
    "PAPER_MAX_POSITIONS",
    "PAPER_CLOSE_PROFITABLE_AUTO",
    "PAPER_DAILY_SYMBOL_LOSS_LIMIT",
    "PAPER_BLOCKED_WINDOWS",
    "PAPER_BLOCKED_WINDOWS_ENABLED",
    "PAPER_MAX_DAILY_DRAWDOWN_PCT",
    "PAPER_RESEARCH_CONFIG_HASH",
    "PAPER_RESEARCH_DECISION",
}
DB_SETTING_KEYS = {
    "enabled_tokens",
    "risk_percent",
    "leverage",
    "max_positions",
    "close_profitable_auto",
    "daily_symbol_loss_limit",
    "blocked_windows",
    "blocked_windows_enabled",
    "max_daily_drawdown_pct",
}


def _resolve(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else REPO_ROOT / path


def _backup(path: Path, suffix: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.name}.{suffix}-{stamp}")
    shutil.copy2(path, backup)
    return backup


def _setting_updates(suggestion: dict) -> dict:
    updates = {}
    symbols = suggestion.get("SYMBOLS") or suggestion.get("BACKTEST_SYMBOLS")
    if symbols:
        updates["enabled_tokens"] = str(symbols)
    risk = suggestion.get("PAPER_RISK_PERCENT")
    if risk is not None:
        updates["risk_percent"] = str(float(risk) * 100)
    leverage = suggestion.get("PAPER_LEVERAGE")
    if leverage is not None:
        updates["leverage"] = str(clamp_runtime_leverage(leverage))
    max_positions = suggestion.get("PAPER_MAX_POSITIONS")
    if max_positions is not None:
        updates["max_positions"] = str(int(max_positions))
    close_profitable = suggestion.get("PAPER_CLOSE_PROFITABLE_AUTO")
    if close_profitable is not None:
        updates["close_profitable_auto"] = (
            "true" if str(close_profitable).strip().lower() in {"1", "true", "yes", "on"} else "false"
        )
    daily_loss_limit = suggestion.get("PAPER_DAILY_SYMBOL_LOSS_LIMIT")
    if daily_loss_limit is not None:
        updates["daily_symbol_loss_limit"] = str(int(daily_loss_limit))
    blocked_windows = suggestion.get("PAPER_BLOCKED_WINDOWS")
    if blocked_windows is not None:
        updates["blocked_windows"] = str(blocked_windows)
    blocked_windows_enabled = suggestion.get("PAPER_BLOCKED_WINDOWS_ENABLED")
    if blocked_windows_enabled is not None:
        updates["blocked_windows_enabled"] = (
            "true" if str(blocked_windows_enabled).strip().lower() in {"1", "true", "yes", "on"} else "false"
        )
    max_daily_drawdown = suggestion.get("PAPER_MAX_DAILY_DRAWDOWN_PCT")
    if max_daily_drawdown is not None:
        updates["max_daily_drawdown_pct"] = str(float(max_daily_drawdown))
    return updates


def _sync_paper_db(
    suggestion: dict,
    db_path: Path,
    reset_paper_state: bool = False,
) -> dict | None:
    if not db_path.exists():
        return None

    updates = _setting_updates(suggestion)
    if not updates and not reset_paper_state:
        return None

    backup = _backup(db_path, "checkpoint-backup")
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        for key, value in updates.items():
            if key not in DB_SETTING_KEYS:
                continue
            cursor.execute(
                """
                INSERT OR REPLACE INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
                """,
                (key, value, datetime.now(timezone.utc).isoformat()),
            )

        if reset_paper_state:
            balance = float(suggestion.get("PAPER_START_BALANCE", 100))
            cursor.execute("DELETE FROM paper_positions")
            cursor.execute("DELETE FROM signals")
            cursor.execute("UPDATE paper_account SET balance = ? WHERE id = 1", (balance,))

        conn.commit()

    return {
        "path": str(db_path),
        "backup": str(backup),
        "updated_settings": sorted(updates),
        "reset_paper_state": reset_paper_state,
    }


def apply_checkpoint(
    checkpoint_path: str | Path,
    env_path: str | Path = ".env",
    paper_db_path: str | Path | None = DEFAULT_PAPER_DB,
    reset_paper_state: bool = False,
) -> dict:
    checkpoint_path = _resolve(checkpoint_path)
    env_path = _resolve(env_path)
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    suggestion = checkpoint.get("paper_env_suggestion")
    if not suggestion:
        raise ValueError("checkpoint has no paper_env_suggestion; refusing to update paper config")
    if checkpoint.get("decision") == "REJECT":
        raise ValueError("checkpoint decision is REJECT; refusing to update paper config")

    updates = {key: str(value) for key, value in suggestion.items() if key in ALLOWED_KEYS}
    if not updates:
        raise ValueError("checkpoint contains no allowed paper env keys")

    lines = env_path.read_text(encoding="utf-8").splitlines()
    seen = set()
    new_lines = []
    for line in lines:
        if "=" not in line or line.lstrip().startswith("#"):
            new_lines.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            new_lines.append(line)

    missing = [key for key in updates if key not in seen]
    if missing:
        if new_lines and new_lines[-1] != "":
            new_lines.append("")
        new_lines.extend(f"{key}={updates[key]}" for key in missing)

    backup = _backup(env_path, "checkpoint-backup")
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    paper_db = None
    if paper_db_path is not None:
        paper_db = _sync_paper_db(
            suggestion,
            _resolve(paper_db_path),
            reset_paper_state=reset_paper_state,
        )

    return {
        "updated": sorted(updates),
        "backup": str(backup),
        "env_path": str(env_path),
        "paper_db": paper_db,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply paper config from a research checkpoint.")
    parser.add_argument("checkpoint_json", help="Path to checkpoint_*.json")
    parser.add_argument("--env", default=".env", help="Env file to update. Default: repo .env")
    parser.add_argument(
        "--paper-db",
        default=str(DEFAULT_PAPER_DB),
        help="Paper SQLite DB to sync runtime settings. Use empty string to skip.",
    )
    parser.add_argument(
        "--reset-paper-state",
        action="store_true",
        help="Clear paper positions and reset wallet balance from PAPER_START_BALANCE.",
    )
    args = parser.parse_args()
    paper_db = args.paper_db or None
    print(
        json.dumps(
            apply_checkpoint(
                args.checkpoint_json,
                args.env,
                paper_db_path=paper_db,
                reset_paper_state=args.reset_paper_state,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
