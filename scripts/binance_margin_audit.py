"""
Binance Margin Audit: Fetch REAL trade data and calculate margin impact
Uses actual Binance API (Docker container keys)
"""
import os
import hmac, hashlib, time, requests, json, sys
from datetime import datetime, timezone, timedelta
from collections import defaultdict, deque
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()
if not API_KEY or not API_SECRET:
    raise RuntimeError("Missing BINANCE_API_KEY/BINANCE_API_SECRET in environment or .env")
TZ7 = timezone(timedelta(hours=7))

def signed_req(ep, p=None):
    if p is None:
        p = {}
    p["timestamp"] = int(time.time() * 1000)
    q = "&".join(f"{k}={v}" for k, v in p.items())
    s = hmac.new(API_SECRET.encode(), q.encode(), hashlib.sha256).hexdigest()
    r = requests.get(f"https://fapi.binance.com{ep}?{q}&signature={s}",
                     headers={"X-MBX-APIKEY": API_KEY})
    return r.json()

def fetch_all_income(income_type, start_ms, end_ms):
    """Fetch all income records with pagination"""
    all_data = []
    cursor = start_ms
    while cursor < end_ms:
        data = signed_req("/fapi/v1/income", {
            "incomeType": income_type,
            "startTime": cursor,
            "endTime": end_ms,
            "limit": 1000,
            "recvWindow": 10000
        })
        if not data or not isinstance(data, list):
            break
        all_data.extend(data)
        if len(data) < 1000:
            break
        cursor = data[-1]["time"] + 1
    return all_data

# Fetch from Feb 17 to now
start_ms = int(datetime(2026, 2, 17, 0, 0, tzinfo=TZ7).timestamp() * 1000)
end_ms = int(time.time() * 1000)

print("Fetching Binance income data...")
all_pnl = fetch_all_income("REALIZED_PNL", start_ms, end_ms)
all_comm = fetch_all_income("COMMISSION", start_ms, end_ms)
print(f"PnL records: {len(all_pnl)}, Commission records: {len(all_comm)}")

