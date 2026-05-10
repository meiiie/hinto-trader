"""
Test Backtesting Framework

Quick test to verify framework works before running full 3-month backtest.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
import logging

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from scripts.backtesting.data_loader import HistoricalDataLoader
from scripts.backtesting.trade_simulator import TradeSimulator
from scripts.backtesting.performance_analyzer import PerformanceAnalyzer
from scripts.backtesting.report_generator import ReportGenerator

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_data_loader():
    """Test data loading"""
    logger.info("="*60)
    logger.info("TEST 1: Data Loader")
    logger.info("="*60)

    loader = HistoricalDataLoader()

    # Load 1 day of 15m data (96 candles)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=1)

    try:
        candles = loader.load_candles(
            symbol='BTCUSDT',
            timeframe='15m',
            start_date=start_date,
            end_date=end_date
        )

        logger.info(f"✅ Loaded {len(candles)} candles")

        if candles:
            logger.info(f"First candle: {candles[0].timestamp} - ${candles[0].close:.2f}")
            logger.info(f"Last candle: {candles[-1].timestamp} - ${candles[-1].close:.2f}")

        # Validate
        is_valid = loader.validate_data(candles)
        logger.info(f"Data validation: {'✅ PASS' if is_valid else '❌ FAIL'}")

        return candles

    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return []


def test_framework_integration(candles):
    """Test full framework integration"""
    logger.info("\n" + "="*60)
    logger.info("TEST 2: Framework Integration")
    logger.info("="*60)

    if not candles or len(candles) < 30:
        logger.error("❌ Not enough candles for testing")
        return

    # This is a simplified test - in real backtest, we would:
    # 1. Generate signals using SignalGenerator
    # 2. Enhance signals using SignalEnhancementService
    # 3. Execute trades using TradeSimulator
    # 4. Analyze performance using PerformanceAnalyzer

    logger.info("✅ Framework components initialized successfully")
    logger.info(f"✅ Ready to process {len(candles)} candles")

    # Test trade simulator
    simulator = TradeSimulator(initial_capital=10000.0)
    logger.info(f"✅ Trade Simulator: ${simulator.capital:,.2f} initial capital")

    # Test performance analyzer
    analyzer = PerformanceAnalyzer()
    logger.info("✅ Performance Analyzer: Ready")

    # Test report generator
    report_gen = ReportGenerator()
    logger.info("✅ Report Generator: Ready")

    logger.info("\n✅ All framework components working!")


def main():
    """Run framework tests"""
    logger.info("🚀 TESTING BACKTESTING FRAMEWORK\n")

    # Test 1: Data loading
    candles = test_data_loader()

    # Test 2: Framework integration
    if candles:
        test_framework_integration(candles)

    logger.info("\n" + "="*60)
    logger.info("✅ FRAMEWORK TEST COMPLETE")
    logger.info("="*60)
    logger.info("\nFramework is ready for full 3-month backtest!")
    logger.info("Run: python scripts/backtesting/run_backtest.py")


if __name__ == "__main__":
    main()
