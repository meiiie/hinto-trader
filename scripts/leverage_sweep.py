"""
Leverage sweep: run BT for each leverage level and compare results
"""
import subprocess, sys, re, json

LEVERAGES = [3, 4, 5, 7, 10, 15, 20]

BASE_CMD = [
    sys.executable, "-X", "utf8", "-u", "backend/run_backtest.py",
    "--top", "40", "--days", "20", "--balance", "20",
    "--max-pos", "5", "--ttl", "50",
    "--full-tp", "--close-profitable-auto", "--profitable-threshold-pct", "5",
    "--portfolio-target-pct", "10", "--max-sl-validation", "--max-sl-pct", "1.2",
    "--breakeven-r", "1.5", "--trailing-atr", "4.0", "--no-compound",
    "--sl-on-close-only", "--hard-cap-pct", "2.0",
    "--sniper-lookback", "15", "--sniper-proximity", "2.5",
    "--fill-buffer", "0",
    "--delta-divergence", "--mtf-trend", "--mtf-ema", "20",
    "--blocked-windows", "06:00-08:00,14:00-15:00,18:00-21:00,23:00-00:00",
]

results = []

for lev in LEVERAGES:
    print(f"\n{'='*60}")
    print(f"Running BT: leverage={lev}x")
    print(f"{'='*60}")

    cmd = BASE_CMD + ["--leverage", str(lev)]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600,
            env={**__import__('os').environ, "PYTHONIOENCODING": "utf-8"}
        )
        output = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT for {lev}x")
        results.append({"lev": lev, "error": "TIMEOUT"})
        continue

    # Parse results from output
    trades = wr = pnl = pf = max_dd = sharpe = avg_win = avg_loss = None

    # Try to find summary line
    for line in output.split('\n'):
        # Look for total trades
        m = re.search(r'Total trades:\s*(\d+)', line)
        if m: trades = int(m.group(1))

        m = re.search(r'Win rate:\s*([\d.]+)%', line)
        if m: wr = float(m.group(1))

        m = re.search(r'Total PnL:\s*\$?([-\d.]+)', line)
        if m: pnl = float(m.group(1))

        m = re.search(r'Profit Factor:\s*([\d.]+)', line)
        if m: pf = float(m.group(1))

        m = re.search(r'Max Drawdown:\s*\$?([-\d.]+)', line)
        if m: max_dd = float(m.group(1))

        m = re.search(r'Sharpe.*?:\s*([-\d.]+)', line)
        if m: sharpe = float(m.group(1))

        m = re.search(r'Avg Win:\s*\$?([\d.]+)', line)
        if m: avg_win = float(m.group(1))

        m = re.search(r'Avg Loss:\s*[-]?\$?([\d.]+)', line)
        if m: avg_loss = float(m.group(1))

    # Also try CSV-style output
    if trades is None:
        for line in output.split('\n'):
            if 'PORTFOLIO SUMMARY' in line or 'Summary' in line:
                continue
            # Various formats the BT might output
            m = re.search(r'(\d+)\s+trades.*?([\d.]+)%\s+WR.*?\$?([-\d.]+)', line)
            if m:
                trades = int(m.group(1))
                wr = float(m.group(2))
                pnl = float(m.group(3))

    r = {"lev": lev, "trades": trades, "wr": wr, "pnl": pnl, "pf": pf,
         "max_dd": max_dd, "sharpe": sharpe, "avg_win": avg_win, "avg_loss": avg_loss}
    results.append(r)

    print(f"  Trades={trades}, WR={wr}%, PnL=${pnl}, PF={pf}, MaxDD={max_dd}")

    # Save raw output for debugging
    with open(f"scripts/bt_lev{lev}x_output.txt", "w", encoding="utf-8") as f:
        f.write(output)

# Summary table
print("\n\n" + "=" * 100)
print("LEVERAGE COMPARISON (20 days, $20, top40)")
print("=" * 100)
print(f"  {'Lev':>4} {'Trades':>7} {'WR':>7} {'PnL':>9} {'PF':>6} {'MaxDD':>8} {'Sharpe':>7} {'AvgWin':>8} {'AvgLoss':>8} {'W/L':>6}")
print(f"  {'-'*80}")

for r in results:
    if "error" in r:
        print(f"  {r['lev']:>3}x  ERROR: {r['error']}")
        continue

    wl = r['avg_win'] / r['avg_loss'] if r.get('avg_win') and r.get('avg_loss') and r['avg_loss'] > 0 else 0

    lev_str = f"{r['lev']}x"
    trades_str = f"{r['trades']}" if r['trades'] else "?"
    wr_str = f"{r['wr']:.1f}%" if r['wr'] else "?"
    pnl_str = f"${r['pnl']:+.2f}" if r['pnl'] is not None else "?"
    pf_str = f"{r['pf']:.2f}" if r['pf'] else "?"
    dd_str = f"${r['max_dd']:.2f}" if r['max_dd'] is not None else "?"
    sh_str = f"{r['sharpe']:.2f}" if r['sharpe'] else "?"
    aw_str = f"${r['avg_win']:.3f}" if r['avg_win'] else "?"
    al_str = f"${r['avg_loss']:.3f}" if r['avg_loss'] else "?"
    wl_str = f"{wl:.3f}" if wl > 0 else "?"

    marker = " <<<" if r['lev'] == 10 else ""
    print(f"  {lev_str:>4} {trades_str:>7} {wr_str:>7} {pnl_str:>9} {pf_str:>6} {dd_str:>8} {sh_str:>7} {aw_str:>8} {al_str:>8} {wl_str:>6}{marker}")
