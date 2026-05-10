# Architecture Audit - 2026-05-10

This note captures the current strategy and architecture read before pushing Hinto closer to open collaboration.

## Strategic Verdict

Stay Binance-first. MBS should remain a later product track because the current edge, data model, execution model, and backtest parity work are all Binance Futures-specific.

The project has real potential, but not because the original scalper can be blindly scaled. The strongest direction is now:

- keep the default liquidity-sniper mean-reversion contract as a controlled baseline
- keep adaptive routing shield-first, not trade-everything
- continue the positive-skew `liquidity_reclaim_trend_runner` as research-only until it survives out-of-sample windows and paper/live-market replay
- validate paper/testnet before any live money changes

## Algorithm Read

The old "win often, lose larger" shape is fragile because it depends on high win rate, low fees, and tight execution parity. It can work only in carefully selected regimes.

The newer research direction is healthier:

- router v7 blocks untrusted regimes instead of forcing trades
- guarded bearish branches use side restrictions and toxic-short exclusions
- `max_same_direction=3` is a useful concentration guard on currently trusted trade branches
- the trend runner has a better payoff thesis, with capped stop and 3R first target

Current limitation: the router is still not a live execution gate. The March research docs already show false negatives from session-start routing, so the next meaningful improvement is rolling/daily regime refresh with dynamic breadth and universe refresh.

## Clean Architecture Findings

Clean enough to continue research, not clean enough to call "done".

Improved in this pass:

- runtime environment normalization moved into `src.config.runtime`
- API dependencies and DI container now share the same `get_trading_db_path()` contract
- `/system/config` and mode switching now report the same DB path that runtime services use

Remaining debt:

- `src/config.py` and `src/config/` still coexist; new runtime helpers are isolated, but a later cleanup should merge the legacy module/package split
- `LiveTradingService` is still too large and owns execution, position lifecycle, order cleanup, reconciliation, and notifications
- architecture property tests document existing application-to-infrastructure violations; those should be burned down service by service, not by a broad import rewrite
- research exit profiles are attached to signals and router states, but live execution should not consume them until the contract is explicitly promoted

## Recommended Next Steps

1. Keep live integration observe-first for router state.
2. Add rolling router v1 with dynamic breadth/universe refresh before promoting any router to execution control.
3. Split `LiveTradingService` along real ownership boundaries: execution adapter, close pipeline, risk gate, reconciliation, and notification publisher.
4. Add a paper-real validation gate that uses live market data but blocks real order placement by construction.
5. Treat every algorithm promotion as a contract change: backtest, replay/paper, testnet, then small live.
