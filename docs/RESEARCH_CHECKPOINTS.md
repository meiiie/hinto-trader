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

For multi-window checks, run:

```bash
python backend/scripts/run_walk_forward.py \
  --window 2026-01-24:2026-02-24 \
  --window 2026-02-24:2026-03-24 \
  --symbols ETHUSDT,BNBUSDT,XRPUSDT \
  --max-pos 3 --case bounce_daily2
```

The walk-forward report writes `walk_forward_*.json` and `walk_forward_*.md`.
Treat a case with any rejected or negative window as not eligible for paper
runtime changes.

For LLM-assisted research review, create a research-only advisor artifact:

```bash
python backend/scripts/llm_research_advisor.py \
  backend/experiment_YYYYMMDD_HHMMSS_xxxxxx.json \
  --scoreboard-json backend/research_scoreboard_YYYYMMDD.json \
  --dry-run
```

The advisor may read allowlisted OpenAI-compatible provider keys such as
`NVIDIA_API_KEY` from an optional `--env-file`, but it never writes secrets,
never mutates paper settings, and never places or suggests executable orders.
Use it only to produce testable hypotheses, risk notes, and the next backtest
matrix. Its `llm_research_*.json` and `.md` outputs are local ignored artifacts.

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
- selection-adjusted bootstrap probability when multiple related variants were
  tested in one matrix;
- Monte Carlo drawdown;
- stress runs without maker assumptions or with worse fill assumptions;
- paper/live drift after enough real-time paper trades.

The selection-adjusted bootstrap gate is a conservative data-snooping guard.
It penalizes the raw bootstrap confidence by the number of completed variants
in a matrix, so the project does not promote the best-looking case merely
because many related cases were tried. It is an operational guardrail before
creating or applying a checkpoint, not a proof of edge.

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

The 2026-05-11 10-token no-DOGE follow-up was rejected as well. Its worst
30-day window returned about `-22.3%`, PF `0.45`, and only about `0.7%`
bootstrap positive-expectancy probability. Checkpoint `fdfe04eee10c` correctly
produced no paper runtime suggestion.

The 2026-05-11 guard-variant follow-up found one promising but fragile lead:
`bounce_time_shield` produced four positive windows on the current paper
universe, with about `+6.1%` average return and `3.5%` max drawdown, but only
`36` total trades. The same filter on the 10-token no-DOGE universe still had
one rejected window. Treat it as a research candidate only; the active paper
runtime remains `ETHUSDT, BNBUSDT, XRPUSDT` with `bounce_daily2` checkpoint
`81a0c75dbfbe`.

Checkpoint `81a0c75dbfbe` was regenerated with the expanded paper suggestion
schema and applied locally for paper observation. The apply path now syncs
`close_profitable_auto=false`, `daily_symbol_loss_limit=2`, blocked windows,
symbols, risk, and max positions into the paper SQLite settings DB. SharkTank
cooldown handling was also corrected so runtime defers near-cooldown batches
instead of discarding them. Paper-real is active with local simulated orders
only; real exchange ordering remains disabled.

The `bounce_adx30` follow-up produced local checkpoint
`checkpoint_20260511_130839_766203_44eeec561da1.json` from the recent
6-month paper-universe run. It intentionally has no `paper_env_suggestion`
because the ADX `30` threshold is not yet represented as a safe Paper runtime
setting. Treat it as research evidence only; do not apply it to Paper.

The 2026-05-13 2x LLM-assisted review was run through
`backend/scripts/llm_research_advisor.py` using a NVIDIA OpenAI-compatible
provider. It recommended paper observation only, mainly because the best 2x
case still had only `48` trades. Two deterministic follow-ups were tested:
`max_sl_pct=0.8` produced `NO_TRADES`, while removing `DOTUSDT` and `AAVEUSDT`
improved the same 3-month 2x window to about `+8.1%`, `43` trades, PF `1.68`,
and `4.7%` audit drawdown. That symbol-filter case was checkpointed locally as
`fcb527361c9a`, but it remains `PAPER_ONLY_SMALL_SAMPLE` and has no
`paper_env_suggestion` because the surrounding research-only flags are not yet
paper-runtime parity settings.

