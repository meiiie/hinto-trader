import json
import sqlite3

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
        apply_checkpoint(checkpoint, env, paper_db_path=None)


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

    result = apply_checkpoint(checkpoint, env, paper_db_path=None)
    content = env.read_text(encoding="utf-8")

    assert "SYMBOLS=ETHUSDT" in content
    assert "TRADING_MODE=PAPER" in content
    assert "BINANCE_API_KEY=secret" in content
    assert "should_not_apply" not in content
    assert result["backup"]
    assert result["paper_db"] is None


def test_apply_checkpoint_syncs_paper_db_settings(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ENV=paper\n", encoding="utf-8")
    db = tmp_path / "paper.db"
    with sqlite3.connect(db) as conn:
        conn.execute("create table settings (key text primary key, value text not null, updated_at text)")
        conn.execute("create table paper_account (id integer primary key, balance real not null)")
        conn.execute("create table paper_positions (id text)")
        conn.execute("create table signals (id text)")
        conn.execute("insert into paper_account (id, balance) values (1, 79)")
        conn.execute("insert into signals (id) values ('old-signal')")
        conn.commit()

    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(
        json.dumps(
            {
                "decision": "PAPER_ONLY_SMALL_SAMPLE",
                "paper_env_suggestion": {
                    "SYMBOLS": "ETHUSDT,BNBUSDT,XRPUSDT",
                    "PAPER_RISK_PERCENT": "0.01",
                    "PAPER_MAX_POSITIONS": "3",
                    "PAPER_START_BALANCE": "100",
                    "PAPER_CLOSE_PROFITABLE_AUTO": "false",
                    "PAPER_DAILY_SYMBOL_LOSS_LIMIT": "2",
                    "PAPER_BLOCKED_WINDOWS": "03:00-05:00,06:00-08:00",
                    "PAPER_BLOCKED_WINDOWS_ENABLED": "true",
                    "PAPER_MAX_DAILY_DRAWDOWN_PCT": "0.30",
                },
            }
        ),
        encoding="utf-8",
    )

    result = apply_checkpoint(checkpoint, env, paper_db_path=db, reset_paper_state=True)

    with sqlite3.connect(db) as conn:
        settings = dict(conn.execute("select key, value from settings").fetchall())
        balance = conn.execute("select balance from paper_account where id = 1").fetchone()[0]
        signal_count = conn.execute("select count(*) from signals").fetchone()[0]

    assert settings["enabled_tokens"] == "ETHUSDT,BNBUSDT,XRPUSDT"
    assert settings["risk_percent"] == "1.0"
    assert settings["max_positions"] == "3"
    assert settings["close_profitable_auto"] == "false"
    assert settings["daily_symbol_loss_limit"] == "2"
    assert settings["blocked_windows"] == "03:00-05:00,06:00-08:00"
    assert settings["blocked_windows_enabled"] == "true"
    assert settings["max_daily_drawdown_pct"] == "0.3"
    assert balance == 100
    assert signal_count == 0
    assert result["paper_db"]["reset_paper_state"] is True
