"""
Exchange Services - Infrastructure Layer

Concrete implementations of IExchangeService interface.
"""

from .paper_exchange_service import PaperExchangeService
# NOTE: BinanceExchangeService uses ccxt which is deprecated.
# Project now uses native REST API via BinanceFuturesClient.
# from .binance_exchange_service import BinanceExchangeService

# SOTA P0: Exchange Filter Service for LOT_SIZE/MIN_NOTIONAL compliance
from .exchange_filter_service import ExchangeFilterService

# SOTA P1: Market Intelligence Service for Funding Rate and Leverage
from .market_intelligence_service import MarketIntelligenceService

__all__ = [
    'PaperExchangeService',
    # 'BinanceExchangeService',  # Deprecated - uses ccxt
    'ExchangeFilterService',
    'MarketIntelligenceService',
]
