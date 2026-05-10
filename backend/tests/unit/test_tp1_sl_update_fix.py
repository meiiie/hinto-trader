"""
Test case for CRITICAL FIX: SL must be updated to breakeven when TP1 hits,
even if partial close fails.

Bug: Before fix, if partial close failed, SL was not updated to breakeven.
This left the position unprotected with original SL.

Fix: Update SL to breakeven IMMEDIATELY when TP1 hits, before partial close.
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timedelta

# Use conftest.py setup instead of manual path manipulation
from src.application.services.position_monitor_service import (
    PositionMonitorService,
    MonitoredPosition,
    PositionPhase
)


class TestTP1SLUpdateFix:
    """Test that SL is updated to breakeven when TP1 hits, regardless of partial close result."""

    def setup_method(self):
        """Reset singleton before each test."""
        import src.application.services.position_monitor_service as pms
        pms._position_monitor = None

    def test_sl_updated_even_when_partial_close_fails(self):
        """
        CRITICAL TEST: SL must be updated to breakeven even if partial close fails.

        Scenario:
        - LONG position: Entry $100, SL $95, TP $110
        - TP1 hits at $110
        - Partial close FAILS (callback returns False)
        - SL should still be updated to breakeven (~$100.05)
        """
        monitor = PositionMonitorService()

        # Track persist calls
        persist_sl_calls = []
        persist_tp_hit_calls = []
        persist_phase_calls = []

        def mock_persist_sl(symbol, new_sl, entry_price=0.0, side=''):
            persist_sl_calls.append({'symbol': symbol, 'sl': new_sl, 'entry_price': entry_price, 'side': side})

        def mock_persist_tp_hit(symbol, count):
            persist_tp_hit_calls.append({'symbol': symbol, 'count': count})

        def mock_persist_phase(symbol, phase, is_be):
            persist_phase_calls.append({'symbol': symbol, 'phase': phase, 'is_be': is_be})

        # Mock partial close to FAIL
        def mock_partial_close_fail(symbol, price, pct):
            return False  # Simulate failure

        monitor._persist_sl = mock_persist_sl
        monitor._persist_tp_hit = mock_persist_tp_hit
        monitor._persist_phase = mock_persist_phase
        monitor._partial_close = mock_partial_close_fail
        monitor._close_position = Mock()  # Fallback

        # Create LONG position
        pos = MonitoredPosition(
            symbol='BTCUSDT',
            side='LONG',
            entry_price=100.0,
            quantity=1.0,
            leverage=10,
            initial_sl=95.0,
            initial_tp=110.0,
            atr=2.0
        )
        pos.entry_time = datetime.now() - timedelta(seconds=60)  # Past grace period

        monitor.start_monitoring(pos)

        # Verify initial state
        assert pos.current_sl == 95.0
        assert pos.phase == PositionPhase.ENTRY

        # Trigger TP1 hit
        monitor._on_tp1_hit(pos, 110.0)

        # CRITICAL ASSERTIONS:
        # 1. SL should be updated to breakeven (entry + buffer)
        expected_sl = 100.0 + (100.0 * 0.0005)  # BREAKEVEN_BUFFER_PCT = 0.0005
        assert pos.current_sl == pytest.approx(expected_sl, rel=0.001), \
            f"SL should be breakeven {expected_sl}, got {pos.current_sl}"

        # 2. Phase should be TRAILING
        assert pos.phase == PositionPhase.TRAILING

        # 3. tp_hit_count should be 1
        assert pos.tp_hit_count == 1

        # 4. is_breakeven should be True
        assert pos.is_breakeven == True

        # 5. SL should have been persisted
        assert len(persist_sl_calls) == 1
        assert persist_sl_calls[0]['symbol'] == 'BTCUSDT'
        assert persist_sl_calls[0]['sl'] == pytest.approx(expected_sl, rel=0.001)

        # 6. tp_hit_count should have been persisted
        assert len(persist_tp_hit_calls) == 1
        assert persist_tp_hit_calls[0]['count'] == 1

        # 7. Phase should have been persisted
        assert len(persist_phase_calls) == 1
        assert persist_phase_calls[0]['phase'] == 'TRAILING'

    def test_sl_updated_for_short_position_when_partial_close_fails(self):
        """
        Test SHORT position: SL should be updated to breakeven (below entry).

        Scenario:
        - SHORT position: Entry $0.1505, SL $0.1535, TP $0.1480
        - TP1 hits at $0.1480
        - Partial close FAILS
        - SL should be updated to breakeven (~$0.1504)
        """
        monitor = PositionMonitorService()

        persist_sl_calls = []

        def mock_persist_sl(symbol, new_sl, entry_price=0.0, side=''):
            persist_sl_calls.append({'symbol': symbol, 'sl': new_sl, 'entry_price': entry_price, 'side': side})

        monitor._persist_sl = mock_persist_sl
        monitor._persist_tp_hit = Mock()
        monitor._persist_phase = Mock()
        monitor._partial_close = Mock(return_value=False)  # FAIL
        monitor._close_position = Mock()

        # Create SHORT position (like DOGEUSDT from user report)
        pos = MonitoredPosition(
            symbol='DOGEUSDT',
            side='SHORT',
            entry_price=0.1505,
            quantity=100.0,
            leverage=10,
            initial_sl=0.1535,  # Above entry for SHORT
            initial_tp=0.1480,  # Below entry for SHORT
            atr=0.002
        )
        pos.entry_time = datetime.now() - timedelta(seconds=60)

        monitor.start_monitoring(pos)

        # Verify initial state
        assert pos.current_sl == 0.1535

        # Trigger TP1 hit
        monitor._on_tp1_hit(pos, 0.1480)

        # For SHORT: breakeven SL = entry - buffer (below entry)
        expected_sl = 0.1505 - (0.1505 * 0.0005)

        # CRITICAL: SL should be BELOW entry for SHORT
        assert pos.current_sl < pos.entry_price, \
            f"SHORT SL {pos.current_sl} should be below entry {pos.entry_price}"

        assert pos.current_sl == pytest.approx(expected_sl, rel=0.001), \
            f"SL should be breakeven {expected_sl}, got {pos.current_sl}"

        # SL should have been persisted
        assert len(persist_sl_calls) == 1
        assert persist_sl_calls[0]['sl'] == pytest.approx(expected_sl, rel=0.001)

    def test_sl_updated_when_partial_close_succeeds(self):
        """
        Verify SL is still updated correctly when partial close succeeds.
        """
        monitor = PositionMonitorService()

        persist_sl_calls = []

        def mock_persist_sl(symbol, new_sl, entry_price=0.0, side=''):
            persist_sl_calls.append({'symbol': symbol, 'sl': new_sl, 'entry_price': entry_price, 'side': side})

        monitor._persist_sl = mock_persist_sl
        monitor._persist_tp_hit = Mock()
        monitor._persist_phase = Mock()
        monitor._partial_close = Mock(return_value=True)  # SUCCESS
        monitor._update_sl = Mock()

        pos = MonitoredPosition(
            symbol='ETHUSDT',
            side='LONG',
            entry_price=2000.0,
            quantity=1.0,
            leverage=10,
            initial_sl=1900.0,
            initial_tp=2200.0,
            atr=50.0
        )
        pos.entry_time = datetime.now() - timedelta(seconds=60)

        monitor.start_monitoring(pos)

        # Trigger TP1 hit
        monitor._on_tp1_hit(pos, 2200.0)

        expected_sl = 2000.0 + (2000.0 * 0.0005)

        # SL should be updated
        assert pos.current_sl == pytest.approx(expected_sl, rel=0.001)

        # Quantity should be reduced (60% closed, 40% remaining)
        assert pos.quantity == pytest.approx(0.4, rel=0.001)

        # SL should have been persisted (once, before partial close)
        assert len(persist_sl_calls) == 1


class TestTP1SLUpdateFixAsync:
    """Test async version of TP1 SL update fix."""

    def setup_method(self):
        """Reset singleton before each test."""
        import src.application.services.position_monitor_service as pms
        pms._position_monitor = None

    @pytest.mark.asyncio
    async def test_async_sl_updated_even_when_partial_close_fails(self):
        """
        Test async version: SL must be updated even if partial close fails.
        """
        monitor = PositionMonitorService()

        persist_sl_calls = []

        def mock_persist_sl(symbol, new_sl, entry_price=0.0, side=''):
            persist_sl_calls.append({'symbol': symbol, 'sl': new_sl, 'entry_price': entry_price, 'side': side})

        async def mock_partial_close_async_fail(symbol, price, pct):
            return False  # FAIL

        monitor._persist_sl = mock_persist_sl
        monitor._persist_tp_hit = Mock()
        monitor._persist_phase = Mock()
        monitor._partial_close_async = mock_partial_close_async_fail

        pos = MonitoredPosition(
            symbol='BTCUSDT',
            side='LONG',
            entry_price=100.0,
            quantity=1.0,
            leverage=10,
            initial_sl=95.0,
            initial_tp=110.0,
            atr=2.0
        )
        pos.entry_time = datetime.now() - timedelta(seconds=60)

        monitor.start_monitoring(pos)

        # Trigger async TP1 hit
        await monitor._on_tp1_hit_async(pos, 110.0)

        expected_sl = 100.0 + (100.0 * 0.0005)

        # SL should be updated to breakeven
        assert pos.current_sl == pytest.approx(expected_sl, rel=0.001)

        # SL should have been persisted
        assert len(persist_sl_calls) == 1


class TestWatermarkCreation:
    """Test that watermarks are created when missing during persist operations."""

    def setup_method(self):
        """Reset singleton before each test."""
        import src.application.services.position_monitor_service as pms
        pms._position_monitor = None

    def test_persist_sl_creates_watermark_when_missing(self):
        """
        CRITICAL TEST: _persist_sl_to_db should create watermark if not exists.

        Bug: Before fix, if watermark didn't exist, SL update was silently ignored.
        Fix: Create minimal watermark entry when key is missing.

        **Validates: Requirements 1.1, 1.4**
        """
        from unittest.mock import Mock, MagicMock
        from src.application.services.live_trading_service import LiveTradingService

        # Create service with mocked dependencies
        service = LiveTradingService.__new__(LiveTradingService)
        service._position_watermarks = {}  # Empty watermarks
        service.order_repo = Mock()
        service.order_repo.update_live_position_sl = Mock()
        service.logger = MagicMock()
        service._portfolio_cache = None  # Required for cache invalidation
        service._portfolio_cache_time = 0  # Required for cache invalidation
        service.active_positions = {}  # Required for fallback lookup
        service._broadcast_sl_update = Mock()  # Required for WebSocket broadcast

        # Call _persist_sl_to_db with symbol NOT in watermarks
        symbol = 'BTCUSDT'
        new_sl = 50000.0

        result = service._persist_sl_to_db(symbol, new_sl)

        # CRITICAL ASSERTIONS:
        # 1. Watermark should now exist
        assert symbol in service._position_watermarks, \
            f"Watermark should be created for {symbol}"

        # 2. Watermark should have correct SL
        assert service._position_watermarks[symbol]['current_sl'] == new_sl, \
            f"Watermark SL should be {new_sl}"

        # 3. Watermark should have default values for TP1 hit scenario
        assert service._position_watermarks[symbol]['tp_target'] == 0
        assert service._position_watermarks[symbol]['is_breakeven'] == True
        assert service._position_watermarks[symbol]['tp_hit_count'] == 1
        assert service._position_watermarks[symbol]['phase'] == 'TRAILING'

        # 4. DB should be updated
        service.order_repo.update_live_position_sl.assert_called_once_with(symbol, new_sl)

        # 5. Warning should be logged
        service.logger.warning.assert_called()

        # 6. Function should return True
        assert result == True

    def test_persist_sl_updates_existing_watermark(self):
        """
        Test that _persist_sl_to_db updates existing watermark correctly.

        **Validates: Requirements 1.1**
        """
        from unittest.mock import Mock, MagicMock
        from src.application.services.live_trading_service import LiveTradingService

        service = LiveTradingService.__new__(LiveTradingService)
        service._position_watermarks = {
            'BTCUSDT': {
                'current_sl': 45000.0,
                'tp_target': 55000.0,
                'is_breakeven': False,
                'tp_hit_count': 0,
                'phase': 'ENTRY'
            }
        }
        service.order_repo = Mock()
        service.order_repo.update_live_position_sl = Mock()
        service.logger = MagicMock()
        service._portfolio_cache = None  # Required for cache invalidation
        service._portfolio_cache_time = 0  # Required for cache invalidation
        service._broadcast_sl_update = Mock()  # Required for WebSocket broadcast

        # Update SL
        new_sl = 50000.0
        result = service._persist_sl_to_db('BTCUSDT', new_sl)

        # Watermark should be updated
        assert service._position_watermarks['BTCUSDT']['current_sl'] == new_sl

        # Other fields should remain unchanged
        assert service._position_watermarks['BTCUSDT']['tp_target'] == 55000.0
        assert service._position_watermarks['BTCUSDT']['is_breakeven'] == False

        # DB should be updated
        service.order_repo.update_live_position_sl.assert_called_once()

        # INFO log should be called (not warning)
        service.logger.info.assert_called()

        assert result == True

    def test_persist_tp_hit_creates_watermark_when_missing(self):
        """
        Test that _persist_tp_hit_to_db creates watermark if not exists.

        **Validates: Requirements 1.1, 1.4**
        """
        from unittest.mock import Mock, MagicMock
        from src.application.services.live_trading_service import LiveTradingService

        service = LiveTradingService.__new__(LiveTradingService)
        service._position_watermarks = {}  # Empty
        service.order_repo = Mock()
        service.order_repo.update_live_position_tp_hit_count = Mock()
        service.logger = MagicMock()

        # Call with symbol NOT in watermarks
        result = service._persist_tp_hit_to_db('ETHUSDT', 1)

        # Watermark should be created
        assert 'ETHUSDT' in service._position_watermarks
        assert service._position_watermarks['ETHUSDT']['tp_hit_count'] == 1
        assert service._position_watermarks['ETHUSDT']['tp_target'] == 0  # Cleared after TP1

        # Warning should be logged
        service.logger.warning.assert_called()

        assert result == True

    def test_persist_phase_creates_watermark_when_missing(self):
        """
        Test that _persist_phase_to_db creates watermark if not exists.

        **Validates: Requirements 1.1, 1.4**
        """
        from unittest.mock import Mock, MagicMock
        from src.application.services.live_trading_service import LiveTradingService

        service = LiveTradingService.__new__(LiveTradingService)
        service._position_watermarks = {}  # Empty
        service.order_repo = Mock()
        service.order_repo.update_live_position_phase = Mock()
        service.logger = MagicMock()

        # Call with symbol NOT in watermarks
        result = service._persist_phase_to_db('DOGEUSDT', 'TRAILING', True)

        # Watermark should be created
        assert 'DOGEUSDT' in service._position_watermarks
        assert service._position_watermarks['DOGEUSDT']['phase'] == 'TRAILING'
        assert service._position_watermarks['DOGEUSDT']['is_breakeven'] == True

        # Warning should be logged
        service.logger.warning.assert_called()

        # DB should be updated
        service.order_repo.update_live_position_phase.assert_called_once_with('DOGEUSDT', 'TRAILING', True)

        assert result == True

    def test_persist_sl_idempotent(self):
        """
        Test that calling _persist_sl_to_db multiple times produces same result.

        **Property 2: SL Update Idempotence**
        **Validates: Requirements 1.1, 3.4**
        """
        from unittest.mock import Mock, MagicMock
        from src.application.services.live_trading_service import LiveTradingService

        service = LiveTradingService.__new__(LiveTradingService)
        service._position_watermarks = {}
        service.order_repo = Mock()
        service.order_repo.update_live_position_sl = Mock()
        service.logger = MagicMock()
        service._portfolio_cache = None  # Required for cache invalidation
        service._portfolio_cache_time = 0  # Required for cache invalidation
        service.active_positions = {}  # Required for fallback lookup
        service._broadcast_sl_update = Mock()  # Required for WebSocket broadcast

        new_sl = 50000.0

        # Call multiple times
        service._persist_sl_to_db('BTCUSDT', new_sl)
        service._persist_sl_to_db('BTCUSDT', new_sl)
        service._persist_sl_to_db('BTCUSDT', new_sl)

        # Final state should be same as after first call
        assert service._position_watermarks['BTCUSDT']['current_sl'] == new_sl

        # DB should be called 3 times
        assert service.order_repo.update_live_position_sl.call_count == 3


class TestTP1StateConsistency:
    """Test that TP1 hit updates all state fields correctly."""

    def setup_method(self):
        """Reset singleton before each test."""
        import src.application.services.position_monitor_service as pms
        pms._position_monitor = None

    def test_tp1_hit_updates_all_state_fields_long(self):
        """
        Test that TP1 hit updates all state fields correctly for LONG position.

        After TP1 hit:
        - current_sl = entry_price + buffer (breakeven)
        - is_breakeven = True
        - phase = TRAILING
        - tp_hit_count = 1

        **Property 3: TP1 Hit State Consistency**
        **Validates: Requirements 4.1, 4.2, 4.3**
        """
        monitor = PositionMonitorService()

        # Track all persist calls
        persist_calls = {
            'sl': [],
            'tp_hit': [],
            'phase': []
        }

        def mock_persist_sl(symbol, new_sl, entry_price=0.0, side=''):
            persist_calls['sl'].append({'symbol': symbol, 'sl': new_sl})

        def mock_persist_tp_hit(symbol, count):
            persist_calls['tp_hit'].append({'symbol': symbol, 'count': count})

        def mock_persist_phase(symbol, phase, is_be):
            persist_calls['phase'].append({'symbol': symbol, 'phase': phase, 'is_be': is_be})

        monitor._persist_sl = mock_persist_sl
        monitor._persist_tp_hit = mock_persist_tp_hit
        monitor._persist_phase = mock_persist_phase
        monitor._partial_close = Mock(return_value=True)
        monitor._update_sl = Mock()

        # Create LONG position
        pos = MonitoredPosition(
            symbol='BTCUSDT',
            side='LONG',
            entry_price=50000.0,
            quantity=1.0,
            leverage=10,
            initial_sl=48000.0,
            initial_tp=55000.0,
            atr=500.0
        )
        pos.entry_time = datetime.now() - timedelta(seconds=60)

        monitor.start_monitoring(pos)

        # Verify initial state
        assert pos.current_sl == 48000.0
        assert pos.phase == PositionPhase.ENTRY
        assert pos.tp_hit_count == 0
        assert pos.is_breakeven == False

        # Trigger TP1 hit
        monitor._on_tp1_hit(pos, 55000.0)

        # Calculate expected breakeven SL
        expected_sl = 50000.0 + (50000.0 * 0.0005)  # BREAKEVEN_BUFFER_PCT = 0.0005

        # CRITICAL ASSERTIONS - All state fields must be correct:

        # 1. current_sl = breakeven
        assert pos.current_sl == pytest.approx(expected_sl, rel=0.001), \
            f"current_sl should be {expected_sl}, got {pos.current_sl}"

        # 2. is_breakeven = True
        assert pos.is_breakeven == True, \
            "is_breakeven should be True after TP1 hit"

        # 3. phase = TRAILING
        assert pos.phase == PositionPhase.TRAILING, \
            f"phase should be TRAILING, got {pos.phase}"

        # 4. tp_hit_count = 1
        assert pos.tp_hit_count == 1, \
            f"tp_hit_count should be 1, got {pos.tp_hit_count}"

        # 5. All persist callbacks should have been called
        assert len(persist_calls['sl']) == 1, "SL should be persisted once"
        assert len(persist_calls['tp_hit']) == 1, "tp_hit_count should be persisted once"
        assert len(persist_calls['phase']) == 1, "phase should be persisted once"

        # 6. Persisted values should match local state
        assert persist_calls['sl'][0]['sl'] == pytest.approx(expected_sl, rel=0.001)
        assert persist_calls['tp_hit'][0]['count'] == 1
        assert persist_calls['phase'][0]['phase'] == 'TRAILING'
        assert persist_calls['phase'][0]['is_be'] == True

    def test_tp1_hit_updates_all_state_fields_short(self):
        """
        Test that TP1 hit updates all state fields correctly for SHORT position.

        For SHORT: breakeven SL = entry_price - buffer (below entry)

        **Property 3: TP1 Hit State Consistency**
        **Validates: Requirements 4.1, 4.2, 4.3**
        """
        monitor = PositionMonitorService()

        persist_calls = {'sl': [], 'tp_hit': [], 'phase': []}

        monitor._persist_sl = lambda s, sl, ep=0, side='': persist_calls['sl'].append({'symbol': s, 'sl': sl})
        monitor._persist_tp_hit = lambda s, c: persist_calls['tp_hit'].append({'symbol': s, 'count': c})
        monitor._persist_phase = lambda s, p, b: persist_calls['phase'].append({'symbol': s, 'phase': p, 'is_be': b})
        monitor._partial_close = Mock(return_value=True)
        monitor._update_sl = Mock()

        # Create SHORT position (like DOGEUSDT from user report)
        pos = MonitoredPosition(
            symbol='DOGEUSDT',
            side='SHORT',
            entry_price=0.1505,
            quantity=100.0,
            leverage=10,
            initial_sl=0.1535,  # Above entry for SHORT
            initial_tp=0.1480,  # Below entry for SHORT
            atr=0.002
        )
        pos.entry_time = datetime.now() - timedelta(seconds=60)

        monitor.start_monitoring(pos)

        # Trigger TP1 hit
        monitor._on_tp1_hit(pos, 0.1480)

        # For SHORT: breakeven SL = entry - buffer
        expected_sl = 0.1505 - (0.1505 * 0.0005)

        # All state fields must be correct:
        assert pos.current_sl == pytest.approx(expected_sl, rel=0.001)
        assert pos.is_breakeven == True
        assert pos.phase == PositionPhase.TRAILING
        assert pos.tp_hit_count == 1

        # SL should be BELOW entry for SHORT
        assert pos.current_sl < pos.entry_price

    def test_tp1_state_consistency_after_partial_close_failure(self):
        """
        Test that state is still consistent even when partial close callback is not registered.

        CRITICAL: SL should be updated to breakeven BEFORE partial close attempt.
        This ensures position is protected even if execution fails.

        Note: Current implementation uses fire-and-forget pattern for partial close.
        If callback is registered, it's considered "success" (initiated).
        If callback is NOT registered, it's a failure.

        **Validates: Requirements 4.1, 4.4**
        """
        monitor = PositionMonitorService()

        persist_calls = {'sl': [], 'tp_hit': [], 'phase': []}

        monitor._persist_sl = lambda s, sl, ep=0, side='': persist_calls['sl'].append({'symbol': s, 'sl': sl})
        monitor._persist_tp_hit = lambda s, c: persist_calls['tp_hit'].append({'symbol': s, 'count': c})
        monitor._persist_phase = lambda s, p, b: persist_calls['phase'].append({'symbol': s, 'phase': p, 'is_be': b})
        monitor._partial_close = None  # NOT REGISTERED - this causes failure
        monitor._close_position = Mock()  # Fallback

        pos = MonitoredPosition(
            symbol='ETHUSDT',
            side='LONG',
            entry_price=2000.0,
            quantity=1.0,
            leverage=10,
            initial_sl=1900.0,
            initial_tp=2200.0,
            atr=50.0
        )
        pos.entry_time = datetime.now() - timedelta(seconds=60)

        monitor.start_monitoring(pos)

        # Trigger TP1 hit (partial close will fail because callback not registered)
        monitor._on_tp1_hit(pos, 2200.0)

        expected_sl = 2000.0 + (2000.0 * 0.0005)

        # State should still be consistent:
        assert pos.current_sl == pytest.approx(expected_sl, rel=0.001)
        assert pos.is_breakeven == True
        assert pos.phase == PositionPhase.TRAILING
        assert pos.tp_hit_count == 1

        # SL should have been persisted BEFORE partial close attempt
        assert len(persist_calls['sl']) == 1
        assert persist_calls['sl'][0]['sl'] == pytest.approx(expected_sl, rel=0.001)

        # Quantity should NOT be reduced (partial close failed)
        assert pos.quantity == 1.0


class TestTP1IntegrationFlow:
    """Integration tests for end-to-end TP1 flow with watermarks."""

    def setup_method(self):
        """Reset singleton before each test."""
        import src.application.services.position_monitor_service as pms
        pms._position_monitor = None

    def test_tp1_flow_updates_watermarks_correctly(self):
        """
        Integration test: TP1 flow should update watermarks correctly.

        Flow:
        1. Create position
        2. Wire callbacks from LiveTradingService
        3. Trigger TP1
        4. Verify watermark has correct SL

        **Validates: Requirements 3.1, 3.4**
        """
        from unittest.mock import Mock, MagicMock
        from src.application.services.live_trading_service import LiveTradingService

        # Create LiveTradingService with mocked dependencies
        service = LiveTradingService.__new__(LiveTradingService)
        service._position_watermarks = {}
        service.order_repo = Mock()
        service.order_repo.update_live_position_sl = Mock()
        service.order_repo.update_live_position_tp_hit_count = Mock()
        service.order_repo.update_live_position_phase = Mock()
        service.logger = MagicMock()

        # Create PositionMonitorService
        monitor = PositionMonitorService()

        # Wire callbacks (simulating LiveTradingService._setup_position_monitor)
        monitor._persist_sl = service._persist_sl_to_db
        monitor._persist_tp_hit = service._persist_tp_hit_to_db
        monitor._persist_phase = service._persist_phase_to_db
        monitor._partial_close = Mock(return_value=True)
        monitor._update_sl = Mock()

        # Create position
        pos = MonitoredPosition(
            symbol='BTCUSDT',
            side='LONG',
            entry_price=50000.0,
            quantity=1.0,
            leverage=10,
            initial_sl=48000.0,
            initial_tp=55000.0,
            atr=500.0
        )
        pos.entry_time = datetime.now() - timedelta(seconds=60)

        # Initialize watermark (simulating position open)
        service._position_watermarks['BTCUSDT'] = {
            'current_sl': 48000.0,
            'tp_target': 55000.0,
            'is_breakeven': False,
            'tp_hit_count': 0,
            'phase': 'ENTRY',
            'entry_price': 50000.0,
            'side': 'LONG'
        }

        monitor.start_monitoring(pos)

        # Trigger TP1 hit
        monitor._on_tp1_hit(pos, 55000.0)

        # Calculate expected breakeven SL
        expected_sl = 50000.0 + (50000.0 * 0.0005)

        # CRITICAL: Verify watermark has correct SL
        assert 'BTCUSDT' in service._position_watermarks
        assert service._position_watermarks['BTCUSDT']['current_sl'] == pytest.approx(expected_sl, rel=0.001), \
            f"Watermark SL should be {expected_sl}, got {service._position_watermarks['BTCUSDT']['current_sl']}"

        # Verify other watermark fields
        assert service._position_watermarks['BTCUSDT']['tp_hit_count'] == 1
        assert service._position_watermarks['BTCUSDT']['tp_target'] == 0  # Cleared after TP1
        assert service._position_watermarks['BTCUSDT']['phase'] == 'TRAILING'
        assert service._position_watermarks['BTCUSDT']['is_breakeven'] == True

        # Verify DB was updated
        service.order_repo.update_live_position_sl.assert_called_once()
        service.order_repo.update_live_position_tp_hit_count.assert_called_once()
        service.order_repo.update_live_position_phase.assert_called_once()

    def test_get_portfolio_returns_correct_sl_after_tp1(self):
        """
        Test that get_portfolio would return correct SL after TP1 hit.

        This simulates what UI would see via get_portfolio() endpoint.

        **Validates: Requirements 3.4**
        """
        from unittest.mock import Mock, MagicMock
        from src.application.services.live_trading_service import LiveTradingService

        # Create service with watermarks
        service = LiveTradingService.__new__(LiveTradingService)
        service._position_watermarks = {}
        service.order_repo = Mock()
        service.order_repo.update_live_position_sl = Mock()
        service.order_repo.update_live_position_tp_hit_count = Mock()
        service.order_repo.update_live_position_phase = Mock()
        service.logger = MagicMock()

        # Create monitor
        monitor = PositionMonitorService()
        monitor._persist_sl = service._persist_sl_to_db
        monitor._persist_tp_hit = service._persist_tp_hit_to_db
        monitor._persist_phase = service._persist_phase_to_db
        monitor._partial_close = Mock(return_value=True)
        monitor._update_sl = Mock()

        # Create SHORT position (like DOGEUSDT from user report)
        pos = MonitoredPosition(
            symbol='DOGEUSDT',
            side='SHORT',
            entry_price=0.1505,
            quantity=100.0,
            leverage=10,
            initial_sl=0.1535,
            initial_tp=0.1480,
            atr=0.002
        )
        pos.entry_time = datetime.now() - timedelta(seconds=60)

        # Initialize watermark
        service._position_watermarks['DOGEUSDT'] = {
            'current_sl': 0.1535,  # Original SL (above entry for SHORT)
            'tp_target': 0.1480,
            'is_breakeven': False,
            'tp_hit_count': 0,
            'phase': 'ENTRY',
            'entry_price': 0.1505,
            'side': 'SHORT'
        }

        monitor.start_monitoring(pos)

        # Trigger TP1 hit
        monitor._on_tp1_hit(pos, 0.1480)

        # For SHORT: breakeven SL = entry - buffer (below entry)
        expected_sl = 0.1505 - (0.1505 * 0.0005)

        # Simulate what get_portfolio would return
        portfolio_sl = service._position_watermarks['DOGEUSDT']['current_sl']

        # CRITICAL: UI should see correct SL (breakeven, not original)
        assert portfolio_sl == pytest.approx(expected_sl, rel=0.001), \
            f"Portfolio SL should be {expected_sl}, got {portfolio_sl}"

        # SL should be BELOW entry for SHORT (breakeven)
        assert portfolio_sl < 0.1505, \
            f"SHORT breakeven SL {portfolio_sl} should be below entry 0.1505"

        # Original SL was 0.1535 (above entry), new SL should be different
        assert portfolio_sl != 0.1535, \
            "SL should have changed from original 0.1535"

    def test_tp1_flow_with_missing_watermark_creates_it(self):
        """
        Test that TP1 flow creates watermark if it's missing.

        This tests the CRITICAL FIX for the bug where SL wasn't updated
        because watermark didn't exist.

        **Validates: Requirements 1.1, 1.4, 3.1**
        """
        from unittest.mock import Mock, MagicMock
        from src.application.services.live_trading_service import LiveTradingService

        # Create service with EMPTY watermarks (simulating the bug scenario)
        service = LiveTradingService.__new__(LiveTradingService)
        service._position_watermarks = {}  # EMPTY - no watermark for position
        service.order_repo = Mock()
        service.order_repo.update_live_position_sl = Mock()
        service.order_repo.update_live_position_tp_hit_count = Mock()
        service.order_repo.update_live_position_phase = Mock()
        service.logger = MagicMock()

        # Create monitor
        monitor = PositionMonitorService()
        monitor._persist_sl = service._persist_sl_to_db
        monitor._persist_tp_hit = service._persist_tp_hit_to_db
        monitor._persist_phase = service._persist_phase_to_db
        monitor._partial_close = Mock(return_value=True)
        monitor._update_sl = Mock()

        # Create position
        pos = MonitoredPosition(
            symbol='ETHUSDT',
            side='LONG',
            entry_price=2000.0,
            quantity=1.0,
            leverage=10,
            initial_sl=1900.0,
            initial_tp=2200.0,
            atr=50.0
        )
        pos.entry_time = datetime.now() - timedelta(seconds=60)

        monitor.start_monitoring(pos)

        # Verify watermark doesn't exist before TP1
        assert 'ETHUSDT' not in service._position_watermarks

        # Trigger TP1 hit
        monitor._on_tp1_hit(pos, 2200.0)

        expected_sl = 2000.0 + (2000.0 * 0.0005)

        # CRITICAL: Watermark should now exist with correct SL
        assert 'ETHUSDT' in service._position_watermarks, \
            "Watermark should be created when missing"

        assert service._position_watermarks['ETHUSDT']['current_sl'] == pytest.approx(expected_sl, rel=0.001), \
            f"Watermark SL should be {expected_sl}"

        # Warning should have been logged about missing watermark
        service.logger.warning.assert_called()
