"""
MarketMode - Unified Market Mode Configuration

SOTA Implementation (Jan 2026):
- Centralized market mode enum (SPOT/FUTURES)
- Auto-configured URLs per mode
- Single source of truth for all data flows

Usage:
    from src.config.market_mode import MarketMode, get_market_config

    config = get_market_config(MarketMode.FUTURES)
    print(config.rest_url)  # https://fapi.binance.com/fapi/v1
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional
import os


class MarketMode(Enum):
    """Market trading mode."""
    SPOT = "spot"
    FUTURES = "futures"


@dataclass
class MarketConfig:
    """
    Configuration for a specific market mode.

    Contains all URLs and settings needed for data fetching
    and trading in either SPOT or FUTURES mode.
    """
    mode: MarketMode
    rest_base_url: str
    ws_base_url: str
    ws_stream_url: str  # For combined streams

    # Mode-specific settings
    has_leverage: bool = False
    has_funding: bool = False
    klines_endpoint: str = "/klines"

    @property
    def name(self) -> str:
        return self.mode.value.upper()


# Pre-configured market configs
SPOT_CONFIG = MarketConfig(
    mode=MarketMode.SPOT,
    rest_base_url="https://api.binance.com/api/v3",
    ws_base_url="wss://stream.binance.com:9443/ws",
    ws_stream_url="wss://stream.binance.com:9443/stream",
    has_leverage=False,
    has_funding=False,
    klines_endpoint="/klines"
)

FUTURES_CONFIG = MarketConfig(
    mode=MarketMode.FUTURES,
    rest_base_url="https://fapi.binance.com/fapi/v1",
    ws_base_url="wss://fstream.binance.com/ws",
    ws_stream_url="wss://fstream.binance.com/stream",
    has_leverage=True,
    has_funding=True,
    klines_endpoint="/klines"
)


def get_market_config(mode: MarketMode) -> MarketConfig:
    """
    Get configuration for specified market mode.

    Args:
        mode: MarketMode.SPOT or MarketMode.FUTURES

    Returns:
        MarketConfig with all relevant URLs and settings
    """
    if mode == MarketMode.SPOT:
        return SPOT_CONFIG
    return FUTURES_CONFIG


def get_default_market_mode() -> MarketMode:
    """
    Get default market mode from environment or return FUTURES.

    Environment variable: MARKET_MODE (spot/futures)
    """
    mode_str = os.getenv("MARKET_MODE", "futures").lower()
    if mode_str == "spot":
        return MarketMode.SPOT
    return MarketMode.FUTURES
