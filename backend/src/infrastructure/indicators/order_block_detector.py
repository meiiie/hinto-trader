"""
Order Block Detector - Infrastructure Layer

Detects Order Blocks based on Market Structure Break (MSB).
SOTA Implementation: Identifies the last opposing candle before a significant move.
"""

from typing import List, Optional
from ...domain.entities.candle import Candle
from ...domain.interfaces.i_order_block_detector import IOrderBlockDetector, OrderBlock

class OrderBlockDetector(IOrderBlockDetector):
    def detect(self, candles: List[Candle], lookback: int = 50) -> List[OrderBlock]:
        if len(candles) < lookback:
            return []

        order_blocks = []

        # Simple Pivot High/Low detection for MSB
        # Iterate backwards to find recent OBs
        for i in range(len(candles) - 5, 5, -1):
            # Bullish MSB Detection (Price broke above a recent high)
            # 1. Identify a local high at i-2
            if self._is_swing_high(candles, i-2):
                swing_high = candles[i-2].high
                # 2. Check if a later candle broke this high
                for j in range(i-1, len(candles)):
                    if candles[j].close > swing_high:
                        # MSB Confirmed. Look for the OB (last red candle) before the move started
                        # Search backwards from the breakout start (approx i-2)
                        ob_candle = self._find_last_red_candle(candles, i-2)
                        if ob_candle:
                            ob = OrderBlock(
                                top=ob_candle.high,
                                bottom=ob_candle.low,
                                mitigated=False, # Naive check
                                ob_type='BULLISH',
                                creation_time=ob_candle.timestamp,
                                volume=ob_candle.volume
                            )
                            # Check mitigation
                            if self._is_mitigated(ob, candles[j+1:]):
                                ob.mitigated = True

                            # Only add if not mitigated (or keep track)
                            if not ob.mitigated:
                                order_blocks.append(ob)
                        break

            # Bearish MSB Detection (Price broke below a recent low)
            if self._is_swing_low(candles, i-2):
                swing_low = candles[i-2].low
                for j in range(i-1, len(candles)):
                    if candles[j].close < swing_low:
                        # MSB Confirmed. Look for OB (last green candle)
                        ob_candle = self._find_last_green_candle(candles, i-2)
                        if ob_candle:
                            ob = OrderBlock(
                                top=ob_candle.high,
                                bottom=ob_candle.low,
                                mitigated=False,
                                ob_type='BEARISH',
                                creation_time=ob_candle.timestamp,
                                volume=ob_candle.volume
                            )
                            if self._is_mitigated(ob, candles[j+1:]):
                                ob.mitigated = True
                            if not ob.mitigated:
                                order_blocks.append(ob)
                        break

        return order_blocks

    def _is_swing_high(self, candles, index):
        # Fractal High (5 candles)
        return (candles[index].high > candles[index-1].high and
                candles[index].high > candles[index-2].high and
                candles[index].high > candles[index+1].high and
                candles[index].high > candles[index+2].high)

    def _is_swing_low(self, candles, index):
        # Fractal Low
        return (candles[index].low < candles[index-1].low and
                candles[index].low < candles[index-2].low and
                candles[index].low < candles[index+1].low and
                candles[index].low < candles[index+2].low)

    def _find_last_red_candle(self, candles, start_index) -> Optional[Candle]:
        # Search backwards from start_index
        for k in range(start_index, max(0, start_index - 20), -1):
            if candles[k].close < candles[k].open: # Red
                return candles[k]
        return None

    def _find_last_green_candle(self, candles, start_index) -> Optional[Candle]:
        for k in range(start_index, max(0, start_index - 20), -1):
            if candles[k].close > candles[k].open: # Green
                return candles[k]
        return None

    def _is_mitigated(self, ob: OrderBlock, future_candles: List[Candle]) -> bool:
        """Check if price has returned to touch the OB."""
        for c in future_candles:
            if ob.ob_type == 'BULLISH':
                # Price drops into OB zone
                if c.low <= ob.top:
                    return True
            else:
                # Price rises into OB zone
                if c.high >= ob.bottom:
                    return True
        return False
