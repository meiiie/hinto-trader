#!/usr/bin/env python3
"""Full LIVE analysis from Binance API — Feb 18 onwards (system start)"""
import requests, hmac, hashlib, time, os, json
from datetime import datetime, timezone, timedelta
from collections import defaultdict

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
D = '$'

def sign(params):
    query = '&'.join(f'{k}={v}' for k, v in params.items())
    sig = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    return query + f'&signature={sig}'

def get_income(income_type=None, start_ms=None, end_ms=None, limit=1000):
    params = {'timestamp': int(time.time() * 1000), 'limit': limit}
    if income_type:
        params['incomeType'] = income_type
    if start_ms:
        params['startTime'] = start_ms
    if end_ms:
        params['endTime'] = end_ms
    url = f'{BASE}/fapi/v1/income?{sign(params)}'
    r = requests.get(url, headers={'X-MBX-APIKEY': key})
    return r.json()

# System start: Feb 18 04:00 UTC+7 (v6.5.10 deploy)
sys_start = datetime(2026, 2, 18, 4, 0, 0, tzinfo=UTC7)
start_ms = int(sys_start.timestamp() * 1000)
now = datetime.now(UTC7)

print("=" * 80)
print(f"BINANCE API — FULL LIVE ANALYSIS")
print(f"Period: {sys_start.strftime('%Y-%m-%d %H:%M')} -> {now.strftime('%Y-%m-%d %H:%M')} UTC+7")
print("=" * 80)

# Fetch all income types
all_pnl = get_income('REALIZED_PNL', start_ms)
all_funding = get_income('FUNDING_FEE', start_ms)
all_commission = get_income('COMMISSION', start_ms)

total_funding = sum(float(f['income']) for f in all_funding)
total_commission = sum(float(c['income']) for c in all_commission)

# Group fills into logical trades (same symbol within 5 seconds = 1 trade)
fills = []
for inc in all_pnl:
    t = datetime.fromtimestamp(inc['time'] / 1000, UTC7)
    fills.append({
        'time': t,
        'symbol': inc['symbol'],
        'pnl': float(inc['income']),
        'day': t.strftime('%Y-%m-%d'),
        'hour': t.hour,
    })

fills.sort(key=lambda x: x['time'])

# Group into logical trades
trades = []
if fills:
    current = {'symbol': fills[0]['symbol'], 'time': fills[0]['time'],
               'pnl': fills[0]['pnl'], 'fills': 1,
               'day': fills[0]['day'], 'hour': fills[0]['hour']}
    for f in fills[1:]:
        dt = (f['time'] - current['time']).total_seconds()
        if f['symbol'] == current['symbol'] and dt < 5:
            current['pnl'] += f['pnl']
            current['fills'] += 1
        else:
            trades.append(current)
            current = {'symbol': f['symbol'], 'time': f['time'],
                       'pnl': f['pnl'], 'fills': 1,
                       'day': f['day'], 'hour': f['hour']}
    trades.append(current)

# ============================================================
# SECTION 1: ALL TRADES
# ============================================================
print(f"\n{'='*80}")
print(f"SECTION 1: TAT CA TRADES ({len(trades)} logical trades, {len(fills)} fills)")
print(f"{'='*80}")
print(f"\n {'#':>3s} {'Time':>18s} {'Symbol':<16s} {'PnL':>10s} {'Fills':>5s} {'Result':>6s}")
print(" " + "-" * 65)

total_pnl = 0
wins = losses = 0
for i, t in enumerate(trades):
    total_pnl += t['pnl']
    result = 'WIN' if t['pnl'] > 0 else 'LOSS'
    if t['pnl'] > 0:
        wins += 1
    else:
        losses += 1
    print(f" {i+1:>3d} {t['time'].strftime('%m-%d %H:%M'):>18s} {t['symbol']:<16s} {D}{t['pnl']:>+9.4f} {t['fills']:>4d}  {result:>6s}")

total = wins + losses
wr = wins / total * 100 if total > 0 else 0
print(" " + "-" * 65)
print(f" Total: {total}t ({wins}W/{losses}L) = {wr:.1f}% WR")
print(f" Realized PnL: {D}{total_pnl:+.4f}")
print(f" Funding:      {D}{total_funding:+.4f}")
print(f" Commission:   {D}{total_commission:+.4f}")
print(f" NET PnL:      {D}{total_pnl + total_funding + total_commission:+.4f}")

