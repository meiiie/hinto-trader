# Hinto Strategy Roadmap

Hinto should evolve as a research platform first and a live trading system
second. The goal is not to maximize headline win rate. The goal is to prove
positive expectancy after fees, slippage, funding, latency, and regime change.

## Current Assessment

The current strategy family is a liquidity-zone mean-reversion scalper:

- entries are generated near recent swing highs/lows;
- execution is local-first, then converted into exchange orders when triggered;
- risk is protected by local stop logic, hard cap, backup stop, and global halt;
- backtests model taker/maker fees, funding, slippage, and 1m monitoring.

This is useful infrastructure. It is not yet enough evidence for a durable
trading edge. The current payoff profile can become "many small wins, fewer
large losses" if it is promoted based on win rate alone.

## May 2026 Paper Audit

Four-day Binance Futures backtests were initially run with paper-like settings: 1m
monitoring, maker/taker fees, funding, max four positions, a historical 20x margin model,
1% account-risk cap, MTF trend filter, and volume-delta divergence filter.

Core 12-symbol result with the previous default (`AUTO_CLOSE` at `20% ROE`):

- net return: `-14.73%`
- trades: `37`
- win rate: `37.84%`
- average win/loss payoff: `0.79`
- main failure cluster: late-US entries around `03:00-05:00 UTC+7`

The issue was not only position sizing. Early auto-close compressed winners to
about 1R, while stop losses plus fees and candle-close slippage were larger than
1R. That made the payoff mathematically negative at the observed win rate.

Paper-default adjustments after the audit:

- disable early profitable auto-close by default;
- keep the threshold at `40% ROE` for experiments that explicitly enable it;
- add `03:00-05:00 UTC+7` to blocked windows;
- enable the ADX max filter at `40` for the mean-reversion runtime path.

After disabling auto-close, blocking `03:00-05:00`, and enabling the ADX max
filter, the same core set improved to roughly `-5.4%` over the four-day window,
with max drawdown down to about `9%`. This is better risk containment, not
proof of edge.

Thirty-day follow-up:

- baseline contract defaults: about `-7.4%`, profit factor `0.90`, longest loss
  streak `16`;
- direction blocking reduced losses to about `-3.1%`, but did not create a
  positive edge;
- BTC regime/impulse filtering made results worse on this sample;
- `--bounce-confirm --daily-symbol-loss-limit 2` was the best candidate, about
  `+1.0%` with profit factor `1.02` and about `10.8%` max drawdown.

This moves Hinto from "badly unsafe" toward "paper-observable", not toward live
money. The right interpretation is that bounce confirmation may reduce false
mean-reversion entries, while the remaining edge is too thin to trust.

Sixty-day follow-up of the same paper candidate improved to about `+6.4%` with
`135` trades and max drawdown around `14.1%`, but profit factor was only `1.07`.
That is still below the promotion threshold. Treat it as a monitored paper
candidate, not a live strategy.

Major-universe follow-up:

- `BTC, ETH, BNB, SOL, XRP` with `--bounce-confirm --daily-symbol-loss-limit 2`
  improved to about `+17.7%` over 120 days, PF `1.21`, `126` trades, max
  drawdown about `11.2%`;
- the same major universe without bounce confirmation was about `-22.9%`, PF
  `0.86`;
- removing MTF trend or delta-divergence filters from the broad candidate was
  strongly negative, so both filters remain part of the research contract.

After bootstrap expectancy checks, this is better described as the strongest
current paper experiment, not a candidate for promotion. Its bootstrap
positive-expectancy probability was about `85%`, below the `90%` research gate,
and the 5th-percentile bootstrapped return was still negative. The sample is
far below 1,000 out-of-sample trades and one 30-day walk-forward window was
blocked by missing 1m data coverage rather than forced through with incomplete
intrabar information.

Coverage also matters for interpreting the 120-day major-universe result:
`BTCUSDT` 1m cache coverage starts after the requested 120-day window, so the
engine reported one quality rejection. Until that data is backfilled, treat the
result as a four-symbol covered experiment rather than a fully covered five-
symbol study.

