# Backtest Speed Plan

Hinto should keep one event-driven, live-like backtester as the source of truth.
Speed work should accelerate research without weakening execution realism.

## Current Timing Notes

Observed on a warm local cache:

- 30-day fixed-universe 5-case matrix: about `276s`
- 60-day 5-symbol candidate: about `40s`
- 120-day 5-symbol candidate: about `69s`
- 120-day 5-symbol baseline: about `103s`

The current engine is event-driven and uses 1m monitoring for SL/TP parity with
paper/live behavior. That realism is worth keeping for final acceptance tests.

## Safe Acceleration Path

1. Keep event-driven simulation as the final gate.
2. Use `scripts/run_research_matrix.py` to standardize experiment execution and
   prevent ad hoc result picking.
3. Preload and validate cache coverage before a matrix starts so missing 1m
   data fails early.
4. Add a fast pre-screen layer later:
   - vectorized pandas/NumPy signal generation for candidate timestamps;
   - optional Numba kernels for indicator sweeps;
   - no order/fill simplification in the final acceptance run.
5. Parallelize only independent cases after cache coverage is complete. Avoid
   parallel cache writes while historical data is being backfilled.

## Mathematical Gates

Research promotion requires more than PnL:

- positive expectancy in R-multiple terms;
- profit factor above `1.20` for a paper candidate and above `1.30` for
  promotion discussions;
- walk-forward windows should not depend on one isolated period;
- Monte Carlo shuffled drawdown must stay survivable;
- data coverage gaps must fail closed, especially when 1m intrabar monitoring
  is enabled.

The next worthwhile math upgrades are Deflated Sharpe Ratio and a simple
walk-forward/CSCV report. These should be reporting gates first, not optimizer
inputs, to avoid backtest overfitting.
