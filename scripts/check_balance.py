import os
import hmac, hashlib, time, requests
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()
if not API_KEY or not API_SECRET:
    raise RuntimeError("Missing BINANCE_API_KEY/BINANCE_API_SECRET in environment or .env")
p = {"timestamp": int(time.time()*1000), "recvWindow": 10000}
q = "&".join(f"{k}={v}" for k,v in p.items())
s = hmac.new(API_SECRET.encode(), q.encode(), hashlib.sha256).hexdigest()
r = requests.get(f"https://fapi.binance.com/fapi/v2/balance?{q}&signature={s}",
                 headers={"X-MBX-APIKEY": API_KEY}).json()
for a in r:
    if a["asset"] == "USDT":
        w = float(a["balance"])
        av = float(a["availableBalance"])
        pnl = float(a["crossUnPnl"])
        print(f"Wallet:      ${w:.2f}")
        print(f"Available:   ${av:.2f}")
        print(f"Unrealized:  ${pnl:.2f}")
        print(f"Equity:      ${w + pnl:.2f}")

# Also get positions
p2 = {"timestamp": int(time.time()*1000), "recvWindow": 10000}
q2 = "&".join(f"{k}={v}" for k,v in p2.items())
s2 = hmac.new(API_SECRET.encode(), q2.encode(), hashlib.sha256).hexdigest()
r2 = requests.get(f"https://fapi.binance.com/fapi/v2/positionRisk?{q2}&signature={s2}",
                  headers={"X-MBX-APIKEY": API_KEY}).json()
open_pos = [p for p in r2 if float(p["positionAmt"]) != 0]
if open_pos:
    print(f"\nOpen positions: {len(open_pos)}")
    for p in open_pos:
        print(f"  {p['symbol']}: qty={p['positionAmt']}, PnL=${float(p['unRealizedProfit']):.2f}, entry=${float(p['entryPrice']):.4f}")
else:
    print("\nNo open positions")