# ============================================================
# SECTION 2: DAILY BREAKDOWN
# ============================================================
print(f"\n{'='*80}")
print(f"SECTION 2: DAILY BREAKDOWN")
print(f"{'='*80}")

daily = defaultdict(lambda: {'trades': [], 'pnl': 0, 'wins': 0, 'losses': 0})
for t in trades:
    daily[t['day']]['trades'].append(t)
    daily[t['day']]['pnl'] += t['pnl']
    if t['pnl'] > 0:
        daily[t['day']]['wins'] += 1
    else:
        daily[t['day']]['losses'] += 1

print(f"\n {'Day':>12s} | {'Trades':>7s} | {'W/L':>7s} | {'WR%':>6s} | {'PnL':>10s} | {D+'/trade':>9s}")
print(" " + "-" * 65)

cumulative = 0
for day in sorted(daily.keys()):
    d = daily[day]
    n = d['wins'] + d['losses']
    wr_d = d['wins'] / n * 100 if n > 0 else 0
    pt = d['pnl'] / n if n > 0 else 0
    cumulative += d['pnl']
    print(f" {day:>12s} | {n:>5d}   | {d['wins']}W/{d['losses']}L | {wr_d:>5.1f}% | {D}{d['pnl']:>+9.4f} | {D}{pt:>+7.4f}")
print(" " + "-" * 65)
n_total = sum(d['wins'] + d['losses'] for d in daily.values())
wr_all = sum(d['wins'] for d in daily.values()) / n_total * 100 if n_total > 0 else 0
print(f" {'TOTAL':>12s} | {n_total:>5d}   |         | {wr_all:>5.1f}% | {D}{cumulative:>+9.4f} | {D}{cumulative/n_total:>+7.4f}")

# ============================================================
# SECTION 3: PER-SYMBOL ANALYSIS
# ============================================================
print(f"\n{'='*80}")
print(f"SECTION 3: PER-SYMBOL PERFORMANCE")
print(f"{'='*80}")

sym_stats = defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0, 'pnls': []})
for t in trades:
    sym_stats[t['symbol']]['trades'] += 1
    sym_stats[t['symbol']]['pnl'] += t['pnl']
    sym_stats[t['symbol']]['pnls'].append(t['pnl'])
    if t['pnl'] > 0:
        sym_stats[t['symbol']]['wins'] += 1

sorted_syms = sorted(sym_stats.items(), key=lambda x: x[1]['pnl'])
print(f"\n {'Symbol':>16s} | {'Trades':>6s} | {'WR%':>6s} | {'PnL':>10s} | {D+'/trade':>9s} | {'Verdict':>10s}")
print(" " + "-" * 70)

for sym, s in sorted_syms:
    wr_s = s['wins'] / s['trades'] * 100 if s['trades'] > 0 else 0
    pt = s['pnl'] / s['trades']
    if s['pnl'] < -1.0 and wr_s < 60:
        verdict = 'TOXIC'
    elif s['pnl'] < 0:
        verdict = 'NEGATIVE'
    elif wr_s >= 80:
        verdict = 'STRONG'
    else:
        verdict = 'OK'
    print(f" {sym:>16s} | {s['trades']:>4d}   | {wr_s:>5.1f}% | {D}{s['pnl']:>+9.4f} | {D}{pt:>+7.4f} | {verdict:>10s}")

# ============================================================
# SECTION 4: HOURLY ANALYSIS
# ============================================================
print(f"\n{'='*80}")
print(f"SECTION 4: HOURLY PERFORMANCE (UTC+7)")
print(f"{'='*80}")

hourly = defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0})
for t in trades:
    hourly[t['hour']]['trades'] += 1
    hourly[t['hour']]['pnl'] += t['pnl']
    if t['pnl'] > 0:
        hourly[t['hour']]['wins'] += 1

print(f"\n {'Hour':>6s} | {'Trades':>6s} | {'WR%':>6s} | {'PnL':>10s} | {'DZ?':>5s} | {'Status':>8s}")
print(" " + "-" * 55)

dz_hours = {6, 7, 14, 18, 19, 20, 23}
for h in range(24):
    s = hourly[h]
    if s['trades'] == 0:
        continue
    wr_h = s['wins'] / s['trades'] * 100
    in_dz = 'DZ' if h in dz_hours else ''
    if wr_h < 50 and s['trades'] >= 2:
        status = 'BAD'
    elif wr_h >= 80:
        status = 'GOOD'
    else:
        status = ''
    print(f" H{h:02d}    | {s['trades']:>4d}   | {wr_h:>5.1f}% | {D}{s['pnl']:>+9.4f} | {in_dz:>5s} | {status:>8s}")