# Build commission map: (symbol, minute_bucket) -> total commission
comm_map = defaultdict(float)
for c in all_comm:
    key = (c["symbol"], c["time"] // 60000)
    comm_map[key] += abs(float(c["income"]))

# Parse PnL into trades (skip zero-PnL entries)
trades = []
for p in all_pnl:
    pnl = float(p["income"])
    if abs(pnl) < 0.0001:
        continue
    dt = datetime.fromtimestamp(p["time"] / 1000, tz=TZ7)
    sym = p["symbol"]

    # Find commission near this time (search +/- 2 minutes)
    comm = 0
    for offset in range(-2, 3):
        key = (sym, p["time"] // 60000 + offset)
        if key in comm_map:
            comm += comm_map[key]

    trades.append({
        "time": dt,
        "time_str": dt.strftime("%m/%d %H:%M"),
        "symbol": sym,
        "pnl": pnl,
        "comm": comm,
        "net": pnl - comm,
        "result": "WIN" if pnl > 0 else "LOSS",
    })

# Filter from Feb 18
trades = [t for t in trades if t["time"] >= datetime(2026, 2, 18, 0, 0, tzinfo=TZ7)]
trades.sort(key=lambda x: x["time"])
print(f"Trades from Feb 18: {len(trades)}")

# ============================================================
# Now read Docker logs from stdin for sizing data
# ============================================================
print("\nReading Docker logs for sizing data...")
sizing_logs = []
log_lines = sys.stdin.readlines()
for line in log_lines:
    line = line.strip()
    # Parse: 2026-02-22 03:00:02,594 - INFO - Sizing: bal=$13.56 | slot=$2.71 ...
    import re
    ts_match = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
    sz_match = re.search(r'Sizing: bal=\$([0-9.]+) \| slot=\$([0-9.]+) \| pos_val=\$([0-9.]+) \| qty=([0-9.]+)', line)
    if ts_match and sz_match:
        ts = datetime.strptime(ts_match.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ7)
        sizing_logs.append({
            "time": ts,
            "bal": float(sz_match.group(1)),
            "slot": float(sz_match.group(2)),
            "pos_val": float(sz_match.group(3)),
            "qty": float(sz_match.group(4)),
        })

    # Also parse balance events
    bal_match = re.search(r'Balance published: Wallet=\$([0-9.]+)', line)
    if ts_match and bal_match:
        pass  # we'll use sizing logs directly

# Parse MARKET FILLED to match sizing -> trade
fill_logs = []
for line in log_lines:
    line = line.strip()
    ts_match = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
    fill_match = re.search(r'MARKET FILLED: (BUY|SELL) (\w+) qty=([0-9.]+) @ \$([0-9.]+)', line)
    if ts_match and fill_match:
        ts = datetime.strptime(ts_match.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ7)
        fill_logs.append({
            "time": ts,
            "side": fill_match.group(1),
            "symbol": fill_match.group(2),
            "qty": float(fill_match.group(3)),
            "price": float(fill_match.group(4)),
        })

print(f"Sizing logs: {len(sizing_logs)}, Fill logs: {len(fill_logs)}")

# Match each BUY fill to its sizing log (closest sizing before fill with similar qty)
fill_sizing_map = {}  # fill_index -> sizing
for i, fill in enumerate(fill_logs):
    if fill["side"] != "BUY":
        continue
    best = None
    for s in reversed(sizing_logs):
        if s["time"] <= fill["time"]:
            # qty within 5% or within 1 unit
            if abs(s["qty"] - fill["qty"]) / max(fill["qty"], 0.001) < 0.05 or abs(s["qty"] - fill["qty"]) < 1.0:
                best = s
                break
    if best:
        fill_sizing_map[i] = best

# For each Binance trade (close), find the matching entry fill
# Build entry queue per symbol from fill_logs
entry_queue = defaultdict(deque)
for i, fill in enumerate(fill_logs):
    if fill["side"] == "BUY":
        entry_queue[fill["symbol"]].append((i, fill))

# Match Binance PnL trades to entry fills
paired = []
for trade in trades:
    sym = trade["symbol"]
    if entry_queue[sym]:
        fill_idx, entry_fill = entry_queue[sym].popleft()
        sizing = fill_sizing_map.get(fill_idx)

        if sizing:
            actual_bal = sizing["bal"]   # _cached_available (bug)
            actual_slot = sizing["slot"]
            # Estimate wallet balance: for the first sizing in a batch, bal IS wallet
            # For subsequent ones, wallet > bal. We need the max bal seen recently
            # Simple heuristic: wallet is the max of recent bal values
            wallet_bal = actual_bal  # conservative estimate

            # Better: find the max bal in the last 30 minutes (represents wallet when 0 pos)
            for s in sizing_logs:
                if abs((s["time"] - sizing["time"]).total_seconds()) < 7200:  # within 2 hours
                    if s["bal"] > wallet_bal:
                        wallet_bal = s["bal"]

            ideal_slot = wallet_bal / 5
            margin_ratio = actual_slot / ideal_slot if ideal_slot > 0 else 1.0
            # Cap at 1.0 (can't be more than 100%)
            margin_ratio = min(margin_ratio, 1.0)

            # Scale PnL
            actual_pnl = trade["pnl"]
            ideal_pnl = actual_pnl / margin_ratio if margin_ratio > 0 else actual_pnl
            pnl_diff = ideal_pnl - actual_pnl

            paired.append({
                "time_str": trade["time_str"],
                "symbol": sym,
                "result": trade["result"],
                "actual_bal": actual_bal,
                "wallet_bal": wallet_bal,
                "actual_slot": actual_slot,
                "ideal_slot": ideal_slot,
                "margin_ratio": margin_ratio,
                "actual_pnl": actual_pnl,
                "ideal_pnl": ideal_pnl,
                "pnl_diff": pnl_diff,
                "comm": trade["comm"],
            })
        else:
            # No sizing match - assume full margin
            paired.append({
                "time_str": trade["time_str"],
                "symbol": sym,
                "result": trade["result"],
                "actual_bal": 0,
                "wallet_bal": 0,
                "actual_slot": 0,
                "ideal_slot": 0,
                "margin_ratio": 1.0,
                "actual_pnl": trade["pnl"],
                "ideal_pnl": trade["pnl"],
                "pnl_diff": 0,
                "comm": trade["comm"],
            })

print(f"\nPaired trades: {len(paired)}")
print()

# ============================================================
# OUTPUT
# ============================================================
print("=" * 130)
print(f"{'Time':<12} {'Symbol':<14} {'Res':<5} {'AvailBal':>9} {'WalletBal':>10} {'ActSlot':>8} {'IdealSlot':>9} {'Ratio':>6} {'BinancePnL':>11} {'IdealPnL':>10} {'Diff':>8}")
print("=" * 130)

daily = defaultdict(lambda: {"t":0,"w":0,"l":0,"act":0,"ideal":0,"diff":0,
                               "w_act":0,"w_ideal":0,"l_act":0,"l_ideal":0,
                               "w_ratios":[],"l_ratios":[],"all_ratios":[]})

for p in paired:
    r_pct = p["margin_ratio"] * 100
    print(f"{p['time_str']:<12} {p['symbol']:<14} {p['result']:<5} "
          f"${p['actual_bal']:>8.2f} ${p['wallet_bal']:>9.2f} "
          f"${p['actual_slot']:>7.2f} ${p['ideal_slot']:>8.2f} "
          f"{r_pct:>5.0f}% "
          f"{p['actual_pnl']:>+11.4f} {p['ideal_pnl']:>+10.4f} {p['pnl_diff']:>+8.4f}")

    d = p["time_str"][:5]
    dd = daily[d]
    dd["t"] += 1; dd["act"] += p["actual_pnl"]; dd["ideal"] += p["ideal_pnl"]; dd["diff"] += p["pnl_diff"]
    dd["all_ratios"].append(p["margin_ratio"])
    if p["result"] == "WIN":
        dd["w"] += 1; dd["w_act"] += p["actual_pnl"]; dd["w_ideal"] += p["ideal_pnl"]
        dd["w_ratios"].append(p["margin_ratio"])
    else:
        dd["l"] += 1; dd["l_act"] += p["actual_pnl"]; dd["l_ideal"] += p["ideal_pnl"]
        dd["l_ratios"].append(p["margin_ratio"])

# Daily summary
print()
print("=" * 120)
print("DAILY SUMMARY (Binance PnL)")
print("=" * 120)
print(f"{'Date':<6} {'Trades':>6} {'W/L':>8} {'ActPnL':>10} {'IdealPnL':>11} {'PnL Diff':>9} {'AvgRatio':>9} {'WinRatio':>9} {'LossRatio':>10}")
print("-" * 120)

totals = {"t":0,"w":0,"l":0,"act":0,"ideal":0,"diff":0,"w_r":[],"l_r":[]}
for d in sorted(daily.keys()):
    v = daily[d]
    avg_r = sum(v["all_ratios"])/len(v["all_ratios"]) if v["all_ratios"] else 1
    w_r = sum(v["w_ratios"])/len(v["w_ratios"]) if v["w_ratios"] else 0
    l_r = sum(v["l_ratios"])/len(v["l_ratios"]) if v["l_ratios"] else 0
    print(f"{d:<6} {v['t']:>6} {v['w']:>3}W/{v['l']:<3}L "
          f"${v['act']:>+9.2f} ${v['ideal']:>+10.2f} ${v['diff']:>+8.2f} "
          f"{avg_r*100:>8.0f}% {w_r*100:>8.0f}% {l_r*100:>9.0f}%")
    totals["t"]+=v["t"]; totals["w"]+=v["w"]; totals["l"]+=v["l"]
    totals["act"]+=v["act"]; totals["ideal"]+=v["ideal"]; totals["diff"]+=v["diff"]
    totals["w_r"].extend(v["w_ratios"]); totals["l_r"].extend(v["l_ratios"])

print("-" * 120)
avg_w = sum(totals["w_r"])/len(totals["w_r"]) if totals["w_r"] else 0
avg_l = sum(totals["l_r"])/len(totals["l_r"]) if totals["l_r"] else 0
print(f"{'TOTAL':<6} {totals['t']:>6} {totals['w']:>3}W/{totals['l']:<3}L "
      f"${totals['act']:>+9.2f} ${totals['ideal']:>+10.2f} ${totals['diff']:>+8.2f} "
      f"{'':>9} {avg_w*100:>8.0f}% {avg_l*100:>9.0f}%")

# Asymmetry
print()
print("=" * 80)
print("ASYMMETRY & IMPACT")
print("=" * 80)
print(f"  Avg WIN margin ratio:  {avg_w*100:.1f}% of ideal")
print(f"  Avg LOSS margin ratio: {avg_l*100:.1f}% of ideal")
if avg_w > 0 and avg_l > 0:
    asym = avg_l / avg_w
    print(f"  Asymmetry ratio:       {asym:.3f}x (>1 = losses bigger)")
print()
print(f"  Actual PnL (Binance):  ${totals['act']:+.2f}")
print(f"  Ideal PnL (equal $):   ${totals['ideal']:+.2f}")
print(f"  PnL difference:        ${totals['diff']:+.2f}")
if totals["act"] != 0:
    impact_pct = abs(totals["diff"]) / abs(totals["act"]) * 100
    print(f"  Impact magnitude:      {impact_pct:.1f}% of actual PnL")

# Win/Loss breakdown
print()
total_w_act = sum(p["actual_pnl"] for p in paired if p["result"] == "WIN")
total_w_ideal = sum(p["ideal_pnl"] for p in paired if p["result"] == "WIN")
total_l_act = sum(p["actual_pnl"] for p in paired if p["result"] == "LOSS")
total_l_ideal = sum(p["ideal_pnl"] for p in paired if p["result"] == "LOSS")
print(f"  WIN  total: Actual ${total_w_act:+.2f} -> Ideal ${total_w_ideal:+.2f} (diff ${total_w_ideal-total_w_act:+.2f})")
print(f"  LOSS total: Actual ${total_l_act:+.2f} -> Ideal ${total_l_ideal:+.2f} (diff ${total_l_ideal-total_l_act:+.2f})")
