"""
Generate Expert Comparison Report

This script generates a detailed report of current dashboard indicators
for expert comparison with Binance 15m timeframe data.
"""

import sys
import os
from datetime import datetime
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.infrastructure.api.binance_rest_client import BinanceRestClient
from src.application.analysis.rsi_monitor import RSIMonitor
from src.infrastructure.indicators.talib_calculator import TALibCalculator
import pandas as pd


def generate_report():
    """Generate comprehensive indicator report"""

    print("=" * 80)
    print("DASHBOARD INDICATOR REPORT FOR EXPERT COMPARISON")
    print("Generated:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 80)

    client = BinanceRestClient()
    talib_calc = TALibCalculator()

    # Report data structure
    report = {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "symbol": "BTCUSDT",
            "source": "Binance API",
            "dashboard_version": "1.0"
        },
        "timeframes": {}
    }

    # Analyze multiple timeframes
    timeframes = [
        ("1m", 100, "1 minute"),
        ("5m", 100, "5 minutes"),
        ("15m", 100, "15 minutes"),
        ("1h", 100, "1 hour")
    ]

    for interval, limit, description in timeframes:
        print(f"\n{'=' * 80}")
        print(f"TIMEFRAME: {interval.upper()} ({description})")
        print(f"{'=' * 80}")

        # Fetch candles
        candles = client.get_klines(symbol='BTCUSDT', interval=interval, limit=limit)

        if not candles or len(candles) < 20:
            print(f"❌ Insufficient data for {interval}")
            continue

        # Latest candle
        latest = candles[-1]
        first = candles[0]

        print(f"\n📊 PRICE DATA")
        print(f"   Latest Candle Time: {latest.timestamp}")
        print(f"   Open:  ${latest.open:,.2f}")
        print(f"   High:  ${latest.high:,.2f}")
        print(f"   Low:   ${latest.low:,.2f}")
        print(f"   Close: ${latest.close:,.2f}")

        # Price change
        price_change = latest.close - first.close
        price_change_pct = (price_change / first.close) * 100
        print(f"\n   Price Change ({len(candles)} candles):")
        print(f"   Absolute: ${price_change:,.2f}")
        print(f"   Percentage: {price_change_pct:+.2f}%")

        # Volume analysis
        print(f"\n📈 VOLUME ANALYSIS")
        print(f"   Current Candle Volume: {latest.volume:.2f} BTC")

        total_volume = sum(c.volume for c in candles)
        avg_volume = total_volume / len(candles)
        print(f"   Total Volume ({len(candles)} candles): {total_volume:,.2f} BTC")
        print(f"   Average Volume per candle: {avg_volume:.2f} BTC")
        print(f"   Current vs Average: {(latest.volume / avg_volume * 100):.1f}%")

        # Convert to DataFrame for indicators
        df = pd.DataFrame({
            'close': [c.close for c in candles],
            'open': [c.open for c in candles],
            'high': [c.high for c in candles],
            'low': [c.low for c in candles],
            'volume': [c.volume for c in candles]
        })

        # Calculate all indicators
        result_df = talib_calc.calculate_all(df)

        # RSI Analysis
        print(f"\n📉 RSI ANALYSIS")

        # RSI(6) - Dashboard default
        rsi_6 = RSIMonitor(period=6)
        rsi_6_result = rsi_6.analyze(candles)
        if rsi_6_result:
            print(f"   RSI(6):  {rsi_6_result['rsi']:.2f} - {rsi_6_result['zone'].value}")

        # RSI(14) - Binance default
        rsi_14 = RSIMonitor(period=14)
        rsi_14_result = rsi_14.analyze(candles)
        if rsi_14_result:
            print(f"   RSI(14): {rsi_14_result['rsi']:.2f} - {rsi_14_result['zone'].value}")

        # EMA Analysis
        print(f"\n📊 EMA (Exponential Moving Average)")

        ema_periods = ['ema_7', 'ema_25', 'ema_99']
        for ema_col in ema_periods:
            if ema_col in result_df.columns:
                ema_value = result_df[ema_col].iloc[-1]
                if pd.notna(ema_value):
                    period = ema_col.split('_')[1]
                    diff = latest.close - ema_value
                    diff_pct = (diff / ema_value) * 100
                    print(f"   EMA({period}): ${ema_value:,.2f} (Price {diff_pct:+.2f}% from EMA)")

        # MACD Analysis
        print(f"\n📈 MACD (Moving Average Convergence Divergence)")
        if 'macd' in result_df.columns:
            macd = result_df['macd'].iloc[-1]
            macd_signal = result_df['macd_signal'].iloc[-1]
            macd_hist = result_df['macd_hist'].iloc[-1]

            if pd.notna(macd):
                print(f"   MACD Line:   {macd:.2f}")
                print(f"   Signal Line: {macd_signal:.2f}")
                print(f"   Histogram:   {macd_hist:.2f}")

                if macd > macd_signal:
                    print(f"   Status: 🟢 Bullish (MACD above Signal)")
                else:
                    print(f"   Status: 🔴 Bearish (MACD below Signal)")

        # Bollinger Bands
        print(f"\n📊 BOLLINGER BANDS")
        if 'bb_upper' in result_df.columns:
            bb_upper = result_df['bb_upper'].iloc[-1]
            bb_middle = result_df['bb_middle'].iloc[-1]
            bb_lower = result_df['bb_lower'].iloc[-1]

            if pd.notna(bb_upper):
                print(f"   Upper Band:  ${bb_upper:,.2f}")
                print(f"   Middle Band: ${bb_middle:,.2f}")
                print(f"   Lower Band:  ${bb_lower:,.2f}")

                # Position relative to bands
                bb_range = bb_upper - bb_lower
                position = (latest.close - bb_lower) / bb_range * 100
                print(f"   Price Position: {position:.1f}% of band range")

                if latest.close > bb_upper:
                    print(f"   Status: 🔴 Above upper band (Overbought)")
                elif latest.close < bb_lower:
                    print(f"   Status: 🟢 Below lower band (Oversold)")
                else:
                    print(f"   Status: ⚪ Within bands (Normal)")

        # Store in report
        report["timeframes"][interval] = {
            "description": description,
            "candle_count": len(candles),
            "latest_time": latest.timestamp.isoformat(),
            "price": {
                "open": float(latest.open),
                "high": float(latest.high),
                "low": float(latest.low),
                "close": float(latest.close),
                "change": float(price_change),
                "change_pct": float(price_change_pct)
            },
            "volume": {
                "current": float(latest.volume),
                "total": float(total_volume),
                "average": float(avg_volume)
            },
            "indicators": {}
        }

        # Add RSI
        if rsi_6_result:
            report["timeframes"][interval]["indicators"]["rsi_6"] = {
                "value": float(rsi_6_result['rsi']),
                "zone": rsi_6_result['zone'].value
            }

        if rsi_14_result:
            report["timeframes"][interval]["indicators"]["rsi_14"] = {
                "value": float(rsi_14_result['rsi']),
                "zone": rsi_14_result['zone'].value
            }

        # Add EMAs
        for ema_col in ema_periods:
            if ema_col in result_df.columns:
                ema_value = result_df[ema_col].iloc[-1]
                if pd.notna(ema_value):
                    period = ema_col.split('_')[1]
                    report["timeframes"][interval]["indicators"][f"ema_{period}"] = float(ema_value)

        # Add MACD
        if 'macd' in result_df.columns and pd.notna(result_df['macd'].iloc[-1]):
            report["timeframes"][interval]["indicators"]["macd"] = {
                "macd": float(result_df['macd'].iloc[-1]),
                "signal": float(result_df['macd_signal'].iloc[-1]),
                "histogram": float(result_df['macd_hist'].iloc[-1])
            }

        # Add Bollinger Bands
        if 'bb_upper' in result_df.columns and pd.notna(result_df['bb_upper'].iloc[-1]):
            report["timeframes"][interval]["indicators"]["bollinger_bands"] = {
                "upper": float(result_df['bb_upper'].iloc[-1]),
                "middle": float(result_df['bb_middle'].iloc[-1]),
                "lower": float(result_df['bb_lower'].iloc[-1])
            }

    # Focus on 15m timeframe for expert comparison
    print(f"\n{'=' * 80}")
    print("FOCUS: 15-MINUTE TIMEFRAME FOR EXPERT COMPARISON")
    print(f"{'=' * 80}")

    if "15m" in report["timeframes"]:
        tf_15m = report["timeframes"]["15m"]

        print(f"\n🎯 KEY METRICS FOR COMPARISON WITH BINANCE 15M CHART:")
        print(f"\n1. PRICE:")
        print(f"   Current: ${tf_15m['price']['close']:,.2f}")
        print(f"   Change:  {tf_15m['price']['change_pct']:+.2f}%")

        print(f"\n2. VOLUME:")
        print(f"   Current Candle: {tf_15m['volume']['current']:.2f} BTC")
        print(f"   Average:        {tf_15m['volume']['average']:.2f} BTC")

        print(f"\n3. RSI:")
        if 'rsi_14' in tf_15m['indicators']:
            rsi = tf_15m['indicators']['rsi_14']
            print(f"   RSI(14): {rsi['value']:.2f} ({rsi['zone']})")

        print(f"\n4. EMA:")
        for key in ['ema_7', 'ema_25', 'ema_99']:
            if key in tf_15m['indicators']:
                period = key.split('_')[1]
                value = tf_15m['indicators'][key]
                print(f"   EMA({period}): ${value:,.2f}")

        print(f"\n5. MACD:")
        if 'macd' in tf_15m['indicators']:
            macd = tf_15m['indicators']['macd']
            print(f"   MACD:      {macd['macd']:.2f}")
            print(f"   Signal:    {macd['signal']:.2f}")
            print(f"   Histogram: {macd['histogram']:.2f}")

        print(f"\n6. BOLLINGER BANDS:")
        if 'bollinger_bands' in tf_15m['indicators']:
            bb = tf_15m['indicators']['bollinger_bands']
            print(f"   Upper:  ${bb['upper']:,.2f}")
            print(f"   Middle: ${bb['middle']:,.2f}")
            print(f"   Lower:  ${bb['lower']:,.2f}")

    # Save JSON report
    report_file = "documents/EXPERT_COMPARISON_REPORT.json"
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 80}")
    print(f"✅ Report saved to: {report_file}")
    print(f"{'=' * 80}")

    # Generate markdown summary
    generate_markdown_summary(report)

    return report


