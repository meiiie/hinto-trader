"""Create a local research checkpoint from backtest experiment metadata.

Checkpoints are intentionally local artifacts. They preserve the audit result,
promotion gate, and optional paper-mode configuration suggestion without
silently mutating a user's .env file.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
SCRIPT_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from src.trading_contract import (
    PRODUCTION_ADX_MAX_THRESHOLD,
    PRODUCTION_SNIPER_LOOKBACK,
    PRODUCTION_SNIPER_PROXIMITY,
    PRODUCTION_USE_ADX_MAX_FILTER,
    PRODUCTION_USE_DELTA_DIVERGENCE,
    PRODUCTION_USE_MTF_TREND,
    clamp_runtime_leverage,
)
from research_audit import audit_trades, load_trades
CHECKPOINT_DIR = ROOT / "research_checkpoints"
PAPER_RESEARCH_DECISIONS = {
    "PAPER_ONLY_SMALL_SAMPLE",
    "PAPER_RESEARCH_CANDIDATE_NEEDS_OOS",
    "PROMOTION_CANDIDATE_REVIEW_REQUIRED",
}
UNSUPPORTED_PAPER_SUGGESTION_FLAGS = (
    "adx_regime_filter",
    "atr_sl",
    "bb_filter",
    "cb",
    "direction_block",
    "dynamic_tp",
    "extra_blacklist",
    "extra_blacklist_sides",
    "fill_top_eligible",
    "fix_vwap",
    "funding_filter",
    "daily_loss_size_penalty",
    "low_profit_pair_limit",
    "max_same_direction",
    "no_compound",
    "regime_filter",
    "symbol_side_loss_limit",
    "stochrsi_filter",
    "vol_sizing",
    "volume_confirm",
)


def _has_unsupported_paper_suggestion_args(args: dict) -> bool:
    """Return True when a research run cannot be represented by paper settings."""
    for flag in UNSUPPORTED_PAPER_SUGGESTION_FLAGS:
        if args.get(flag):
            return True

    if (
        args.get("adx_max_filter") is not None
        and bool(args.get("adx_max_filter")) != PRODUCTION_USE_ADX_MAX_FILTER
    ):
        return True
    if (
        args.get("adx_max_threshold") is not None
        and float(args.get("adx_max_threshold")) != PRODUCTION_ADX_MAX_THRESHOLD
    ):
        return True
    if (
        args.get("delta_divergence") is not None
        and bool(args.get("delta_divergence")) != PRODUCTION_USE_DELTA_DIVERGENCE
    ):
        return True
    if (
        args.get("mtf_trend") is not None
        and bool(args.get("mtf_trend")) != PRODUCTION_USE_MTF_TREND
    ):
        return True
    if (
        args.get("sniper_lookback") is not None
        and int(args.get("sniper_lookback")) != PRODUCTION_SNIPER_LOOKBACK
    ):
        return True
    if args.get("sniper_proximity") is not None:
        proximity = float(args.get("sniper_proximity"))
        # CLI stores percent units, while the production contract stores a decimal.
        if proximity > 1:
            proximity /= 100.0
        if proximity != PRODUCTION_SNIPER_PROXIMITY:
            return True

    return False


def _paper_env_suggestion(metadata: dict, audit: dict) -> dict | None:
    decision = audit.get("decision")
    if decision not in PAPER_RESEARCH_DECISIONS:
        return None

    config = metadata.get("experiment_config", {})
    args = config.get("args", {})
    if _has_unsupported_paper_suggestion_args(args):
        return None

    symbols = config.get("eligible_symbols") or config.get("symbols") or config.get("requested_symbols") or []

    return {
        "ENV": "paper",
        "TRADING_MODE": "PAPER",
        "HINTO_PAPER_REAL": "true",
        "HINTO_STRATEGY_ID": args.get("strategy_id") or "liquidity_sniper_mean_reversion",
        "SYMBOLS": ",".join(symbols),
        "BACKTEST_SYMBOLS": ",".join(symbols),
        "USE_FIXED_SYMBOLS": "true",
        "PAPER_START_BALANCE": "100",
        "PAPER_RISK_PERCENT": "0.01",
        "PAPER_LEVERAGE": str(clamp_runtime_leverage(args.get("leverage", 2))),
        "PAPER_MAX_POSITIONS": str(args.get("max_pos", 4)),
        "PAPER_CLOSE_PROFITABLE_AUTO": "true" if args.get("close_profitable_auto") else "false",
        "PAPER_DAILY_SYMBOL_LOSS_LIMIT": str(int(args.get("daily_symbol_loss_limit") or 0)),
        "PAPER_BLOCKED_WINDOWS": str(args.get("blocked_windows") or ""),
        "PAPER_BLOCKED_WINDOWS_ENABLED": "true" if args.get("blocked_windows") else "false",
        "PAPER_MAX_DAILY_DRAWDOWN_PCT": str(args.get("drawdown", 0.15)),
        "PAPER_RESEARCH_CONFIG_HASH": metadata.get("config_hash"),
        "PAPER_RESEARCH_DECISION": decision,
    }


def create_checkpoint(metadata_path: str | Path, *, audit_runs: int, seed: int) -> dict:
    metadata_path = Path(metadata_path)
    if not metadata_path.is_absolute():
        repo_relative = REPO_ROOT / metadata_path
        metadata_path = repo_relative if repo_relative.exists() else ROOT / metadata_path
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    trade_file = ROOT / metadata["artifacts"]["trades_csv"]
    audit = audit_trades(
        load_trades(trade_file),
        initial_balance=100.0,
        risk_percent=0.01,
        monte_carlo_runs=audit_runs,
        seed=seed,
    )
    suggestion = _paper_env_suggestion(metadata, audit)

    checkpoint = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_metadata": metadata_path.name,
        "config_hash": metadata.get("config_hash"),
        "decision": audit.get("decision"),
        "audit": audit,
        "artifacts": metadata.get("artifacts", {}),
        "paper_env_suggestion": suggestion,
        "paper_env_applied": False,
        "notes": (
            "No runtime .env file was changed. Apply paper_env_suggestion only after "
            "reviewing data coverage, stress results, and paper/live drift."
        ),
    }

    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    output = CHECKPOINT_DIR / f"checkpoint_{stamp}_{metadata.get('config_hash', 'unknown')}.json"
    output.write_text(json.dumps(checkpoint, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"checkpoint": output.name, **checkpoint}


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a Hinto research checkpoint.")
    parser.add_argument("metadata_json", help="Path/name of experiment_*.json")
    parser.add_argument("--audit-runs", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=1337)
    args = parser.parse_args()

    print(json.dumps(create_checkpoint(args.metadata_json, audit_runs=args.audit_runs, seed=args.seed), indent=2))


if __name__ == "__main__":
    main()
