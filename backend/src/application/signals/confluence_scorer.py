"""
Confluence Scorer - SOTA Weighted Signal Scoring

Implements weighted confluence scoring pattern used by institutional traders.
Instead of requiring 4/5 conditions (80%), uses weighted scores where
important conditions have higher weights.

Based on: Smart Money Concepts, Institutional Trading patterns.

Author: Workspace Navigator AI
Version: 1.0
"""

from typing import Dict, Optional
from dataclasses import dataclass
from enum import Enum
import logging


class ConditionType(Enum):
    """Signal condition types."""
    TREND_ALIGNMENT = "trend_alignment"
    PULLBACK_ZONE = "pullback_zone"
    MOMENTUM_TRIGGER = "momentum_trigger"
    CANDLE_CONFIRMATION = "candle_confirmation"
    VOLUME_CONFIRMATION = "volume_confirmation"
    VOLUME_DELTA_CONFIRMATION = "volume_delta_confirmation"


@dataclass
class ConfluenceResult:
    """Result of confluence scoring."""
    score: float  # 0.0 to 1.0
    conditions_met: Dict[str, bool]
    weighted_contributions: Dict[str, float]
    is_valid: bool  # True if score >= min_threshold
    reasons: list


class ConfluenceScorer:
    """
    SOTA: Weighted confluence scoring for signal generation.

    Instead of: "4 out of 5 conditions must be true" (80% binary)
    Uses: "Weighted score must be >= 60%" (flexible, importance-aware)

    Example:
        If only Pullback Zone (30%) + Momentum Trigger (25%) are met,
        score = 55%, which might be valid with a 50% threshold.

    This allows:
    - Important conditions (pullback zone) to matter more
    - Minor confirmations (candle color) to be optional
    - Flexible thresholds based on market conditions
    """

    # Default weights based on SOTA research
    DEFAULT_WEIGHTS = {
        ConditionType.TREND_ALIGNMENT: 0.25,      # Price vs VWAP
        ConditionType.PULLBACK_ZONE: 0.30,        # Near support (most important)
        ConditionType.MOMENTUM_TRIGGER: 0.25,     # StochRSI cross
        ConditionType.CANDLE_CONFIRMATION: 0.10,  # Green/Red candle
        ConditionType.VOLUME_CONFIRMATION: 0.05,  # Volume spike (reduced)
        ConditionType.VOLUME_DELTA_CONFIRMATION: 0.05, # Delta confirmation (new)
    }

    def __init__(
        self,
        weights: Optional[Dict[ConditionType, float]] = None,
        min_score: float = 0.60
    ):
        """
        Initialize confluence scorer.

        Args:
            weights: Custom weights for each condition type
            min_score: Minimum score to consider signal valid (0-1)
        """
        self.weights = weights or self.DEFAULT_WEIGHTS
        self.min_score = min_score
        self.logger = logging.getLogger(__name__)

        # Validate weights sum to 1.0
        total = sum(self.weights.values())
        if abs(total - 1.0) > 0.01:
            self.logger.warning(
                f"Weights sum to {total:.2f}, not 1.0. Results may be unexpected."
            )

    def calculate_score(
        self,
        conditions: Dict[ConditionType, bool]
    ) -> ConfluenceResult:
        """
        Calculate weighted confluence score.

        Args:
            conditions: Dict mapping condition types to bool (met or not)

        Returns:
            ConfluenceResult with score and breakdown
        """
        score = 0.0
        contributions = {}
        reasons = []

        for condition_type, weight in self.weights.items():
            is_met = conditions.get(condition_type, False)

            if is_met:
                score += weight
                contributions[condition_type.value] = weight
                reasons.append(f"✓ {condition_type.value}: +{weight:.0%}")
            else:
                contributions[condition_type.value] = 0.0
                reasons.append(f"✗ {condition_type.value}: 0%")

        is_valid = score >= self.min_score

        if is_valid:
            self.logger.debug(
                f"Confluence PASS: {score:.1%} >= {self.min_score:.1%}"
            )
        else:
            self.logger.debug(
                f"Confluence FAIL: {score:.1%} < {self.min_score:.1%}"
            )

        return ConfluenceResult(
            score=score,
            conditions_met={ct.value: conditions.get(ct, False) for ct in ConditionType},
            weighted_contributions=contributions,
            is_valid=is_valid,
            reasons=reasons
        )

    def calculate_from_dict(
        self,
        conditions: Dict[str, bool]
    ) -> ConfluenceResult:
        """
        Calculate score from string-keyed dict (convenience method).

        Args:
            conditions: Dict with string keys matching ConditionType values

        Returns:
            ConfluenceResult
        """
        typed_conditions = {}
        for ct in ConditionType:
            typed_conditions[ct] = conditions.get(ct.value, False)

        return self.calculate_score(typed_conditions)

    def update_min_score(self, new_min: float) -> None:
        """
        Update minimum score threshold.

        Useful for dynamic adjustment based on market conditions.

        Args:
            new_min: New minimum score (0-1)
        """
        if 0.0 <= new_min <= 1.0:
            self.min_score = new_min
            self.logger.info(f"Updated min_score to {new_min:.1%}")
        else:
            self.logger.warning(f"Invalid min_score: {new_min}. Keeping {self.min_score:.1%}")


def create_confluence_scorer_from_config(strategy_config) -> ConfluenceScorer:
    """
    Factory function to create ConfluenceScorer from StrategyConfig.

    Args:
        strategy_config: StrategyConfig instance

    Returns:
        ConfluenceScorer configured from strategy settings
    """
    weights = {
        ConditionType.TREND_ALIGNMENT: strategy_config.weight_trend_alignment,
        ConditionType.PULLBACK_ZONE: strategy_config.weight_pullback_zone,
        ConditionType.MOMENTUM_TRIGGER: strategy_config.weight_momentum_trigger,
        ConditionType.CANDLE_CONFIRMATION: strategy_config.weight_candle_confirmation,
        ConditionType.VOLUME_CONFIRMATION: strategy_config.weight_volume_confirmation,
    }

    return ConfluenceScorer(
        weights=weights,
        min_score=strategy_config.min_confluence_score
    )
