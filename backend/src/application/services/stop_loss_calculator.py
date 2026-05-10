"""
Stop Loss Calculator - Application Layer

Calculates risk-based stop loss ensuring maximum 1% account risk.
"""

import logging
from typing import Optional, List, Any
from dataclasses import dataclass

from ...domain.entities.candle import Candle
from ...domain.interfaces import ISwingPointDetector


@dataclass
class StopLossResult:
    """
    Stop loss calculation result.

    Attributes:
        stop_loss: Calculated stop loss price
        stop_type: Type of stop ('swing', 'ema', 'risk_based', 'atr_based', 'smart_liquidity')
        distance_from_entry_pct: Distance from entry in percentage
        swing_level: Swing level used (if applicable)
        ema_level: EMA level used (if applicable)
        is_valid: Whether stop meets minimum distance requirement
        atr_value: ATR value used (if ATR-based)
        atr_multiplier: ATR multiplier used (if ATR-based)
        position_size: Calculated position size (if applicable)
        risk_amount: Risk amount in dollars (if applicable)
    """
    stop_loss: float
    stop_type: str
    distance_from_entry_pct: float
    swing_level: Optional[float] = None
    ema_level: Optional[float] = None
    is_valid: bool = True
    atr_value: Optional[float] = None
    atr_multiplier: Optional[float] = None
    position_size: Optional[float] = None
    risk_amount: Optional[float] = None


