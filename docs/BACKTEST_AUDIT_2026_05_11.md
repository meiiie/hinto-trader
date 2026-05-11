# Backtest Audit - 2026-05-11

This audit checks whether the current Binance-first paper strategy is ready to
continue paper trading with live-like constraints. It is not a live-trading
approval.

## Configuration

- window: last 4 days from 2026-05-11 runtime
- market: Binance USDT-M futures
- balance: `$100`
- risk cap: `1%` account risk per trade
- leverage: `2x` runtime ceiling
- max positions: `3` for the current paper-observation preset
- entries: limit sniper mean reversion
- exits: full TP at TP1, no early auto-close, 1m monitoring
- fees: maker entries/TP, taker stops
- filters: MTF EMA20, delta divergence, ADX max `40`
- blocked windows: `03:00-05:00,06:00-08:00,14:00-15:00,18:00-21:00,23:00-00:00` UTC+7

## Findings

### Core 12, old default

Previous paper-style defaults with auto-close at `20% ROE`:

- return: `-14.73%`
- trades: `37`
- win rate: `37.84%`
- average win/loss payoff: `0.79`
- problem: winners were cut too early while stop-loss exits were larger after
  fees and candle-close slippage.

### Core 12, contract defaults

After contract-default cleanup:

- return: about `-5.37%`
- trades: `28`
- win rate: `39.29%`
- max drawdown: about `9%`

This is still negative, but risk containment is materially better.

### Fixed 15, contract defaults

Run artifact: `backend/portfolio_backtest_20260511_105645.csv`

- return: `-1.08%`
- trades: `26`
- win rate: `42.31%`
- max drawdown: `7.59%`
- average win: `$1.56`
- average loss: `$-1.21`
- payoff: `1.29`
- expectancy: `$-0.04` per trade

Reason breakdown:

- `TAKE_PROFIT_1`: 10 trades, `$+17.06`
- `STOP_LOSS`: 12 trades, `$-14.85`
- `HARD_CAP`: 1 trade, `$-2.27`
- `END_OF_DATA`: 3 trades, `$-0.97`

Worst contributors in this window:

- `BCHUSDT`: `$-3.81`
- `XRPUSDT`: `$-1.75`
- `ETHUSDT`: `$-1.33`
- `AVAXUSDT`: `$-1.25`

Best contributors in this window:

- `DOTUSDT`: `$+2.94`
- `APTUSDT`: `$+2.01`
- `SUIUSDT`: `$+1.98`
- `SOLUSDT`: `$+1.53`

## Decision

Hinto is safer for continued paper-real observation after the cleanup, but it is
not ready for live money. The current strategy is near break-even on the wider
sample and still negative on the core sample. Keep paper trading only.

## 30-Day Robustness Check

Run family: fixed Binance futures universe, `$100` balance, `1%` account risk,
historical `20x` margin model, max four positions, no compounding, full TP,
maker entries and maker TP with taker stops.

Baseline contract defaults over 30 days:

- return: about `-7.4%`
- trades: `114`
- win rate: `36.84%`
- profit factor: `0.90`
- payoff: `1.55`
- longest loss streak: `16`
- max drawdown: about `25%`
- decision: reject for promotion

Risk-filter variants:

- daily symbol loss limit: still about `-7.8%`
- symbol-side quarantine: improved to about `-4.7%`, but still negative
- direction block: improved to about `-3.1%`, but still negative
- BTC regime + impulse filter: worse, about `-13.4%`
- bounce confirmation + daily symbol loss limit: about `+1.0%`, `69` trades,
  `39.13%` win rate, `1.02` profit factor, about `10.8%` drawdown

The best 30-day variant is not strong enough to promote. It has lower drawdown
and removes many low-quality fills, but `PF ~= 1.02` means the edge is too thin
to survive small execution drift, fee changes, data issues, or overfitting.

The same paper candidate over 60 days produced a positive return, but still did
not clear promotion gates:

