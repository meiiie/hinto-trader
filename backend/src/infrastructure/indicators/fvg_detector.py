"""
FVG Detector - Infrastructure Layer

Detects Fair Value Gaps (Imbalance) in price action.
SOTA Implementation: Identifying gaps between wicks of non-adjacent candles.
"""

from typing import List
from ...domain.entities.candle import Candle
from ...domain.interfaces.i_fvg_detector import IFVGDetector, FVG

class FVGDetector(IFVGDetector):
    def detect(self, candles: List[Candle], lookback: int = 100) -> List[FVG]:
        if len(candles) < 3:
            return []

        fvgs = []
        # Iterate through candles (starting from index 1 to len-2)
        start_index = max(1, len(candles) - lookback)

        for i in range(start_index, len(candles) - 1):
            prev_candle = candles[i-1] # i-1
            # curr_candle = candles[i] # i (The expansion candle)
            next_candle = candles[i+1] # i+1

            # 1. Bullish FVG Detection (Gap Up)
            # Condition: Low of (i+1) > High of (i-1)
            if next_candle.low > prev_candle.high:
                gap_size = next_candle.low - prev_candle.high
                # Optional: Filter tiny gaps
                if gap_size > 0:
                    fvg = FVG(
                        top=next_candle.low,
                        bottom=prev_candle.high,
                        midpoint=(next_candle.low + prev_candle.high) / 2,
                        fvg_type='BULLISH',
                        creation_time=candles[i].timestamp,
                        mitigated=False
                    )
                    # Check mitigation in future candles
                    if self._is_mitigated(fvg, candles[i+2:]):
                        fvg.mitigated = True

                    if not fvg.mitigated:
                        fvgs.append(fvg)

            # 2. Bearish FVG Detection (Gap Down)
            # Condition: High of (i+1) < Low of (i-1)
            elif next_candle.high < prev_candle.low:
                gap_size = prev_candle.low - next_candle.high
                if gap_size > 0:
                    fvg = FVG(
                        top=prev_candle.low,
                        bottom=next_candle.high,
                        midpoint=(prev_candle.low + next_candle.high) / 2,
                        fvg_type='BEARISH',
                        creation_time=candles[i].timestamp,
                        mitigated=False
                    )
                    if self._is_mitigated(fvg, candles[i+2:]):
                        fvg.mitigated = True

                    if not fvg.mitigated:
                        fvgs.append(fvg)

        return fvgs

    def _is_mitigated(self, fvg: FVG, future_candles: List[Candle]) -> bool:
        """Check if price has returned to fill the gap."""
        for c in future_candles:
            if fvg.fvg_type == 'BULLISH':
                # Price drops into gap
                if c.low <= fvg.top:
                    return True
            else:
                # Price rises into gap
                if c.high >= fvg.bottom:
                    return True
        return False
