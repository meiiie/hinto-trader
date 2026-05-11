# Research Checkpoints

Hinto should not promote a strategy from memory, screenshots, or a single
profitable backtest. Every improvement must leave a local checkpoint with the
exact config hash, trade artifact, audit metrics, and decision.

## Workflow

1. Run a backtest or research matrix.
2. Confirm it produced `experiment_*.json` metadata.
3. Generate or review the research scoreboard.
4. Create a checkpoint:

```bash
python backend/scripts/research_scoreboard.py backend/experiment_YYYYMMDD_HHMMSS_xxxxxx.json
```

`backend/scripts/run_research_matrix.py` creates
`research_scoreboard_*.json` and `research_scoreboard_*.md` automatically for
matrix runs. The scoreboard is not a second source of truth; it is a compact
view over the same trade CSV, experiment metadata, and `research_audit` gates.
Use it to compare return, profit factor, expectancy, drawdown, bootstrap
confidence, weak symbols, and exit reasons before creating a checkpoint.

```bash
python backend/scripts/checkpoint_research.py backend/experiment_YYYYMMDD_HHMMSS_xxxxxx.json
```

The checkpoint is written to `backend/research_checkpoints/` and ignored by Git.
`backend/run_backtest.py` writes research artifacts under `backend/` regardless
of the caller's current working directory, so checkpoint creation can resolve
metadata and trade CSV paths deterministically.
The experiment metadata still records `git_commit` for traceability, but the
paper `config_hash` excludes it so unrelated documentation commits do not force
a new paper checkpoint.

## Paper Trading Updates

Checkpoints may include `paper_env_suggestion` only when the audit decision is
not `REJECT`. The script never mutates `.env` automatically.

To apply a reviewed non-rejected checkpoint to local paper mode:

```bash
python backend/scripts/apply_paper_checkpoint.py \
  backend/research_checkpoints/checkpoint_YYYYMMDD_HHMMSS_hash.json
```

The apply script refuses `REJECT`, only updates paper allowlist keys, preserves
secrets, syncs the local paper SQLite runtime settings that override `.env`,
and creates timestamped backups.

For a fresh paper observation run with no old paper positions:

```bash
python backend/scripts/apply_paper_checkpoint.py \
  backend/research_checkpoints/checkpoint_YYYYMMDD_HHMMSS_hash.json \
  --reset-paper-state
```

`--reset-paper-state` clears paper-only positions and local signal lifecycle
rows, then resets the local simulated wallet from `PAPER_START_BALANCE`. It does
not touch exchange orders.

When metadata includes both `requested_symbols` and `eligible_symbols`, paper
suggestions use `eligible_symbols`. This prevents a runtime paper config from
including symbols that were excluded by coverage or quality gates during the
research run.

Paper mode can be adjusted only after reviewing:

- 1m data coverage and fail-closed behavior;
- bootstrap positive-expectancy probability;
- Monte Carlo drawdown;
- stress runs without maker assumptions or with worse fill assumptions;
- paper/live drift after enough real-time paper trades.

If the decision is `REJECT`, the correct paper update is no update.

Stress results are part of the checkpoint decision. A result that looks
profitable but fails bootstrap or fee/fill stress should be checkpointed as a
rejected experiment, not applied to paper runtime.

## Current Status

The best current major-universe experiment is still rejected by the stricter
bootstrap gate and by stress-check confidence. It is useful for continued
paper observation, but not for promotion or live money.

The 2026-05-11 dynamic top50 smoke test was also rejected: `50` requested
symbols collapsed to `27` quality-filter-eligible symbols, returned about
`-6.5%` over four days, and had only about `9%` bootstrap positive-expectancy
probability. No paper runtime settings were changed from that checkpoint.
