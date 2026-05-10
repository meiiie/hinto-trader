"""
RSIMonitor - Application Layer

Monitors RSI values and generates alerts for overbought/oversold conditions.
"""

import logging
import pandas as pd
import numpy as np
from typing import List, Optional
from dataclasses import dataclass
from enum import Enum

from ...domain.entities.candle import Candle
from ...domain.interfaces import IIndicatorCalculator


class RSIZone(Enum):
    """RSI zone classifications (Professional short-term trading)"""
    STRONG_OVERSOLD = "strong_oversold"  # RSI < 20
    OVERSOLD = "oversold"                # 20 <= RSI < 35 (warning zone)
    NEUTRAL = "neutral"                  # 35 <= RSI < 65
    OVERBOUGHT = "overbought"            # 65 <= RSI < 80 (warning zone)
    STRONG_OVERBOUGHT = "strong_overbought"  # RSI >= 80


@dataclass
class RSIAlert:
    """
    RSI alert information.

    Attributes:
        zone: Current RSI zone
        rsi_value: Current RSI value
        message: Alert message
        severity: Alert severity (info, warning, critical)
    """
    zone: RSIZone
    rsi_value: float
    message: str
    severity: str  # 'info', 'warning', 'critical'


class RSIMonitor:
    """
    Monitor for RSI (Relative Strength Index) analysis.

    Features:
    - RSI(6) calculation using TA-Lib
    - Zone detection (strong oversold, oversold, neutral, overbought, strong overbought)
    - Alert generation for overbought/oversold conditions
    - Threshold customization
    """

    def __init__(
        self,
        period: int = 6,
        oversold_threshold: float = 35.0,
        overbought_threshold: float = 65.0,
        strong_oversold_threshold: float = 20.0,
        strong_overbought_threshold: float = 80.0,
        calculator: Optional[IIndicatorCalculator] = None
    ):
        """
        Initialize RSI monitor with professional short-term thresholds.

        Args:
            period: RSI period (default: 6 for short-term trading)
            oversold_threshold: Oversold warning zone (default: 35)
            overbought_threshold: Overbought warning zone (default: 65)
            strong_oversold_threshold: Strong oversold threshold (default: 20)
            strong_overbought_threshold: Strong overbought threshold (default: 80)
            calculator: Indicator calculator (injected)

        Professional Thresholds:
        - Strong Oversold: < 20 (Critical buy signal)
        - Oversold Warning: 20-35 (Approaching oversold)
        - Neutral: 35-65 (Normal trading range)
        - Overbought Warning: 65-80 (Approaching overbought)
        - Strong Overbought: >= 80 (Critical sell signal)
        """
        self.period = period
        self.oversold_threshold = oversold_threshold
        self.overbought_threshold = overbought_threshold
        self.strong_oversold_threshold = strong_oversold_threshold
        self.strong_overbought_threshold = strong_overbought_threshold

        # Warning zones for professional trading
        self.neutral_bottom = oversold_threshold  # 35
        self.neutral_top = overbought_threshold   # 65

        self.calculator = calculator  # Injected dependency
        self.logger = logging.getLogger(__name__)

        self.logger.info(
            f"RSIMonitor initialized: period={period}, "
            f"thresholds=[{strong_oversold_threshold}, {oversold_threshold}, "
            f"{overbought_threshold}, {strong_overbought_threshold}]"
        )

    def calculate_rsi(self, candles: List[Candle]) -> Optional[float]:
        """
        Calculate RSI for the given candles.

        Args:
            candles: List of Candle entities (chronological order)

        Returns:
            RSI value for the last candle, or None if insufficient data
        """
        if not candles:
            self.logger.warning("No candles provided for RSI calculation")
            return None

        # Need at least period + 1 candles for RSI
        if len(candles) < self.period + 1:
            self.logger.debug(
                f"Insufficient candles for RSI({self.period}): "
                f"got {len(candles)}, need {self.period + 1}"
            )
            return None

        try:
            # Convert candles to DataFrame
            data = {
                'close': [c.close for c in candles],
                'open': [c.open for c in candles],
                'high': [c.high for c in candles],
                'low': [c.low for c in candles],
                'volume': [c.volume for c in candles]
            }
            df = pd.DataFrame(data)

            # Calculate RSI using TALibCalculator
            result_df = self.calculator.calculate_all(df)

            # Get last RSI value
            rsi_values = result_df['rsi_6'].values
            last_rsi = rsi_values[-1]

            if np.isnan(last_rsi):
                self.logger.debug("RSI calculation returned NaN")
                return None

            return float(last_rsi)

        except Exception as e:
            self.logger.error(f"Error calculating RSI: {e}")
            return None


    def get_rsi_zone(self, rsi_value: float) -> RSIZone:
        """
        Determine RSI zone based on value and thresholds.

        Args:
            rsi_value: RSI value (0-100)

        Returns:
            RSIZone enum
        """
        if rsi_value < self.strong_oversold_threshold:
            return RSIZone.STRONG_OVERSOLD
        elif rsi_value < self.oversold_threshold:
            return RSIZone.OVERSOLD
        elif rsi_value < self.overbought_threshold:
            return RSIZone.NEUTRAL
        elif rsi_value < self.strong_overbought_threshold:
            return RSIZone.OVERBOUGHT
        else:
            return RSIZone.STRONG_OVERBOUGHT

    def generate_alerts(self, rsi_value: float) -> List[RSIAlert]:
        """
        Generate alerts based on RSI value.

        Args:
            rsi_value: Current RSI value

        Returns:
            List of RSIAlert objects
        """
        alerts = []
        zone = self.get_rsi_zone(rsi_value)

        if zone == RSIZone.STRONG_OVERBOUGHT:
            alerts.append(RSIAlert(
                zone=zone,
                rsi_value=rsi_value,
                message=f"🔴 STRONG OVERBOUGHT: RSI = {rsi_value:.2f} (>= {self.strong_overbought_threshold})",
                severity='critical'
            ))
        elif zone == RSIZone.OVERBOUGHT:
            alerts.append(RSIAlert(
                zone=zone,
                rsi_value=rsi_value,
                message=f"🟠 OVERBOUGHT: RSI = {rsi_value:.2f} (>= {self.overbought_threshold})",
                severity='warning'
            ))
        elif zone == RSIZone.OVERSOLD:
            alerts.append(RSIAlert(
                zone=zone,
                rsi_value=rsi_value,
                message=f"🟢 OVERSOLD: RSI = {rsi_value:.2f} (<= {self.oversold_threshold})",
                severity='warning'
            ))
        elif zone == RSIZone.STRONG_OVERSOLD:
            alerts.append(RSIAlert(
                zone=zone,
                rsi_value=rsi_value,
                message=f"🔵 STRONG OVERSOLD: RSI = {rsi_value:.2f} (<= {self.strong_oversold_threshold})",
                severity='critical'
            ))

        return alerts

    def analyze(self, candles: List[Candle]) -> Optional[dict]:
        """
        Perform complete RSI analysis.

        Args:
            candles: List of Candle entities

        Returns:
            Dict with RSI analysis results or None if insufficient data
        """
        rsi_value = self.calculate_rsi(candles)

        if rsi_value is None:
            return None

        zone = self.get_rsi_zone(rsi_value)
        alerts = self.generate_alerts(rsi_value)

        return {
            'rsi': rsi_value,
            'zone': zone,
            'alerts': alerts,
            'is_overbought': zone in [RSIZone.OVERBOUGHT, RSIZone.STRONG_OVERBOUGHT],
            'is_oversold': zone in [RSIZone.OVERSOLD, RSIZone.STRONG_OVERSOLD],
            'is_neutral': zone == RSIZone.NEUTRAL
        }

    def get_zone_color(self, zone: RSIZone) -> str:
        """
        Get color code for RSI zone (for UI display).

        Args:
            zone: RSIZone enum

        Returns:
            Color name or hex code
        """
        color_map = {
            RSIZone.STRONG_OVERSOLD: '#26C6DA',  # Cyan
            RSIZone.OVERSOLD: '#66BB6A',         # Green
            RSIZone.NEUTRAL: '#FFC107',          # Yellow
            RSIZone.OVERBOUGHT: '#FF9800',       # Orange
            RSIZone.STRONG_OVERBOUGHT: '#EF5350' # Red
        }
        return color_map.get(zone, '#757575')  # Gray default

    def get_zone_label(self, zone: RSIZone) -> str:
        """
        Get human-readable label for RSI zone.

        Args:
            zone: RSIZone enum

        Returns:
            Zone label string
        """
        label_map = {
            RSIZone.STRONG_OVERSOLD: 'Strong Oversold',
            RSIZone.OVERSOLD: 'Oversold',
            RSIZone.NEUTRAL: 'Neutral',
            RSIZone.OVERBOUGHT: 'Overbought',
            RSIZone.STRONG_OVERBOUGHT: 'Strong Overbought'
        }
        return label_map.get(zone, 'Unknown')

    def __repr__(self) -> str:
        """String representation"""
        return (
            f"RSIMonitor(period={self.period}, "
            f"thresholds={self.strong_oversold_threshold}/"
            f"{self.oversold_threshold}/"
            f"{self.overbought_threshold}/"
            f"{self.strong_overbought_threshold})"
        )