class StopLossCalculator:
    """
    Calculator for risk-based stop loss.

    Features:
    - Calculate stop ensuring max 1% account risk
    - BUY: Place stop below swing low or EMA(25)
    - SELL: Place stop above swing high or EMA(25)
    - Use more conservative (safer) stop
    - Validate minimum 0.3% distance from entry
    - Smart Liquidity Stop Loss using Volume Profile

    Usage:
        calculator = StopLossCalculator(
            max_risk_pct=0.01,
            min_distance_pct=0.003
        )
        result = calculator.calculate_stop_loss(
            entry_price=50000.0,
            direction='BUY',
            candles=candles,
            ema25=49500.0,
            account_size=10000.0
        )
    """

    def __init__(
        self,
        max_risk_pct: float = 0.01,  # 1%
        min_distance_pct: float = 0.003,  # 0.3%
        stop_buffer_pct: float = 0.001,  # 0.1% buffer below/above swing
        swing_detector: Optional[ISwingPointDetector] = None
    ):
        """
        Initialize stop loss calculator.

        Args:
            max_risk_pct: Maximum risk per trade (default: 0.01 = 1%)
            min_distance_pct: Minimum distance from entry (default: 0.003 = 0.3%)
            stop_buffer_pct: Buffer below/above swing point (default: 0.001 = 0.1%)
            swing_detector: Swing point detector (injected)
        """
        if max_risk_pct <= 0 or max_risk_pct > 0.05:
            raise ValueError("Max risk must be between 0 and 0.05 (5%)")

        if min_distance_pct < 0 or min_distance_pct > 0.01:
            raise ValueError("Min distance must be between 0 and 0.01 (1%)")

        self.max_risk_pct = max_risk_pct
        self.min_distance_pct = min_distance_pct
        self.stop_buffer_pct = stop_buffer_pct
        self.swing_detector = swing_detector  # Injected dependency
        self.logger = logging.getLogger(__name__)

        self.logger.info(
            f"StopLossCalculator initialized: "
            f"max_risk={max_risk_pct:.3%}, min_distance={min_distance_pct:.3%}"
        )

    def calculate_smart_stop_loss(
        self,
        entry_price: float,
        direction: str,
        volume_profile: Any, # VolumeProfileResult
        atr_value: float
    ) -> float:
        """
        Calculate Smart Stop Loss using Volume Profile Value Area.
        Puts SL outside value area to avoid liquidity hunts.

        Logic:
        - LONG: SL < VAL (Value Area Low) - 0.5 * ATR
        - SHORT: SL > VAH (Value Area High) + 0.5 * ATR

        Args:
            entry_price: Entry price
            direction: 'BUY' or 'SELL'
            volume_profile: VolumeProfileResult object
            atr_value: Current ATR value

        Returns:
            Calculated stop loss price
        """
        if not volume_profile or atr_value <= 0:
            # Fallback to standard 1.5% stop if VP not available
            if direction == 'BUY':
                return entry_price * 0.985
            else:
                return entry_price * 1.015

        buffer = atr_value * 0.5

        if direction == 'BUY':
            # Place below Value Area Low
            smart_sl = volume_profile.val - buffer
            # Safety check: SL shouldn't be above entry
            if smart_sl >= entry_price:
                smart_sl = entry_price - (atr_value * 1.5)
        else:
            # Place above Value Area High
            smart_sl = volume_profile.vah + buffer
            # Safety check: SL shouldn't be below entry
            if smart_sl <= entry_price:
                smart_sl = entry_price + (atr_value * 1.5)

        self.logger.info(
            f"🛡️ Smart Liquidity SL ({direction}): {smart_sl:.2f} "
            f"(VAL={volume_profile.val:.2f}, VAH={volume_profile.vah:.2f}, ATR={atr_value:.2f})"
        )
        return smart_sl

    def calculate_stop_loss(
        self,
        entry_price: float,
        direction: str,
        candles: List[Candle],
        ema25: float,
        account_size: Optional[float] = None
    ) -> Optional[StopLossResult]:
        """
        Calculate risk-based stop loss.

        For BUY signals:
        - Find swing low and EMA(25)
        - Use lower of the two (more conservative)
        - Apply buffer below stop level
        - Validate against max risk if account_size provided

        For SELL signals:
        - Find swing high and EMA(25)
        - Use higher of the two (more conservative)
        - Apply buffer above stop level
        - Validate against max risk if account_size provided

        Args:
            entry_price: Entry price
            direction: 'BUY' or 'SELL'
            candles: List of Candle entities
            ema25: Current EMA(25) value
            account_size: Account size for risk validation (optional)

        Returns:
            StopLossResult or None if calculation fails

        Example:
            >>> calculator = StopLossCalculator()
            >>> result = calculator.calculate_stop_loss(
            ...     entry_price=50000.0,
            ...     direction='BUY',
            ...     candles=candles,
            ...     ema25=49500.0,
            ...     account_size=10000.0
            ... )
            >>> if result and result.is_valid:
            ...     print(f"Stop Loss: ${result.stop_loss:,.2f}")
        """
        # Validate inputs
        if direction not in ['BUY', 'SELL']:
            self.logger.error(f"Invalid direction: {direction}")
            return None

        if entry_price <= 0 or ema25 <= 0:
            self.logger.error(f"Invalid prices: entry={entry_price}, ema25={ema25}")
            return None

        if not candles or len(candles) < 11:
            self.logger.warning(f"Insufficient candles: need 11, got {len(candles)}")
            return None

        # Calculate based on direction
        if direction == 'BUY':
            return self._calculate_buy_stop_loss(
                entry_price, candles, ema25, account_size
            )
        else:  # SELL
            return self._calculate_sell_stop_loss(
                entry_price, candles, ema25, account_size
            )

    def _calculate_buy_stop_loss(
        self,
        entry_price: float,
        candles: List[Candle],
        ema25: float,
        account_size: Optional[float]
    ) -> StopLossResult:
        """
        Calculate stop loss for BUY signal.

        Args:
            entry_price: Entry price
            candles: List of candles
            ema25: EMA(25) value
            account_size: Account size (optional)

        Returns:
            StopLossResult
        """
        # Find swing low
        swing_low = self.swing_detector.find_recent_swing_low(candles)
        swing_level = swing_low.price if swing_low else None

        # Candidate stops
        candidates = []

        # 1. Swing-based stop (below swing low with buffer)
        if swing_level:
            swing_stop = swing_level * (1 - self.stop_buffer_pct)
            if swing_stop < entry_price:
                candidates.append(('swing', swing_stop, swing_level))
                self.logger.debug(f"BUY swing stop: ${swing_stop:.2f}")

        # 2. EMA(25)-based stop (below EMA with buffer)
        ema_stop = ema25 * (1 - self.stop_buffer_pct)
        if ema_stop < entry_price:
            candidates.append(('ema', ema_stop, ema25))
            self.logger.debug(f"BUY EMA stop: ${ema_stop:.2f}")

        # 3. Risk-based stop (if account size provided)
        if account_size:
            max_risk_amount = account_size * self.max_risk_pct
            # Assume position size that risks max 1%
            # This is a fallback if swing/EMA stops are too tight
            risk_stop = entry_price * 0.99  # 1% below entry as fallback
            candidates.append(('risk_based', risk_stop, None))
            self.logger.debug(f"BUY risk stop: ${risk_stop:.2f}")

        if not candidates:
            # Fallback: 1% below entry
            stop_loss = entry_price * 0.99
            stop_type = 'fallback'
            self.logger.warning(f"BUY: Using fallback stop at ${stop_loss:.2f}")
        else:
            # Use most conservative (lowest) stop for BUY
            stop_type, stop_loss, level = min(candidates, key=lambda x: x[1])
            self.logger.info(
                f"BUY: Selected {stop_type} stop at ${stop_loss:.2f}"
            )

        # Calculate distance from entry
        distance_pct = abs((entry_price - stop_loss) / entry_price)

        # Validate minimum distance
        is_valid = distance_pct >= self.min_distance_pct

        if not is_valid:
            self.logger.warning(
                f"BUY stop too close: {distance_pct:.3%} < {self.min_distance_pct:.3%}"
            )

        return StopLossResult(
            stop_loss=stop_loss,
            stop_type=stop_type,
            distance_from_entry_pct=distance_pct,
            swing_level=swing_level,
            ema_level=ema25,
            is_valid=is_valid
        )

    def _calculate_sell_stop_loss(
        self,
        entry_price: float,
        candles: List[Candle],
        ema25: float,
        account_size: Optional[float]
    ) -> StopLossResult:
        """
        Calculate stop loss for SELL signal.

        Args:
            entry_price: Entry price
            candles: List of candles
            ema25: EMA(25) value
            account_size: Account size (optional)

        Returns:
            StopLossResult
        """
        # Find swing high
        swing_high = self.swing_detector.find_recent_swing_high(candles)
        swing_level = swing_high.price if swing_high else None

        # Candidate stops
        candidates = []

        # 1. Swing-based stop (above swing high with buffer)
        if swing_level:
            swing_stop = swing_level * (1 + self.stop_buffer_pct)
            if swing_stop > entry_price:
                candidates.append(('swing', swing_stop, swing_level))
                self.logger.debug(f"SELL swing stop: ${swing_stop:.2f}")

        # 2. EMA(25)-based stop (above EMA with buffer)
        ema_stop = ema25 * (1 + self.stop_buffer_pct)
        if ema_stop > entry_price:
            candidates.append(('ema', ema_stop, ema25))
            self.logger.debug(f"SELL EMA stop: ${ema_stop:.2f}")

        # 3. Risk-based stop (if account size provided)
        if account_size:
            max_risk_amount = account_size * self.max_risk_pct
            # Fallback if swing/EMA stops are too tight
            risk_stop = entry_price * 1.01  # 1% above entry as fallback
            candidates.append(('risk_based', risk_stop, None))
            self.logger.debug(f"SELL risk stop: ${risk_stop:.2f}")

        if not candidates:
            # Fallback: 1% above entry
            stop_loss = entry_price * 1.01
            stop_type = 'fallback'
            self.logger.warning(f"SELL: Using fallback stop at ${stop_loss:.2f}")
        else:
            # Use most conservative (highest) stop for SELL
            stop_type, stop_loss, level = max(candidates, key=lambda x: x[1])
            self.logger.info(
                f"SELL: Selected {stop_type} stop at ${stop_loss:.2f}"
            )

        # Calculate distance from entry
        distance_pct = abs((stop_loss - entry_price) / entry_price)

        # Validate minimum distance
        is_valid = distance_pct >= self.min_distance_pct

        if not is_valid:
            self.logger.warning(
                f"SELL stop too close: {distance_pct:.3%} < {self.min_distance_pct:.3%}"
            )

        return StopLossResult(
            stop_loss=stop_loss,
            stop_type=stop_type,
            distance_from_entry_pct=distance_pct,
            swing_level=swing_level,
            ema_level=ema25,
            is_valid=is_valid
        )

    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss: float,
        account_size: float,
        risk_pct: Optional[float] = None
    ) -> float:
        """
        Calculate position size for specified risk.

        Args:
            entry_price: Entry price
            stop_loss: Stop loss price
            account_size: Total account size
            risk_pct: Risk percentage (default: use max_risk_pct)

        Returns:
            Position size

        Example:
            >>> calculator = StopLossCalculator()
            >>> size = calculator.calculate_position_size(
            ...     entry_price=50000.0,
            ...     stop_loss=49500.0,
            ...     account_size=10000.0
            ... )
            >>> print(f"Position: {size:.6f} BTC")
        """
        if risk_pct is None:
            risk_pct = self.max_risk_pct

        # Calculate risk amount
        max_risk_amount = account_size * risk_pct

        # Calculate risk per unit
        risk_per_unit = abs(entry_price - stop_loss)

        if risk_per_unit == 0:
            self.logger.error("Risk per unit is zero")
            return 0.0

        # Calculate position size
        position_size = max_risk_amount / risk_per_unit

        self.logger.info(
            f"Position size: {position_size:.6f} "
            f"(risk: ${max_risk_amount:.2f}, per unit: ${risk_per_unit:.2f})"
        )

        return position_size

    def validate_stop_loss(
        self,
        stop_loss: float,
        entry_price: float,
        direction: str
    ) -> bool:
        """
        Validate stop loss placement.

        Args:
            stop_loss: Stop loss price
            entry_price: Entry price
            direction: 'BUY' or 'SELL'

        Returns:
            True if valid, False otherwise
        """
        # Check stop is on correct side of entry
        if direction == 'BUY':
            if stop_loss >= entry_price:
                self.logger.error(f"BUY: Stop must be below entry")
                return False
        else:  # SELL
            if stop_loss <= entry_price:
                self.logger.error(f"SELL: Stop must be above entry")
                return False

        # Check minimum distance
        distance_pct = abs((entry_price - stop_loss) / entry_price)
        if distance_pct < self.min_distance_pct:
            self.logger.error(
                f"Stop too close: {distance_pct:.3%} < {self.min_distance_pct:.3%}"
            )
            return False

        return True

    def calculate_stop_loss_atr_based(
        self,
        entry_price: float,
        direction: str,
        atr_value: float,
        atr_multiplier: float = 3.0,
        min_distance_pct: float = 0.015
    ) -> StopLossResult:
        """
        Calculate ATR-based stop loss with dynamic position sizing.

        This method replaces fixed stop loss with volatility-based stops
        that adapt to market conditions.

        Args:
            entry_price: Entry price
            direction: 'BUY' or 'SELL'
            atr_value: Current ATR value
            atr_multiplier: ATR multiplier (default: 3.0 for 15m timeframe)
            min_distance_pct: Minimum distance % (default: 0.015 = 1.5%)

        Returns:
            StopLossResult with ATR-based stop loss

        Example:
            >>> calculator = StopLossCalculator()
            >>> result = calculator.calculate_stop_loss_atr_based(
            ...     entry_price=50000.0,
            ...     direction='BUY',
            ...     atr_value=500.0,
            ...     atr_multiplier=3.0
            ... )
            >>> print(f"Stop Loss: ${result.stop_loss:,.2f}")
            >>> print(f"Distance: {result.distance_from_entry_pct:.2%}")
        """
        # Validate inputs
        if direction not in ['BUY', 'SELL']:
            raise ValueError(f"Invalid direction: {direction}")

        if entry_price <= 0:
            raise ValueError(f"Entry price must be positive: {entry_price}")

        if atr_value < 0:
            raise ValueError(f"ATR value must be non-negative: {atr_value}")

        if atr_multiplier <= 0:
            raise ValueError(f"ATR multiplier must be positive: {atr_multiplier}")

        # Calculate ATR-based distance
        atr_distance = atr_value * atr_multiplier

        # Calculate minimum distance in dollars
        min_distance_dollars = entry_price * min_distance_pct

        # Use larger of ATR distance or minimum distance
        stop_distance = max(atr_distance, min_distance_dollars)

        # Calculate stop loss price based on direction
        if direction == 'BUY':
            stop_loss = entry_price - stop_distance
        else:  # SELL
            stop_loss = entry_price + stop_distance

        # Calculate distance percentage
        distance_pct = (stop_distance / entry_price)

        # Validate stop loss is positive
        if stop_loss <= 0:
            self.logger.warning(
                f"Calculated stop loss is non-positive: ${stop_loss:.2f}, "
                f"using minimum distance instead"
            )
            if direction == 'BUY':
                stop_loss = entry_price * (1 - min_distance_pct)
            else:
                stop_loss = entry_price * (1 + min_distance_pct)
            distance_pct = min_distance_pct

        self.logger.info(
            f"ATR-based {direction} stop: ${stop_loss:.2f} "
            f"(distance: ${stop_distance:.2f}, {distance_pct:.2%}, "
            f"ATR: ${atr_value:.2f} × {atr_multiplier})"
        )

        return StopLossResult(
            stop_loss=stop_loss,
            stop_type='atr_based',
            distance_from_entry_pct=distance_pct,
            swing_level=None,
            ema_level=None,
            is_valid=True
        )

    def calculate_position_size_with_risk(
        self,
        entry_price: float,
        stop_loss: float,
        account_balance: float,
        risk_pct: float = 0.01
    ) -> float:
        """
        Calculate position size for 1% risk rule.

        Formula: position_size = (account × risk_pct) / stop_distance

        This ensures that if stop loss is hit, the loss is exactly
        risk_pct of the account balance.

        Args:
            entry_price: Entry price
            stop_loss: Stop loss price
            account_balance: Current account balance
            risk_pct: Risk percentage per trade (default: 0.01 = 1%)

        Returns:
            Position size in BTC (8 decimal precision)

        Example:
            >>> calculator = StopLossCalculator()
            >>> position = calculator.calculate_position_size_with_risk(
            ...     entry_price=50000.0,
            ...     stop_loss=49000.0,
            ...     account_balance=10000.0,
            ...     risk_pct=0.01
            ... )
            >>> print(f"Position: {position:.8f} BTC")
            >>> # If SL hit: loss = position × 1000 = $100 (1% of $10,000)
        """
        # Validate inputs
        if entry_price <= 0:
            raise ValueError(f"Entry price must be positive: {entry_price}")

        if stop_loss <= 0:
            raise ValueError(f"Stop loss must be positive: {stop_loss}")

        if account_balance <= 0:
            raise ValueError(f"Account balance must be positive: {account_balance}")

        if risk_pct <= 0 or risk_pct > 0.05:
            raise ValueError(f"Risk percentage must be between 0 and 0.05: {risk_pct}")

        # Calculate stop distance in dollars
        stop_distance = abs(entry_price - stop_loss)

        if stop_distance == 0:
            self.logger.error("Stop distance is zero, cannot calculate position size")
            return 0.0

        # Calculate maximum risk amount
        max_risk_amount = account_balance * risk_pct

        # Calculate position size
        # position_size × stop_distance = max_risk_amount
        # position_size = max_risk_amount / stop_distance
        position_size = max_risk_amount / stop_distance

        # Round to 8 decimal places (BTC precision)
        position_size = round(position_size, 8)

        self.logger.info(
            f"Position size calculated: {position_size:.8f} BTC "
            f"(risk: ${max_risk_amount:.2f}, stop distance: ${stop_distance:.2f})"
        )

        # Verify the calculation
        actual_risk = position_size * stop_distance
        risk_pct_actual = (actual_risk / account_balance) * 100

        self.logger.debug(
            f"Verification: position {position_size:.8f} × distance ${stop_distance:.2f} "
            f"= ${actual_risk:.2f} ({risk_pct_actual:.2f}% of account)"
        )

        return position_size

    def __repr__(self) -> str:
        """String representation"""
        return (
            f"StopLossCalculator("
            f"max_risk={self.max_risk_pct:.3%}, "
            f"min_distance={self.min_distance_pct:.3%}, "
            f"swing_lookback={self.swing_detector.lookback})"
        )
