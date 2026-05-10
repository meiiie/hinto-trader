# Hinto Trader Pro - Backend API

**FastAPI Backend with WebSocket Streaming**

---

## 🚀 Quick Start

```bash
# Start server
python -m uvicorn src.api.main:app --reload

# With custom port
python -m uvicorn src.api.main:app --reload --port 8080
```

**Base URL:** `http://127.0.0.1:8000`

---

## 📡 WebSocket Endpoints

### `/ws/stream/{symbol}`
Real-time market data stream.

**Events:**
| Type | Description |
|------|-------------|
| `candle` | 1m tick updates |
| `candle_15m` | 15m tick updates (SOTA) |
| `candle_1h` | 1h tick updates (SOTA) |
| `signal` | Trading signals |
| `state_change` | State machine transitions |

**Example:**
```javascript
const ws = new WebSocket('ws://127.0.0.1:8000/ws/stream/btcusdt');
ws.onmessage = (e) => {
  const data = JSON.parse(e.data);
  if (data.type === 'candle_15m') {
    console.log('15m tick:', data.close);
  }
};
```

---

## 🛠️ REST Endpoints

### System
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Health check |
| `/api/status` | GET | System status |

### Market
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/ws/history/{symbol}` | GET | Historical klines |
| `/market/positions` | GET | Open positions |

**Query Params for history:**
- `timeframe`: `1m`, `15m`, `1h` (default: `15m`)
- `limit`: Number of candles (default: `400`)

### Signals
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/signals` | GET | Active signals |
| `/signals/history` | GET | Signal history |

---

## 🏗️ Architecture

```
src/api/
├── main.py              # FastAPI app, lifespan
├── event_bus.py         # Event routing (SOTA EventBus)
├── websocket_manager.py # WebSocket connections
├── dependencies.py      # DI container
└── routers/
    ├── system.py        # Health endpoints
    ├── market.py        # Market data endpoints
    ├── signals.py       # Signal tracking
    └── trades.py        # Trade history
```

---

## 🔌 EventBus (SOTA Pattern)

Event-driven architecture for decoupled components:

```python
from src.api.event_bus import get_event_bus

event_bus = get_event_bus()

# Publish events
event_bus.publish_candle(candle_data, symbol='btcusdt')
event_bus.publish_candle_15m(candle_data, symbol='btcusdt')  # NEW
event_bus.publish_candle_1h(candle_data, symbol='btcusdt')   # NEW
event_bus.publish_signal(signal_data, symbol='btcusdt')
```

---

## 📝 License

MIT License