- command profile: `--bounce-confirm --daily-symbol-loss-limit 2`
- return: about `+6.4%`
- trades: `135`
- win rate: `40.74%`
- profit factor: `1.07`
- payoff: `1.56`
- max drawdown: about `14.1%`
- longest loss streak: `7`
- decision: reject for promotion, continue paper-only research

This is an improvement over the baseline, but still not a robust edge. A profit
factor near `1.07` can disappear with small fee, spread, latency, or fill-quality
drift.

## Matrix and Walk-Forward Follow-Up

`backend/scripts/run_research_matrix.py` now runs reproducible strategy cases
through the existing event-driven backtester and attaches `research_audit`
output to each case.

Thirty-day fixed universe matrix:

- baseline contract: `-7.1%` audit return, PF `0.91`, reject
- `bounce-confirm + daily-symbol-loss-limit 2`: `+2.5%`, PF `1.05`, paper-only
- trend runner: `-7.1%`, PF `0.56`, reject
- bounce without MTF trend filter: `-19.6%`, reject
- bounce without delta divergence: `-12.5%`, reject

Interpretation: the MTF trend and delta-divergence filters are doing real risk
work. Removing either one materially worsens the strategy.

Symbol-universe test:

- 60-day major universe (`BTC, ETH, BNB, SOL, XRP`): `+20.1%`, PF `1.45`,
  only `78` trades, paper-only due to sample size
- 120-day major universe: `+17.7%`, PF `1.21`, `126` trades, initially
  interesting but rejected by stricter bootstrap gate
- 120-day same major universe without bounce filter: `-22.9%`, PF `0.86`,
  reject

Walk-forward checks on the major-universe candidate were positive on the
available 30-day windows:

- `2026-01-11 -> 2026-02-10`: `+5.0%`, PF `1.27`, `30` trades
- `2026-03-12 -> 2026-04-11`: `+12.8%`, PF `1.56`, `43` trades
- `2026-04-11 -> 2026-05-11`: `+8.9%`, PF `1.43`, `35` trades

The `2026-02-10 -> 2026-03-12` window was rejected by the backtest engine due
to a 1m cache coverage gap for `BNBUSDT`. This is the correct behavior:
paper-like backtests must fail closed when intrabar SL/TP data is incomplete.

Coverage note: an explicit cache check showed `BTCUSDT` 1m coverage starts at
`2026-01-23T17:00:00Z`, so 120-day runs starting `2026-01-10T17:00:00Z` do
not have full BTC 1m coverage. Those runs reported four eligible symbols and
one quality rejection. Treat them as covered `ETH/BNB/SOL/XRP` experiments
unless BTC 1m data is backfilled or the start date is moved later.

A later coverage-safe run from `2026-01-24 -> 2026-05-11` passed explicit 1m
and 15m coverage checks for all requested symbols, but the quality filter still
reported four eligible symbols and one rejection. Its result remained
statistically rejected: `+15.6%`, PF `1.21`, `112` trades, bootstrap
positive-expectancy probability about `83.5%`, 5th-percentile return about
`-10.6%`. Future metadata records both requested and eligible symbols so
checkpoints cannot confuse the two universes.

Removing the negative `SOLUSDT` leg from the same covered window produced a
small-sample paper experiment:

- universe: `ETHUSDT, BNBUSDT, XRPUSDT`
- return: `+20.6%`
- trades: `85`
- PF: `1.38`
- max drawdown: about `8.6%`
- bootstrap positive-expectancy probability: about `93-94%`
- decision: `PAPER_ONLY_SMALL_SAMPLE`

This is the first non-rejected checkpoint. It is suitable only for paper-mode
observation because the trade count is below `100`, and the 5th-percentile
bootstrapped return can still dip slightly negative.

## Runtime Parity Follow-Up

Follow-up validation on 2026-05-11 fixed two reproducibility issues:

- development config loading now skips `.env` directories and only accepts real
  `.env` files;
