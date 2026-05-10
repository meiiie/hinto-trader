"""Broker capability model for safe venue selection.

The trading engine should not assume every venue behaves like Binance Futures.
This value object makes broker constraints explicit before a strategy is wired
to live execution.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Tuple


class VenueType(str, Enum):
    """Supported market venue families."""

    CRYPTO_FUTURES = "crypto_futures"
    VN_EQUITIES = "vn_equities"
    VN_DERIVATIVES = "vn_derivatives"


@dataclass(frozen=True)
class BrokerCapabilities:
    """Execution and market-structure capabilities for a broker or exchange."""

    broker_id: str
    venue_type: VenueType
    supports_live_trading_api: bool
    supports_market_data_stream: bool
    supports_short_selling: bool
    supports_leverage: bool
    supports_intraday_round_trip: bool
    supports_stop_orders: bool
    requires_manual_otp: bool = False
    settlement_cycle: str = "continuous"
    notes: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_automation_ready(self) -> bool:
        """True when live order automation can be considered."""

        return self.supports_live_trading_api and not self.requires_manual_otp

    def automation_blockers(self) -> Tuple[str, ...]:
        """Human-readable blockers for live automation."""

        blockers = []
        if not self.supports_live_trading_api:
            blockers.append("no official live trading API")
        if self.requires_manual_otp:
            blockers.append("manual OTP/order confirmation required")
        if not self.supports_market_data_stream:
            blockers.append("no real-time market data stream")
        return tuple(blockers)


def binance_futures_capabilities() -> BrokerCapabilities:
    """Baseline capabilities for the current Binance Futures adapter."""

    return BrokerCapabilities(
        broker_id="binance_futures",
        venue_type=VenueType.CRYPTO_FUTURES,
        supports_live_trading_api=True,
        supports_market_data_stream=True,
        supports_short_selling=True,
        supports_leverage=True,
        supports_intraday_round_trip=True,
        supports_stop_orders=True,
        settlement_cycle="continuous",
        notes=("24/7 market", "funding and liquidation risk apply"),
    )


def vietnam_equities_manual_capabilities(broker_id: str) -> BrokerCapabilities:
    """Conservative profile for Vietnamese cash-equity broker channels."""

    return BrokerCapabilities(
        broker_id=broker_id,
        venue_type=VenueType.VN_EQUITIES,
        supports_live_trading_api=False,
        supports_market_data_stream=False,
        supports_short_selling=False,
        supports_leverage=False,
        supports_intraday_round_trip=False,
        supports_stop_orders=False,
        requires_manual_otp=True,
        settlement_cycle="T+2",
        notes=("use for research/alerts only unless an official API contract exists",),
    )


def vietnam_derivatives_manual_capabilities(broker_id: str) -> BrokerCapabilities:
    """Conservative profile for Vietnamese derivatives via retail channels."""

    return BrokerCapabilities(
        broker_id=broker_id,
        venue_type=VenueType.VN_DERIVATIVES,
        supports_live_trading_api=False,
        supports_market_data_stream=False,
        supports_short_selling=True,
        supports_leverage=True,
        supports_intraday_round_trip=True,
        supports_stop_orders=True,
        requires_manual_otp=True,
        settlement_cycle="daily_mark_to_market",
        notes=("manual/web/app order flow is not acceptable for open-source automation",),
    )
