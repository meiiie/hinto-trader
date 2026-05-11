# Hinto - Backend

Algorithmic trading engine for Binance Futures. Local-first execution with institutional-grade risk management.

Current strategy direction lives in [../docs/STRATEGY_ROADMAP.md](../docs/STRATEGY_ROADMAP.md). Historical commands below remain useful, but should not be read as the current live-ready preset without checking the roadmap and current validation results first.

## Architecture

```
Binance WebSocket -> SharedBinanceClient -> SignalGenerator (Liquidity Sniper)
                                                |
                                      SharkTankCoordinator (batch, rank, filter)
                                                |
                                      LiveTradingService (validate, execute, notify)
                                                |
                                     PositionMonitorService (SL/TP/trailing/breakeven)
                                                |
                                       Binance REST API (LIMIT+GTX / MARKET)
```

## Key Services

| Service | File | Role |
|---------|------|------|
| SignalGenerator | `application/signals/signal_generator.py` | Confluence scoring (LB=15, Prox=2.5%) + delta/MTF filters |
| SharkTankCoordinator | `application/services/shark_tank_coordinator.py` | Batch ranking + dead zone gate |
| LiveTradingService | `application/services/live_trading_service.py` | Execution + circuit breaker + Telegram |
| PositionMonitorService | `application/services/position_monitor_service.py` | 4-layer SL + AC20 + breakeven + trailing |
| CircuitBreaker | `application/risk_management/circuit_breaker.py` | Global halt (30% DD) + dead zones |
| LocalPosition | `domain/entities/local_position_tracker.py` | PnL tracking + signal_id persistence |
| DIContainer | `infrastructure/di_container.py` | Service wiring + config injection |

## Production Parameters

| Parameter | Value |
|-----------|-------|
| Leverage | 2x runtime ceiling |
| Max Positions | 4 |
| Symbols | Curated watchlist from DB/.env |
| Lookback | 15 |
| Proximity | 2.5% |
| Stop Loss | 1.2% (candle close) |
| Hard Cap | 2.0% (every tick) |
| AUTO_CLOSE | 20% ROE (1m candle close) |
| Take Profit | 2.0% price (+40% ROE) |
| Breakeven | 1.5R |
| Dead Zones | 06-08, 14-15, 18-21, 23-00 UTC+7 |

## Setup

Requires Python 3.11+.

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux
pip install -r requirements.txt
```

### Environment

Copy `.env.example` to `.env` and set:

- `BINANCE_API_KEY` / `BINANCE_API_SECRET`
- `ENV`: `paper`, `testnet`, or `live`
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`

For Binance-first validation without order risk, keep:

```env
ENV=paper
HINTO_PAPER_REAL=true
PAPER_LEVERAGE=2
```

This uses live Binance market data with local simulated fills. `/system/config`
will report `real_ordering_enabled=false`.

Settings priority: Database > ENV > code defaults. Use the API to override at runtime.

### Running

```bash
# Live/paper trading
python run_backend.py

# Backtest (use the same curated watchlist as live)
python run_backtest.py \
  --symbols "ETHUSDT,BNBUSDT,XRPUSDT" \
  --days 20 --balance 100 --leverage 2 --max-pos 3 --ttl 50 \
  --full-tp --close-profitable-auto --profitable-threshold-pct 20 \
  --portfolio-target-pct 10 --max-sl-validation --max-sl-pct 1.2 \
  --breakeven-r 1.5 --trailing-atr 4.0 --no-compound \
  --sl-on-close-only --hard-cap-pct 2.0 \
  --sniper-lookback 15 --sniper-proximity 2.5 \
  --1m-monitoring --fill-buffer 0 \
  --delta-divergence --mtf-trend --mtf-ema 20 \
  --blocked-windows "06:00-08:00,14:00-15:00,18:00-21:00,23:00-00:00" \
  --ac-threshold-exit
```

### Research Strategy Switch

Backtests default to the production-compatible mean-reversion sniper:
`--strategy-id liquidity_sniper_mean_reversion`.

To test the positive-skew reclaim runner without changing live defaults:

```bash
python run_backtest.py --strategy-id liquidity_reclaim_trend_runner --top 40 --days 30 --no-compound --1m-monitoring
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/settings` | Current settings |
| POST | `/settings` | Update settings (no restart needed) |
| GET | `/system/circuit-breaker/status` | CB + dead zone status |
| GET | `/positions` | Active positions |
| POST | `/signals/flush` | Flush pending signals |
| GET | `/health` | System health check |

## BroSubSoul Integration

The risk sentinel ([bro-subsoul](https://github.com/meiiie/bro-subsoul)) runs on GCP and monitors 12 data sources. It adjusts position limits and leverage via the `/settings` API based on real-time risk scoring.

## Code Organization

```
backend/
  backend/           # Source code (Clean Architecture)
    application/     # Services, signals, risk management
    domain/          # Entities, value objects
    infrastructure/  # Binance client, DB, Telegram, DI
  config/            # Configuration files
  scripts/           # Analysis & deployment scripts
  run_backend.py     # Server entrypoint
  run_backtest.py    # Backtest CLI
  run_live_trading.py # Direct trading entrypoint
```

Copyright 2026 Hinto contributors.
