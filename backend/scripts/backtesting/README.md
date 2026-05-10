# 📊 Backtesting Framework

Comprehensive backtesting framework for validating Layer 1 Enhanced Signals with historical data.

## 🎯 Purpose

Validate trading signals by:
- Running signals on 3 months of historical BTC/USDT data
- Simulating trade execution with Entry/TP/SL levels
- Calculating comprehensive performance metrics
- Generating detailed reports

## 📁 Components

### 1. `data_loader.py`
Loads historical candle data from Binance API.

**Features:**
- Load candles for any timeframe (15m, 1h, etc.)
- Validate data completeness
- Handle missing data

### 2. `trade_simulator.py`
Simulates trade execution based on signals.

**Features:**
- Execute trades at Entry price
- Track TP1/TP2/TP3 hits
- Track Stop Loss hits
- Calculate P&L per trade
- Manage position sizing (1% risk)

### 3. `performance_analyzer.py`
Calculates comprehensive performance metrics.

**Metrics:**
- Win rate
- Average R:R ratio
- Maximum drawdown
- Sharpe ratio
- Profit factor
- Exit breakdown

### 4. `report_generator.py`
Generates backtest reports.

**Outputs:**
- Text summary
- Detailed trade log
- Performance metrics table
- Export to file

### 5. `run_backtest.py`
Main script to run backtest.

## 🚀 Usage

### Quick Start

```bash
# Run backtest with default parameters
python scripts/backtesting/run_backtest.py
```

### Custom Parameters

```python
from scripts.backtesting.run_backtest import run_backtest

# Run custom backtest
run_backtest(
    symbol='BTCUSDT',
    timeframe='15m',
    months=3,
    initial_capital=10000.0
)
```

## 📊 Success Criteria

The backtest validates signals against professional standards:

| Metric | Target | Description |
|--------|--------|-------------|
| Win Rate | > 70% | Percentage of winning trades |
| Avg R:R | > 1.5 | Average risk/reward ratio |
| Max DD | < 15% | Maximum drawdown percentage |
| Sharpe | > 1.0 | Risk-adjusted returns |
| Profit Factor | > 1.5 | Gross profit / Gross loss |

## 📈 Output Example

```
=================================================================
BACKTEST RESULTS - BTCUSDT 15m
=================================================================
Period: 2025-08-19 to 2025-11-19 (3 months)
Initial Capital: $10,000

TRADE STATISTICS:
-----------------------------------------------------------------
Total Trades:        45
Winning Trades:      33 (73.3%)  ✅ Target: >70%
Losing Trades:       12 (26.7%)
Win Rate:            73.3%       ✅ PASS

PROFIT & LOSS:
-----------------------------------------------------------------
Total P&L:           $1,250.00
Total Return:        12.5%
Average Win:         $85.50
Average Loss:        -$42.30
Avg R:R Ratio:       2.02        ✅ Target: >1.5
Profit Factor:       1.85        ✅ Target: >1.5

RISK METRICS:
-----------------------------------------------------------------
Max Drawdown:        $450.00 (4.5%)   ✅ Target: <15%
Sharpe Ratio:        1.45             ✅ Target: >1.0

EXIT BREAKDOWN:
-----------------------------------------------------------------
TP1 Hit:             18 (40.0%)
TP2 Hit:             10 (22.2%)
TP3 Hit:             5 (11.1%)
Stop Loss Hit:       12 (26.7%)

=================================================================
✅ BACKTEST PASSED ALL TARGETS!
=================================================================
```

## 🔧 Configuration

### Backtest Parameters

```python
# In run_backtest.py

# Symbol to backtest
symbol = 'BTCUSDT'

# Timeframe (15m recommended for Layer 1)
timeframe = '15m'

# Number of months to backtest
months = 3

# Starting capital
initial_capital = 10000.0

# Max hold time per trade
max_hold_time = timedelta(hours=24)
```

### Risk Management

```python
# In trade_simulator.py

# Maximum risk per trade (1%)
max_risk_pct = 0.01

# Position sizing based on stop loss distance
position_size = (capital * max_risk_pct) / stop_loss_distance
```

## 📝 Trade Simulation Logic

### Entry Execution
- Trade opens at signal's Entry Price
- Position size calculated for 1% risk
- Stop Loss and TP levels set

### Exit Conditions (checked in order)
1. **Timeout**: Max hold time exceeded (24h)
2. **Stop Loss**: Price hits SL level
3. **TP3**: Price hits highest target (best case)
4. **TP2**: Price hits medium target
5. **TP1**: Price hits first target

### P&L Calculation
```python
# For BUY trades
pnl = (exit_price - entry_price) * position_size

# For SELL trades
pnl = (entry_price - exit_price) * position_size
```

## 🧪 Testing

### Unit Tests

```bash
# Test data loader
pytest tests/backtesting/test_data_loader.py

# Test trade simulator
pytest tests/backtesting/test_trade_simulator.py

# Test performance analyzer
pytest tests/backtesting/test_performance_analyzer.py
```

## 📊 Output Files

Results are saved to `documents/backtesting/`:

```
documents/backtesting/
└── backtest_results_20251119_143022.txt
```

Each file contains:
- Summary with all metrics
- Detailed trade log
- Performance analysis

## ⚠️ Limitations

### Assumptions
- **No slippage**: Executes at exact prices
- **No fees**: Conservative estimate
- **Instant execution**: No delays
- **Perfect information**: No data gaps

### Not Included
- Market impact
- Liquidity constraints
- Real-world execution delays
- Trading fees/commissions

## 🎓 Interpretation

### Good Results
- ✅ Win rate > 70%
- ✅ Consistent profits
- ✅ Low drawdown
- ✅ High Sharpe ratio

### Warning Signs
- ⚠️ Win rate < 60%
- ⚠️ High drawdown (> 20%)
- ⚠️ Low Sharpe (< 0.5)
- ⚠️ Profit factor < 1.0

### Next Steps
- If PASS: Deploy to live trading
- If FAIL: Optimize parameters
- If MARGINAL: More testing needed

## 🔄 Workflow

1. **Load Data**: Get 3 months of 15m candles
2. **Generate Signals**: Run SignalGenerator on each candle
3. **Enhance Signals**: Add Entry/TP/SL levels
4. **Simulate Trades**: Execute and track outcomes
5. **Analyze Performance**: Calculate all metrics
6. **Generate Report**: Create summary and trade log

## 📚 References

- **Spec**: `.kiro/specs/layer1-enhancement/`
- **Plan**: `TASK_9_BACKTESTING_PLAN.md`
- **Requirements**: Task 9 in `tasks.md`

## 🎯 Success Metrics

**Target Performance:**
- Win Rate: > 70% ✅
- Avg R:R: > 1.5 ✅
- Max DD: < 15% ✅
- Sharpe: > 1.0 ✅
- Profit Factor: > 1.5 ✅

**If all targets met:**
- ✅ Signals are professional-grade
- ✅ Ready for live trading
- ✅ Risk management validated

---

**Ready to validate your signals!** 🚀

Run: `python scripts/backtesting/run_backtest.py`