- `run_backtest.py` uses the same file-only `.env` rule and always writes
  trade, equity, and experiment artifacts under `backend/`, independent of the
  caller's current working directory.

The 4-day smoke run for `ETHUSDT, BNBUSDT, XRPUSDT` produced only `4` trades:
`+0.72%`, PF `1.27`, bootstrap positive-expectancy probability about `70%`,
and decision `PAPER_ONLY_SMALL_SAMPLE`. This is useful only as a runtime parity
smoke test, not strategy evidence.

The full covered-window rerun after the parity fix produced the same strategy
profile:

- checkpoint hash: `81a0c75dbfbe`
- universe: `ETHUSDT, BNBUSDT, XRPUSDT`
- return: `+20.61%`
- trades: `85`
- PF: `1.38`
- max drawdown: about `8.6%`
- bootstrap positive-expectancy probability: about `93.4%`
- bootstrap 5th-percentile return: about `-2.2%`
- decision: `PAPER_ONLY_SMALL_SAMPLE`

This supersedes the earlier local paper hashes `c1b97eeaa869` and
`33d4f1260aba`. The strategy configuration did not improve; the checkpoint was
refreshed because runtime and artifact reproducibility were fixed. It remains
paper-only. The research config hash is now based on strategy inputs and
excludes the tracing `git_commit`, so documentation commits do not invalidate
the paper checkpoint.

Current paper-observation checkpoint experiment:

```bash
python backend/run_backtest.py \
  --symbols ETHUSDT,BNBUSDT,XRPUSDT \
  --start 2026-01-24T00:00:00+00:00 --balance 100 --risk 0.01 --leverage 2 \
  --max-pos 3 --no-compound --full-tp --maker-orders \
  --bounce-confirm --daily-symbol-loss-limit 2
```

Checkpoint hash: `81a0c75dbfbe`.

The wider major-universe experiment remains rejected after adding bootstrap
expectancy checks:

- bootstrap positive-expectancy probability: about `85%`
- bootstrap 5th-percentile expectancy: about `-0.08` per trade
- bootstrap 5th-percentile return: about `-10.2%`
- decision: reject for promotion, keep as a paper experiment only

The sample is only `126` trades, below the long-run promotion rule. It is a
stronger experiment than the broad universe because it avoids weaker altcoin
behavior and retains the filters that survived ablation, but it is not yet
mathematically stable enough to call "good".

Stress follow-up on the same 120-day major-universe experiment:

- taker-fee/no-maker stress: `+15.7%`, PF `1.19`, bootstrap positive
  expectancy probability about `83%`, reject
- maker plus `0.02%` fill-buffer stress: `+16.1%`, PF `1.20`, bootstrap
  positive expectancy probability about `84%`, reject

These stress runs support the same decision: do not promote the wider
major-universe runtime configuration. A checkpoint was created for each stress
result, and both correctly produced no `paper_env_suggestion`.

Parallel-run note: `run_backtest.py` now writes output artifacts with
microsecond timestamps and reuses one run stamp for trade, equity, and replay
files. This prevents simultaneous research jobs from overwriting each other.
It also emits `experiment_*.json` metadata locally with argv, resolved args,
symbols, window, git commit, config hash, summary metrics, and artifact names.

## Top-50 Universe Follow-Up

An explicit `--top 50` backtest now overrides local paper `.env` fixed-symbol
settings. Before this fix, `USE_FIXED_SYMBOLS=true` could silently shrink a
top-N research run back to the paper watchlist, which made broad-universe tests
look cleaner than they really were.

Top-50 smoke command:

```bash
cd backend
python run_backtest.py \
  --top 50 --start 2026-05-07 --end 2026-05-11 \
  --balance 100 --risk 0.01 --leverage 2 --max-pos 3 \
  --no-compound --full-tp --maker-orders \
  --bounce-confirm --daily-symbol-loss-limit 2
```

Result:

- requested universe: `50` historical top-volume Binance futures symbols
- eligible after quality filter: `27`
- rejected by quality filter: `23`
- return: about `-6.5%`
- trades: `15`
- win rate: `26.67%`
- profit factor: about `0.50`
- max drawdown: about `6.5%`
- bootstrap positive-expectancy probability: about `9%`
- decision: `REJECT`

Interpretation: the current strategy does not improve by widening to raw top50.
The broad universe adds weak/noisy altcoin behavior and reduces fill quality.
This rejected checkpoint produced no paper runtime suggestion, so the current
paper-observation config remains the narrower `ETHUSDT, BNBUSDT, XRPUSDT`
checkpoint `81a0c75dbfbe`.

The run also exposed a speed issue: ranking-volume cache paths used to depend
on the caller's current working directory. The volume ranking cache is now
anchored under `backend/data/cache/volume_rankings`, matching the rest of the
historical data cache.

## Paper Universe Matrix Follow-Up

After adding research scoreboards, a 30-day matrix was run on the current paper
universe with paper-like sizing:

```bash
python backend/scripts/run_research_matrix.py \
  --start 2026-04-11 --end 2026-05-11 \
  --symbols ETHUSDT,BNBUSDT,XRPUSDT --max-pos 3 \
  --case baseline_contract --case bounce_daily2 --case trend_runner \
  --audit-runs 1000
```

Results:

- `baseline_contract`: `+14.61%`, `42` trades, PF `1.57`, max drawdown
  `7.88%`, bootstrap positive-expectancy probability `92.0%`;
- `bounce_daily2`: `+9.92%`, `22` trades, PF `1.87`, max drawdown `4.50%`,
  bootstrap positive-expectancy probability `91.7%`;
- `trend_runner`: `+0.74%`, `2` trades, PF `1.40`, max drawdown `1.81%`,
  bootstrap positive-expectancy probability `75.5%`.

All three cases remain `PAPER_ONLY_SMALL_SAMPLE` and fail the scoreboard sample
gate. The current bounce/daily-loss profile is still the cleaner paper
observation profile because it lowers drawdown and improves PF, even though the
looser baseline produced more return in this 30-day slice. The trend-runner
track did not produce enough trades on this narrow universe; it needs a
separate universe/regime study before it can replace the current paper track.

A local checkpoint was created for the `bounce_daily2` result with config hash
`d1fd48e9bdc1`, but paper runtime was not changed. The longer covered-window
checkpoint `81a0c75dbfbe` remains the active paper-observation checkpoint.

## Walk-Forward And 10-Token Follow-Up

The current paper universe was tested across four rolling-ish windows with
`max-pos 3` and the same `$100` / `1%` risk profile:

| Window | Baseline | Bounce daily2 | Trend runner |
| --- | ---: | ---: | ---: |
| `2026-01-24 -> 2026-02-24` | `-8.95%`, PF `0.74` | `+11.61%`, PF `1.92` | `+3.54%`, PF `1.37` |
| `2026-02-24 -> 2026-03-24` | `-13.05%`, PF `0.68` | `-4.67%`, PF `0.72` | `+2.97%`, PF `1.33` |
| `2026-03-24 -> 2026-04-24` | `+2.33%`, PF `1.07` | `+7.48%`, PF `1.46` | `-4.25%`, PF `0.00` |
| `2026-04-11 -> 2026-05-11` | `+14.61%`, PF `1.57` | `+9.92%`, PF `1.87` | `+0.74%`, PF `1.40` |

Interpretation: `bounce_daily2` is still the best paper-observation profile.
It wins three of four windows versus baseline on drawdown/quality and is the
least erratic of the three. The `2026-02-24 -> 2026-03-24` slice is the key
warning: the strategy can still lose money even on the narrow paper universe,
so it remains paper-only.

The first 10-token candidate was:

`BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT, DOGEUSDT, ADAUSDT, AVAXUSDT, LINKUSDT, LTCUSDT`

