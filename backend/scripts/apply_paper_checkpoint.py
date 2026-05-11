"""Apply a non-rejected research checkpoint to a local paper .env file."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
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
    "PAPER_MAX_POSITIONS",
    "PAPER_RESEARCH_CONFIG_HASH",
    "PAPER_RESEARCH_DECISION",
}


def _resolve(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else REPO_ROOT / path


def apply_checkpoint(checkpoint_path: str | Path, env_path: str | Path = ".env") -> dict:
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

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup = env_path.with_name(f"{env_path.name}.checkpoint-backup-{stamp}")
    shutil.copy2(env_path, backup)
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return {"updated": sorted(updates), "backup": str(backup), "env_path": str(env_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply paper config from a research checkpoint.")
    parser.add_argument("checkpoint_json", help="Path to checkpoint_*.json")
    parser.add_argument("--env", default=".env", help="Env file to update. Default: repo .env")
    args = parser.parse_args()
    print(json.dumps(apply_checkpoint(args.checkpoint_json, args.env), indent=2))


if __name__ == "__main__":
    main()
