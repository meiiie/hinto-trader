"""
TALibCalculator - Infrastructure Layer

TA-Lib based technical indicator calculator.
Refactored from src/indicators.py to infrastructure layer.
"""

import pandas as pd
import numpy as np
from typing import Optional
import logging

try:
    import talib
    TALIB_AVAILABLE = True
except ImportError:
    TALIB_AVAILABLE = False


class TALibCalculator:
    """
    Technical indicator calculator using TA-Lib.

    This calculator provides:
    - EMA (Exponential Moving Average)
    - RSI (Relative Strength Index)
    - Volume MA (Volume Moving Average)

    Falls back to pandas-based calculations if TA-Lib is not available.
    """

    def __init__(self):
        """Initialize calculator"""
        self.logger = logging.getLogger(__name__)

        if TALIB_AVAILABLE:
            self.logger.info(f"Using TA-Lib version {talib.__version__}")
        else:
            self.logger.warning("TA-Lib not available, using pandas fallback")

    @staticmethod
    def calculate_all(df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate all technical indicators for the given DataFrame.

        Args:
            df: DataFrame with OHLCV data
                Required columns: open, high, low, close, volume

        Returns:
            DataFrame with additional indicator columns:
            - ema_7: 7-period Exponential Moving Average
            - ema_25: 25-period Exponential Moving Average
            - rsi_6: 6-period Relative Strength Index
            - volume_ma_20: 20-period Volume Moving Average

        Raises:
            ValueError: If required columns are missing
            RuntimeError: If calculation fails
        """
        logger = logging.getLogger(__name__)

        try:
            # Validate input DataFrame
            required_columns = ['open', 'high', 'low', 'close', 'volume']
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                raise ValueError(f"Missing required columns: {missing_columns}")

            if df.empty:
                logger.warning("Empty DataFrame provided")
                return df

            # Create a copy to avoid modifying original
            result_df = df.copy()

            # Convert to numpy arrays for TA-Lib
            close_prices = df['close'].values.astype(np.float64)
            high_prices = df['high'].values.astype(np.float64)
            low_prices = df['low'].values.astype(np.float64)
            volumes = df['volume'].values.astype(np.float64)

            if TALIB_AVAILABLE:
                # Use TA-Lib for calculations
                logger.debug("Calculating indicators using TA-Lib")

                # EMA(7)
                try:
                    ema_7 = talib.EMA(close_prices, timeperiod=7)
                    result_df['ema_7'] = ema_7
                except Exception as e:
                    logger.warning(f"TA-Lib EMA(7) calculation failed: {e}")
                    result_df['ema_7'] = TALibCalculator._calculate_ema_fallback(close_prices, 7)

                # EMA(25) - Professional crossover system
                try:
                    ema_25 = talib.EMA(close_prices, timeperiod=25)
                    result_df['ema_25'] = ema_25
                except Exception as e:
                    logger.warning(f"TA-Lib EMA(25) calculation failed: {e}")
                    result_df['ema_25'] = TALibCalculator._calculate_ema_fallback(close_prices, 25)

                # RSI(6)
                try:
                    rsi_6 = talib.RSI(close_prices, timeperiod=6)
                    result_df['rsi_6'] = rsi_6
                except Exception as e:
                    logger.warning(f"TA-Lib RSI calculation failed: {e}")
                    result_df['rsi_6'] = TALibCalculator._calculate_rsi_fallback(close_prices, 6)

                # Volume MA(20)
                try:
                    volume_ma_20 = talib.SMA(volumes, timeperiod=20)
                    result_df['volume_ma_20'] = volume_ma_20
                except Exception as e:
                    logger.warning(f"TA-Lib Volume MA calculation failed: {e}")
                    result_df['volume_ma_20'] = TALibCalculator._calculate_sma_fallback(volumes, 20)

            else:
                # Use pandas fallback calculations
                logger.debug("Calculating indicators using pandas fallback")

                result_df['ema_7'] = TALibCalculator._calculate_ema_fallback(close_prices, 7)
                result_df['ema_25'] = TALibCalculator._calculate_ema_fallback(close_prices, 25)
                result_df['rsi_6'] = TALibCalculator._calculate_rsi_fallback(close_prices, 6)
                result_df['volume_ma_20'] = TALibCalculator._calculate_sma_fallback(volumes, 20)

            # Log calculation summary
            ema7_valid = result_df['ema_7'].notna().sum()
            ema25_valid = result_df['ema_25'].notna().sum()
            rsi_valid = result_df['rsi_6'].notna().sum()
            vma_valid = result_df['volume_ma_20'].notna().sum()

            logger.debug(f"Indicators calculated: EMA7({ema7_valid}/{len(df)}), "
                       f"EMA25({ema25_valid}/{len(df)}), "
                       f"RSI({rsi_valid}/{len(df)}), VMA({vma_valid}/{len(df)})")

            return result_df

        except RecursionError:
            logger.error("CRITICAL: Infinite recursion detected in indicator calc!")
            raise RuntimeError("Infinite recursion in indicator calculation")
        except Exception as e:
            logger.error(f"Error calculating indicators: {e}")
            raise RuntimeError(f"Indicator calculation failed: {e}") from e

    @staticmethod
    def _calculate_ema_fallback(prices: np.ndarray, period: int) -> pd.Series:
        """
        Calculate EMA using pandas (fallback method).

        Args:
            prices: Array of prices
            period: EMA period

        Returns:
            Series with EMA values
        """
        try:
            prices_series = pd.Series(prices)
            return prices_series.ewm(span=period, adjust=False).mean()
        except Exception:
            return pd.Series([np.nan] * len(prices))

    @staticmethod
    def _calculate_rsi_fallback(prices: np.ndarray, period: int) -> pd.Series:
        """
        Calculate RSI using pandas (fallback method).

        Args:
            prices: Array of prices
            period: RSI period

        Returns:
            Series with RSI values
        """
        try:
            prices_series = pd.Series(prices)
            delta = prices_series.diff()

            gain = delta.where(delta > 0, 0)
            loss = -delta.where(delta < 0, 0)

            avg_gain = gain.rolling(window=period, min_periods=period).mean()
            avg_loss = loss.rolling(window=period, min_periods=period).mean()

            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

            return rsi
        except Exception:
            return pd.Series([np.nan] * len(prices))

    @staticmethod
    def _calculate_sma_fallback(values: np.ndarray, period: int) -> pd.Series:
        """
        Calculate SMA using pandas (fallback method).

        Args:
            values: Array of values
            period: SMA period

        Returns:
            Series with SMA values
        """
        try:
            values_series = pd.Series(values)
            return values_series.rolling(window=period, min_periods=period).mean()
        except Exception:
            return pd.Series([np.nan] * len(values))

    def is_talib_available(self) -> bool:
        """
        Check if TA-Lib is available.

        Returns:
            True if TA-Lib is available, False otherwise
        """
        return TALIB_AVAILABLE

    def get_version_info(self) -> dict:
        """
        Get version information for the calculator.

        Returns:
            Dictionary with version information
        """
        info = {
            'calculator': 'TALibCalculator',
            'talib_available': TALIB_AVAILABLE,
            'fallback_mode': not TALIB_AVAILABLE
        }

        if TALIB_AVAILABLE:
            info['talib_version'] = talib.__version__

        return info


# Alias for backward compatibility
IndicatorCalculator = TALibCalculator