Experiment metadata now stores requested and eligible symbols separately, and
checkpoint paper suggestions use eligible symbols only.

Stress checks did not rescue the decision: taker-fee/no-maker and `0.02%`
fill-buffer stress variants stayed profitable in headline PnL, but their
bootstrap positive-expectancy probabilities were still only about `83-84%`.
That keeps the status at reject for promotion and no automatic paper config
change.

Leverage policy was tightened after the paper-real audit. Hinto's runtime
ceiling is now `2x`, and API/UI/checkpoint application paths clamp higher
values before they can reach paper or live execution. At `2x` on a `$100`
paper wallet with `max-pos 3`, each full slot is roughly `$33` margin and
about `$66` notional, while the `1%` risk cap still targets about `$1` account
risk before fees/slippage.

The 2x retest supports a narrow paper universe only:

- `ETHUSDT, BNBUSDT, XRPUSDT`, 30 days, `bounce_daily2`: about `+6.4%`,
  `22` trades, PF `1.89`, max drawdown about `3.6%`, still
  `PAPER_ONLY_SMALL_SAMPLE`;
- same narrow universe, 4 short walk-forward windows: `bounce_daily2` had
  `4/4` positive windows but only `13` trades, so the stability label remains
  `FRAGILE`;
- 10-token no-DOGE universe at 2x: rejected across short walk-forward and
  30-day checks; wider symbols added noise and worse drawdown.

Current interpretation: `2x + ETH/BNB/XRP + bounce confirmation + daily
symbol loss limit` is acceptable for paper observation, not live promotion.

Follow-up strategy research added a stricter mean-reversion regime branch:
`bounce_adx30`, which keeps the same bounce/daily-loss contract but blocks
signals when ADX is above `30` instead of the production `40`.

Summary of the latest checks:

- worst 6-month ETH window: `bounce_adx30` improved `bounce_daily2` from about
  `-3.3%` to about `+0.5%`, but only with `28` trades;
- full 2-year ETH window: `bounce_adx30` improved PF from about `1.12` to
  `1.27` and reduced drawdown from about `10.9%` to `7.6%`, but bootstrap
  positive expectancy was still below the `90%` gate;
- seven rolling 6-month ETH windows: `bounce_adx30` was positive in `5/7`
  windows versus `3/7` for `bounce_daily2`, but both remain rejected because
  at least one window is materially negative.

The ADX threshold sweep rejected the nearby alternatives:

- `bounce_adx25` was too strict and lost money in the worst 6-month window;
- `bounce_adx35` increased the trade count, but weakened PF and walk-forward
  stability versus ADX30;
- ADX plus time shields cut sample size too far to trust.

Scoreboards now report a selection-adjusted bootstrap probability. This is a
conservative multiple-test haircut: if several related variants are tested in
one matrix, the best-looking variant must still show a robust edge after the
selection penalty. On the 2-year ETH rerun, `bounce_adx30` had `87.6%` raw
bootstrap positive expectancy but only `62.8%` after the matrix haircut, so it
remains below the promotion gate.

Decision: `bounce_adx30` is a research candidate, not a Paper runtime update.
Do not lower the production ADX threshold until it survives walk-forward gates
and the runtime has an explicit, reviewed Paper setting for that threshold.

## Monthly Return Target Check

The `10%` monthly target was tested separately in
`docs/MONTHLY_TARGET_RESEARCH_2026_05_11.md`.

Result: not achieved.

Key findings:

- current Paper universe `ETH/BNB/XRP` with `bounce_daily2` averaged about
  `+3.5%` per tested month after repairing 1m coverage;
- adding `SOL` made `bounce_time_shield` stable across `6/6` monthly windows,
  but average return was about `+3.4%`, with only `76` trades;
- increasing `risk` from `1%` to `2%` did not change results because sizing was
  margin-slot constrained at `2x`;
- reducing `max-pos` concentrated capital and raised headline averages, but
  introduced rejected months;
- the current `trend_runner` positive-skew implementation was rejected across
  the same monthly windows.

Decision: keep the `10%` target as a research objective, not a Paper runtime
claim. The next useful work is a real observe-only regime router plus a new
trend-mode entry design, not another small threshold tweak.

