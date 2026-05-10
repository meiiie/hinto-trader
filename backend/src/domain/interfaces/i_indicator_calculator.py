"""
IIndicatorCalculator - Domain Interface

Abstract interface for technical indicator calculations.
Infrastructure layer provides concrete implementations.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
import pandas as pd

from ..entities.candle import Candle


@dataclass
class BollingerBandsResult:
    """Result of Bollinger Bands calculation."""
    upper_band: float
    middle_band: float
    lower_band: float
    bandwidth: float
    percent_b: float


@dataclass
class BollingerBandsSeriesResult:
    """Series result of Bollinger Bands calculation."""
    upper_band: List[float]
    middle_band: List[float]
    lower_band: List[float]


@dataclass
class StochRSIResult:
    """Result of Stochastic RSI calculation."""
    k_value: float
    d_value: float
    zone: Any  # StochRSIZone enum


@dataclass
class ADXResult:
    """Result of ADX calculation."""
    adx: float
    plus_di: float
    minus_di: float
    is_trending: bool
    trend_strength: str
    trend_direction: str


@dataclass
class SwingPoint:
    """Represents a swing high or swing low point."""
    price: float
    index: int
    is_high: bool


class IIndicatorCalculator(ABC):
    """
    Abstract interface for technical indicator calculations.

    Application layer uses this interface.
    Infrastructure layer (TALibCalculator, etc.) implements it.
    """

    @abstractmethod
    def calculate_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate all indicators and return DataFrame with results."""
        pass

    @abstractmethod
    def calculate_ema(self, prices: List[float], period: int) -> Optional[float]:
        """Calculate Exponential Moving Average."""
        pass

    @abstractmethod
    def calculate_rsi(self, prices: List[float], period: int) -> Optional[float]:
        """Calculate Relative Strength Index."""
        pass

    @abstractmethod
    def calculate_atr(self, candles: List[Candle], period: int) -> Optional[float]:
        """Calculate Average True Range."""
        pass


class IVWAPCalculator(ABC):
    """Interface for VWAP calculations."""

    @abstractmethod
    def calculate_vwap(self, candles: List[Candle]) -> Optional[float]:
        """Calculate Volume Weighted Average Price."""
        pass

    @abstractmethod
    def calculate_vwap_series(self, candles: List[Candle]) -> Optional[pd.Series]:
        """Calculate VWAP series for all candles."""
        pass


class IBollingerCalculator(ABC):
    """Interface for Bollinger Bands calculations."""

    @abstractmethod
    def calculate_bands(self, candles: List[Candle]) -> Optional[BollingerBandsResult]:
        """Calculate Bollinger Bands for latest candle."""
        pass

    @abstractmethod
    def calculate_bands_series(self, candles: List[Candle]) -> Optional[BollingerBandsSeriesResult]:
        """Calculate Bollinger Bands series for all candles."""
        pass


class IStochRSICalculator(ABC):
    """Interface for Stochastic RSI calculations."""

    @abstractmethod
    def calculate_stoch_rsi(self, candles: List[Candle]) -> Optional[StochRSIResult]:
        """Calculate Stochastic RSI."""
        pass


class IADXCalculator(ABC):
    """Interface for ADX calculations."""

    @abstractmethod
    def calculate_adx(self, candles: List[Candle]) -> Optional[ADXResult]:
        """Calculate ADX indicator."""
        pass


class IATRCalculator(ABC):
    """Interface for ATR calculations."""

    @abstractmethod
    def calculate_atr(self, candles: List[Candle]) -> Optional[float]:
        """Calculate Average True Range."""
        pass


class IVolumeSpikeDetector(ABC):
    """Interface for volume spike detection."""

    @abstractmethod
    def detect_spike(self, candles: List[Candle]) -> bool:
        """Detect if there's a volume spike."""
        pass

    @abstractmethod
    def get_volume_ratio(self, candles: List[Candle]) -> float:
        """Get current volume ratio vs average."""
        pass


class ISwingPointDetector(ABC):
    """Interface for swing point detection."""

    @abstractmethod
    def find_swing_highs(self, candles: List[Candle], lookback: int) -> List[SwingPoint]:
        """Find swing high points."""
        pass

    @abstractmethod
    def find_swing_lows(self, candles: List[Candle], lookback: int) -> List[SwingPoint]:
        """Find swing low points."""
        pass
