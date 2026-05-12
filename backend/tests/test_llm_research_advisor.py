import json

from scripts.llm_research_advisor import (
    _load_env_file,
    build_research_pack,
    build_research_prompt,
    parse_json_response,
    resolve_provider,
    sanitize_for_prompt,
    summarize_trades,
)


def test_env_loader_reads_only_allowlisted_provider_keys(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "NVIDIA_API_KEY=nvapi-test-value",
                "NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1",
                "DATABASE_URL=postgres://should-not-load",
                "BINANCE_API_SECRET=do-not-load",
            ]
        ),
        encoding="utf-8",
    )

    loaded = _load_env_file(env_file)

    assert loaded["NVIDIA_API_KEY"] == "nvapi-test-value"
    assert loaded["NVIDIA_BASE_URL"] == "https://integrate.api.nvidia.com/v1"
    assert "DATABASE_URL" not in loaded
    assert "BINANCE_API_SECRET" not in loaded


def test_provider_public_metadata_does_not_expose_api_key():
    provider = resolve_provider(
        "nvidia",
        env={
            "NVIDIA_API_KEY": "nvapi-secret-value",
            "NVIDIA_MODEL": "deepseek-ai/deepseek-v4-flash",
        },
    )

    assert provider.public()["auth_status"] == "configured"
    assert "nvapi-secret-value" not in json.dumps(provider.public())


def test_sanitize_for_prompt_redacts_secret_keys_and_values():
    payload = {
        "api_key": "nvapi-" + "x" * 40,
        "nested": {"token": "sk-" + "a" * 40},
        "safe": "ETHUSDT",
    }

    cleaned = sanitize_for_prompt(payload)
    dumped = json.dumps(cleaned)

    assert "ETHUSDT" in dumped
    assert "nvapi-" not in dumped
    assert "sk-" not in dumped
    assert "[REDACTED]" in dumped


def test_sanitize_can_preserve_long_artifact_strings():
    long_text = "x" * 3000

    assert len(sanitize_for_prompt(long_text)) == 2000
    assert len(sanitize_for_prompt(long_text, max_string=50000)) == 3000


def test_trade_summary_extracts_symbol_reason_and_month(tmp_path):
    trade_csv = tmp_path / "trades.csv"
    trade_csv.write_text(
        "\n".join(
            [
                "Trade ID,Symbol,Side,Entry Time (UTC+7),Exit Time (UTC+7),Hold Duration (h),PnL ($),Reason",
                "1,ETHUSDT,LONG,2026-05-01 01:00:00,2026-05-01 02:00:00,1.0,1.50,TAKE_PROFIT_1",
                "2,DOTUSDT,LONG,2026-05-02 01:00:00,2026-05-02 03:00:00,2.0,-0.70,STOP_LOSS",
            ]
        ),
        encoding="utf-8",
    )

    summary = summarize_trades(trade_csv)

    assert summary["total_trades"] == 2
    assert summary["total_pnl"] == 0.8
    assert summary["best_symbols"][0]["key"] == "ETHUSDT"
    assert summary["worst_symbols"][0]["key"] == "DOTUSDT"
    assert summary["exit_reasons"][0]["key"] == "TAKE_PROFIT_1"


def test_research_pack_and_prompt_keep_llm_research_only():
    metadata = {
        "run_stamp": "20260513_000000",
        "config_hash": "abc123",
        "experiment_config": {
            "args": {
                "strategy_id": "liquidity_sniper_mean_reversion",
                "leverage": 2,
                "risk": 0.01,
                "max_pos": 4,
                "api_key": "nvapi-" + "z" * 40,
            },
            "eligible_symbols": ["ETHUSDT", "BNBUSDT"],
            "requested_symbols": ["ETHUSDT", "BNBUSDT", "DOGEUSDT"],
        },
        "summary": {"net_return_pct": 3.4, "total_trades": 12},
    }

    pack = build_research_pack(metadata)
    prompt = build_research_prompt(pack)

    assert "Target leverage remains 2x" in prompt
    assert "Do not produce executable orders" in prompt
    assert "ETHUSDT" in prompt
    assert "nvapi-" not in prompt


def test_parse_json_response_accepts_wrapped_json_and_reports_truncation():
    parsed, error = parse_json_response('notes\n{"verdict":"paper_observe_only"}\n')

    assert parsed == {"verdict": "paper_observe_only"}
    assert error is None

    parsed, error = parse_json_response('{"verdict":"paper_observe_only"')

    assert parsed is None
    assert error