## Research Tracks

### Track A: Mean-Reversion Scalper

Purpose: preserve the existing strategy as a benchmark and a paper-mode system.

Promotion criteria:

- at least 1,000 out-of-sample trades;
- profit factor above 1.30 after taker-fee stress;
- no single hour/session contributes more than 30% of total PnL;
- live/paper trade quality does not drift more than 10% from backtest
  expectancy after 500 paper trades.

Kill criteria:

- average loss remains larger than 1.8x average win after fees;
- net expectancy is positive only with maker assumptions;
- more than 40% of profit comes from one symbol cluster or one market regime;
- drawdown recovers only by increasing leverage or widening stops.

Current paper experiment:

```bash
python backend/run_backtest.py \
  --symbols ETHUSDT,BNBUSDT,XRPUSDT \
  --days 120 --balance 100 --risk 0.01 --leverage 2 \
  --max-pos 3 --no-compound --full-tp --maker-orders \
  --bounce-confirm --daily-symbol-loss-limit 2
```

Current research candidate:

```bash
python backend/scripts/run_walk_forward.py \
  --symbols ETHUSDT --balance 100 --risk 0.01 --leverage 2 \
  --max-pos 3 --case bounce_daily2 --case bounce_adx30 \
  --window 2024-05-11:2024-11-11 \
  --window 2024-08-11:2025-02-11 \
  --window 2024-11-11:2025-05-11 \
  --window 2025-02-11:2025-08-11 \
  --window 2025-05-11:2025-11-11 \
  --window 2025-08-11:2026-02-11 \
  --window 2025-11-11:2026-05-11
```

Keep the broad fixed universe as a benchmark, not the primary experiment. Do
not add symbol-side quarantine or broad hour exclusions to production based on
the current sample. They either reduced returns or looked like sample-specific
curve fitting.

### Track B: Positive-Skew Trend Runner

Purpose: test the opposite payoff shape: lose quickly when the setup fails,
but allow larger winners when a sweep/reclaim turns into continuation.

Initial hypothesis:

- wait for a liquidity sweep and reclaim;
- require higher-timeframe alignment;
- require volume delta or momentum confirmation;
- risk no more than 1R on invalidation;
- take partial profit near 1R only if needed for psychological/fee stability;
- trail the remaining position by ATR or structure.

Current implementation status:

- `--strategy-id liquidity_reclaim_trend_runner` is available for research
  backtests.
- `--strategy-id donchian_breakout_trend_runner` is available for research
  backtests as a stricter channel-breakout family. It requires higher timeframe
  alignment, a prior Donchian channel break, volume confirmation, a strong
  candle body, close near the candle extreme, bounded ATR%, and a capped stop.
- It rejects stops wider than `1.2%`, enters as a market-style continuation
  signal in the simulator, and sets the first target at `3R`.
- It tags signals with `research_exit_profile=trend_runner_3r`, disabling early
  auto-close so the backtest can measure a different payoff shape from the
  legacy scalper.
- The default remains `liquidity_sniper_mean_reversion`; live behavior does not
  change unless the operator explicitly chooses a different strategy id.

Example:

```bash
python backend/run_backtest.py \
  --strategy-id liquidity_reclaim_trend_runner \
  --top 40 --days 30 --balance 100 --leverage 2 \
  --max-pos 3 --no-compound --1m-monitoring --fill-buffer 0 \
  --max-sl-validation --max-sl-pct 1.2
```

Latest result:

- Strict Donchian v0 on the fixed 12-symbol Feb-May 2026 window was rejected:
  `-12.44%`, PF `0.60`, `125` trades, and only `0.8%` bootstrap
  positive-expectancy probability. The problem was not only win rate; stop-loss
  exits overwhelmed the few runner exits. Do not promote this strategy id to
  paper runtime.

Promotion criteria:

- profit factor above 1.20 even with win rate below 50%;
- average win at least 1.5x average loss;
- maximum adverse excursion remains bounded before stop;
- Monte Carlo reshuffle survives the worst 5% ordering without account failure.

Kill criteria:

- positive results depend on one crash/trend window;
- winners vanish after realistic exit slippage;
- entry selectivity becomes so strict that sample size is not meaningful.

### Track C: Regime Router

Purpose: route the same pre-registered universe through conservative research
presets instead of forcing a single strategy in every market condition.

Current implementation status:

- `--rolling-adaptive-router` now has a concrete
  `src.application.analysis.adaptive_regime_router` module.
- The rolling schedule no longer seeds symbols from start/mid/end rankings.
  Daily ranking is constrained to the universe known before the test starts.
- Router states can choose `shield`, guarded mean reversion, or guarded
  short-only branches with symbol-side blocks.
- Router exit profiles are research metadata only; they must not be consumed as
  a live contract until explicitly promoted.

Latest result:

- Fixed 12-symbol rolling router v1 on Feb-May 2026 was rejected but informative:
  `-0.18%`, PF `0.995`, `151` trades, max DD `5.71%`, and bootstrap
  positive-expectancy probability `49.3%`.
- A single stop-width sensitivity at `max_sl_pct=1.5` improved the same router
  to `+0.33%`, PF `1.01`, and bootstrap positive-expectancy probability
  `52.15%`, but it still failed promotion gates and the selection-adjusted
  bootstrap was only `4.3%`.
- The router reduced damage compared with raw breakout research, but it did not
  create positive expectancy. It remains research-only.

Next deterministic experiments:

- split the same window into strict time-based out-of-sample checks;
- run per-symbol robustness only as diagnostics, not as a promotion shortcut;
- stress maker assumptions with taker-fee and worse-fill variants;
- simplify filters before adding new parameters.

## Broker Expansion Policy

Do not wire live automation to a broker unless the broker has an official API
for both market data and order management.

Vietnamese broker channels such as MBS Mobile, S24, Plus24, or OTP-confirmed
order flows should be treated as research/alert-only unless an official API
contract is available. Browser automation or OTP bypassing is not acceptable for
an open-source trading project.

Venue implications:

- Binance Futures fits the current local-first execution model, but has funding,
  liquidation, and 24/7 volatility risk.
- Vietnamese cash equities have T+2 settlement, no normal short selling, market
  hours, price bands, and a very different liquidity model.
- Vietnamese derivatives may support intraday long/short logic, but the system
  still needs official trading/data APIs before live automation.

## Architecture Plan

Phase 1: Contracts and gates

- Define broker capabilities before adding adapters.
- Define strategy contracts before adding new strategy variants.
- Keep current runtime behavior unchanged while contracts are tested.

Phase 2: Strategy extraction

- Move `liquidity_sniper` logic behind a strategy interface.
- Add a `trend_runner` strategy as a separate implementation.
- Run both strategies through the same backtest execution simulator.

Phase 3: Experiment discipline

- Store every experiment with config hash, data window, symbols, fees, slippage,
  and code commit.
- Avoid parallel output collisions; backtest artifacts now use microsecond run
  stamps so trade logs, equity curves, and replay files remain tied together.
- `run_backtest.py` writes local `experiment_*.json` metadata for each run;
  these files are ignored by Git and should be copied into reports only when a
  specific result is promoted for discussion.
- `scripts/run_research_matrix.py` runs named strategy cases and records
  elapsed time plus audit output. Use it for ablations and symbol-universe
  comparisons before touching production defaults.
- `scripts/checkpoint_research.py` creates local checkpoints from experiment
  metadata. If the checkpoint decision is `REJECT`, paper runtime configuration
  must not change.
- Report R-multiple distribution, payoff skew, profit factor, max drawdown,
  regime contribution, and bootstrap/Monte Carlo robustness.
- Reject experiments that improve PnL only by increasing leverage.

Phase 4: Broker adapters

- Add adapters only when official broker capabilities are known.
- Every adapter must declare `BrokerCapabilities`.
- Live execution must be disabled when capability blockers exist.

## Operating Rule

No strategy is live-ready because a single backtest is profitable. A strategy is
only a candidate after it survives out-of-sample data, realistic execution cost,
paper/live drift checks, and a defined kill switch.
