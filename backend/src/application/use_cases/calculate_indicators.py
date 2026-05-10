"""
CalculateIndicatorsUseCase - Application Layer

Use case for calculating technical indicators from candle data.
"""

from typing import List, Tuple, Protocol
import pandas as pd

from ...domain.entities.candle import Candle
from ...domain.entities.indicator import Indicator


class IndicatorCalculatorProtocol(Protocol):
    """Protocol defining the interface for indicator calculator"""
    @staticmethod
    def calculate_all(df: pd.DataFrame) -> pd.DataFrame:
        """Calculate all indicators from OHLCV data"""
        ...


class CalculateIndicatorsUseCase:
    """
    Use case for calculating technical indicators.

    This use case:
    1. Takes list of Candle entities
    2. Converts to DataFrame
    3. Calculates indicators using TA-Lib
    4. Returns list of (Candle, Indicator) tuples
    """

    def __init__(self, calculator: IndicatorCalculatorProtocol):
        """
        Initialize use case with dependencies.

        Args:
            calculator: Calculator for computing technical indicators
        """
        self.calculator = calculator

    def execute(self, candles: List[Candle]) -> List[Tuple[Candle, Indicator]]:
        """
        Execute the use case: calculate indicators for candles.

        Args:
            candles: List of Candle entities

        Returns:
            List of (Candle, Indicator) tuples

        Raises:
            ValueError: If candles list is empty
            RuntimeError: If calculation fails
        """
        if not candles:
            raise ValueError("Cannot calculate indicators for empty candle list")

        # Convert candles to DataFrame
        data = {
            'open_time': [c.timestamp for c in candles],
            'open': [c.open for c in candles],
            'high': [c.high for c in candles],
            'low': [c.low for c in candles],
            'close': [c.close for c in candles],
            'volume': [c.volume for c in candles]
        }
        df = pd.DataFrame(data)

        # Calculate indicators
        try:
            df_with_indicators = self.calculator.calculate_all(df)
        except Exception as e:
            raise RuntimeError(f"Failed to calculate indicators: {e}") from e

        # Convert back to entities
        results = []
        for i, candle in enumerate(candles):
            # Get indicator values from DataFrame
            # Note: DataFrame index might be different after calculation
            try:
                row = df_with_indicators.iloc[i]
                indicator = Indicator(
                    ema_7=row.get('ema_7'),
                    rsi_6=row.get('rsi_6'),
                    volume_ma_20=row.get('volume_ma_20')
                )
                results.append((candle, indicator))
            except (IndexError, KeyError):
                # If indicator calculation failed, use None values
                indicator = Indicator(ema_7=None, rsi_6=None, volume_ma_20=None)
                results.append((candle, indicator))

        return results