A deeper 2026-05-13 follow-up confirmed that the attractive 3-month symbol
filters are not yet robust. Removing more weak symbols improved the same
Feb-May 2026 window, with a 6-symbol long-only variant reaching about `+14.6%`
over 3 months. Walk-forward then exposed the risk: older windows from May 2025
through February 2026 were flat to negative and often had only 3 quality-filter
eligible symbols. The 1-year 6-symbol long-only check returned only about
`+6.4%` with `61` trades, PF `1.36`, and bootstrap positive-expectancy
probability below the `0.90` gate. The 1-year long/short variant had more
trades but was rejected, with PF `1.12` and bootstrap confidence around `0.74`.
Conclusion: do not promote the symbol-filtered variants to paper runtime; the
current mean-reversion family still needs either more reliable regime selection,
more trade coverage, or a genuinely different strategy family.

The 2026-05-13 regime-router / positive-skew follow-up kept the 12-symbol
research universe pre-registered before testing:
`BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT, DOGEUSDT, ADAUSDT, AVAXUSDT,
LINKUSDT, LTCUSDT, BCHUSDT, SUIUSDT`.

Two new research branches were tested on `2026-02-11` through `2026-05-11`,
with 2x leverage, no compounding, 1m monitoring, volume slippage, adversarial
pathing, and realistic fills:

- `donchian_breakout_trend_runner` strict breakout runner:
  checkpoint `e3fcc3e5dfdd`, `125` trades, `-12.44%` audit return, PF `0.60`,
  max DD `15.6%`, bootstrap positive-expectancy probability `0.8%`. Decision:
  `REJECT`.
- fixed-universe `rolling-adaptive-router` v1:
  checkpoint `44dd9291998f`, `151` trades, `-0.18%` audit return, PF `0.995`,
  max DD `5.71%`, bootstrap positive-expectancy probability `49.3%`. Decision:
  `REJECT`.
- fixed-universe `rolling-adaptive-router` v1 with `max_sl_pct=1.5`:
  checkpoint `1995063367a1`, `151` trades, `+0.33%` audit return, PF `1.01`,
  max DD `5.68%`, bootstrap positive-expectancy probability `52.15%`, and
  selection-adjusted bootstrap `4.3%`. Decision: `REJECT`.

The rolling router is a useful architecture improvement because it now uses only
a pre-registered universe instead of seeding from start/mid/end hindsight
rankings. It is still not an edge. The NVIDIA-backed LLM research advisor also
returned `reject`, mainly due to negative expectancy, PF below `1`, thin sample
size, and stop losses dominating gross PnL. No paper runtime setting should be
changed from these runs.

The 2026-05-13 momentum-pullback follow-up tested a new strategy family,
`adaptive_momentum_pullback`, on the same pre-registered 12-symbol research
universe. The hypothesis was to avoid raw breakout chasing: require
multi-horizon momentum first, then enter only after a pullback reclaims a short
EMA with capped ATR/swing risk.

Results:

- Feb-May 2026, long/short:
  checkpoint `85b67a08d316`, `107` trades, `+3.16%` audit return, PF `1.13`,
  max DD `7.72%`, bootstrap positive-expectancy probability `70.15%`.
  Decision: `REJECT` because sample size was thin and bootstrap confidence was
  below the `90%` gate.
- May 2025-May 2026, long/short:
  checkpoint `df103765ae99`, `291` trades, `-10.76%` audit return, PF `0.86`,
  max DD `18.77%`, bootstrap positive-expectancy probability `12.1%`.
  Decision: `REJECT`.
- May 2025-May 2026, long-only:
  checkpoint `93342bff7992`, `157` trades, `-9.66%` audit return, PF `0.78`,
  max DD `13.34%`, bootstrap positive-expectancy probability `8.6%`.
  Decision: `REJECT`.

