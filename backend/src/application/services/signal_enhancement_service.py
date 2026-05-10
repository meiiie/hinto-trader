"""
Signal Enhancement Service - Application Layer

Transforms basic signals into professional trading plans with Entry/TP/ST levels.
"""

import logging
from typing import Optional, List
from datetime import datetime, timedelta

from ...domain.entities.candle import Candle
from ...domain.entities.enhanced_signal import EnhancedSignal, TPLevels
from .entry_price_calculator import EntryPriceCalculator
from .tp_calculator import TPCalculator
from .stop_loss_calculator import StopLossCalculator
from .confidence_calculator import ConfidenceCalculator


class SignalEnhancementService:
    """
    Service for enhancing basic signals with complete trading plans.

    Transforms basic signals into professional trading plans with:
    - Precise entry price
    - Multi-target take profit levels (TP1/TP2/TP3)
    - Risk-based stop loss
    - Position sizing for 1% max risk
    - Confidence scoring

    Usage:
        service = SignalEnhancementService(account_size=10000.0)

        enhanced_signal = service.enhance_signal(
            direction='BUY',
            candles=candles,
            ema7=50100.0,
            ema25=49900.0,
            rsi6=25.0,
            volume_spike=True,
            ema_crossover='bullish',
            symbol='BTCUSDT',
            timeframe='15m'
        )
    """

    def __init__(
        self,
        account_size: float = 10000.0,
        max_risk_pct: float = 0.01,
        min_risk_reward: float = 1.5
    ):
        """
        Initialize signal enhancement service.

        Args:
            account_size: Account size for position sizing (default: 10000)
            max_risk_pct: Maximum risk per trade (default: 0.01 = 1%)
            min_risk_reward: Minimum risk-reward ratio (default: 1.5)
        """
        self.account_size = account_size
        self.max_risk_pct = max_risk_pct
        self.min_risk_reward = min_risk_reward

        # Initialize calculators
        self.entry_calculator = EntryPriceCalculator()
        self.tp_calculator = TPCalculator(min_risk_reward=min_risk_reward)
        self.sl_calculator = StopLossCalculator(max_risk_pct=max_risk_pct)
        self.confidence_calculator = ConfidenceCalculator()

        self.logger = logging.getLogger(__name__)
        self.logger.info(
            f"SignalEnhancementService initialized: "
            f"account=${account_size:,.2f}, max_risk={max_risk_pct:.1%}"
        )

    def enhance_signal(
        self,
        direction: str,
        candles: List[Candle],
        ema7: float,
        ema25: float,
        rsi6: float,
        volume_spike: bool,
        ema_crossover: Optional[str],
        symbol: str,
        timeframe: str,
        timestamp: Optional[datetime] = None
    ) -> Optional[EnhancedSignal]:
        """
        Enhance basic signal with complete trading plan.

        Args:
            direction: 'BUY' or 'SELL'
            candles: List of Candle entities
            ema7: EMA(7) value
            ema25: EMA(25) value
            rsi6: RSI(6) value
            volume_spike: Whether volume spike detected
            ema_crossover: Crossover type ('bullish', 'bearish', None)
            symbol: Trading pair (e.g., 'BTCUSDT')
            timeframe: Timeframe (e.g., '15m', '1h')
            timestamp: Signal timestamp (default: now)

        Returns:
            EnhancedSignal or None if enhancement fails

        Example:
            >>> service = SignalEnhancementService()
            >>> signal = service.enhance_signal(
            ...     direction='BUY',
            ...     candles=candles,
            ...     ema7=50100.0,
            ...     ema25=49900.0,
            ...     rsi6=25.0,
            ...     volume_spike=True,
            ...     ema_crossover='bullish',
            ...     symbol='BTCUSDT',
            ...     timeframe='15m'
            ... )
        """
        if timestamp is None:
            timestamp = datetime.now()

        self.logger.info(
            f"Enhancing {direction} signal for {symbol} {timeframe}"
        )

        try:
            # Step 1: Calculate Entry Price
            entry_result = self.entry_calculator.calculate_entry_price(
                direction=direction,
                candles=candles,
                ema7=ema7
            )

            if not entry_result or not entry_result.is_valid:
                self.logger.warning("No valid entry price found")
                return None

            entry_price = entry_result.entry_price
            self.logger.info(f"Entry price: ${entry_price:,.2f}")

            # Step 2: Calculate Stop Loss
            sl_result = self.sl_calculator.calculate_stop_loss(
                entry_price=entry_price,
                direction=direction,
                candles=candles,
                ema25=ema25,
                account_size=self.account_size
            )

            if not sl_result or not sl_result.is_valid:
                self.logger.warning("No valid stop loss found")
                return None

            stop_loss = sl_result.stop_loss
            self.logger.info(f"Stop loss: ${stop_loss:,.2f}")

            # Step 3: Calculate Position Size
            position_size = self.sl_calculator.calculate_position_size(
                entry_price=entry_price,
                stop_loss=stop_loss,
                account_size=self.account_size,
                risk_pct=self.max_risk_pct
            )

            self.logger.info(f"Position size: {position_size:.6f}")

            # Step 4: Calculate Take Profit Levels
            tp_result = self.tp_calculator.calculate_tp_levels(
                entry_price=entry_price,
                stop_loss=stop_loss,
                direction=direction,
                candles=candles
            )

            if not tp_result or not tp_result.is_valid:
                self.logger.warning("No valid TP levels found")
                return None

            tp_levels = tp_result.tp_levels
            risk_reward_ratio = tp_result.risk_reward_ratio

            self.logger.info(
                f"TP levels: TP1=${tp_levels.tp1:,.2f}, "
                f"TP2=${tp_levels.tp2:,.2f}, TP3=${tp_levels.tp3:,.2f}"
            )

            # Step 5: Calculate Confidence Score
            current_price = candles[-1].close
            confidence_result = self.confidence_calculator.calculate_confidence(
                direction=direction,
                ema_crossover=ema_crossover,
                volume_spike=volume_spike,
                rsi_value=rsi6,
                ema7=ema7,
                ema25=ema25,
                price=current_price
            )

            confidence_score = confidence_result.confidence_score
            indicator_alignment = confidence_result.indicator_alignment

            self.logger.info(f"Confidence score: {confidence_score:.0f}%")

            # Step 6: Create Enhanced Signal
            enhanced_signal = EnhancedSignal(
                timestamp=timestamp,
                symbol=symbol,
                timeframe=timeframe,
                direction=direction,
                entry_price=entry_price,
                take_profit=tp_levels,
                stop_loss=stop_loss,
                position_size=position_size,
                risk_reward_ratio=risk_reward_ratio,
                confidence_score=confidence_score,
                max_risk_pct=self.max_risk_pct,
                indicator_alignment=indicator_alignment,
                max_hold_time=timedelta(hours=4),
                ema7=ema7,
                ema25=ema25,
                rsi6=rsi6,
                volume_spike=volume_spike
            )

            self.logger.info(
                f"✅ Enhanced signal created: {direction} {symbol} @ ${entry_price:,.2f}, "
                f"Confidence: {confidence_score:.0f}%"
            )

            return enhanced_signal

        except Exception as e:
            self.logger.error(f"Signal enhancement failed: {e}", exc_info=True)
            return None

    def update_account_size(self, new_account_size: float):
        """
        Update account size for position sizing.

        Args:
            new_account_size: New account size
        """
        self.account_size = new_account_size
        self.logger.info(f"Account size updated to ${new_account_size:,.2f}")

    def __repr__(self) -> str:
        """String representation"""
        return (
            f"SignalEnhancementService("
            f"account=${self.account_size:,.2f}, "
            f"max_risk={self.max_risk_pct:.1%}, "
            f"min_RR={self.min_risk_reward})"
        )
