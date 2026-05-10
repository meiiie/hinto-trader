#!/usr/bin/env python3
"""Fetch today's trades from Binance Futures API — SOURCE OF TRUTH"""
import requests, hmac, hashlib, time, os
from datetime import datetime, timezone, timedelta

# Read keys
key = secret = ''
for env_path in [os.path.expanduser('~/hinto-trader/.env'), '.env']:
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.startswith('BINANCE_API_KEY='):
                    key = line.strip().split('=', 1)[1]
                if line.startswith('BINANCE_API_SECRET='):
                    secret = line.strip().split('=', 1)[1]
        if key:
            break

UTC7 = timezone(timedelta(hours=7))
BASE = 'https://fapi.binance.com'

def sign(params):
    query = '&'.join(f'{k}={v}' for k, v in params.items())
    sig = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    return query + f'&signature={sig}'

def get_income(income_type=None, start_ms=None, limit=1000):
    params = {'timestamp': int(time.time() * 1000), 'limit': limit}
    if income_type:
        params['incomeType'] = income_type
    if start_ms:
        params['startTime'] = start_ms
    url = f'{BASE}/fapi/v1/income?{sign(params)}'
    r = requests.get(url, headers={'X-MBX-APIKEY': key})
    return r.json()

def get_trades(symbol, start_ms=None, limit=100):
    params = {'symbol': symbol, 'timestamp': int(time.time() * 1000), 'limit': limit}
    if start_ms:
        params['startTime'] = start_ms
    url = f'{BASE}/fapi/v1/userTrades?{sign(params)}'
    r = requests.get(url, headers={'X-MBX-APIKEY': key})
    return r.json()

# Get today start (UTC+7 00:00 = yesterday 17:00 UTC)
now_utc7 = datetime.now(UTC7)
today_start_utc7 = now_utc7.replace(hour=0, minute=0, second=0, microsecond=0)
start_ms = int(today_start_utc7.timestamp() * 1000)

print("=" * 70)
print(f"BINANCE API — TRADES TODAY ({today_start_utc7.strftime('%Y-%m-%d')} UTC+7)")
print("=" * 70)

# Get all REALIZED_PNL income entries (= closed trades)
incomes = get_income('REALIZED_PNL', start_ms)

# Group by symbol+time to reconstruct trades
trades = []
for inc in incomes:
    t = datetime.fromtimestamp(inc['time'] / 1000, UTC7)
    pnl = float(inc['income'])
    sym = inc['symbol']
    trades.append((t, sym, pnl))

# Also get FUNDING_FEE
funding = get_income('FUNDING_FEE', start_ms)
total_funding = sum(float(f['income']) for f in funding)

# Also get COMMISSION
commissions = get_income('COMMISSION', start_ms)
total_commission = sum(float(c['income']) for c in commissions)

# Print trades
print(f"\n{'#':>2s} {'Time':>8s} {'Symbol':<14s} {'PnL':>10s} {'Result':>6s}")
print("-" * 50)

total_pnl = 0
wins = 0
losses = 0

for i, (t, sym, pnl) in enumerate(trades):
    total_pnl += pnl
    result = 'WIN' if pnl > 0 else 'LOSS'
    if pnl > 0:
        wins += 1
    else:
        losses += 1
    print(f"{i+1:2d} {t.strftime('%H:%M')} {sym:<14s} ${pnl:>+9.4f} {result:>6s}")

total = wins + losses
wr = wins / total * 100 if total > 0 else 0

print("-" * 50)
print(f"\nTrades: {total} ({wins}W / {losses}L)")
print(f"Win Rate: {wr:.1f}%")
print(f"Realized PnL: ${total_pnl:.4f}")
print(f"Funding: ${total_funding:.4f}")
print(f"Commission: ${total_commission:.4f}")
print(f"NET PnL: ${total_pnl + total_funding + total_commission:.4f}")

# Current balance
params = {'timestamp': int(time.time() * 1000)}
url = f'{BASE}/fapi/v2/balance?{sign(params)}'
r = requests.get(url, headers={'X-MBX-APIKEY': key})
for b in r.json():
    if b['asset'] == 'USDT':
        print(f"\nWallet Balance: ${float(b['balance']):.2f}")
        print(f"Unrealized PnL: ${float(b['crossUnPnl']):.2f}")
        break
