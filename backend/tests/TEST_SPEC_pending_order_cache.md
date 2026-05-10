# Test Specification: Pending Order Local Caching

## Module Under Test
- `LiveTradingService._cached_open_orders` (local order cache)
- `LiveTradingService._sync_local_cache()` (startup sync)
- `LiveTradingService.update_cached_order()` (WebSocket update)
- `LiveTradingService.get_portfolio()` (uses cache)

---

## Test Environment Requirements

| Requirement | Value |
|-------------|-------|
| Mode | TESTNET (`ENV=testnet` in `.env`) |
| API Keys | `BINANCE_TESTNET_API_KEY` / `SECRET` |
| Backend | `python run_backend.py` |
| Frontend | `npm run dev` (optional) |

---

## Test Cases

### TC-001: Startup Cache Sync
**Objective**: Verify `_sync_local_cache()` populates local cache on startup.

**Preconditions**:
1. Have at least 1 open LIMIT order on Testnet Binance
2. Backend not running

**Steps**:
1. Start backend: `python run_backend.py`
2. Check logs for: `📦 Syncing local cache from Binance...`
3. Check logs for: `📦 Local cache synced: X orders, Y positions`

**Expected**:
- Log shows correct count of orders matching Binance Testnet UI
- No errors in startup

---

### TC-002: Portfolio Response Uses Cache
**Objective**: Verify `get_portfolio()` reads from local cache, NOT Binance API.

**Preconditions**:
1. Backend running (from TC-001)

**Steps**:
1. Call endpoint: `GET http://localhost:8000/trades/portfolio`
2. Check response time
3. Check backend logs

**Expected**:
- Response time < 100ms (cache hit)
- Logs show: `📦 Using cached orders: X orders`
- Logs do NOT show any Binance API calls for orders

---

### TC-003: WebSocket Order Create Updates Cache
**Objective**: Verify new order via WebSocket updates local cache in real-time.

**Preconditions**:
1. Backend running
2. UserDataStream connected (check logs: `✅ Connected to User Data Stream`)

**Steps**:
1. Place a new LIMIT order via Binance Testnet UI or API
2. Check backend logs for: `📝 ORDER_UPDATE | SYMBOL SIDE LIMIT → NEW`
3. Check logs for: `📦 Cache: updated order XXXXX`
4. Call endpoint: `GET http://localhost:8000/trades/portfolio`
5. Verify new order appears in `pending_orders` array

**Expected**:
- WebSocket event received within 1-2 seconds
- Cache updated automatically
- Portfolio endpoint returns new order without restart

---

### TC-004: WebSocket Order Fill Updates Cache
**Objective**: Verify filled order is removed from cache.

**Preconditions**:
1. Backend running
2. Have at least 1 open LIMIT order

**Steps**:
1. Wait for order to fill (or place Market order at limit price to trigger)
2. Check backend logs for: `📝 ORDER_UPDATE | SYMBOL SIDE LIMIT → FILLED`
3. Check logs for: `📦 Cache: removed order XXXXX`
4. Call endpoint: `GET http://localhost:8000/trades/portfolio`

**Expected**:
- Order removed from `pending_orders` array
- Position appears in `open_positions` array (if not closed immediately)

---

### TC-005: WebSocket Order Cancel Updates Cache
**Objective**: Verify cancelled order is removed from cache.

**Steps**:
1. Create a LIMIT order
2. Cancel order via Binance Testnet UI
3. Check backend logs for: `📝 ORDER_UPDATE | SYMBOL SIDE LIMIT → CANCELED`
4. Check logs for: `📦 Cache: removed order XXXXX`
5. Call endpoint: `GET http://localhost:8000/trades/portfolio`

**Expected**:
- Order removed from `pending_orders` array immediately
- No stale data in portfolio response

---

### TC-006: Performance Benchmark
**Objective**: Verify 50s → <100ms improvement in portfolio response.

**Steps**:
1. Run backend for 5-10 minutes with app open
2. Press Ctrl+C to stop backend
3. Open latest session report: `backend/logs/session_report_YYYYMMDD_HHMMSS.md`
4. Check `/trades/portfolio` metrics

**Expected**:
| Metric | Before Fix | After Fix (Expected) |
|--------|------------|---------------------|
| Avg latency | 4512ms | **<100ms** |
| Max latency | 50609ms | **<500ms** |
| Calls | 84 (10min) | Similar or lower |

---

### TC-007: Cache Fallback on Startup Failure
**Objective**: Verify graceful degradation if cache sync fails.

**Steps**:
1. Temporarily break API key (rename in `.env`)
2. Start backend
3. Check logs for: `Failed to sync local cache: ...`
4. Call endpoint: `GET http://localhost:8000/trades/portfolio`

**Expected**:
- Logs show warning but no crash
- Portfolio falls back to API call (slow but works)
- Logs show: `📡 Cache not initialized, using API for orders`

---

## Test Data Preparation

### Create Test Orders (via Python Script)
```python
# Run in backend directory with venv activated
from src.infrastructure.api.binance_futures_client import BinanceFuturesClient

client = BinanceFuturesClient(use_testnet=True)

# Create a LIMIT order below current price (won't fill immediately)
current_price = client.get_ticker_price("BTCUSDT")
limit_price = round(current_price * 0.95, 0)  # 5% below

order = client.place_order(
    symbol="BTCUSDT",
    side="BUY",
    order_type="LIMIT",
    quantity=0.001,
    price=limit_price,
    time_in_force="GTC"
)
print(f"Created order: {order}")
```

### Cleanup Test Orders
```python
client.cancel_all_orders("BTCUSDT")
```

---

## Success Criteria

| Criteria | Pass Condition |
|----------|----------------|
| Cache syncs on startup | ✅ Orders match Binance UI |
| WebSocket updates cache | ✅ Real-time sync < 2s |
| Portfolio uses cache | ✅ Response < 100ms |
| No API calls for orders | ✅ Logs confirm cache usage |
| Graceful fallback | ✅ System works if cache fails |

---

## Notes for QA Team

1. **WebSocket Connection**: Ensure `UserDataStream` is connected (check startup logs)
2. **Testnet Limitations**: Testnet may have intermittent issues - retry if connection drops
3. **Session Report**: Always check `backend/logs/session_report_*.md` for detailed metrics
4. **Log Level**: Set `LOG_LEVEL=DEBUG` in `.env` for verbose cache logs