Conclusion: the family found recent-regime signal, but it failed the longer
window and long-only did not fix the stop-out problem. Do not promote
`adaptive_momentum_pullback` to paper runtime. The next new-family work should
avoid another EMA threshold tweak and instead test a true regime-conditioned
model, e.g. only enabling trend continuation after a pre-declared volatility
compression / expansion state or after a portfolio-level breadth confirmation.

The 2026-05-13 volatility-squeeze follow-up implemented a new research family,
`volatility_squeeze_breakout`, on the same pre-registered 12-symbol universe.
The hypothesis was to enter only after volatility compression expands into a
trend-aligned breakout.

Results:

- Raw squeeze breakout was rejected immediately:
  `118` trades, `-22.43%` audit return, win rate `23.73%`, max DD `26.90%`.
  The strategy was also found to recompute full Bollinger bandwidth history per
  candle; this was fixed by limiting percentile computation to the required
  recent window.
- Adding a 96-bar structure breakout gate, stronger close-location filter,
  tighter ATR stop, and lower `2.2R` first target improved risk containment:
  `23` trades, `-2.88%` audit return, win rate `34.78%`, max DD `4.40%`.
  It still had negative expectancy.
- Adding ADX regime and `1.5x` volume confirmation produced the least bad
  filtered run:
  checkpoint `f6eb74e494d8`, `21` trades, `-2.01%` audit return, PF `0.60`,
  max DD `3.54%`, bootstrap positive-expectancy probability `14.35%`.
  Decision: `REJECT`.

Conclusion: volatility compression is not yet a profitable standalone entry in
this 15m Binance Futures setup. The MFE profile was too small for positive
skew at 2x, with zero trades reaching `7%` ROE in the best filtered run. Keep
the code as a research family/regime label, but do not update Paper runtime.

The 2026-05-13 liquidity-sweep follow-up implemented another standalone
research family, `liquidity_sweep_reversal`. The hypothesis was to fade failed
stop-run candles only after a swing sweep, reclaim close, wick rejection,
anchored-VWAP proximity, and capped ATR risk.

External research consulted for this round:

- Han/Kang/Ryu on cryptocurrency time-series and cross-sectional momentum under
  realistic assumptions: https://ssrn.com/abstract=4675565
- Osler on stop-loss order clusters and price cascades in currency markets:
  https://www.sciencedirect.com/science/article/abs/pii/S0261560604001147
- Bailey/Lopez de Prado on Deflated Sharpe and backtest selection bias:
  https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf

Results:

- Initial sweep-reversal defaults:
  `42` trades, `-7.69%` audit return, win rate `38.10%`, max DD `7.69%`.
  `BCHUSDT` and `XRPUSDT` were positive, but `ETHUSDT`, `BNBUSDT`, `LTCUSDT`,
  `AVAXUSDT`, and `SOLUSDT` dominated losses. Both long and short sides were
  negative.
- Tightening wick ratio, close-location reclaim, volume, and long-horizon
  momentum filters reduced trade count but did not create edge:
  checkpoint `93e1bf99979b`, `30` trades, `-6.32%` audit return, PF `0.29`,
  max DD `6.32%`, bootstrap positive-expectancy probability `0.05%`.
  Decision: `REJECT`.

Conclusion: standalone candle-pattern sweeps are not enough. The MFE profile
was too small after fees/slippage, and the average loss was larger than the
average win. Do not update Paper runtime from `liquidity_sweep_reversal`.
The next research step should move away from single-entry-pattern families and
treat regime routing / breadth selection as first-class hypotheses.

The 2026-05-13 volatility-managed momentum follow-up implemented
`volatility_managed_momentum`. The hypothesis was to keep time-series momentum
but only when short realized volatility is below the symbol's own longer
baseline, approximating volatility-managed portfolio research in the signal
layer.

External research consulted for this round:

- Han/Kang/Ryu on crypto time-series momentum under realistic costs and
  liquidation-aware assumptions: https://ssrn.com/abstract=4675565
- Moreira/Muir on volatility-managed portfolios:
  https://www.nber.org/papers/w22208
- Adaptive crypto trend-following / portfolio construction:
  https://arxiv.org/abs/2602.11708

