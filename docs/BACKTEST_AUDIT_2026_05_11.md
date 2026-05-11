# Backtest Audit - 2026-05-11

This audit checks whether the current Binance-first paper strategy is ready to
continue paper trading with live-like constraints. It is not a live-trading
approval.

## Configuration

- window: last 4 days from 2026-05-11 runtime
- market: Binance USDT-M futures
- balance: `$100`
- risk cap: `1%` account risk per trade
- leverage: `20x` margin model
- max positions: `4`
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
`20x` margin model, max four positions, no compounding, full TP, maker entries
and maker TP with taker stops.

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

Parallel-run note: `run_backtest.py` now writes output artifacts with
microsecond timestamps and reuses one run stamp for trade, equity, and replay
files. This prevents simultaneous research jobs from overwriting each other.

## Next Research Steps

- collect at least 200 paper/backtest-comparable trades before promoting any
  setting;
- keep the best current candidate as paper-only:
  `--bounce-confirm --daily-symbol-loss-limit 2`;
- add per-symbol quarantine rules only after repeated out-of-sample evidence;
- test a regime router that allows mean reversion only in range conditions;
- continue the `liquidity_reclaim_trend_runner` track, but improve selectivity
  before considering it as a replacement;
- report R-multiple distribution and expectancy, not only win rate.
