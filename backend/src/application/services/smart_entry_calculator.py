"""
Smart Entry Calculator

Calculates optimal limit entry prices instead of market orders.
Waits for pullback within signal candle for better R:R ratio.
"""

from typing import Optional
from dataclasses import dataclass

from ...domain.entities.candle import Candle
from ...domain.entities.trading_signal import SignalType


@dataclass
class SmartEntryResult:
    """Smart entry calculation result"""
    entry_price: float
    pullback_ratio: float  # How much pullback was expected
    signal_candle_body: float
    signal_candle_range: float
    is_strong_candle: bool  # Large body relative to range


class SmartEntryCalculator:
    """
    Calculate smart limit entry prices.

    Strategy:
        - Don't chase market orders at signal close
        - Wait for price to pullback 30-50% of signal candle body
        - Enter when dip buyers/sellers step in (better entry)

    Result:
        - Lower entry for BUY = tighter stop loss
        - Higher entry for SELL = tighter stop loss
        - Better R:R from the start
    """

    def __init__(
        self,
        default_pullback_ratio: float = 0.3,
        strong_candle_pullback_ratio: float = 0.5,
        strong_candle_threshold: float = 0.8
    ):
        """
        Initialize Smart Entry Calculator.

        Args:
            default_pullback_ratio: Default pullback % (0.3 = 30%)
            strong_candle_pullback_ratio: Pullback for strong candles (0.5 = 50%)
            strong_candle_threshold: Body/Range ratio for "strong" candle (0.8 = 80%)
        """
        self.default_pullback_ratio = default_pullback_ratio
        self.strong_candle_pullback_ratio = strong_candle_pullback_ratio
        self.strong_candle_threshold = strong_candle_threshold

    def calculate_entry_price(
        self,
        signal_candle: Candle,
        signal_type:  SignalType,
        custom_pullback_ratio: Optional[float] = None
    ) -> SmartEntryResult:
        """
        Calculate smart limit entry price.

        Args:
            signal_candle: The candle that generated the signal
            signal_type: BUY or SELL
            custom_pullback_ratio: Override default pullback ratio

        Returns:
            SmartEntryResult with calculated entry price
        """
        # Calculate candle metrics
        body_size = abs(signal_candle.close - signal_candle.open)
        total_range = signal_candle.high - signal_candle.low

        # Avoid division by zero
        if total_range == 0:
            total_range = body_size if body_size > 0 else 1.0

        # Determine if this is a strong candle (large body)
        is_strong = (body_size / total_range) >= self.strong_candle_threshold

        # Select pullback ratio
        if custom_pullback_ratio is not None:
            pullback_ratio = custom_pullback_ratio
        elif is_strong:
            # Strong candles need deeper pullback (50%)
            pullback_ratio = self.strong_candle_pullback_ratio
        else:
            # Normal candles use default (30%)
            pullback_ratio = self.default_pullback_ratio

        # Calculate entry price
        if signal_type == SignalType.BUY:
            # For BUY: Enter below close (wait for dip)
            # Entry = Close - (Body × Pullback%)
            entry_price = signal_candle.close - (body_size * pullback_ratio)

            # Safety: Don't go below candle low
            entry_price = max(entry_price, signal_candle.low)

        elif signal_type == SignalType.SELL:
            # For SELL: Enter above close (wait for bounce)
            # Entry = Close + (Body × Pullback%)
            entry_price = signal_candle.close + (body_size * pullback_ratio)

            # Safety: Don't go above candle high
            entry_price = min(entry_price, signal_candle.high)

        else:  # NEUTRAL - use close price
            entry_price = signal_candle.close

        return SmartEntryResult(
            entry_price=entry_price,
            pullback_ratio=pullback_ratio,
            signal_candle_body=body_size,
            signal_candle_range=total_range,
            is_strong_candle=is_strong
        )

    def calculate_entry_with_vwap(
        self,
        signal_candle: Candle,
        signal_type: SignalType,
        vwap: float
    ) -> float:
        """
        Alternative: Use VWAP as entry target during pullback.

        Args:
            signal_candle: Signal candle
            signal_type: BUY or SELL
            vwap: Current VWAP value

        Returns:
            Entry price (VWAP or better)
        """
        if signal_type == SignalType.BUY:
            # For BUY: Enter at VWAP if below signal close
            if vwap < signal_candle.close:
                return vwap
            else:
                # VWAP too high, use pullback method
                result = self.calculate_entry_price(signal_candle, signal_type)
                return result.entry_price

        elif signal_type == SignalType.SELL:
            # For SELL: Enter at VWAP if above signal close
            if vwap > signal_candle.close:
                return vwap
            else:
                # VWAP too low, use pullback method
                result = self.calculate_entry_price(signal_candle, signal_type)
                return result.entry_price

        return signal_candle.close
