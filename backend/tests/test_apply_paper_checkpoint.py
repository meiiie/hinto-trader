import json

import pytest

from scripts.apply_paper_checkpoint import apply_checkpoint


def test_apply_checkpoint_refuses_reject(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ENV=paper\n", encoding="utf-8")
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(
        json.dumps({"decision": "REJECT", "paper_env_suggestion": {"ENV": "paper"}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="REJECT"):
        apply_checkpoint(checkpoint, env)


def test_apply_checkpoint_updates_allowlisted_keys_and_preserves_other_values(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ENV=paper\nBINANCE_API_KEY=secret\nSYMBOLS=BTCUSDT\n", encoding="utf-8")
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(
        json.dumps(
            {
                "decision": "PAPER_ONLY_SMALL_SAMPLE",
                "paper_env_suggestion": {
                    "ENV": "paper",
                    "TRADING_MODE": "PAPER",
                    "SYMBOLS": "ETHUSDT",
                    "BINANCE_API_KEY": "should_not_apply",
                },
            }
        ),
        encoding="utf-8",
    )

    result = apply_checkpoint(checkpoint, env)
    content = env.read_text(encoding="utf-8")

    assert "SYMBOLS=ETHUSDT" in content
    assert "TRADING_MODE=PAPER" in content
    assert "BINANCE_API_KEY=secret" in content
    assert "should_not_apply" not in content
    assert result["backup"]
