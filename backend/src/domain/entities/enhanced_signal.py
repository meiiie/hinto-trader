"""
Enhanced Signal Entities - Domain Layer

Professional trading signal with complete trading plan (Entry/TP/ST).
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any


@dataclass
class TPLevels:
    """
    Take Profit levels with position sizing.

    Multi-target TP system for progressive profit taking:
    - TP1: Nearest target (60% position)
    - TP2: Major target (30% position)
    - TP3: Extended target (10% position)

    Attributes:
        tp1: First take profit level (60% position)
        tp2: Second take profit level (30% position)
        tp3: Third take profit level (10% position)
        sizes: Position sizes for each TP [0.6, 0.3, 0.1]

    Example:
        >>> tp_levels = TPLevels(
        ...     tp1=50500.0,
        ...     tp2=51000.0,
        ...     tp3=51500.0,
        ...     sizes=[0.6, 0.3, 0.1]
        ... )
        >>> print(f"TP1: ${tp_levels.tp1:.2f} ({tp_levels.sizes[0]:.0%})")
        TP1: $50500.00 (60%)
    """
    tp1: float
    tp2: float
    tp3: float
    sizes: List[float] = field(default_factory=lambda: [0.6, 0.3, 0.1])

    def __post_init__(self):
        """Validate TP levels after initialization"""
        # Validate TP levels are in ascending order (for BUY) or descending (for SELL)
        # This will be validated by the service that creates TPLevels

        # Validate sizes sum to 1.0
        if abs(sum(self.sizes) - 1.0) > 0.01:
            raise ValueError(
                f"Position sizes must sum to 1.0, got {sum(self.sizes):.2f}"
            )

        # Validate all sizes are positive
        if any(size <= 0 for size in self.sizes):
            raise ValueError("All position sizes must be positive")

        # Validate TP levels are positive
        if self.tp1 <= 0 or self.tp2 <= 0 or self.tp3 <= 0:
            raise ValueError("All TP levels must be positive")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'tp1': self.tp1,
            'tp2': self.tp2,
            'tp3': self.tp3,
            'sizes': self.sizes
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TPLevels':
        """Create from dictionary"""
        return cls(
            tp1=data['tp1'],
            tp2=data['tp2'],
            tp3=data['tp3'],
            sizes=data.get('sizes', [0.6, 0.3, 0.1])
        )

    def __str__(self) -> str:
        """String representation"""
        return (
            f"TP1: ${self.tp1:.2f} ({self.sizes[0]:.0%}), "
            f"TP2: ${self.tp2:.2f} ({self.sizes[1]:.0%}), "
            f"TP3: ${self.tp3:.2f} ({self.sizes[2]:.0%})"
        )


@dataclass
class EnhancedSignal:
    """
    Professional trading signal with complete trading plan.

    Transforms basic signals into actionable trading plans with:
    - Precise entry price
    - Multi-target take profit levels
    - Risk-based stop loss
    - Position sizing for 1% max risk
    - Confidence scoring

    Attributes:
        # Basic signal info
        timestamp: When signal was generated
        symbol: Trading pair (e.g., 'BTCUSDT')
        timeframe: Timeframe (e.g., '15m', '1h')
        direction: 'BUY' or 'SELL'

        # Professional trading plan
        entry_price: Optimal entry price
        take_profit: Multi-target TP levels
        stop_loss: Risk-based stop loss
        position_size: Position size for 1% risk

        # Risk management
        risk_reward_ratio: Risk/reward ratio (target: > 1.5)
        max_risk_pct: Maximum risk per trade (always 1%)

        # Confidence and metadata
        confidence_score: Signal confidence (0-100)
        indicator_alignment: Dict of indicator confirmations
        max_hold_time: Maximum time to hold position

        # Indicator values at signal time
        ema7: EMA(7) value
        ema25: EMA(25) value
        rsi6: RSI(6) value
        volume_spike: Whether volume spike detected

    Example:
        >>> signal = EnhancedSignal(
        ...     timestamp=datetime.now(),
        ...     symbol='BTCUSDT',
        ...     timeframe='15m',
        ...     direction='BUY',
        ...     entry_price=50000.0,
        ...     take_profit=TPLevels(50500, 51000, 51500),
        ...     stop_loss=49500.0,
        ...     position_size=0.1,
        ...     risk_reward_ratio=2.0,
        ...     max_risk_pct=0.01,
        ...     confidence_score=85.0,
        ...     indicator_alignment={'rsi': True, 'volume': True, 'ema': True},
        ...     max_hold_time=timedelta(hours=4),
        ...     ema7=49800.0,
        ...     ema25=49500.0,
        ...     rsi6=25.0,
        ...     volume_spike=True
        ... )
    """
    # Basic signal info
    timestamp: datetime
    symbol: str
    timeframe: str
    direction: str  # 'BUY' or 'SELL'

    # Professional trading plan
    entry_price: float
    take_profit: TPLevels
    stop_loss: float
    position_size: float

    # Risk management
    risk_reward_ratio: float
    confidence_score: float  # 0-100

    # Optional fields with defaults
    max_risk_pct: float = 0.01  # Always 1%
    indicator_alignment: Dict[str, bool] = field(default_factory=dict)
    max_hold_time: timedelta = field(default_factory=lambda: timedelta(hours=4))

    # Indicator values at signal time
    ema7: float = 0.0
    ema25: float = 0.0
    rsi6: float = 0.0
    volume_spike: bool = False

    def __post_init__(self):
        """Validate signal after initialization"""
        # Validate direction
        if self.direction not in ['BUY', 'SELL']:
            raise ValueError(f"Direction must be 'BUY' or 'SELL', got '{self.direction}'")

        # Validate prices are positive
        if self.entry_price <= 0:
            raise ValueError("Entry price must be positive")
        if self.stop_loss <= 0:
            raise ValueError("Stop loss must be positive")

        # Validate position size
        if self.position_size <= 0:
            raise ValueError("Position size must be positive")

        # Validate confidence score
        if not 0 <= self.confidence_score <= 100:
            raise ValueError(f"Confidence score must be 0-100, got {self.confidence_score}")

        # Validate risk/reward ratio
        if self.risk_reward_ratio < 0:
            raise ValueError("Risk/reward ratio must be non-negative")

        # Validate stop loss placement
        if self.direction == 'BUY':
            if self.stop_loss >= self.entry_price:
                raise ValueError(
                    f"For BUY, stop loss ({self.stop_loss}) must be below entry ({self.entry_price})"
                )
            if self.take_profit.tp1 <= self.entry_price:
                raise ValueError(
                    f"For BUY, TP1 ({self.take_profit.tp1}) must be above entry ({self.entry_price})"
                )
        else:  # SELL
            if self.stop_loss <= self.entry_price:
                raise ValueError(
                    f"For SELL, stop loss ({self.stop_loss}) must be above entry ({self.entry_price})"
                )
            if self.take_profit.tp1 >= self.entry_price:
                raise ValueError(
                    f"For SELL, TP1 ({self.take_profit.tp1}) must be below entry ({self.entry_price})"
                )

    def calculate_risk_amount(self, account_size: float) -> float:
        """
        Calculate risk amount in account currency.

        Args:
            account_size: Total account size

        Returns:
            Risk amount (account_size * max_risk_pct)
        """
        return account_size * self.max_risk_pct

    def calculate_potential_profit(self) -> Dict[str, float]:
        """
        Calculate potential profit for each TP level.

        Returns:
            Dict with profit for each TP level
        """
        if self.direction == 'BUY':
            return {
                'tp1': (self.take_profit.tp1 - self.entry_price) * self.position_size * self.take_profit.sizes[0],
                'tp2': (self.take_profit.tp2 - self.entry_price) * self.position_size * self.take_profit.sizes[1],
                'tp3': (self.take_profit.tp3 - self.entry_price) * self.position_size * self.take_profit.sizes[2]
            }
        else:  # SELL
            return {
                'tp1': (self.entry_price - self.take_profit.tp1) * self.position_size * self.take_profit.sizes[0],
                'tp2': (self.entry_price - self.take_profit.tp2) * self.position_size * self.take_profit.sizes[1],
                'tp3': (self.entry_price - self.take_profit.tp3) * self.position_size * self.take_profit.sizes[2]
            }

    def calculate_potential_loss(self) -> float:
        """
        Calculate potential loss if stop loss is hit.

        Returns:
            Potential loss amount
        """
        if self.direction == 'BUY':
            return (self.entry_price - self.stop_loss) * self.position_size
        else:  # SELL
            return (self.stop_loss - self.entry_price) * self.position_size

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            'timestamp': self.timestamp.isoformat(),
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'direction': self.direction,
            'entry_price': self.entry_price,
            'take_profit': self.take_profit.to_dict(),
            'stop_loss': self.stop_loss,
            'position_size': self.position_size,
            'risk_reward_ratio': self.risk_reward_ratio,
            'max_risk_pct': self.max_risk_pct,
            'confidence_score': self.confidence_score,
            'indicator_alignment': self.indicator_alignment,
            'max_hold_time': self.max_hold_time.total_seconds(),
            'ema7': self.ema7,
            'ema25': self.ema25,
            'rsi6': self.rsi6,
            'volume_spike': self.volume_spike
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'EnhancedSignal':
        """Create from dictionary"""
        return cls(
            timestamp=datetime.fromisoformat(data['timestamp']),
            symbol=data['symbol'],
            timeframe=data['timeframe'],
            direction=data['direction'],
            entry_price=data['entry_price'],
            take_profit=TPLevels.from_dict(data['take_profit']),
            stop_loss=data['stop_loss'],
            position_size=data['position_size'],
            risk_reward_ratio=data['risk_reward_ratio'],
            max_risk_pct=data.get('max_risk_pct', 0.01),
            confidence_score=data['confidence_score'],
            indicator_alignment=data.get('indicator_alignment', {}),
            max_hold_time=timedelta(seconds=data.get('max_hold_time', 14400)),
            ema7=data.get('ema7', 0.0),
            ema25=data.get('ema25', 0.0),
            rsi6=data.get('rsi6', 0.0),
            volume_spike=data.get('volume_spike', False)
        )

    def __str__(self) -> str:
        """String representation"""
        emoji = "🟢" if self.direction == 'BUY' else "🔴"
        return (
            f"{emoji} {self.direction} {self.symbol} @ ${self.entry_price:.2f}\n"
            f"   TP: {self.take_profit}\n"
            f"   SL: ${self.stop_loss:.2f}\n"
            f"   Size: {self.position_size:.4f}\n"
            f"   R:R: {self.risk_reward_ratio:.2f}\n"
            f"   Confidence: {self.confidence_score:.0f}%"
        )
