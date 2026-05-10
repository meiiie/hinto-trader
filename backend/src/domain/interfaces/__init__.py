"""
Domain Interfaces - Abstract contracts for infrastructure implementations.

These interfaces define the contracts that infrastructure layer must implement.
Application layer depends on these interfaces, not concrete implementations.
"""

from .i_indicator_calculator import (
    IIndicatorCalculator,
    IVWAPCalculator,
    IBollingerCalculator,
    IStochRSICalculator,
    IADXCalculator,
    IATRCalculator,
    IVolumeSpikeDetector,
    ISwingPointDetector,
    BollingerBandsResult,
    BollingerBandsSeriesResult,
    StochRSIResult,
    ADXResult,
    SwingPoint,
)
from .i_volume_delta_calculator import (
    IVolumeDeltaCalculator,
    VolumeDeltaResult,
    CumulativeDeltaResult,
)
from .i_liquidity_zone_detector import (
    ILiquidityZoneDetector,
    LiquidityZone,
    LiquidityZonesResult,
)
from .i_sfp_detector import (
    ISFPDetector,
    SFPResult,
    SFPType,
)
from .i_momentum_velocity_calculator import (
    IMomentumVelocityCalculator,
    VelocityResult,
)
from .i_websocket_client import (
    IWebSocketClient,
    ConnectionState,
    ConnectionStatus,
)
from .i_rest_client import IRestClient
from .i_data_aggregator import IDataAggregator
from .i_book_ticker_client import IBookTickerClient, BookTickerData
from .i_exchange_service import IExchangeService, ExchangeError

__all__ = [
    # Indicator interfaces
    'IIndicatorCalculator',
    'IVWAPCalculator',
    'IBollingerCalculator',
    'IStochRSICalculator',
    'IADXCalculator',
    'IATRCalculator',
    'IVolumeSpikeDetector',
    'ISwingPointDetector',
    # Volume Delta
    'IVolumeDeltaCalculator',
    'VolumeDeltaResult',
    'CumulativeDeltaResult',
    # Liquidity Zones
    'ILiquidityZoneDetector',
    'LiquidityZone',
    'LiquidityZonesResult',
    # SFP
    'ISFPDetector',
    'SFPResult',
    'SFPType',
    # Momentum Velocity
    'IMomentumVelocityCalculator',
    'VelocityResult',
    # Result types
    'BollingerBandsResult',
    'BollingerBandsSeriesResult',
    'StochRSIResult',
    'ADXResult',
    'SwingPoint',
    # WebSocket
    'IWebSocketClient',
    'ConnectionState',
    'ConnectionStatus',
    # REST
    'IRestClient',
    # Aggregator
    'IDataAggregator',
    # BookTicker
    'IBookTickerClient',
    'BookTickerData',
    # Exchange Service
    'IExchangeService',
    'ExchangeError',
]