Results:

- Fixed 12-symbol Feb-May 2026 long/short:
  `83` trades, `-5.39%` audit return, win rate `43.37%`, max DD `10.87%`.
  Several symbols were positive (`LTCUSDT`, `AVAXUSDT`, `XRPUSDT`, `ETHUSDT`),
  but losses in `BNBUSDT`, `LINKUSDT`, `BCHUSDT`, and `SUIUSDT` dominated.
- Long-only diagnostic improved the damage but still failed:
  checkpoint `2e06f458e1c8`, `46` trades, `-1.80%` audit return, PF `0.83`,
  max DD `5.14%`, bootstrap positive-expectancy probability `26.8%`.
  Decision: `REJECT`.

Conclusion: volatility-gating helps compared with raw long/short momentum, but
does not create a robust edge as a standalone entry family. Do not update Paper
runtime. The next step should be a portfolio-level breadth/risk-on gate and
true volatility-targeted sizing parity, not another per-symbol entry variant.

The 2026-05-13 portfolio-breadth follow-up implemented a research-only
`--breadth-risk-gate` in the backtest engine. The gate measures the current
pre-registered universe at signal time and blocks LONG unless enough symbols
are above their own EMA and have positive short momentum; it blocks SHORT under
the symmetric bearish condition. It uses only already-available candle history
and fails closed when coverage is too low.

External research consulted for this round:

- Market breadth as a timing signal:
  https://www.sciencedirect.com/science/article/pii/S0264999319312982
- Adaptive crypto trend-following and portfolio construction:
  https://arxiv.org/abs/2602.11708
- Volatility-managed exposure:
  https://www.nber.org/papers/w22208

Results on the fixed 12-symbol Feb-May 2026 2x research universe:

- Baseline without breadth gate:
  `127` trades, `+0.63%` audit return, PF `1.02`, max DD `9.11%`,
  bootstrap positive-expectancy probability `55.9%`. Decision: `REJECT`.
- Breadth gate EMA `96`, momentum `24`, threshold `0.55`:
  `43` trades, `+0.81%` audit return, PF `1.09`, max DD `2.18%`,
  bootstrap positive-expectancy probability `60.95%`.
- Breadth gate EMA `96`, momentum `24`, threshold `0.60`:
  checkpoint `checkpoint_20260513_032151_888602_e3a2763b1d8a.json`,
  `33` trades, `+3.14%` audit return, PF `1.665`, max DD `1.73%`,
  bootstrap positive-expectancy probability `89.55%`.
- Breadth gate EMA `192`, momentum `48`, threshold `0.60`:
  `58` trades, `+2.41%` audit return, PF `1.20`, max DD `3.02%`,
  bootstrap positive-expectancy probability `75.65%`.

The scoreboard file
`backend/research_scoreboard_breadth_gate_3m_20260513.md` ranks the threshold
`0.60` / `0.65` runs highest, but every case remains `FAIL` after sample-size
and selection-adjusted bootstrap gates. The best run is promising, not
promotion-ready: it has only `33` trades and selection-adjusted bootstrap is
only `37.3%` after six tested cases.

A follow-up OOS check on `2025-05-11` through `2026-05-11` found the failure
mode. With the same `min_symbols=9`, only `7` symbols passed quality filtering,
so the gate failed closed and generated no trades. The engine now records a
coverage warning when `breadth_min_symbols` exceeds the eligible universe.

Lowering only `breadth_min_symbols` to `6` allowed the 1-year test to trade,
but the edge did not hold:

- checkpoint `checkpoint_20260513_033344_320069_7cc9a108313d.json`,
  `134` trades, `-6.28%` audit return, PF `0.8119`, max DD `13.89%`,
  bootstrap positive-expectancy probability `12.15%`. Decision: `REJECT`.

Conclusion: breadth gating is a useful architecture direction because it
improves the recent 3-month baseline and exposes a better risk-on/risk-off
control surface. It is not yet a durable trading edge. No Paper runtime or
`.env` setting was changed.