# ============================================================
# SECTION 5: WIN/LOSS PATTERN
# ============================================================
print(f"\n{'='*80}")
print(f"SECTION 5: WIN/LOSS PATTERN ANALYSIS")
print(f"{'='*80}")

# Streak analysis
max_win_streak = max_loss_streak = 0
cur_win = cur_loss = 0
streaks = []
for t in trades:
    if t['pnl'] > 0:
        cur_win += 1
        if cur_loss > 0:
            streaks.append(('L', cur_loss))
        cur_loss = 0
        max_win_streak = max(max_win_streak, cur_win)
    else:
        cur_loss += 1
        if cur_win > 0:
            streaks.append(('W', cur_win))
        cur_win = 0
        max_loss_streak = max(max_loss_streak, cur_loss)
if cur_win > 0:
    streaks.append(('W', cur_win))
if cur_loss > 0:
    streaks.append(('L', cur_loss))

print(f"\n Max winning streak:  {max_win_streak}")
print(f" Max losing streak:   {max_loss_streak}")
print(f" Streak sequence:     {''.join(f'{s[0]}{s[1]}' for s in streaks)}")

# Average win vs loss size
win_pnls = [t['pnl'] for t in trades if t['pnl'] > 0]
loss_pnls = [t['pnl'] for t in trades if t['pnl'] < 0]

avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0
avg_loss = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0

print(f"\n Average win:   {D}{avg_win:+.4f}")
print(f" Average loss:  {D}{avg_loss:+.4f}")
print(f" Win/Loss ratio: {abs(avg_win/avg_loss):.2f}x" if avg_loss != 0 else "")
print(f" Biggest win:   {D}{max(win_pnls):+.4f}" if win_pnls else "")
print(f" Biggest loss:  {D}{min(loss_pnls):+.4f}" if loss_pnls else "")

# Expectancy
expectancy = wr_all/100 * avg_win + (1 - wr_all/100) * avg_loss
print(f"\n Expectancy: {D}{expectancy:+.4f}/trade")
if expectancy > 0:
    print(f" => POSITIVE expectancy — He thong van co edge")
else:
    print(f" => NEGATIVE expectancy — CAN XEM XET")

# ============================================================
# SECTION 6: LONG vs SHORT
# ============================================================
print(f"\n{'='*80}")
print(f"SECTION 6: SIDE ANALYSIS (from commission data)")
print(f"{'='*80}")

# We can't get side from income API easily, skip this
print(f" (Can not determine LONG/SHORT from income API alone)")
print(f" Check docker logs for side breakdown")

# ============================================================
# SECTION 7: CUMULATIVE PnL CURVE
# ============================================================
print(f"\n{'='*80}")
print(f"SECTION 7: CUMULATIVE PnL CURVE")
print(f"{'='*80}")

cum = 0
peak = 0
max_dd = 0
print(f"\n {'#':>3s} {'Time':>14s} {'PnL':>9s} {'Cum PnL':>10s} {'DD':>8s}")
print(" " + "-" * 50)
for i, t in enumerate(trades):
    cum += t['pnl']
    if cum > peak:
        peak = cum
    dd = peak - cum
    if dd > max_dd:
        max_dd = dd
    dd_pct = dd / (62.54 + peak) * 100 if (62.54 + peak) > 0 else 0
    print(f" {i+1:>3d} {t['time'].strftime('%m-%d %H:%M'):>14s} {D}{t['pnl']:>+8.4f} {D}{cum:>+9.4f} {D}{-dd:>+7.2f}")

print(f"\n Peak PnL:     {D}{peak:+.4f}")
print(f" Max Drawdown: {D}{-max_dd:.4f} ({max_dd/(62.54+peak)*100:.1f}%)")
print(f" Current PnL:  {D}{cum:+.4f}")

# Balance
params = {'timestamp': int(time.time() * 1000)}
url = f'{BASE}/fapi/v2/balance?{sign(params)}'
r = requests.get(url, headers={'X-MBX-APIKEY': key})
for b in r.json():
    if b['asset'] == 'USDT':
        bal = float(b['balance'])
        unreal = float(b['crossUnPnl'])
        print(f"\n Current Wallet: {D}{bal:.2f}")
        print(f" Unrealized:     {D}{unreal:.2f}")
        print(f" Equity:         {D}{bal + unreal:.2f}")
        break

print(f"\n{'='*80}")
print(f"ANALYSIS COMPLETE")
print(f"{'='*80}")
