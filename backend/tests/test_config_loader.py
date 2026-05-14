from pathlib import Path

from src import config_loader


def test_config_loader_skips_env_directory_and_uses_parent_file(tmp_path, monkeypatch):
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    (backend_dir / ".env").mkdir()
    parent_env = tmp_path / ".env"
    parent_env.write_text("ENV=paper\n", encoding="utf-8")

    monkeypatch.chdir(backend_dir)
    config_loader._config_result = None

    assert config_loader.get_config_path() == parent_env


def test_config_loader_prefers_current_directory_env_file(tmp_path, monkeypatch):
    cwd_env = tmp_path / ".env"
    cwd_env.write_text("ENV=paper\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    config_loader._config_result = None

    assert config_loader.get_config_path() == cwd_env
