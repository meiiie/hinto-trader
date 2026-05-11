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
            "args": {"strategy_id": "liquidity_sniper_mean_reversion", "max_pos": 4},
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
    assert Path("docs/RESEARCH_CHECKPOINTS.md").exists()
