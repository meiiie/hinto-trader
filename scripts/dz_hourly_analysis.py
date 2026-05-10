"""Analyze BT trades by hour to find optimal Dead Zone configuration

Enhanced with sub-period stability analysis:
  - Splits trades into 30-day sub-periods
  - Shows hourly PnL heat map across all periods
  - Computes Spearman rank correlation between periods
  - Classifies hours as STABLE / NOISE
"""
import csv, sys, os
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from itertools import combinations

def analyze_csv(csv_path):
    """Analyze trades by hour from BT CSV"""
    utc7 = timezone(timedelta(hours=7))

    hourly = defaultdict(lambda: {"w": 0, "l": 0, "pnl": 0.0, "trades": []})

    with open(csv_path) as f:
        rows = list(csv.DictReader(f))

    # Find columns
    pnl_col = None
    for col in ['PnL ($)', 'pnl', 'realized_pnl', 'net_pnl']:
        if col in rows[0]:
            pnl_col = col
            break

    time_col = None
    for col in ['Entry Time (UTC+7)', 'entry_time', 'Entry Time', 'open_time']:
        if col in rows[0]:
            time_col = col
            break

    if not pnl_col or not time_col:
        print(f"ERROR: Missing columns. Available: {list(rows[0].keys())}")
        return

    total_pnl = 0
    total_trades = 0
    total_wins = 0

    for r in rows:
        pnl = float(r[pnl_col])
        time_str = r[time_col]

        # Parse time - handle multiple formats
        for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M']:
            try:
                dt = datetime.strptime(time_str, fmt)
                break
            except ValueError:
                continue
        else:
            try:
                dt = datetime.fromisoformat(time_str)
            except:
                continue

        # Time is already UTC+7 if column says so
        hour = dt.hour

        hourly[hour]["pnl"] += pnl
        hourly[hour]["trades"].append(pnl)
        if pnl > 0:
            hourly[hour]["w"] += 1
            total_wins += 1
        else:
            hourly[hour]["l"] += 1

        total_pnl += pnl
        total_trades += 1

    total_wr = total_wins / total_trades * 100 if total_trades > 0 else 0

    print(f"\n{'='*80}")
    print(f"HOURLY ANALYSIS (UTC+7) — {total_trades} trades, {total_wr:.1f}% WR, ${total_pnl:+.2f}")
    print(f"{'='*80}")
    print(f"\n{'Hour':>6s} {'Trades':>7s} {'Wins':>5s} {'Loss':>5s} {'WR%':>6s} {'PnL':>8s} {'$/trade':>8s} {'Bar'}")
    print("-" * 75)

    for h in range(24):
        d = hourly[h]
        t = d["w"] + d["l"]
        if t == 0:
            print(f"  H{h:02d}   {0:>5d}     -     -      -        -        -")
            continue
        wr = d["w"] / t * 100
        per_trade = d["pnl"] / t

        # Visual bar
        bar_len = int(abs(d["pnl"]) / 0.2)  # Scale
        bar = ("+" * bar_len) if d["pnl"] > 0 else ("-" * bar_len)

        # Flag toxic hours
        flag = ""
        if wr < 65 and t >= 5:
            flag = " ⚠️ TOXIC"
        elif wr < 70 and t >= 5:
            flag = " ⚡ WEAK"
        elif wr >= 80 and t >= 5:
            flag = " ✅ STRONG"

        print(f"  H{h:02d}   {t:>5d}   {d['w']:>3d}   {d['l']:>3d}  {wr:>5.1f}% {d['pnl']:>+7.2f} {per_trade:>+7.4f}  {bar}{flag}")

    # Find toxic hours (below average performance)
    print(f"\n{'='*80}")
    print("TOXIC HOUR IDENTIFICATION")
    print(f"{'='*80}")

    avg_pnl_per_trade = total_pnl / total_trades if total_trades > 0 else 0
    print(f"\nAvg PnL/trade: ${avg_pnl_per_trade:+.4f}")

    # Rank hours by PnL contribution
    hour_stats = []
    for h in range(24):
        d = hourly[h]
        t = d["w"] + d["l"]
        if t > 0:
            wr = d["w"] / t * 100
            per_trade = d["pnl"] / t
            hour_stats.append((h, t, wr, d["pnl"], per_trade))

    # Sort by PnL (worst first)
    hour_stats.sort(key=lambda x: x[3])

    print(f"\nHours ranked by PnL (worst → best):")
    for h, t, wr, pnl, pt in hour_stats:
        marker = "<<<" if pnl < 0 else ""
        print(f"  H{h:02d}: {t:>3d} trades, {wr:>5.1f}% WR, ${pnl:>+7.2f} (${pt:>+.4f}/t) {marker}")

    # Test all possible DZ configurations
    print(f"\n{'='*80}")
    print("DEAD ZONE OPTIMIZATION — Testing all combinations")
    print(f"{'='*80}")

    # Identify negative hours
    negative_hours = [h for h, t, wr, pnl, pt in hour_stats if pnl < 0 and t >= 3]
    print(f"\nNegative PnL hours (≥3 trades): {[f'H{h:02d}' for h in negative_hours]}")

    # Test single-hour DZs
    print(f"\n--- Single-hour DZ ---")
    print(f"{'DZ':>15s} {'Blocked':>8s} {'Remaining':>10s} {'PnL':>8s} {'Δ vs none':>10s} {'WR%':>6s}")

    no_dz_pnl = total_pnl
    results = []

    for h in range(24):
        d = hourly[h]
        t = d["w"] + d["l"]
        if t == 0:
            continue
        remaining_pnl = total_pnl - d["pnl"]
        remaining_trades = total_trades - t
        remaining_wins = total_wins - d["w"]
        remaining_wr = remaining_wins / remaining_trades * 100 if remaining_trades > 0 else 0
        delta = remaining_pnl - no_dz_pnl
        results.append((f"H{h:02d}", t, remaining_trades, remaining_pnl, delta, remaining_wr, [h]))
        print(f"  Block H{h:02d}   {t:>5d}     {remaining_trades:>6d}   {remaining_pnl:>+7.2f}   {delta:>+7.2f}     {remaining_wr:>5.1f}%")

    # Test contiguous multi-hour DZs (2-4 hours)
    print(f"\n--- Multi-hour contiguous DZ ---")
    print(f"{'DZ':>20s} {'Blocked':>8s} {'Remaining':>10s} {'PnL':>8s} {'Δ vs none':>10s} {'WR%':>6s}")

    for length in [2, 3, 4]:
        for start in range(24):
            hours_blocked = [(start + i) % 24 for i in range(length)]
            blocked_trades = sum(hourly[h]["w"] + hourly[h]["l"] for h in hours_blocked)
            blocked_pnl = sum(hourly[h]["pnl"] for h in hours_blocked)
            blocked_wins = sum(hourly[h]["w"] for h in hours_blocked)

            if blocked_trades == 0:
                continue

            remaining_pnl = total_pnl - blocked_pnl
            remaining_trades = total_trades - blocked_trades
            remaining_wins = total_wins - blocked_wins
            remaining_wr = remaining_wins / remaining_trades * 100 if remaining_trades > 0 else 0
            delta = remaining_pnl - no_dz_pnl

            dz_label = f"H{start:02d}-H{(start+length)%24:02d}"
            results.append((dz_label, blocked_trades, remaining_trades, remaining_pnl, delta, remaining_wr, hours_blocked))

            if delta > 0:  # Only show improvements
                print(f"  {dz_label:>18s}   {blocked_trades:>5d}     {remaining_trades:>6d}   {remaining_pnl:>+7.2f}   {delta:>+7.2f}     {remaining_wr:>5.1f}%")

    # Test non-contiguous DZs (combine 2 worst hours)
    if len(negative_hours) >= 2:
        print(f"\n--- Non-contiguous DZ (combining toxic hours) ---")
        print(f"{'DZ':>25s} {'Blocked':>8s} {'Remaining':>10s} {'PnL':>8s} {'Δ vs none':>10s} {'WR%':>6s}")

        for combo_size in [2, 3]:
            if len(negative_hours) < combo_size:
                break
            for combo in combinations(negative_hours, combo_size):
                blocked_trades = sum(hourly[h]["w"] + hourly[h]["l"] for h in combo)
                blocked_pnl = sum(hourly[h]["pnl"] for h in combo)
                blocked_wins = sum(hourly[h]["w"] for h in combo)

                remaining_pnl = total_pnl - blocked_pnl
                remaining_trades = total_trades - blocked_trades
                remaining_wins = total_wins - blocked_wins
                remaining_wr = remaining_wins / remaining_trades * 100 if remaining_trades > 0 else 0
                delta = remaining_pnl - no_dz_pnl

                dz_label = "+".join(f"H{h:02d}" for h in combo)
                results.append((dz_label, blocked_trades, remaining_trades, remaining_pnl, delta, remaining_wr, list(combo)))

                if delta > 0:
                    print(f"  {dz_label:>23s}   {blocked_trades:>5d}     {remaining_trades:>6d}   {remaining_pnl:>+7.2f}   {delta:>+7.2f}     {remaining_wr:>5.1f}%")

    # TOP 10 best DZ configs
    results.sort(key=lambda x: x[3], reverse=True)  # Sort by remaining PnL

    print(f"\n{'='*80}")
    print("TOP 10 BEST DEAD ZONE CONFIGURATIONS")
    print(f"{'='*80}")
    print(f"{'#':>3s} {'DZ':>25s} {'Blocked':>8s} {'Trades':>7s} {'PnL':>8s} {'Δ PnL':>8s} {'WR%':>6s} {'$/trade':>8s}")
    print("-" * 85)

    # Add no-DZ as reference
    print(f"  - {'NO DZ (baseline)':>23s}   {0:>5d}     {total_trades:>5d}   {total_pnl:>+7.2f}   {0:>+7.2f}     {total_wr:>5.1f}%  {avg_pnl_per_trade:>+7.4f}")

    for i, (label, blocked, remaining, pnl, delta, wr, hours) in enumerate(results[:10]):
        per_t = pnl / remaining if remaining > 0 else 0
        marker = " ★" if i == 0 else ""
        print(f" {i+1:>2d} {label:>23s}   {blocked:>5d}     {remaining:>5d}   {pnl:>+7.2f}   {delta:>+7.2f}     {wr:>5.1f}%  {per_t:>+7.4f}{marker}")

    # Current DZ comparison (deployed: 06-08+19-21)
    print(f"\n--- Deployed DZ (06-08+19-21 = H06,H07,H19,H20) comparison ---")
    deployed_hours = [6, 7, 19, 20]
    deployed_trades = sum(hourly[h]["w"] + hourly[h]["l"] for h in deployed_hours)
    deployed_pnl = sum(hourly[h]["pnl"] for h in deployed_hours)
    deployed_wins = sum(hourly[h]["w"] for h in deployed_hours)
    if deployed_trades > 0:
        deployed_wr = deployed_wins / deployed_trades * 100
        print(f"  Blocked: {deployed_trades} trades, {deployed_wr:.1f}% WR, ${deployed_pnl:+.2f}")
        print(f"  Without: {total_trades - deployed_trades} trades, PnL ${total_pnl - deployed_pnl:+.2f}")
        print(f"  Improvement: ${-deployed_pnl:+.2f}")


