import json
from pathlib import Path

from scripts.checkpoint_research import _paper_env_suggestion


def test_rejected_checkpoint_has_no_paper_env_suggestion():
    metadata = {
        "config_hash": "abc123",
        "experiment_config": {
            "args": {"strategy_id": "liquidity_sniper_mean_reversion", "max_pos": 4},
            "symbols": ["BTCUSDT", "ETHUSDT"],
        },
    }

    assert _paper_env_suggestion(metadata, {"decision": "REJECT"}) is None


def test_non_rejected_checkpoint_builds_reviewable_paper_env_suggestion():
    metadata = {
        "config_hash": "abc123",
        "experiment_config": {
            "args": {
                "strategy_id": "liquidity_sniper_mean_reversion",
                "max_pos": 4,
                "leverage": 20,
                "close_profitable_auto": False,
                "daily_symbol_loss_limit": 2,
                "blocked_windows": "03:00-05:00",
            },
            "symbols": ["BTCUSDT", "ETHUSDT"],
        },
    }

    suggestion = _paper_env_suggestion(
        metadata,
        {"decision": "PAPER_RESEARCH_CANDIDATE_NEEDS_OOS"},
    )

    assert suggestion["ENV"] == "paper"
    assert suggestion["TRADING_MODE"] == "PAPER"
    assert suggestion["SYMBOLS"] == "BTCUSDT,ETHUSDT"
    assert suggestion["PAPER_RESEARCH_CONFIG_HASH"] == "abc123"
    assert suggestion["PAPER_LEVERAGE"] == "2"
    assert suggestion["PAPER_CLOSE_PROFITABLE_AUTO"] == "false"
    assert suggestion["PAPER_DAILY_SYMBOL_LOSS_LIMIT"] == "2"
    assert suggestion["PAPER_BLOCKED_WINDOWS"] == "03:00-05:00"
    assert suggestion["PAPER_BLOCKED_WINDOWS_ENABLED"] == "true"


def test_non_rejected_checkpoint_skips_unsupported_research_flags():
    metadata = {
        "config_hash": "abc123",
        "experiment_config": {
            "args": {
                "strategy_id": "liquidity_sniper_mean_reversion",
                "max_pos": 3,
                "adx_max_threshold": 30.0,
            },
            "symbols": ["ETHUSDT"],
        },
    }

    assert _paper_env_suggestion(
        metadata,
        {"decision": "PAPER_ONLY_SMALL_SAMPLE"},
    ) is None


def test_checkpoint_skips_research_only_runtime_drift_flags():
    metadata = {
        "config_hash": "abc123",
        "experiment_config": {
            "args": {
                "strategy_id": "liquidity_sniper_mean_reversion",
                "max_pos": 4,
                "leverage": 10,
                "extra_blacklist_sides": "*:SHORT",
                "symbol_side_loss_limit": 1,
                "direction_block": True,
            },
            "symbols": ["ETHUSDT", "BNBUSDT"],
        },
    }

    assert _paper_env_suggestion(
        metadata,
        {"decision": "PAPER_ONLY_SMALL_SAMPLE"},
    ) is None


def test_checkpoint_prefers_eligible_symbols_over_requested_symbols():
    metadata = {
        "config_hash": "abc123",
        "experiment_config": {
            "args": {"strategy_id": "liquidity_sniper_mean_reversion", "max_pos": 4},
            "requested_symbols": ["BTCUSDT", "ETHUSDT"],
            "eligible_symbols": ["ETHUSDT"],
        },
    }

    suggestion = _paper_env_suggestion(
        metadata,
        {"decision": "PAPER_RESEARCH_CANDIDATE_NEEDS_OOS"},
    )

    assert suggestion["SYMBOLS"] == "ETHUSDT"


def test_checkpoint_docs_exist():
    repo_root = Path(__file__).resolve().parents[2]
    assert (repo_root / "docs" / "RESEARCH_CHECKPOINTS.md").exists()
