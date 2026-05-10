"""
IndicatorRepository Interface - Domain Layer

Abstract repository interface for indicator-specific queries.
This provides specialized queries for technical indicator analysis.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from datetime import datetime

from ..entities.indicator import Indicator


class IndicatorRepository(ABC):
    """
    Abstract repository interface for indicator-specific operations.

    This interface provides specialized queries for analyzing
    technical indicators across different timeframes and periods.
    """

    @abstractmethod
    def get_indicator_stats(
        self,
        timeframe: str,
        indicator_name: str,
        period_days: int = 30
    ) -> Dict[str, float]:
        """
        Get statistical information about an indicator.

        Args:
            timeframe: The timeframe to analyze
            indicator_name: Name of indicator ('ema_7', 'rsi_6', 'volume_ma_20')
            period_days: Number of days to analyze (default: 30)

        Returns:
            Dictionary with statistics:
            - min: Minimum value
            - max: Maximum value
            - avg: Average value
            - std: Standard deviation
            - count: Number of non-null values
            - null_count: Number of null values
            - null_percentage: Percentage of null values

        Raises:
            RepositoryError: If query fails
        """
        pass

    @abstractmethod
    def get_missing_indicators(
        self,
        timeframe: str,
        limit: int = 100
    ) -> List[datetime]:
        """
        Get timestamps where indicators are missing (None/NULL).

        Args:
            timeframe: The timeframe to check
            limit: Maximum number of timestamps to return

        Returns:
            List of timestamps with missing indicators

        Raises:
            RepositoryError: If query fails
        """
        pass

    @abstractmethod
    def get_indicator_completion_rate(self, timeframe: str) -> Dict[str, float]:
        """
        Get completion rate for each indicator.

        Args:
            timeframe: The timeframe to analyze

        Returns:
            Dictionary mapping indicator names to completion percentages:
            - ema_7: float (0-100)
            - rsi_6: float (0-100)
            - volume_ma_20: float (0-100)

        Raises:
            RepositoryError: If query fails
        """
        pass

    @abstractmethod
    def get_rsi_extremes(
        self,
        timeframe: str,
        threshold_low: float = 30.0,
        threshold_high: float = 70.0,
        limit: int = 50
    ) -> Dict[str, List[tuple[datetime, float]]]:
        """
        Get timestamps where RSI is in extreme zones.

        Args:
            timeframe: The timeframe to analyze
            threshold_low: Oversold threshold (default: 30)
            threshold_high: Overbought threshold (default: 70)
            limit: Maximum results per category

        Returns:
            Dictionary with:
            - oversold: List of (timestamp, rsi_value) tuples
            - overbought: List of (timestamp, rsi_value) tuples

        Raises:
            RepositoryError: If query fails
        """
        pass

    @abstractmethod
    def get_indicator_anomalies(
        self,
        timeframe: str,
        limit: int = 50
    ) -> Dict[str, List[tuple[datetime, float]]]:
        """
        Detect anomalies in indicator values.

        Anomalies include:
        - RSI > 100 or RSI < 0
        - Negative EMA values
        - Negative Volume MA values

        Args:
            timeframe: The timeframe to check
            limit: Maximum anomalies to return per type

        Returns:
            Dictionary mapping anomaly types to list of (timestamp, value) tuples:
            - invalid_rsi: RSI out of range
            - negative_ema: Negative EMA values
            - negative_volume_ma: Negative Volume MA values

        Raises:
            RepositoryError: If query fails
        """
        pass

    @abstractmethod
    def get_indicator_trend(
        self,
        timeframe: str,
        indicator_name: str,
        period_days: int = 7
    ) -> Dict[str, any]:
        """
        Analyze trend of an indicator over time.

        Args:
            timeframe: The timeframe to analyze
            indicator_name: Name of indicator
            period_days: Number of days to analyze

        Returns:
            Dictionary with trend information:
            - direction: 'UP', 'DOWN', or 'FLAT'
            - slope: Rate of change
            - start_value: Value at start of period
            - end_value: Value at end of period
            - change_percentage: Percentage change

        Raises:
            RepositoryError: If query fails
        """
        pass

    @abstractmethod
    def get_indicator_correlation(
        self,
        timeframe: str,
        indicator1: str,
        indicator2: str,
        period_days: int = 30
    ) -> float:
        """
        Calculate correlation between two indicators.

        Args:
            timeframe: The timeframe to analyze
            indicator1: First indicator name
            indicator2: Second indicator name
            period_days: Number of days to analyze

        Returns:
            Correlation coefficient (-1 to 1)

        Raises:
            RepositoryError: If query fails
        """
        pass

    @abstractmethod
    def get_data_quality_score(self, timeframe: str) -> float:
        """
        Calculate overall data quality score for a timeframe.

        Based on:
        - Indicator completion rate
        - Absence of anomalies
        - Time continuity
        - Data freshness

        Args:
            timeframe: The timeframe to evaluate

        Returns:
            Quality score from 0 to 100

        Raises:
            RepositoryError: If query fails
        """
        pass


# Re-export RepositoryError from market_data_repository
from .market_data_repository import RepositoryError

__all__ = ['IndicatorRepository', 'RepositoryError']