def analyze_subperiod_stability(csv_path, period_days=30):
    """
    Sub-period stability analysis: split trades into sub-periods,
    compute hourly PnL per period, and classify hours as STABLE / NOISE.
    """
    with open(csv_path, encoding='utf-8') as f:
        rows = list(csv.DictReader(f))

    if not rows:
        return

    # Find columns
    pnl_col = None
    for col in ['PnL ($)', 'pnl', 'realized_pnl', 'net_pnl']:
        if col in rows[0]:
            pnl_col = col
            break

    time_col = None
    for col in ['Entry Time (UTC+7)', 'entry_time', 'Entry Time', 'open_time']:
        if col in rows[0]:
            time_col = col
            break

    if not pnl_col or not time_col:
        return

    # Parse trades
    trades = []
    for r in rows:
        pnl = float(r[pnl_col])
        time_str = r[time_col]
        dt = None
        for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M']:
            try:
                dt = datetime.strptime(time_str, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            try:
                dt = datetime.fromisoformat(time_str)
            except Exception:
                continue
        trades.append({'datetime': dt, 'date': dt.date(), 'hour': dt.hour, 'pnl': pnl})

    if not trades:
        return

    trades.sort(key=lambda t: t['datetime'])
    first_date = trades[0]['date']
    last_date = trades[-1]['date']
    total_days = (last_date - first_date).days

    if total_days < period_days:
        print(f"\n  Only {total_days} days of data, need >= {period_days} for sub-period analysis")
        return

    # Split into sub-periods
    periods = []
    current = first_date
    while current + timedelta(days=period_days) <= last_date + timedelta(days=1):
        period_end = current + timedelta(days=period_days)
        period_trades = [t for t in trades if current <= t['date'] < period_end]
        if period_trades:
            periods.append({
                'start': current,
                'end': period_end,
                'trades': period_trades,
            })
        current = period_end

    # Collect leftover trades into last period if significant
    leftover = [t for t in trades if t['date'] >= current]
    if leftover and len(leftover) >= 20:
        periods.append({
            'start': current,
            'end': last_date + timedelta(days=1),
            'trades': leftover,
        })

    if len(periods) < 2:
        print(f"\n  Only {len(periods)} sub-period(s), need >= 2 for stability analysis")
        return

    # Build hourly PnL matrix: periods x hours
    pnl_matrix = []  # [period_idx][hour] = pnl
    wr_matrix = []
    count_matrix = []
    for p in periods:
        hour_pnl = [0.0] * 24
        hour_wins = [0] * 24
        hour_count = [0] * 24
        for t in p['trades']:
            hour_pnl[t['hour']] += t['pnl']
            hour_count[t['hour']] += 1
            if t['pnl'] > 0:
                hour_wins[t['hour']] += 1
        pnl_matrix.append(hour_pnl)
        count_matrix.append(hour_count)
        wr_matrix.append([
            hour_wins[h] / hour_count[h] * 100 if hour_count[h] > 0 else 0
            for h in range(24)
        ])

    # Print heat map
    print(f"\n{'='*80}")
    print(f"SUB-PERIOD STABILITY ANALYSIS ({period_days}d periods, {len(periods)} periods)")
    print(f"{'='*80}")

    # Period headers
    period_labels = [f"P{i+1}" for i in range(len(periods))]
    header = f"{'Hour':>6s} " + " ".join(f"{l:>10s}" for l in period_labels) + f" {'Consist':>8s}  {'Class'}"
    print(f"\n  PnL Heat Map ($ per period):")
    print(f"  {header}")

    # Period date ranges
    date_header = f"{'':>6s} " + " ".join(
        f"{p['start'].strftime('%m/%d'):>10s}" for p in periods
    )
    print(f"  {date_header}")
    print("  " + "-" * len(header))

    # Classify each hour
    hour_classifications = {}
    for h in range(24):
        values = [pnl_matrix[i][h] for i in range(len(periods))]
        counts = [count_matrix[i][h] for i in range(len(periods))]

        # Consistency: how many periods agree on sign (positive or negative)?
        positive = sum(1 for v in values if v > 0)
        negative = sum(1 for v in values if v < 0)
        zero = sum(1 for v in values if v == 0)
        active_periods = len(values) - zero
        consistency = max(positive, negative) / active_periods * 100 if active_periods > 0 else 0

        # Is consistently negative?
        neg_pct = negative / active_periods * 100 if active_periods > 0 else 0
        pos_pct = positive / active_periods * 100 if active_periods > 0 else 0

        if neg_pct >= 70:
            classification = "TOXIC-STABLE"
        elif pos_pct >= 70:
            classification = "GOOD-STABLE"
        elif active_periods < 2:
            classification = "LOW-DATA"
        else:
            classification = "NOISE"

        hour_classifications[h] = classification

        # Format row
        row = f"  H{h:02d}   "
        for i in range(len(periods)):
            v = pnl_matrix[i][h]
            c = count_matrix[i][h]
            if c == 0:
                row += f"{'--':>10s} "
            elif v >= 0:
                row += f"{'$'+f'{v:+.2f}':>10s} "
            else:
                row += f"{'$'+f'{v:+.2f}':>10s} "
        row += f"  {consistency:>5.0f}%   {classification}"
        print(row)

    # Spearman rank correlation between periods
    print(f"\n  Spearman Rank Correlation (hourly PnL rankings between periods):")

    def rank_values(values):
        indexed = sorted(enumerate(values), key=lambda x: x[1])
        ranks = [0.0] * len(values)
        i = 0
        while i < len(indexed):
            j = i
            while j < len(indexed) and indexed[j][1] == indexed[i][1]:
                j += 1
            avg_rank = (i + j - 1) / 2 + 1
            for k in range(i, j):
                ranks[indexed[k][0]] = avg_rank
            i = j
        return ranks

    def spearman(x, y):
        rx = rank_values(x)
        ry = rank_values(y)
        n = len(rx)
        d_sq = sum((a - b) ** 2 for a, b in zip(rx, ry))
        return 1 - (6 * d_sq) / (n * (n * n - 1))

    correlations = []
    for i in range(len(periods)):
        for j in range(i + 1, len(periods)):
            rho = spearman(pnl_matrix[i], pnl_matrix[j])
            correlations.append(rho)
            print(f"    P{i+1} vs P{j+1} ({periods[i]['start']} vs {periods[j]['start']}): rho = {rho:+.3f}")

    if correlations:
        avg_rho = sum(correlations) / len(correlations)
        print(f"\n    Average rho: {avg_rho:+.3f}")
        if avg_rho >= 0.5:
            print(f"    Verdict: STRONG consistency — hourly patterns persist across periods")
        elif avg_rho >= 0.3:
            print(f"    Verdict: MODERATE consistency — some pattern stability")
        elif avg_rho >= 0.1:
            print(f"    Verdict: WEAK consistency — patterns may be partially overfit")
        else:
            print(f"    Verdict: NO consistency — patterns appear random across periods")

    # Summary: which hours are consistently toxic?
    stable_toxic = [h for h, c in hour_classifications.items() if c == "TOXIC-STABLE"]
    stable_good = [h for h, c in hour_classifications.items() if c == "GOOD-STABLE"]
    noise = [h for h, c in hour_classifications.items() if c == "NOISE"]

    print(f"\n  Hour Classification Summary:")
    print(f"    TOXIC-STABLE (neg PnL in 70%+ periods): {[f'H{h:02d}' for h in sorted(stable_toxic)] or 'None'}")
    print(f"    GOOD-STABLE  (pos PnL in 70%+ periods): {[f'H{h:02d}' for h in sorted(stable_good)] or 'None'}")
    print(f"    NOISE (inconsistent across periods):     {[f'H{h:02d}' for h in sorted(noise)] or 'None'}")

    # Check deployed DZ
    deployed = {6, 7, 19, 20}
    print(f"\n  Deployed DZ (H06,H07,H19,H20) classification:")
    for h in sorted(deployed):
        print(f"    H{h:02d}: {hour_classifications.get(h, 'N/A')}")

    all_stable = all(hour_classifications.get(h) == "TOXIC-STABLE" for h in deployed)
    if all_stable:
        print(f"\n    >>> All deployed DZ hours are TOXIC-STABLE — DZ is structurally validated")
    else:
        unstable = [h for h in deployed if hour_classifications.get(h) != "TOXIC-STABLE"]
        print(f"\n    >>> WARNING: {[f'H{h:02d}' for h in unstable]} are NOT consistently toxic")
        print(f"    >>> Consider narrowing DZ to only TOXIC-STABLE hours")


if __name__ == "__main__":
    # Find most recent BT CSV
    import glob
    csvs = sorted(glob.glob("portfolio_backtest_*.csv"), key=os.path.getmtime, reverse=True)

    if not csvs:
        print("No BT CSV files found!")
        sys.exit(1)

    csv_path = csvs[0]
    print(f"Analyzing: {csv_path}")
    analyze_csv(csv_path)

    # Run sub-period stability analysis
    analyze_subperiod_stability(csv_path, period_days=30)
