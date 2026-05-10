"""
Main Backtesting Script

Run comprehensive backtest on historical data to validate enhanced signals.

Usage:
    python scripts/backtesting/run_backtest.py
"""

import sys
import os
from datetime import datetime, timedelta
from pathlib import Path
import logging

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from scripts.backtesting.data_loader import HistoricalDataLoader
from scripts.backtesting.trade_simulator import TradeSimulator
from scripts.backtesting.performance_analyzer import PerformanceAnalyzer
from scripts.backtesting.report_generator import ReportGenerator
from src.application.signals.signal_generator import SignalGenerator
from src.infrastructure.indicators.talib_calculator import TALibCalculator
from src.application.services.entry_price_calculator import EntryPriceCalculator
from src.application.services.tp_calculator import TPCalculator
from src.application.services.stop_loss_calculator import StopLossCalculator
from src.application.services.confidence_calculator import ConfidenceCalculator

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_backtest(
    symbol: str = 'BTCUSDT',
    timeframe: str = '15m',
    months: int = 3,
    initial_capital: float = 10000.0
):
    """
    Run backtest on historical data

    Args:
        symbol: Trading pair
        timeframe: Candle timeframe
        months: Number of months to backtest
        initial_capital: Starting capital
    """
    logger.info("="*60)
    logger.info("STARTING BACKTEST")
    logger.info("="*60)

    # Calculate date range
    end_date = datetime.now()
    start_date = end_date - timedelta(days=months * 30)

    logger.info(f"Symbol: {symbol}")
    logger.info(f"Timeframe: {timeframe}")
    logger.info(f"Period: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    logger.info(f"Initial Capital: ${initial_capital:,.2f}")
    logger.info("")

    # Step 1: Load historical data
    logger.info("Step 1: Loading historical data...")
    data_loader = HistoricalDataLoader()

    try:
        candles = data_loader.load_candles(
            symbol=symbol,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date
        )

        if not candles:
            logger.error("No candles loaded. Exiting.")
            return

        logger.info(f"Loaded {len(candles)} candles")

        # Validate data
        if not data_loader.validate_data(candles):
            logger.warning("Data validation failed, but continuing...")

    except Exception as e:
        logger.error(f"Error loading data: {e}")
        return

    # Step 2: Initialize components
    logger.info("\nStep 2: Initializing components...")

    # Initialize calculators
    talib_calc = TALibCalculator()
    entry_calc = EntryPriceCalculator()
    tp_calc = TPCalculator()
    sl_calc = StopLossCalculator()
    conf_calc = ConfidenceCalculator()

    # New calculators for DI
    from src.infrastructure.indicators.vwap_calculator import VWAPCalculator
    from src.infrastructure.indicators.bollinger_calculator import BollingerCalculator
    from src.infrastructure.indicators.stoch_rsi_calculator import StochRSICalculator
    from src.application.services.smart_entry_calculator import SmartEntryCalculator

    vwap_calc = VWAPCalculator()
    bb_calc = BollingerCalculator()
    stoch_calc = StochRSICalculator()
    smart_entry_calc = SmartEntryCalculator()

    # Use improved strategy with filters but NORMAL mode (not strict)
    signal_generator = SignalGenerator(
        talib_calculator=talib_calc,
        vwap_calculator=vwap_calc,
        bollinger_calculator=bb_calc,
        stoch_rsi_calculator=stoch_calc,
        smart_entry_calculator=smart_entry_calc,
        entry_calculator=entry_calc,
        tp_calculator=tp_calc,
        stop_loss_calculator=sl_calc,
        confidence_calculator=conf_calc,
        account_size=initial_capital,
        use_filters=True,   # Enable trend and volatility filters
        strict_mode=False   # Use NORMAL mode
    )

    trade_simulator = TradeSimulator(initial_capital=initial_capital)

    logger.info("Strategy configuration:")
    logger.info("  - Filters: ENABLED (Trend + Volatility)")
    logger.info("  - Strict Mode: DISABLED (using normal thresholds)")
    logger.info("  - RSI: 30/70 (normal), Volume: 2.0x, Conditions: 2+")
    logger.info("  - ATR-based stops: ENABLED")
    logger.info("  - Position sizing: 1% risk rule")

    # Step 3: Generate signals and simulate trades
    logger.info("\nStep 3: Generating signals and simulating trades...")
    signals_generated = 0
    trades_executed = 0

    # Need enough candles for indicators (50 for EMA50 trend filter)
    min_candles = 50  # Increased from 30 to support EMA50 filter

    for i in range(min_candles, len(candles)):
        # Get candle window for analysis
        candle_window = candles[max(0, i-100):i+1]
        current_candle = candles[i]

        # Generate signal (now fully enriched)
        signal = signal_generator.generate_signal(candle_window)

        if signal and signal.signal_type.value.upper() in ['BUY', 'SELL']:
            signals_generated += 1

            # Execute trade
            trade = trade_simulator.execute_signal(
                signal=signal,
                candles=candle_window
            )

            if trade:
                trades_executed += 1

        # Update open trades
        trade_simulator.update_trades(current_candle)

        # Progress indicator
        if i % 500 == 0:
            progress = (i / len(candles)) * 100
            logger.info(f"Progress: {progress:.1f}% - Signals: {signals_generated}, Trades: {trades_executed}")

    logger.info(f"\nSignals generated: {signals_generated}")
    logger.info(f"Trades executed: {trades_executed}")

    # Step 4: Analyze performance
    logger.info("\nStep 4: Analyzing performance...")
    analyzer = PerformanceAnalyzer()

    results = analyzer.analyze(
        trades=trade_simulator.trades,
        equity_curve=trade_simulator.equity_curve,
        initial_capital=initial_capital
    )

    # Step 5: Generate report
    logger.info("\nStep 5: Generating report...")
    report_gen = ReportGenerator()

    summary = report_gen.generate_summary(
        results=results,
        symbol=symbol,
        timeframe=timeframe,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital
    )

    trade_log = report_gen.generate_trade_log(results.trades)

    # Print to console
    print(summary)
    print(trade_log)

    # Export to file
    output_dir = project_root / "documents" / "backtesting"
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_file = output_dir / f"backtest_results_{timestamp}.txt"

    report_gen.export_results(
        results=results,
        summary=summary,
        trade_log=trade_log,
        output_path=str(output_file)
    )

    # Print summary table
    report_gen.print_summary_table(results)

    logger.info(f"\n✅ Backtest complete! Results saved to: {output_file}")


if __name__ == "__main__":
    # Run backtest with default parameters
    # Run backtest
    run_backtest(
        symbol="BTCUSDT",
        timeframe="15m",
        months=1  # 30 days for quick validation
    )
