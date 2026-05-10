from pathlib import Path

from src.config import get_trading_db_path as exported_db_path
from src.config.runtime import (
    get_execution_mode,
    get_trading_db_path,
    get_trading_mode_label,
    is_paper_real_enabled,
    is_real_ordering_enabled,
    normalize_runtime_env,
)


def test_runtime_env_normalizes_unknown_values_to_paper():
    assert normalize_runtime_env("live") == "live"
    assert normalize_runtime_env("TESTNET") == "testnet"
    assert normalize_runtime_env("unknown") == "paper"
    assert normalize_runtime_env(None) == "paper"


def test_paper_real_defaults_to_live_market_data_without_real_orders(monkeypatch):
    monkeypatch.setenv("ENV", "paper")
    monkeypatch.delenv("HINTO_PAPER_REAL", raising=False)

    assert get_execution_mode() == "paper_real"
    assert is_paper_real_enabled() is True
    assert is_real_ordering_enabled() is False


def test_trading_mode_label_uses_public_uppercase_names():
    assert get_trading_mode_label("paper") == "PAPER"
    assert get_trading_mode_label("testnet") == "TESTNET"
    assert get_trading_mode_label("live") == "LIVE"


def test_trading_db_path_is_environment_scoped(tmp_path: Path):
    assert get_trading_db_path("live", tmp_path) == tmp_path / "data" / "live" / "trading_system.db"
    assert get_trading_db_path("bad-env", tmp_path) == tmp_path / "data" / "paper" / "trading_system.db"


def test_legacy_config_export_uses_runtime_helper(tmp_path: Path):
    assert exported_db_path("testnet", tmp_path) == get_trading_db_path("testnet", tmp_path)