`DOGEUSDT` was rejected by the live-like backtester because its 1m cache had a
window coverage gap. The coverage checker now detects this case by verifying
the actual timestamps inside the requested window, not only the absolute cache
min/max.

The 10-token no-DOGE universe was then tested:

`BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT, ADAUSDT, AVAXUSDT, LINKUSDT, LTCUSDT, DOTUSDT`

`bounce_daily2` results:

| Window | Return | Trades | PF | Bootstrap positive expectancy |
| --- | ---: | ---: | ---: | ---: |
| `2026-01-24 -> 2026-02-24` | `+5.97%` | `41` | `1.24` | `75.8%` |
| `2026-02-24 -> 2026-03-24` | `-22.29%` | `50` | `0.45` | `0.7%` |
| `2026-03-24 -> 2026-04-24` | `+3.10%` | `50` | `1.10` | `62.4%` |
| `2026-04-11 -> 2026-05-11` | `+2.29%` | `43` | `1.08` | `60.6%` |

The 10-token universe is rejected for paper runtime. It adds more trades, but
the extra symbols dilute the edge and introduce a severe `-22.29%` month.
Worst contributors in the rejected month included `SOLUSDT`, `LINKUSDT`,
`DOTUSDT`, `XRPUSDT`, and `BTCUSDT`. A rejected checkpoint was created for the
bad 10-token run with config hash `fdfe04eee10c`; it produced no paper runtime
suggestion.

On the recent `2026-04-11 -> 2026-05-11` 10-token universe, extra strategy
checks also failed:

- baseline: about `-0.49%`, PF `0.99`, max drawdown `16.68%`, `REJECT`;
- trend-runner: about `-5.45%`, PF `0.53`, bootstrap positive-expectancy
  probability `15.2%`, `REJECT`.

Current decision: keep paper runtime on `ETHUSDT, BNBUSDT, XRPUSDT` and do not
expand to 10 symbols yet.

## Guard-Variant Follow-Up

The current paper universe was retested with additional guard variants across
the same four walk-forward windows:

- `bounce_symbol_side2`: adds symbol+side quarantine after repeated losses;
- `bounce_direction2`: blocks repeated losing trade direction;
- `bounce_time_shield`: blocks historically weak UTC+7 time windows;
- `bounce_btc_impulse`: blocks entries during sharp BTC impulse context.

Three of the four guard variants still failed because at least one window was
negative and rejected. `bounce_time_shield` was the only variant with all four
paper-universe windows positive:

| Case | Positive windows | Avg return | Min return | Max DD | Trades | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `bounce_time_shield` | `4/4` | `+6.12%` | `+1.88%` | `3.53%` | `36` | `FRAGILE` |
| `bounce_daily2` | `3/4` | `+6.08%` | `-4.67%` | `7.55%` | `97` | `REJECT` |
| `bounce_symbol_side2` | `3/4` | `+5.33%` | `-3.07%` | `6.90%` | `92` | `REJECT` |
| `bounce_btc_impulse` | `3/4` | `+5.07%` | `-5.64%` | `8.20%` | `83` | `REJECT` |

This is useful evidence that time-of-day risk matters, but it is not a paper
runtime upgrade. The time shield cut the sample to only `36` trades and is too
close to a data-derived filter to trust without broader confirmation.

The same `bounce_time_shield` check on the 10-token no-DOGE universe reduced
damage but still failed:

- positive windows: `3/4`
- average return: `+4.28%`
- worst window: `-3.30%`
- max drawdown: `6.00%`
- trades: `89`
- decision: `REJECT`

Interpretation: the filter is a promising research lead, not a validated edge.
Do not apply it to paper runtime until it passes wider out-of-sample checks
with enough trades and without a rejected window.

## Paper Runtime Activation Follow-Up

Paper runtime was rechecked after the guard-variant research. Two parity issues
were fixed before continuing paper observation:

