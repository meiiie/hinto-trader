"""Research-only adaptive regime router.

The router maps a small, pre-declared feature set into backtest presets. It is
intentionally deterministic so research runs can be repeated from metadata
instead of reconstructed from screenshots or memory.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, FrozenSet, Tuple


BEARISH_TOXIC_SHORT_BLACKLIST: Tuple[str, ...] = (
    "DOGEUSDT",
    "DOTUSDT",
    "AAVEUSDT",
)


@dataclass(frozen=True)
class AdaptiveRouterFeatures:
    """Inputs used by the research router at a session boundary."""

    eligible_count: int
    btc_trend_ema20: str
    btc_spread_pct: float
    regime_15m: str
    regime_confidence: float


@dataclass(frozen=True)
class AdaptiveRouterDecision:
    """Router output consumed by the backtest CLI."""

    preset: str
    reason: str


@dataclass(frozen=True)
class RollingRouterState:
    """Daily/rolling router state attached to the backtest engine."""

    session_start_utc: datetime
    session_date_utc7: str
    preset: str
    reason: str
    features: AdaptiveRouterFeatures
    allowed_symbols: FrozenSet[str]
    blocked_symbol_sides: Tuple[Tuple[str, str], ...] = ()


class AdaptiveRegimeRouter:
    """Deterministic regime router for research backtests."""

    def __init__(
        self,
        *,
        neutral_breadth_threshold: int = 8,
        neutral_spread_floor_pct: float = 0.0,
        bearish_trend_spread_pct: float = -3.0,
        bearish_top50_breadth_threshold: int = 15,
        moderate_bear_spread_pct: float = -1.5,
        moderate_bear_breadth_threshold: int = 16,
        strong_spread_breadth_threshold: int = 13,
        strong_spread_pct: float = -4.0,
    ) -> None:
        self.neutral_breadth_threshold = neutral_breadth_threshold
        self.neutral_spread_floor_pct = neutral_spread_floor_pct
        self.bearish_trend_spread_pct = bearish_trend_spread_pct
        self.bearish_top50_breadth_threshold = bearish_top50_breadth_threshold
        self.moderate_bear_spread_pct = moderate_bear_spread_pct
        self.moderate_bear_breadth_threshold = moderate_bear_breadth_threshold
        self.strong_spread_breadth_threshold = strong_spread_breadth_threshold
        self.strong_spread_pct = strong_spread_pct

    def decide(self, features: AdaptiveRouterFeatures) -> AdaptiveRouterDecision:
        trend = (features.btc_trend_ema20 or "NEUTRAL").upper()
        regime = (features.regime_15m or "ranging").lower()
        eligible = int(features.eligible_count)
        spread = float(features.btc_spread_pct)

        if eligible < self.neutral_breadth_threshold:
            return AdaptiveRouterDecision(
                preset="shield",
                reason=(
                    f"eligible breadth {eligible} below minimum "
                    f"{self.neutral_breadth_threshold}"
                ),
            )

        if (
            trend == "BEARISH"
            and spread <= self.strong_spread_pct
            and eligible <= self.strong_spread_breadth_threshold
        ):
            return AdaptiveRouterDecision(
                preset="shield",
                reason=(
                    "strong bearish BTC spread with weak eligible breadth "
                    f"(spread={spread:.2f}%, eligible={eligible})"
                ),
            )

        if trend == "BEARISH" and (
            spread <= self.bearish_trend_spread_pct
            or eligible <= self.bearish_top50_breadth_threshold
        ):
            return AdaptiveRouterDecision(
                preset="short_only_bounce_daily_pt15_maker_top50_toxicblk",
                reason=(
                    "guarded bearish branch: block longs and exclude known "
                    f"toxic shorts (spread={spread:.2f}%, eligible={eligible})"
                ),
            )

        if trend == "BEARISH" or (
            spread <= self.moderate_bear_spread_pct
            and eligible <= self.moderate_bear_breadth_threshold
        ):
            return AdaptiveRouterDecision(
                preset="short_only_bounce_daily_pt15_maker",
                reason=(
                    "moderate bearish branch: short-only mean reversion with "
                    f"daily loss guard (spread={spread:.2f}%, eligible={eligible})"
                ),
            )

        if regime == "ranging" and features.regime_confidence >= 0.60:
            return AdaptiveRouterDecision(
                preset="bounce_daily_pt15_maker",
                reason="range regime: allow mean-reversion bounce with maker exits",
            )

        if trend == "BULLISH" and spread >= self.neutral_spread_floor_pct:
            return AdaptiveRouterDecision(
                preset="bounce_daily_pt15_maker",
                reason=(
                    "bullish/healthy regime: allow guarded mean reversion "
                    f"(spread={spread:.2f}%)"
                ),
            )

        return AdaptiveRouterDecision(
            preset="baseline_cb",
            reason=(
                "uncertain but tradable regime: keep baseline with circuit "
                f"breakers (trend={trend}, spread={spread:.2f}%, regime={regime})"
            ),
        )


def get_router_recommended_symbol_side_blocks(
    preset: str,
) -> Tuple[Tuple[str, str], ...]:
    """Return preset side blocks for the simulator."""

    if not preset.startswith("short_only_"):
        return ()

    blocks = [("*", "LONG")]
    if preset.endswith("_toxicblk"):
        blocks.extend((symbol, "SHORT") for symbol in BEARISH_TOXIC_SHORT_BLACKLIST)
    return tuple(blocks)


def get_router_research_exit_profile(
    preset: str,
    *,
    guarded_bear_override: str | None = None,
) -> dict[str, Any] | None:
    """Exit-profile override attached by the rolling router.

    These profiles are research metadata for the simulator. They must not be
    treated as a live trading contract until explicitly promoted.
    """

    if preset in {"baseline", "baseline_cb", "shield"}:
        return None

    profile = {
        "profile_name": f"router_{preset}",
        "close_profitable_auto": True,
        "profitable_threshold_pct": 15.0,
        "trailing_stop_atr": 4.0,
        "partial_close_ac": False,
    }

    if guarded_bear_override == "pt20":
        profile["profitable_threshold_pct"] = 20.0
        profile["profile_name"] = f"{profile['profile_name']}_pt20"
    elif guarded_bear_override == "no_ac_trail3":
        profile["close_profitable_auto"] = False
        profile["trailing_stop_atr"] = 3.0
        profile["profile_name"] = f"{profile['profile_name']}_no_ac_trail3"

    return profile
