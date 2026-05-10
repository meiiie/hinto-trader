"""
Liquidity Zone Detector - Application Layer

Detects areas of concentrated stop losses, take profits, and potential
breakout zones using existing indicators (ATR, VWAP, Swing Points).

Based on Expert Feedback (gopy1.md):
- Uses ATR for zone width calculation
- Uses swing points for stop loss cluster detection
- Uses VWAP as dynamic support/resistance

This helps:
1. Avoid placing stop losses where they'll get hunted
2. Identify take profit zones with high conviction
3. Recognize breakout zones for momentum trades

References:
- Smart Money Concepts (SMC/ICT methodology)
- Institutional Order Flow patterns (Dec 2025)

Created: 2025-12-31
Author: Quant Specialist AI
"""

from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import numpy as np
import logging

from ...domain.entities.candle import Candle
from ...domain.interfaces import (
    ILiquidityZoneDetector,
    LiquidityZone,
    LiquidityZonesResult
)


logger = logging.getLogger(__name__)


class LiquidityZoneDetector(ILiquidityZoneDetector):
    """
    Detect liquidity zones from price action and indicators.

    This identifies:
    1. Stop Loss Clusters - where retail traders place stops (to avoid)
    2. Take Profit Zones - high-volume areas for profit taking
    3. Breakout Zones - consolidation areas that may lead to moves

    Algorithm:
    1. Find swing highs/lows as anchor points
    2. Create zones around them using ATR
    3. Count touches to determine zone strength
    4. Recommend optimal SL/TP placement

    Example usage:
        detector = LiquidityZoneDetector(atr_calculator)
        result = detector.detect_zones(candles, current_price)
        opt_sl = result.recommended_stop_loss
    """

    def __init__(
        self,
        atr_calculator=None,
        vwap_calculator=None,
        swing_lookback: int = 5,
        zone_atr_multiplier: float = 0.5
    ):
        """
        Initialize Liquidity Zone Detector.

        Args:
            atr_calculator: ATR calculator for zone width
            vwap_calculator: VWAP calculator for dynamic S/R
            swing_lookback: Candles to look for swing points
            zone_atr_multiplier: ATR multiplier for zone width
        """
        self.atr_calculator = atr_calculator
        self.vwap_calculator = vwap_calculator
        self.swing_lookback = swing_lookback
        self.zone_atr_multiplier = zone_atr_multiplier

        logger.info(
            f"📊 LiquidityZoneDetector initialized: "
            f"swing_lookback={swing_lookback}, zone_atr_mult={zone_atr_multiplier}"
        )

    def detect_zones(
        self,
        candles: List[Candle],
        current_price: Optional[float] = None,
        atr_value: Optional[float] = None
    ) -> Optional[LiquidityZonesResult]:
        """
        Detect all liquidity zones from candles.

        Args:
            candles: List of OHLCV candles
            current_price: Current market price (for recommendations)
            atr_value: Pre-calculated ATR (or will calculate)

        Returns:
            LiquidityZonesResult with all detected zones
        """
        start_time = datetime.now()

        if not candles or len(candles) < 20:
            logger.warning("Not enough candles for liquidity zone detection")
            return None

        try:
            # Use current price if not provided
            if current_price is None:
                current_price = candles[-1].close

            # Calculate ATR if not provided
            if atr_value is None:
                if self.atr_calculator:
                    atr_result = self.atr_calculator.calculate_atr(candles)
                    atr_value = atr_result.atr_value if atr_result else self._calculate_simple_atr(candles)
                else:
                    atr_value = self._calculate_simple_atr(candles)

            # Zone width based on ATR
            zone_width = atr_value * self.zone_atr_multiplier

            # 1. Find swing highs and lows
            swing_highs = self._find_swing_highs(candles, self.swing_lookback)
            swing_lows = self._find_swing_lows(candles, self.swing_lookback)

            # 2. Detect stop loss clusters (below swing lows)
            sl_clusters = self._detect_stop_loss_clusters(
                candles, swing_lows, zone_width
            )

            # 3. Detect take profit zones (near swing highs)
            tp_zones = self._detect_take_profit_zones(
                candles, swing_highs, zone_width
            )

            # 4. Detect breakout zones (consolidation areas)
            breakout_zones = self._detect_breakout_zones(
                candles, zone_width
            )

            # 5. Find nearest support/resistance
            nearest_support = self._find_nearest_zone(
                sl_clusters + [z for z in tp_zones if z.zone_high < current_price],
                current_price,
                below=True
            )

            nearest_resistance = self._find_nearest_zone(
                tp_zones + [z for z in sl_clusters if z.zone_low > current_price],
                current_price,
                below=False
            )

            # 6. Recommend optimal SL/TP
            recommended_sl = self._recommend_stop_loss(
                current_price, sl_clusters, zone_width
            )
            recommended_tp = self._recommend_take_profit(
                current_price, tp_zones, nearest_resistance
            )

            # Create result
            calc_time = (datetime.now() - start_time).total_seconds() * 1000

            result = LiquidityZonesResult(
                stop_loss_clusters=sl_clusters,
                take_profit_zones=tp_zones,
                breakout_zones=breakout_zones,
                nearest_support=nearest_support,
                nearest_resistance=nearest_resistance,
                recommended_stop_loss=recommended_sl,
                recommended_take_profit=recommended_tp,
                analysis_high=max(c.high for c in candles),
                analysis_low=min(c.low for c in candles),
                calculation_time_ms=round(calc_time, 2)
            )

            logger.debug(
                f"📊 Liquidity Zones: {len(sl_clusters)} SL clusters, "
                f"{len(tp_zones)} TP zones, {len(breakout_zones)} breakout zones, "
                f"time={calc_time:.1f}ms"
            )

            return result

        except Exception as e:
            logger.error(f"Error detecting liquidity zones: {e}")
            return None

    def _calculate_simple_atr(self, candles: List[Candle], period: int = 14) -> float:
        """Calculate simple ATR if no calculator provided."""
        if len(candles) < period:
            return candles[-1].high - candles[-1].low

        trs = []
        for i in range(1, len(candles)):
            c = candles[i]
            p = candles[i-1]
            tr = max(
                c.high - c.low,
                abs(c.high - p.close),
                abs(c.low - p.close)
            )
            trs.append(tr)

        return np.mean(trs[-period:])

    def _find_swing_highs(
        self,
        candles: List[Candle],
        lookback: int
    ) -> List[Tuple[int, float]]:
        """Find swing high points (local maxima)."""
        swing_highs = []

        for i in range(lookback, len(candles) - lookback):
            current_high = candles[i].high
            is_swing = True

            for j in range(i - lookback, i + lookback + 1):
                if j != i and candles[j].high >= current_high:
                    is_swing = False
                    break

            if is_swing:
                swing_highs.append((i, current_high))

        return swing_highs

    def _find_swing_lows(
        self,
        candles: List[Candle],
        lookback: int
    ) -> List[Tuple[int, float]]:
        """Find swing low points (local minima)."""
        swing_lows = []

        for i in range(lookback, len(candles) - lookback):
            current_low = candles[i].low
            is_swing = True

            for j in range(i - lookback, i + lookback + 1):
                if j != i and candles[j].low <= current_low:
                    is_swing = False
                    break

            if is_swing:
                swing_lows.append((i, current_low))

        return swing_lows

    def _detect_stop_loss_clusters(
        self,
        candles: List[Candle],
        swing_lows: List[Tuple[int, float]],
        zone_width: float
    ) -> List[LiquidityZone]:
        """
        Detect stop loss cluster zones below swing lows.

        Retail traders typically place stops just below swing lows,
        making these areas targets for stop hunts.
        """
        sl_clusters = []

        for idx, swing_low in swing_lows[-5:]:  # Last 5 swing lows
            zone_low = swing_low - zone_width
            zone_high = swing_low

            # Count touches (price came close to this level)
            touch_count = 0
            last_touch = idx

            for i, c in enumerate(candles[idx:], start=idx):
                if zone_low <= c.low <= zone_high:
                    touch_count += 1
                    last_touch = i

            # Check if zone was broken
            is_broken = any(c.close < zone_low for c in candles[idx:])

            # Strength based on touches and recency
            recency_factor = 1 - (len(candles) - last_touch) / len(candles)
            strength = min(1.0, (touch_count * 0.2 + recency_factor * 0.5))

            if not is_broken:
                sl_clusters.append(LiquidityZone(
                    zone_low=zone_low,
                    zone_high=zone_high,
                    zone_type="stop_loss_cluster",
                    strength=strength,
                    touch_count=touch_count,
                    last_touch_idx=last_touch,
                    is_broken=is_broken
                ))

        return sorted(sl_clusters, key=lambda z: z.zone_low, reverse=True)

    def _detect_take_profit_zones(
        self,
        candles: List[Candle],
        swing_highs: List[Tuple[int, float]],
        zone_width: float
    ) -> List[LiquidityZone]:
        """
        Detect take profit zones near swing highs.

        Traders often take profits at previous highs (resistance).
        """
        tp_zones = []

        for idx, swing_high in swing_highs[-5:]:  # Last 5 swing highs
            zone_low = swing_high
            zone_high = swing_high + zone_width

            # Count touches
            touch_count = 0
            last_touch = idx

            for i, c in enumerate(candles[idx:], start=idx):
                if zone_low <= c.high <= zone_high:
                    touch_count += 1
                    last_touch = i

            # Check if zone was broken (price closed above)
            is_broken = any(c.close > zone_high for c in candles[idx:])

            # Strength
            recency_factor = 1 - (len(candles) - last_touch) / len(candles)
            strength = min(1.0, (touch_count * 0.2 + recency_factor * 0.5))

            if not is_broken:
                tp_zones.append(LiquidityZone(
                    zone_low=zone_low,
                    zone_high=zone_high,
                    zone_type="take_profit_zone",
                    strength=strength,
                    touch_count=touch_count,
                    last_touch_idx=last_touch,
                    is_broken=is_broken
                ))

        return sorted(tp_zones, key=lambda z: z.zone_low)

    def _detect_breakout_zones(
        self,
        candles: List[Candle],
        zone_width: float
    ) -> List[LiquidityZone]:
        """
        Detect consolidation / breakout zones.

        Areas where price has been ranging with multiple touches
        on both sides, indicating potential breakout.
        """
        breakout_zones = []

        # Look for consolidation ranges in recent candles
        recent_candles = candles[-30:]
        if len(recent_candles) < 20:
            return breakout_zones

        # Find tight ranges
        for i in range(0, len(recent_candles) - 10, 5):
            window = recent_candles[i:i+10]
            high = max(c.high for c in window)
            low = min(c.low for c in window)
            range_pct = (high - low) / low * 100

            # Tight range = potential breakout zone
            if range_pct < 3.0:  # Less than 3% range
                touch_count = sum(
                    1 for c in window
                    if c.high > high - zone_width or c.low < low + zone_width
                )

                strength = min(1.0, range_pct / 3.0 + touch_count * 0.1)

                breakout_zones.append(LiquidityZone(
                    zone_low=low,
                    zone_high=high,
                    zone_type="breakout_zone",
                    strength=strength,
                    touch_count=touch_count,
                    last_touch_idx=i + len(candles) - len(recent_candles),
                    is_broken=False
                ))

        return breakout_zones[:3]  # Top 3 most recent

    def _find_nearest_zone(
        self,
        zones: List[LiquidityZone],
        price: float,
        below: bool
    ) -> Optional[LiquidityZone]:
        """Find nearest zone above or below price."""
        if not zones:
            return None

        if below:
            # Zones below price
            valid = [z for z in zones if z.zone_high < price]
            if valid:
                return max(valid, key=lambda z: z.zone_high)
        else:
            # Zones above price
            valid = [z for z in zones if z.zone_low > price]
            if valid:
                return min(valid, key=lambda z: z.zone_low)

        return None

    def _recommend_stop_loss(
        self,
        current_price: float,
        sl_clusters: List[LiquidityZone],
        zone_width: float
    ) -> Optional[float]:
        """
        Recommend optimal stop loss placement.

        Places SL OUTSIDE stop loss clusters to avoid stop hunts.
        """
        if not sl_clusters:
            return None

        # Find nearest SL cluster below current price
        below_clusters = [z for z in sl_clusters if z.zone_high < current_price]
        if not below_clusters:
            return None

        nearest = max(below_clusters, key=lambda z: z.zone_high)

        # Place stop BELOW the cluster (outside the hunt zone)
        recommended = nearest.zone_low - zone_width * 0.5

        return round(recommended, 4)

    def _recommend_take_profit(
        self,
        current_price: float,
        tp_zones: List[LiquidityZone],
        nearest_resistance: Optional[LiquidityZone]
    ) -> Optional[float]:
        """
        Recommend take profit placement.

        Places TP at high-confidence resistance zones.
        """
        if nearest_resistance:
            # TP at resistance zone midpoint
            return round(nearest_resistance.midpoint, 4)

        if tp_zones:
            # Find strongest zone above current price
            above_zones = [z for z in tp_zones if z.zone_low > current_price]
            if above_zones:
                strongest = max(above_zones, key=lambda z: z.strength)
                return round(strongest.midpoint, 4)

        return None
