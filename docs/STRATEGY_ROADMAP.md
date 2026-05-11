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

Four-day Binance Futures backtests were run with paper-like settings: 1m
monitoring, maker/taker fees, funding, max four positions, 20x margin model,
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

Current paper candidate:

```bash
python backend/run_backtest.py \
  --top 30 --days 30 --balance 100 --risk 0.01 --leverage 20 \
  --max-pos 4 --no-compound --full-tp --maker-orders \
  --bounce-confirm --daily-symbol-loss-limit 2
```

Do not add symbol-side quarantine or broad hour exclusions to production based
on the current 30-day sample. They either reduced returns or looked like
sample-specific curve fitting.

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
  --top 40 --days 30 --balance 50 --leverage 20 \
  --max-pos 4 --no-compound --1m-monitoring --fill-buffer 0 \
  --max-sl-validation --max-sl-pct 1.2
```

Promotion criteria:

- profit factor above 1.20 even with win rate below 50%;
- average win at least 1.5x average loss;
- maximum adverse excursion remains bounded before stop;
- Monte Carlo reshuffle survives the worst 5% ordering without account failure.

Kill criteria:

- positive results depend on one crash/trend window;
- winners vanish after realistic exit slippage;
- entry selectivity becomes so strict that sample size is not meaningful.

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
