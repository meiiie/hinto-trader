"""Tests for BroSubSoul heartbeat guard in LiveTradingService."""

import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from src.application.services.live_trading_service import LiveTradingService


class TestBroHeartbeatGuard:
    """Heartbeat health evaluation for new live entries."""

    def _make_service(self, settings=None, *, startup_age_seconds=600):
        service = LiveTradingService.__new__(LiveTradingService)
        service.logger = MagicMock()
        service.settings_repo = MagicMock()
        service.settings_repo.get_all_settings.return_value = settings or {}
        service._startup_time = datetime.now() - timedelta(seconds=startup_age_seconds)
        service.BRO_HEARTBEAT_STARTUP_GRACE_SECONDS = 180
        service.BRO_HEARTBEAT_MAX_STALENESS_SECONDS = 300
        return service

    def test_missing_heartbeat_blocks_after_startup_grace(self):
        service = self._make_service()

        healthy, reason = service._is_bro_heartbeat_healthy()

        assert healthy is False
        assert "missing" in reason

    def test_missing_heartbeat_allowed_during_startup_grace(self):
        service = self._make_service(startup_age_seconds=30)

        healthy, reason = service._is_bro_heartbeat_healthy()

        assert healthy is True
        assert "startup grace" in reason

    def test_fresh_heartbeat_allows_trade(self):
        now = int(time.time())
        service = self._make_service({
            "bro_subsoul_last_heartbeat": str(now - 60),
        })

        healthy, reason = service._is_bro_heartbeat_healthy()

        assert healthy is True
        assert "healthy" in reason

    def test_stale_heartbeat_blocks_trade(self):
        now = int(time.time())
        service = self._make_service({
            "bro_subsoul_last_heartbeat": str(now - 400),
        })

        healthy, reason = service._is_bro_heartbeat_healthy()

        assert healthy is False
        assert "stale" in reason

    def test_invalid_heartbeat_blocks_trade(self):
        service = self._make_service({
            "bro_subsoul_last_heartbeat": "not-a-timestamp",
        })

        healthy, reason = service._is_bro_heartbeat_healthy()

        assert healthy is False
        assert "invalid" in reason

    def test_settings_read_error_blocks_trade(self):
        service = self._make_service()
        service.settings_repo.get_all_settings.side_effect = RuntimeError("db down")

        healthy, reason = service._is_bro_heartbeat_healthy()

        assert healthy is False
        assert "read error" in reason