def generate_markdown_summary(report):
    """Generate markdown summary for expert"""

    md_content = f"""# Dashboard Indicator Report - Expert Comparison

**Generated:** {report['metadata']['generated_at']}
**Symbol:** {report['metadata']['symbol']}
**Source:** {report['metadata']['source']}

---

## Executive Summary

This report contains all technical indicators calculated by the dashboard for comparison with Binance data.

### Dashboard Configuration

- **Primary Timeframe:** 1 minute (real-time)
- **Aggregated Timeframes:** 15 minutes, 1 hour
- **RSI Periods:** 6 (dashboard default), 14 (Binance default)
- **EMA Periods:** 7, 25, 99
- **MACD Settings:** 12, 26, 9 (standard)
- **Bollinger Bands:** 20-period, 2 standard deviations

---

## 15-Minute Timeframe Analysis (PRIMARY FOCUS)

"""

    if "15m" in report["timeframes"]:
        tf = report["timeframes"]["15m"]

        md_content += f"""
### Price Data
- **Current Price:** ${tf['price']['close']:,.2f}
- **Open:** ${tf['price']['open']:,.2f}
- **High:** ${tf['price']['high']:,.2f}
- **Low:** ${tf['price']['low']:,.2f}
- **Change:** {tf['price']['change_pct']:+.2f}% (${tf['price']['change']:,.2f})

### Volume
- **Current Candle:** {tf['volume']['current']:.2f} BTC
- **Average:** {tf['volume']['average']:.2f} BTC
- **Total ({tf['candle_count']} candles):** {tf['volume']['total']:,.2f} BTC

### Technical Indicators

#### RSI (Relative Strength Index)
"""

        if 'rsi_14' in tf['indicators']:
            rsi = tf['indicators']['rsi_14']
            md_content += f"- **RSI(14):** {rsi['value']:.2f} - *{rsi['zone']}*\n"

        if 'rsi_6' in tf['indicators']:
            rsi = tf['indicators']['rsi_6']
            md_content += f"- **RSI(6):** {rsi['value']:.2f} - *{rsi['zone']}*\n"

        md_content += "\n#### EMA (Exponential Moving Average)\n"
        for key in ['ema_7', 'ema_25', 'ema_99']:
            if key in tf['indicators']:
                period = key.split('_')[1]
                value = tf['indicators'][key]
                diff = tf['price']['close'] - value
                diff_pct = (diff / value) * 100
                md_content += f"- **EMA({period}):** ${value:,.2f} (Price {diff_pct:+.2f}% from EMA)\n"

        if 'macd' in tf['indicators']:
            macd = tf['indicators']['macd']
            md_content += f"""
#### MACD (Moving Average Convergence Divergence)
- **MACD Line:** {macd['macd']:.2f}
- **Signal Line:** {macd['signal']:.2f}
- **Histogram:** {macd['histogram']:.2f}
- **Status:** {'🟢 Bullish' if macd['macd'] > macd['signal'] else '🔴 Bearish'}
"""

        if 'bollinger_bands' in tf['indicators']:
            bb = tf['indicators']['bollinger_bands']
            price = tf['price']['close']
            bb_range = bb['upper'] - bb['lower']
            position = (price - bb['lower']) / bb_range * 100

            md_content += f"""
#### Bollinger Bands
- **Upper Band:** ${bb['upper']:,.2f}
- **Middle Band:** ${bb['middle']:,.2f}
- **Lower Band:** ${bb['lower']:,.2f}
- **Price Position:** {position:.1f}% of band range
"""

    # Add other timeframes
    md_content += "\n---\n\n## Other Timeframes\n\n"

    for tf_key in ['1m', '5m', '1h']:
        if tf_key in report["timeframes"]:
            tf = report["timeframes"][tf_key]
            md_content += f"""
### {tf_key.upper()} - {tf['description']}

**Price:** ${tf['price']['close']:,.2f} ({tf['price']['change_pct']:+.2f}%)
"""
            if 'rsi_14' in tf['indicators']:
                md_content += f"**RSI(14):** {tf['indicators']['rsi_14']['value']:.2f}  \n"

            if 'ema_7' in tf['indicators']:
                md_content += f"**EMA(7):** ${tf['indicators']['ema_7']:,.2f}  \n"

            md_content += "\n"

    md_content += """
---

## How to Compare with Binance

### Step 1: Open Binance Chart
1. Go to Binance.com
2. Select BTC/USDT
3. Set timeframe to **15m**

### Step 2: Add Indicators
1. Click "Indicators" button
2. Add: RSI(14), EMA(7, 25, 99), MACD, Bollinger Bands

### Step 3: Compare Values
Compare the values in this report with what you see on Binance chart at the same timestamp.

### Expected Differences
- **Minor price differences:** Due to timing (report is snapshot, Binance is live)
- **Volume differences:** Dashboard shows per-candle, Binance may show 24h
- **Indicator lag:** Indicators update as new candles form

### What Should Match
- ✅ RSI(14) values (within ±1)
- ✅ EMA values (within ±0.5%)
- ✅ MACD direction (bullish/bearish)
- ✅ Bollinger Band positions

---

## Notes for Expert

1. **Timestamp:** All data is from the same API call to ensure consistency
2. **Calculation Method:** Using TA-Lib library (industry standard)
3. **Data Source:** Binance REST API (same as Binance chart)
4. **Precision:** All calculations use full precision, rounded for display

If you find discrepancies, please note:
- Exact timestamp of comparison
- Which indicator differs
- Expected vs actual values
- Binance chart settings used

---

**Report End**
"""

    # Save markdown
    md_file = "documents/EXPERT_COMPARISON_REPORT.md"
    with open(md_file, 'w', encoding='utf-8') as f:
        f.write(md_content)

    print(f"✅ Markdown summary saved to: {md_file}")


if __name__ == "__main__":
    generate_report()
