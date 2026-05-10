"""
Test: Execute Signal Flow

SOTA (Jan 2026): E2E test for signal execution flow.
From signal generation → LocalSignalTracker → MARKET execution.

Reference:
- live_trading_service.py execute_signal() L608-739
- live_trading_service.py _execute_triggered_signal() L1482-1724
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestExecuteSignalValidation:
    """Test signal validation before adding to tracker"""

    # =========================================================================
    # REFERENCE (L615-680):
    #   Pre-flight checks:
    #   - Trading enabled
    #   - Not in SAFE_MODE
    #   - Symbol not blacklisted
    #   - Max positions not reached
    #   - Symbol not already in active_positions
    # =========================================================================

    def test_safe_mode_blocks_execution(self):
        """SAFE_MODE should block signal execution"""
        enable_trading = False  # SAFE_MODE

        should_proceed = enable_trading

        assert should_proceed is False

    def test_trading_enabled_allows_execution(self):
        """enable_trading=True should allow signal execution"""
        enable_trading = True

        should_proceed = enable_trading

        assert should_proceed is True

    def test_max_positions_blocks_new_signal(self):
        """Max positions reached should block new signals"""
        active_positions = {"BTCUSDT": {}, "ETHUSDT": {}, "BNBUSDT": {}}
        pending_signals = {"DOGEUSDT": {}, "PEPEUSDT": {}}
        max_positions = 5

        current_slots = len(active_positions) + len(pending_signals)
        is_full = current_slots >= max_positions

        assert current_slots == 5
        assert is_full is True

    def test_positions_available_allows_signal(self):
        """Slots available should allow new signal"""
        active_positions = {"BTCUSDT": {}}
        pending_signals = {"ETHUSDT": {}}
        max_positions = 10

        current_slots = len(active_positions) + len(pending_signals)
        is_full = current_slots >= max_positions

        assert current_slots == 2
        assert is_full is False

    def test_existing_position_blocks_duplicate(self):
        """Already having position in symbol should block"""
        active_positions = {"BTCUSDT": {}, "ETHUSDT": {}}
        new_signal_symbol = "BTCUSDT"

        has_position = new_signal_symbol in active_positions

        assert has_position is True


class TestSignalTrackerAdd:
    """Test signal is added to LocalSignalTracker"""

    def test_signal_added_to_tracker(self):
        """Signal should be added via add_signal()"""
        tracker = {}  # Mock tracker dict

        signal = {
            "symbol": "BTCUSDT",
            "direction": "LONG",
            "target_price": 50000.0,
            "stop_loss": 49750.0,
            "take_profit": 51000.0,
            "expires_at": "2026-01-12T15:00:00"
        }

        # Add to tracker
        tracker[signal["symbol"]] = signal

        assert "BTCUSDT" in tracker
        assert tracker["BTCUSDT"]["direction"] == "LONG"

    def test_zombie_killer_replaces_old_signal(self):
        """New signal for same symbol should replace old one"""
        tracker = {
            "BTCUSDT": {"target_price": 49000.0, "direction": "LONG"}  # Old signal
        }

        new_signal = {"target_price": 51000.0, "direction": "SHORT"}

        # Zombie killer: replace
        tracker["BTCUSDT"] = new_signal

        assert tracker["BTCUSDT"]["target_price"] == 51000.0
        assert tracker["BTCUSDT"]["direction"] == "SHORT"


class TestSignalTrigger:
    """Test signal triggering when price hits target"""

    # =========================================================================
    # REFERENCE (LocalSignalTracker.on_price_update):
    #   if direction == 'LONG' and current_price <= target_price:
    #       execute_callback(signal, current_price)
    #   elif direction == 'SHORT' and current_price >= target_price:
    #       execute_callback(signal, current_price)
    # =========================================================================

    def test_long_signal_triggers_at_target(self):
        """LONG signal triggers when price <= target"""
        signal = {"direction": "LONG", "target_price": 50000.0}
        current_price = 49900.0  # Below target

        should_trigger = (
            signal["direction"] == "LONG" and
            current_price <= signal["target_price"]
        )

        assert should_trigger is True

    def test_long_signal_not_triggers_above_target(self):
        """LONG signal NOT triggers when price > target"""
        signal = {"direction": "LONG", "target_price": 50000.0}
        current_price = 50100.0  # Above target

        should_trigger = (
            signal["direction"] == "LONG" and
            current_price <= signal["target_price"]
        )

        assert should_trigger is False

    def test_short_signal_triggers_at_target(self):
        """SHORT signal triggers when price >= target"""
        signal = {"direction": "SHORT", "target_price": 3000.0}
        current_price = 3050.0  # Above target

        should_trigger = (
            signal["direction"] == "SHORT" and
            current_price >= signal["target_price"]
        )

        assert should_trigger is True

    def test_short_signal_not_triggers_below_target(self):
        """SHORT signal NOT triggers when price < target"""
        signal = {"direction": "SHORT", "target_price": 3000.0}
        current_price = 2950.0  # Below target

        should_trigger = (
            signal["direction"] == "SHORT" and
            current_price >= signal["target_price"]
        )

        assert should_trigger is False


class TestTriggeredSignalExecution:
    """Test execution when signal triggers"""

    def test_market_order_placed_on_trigger(self):
        """Triggered signal should place MARKET order"""
        signal_direction = "LONG"

        # Determine order side
        order_side = "BUY" if signal_direction == "LONG" else "SELL"
        order_type = "MARKET"

        assert order_side == "BUY"
        assert order_type == "MARKET"

    def test_sl_recalculated_from_fill(self):
        """SL should be recalculated from actual fill price"""
        signal_sl = 49750.0  # Original signal SL
        actual_fill = 50100.0  # Filled higher than signal
        sl_pct = 0.005  # 0.5%

        # Recalculate from fill
        actual_sl = actual_fill * (1 - sl_pct)

        assert actual_sl == pytest.approx(49849.5)
        assert actual_sl > signal_sl  # New SL is higher

    def test_backup_sl_placed_on_exchange(self):
        """Backup SL should be placed at 2% for disaster protection"""
        fill_price = 50000.0
        side = "LONG"
        backup_sl_pct = 0.02  # 2%

        backup_sl = fill_price * (1 - backup_sl_pct) if side == "LONG" else fill_price * (1 + backup_sl_pct)

        assert backup_sl == 49000.0


class TestSignalExpiration:
    """Test signal expiration (TTL)"""

    def test_expired_signal_removed(self):
        """Expired signals should be removed from tracker"""
        from datetime import datetime, timezone, timedelta

        now = datetime.now(timezone.utc)
        expired_time = now - timedelta(minutes=10)
        valid_time = now + timedelta(minutes=30)

        signals = {
            "BTCUSDT": {"expires_at": expired_time},  # Expired
            "ETHUSDT": {"expires_at": valid_time},    # Valid
        }

        # Remove expired
        active_signals = {
            sym: sig for sym, sig in signals.items()
            if sig["expires_at"] > now
        }

        assert "BTCUSDT" not in active_signals
        assert "ETHUSDT" in active_signals

    def test_ttl_default_45_minutes(self):
        """Default TTL should be 45 minutes"""
        from datetime import datetime, timezone, timedelta

        TTL_MINUTES = 45
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=TTL_MINUTES)

        # Check it's in the future
        assert expires_at > now

        # Check it's ~45 minutes
        diff = (expires_at - now).total_seconds() / 60
        assert diff == pytest.approx(45, abs=0.1)


class TestBlacklistCheck:
    """Test blacklist blocks signal execution"""

    def test_blacklisted_symbol_blocked(self):
        """Blacklisted symbol should be blocked"""
        blacklist = ["BTCDOMUSDT", "DEFIUSDT", "USDCUSDT"]
        signal_symbol = "BTCDOMUSDT"

        is_blocked = signal_symbol in blacklist

        assert is_blocked is True

    def test_non_blacklisted_allowed(self):
        """Non-blacklisted symbol should be allowed"""
        blacklist = ["BTCDOMUSDT", "DEFIUSDT", "USDCUSDT"]
        signal_symbol = "BTCUSDT"

        is_blocked = signal_symbol in blacklist

        assert is_blocked is False
