"""
Strategy Registry - Configuration Layer

Centralized repository for symbol-specific strategy parameters.
SOTA Pattern: "Configuration as Code" ensures type safety and version control.
"""

from dataclasses import dataclass
from typing import Dict, Optional

@dataclass
class StrategyConfig:
    """
    Configuration for a specific trading strategy.
    """
    strategy_name: str  # 'sfp_mean_reversion' or 'trend_pullback'
    vwap_distance_threshold: float  # e.g., 0.015 for 1.5%
    sfp_confidence_threshold: float # e.g., 0.8
    stop_loss_buffer: float         # e.g., 0.015 for 1.5% fixed SL
    tp_targets: list[float]         # [1.0] means TP at VWAP, [1.005] means VWAP + 0.5%
    timeframe: str = "15m"          # Recommended timeframe

class StrategyRegistry:
    """
    Registry to retrieve strategy config by symbol.
    """

    # 1. THE WINNING FORMULA (BTC)
    BTC_CONFIG = StrategyConfig(
        strategy_name="sfp_mean_reversion",
        vwap_distance_threshold=0.015,  # 1.5% stretch (proven optimal)
        sfp_confidence_threshold=0.8,   # High confidence only
        stop_loss_buffer=0.015,         # 1.5% SL
        tp_targets=[1.0],               # Target exactly VWAP
        timeframe="15m"
    )

    # 2. DEFAULT (Conservative)
    DEFAULT_CONFIG = StrategyConfig(
        strategy_name="sfp_mean_reversion",
        vwap_distance_threshold=0.02,   # 2% stretch (safer for alts)
        sfp_confidence_threshold=0.7,
        stop_loss_buffer=0.02,          # 2% SL for volatility
        tp_targets=[1.0],
        timeframe="15m"
    )

    # Registry Map
    _REGISTRY: Dict[str, StrategyConfig] = {
        "BTCUSDT": BTC_CONFIG,
        # Future: Add ETHUSDT, SOLUSDT optimized configs here
    }

    @classmethod
    def get_config(cls, symbol: str) -> StrategyConfig:
        """Get config for symbol or default."""
        return cls._REGISTRY.get(symbol.upper(), cls.DEFAULT_CONFIG)
