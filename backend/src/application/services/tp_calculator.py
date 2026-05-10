"""
Take Profit Calculator - Application Layer

Calculates multi-target TP system (TP1, TP2, TP3) based on support/resistance levels.
"""

import logging
from typing import Optional, List, Tuple
from dataclasses import dataclass

from ...domain.entities.candle import Candle
from ...domain.entities.enhanced_signal import TPLevels
from ...domain.interfaces import ISwingPointDetector


@dataclass
class TPCalculationResult:
    """
    TP calculation result with validation info.

    Attributes:
        tp_levels: Calculated TP levels
        risk_reward_ratio: Risk/reward ratio for TP1
        support_resistance_levels: Identified S/R levels used
        is_valid: Whether TP meets minimum R:R ratio
        calculation_method: Method used ('support_resistance' or 'atr_based')
        atr_value: ATR value used (if ATR-based)
    """
    tp_levels: TPLevels
    risk_reward_ratio: float
    support_resistance_levels: List[float]
    is_valid: bool
    calculation_method: str = 'support_resistance'
    atr_value: Optional[float] = None


class TPCalculator:
    """
    Calculator for multi-target Take Profit system.

    Features:
    - Calculate TP1 at nearest resistance/support (60% position)
    - Calculate TP2 at major resistance/support (30% position)
    - Calculate TP3 at extended target 1.5% beyond TP2 (10% position)
    - Validate minimum 1:1.5 risk-reward ratio
    - Use swing points for S/R identification

    Usage:
        calculator = TPCalculator(min_risk_reward=1.5)
        result = calculator.calculate_tp_levels(
            entry_price=50000.0,
            stop_loss=49500.0,
            direction='BUY',
            candles=candles
        )
    """

    def __init__(
        self,
        min_risk_reward: float = 1.5,
        tp3_extension_pct: float = 0.015,  # 1.5%
        swing_detector: Optional[ISwingPointDetector] = None
    ):
        """
        Initialize TP calculator.

        Args:
            min_risk_reward: Minimum risk-reward ratio for TP1 (default: 1.5)
            tp3_extension_pct: Extension percentage for TP3 beyond TP2 (default: 0.015 = 1.5%)
            swing_detector: Swing point detector (injected)
        """
        if min_risk_reward < 1.0:
            raise ValueError("Minimum risk-reward ratio must be >= 1.0")

        if tp3_extension_pct < 0 or tp3_extension_pct > 0.05:
            raise ValueError("TP3 extension must be between 0 and 0.05 (5%)")

        self.min_risk_reward = min_risk_reward
        self.tp3_extension_pct = tp3_extension_pct
        self.swing_detector = swing_detector  # Injected dependency
        self.logger = logging.getLogger(__name__)

        self.logger.info(
            f"TPCalculator initialized: "
            f"min_RR={min_risk_reward}, tp3_ext={tp3_extension_pct:.3%}"
        )

    def calculate_tp_levels(
        self,
        entry_price: float,
        stop_loss: float,
        direction: str,
        candles: List[Candle],
        atr_value: Optional[float] = None,
        force_breakout: bool = False
    ) -> Optional[TPCalculationResult]:
        """
        Calculate multi-target TP levels based on support/resistance.
        SOTA Upgrade: Supports Hybrid Breakout Logic using ATR when Swing R:R is poor.

        Args:
            entry_price: Entry price
            stop_loss: Stop loss price
            direction: 'BUY' or 'SELL'
            candles: List of Candle entities
            atr_value: Current ATR value (for breakout calculation)
            force_breakout: If True, ignore near swing points if they block the trade

        Returns:
            TPCalculationResult or None if calculation fails
        """
        # Validate inputs
        if direction not in ['BUY', 'SELL']:
            self.logger.error(f"Invalid direction: {direction}")
            return None

        if entry_price <= 0 or stop_loss <= 0:
            self.logger.error(f"Invalid prices: entry={entry_price}, stop={stop_loss}")
            return None

        if not candles or len(candles) < 11:
            self.logger.warning(f"Insufficient candles: need 11, got {len(candles)}")
            return None

        # Validate stop loss placement
        if direction == 'BUY' and stop_loss >= entry_price:
            self.logger.error(f"BUY: stop loss must be below entry")
            return None

        if direction == 'SELL' and stop_loss <= entry_price:
            self.logger.error(f"SELL: stop loss must be above entry")
            return None

        # Calculate based on direction
        if direction == 'BUY':
            return self._calculate_buy_tp_levels(entry_price, stop_loss, candles, atr_value, force_breakout)
        else:  # SELL
            return self._calculate_sell_tp_levels(entry_price, stop_loss, candles, atr_value, force_breakout)

    def _calculate_buy_tp_levels(
        self,
        entry_price: float,
        stop_loss: float,
        candles: List[Candle],
        atr_value: Optional[float] = None,
        force_breakout: bool = False
    ) -> Optional[TPCalculationResult]:
        """Calculate TP levels for BUY signal with Breakout Fallback."""
        risk = entry_price - stop_loss

        # Check if swing_detector is available
        if self.swing_detector is None:
            self.logger.warning("swing_detector not available, using fallback TP calculation")
            return self._calculate_fallback_buy_tp(entry_price, stop_loss)

        # Find resistance levels (swing highs)
        supports, resistances = self.swing_detector.find_support_resistance_levels(
            candles, num_levels=5
        )

        valid_resistances = [r for r in resistances if r > entry_price] if resistances else []

        # Strategy A: Swing Point TP
        swing_tp_valid = False
        if len(valid_resistances) >= 1:
            tp1_swing = valid_resistances[0]
            reward_swing = tp1_swing - entry_price
            rr_swing = reward_swing / risk if risk > 0 else 0

            if rr_swing >= self.min_risk_reward:
                # Good Swing Trade
                tp2 = valid_resistances[1] if len(valid_resistances) > 1 else tp1_swing * 1.01
                tp3 = tp2 * (1 + self.tp3_extension_pct)

                return TPCalculationResult(
                    tp_levels=TPLevels(tp1=tp1_swing, tp2=tp2, tp3=tp3, sizes=[0.6, 0.3, 0.1]),
                    risk_reward_ratio=rr_swing,
                    support_resistance_levels=valid_resistances,
                    is_valid=True,
                    calculation_method='swing_structure'
                )
            else:
                self.logger.debug(f"Swing RR too low: {rr_swing:.2f} < {self.min_risk_reward}")

        # Strategy B: Breakout ATR TP (If Swing failed or N/A, AND momentum is strong)
        if force_breakout and atr_value:
            # Assume price will break the resistance
            tp1_atr = entry_price + (atr_value * 2.0) # Aim for 2 ATR move (Breakout)
            reward_atr = tp1_atr - entry_price
            rr_atr = reward_atr / risk if risk > 0 else 0

            if rr_atr >= self.min_risk_reward:
                self.logger.info(f"🚀 SWITCHING TO BREAKOUT TP: Swing RR low, but Momentum is High. Target: {tp1_atr:.2f}")
                return self.calculate_tp_levels_atr_based(entry_price, 'BUY', atr_value)

        # If we reach here, neither Swing nor Breakout logic yielded a valid trade
        # Return the Swing result (even if invalid) so the caller knows why it failed
        if valid_resistances:
             tp1 = valid_resistances[0]
             return TPCalculationResult(
                tp_levels=TPLevels(tp1=tp1, tp2=tp1*1.01, tp3=tp1*1.02, sizes=[0.6, 0.3, 0.1]),
                risk_reward_ratio=(tp1 - entry_price) / risk,
                support_resistance_levels=valid_resistances,
                is_valid=False, # Invalid
                calculation_method='swing_structure'
             )

        return self._calculate_fallback_buy_tp(entry_price, stop_loss)

    def _calculate_sell_tp_levels(
        self,
        entry_price: float,
        stop_loss: float,
        candles: List[Candle],
        atr_value: Optional[float] = None,
        force_breakout: bool = False
    ) -> Optional[TPCalculationResult]:
        """Calculate TP levels for SELL signal with Breakout Fallback."""
        risk = stop_loss - entry_price

        # Check if swing_detector is available
        if self.swing_detector is None:
            self.logger.warning("swing_detector not available, using fallback TP calculation")
            return self._calculate_fallback_sell_tp(entry_price, stop_loss)

        # Find support levels
        supports, resistances = self.swing_detector.find_support_resistance_levels(
            candles, num_levels=5
        )

        valid_supports = [s for s in supports if s < entry_price] if supports else []

        # Strategy A: Swing Point TP
        if len(valid_supports) >= 1:
            tp1_swing = valid_supports[-1] # Highest support below entry
            reward_swing = entry_price - tp1_swing
            rr_swing = reward_swing / risk if risk > 0 else 0

            if rr_swing >= self.min_risk_reward:
                tp2 = valid_supports[-2] if len(valid_supports) > 1 else tp1_swing * 0.99
                tp3 = tp2 * (1 - self.tp3_extension_pct)

                return TPCalculationResult(
                    tp_levels=TPLevels(tp1=tp1_swing, tp2=tp2, tp3=tp3, sizes=[0.6, 0.3, 0.1]),
                    risk_reward_ratio=rr_swing,
                    support_resistance_levels=valid_supports,
                    is_valid=True,
                    calculation_method='swing_structure'
                )
            else:
                self.logger.debug(f"Swing RR too low: {rr_swing:.2f} < {self.min_risk_reward}")

        # Strategy B: Breakout ATR TP
        if force_breakout and atr_value:
            tp1_atr = entry_price - (atr_value * 2.0)
            reward_atr = entry_price - tp1_atr
            rr_atr = reward_atr / risk if risk > 0 else 0

            if rr_atr >= self.min_risk_reward:
                self.logger.info(f"🚀 SWITCHING TO BREAKOUT TP: Swing RR low, but Momentum is High. Target: {tp1_atr:.2f}")
                return self.calculate_tp_levels_atr_based(entry_price, 'SELL', atr_value)

        # Fail
        if valid_supports:
             tp1 = valid_supports[-1]
             return TPCalculationResult(
                tp_levels=TPLevels(tp1=tp1, tp2=tp1*0.99, tp3=tp1*0.98, sizes=[0.6, 0.3, 0.1]),
                risk_reward_ratio=(entry_price - tp1) / risk,
                support_resistance_levels=valid_supports,
                is_valid=False,
                calculation_method='swing_structure'
             )

        return self._calculate_fallback_sell_tp(entry_price, stop_loss)

    def _calculate_fallback_buy_tp(
        self,
        entry_price: float,
        stop_loss: float
    ) -> TPCalculationResult:
        """
        Fallback TP calculation for BUY when no S/R levels found.

        Uses percentage-based targets:
        - TP1: Entry + (Risk * 1.5)
        - TP2: Entry + (Risk * 2.5)
        - TP3: Entry + (Risk * 3.5)

        Args:
            entry_price: Entry price
            stop_loss: Stop loss price

        Returns:
            TPCalculationResult
        """
        risk = entry_price - stop_loss

        # Calculate TPs based on risk multiples
        tp1 = entry_price + (risk * 1.5)  # 1.5R
        tp2 = entry_price + (risk * 2.5)  # 2.5R
        tp3 = entry_price + (risk * 3.5)  # 3.5R

        tp_levels = TPLevels(
            tp1=tp1,
            tp2=tp2,
            tp3=tp3,
            sizes=[0.6, 0.3, 0.1]
        )

        self.logger.info(
            f"BUY fallback TP: TP1=${tp1:.2f} (1.5R), "
            f"TP2=${tp2:.2f} (2.5R), TP3=${tp3:.2f} (3.5R)"
        )

        return TPCalculationResult(
            tp_levels=tp_levels,
            risk_reward_ratio=1.5,
            support_resistance_levels=[],
            is_valid=True
        )

    def _calculate_fallback_sell_tp(
        self,
        entry_price: float,
        stop_loss: float
    ) -> TPCalculationResult:
        """
        Fallback TP calculation for SELL when no S/R levels found.

        Uses percentage-based targets:
        - TP1: Entry - (Risk * 1.5)
        - TP2: Entry - (Risk * 2.5)
        - TP3: Entry - (Risk * 3.5)

        Args:
            entry_price: Entry price
            stop_loss: Stop loss price

        Returns:
            TPCalculationResult
        """
        risk = stop_loss - entry_price

        # Calculate TPs based on risk multiples
        tp1 = entry_price - (risk * 1.5)  # 1.5R
        tp2 = entry_price - (risk * 2.5)  # 2.5R
        tp3 = entry_price - (risk * 3.5)  # 3.5R

        # SOTA FIX: Ensure all TP levels stay positive (minimum 0.5% of entry)
        min_tp = entry_price * 0.005  # Minimum 0.5% of entry price
        tp1 = max(tp1, min_tp)
        tp2 = max(tp2, min_tp * 0.8)
        tp3 = max(tp3, min_tp * 0.6)

        # Ensure proper ordering: tp1 > tp2 > tp3
        if tp2 >= tp1:
            tp2 = tp1 * 0.98
        if tp3 >= tp2:
            tp3 = tp2 * 0.98

        tp_levels = TPLevels(
            tp1=tp1,
            tp2=tp2,
            tp3=tp3,
            sizes=[0.6, 0.3, 0.1]
        )

        self.logger.info(
            f"SELL fallback TP: TP1=${tp1:.2f} (1.5R), "
            f"TP2=${tp2:.2f} (2.5R), TP3=${tp3:.2f} (3.5R)"
        )

        return TPCalculationResult(
            tp_levels=tp_levels,
            risk_reward_ratio=1.5,
            support_resistance_levels=[],
            is_valid=True
        )

    def validate_tp_levels(
        self,
        tp_levels: TPLevels,
        entry_price: float,
        stop_loss: float,
        direction: str
    ) -> bool:
        """
        Validate TP levels are correctly ordered and meet R:R requirements.

        Args:
            tp_levels: TP levels to validate
            entry_price: Entry price
            stop_loss: Stop loss price
            direction: 'BUY' or 'SELL'

        Returns:
            True if valid, False otherwise
        """
        # Check TP ordering
        if direction == 'BUY':
            if not (entry_price < tp_levels.tp1 < tp_levels.tp2 < tp_levels.tp3):
                return False
        else:  # SELL
            if not (entry_price > tp_levels.tp1 > tp_levels.tp2 > tp_levels.tp3):
                return False

        # Check minimum R:R ratio for TP1
        if direction == 'BUY':
            risk = entry_price - stop_loss
            reward = tp_levels.tp1 - entry_price
        else:  # SELL
            risk = stop_loss - entry_price
            reward = entry_price - tp_levels.tp1

        risk_reward_ratio = reward / risk if risk > 0 else 0

        return risk_reward_ratio >= self.min_risk_reward

    def calculate_tp_levels_atr_based(
        self,
        entry_price: float,
        direction: str,
        atr_value: float
    ) -> TPCalculationResult:
        """
        Calculate ATR-based TP levels with dynamic targets.

        TP levels based on ATR multiples:
        - TP1: 1x ATR (1:1 R:R) - 50% position
        - TP2: 2x ATR (2:1 R:R) - 30% position
        - TP3: 3x ATR (3:1 R:R) - 20% position

        Args:
            entry_price: Entry price
            direction: 'BUY' or 'SELL'
            atr_value: Current ATR value

        Returns:
            TPCalculationResult with ATR-based TP levels

        Example:
            >>> calculator = TPCalculator()
            >>> result = calculator.calculate_tp_levels_atr_based(
            ...     entry_price=50000.0,
            ...     direction='BUY',
            ...     atr_value=500.0
            ... )
            >>> print(f"TP1: ${result.tp_levels.tp1:,.2f}")
            >>> print(f"TP2: ${result.tp_levels.tp2:,.2f}")
            >>> print(f"TP3: ${result.tp_levels.tp3:,.2f}")
        """
        # Validate inputs
        if direction not in ['BUY', 'SELL']:
            raise ValueError(f"Invalid direction: {direction}")

        if entry_price <= 0:
            raise ValueError(f"Entry price must be positive: {entry_price}")

        if atr_value < 0:
            raise ValueError(f"ATR value must be non-negative: {atr_value}")

        # Calculate TP levels based on direction
        if direction == 'BUY':
            tp1 = entry_price + (atr_value * 1.0)  # 1x ATR
            tp2 = entry_price + (atr_value * 2.0)  # 2x ATR
            tp3 = entry_price + (atr_value * 3.0)  # 3x ATR
        else:  # SELL
            tp1 = entry_price - (atr_value * 1.0)  # 1x ATR
            tp2 = entry_price - (atr_value * 2.0)  # 2x ATR
            tp3 = entry_price - (atr_value * 3.0)  # 3x ATR

        # Validate TP levels are positive
        if tp1 <= 0 or tp2 <= 0 or tp3 <= 0:
            self.logger.warning(
                f"Calculated TP levels contain non-positive values: "
                f"TP1=${tp1:.2f}, TP2=${tp2:.2f}, TP3=${tp3:.2f}"
            )

        # Create TP levels with position sizes
        tp_levels = TPLevels(
            tp1=tp1,
            tp2=tp2,
            tp3=tp3,
            sizes=[0.5, 0.3, 0.2]  # 50%, 30%, 20%
        )

        # Calculate risk/reward ratio for TP1
        # Assuming stop loss is at entry - (3 × ATR) for BUY or entry + (3 × ATR) for SELL
        if direction == 'BUY':
            assumed_stop_loss = entry_price - (atr_value * 3.0)
            risk = entry_price - assumed_stop_loss
            reward = tp1 - entry_price
        else:  # SELL
            assumed_stop_loss = entry_price + (atr_value * 3.0)
            risk = assumed_stop_loss - entry_price
            reward = entry_price - tp1

        risk_reward_ratio = reward / risk if risk > 0 else 0

        self.logger.info(
            f"ATR-based {direction} TP levels: "
            f"TP1=${tp1:.2f} (1x ATR), TP2=${tp2:.2f} (2x ATR), TP3=${tp3:.2f} (3x ATR), "
            f"R:R={risk_reward_ratio:.2f}"
        )

        return TPCalculationResult(
            tp_levels=tp_levels,
            risk_reward_ratio=risk_reward_ratio,
            support_resistance_levels=[],
            is_valid=True
        )

    def __repr__(self) -> str:
        """String representation"""
        return (
            f"TPCalculator("
            f"min_RR={self.min_risk_reward}, "
            f"tp3_ext={self.tp3_extension_pct:.3%}, "
            f"swing_lookback={self.swing_detector.lookback})"
        )
