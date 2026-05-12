"""Research-only LLM advisor for Hinto backtest artifacts.

The advisor turns deterministic backtest outputs into a compact prompt for an
LLM. It must never place orders, mutate paper state, or promote a strategy.
Its output is an ignored local artifact that suggests testable research ideas.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent

ALLOWED_PROVIDER_ENV = {
    "NVIDIA_API_KEY",
    "NVIDIA_BASE_URL",
    "NVIDIA_MODEL",
    "NVIDIA_MODEL_ADVANCED",
    "OPENROUTER_API_KEY",
    "OPENROUTER_BASE_URL",
    "OPENROUTER_MODEL",
    "ZHIPU_API_KEY",
    "ZHIPU_BASE_URL",
    "ZHIPU_MODEL",
}

SECRET_KEY_RE = re.compile(r"(api[_-]?key|secret|token|password|credential)", re.IGNORECASE)
SECRET_VALUE_RE = re.compile(
    r"(?i)\b(?:sk-[A-Za-z0-9_-]{16,}|nvapi-[A-Za-z0-9_.-]{16,}|"
    r"[A-Za-z0-9_-]{32,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,})\b"
)

PROVIDER_DEFAULTS = {
    "nvidia": {
        "key": "NVIDIA_API_KEY",
        "base": "NVIDIA_BASE_URL",
        "model": ("NVIDIA_MODEL_ADVANCED", "NVIDIA_MODEL"),
        "default_base": "https://integrate.api.nvidia.com/v1",
        "default_model": "deepseek-ai/deepseek-v4-flash",
    },
    "openrouter": {
        "key": "OPENROUTER_API_KEY",
        "base": "OPENROUTER_BASE_URL",
        "model": ("OPENROUTER_MODEL",),
        "default_base": "https://openrouter.ai/api/v1",
        "default_model": "openai/gpt-4.1-mini",
    },
    "zhipu": {
        "key": "ZHIPU_API_KEY",
        "base": "ZHIPU_BASE_URL",
        "model": ("ZHIPU_MODEL",),
        "default_base": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-5",
    },
}

PROMPT_FLAGS = (
    "strategy_id",
    "interval",
    "start",
    "end",
    "risk",
    "leverage",
    "max_pos",
    "full_tp",
    "maker_orders",
    "bounce_confirm",
    "daily_symbol_loss_limit",
    "blocked_windows",
    "max_sl_validation",
    "max_sl_pct",
    "adx_max_filter",
    "adx_max_threshold",
    "delta_divergence",
    "mtf_trend",
    "cb",
    "max_losses",
    "cooldown",
    "drawdown",
    "direction_block",
    "max_same_direction",
    "extra_blacklist_sides",
    "volume_slippage",
    "adversarial_path",
)

PAPER_DRIFT_FLAGS = (
    "cb",
    "direction_block",
    "extra_blacklist_sides",
    "daily_loss_size_penalty",
    "max_same_direction",
    "symbol_side_loss_limit",
    "symbol_side_cooldown",
)


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    base_url: str
    model: str
    api_key: str | None

    def public(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "auth_status": "configured" if self.api_key else "missing",
        }


def _resolve(path: str | Path) -> Path:
    path = Path(path)
    if path.is_absolute():
        return path
    for candidate in (REPO_ROOT / path, ROOT / path):
        if candidate.exists():
            return candidate
    return REPO_ROOT / path


def _load_env_file(path: str | Path | None) -> dict[str, str]:
    if not path:
        return {}
    env_path = Path(path)
    if not env_path.exists():
        raise FileNotFoundError(f"env file not found: {env_path}")

    loaded: dict[str, str] = {}
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in ALLOWED_PROVIDER_ENV:
            continue
        value = value.strip().strip('"').strip("'")
        loaded[key] = value
    return loaded


def _merged_provider_env(env_file: str | Path | None) -> dict[str, str]:
    merged = _load_env_file(env_file)
    for key in ALLOWED_PROVIDER_ENV:
        if os.getenv(key):
            merged[key] = os.environ[key]
    return merged


def _first_env(env: dict[str, str], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = env.get(key)
        if value:
            return value
    return None


def resolve_provider(
    provider: str,
    *,
    env: dict[str, str],
    base_url: str | None = None,
    model: str | None = None,
) -> ProviderConfig:
    if provider not in PROVIDER_DEFAULTS:
        raise ValueError(f"unsupported provider: {provider}")
    defaults = PROVIDER_DEFAULTS[provider]
    return ProviderConfig(
        provider=provider,
        base_url=base_url or env.get(str(defaults["base"])) or str(defaults["default_base"]),
        model=model or _first_env(env, tuple(defaults["model"])) or str(defaults["default_model"]),
        api_key=env.get(str(defaults["key"])),
    )


def _redact_string(value: str) -> str:
    if SECRET_VALUE_RE.search(value):
        return SECRET_VALUE_RE.sub("[REDACTED]", value)
    return value


def sanitize_for_prompt(value: Any, *, max_string: int = 2000) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if SECRET_KEY_RE.search(key_text):
                cleaned[key_text] = "[REDACTED]"
            else:
                cleaned[key_text] = sanitize_for_prompt(item, max_string=max_string)
        return cleaned
    if isinstance(value, list):
        return [sanitize_for_prompt(item, max_string=max_string) for item in value[:100]]
    if isinstance(value, str):
        return _redact_string(value[:max_string])
    return value


def _float_cell(row: dict[str, str], name: str, default: float = 0.0) -> float:
    value = row.get(name, "")
    value = value.replace("$", "").replace(",", "").replace("%", "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _sort_metric_rows(rows: dict[str, dict[str, Any]], *, limit: int, reverse: bool) -> list[dict[str, Any]]:
    sorted_rows = sorted(rows.values(), key=lambda item: float(item["pnl"]), reverse=reverse)
    result = []
    for row in sorted_rows[:limit]:
        trades = max(int(row["trades"]), 1)
        result.append(
            {
                "key": row["key"],
                "trades": row["trades"],
                "pnl": round(float(row["pnl"]), 4),
                "win_rate": round(100.0 * float(row["wins"]) / trades, 2),
            }
        )
    return result


def summarize_trades(csv_path: str | Path | None) -> dict[str, Any]:
    if not csv_path:
        return {}
    path = _resolve(csv_path)
    if not path.exists():
        return {"warning": f"trade csv not found: {path.name}"}

    by_symbol: dict[str, dict[str, Any]] = {}
    by_reason: dict[str, dict[str, Any]] = {}
    by_month: dict[str, dict[str, Any]] = {}
    hold_hours: list[float] = []
    total_pnl = 0.0
    total_trades = 0

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            total_trades += 1
            pnl = _float_cell(row, "PnL ($)")
            total_pnl += pnl
            hold_hours.append(_float_cell(row, "Hold Duration (h)"))
            win = pnl > 0
            symbol = row.get("Symbol", "UNKNOWN") or "UNKNOWN"
            reason = row.get("Reason", "UNKNOWN") or "UNKNOWN"
            exit_time = row.get("Exit Time (UTC+7)") or row.get("Entry Time (UTC+7)") or ""
            month = exit_time[:7] if len(exit_time) >= 7 else "UNKNOWN"

            for bucket, key in ((by_symbol, symbol), (by_reason, reason), (by_month, month)):
                item = bucket.setdefault(key, {"key": key, "trades": 0, "wins": 0, "pnl": 0.0})
                item["trades"] += 1
                item["wins"] += 1 if win else 0
                item["pnl"] += pnl

    avg_hold = sum(hold_hours) / len(hold_hours) if hold_hours else 0.0
    return {
        "source_csv": path.name,
        "total_trades": total_trades,
        "total_pnl": round(total_pnl, 4),
        "avg_hold_hours": round(avg_hold, 2),
        "max_hold_hours": round(max(hold_hours), 2) if hold_hours else 0.0,
        "best_symbols": _sort_metric_rows(by_symbol, limit=8, reverse=True),
        "worst_symbols": _sort_metric_rows(by_symbol, limit=8, reverse=False),
        "exit_reasons": _sort_metric_rows(by_reason, limit=8, reverse=True),
        "monthly": _sort_metric_rows(by_month, limit=12, reverse=True),
    }


def _compact_scoreboard(scoreboard: dict[str, Any] | None) -> dict[str, Any] | None:
    if not scoreboard:
        return None
    cases = []
    for case in scoreboard.get("cases", [])[:12]:
        metrics = case.get("metrics", {})
        cases.append(
            {
                "case": case.get("case"),
                "status": case.get("status"),
                "decision": case.get("decision"),
                "metrics": {
                    "return_pct": metrics.get("return_pct"),
                    "trades": metrics.get("trades"),
                    "win_rate": metrics.get("win_rate"),
                    "profit_factor": metrics.get("profit_factor"),
                    "expectancy_per_trade": metrics.get("expectancy_per_trade"),
                    "max_drawdown_pct": metrics.get("max_drawdown_pct"),
                    "bootstrap_positive_expectancy_prob": metrics.get(
                        "bootstrap_positive_expectancy_prob"
                    ),
                    "selection_adjusted_bootstrap_positive_prob": metrics.get(
                        "selection_adjusted_bootstrap_positive_prob"
                    ),
                },
                "failed_gates": [
                    gate.get("name")
                    for gate in case.get("gates", [])
                    if gate.get("status") in {"FAIL", "WARN"}
                ],
                "worst_symbols": case.get("worst_symbols", [])[:5],
                "reason_breakdown": case.get("reason_breakdown", [])[:5],
            }
        )
    return {
        "summary": scoreboard.get("summary", {}),
        "cases": cases,
    }


def load_json(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    resolved = _resolve(path)
    return json.loads(resolved.read_text(encoding="utf-8"))


def build_research_pack(
    metadata: dict[str, Any],
    *,
    scoreboard: dict[str, Any] | None = None,
    trade_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = metadata.get("experiment_config", {})
    args = config.get("args", {})
    selected_args = {key: args.get(key) for key in PROMPT_FLAGS if key in args}
    paper_drift = sorted(key for key in PAPER_DRIFT_FLAGS if args.get(key))
    eligible = config.get("eligible_symbols") or []
    requested = config.get("requested_symbols") or []

    pack = {
        "project": "Hinto",
        "purpose": "research_only_llm_advisor",
        "hard_constraints": [
            "Target leverage remains 2x.",
            "Do not produce executable orders or real-time trade calls.",
            "Any idea must be expressible as deterministic backtest logic before paper use.",
            "No paper/live promotion if sample size, bootstrap, or fill-stress gates fail.",
            "Prefer changes that improve positive skew: cut losers quickly, let verified winners run.",
        ],
        "source": {
            "run_stamp": metadata.get("run_stamp"),
            "config_hash": metadata.get("config_hash"),
            "created_at_utc": metadata.get("created_at_utc"),
            "git_commit": config.get("git_commit"),
        },
        "summary": metadata.get("summary", {}),
        "config": {
            "args": selected_args,
            "paper_drift_flags_enabled": paper_drift,
            "requested_symbol_count": len(requested),
            "eligible_symbol_count": len(eligible),
            "eligible_symbols": eligible[:80],
            "blocked_symbol_sides": config.get("blocked_symbol_sides", []),
            "start_time_utc": config.get("start_time_utc"),
            "end_time_utc": config.get("end_time_utc"),
        },
        "trade_diagnostics": trade_summary or {},
        "scoreboard": _compact_scoreboard(scoreboard),
    }
    return sanitize_for_prompt(pack)


def build_research_prompt(pack: dict[str, Any]) -> str:
    payload = json.dumps(pack, indent=2, ensure_ascii=False)
    return (
        "You are a skeptical quantitative research reviewer for a crypto paper-trading system.\n"
        "The system trades Binance perpetuals in paper mode, and the owner wants a robust 2x strategy.\n"
        "Do not give financial advice or live trade instructions. Do not optimize for a pretty backtest.\n"
        "Treat sample-size failure, data snooping, fill assumptions, and paper/live drift as first-class risks.\n\n"
        "Return JSON only with this shape:\n"
        "{\n"
        '  "verdict": "reject|paper_observe_only|research_promising",\n'
        '  "why": ["short reason"],\n'
        '  "biggest_risks": ["risk"],\n'
        '  "next_experiments": [\n'
        "    {\n"
        '      "name": "short_snake_case",\n'
        '      "hypothesis": "testable edge mechanism",\n'
        '      "deterministic_rules": ["rules or filters to implement/test"],\n'
        '      "data_needed": ["data"],\n'
        '      "success_gate": "numeric promotion gate",\n'
        '      "failure_gate": "numeric rejection gate",\n'
        '      "paper_parity_risk": "low|medium|high"\n'
        "    }\n"
        "  ],\n"
        '  "llm_allowed_roles": ["safe LLM uses"],\n'
        '  "llm_forbidden_roles": ["unsafe LLM uses"],\n'
        '  "paper_2x_recommendation": "what to do before/while paper testing"\n'
        "}\n\n"
        "Backtest artifact summary:\n"
        f"{payload}\n"
    )


def parse_json_response(text: str | None) -> tuple[Any | None, str | None]:
    if not text:
        return None, "empty response"
    stripped = text.strip()
    try:
        return json.loads(stripped), None
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(stripped[start : end + 1]), None
            except json.JSONDecodeError as exc:
                return None, str(exc)
        return None, "no JSON object found"


def call_chat_completion(
    provider: ProviderConfig,
    prompt: str,
    *,
    timeout: float,
    temperature: float = 0.1,
    max_tokens: int = 1600,
) -> str:
    if not provider.api_key:
        raise ValueError(f"{provider.provider} API key is not configured")

    endpoint = provider.base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": provider.model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a cautious quantitative trading research auditor. "
                    "Return compact JSON and never request secrets or live orders."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"provider HTTP {exc.code}: {details}") from exc
    return str(payload["choices"][0]["message"]["content"])


def _default_output_paths(stamp: str) -> tuple[Path, Path]:
    return ROOT / f"llm_research_{stamp}.json", ROOT / f"llm_research_{stamp}.md"


def _write_markdown(path: Path, artifact: dict[str, Any]) -> None:
    response_json = artifact.get("llm_response_json")
    response = (
        json.dumps(response_json, indent=2, ensure_ascii=False)
        if response_json
        else artifact.get("llm_response") or "(dry run: no model response)"
    )
    provider = artifact["provider"]
    pack = artifact["research_pack"]
    summary = pack.get("summary", {})
    lines = [
        "# Hinto LLM Research Advisor",
        "",
        f"Created: `{artifact['created_at_utc']}`",
        f"Provider: `{provider['provider']}` / `{provider['model']}`",
        f"Dry run: `{artifact['dry_run']}`",
        f"Source: `{artifact['source_metadata']}`",
        "",
        "## Backtest Snapshot",
        "",
        f"- Return: `{summary.get('net_return_pct')}%`",
        f"- Trades: `{summary.get('total_trades')}`",
        f"- Win rate: `{summary.get('win_rate')}%`",
        f"- Max drawdown: `{summary.get('max_drawdown_pct')}%`",
        "",
        "## Model Response",
        "",
        "```json",
        response.strip(),
        "```",
        "",
        f"Parse error: `{artifact.get('llm_response_parse_error') or 'none'}`",
        "",
        "## Guardrail",
        "",
        "This artifact is research-only. It is not a paper/live promotion and it must not be used as a trading signal.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def run_advisor(args: argparse.Namespace) -> dict[str, Any]:
    metadata_path = _resolve(args.metadata_json)
    metadata = load_json(metadata_path) or {}
    scoreboard = load_json(args.scoreboard_json)
    trade_summary = summarize_trades(args.trade_csv or metadata.get("artifacts", {}).get("trades_csv"))
    env = _merged_provider_env(args.env_file)
    provider = resolve_provider(args.provider, env=env, base_url=args.base_url, model=args.model)
    pack = build_research_pack(metadata, scoreboard=scoreboard, trade_summary=trade_summary)
    prompt = build_research_prompt(pack)

    response = None
    if not args.dry_run:
        response = call_chat_completion(provider, prompt, timeout=args.timeout, max_tokens=args.max_tokens)
        response = _redact_string(response)
    response_json, response_parse_error = parse_json_response(response)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    default_json, default_md = _default_output_paths(stamp)
    json_path = _resolve(args.output_json) if args.output_json else default_json
    md_path = _resolve(args.output_md) if args.output_md else default_md
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)

    artifact = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_metadata": metadata_path.name,
        "source_scoreboard": Path(args.scoreboard_json).name if args.scoreboard_json else None,
        "source_trade_csv": trade_summary.get("source_csv") if isinstance(trade_summary, dict) else None,
        "dry_run": bool(args.dry_run),
        "provider": provider.public(),
        "research_pack": pack,
        "prompt": prompt,
        "llm_response": response,
        "llm_response_json": response_json,
        "llm_response_parse_error": response_parse_error,
        "guardrail": (
            "Research-only artifact. LLM output cannot update paper/live settings, "
            "place orders, or override deterministic backtest gates."
        ),
    }
    artifact = sanitize_for_prompt(artifact, max_string=50000)
    json_path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_markdown(md_path, artifact)
    return {
        "json": str(json_path),
        "markdown": str(md_path),
        "dry_run": artifact["dry_run"],
        "provider": artifact["provider"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a research-only LLM review of Hinto backtest artifacts.")
    parser.add_argument("metadata_json", help="Path/name of experiment_*.json")
    parser.add_argument("--scoreboard-json", help="Optional research_scoreboard_*.json")
    parser.add_argument("--trade-csv", help="Optional trade CSV override")
    parser.add_argument("--env-file", help="Optional provider env file; only allowlisted LLM keys are read")
    parser.add_argument("--provider", choices=sorted(PROVIDER_DEFAULTS), default="nvidia")
    parser.add_argument("--base-url", help="Override OpenAI-compatible base URL")
    parser.add_argument("--model", help="Override model name")
    parser.add_argument("--dry-run", action="store_true", help="Write prompt/artifacts without calling the model")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--max-tokens", type=int, default=2600)
    parser.add_argument("--output-json")
    parser.add_argument("--output-md")
    args = parser.parse_args()

    try:
        print(json.dumps(run_advisor(args), indent=2, ensure_ascii=False))
    except Exception as exc:  # pragma: no cover - CLI guardrail
        print(f"llm_research_advisor failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
