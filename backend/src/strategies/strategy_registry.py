"""
Strategy Registry - Strategies Layer

Optimized for 30-day "Trio" test (BNB, SOL, TAO).
"""

from dataclasses import dataclass
from typing import Dict, List

@dataclass
class StrategyConfig:
    strategy_name: str
    vwap_distance_threshold: float
    sfp_confidence_threshold: float
    stop_loss_buffer: float
    tp_targets: List[float]
    timeframe: str = "15m"
    use_dynamic_threshold: bool = False

class StrategyRegistry:
    # 1. BNB: The Engine (Proven)
    BNB_CONFIG = StrategyConfig(
        strategy_name="sfp_mean_reversion",
        vwap_distance_threshold=0.015, # 1.5%
        sfp_confidence_threshold=0.7,
        stop_loss_buffer=0.02,          # 2.0%
        tp_targets=[1.0]
    )

    # 2. SOL: Optimized Volatility
    SOL_CONFIG = StrategyConfig(
        strategy_name="sfp_mean_reversion",
        vwap_distance_threshold=0.02,   # 2.0% (Relaxed)
        sfp_confidence_threshold=0.75,
        stop_loss_buffer=0.03,          # 3.0%
        tp_targets=[1.0],
        use_dynamic_threshold=True
    )

    # 3. TAO: The High-Reward Target
    TAO_CONFIG = StrategyConfig(
        strategy_name="sfp_mean_reversion",
        vwap_distance_threshold=0.025,  # 2.5% (Relaxed)
        sfp_confidence_threshold=0.75,
        stop_loss_buffer=0.04,          # 4.0%
        tp_targets=[1.0],
        use_dynamic_threshold=True
    )

    # Fallbacks
    BTC_CONFIG = StrategyConfig(
        strategy_name="sfp_mean_reversion",
        vwap_distance_threshold=0.01,
        sfp_confidence_threshold=0.75,
        stop_loss_buffer=0.015,
        tp_targets=[1.0]
    )

    _REGISTRY: Dict[str, StrategyConfig] = {
        "BNBUSDT": BNB_CONFIG,
        "SOLUSDT": SOL_CONFIG,
        "TAOUSDT": TAO_CONFIG,
        "BTCUSDT": BTC_CONFIG
    }

    @classmethod
    def get_config(cls, symbol: str) -> StrategyConfig:
        return cls._REGISTRY.get(symbol.upper(), cls.BNB_CONFIG)
