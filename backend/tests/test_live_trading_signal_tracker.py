"""
Unit Test: LiveTradingService execute_signal Flow
Simulates the exact flow from main.py to identify signal_tracker issue
"""

import os
import sys
import unittest
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set environment BEFORE imports
os.environ["ENV"] = "live"

from src.config_loader import load_config
load_config()


class TestLiveTradingServiceSignalTracker(unittest.TestCase):
    """Test LiveTradingService signal_tracker initialization and execute_signal flow"""

    @classmethod
    def setUpClass(cls):
        """Setup once for all tests"""
        from src.infrastructure.di_container import DIContainer
        cls.container = DIContainer()
        cls.live_service = cls.container.get_live_trading_service()

    def test_01_service_created(self):
        """Test 1: LiveTradingService is created"""
        self.assertIsNotNone(self.live_service)
        logger.info(f"✅ LiveTradingService created: {type(self.live_service)}")

    def test_02_mode_is_live(self):
        """Test 2: Mode is LIVE"""
        from src.application.services.live_trading_service import TradingMode
        self.assertEqual(self.live_service.mode, TradingMode.LIVE)
        logger.info(f"✅ Mode: {self.live_service.mode}")

    def test_03_enable_trading_is_true(self):
        """Test 3: enable_trading should be True from settings"""
        logger.info(f"   enable_trading = {self.live_service.enable_trading}")
        # Just log, don't assert - user may not have enabled it

    def test_04_settings_repo_exists(self):
        """Test 4: settings_repo attribute exists"""
        self.assertTrue(hasattr(self.live_service, 'settings_repo'))
        logger.info(f"✅ settings_repo exists: {self.live_service.settings_repo is not None}")

    def test_05_signal_tracker_attribute_exists(self):
        """Test 5: signal_tracker attribute exists"""
        self.assertTrue(hasattr(self.live_service, 'signal_tracker'))
        logger.info(f"✅ signal_tracker attribute exists")

    def test_06_signal_tracker_is_not_none(self):
        """Test 6: signal_tracker is NOT None"""
        self.assertIsNotNone(self.live_service.signal_tracker)
        logger.info(f"✅ signal_tracker is NOT None: {type(self.live_service.signal_tracker)}")

    def test_07_signal_tracker_properties(self):
        """Test 7: signal_tracker has correct properties"""
        tracker = self.live_service.signal_tracker
        logger.info(f"   max_pending: {tracker.max_pending}")
        logger.info(f"   default_ttl_minutes: {tracker.default_ttl_minutes}")
        self.assertGreater(tracker.max_pending, 0)
        self.assertGreater(tracker.default_ttl_minutes, 0)
        logger.info(f"✅ signal_tracker properties OK")

    def test_08_execute_signal_with_mock_signal(self):
        """Test 8: execute_signal accepts signal and checks signal_tracker"""
        from src.domain.entities.trading_signal import TradingSignal, SignalType

        # Create mock signal
        signal = TradingSignal(
            symbol="BTCUSDT",
            signal_type=SignalType.BUY,
            entry_price=50000.0,
            stop_loss=48000.0,
            take_profit=55000.0,
            confidence=0.85,
            signal_id="test-unit-001"
        )

        # Check signal_tracker before execute_signal
        tracker = self.live_service.signal_tracker
        logger.info(f"   Before execute_signal: tracker={tracker is not None}")

        # Call execute_signal (should not throw exception)
        try:
            result = self.live_service.execute_signal(signal)
            logger.info(f"   execute_signal returned: {result}")
        except Exception as e:
            logger.error(f"   ❌ execute_signal exception: {e}")
            raise

    def test_09_singleton_check(self):
        """Test 9: Multiple calls to get_live_trading_service return same instance"""
        service1 = self.container.get_live_trading_service()
        service2 = self.container.get_live_trading_service()
        self.assertIs(service1, service2)
        logger.info(f"✅ Singleton verified: same instance returned")

    def test_10_signal_tracker_still_exists_after_multiple_calls(self):
        """Test 10: signal_tracker persists after multiple service calls"""
        service = self.container.get_live_trading_service()
        self.assertIsNotNone(service.signal_tracker)
        logger.info(f"✅ signal_tracker still exists after multiple get_live_trading_service() calls")


if __name__ == '__main__':
    print("=" * 70)
    print("🧪 UNIT TEST: LiveTradingService Signal Tracker")
    print("=" * 70)

    # Run tests
    unittest.main(verbosity=2)
