# Hinto - Frontend

Monitoring dashboard for the Hinto trading system.

**Status**: v4.0 UI, stable. Not actively developed — backend is the priority.

## Tech Stack

- React 18 + TypeScript
- Zustand (state management)
- Tauri v2 (desktop wrapper)
- TradingView Lightweight Charts
- Custom dark theme (Binance-style)

## Architecture

```
frontend/
  src/
    components/     # CandleChart, TokenIcon, SignalCard, StateIndicator
    hooks/          # useMarketData (WebSocket: 1m, 15m, 1h candles)
    stores/         # Zustand global state
    styles/         # Theme tokens (4px grid, dark palette)
    App.tsx         # Main layout
  src-tauri/        # Rust desktop config
```

## Development

```bash
npm install
npm run dev          # Web dev server
npm run tauri dev    # Desktop app
npm run tauri build  # Production build
```

Requires Node.js 18+ and Rust (stable) for Tauri.

## Theme

Dark mode with professional palette:
- Buy/Sell: `#0ECB81` / `#F6465D`
- Accent: `#F0B90B` (gold)
- Font: Inter, 4/8px grid spacing

## WebSocket

The `useMarketData` hook connects to the backend for real-time data:
- `candle` / `candle_15m` / `candle_1h` — price updates
- `signal` — trading signals
- `state_change` — position state transitions

Copyright 2026 Hinto contributors.