- checkpoint application now syncs runtime controls beyond symbols/risk/slots:
  `close_profitable_auto`, `daily_symbol_loss_limit`, blocked windows, and the
  paper checkpoint hash;
- SharkTank no longer discards a signal batch when the 15-minute cooldown is
  short by a few seconds. It defers the batch and processes it when cooldown
  expires, preventing paper mode from silently missing the next candle.

The active paper runtime was then refreshed from checkpoint `81a0c75dbfbe`
without resetting the paper wallet:

- execution mode: `paper_real`
- real exchange ordering: `false`
- balance: `$100`
- symbols: `BNBUSDT, ETHUSDT, XRPUSDT`
- risk: `1%`
- max positions: `3`
- close-profitable auto: `false`
- daily symbol loss limit: `2`
- pending paper orders observed: `3`

The pending orders are local simulated orders only. They use live Binance
market data for price movement, but `/system/config.real_ordering_enabled`
remains `false`.

## 2x Leverage Retest

Runtime leverage is now capped at `2x` across Paper settings, Live start
requests, API backtest requests, frontend Settings, and checkpoint application.
Higher leverage can no longer be selected through the app UI or normal runtime
API paths.

Short walk-forward, `ETHUSDT, BNBUSDT, XRPUSDT`, `$100`, `1%` risk, `2x`,
`max-pos 3`:

- `bounce_daily2`: `4/4` positive windows, average return about `+1.0%`, max
  drawdown about `1.5%`, only `13` trades, decision `FRAGILE`;
- `baseline_contract`: one rejected negative window, decision `REJECT`;
- `trend_runner`: rejected due weak/negative windows.

The same `2x` short walk-forward on the 10-token no-DOGE universe rejected all
cases. The best case still had a negative window around `-3.5%`.

Thirty-day recent-window matrix, `2026-04-11 -> 2026-05-11`:

- narrow `ETH/BNB/XRP`, `bounce_daily2`: about `+6.4%`, `22` trades, PF
  `1.89`, max drawdown about `3.6%`, bootstrap positive-expectancy probability
  about `91.7%`, decision `PAPER_ONLY_SMALL_SAMPLE`;
- narrow `ETH/BNB/XRP`, `baseline_contract`: about `+9.2%`, `42` trades, PF
  `1.60`, max drawdown about `5.5%`, decision `PAPER_ONLY_SMALL_SAMPLE`;
- 10-token no-DOGE universe, `bounce_daily2`: about `-1.3%`, `44` trades,
  PF `0.95`, max drawdown about `9.5%`, decision `REJECT`;
- 10-token no-DOGE universe, `bounce_time_shield`: about `+4.1%`, `20`
  trades, PF `1.60`, but still `PAPER_ONLY_SMALL_SAMPLE` and too filtered to
  promote.

Decision: keep Paper on `2x`, `$100`, `max-pos 3`, and the narrow
`ETHUSDT, BNBUSDT, XRPUSDT` universe. Prefer `bounce_daily2` for paper
observation because it has lower drawdown than baseline and survived the
short-window stability check better, even though the 30-day baseline slice had
higher headline return. Do not expand to 10 tokens yet.

## Next Research Steps

- collect at least 200 paper/backtest-comparable trades before promoting any
  setting;
- keep the best current candidate as paper-only:
  `--bounce-confirm --daily-symbol-loss-limit 2`;
- use the generated `experiment_*.json` metadata to compare future runs by
  config hash instead of screenshots or memory;
- create `backend/research_checkpoints/checkpoint_*.json` for notable results;
  if a checkpoint decision is `REJECT`, paper runtime config must not change;
- add per-symbol quarantine rules only after repeated out-of-sample evidence;
- test a regime router that allows mean reversion only in range conditions;
- continue the `liquidity_reclaim_trend_runner` track, but improve selectivity
  before considering it as a replacement;
- report R-multiple distribution and expectancy, not only win rate.
