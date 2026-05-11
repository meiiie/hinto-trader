# Monthly Target Research - 2026-05-11

Goal: investigate whether Hinto can credibly target about `10%` monthly return
on a `$100` paper account while keeping `2x` leverage.

This is a research target, not a runtime promise. A monthly result only counts
if it survives clean data coverage, realistic 1m monitoring, fees, drawdown
gates, walk-forward windows, and anti-overfitting checks.

## External Research Principles

The research direction is constrained by four principles:

- avoid selecting the prettiest backtest after trying many variants;
- prefer robust walk-forward evidence over one strong month;
- reduce exposure when realized volatility/regime risk is hostile;
- size positions from survivability first, not from a desired PnL number.

These principles align with backtest-overfitting work by Bailey, Borwein,
Lopez de Prado, and Zhu; volatility-managed portfolio research by Moreira and
Muir; long-horizon trend-following evidence from Hurst, Ooi, and Pedersen; and
Kelly-style position sizing discipline.

## Data Repair

The first 6-month monthly walk-forward found one invalid window caused by a
`BNBUSDT` `1m` cache gap around `2026-03-07`. The backtester correctly failed
closed. The affected cache was rebuilt from Binance, and `XRPUSDT` early `1m`
coverage was backfilled. A strict coverage check then passed for:

`ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT`

from `2025-11-11` through `2026-05-11` on both `15m` and `1m`.

## Current Paper Universe

Universe: `ETHUSDT, BNBUSDT, XRPUSDT`

Window set:

- `2025-11-11 -> 2025-12-11`
- `2025-12-11 -> 2026-01-11`
- `2026-01-11 -> 2026-02-11`
- `2026-02-11 -> 2026-03-11`
- `2026-03-11 -> 2026-04-11`
- `2026-04-11 -> 2026-05-11`

After replacing the invalid February/March window with a clean rerun:

| Case | Monthly Returns | Avg | Worst | Decision |
| --- | --- | ---: | ---: | --- |
| `bounce_daily2` | `+0.15`, `+6.46`, `+4.43`, `+0.99`, `+2.71`, `+6.41` | `+3.53%` | `+0.15%` | Paper-observe only |
| `bounce_time_shield` | `+3.91`, `-0.55`, `+3.22`, `+3.60`, `+1.25`, `+6.76` | `+3.03%` | `-0.55%` | Fragile |
| `bounce_adx30` | `+2.42`, `+4.09`, `+2.86`, `-3.33`, `+2.48`, `+1.08` | `+1.60%` | `-3.33%` | Reject |
| `baseline_contract` | `-11.15`, `+5.12`, `-0.49`, `-15.55`, `-2.08`, `+9.21` | `-2.49%` | `-15.55%` | Reject |

Interpretation: the current paper universe does not support a credible
`10%` monthly target. The nearest headline month was baseline `+9.21%`, but
the same baseline produced deep negative months, so it is not acceptable.

## Expanded Clean Universe

Universe: `ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT`

Artifact: `walk_forward_20260511_145057_892149.md`

| Case | Positive Windows | Avg Return | Worst Return | Max DD | Trades | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `bounce_time_shield` | `6/6` | `+3.41%` | `+0.67%` | `2.93%` | `76` | `FRAGILE` |
| `bounce_daily2` | `4/6` | `+3.88%` | `-2.63%` | `7.70%` | `181` | `REJECT` |
| `baseline_contract` | `2/6` | `-3.86%` | `-15.19%` | `16.60%` | `344` | `REJECT` |

Best single month in this run:

- `bounce_daily2`: `+9.67%`, still below `10%` and not stable;
- `bounce_time_shield`: `+8.33%`, stable but too few trades.

Interpretation: adding `SOLUSDT` improves opportunity count, but does not
produce a robust `10%` monthly system. `bounce_time_shield` is the best
defensive lead because it avoided negative months, but the sample is too small
and the average return is closer to `3-4%` monthly.

## Risk And Slot Tests

`risk=2%` with `2x` produced the same results as `risk=1%`. That means the
current paper-like sizing is constrained by margin slot allocation, not by the
risk-percent input.

Slot concentration tests on the expanded clean universe:

| Config | Case | Avg Return | Worst Return | Decision |
| --- | --- | ---: | ---: | --- |
| `max-pos 3` | `bounce_time_shield` | `+3.41%` | `+0.67%` | `FRAGILE` |
| `max-pos 2` | `bounce_time_shield` | `+4.72%` | `-0.44%` | `REJECT` |
| `max-pos 1` | `bounce_time_shield` | `+4.48%` | `-1.13%` | `REJECT` |

Interpretation: concentrating capital can raise average return slightly, but
it creates rejected months and does not reach `10%`. Keep `max-pos 3` for
paper observation.

## Positive-Skew Track

Artifact: `walk_forward_20260511_151300_771721.md`

The existing `liquidity_reclaim_trend_runner` was retested on the expanded
clean universe:

| Case | Positive Windows | Avg Return | Worst Return | Max DD | Trades | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `trend_runner` | `1/6` | `-1.90%` | `-6.36%` | `8.77%` | `85` | `REJECT` |
| `trend_runner_daily2` | `1/6` | `-1.90%` | `-6.36%` | `8.77%` | `85` | `REJECT` |

Interpretation: the current trend-runner implementation is not a solution to
the monthly target. A positive-skew track still makes sense mathematically, but
it needs a new entry/regime design rather than reuse of the current reclaim
logic.

## Decision

The `10%` monthly target is not achieved.

Current honest expectation for the best available paper-observation family is
closer to `3-5%` average monthly in the tested recent regime, with sample-size
and overfitting warnings still active. Pushing to `10%` by concentrating slots
or selecting one high-return month increases fragility faster than it improves
edge.

Do not update Paper runtime from these tests.

## Next Research Direction

The next worthwhile work is not another threshold sweep. It should be:

1. Build an observe-only regime router that chooses between:
   - no-trade shield;
   - mean-reversion time-shield mode;
   - a redesigned positive-skew trend mode.
2. Add monthly target gates to reports:
   - average monthly return;
   - percentage of months above `10%`;
   - worst monthly return;
   - return-to-drawdown ratio;
   - minimum trades per month.
3. Research a new trend mode around breakout continuation after volatility
   compression, not only sweep/reclaim candles.
4. Keep Paper on conservative settings until the router survives at least
   12 rolling monthly windows and 200-300 comparable trades.
