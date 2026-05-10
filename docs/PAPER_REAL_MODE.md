# Paper-Real Mode

Paper-real is the recommended Binance-first operating mode before live trading.

It is intentionally live-like:

- market data comes from Binance production streams
- signals, pending orders, PnL, fees, cooldowns, and portfolio state update in the dashboard
- the UI labels the session as `PAPER-REAL MODE`

It is intentionally not live:

- `ENV=paper` is the hard safety switch
- Binance order clients are not initialized for execution
- fills are handled by `PaperTradingService`
- `/system/config` reports `real_ordering_enabled=false`
- `LiveTradingService.execute_signal()` rejects paper-mode execution attempts

## Local Configuration

```env
ENV=paper
HINTO_PAPER_REAL=true
```

Use this while validating Binance strategy behavior with live market conditions.
Move to `ENV=testnet` only when you want Binance testnet order routing. Move to
`ENV=live` only after paper and testnet evidence is strong enough for real money.

## Operator Checklist

Before live mode:

- run `scripts/secret-scan.ps1`
- confirm `/system/config` shows the intended environment
- confirm `/system/config.real_ordering_enabled` is `false` for paper-real
- export and review paper-real trade history
- compare paper-real behavior with backtest and Binance testnet fills
