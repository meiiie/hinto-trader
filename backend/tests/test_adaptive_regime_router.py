from datetime import datetime, timezone

from src.application.analysis.adaptive_regime_router import (
    BEARISH_TOXIC_SHORT_BLACKLIST,
    AdaptiveRegimeRouter,
    AdaptiveRouterFeatures,
    RollingRouterState,
    get_router_recommended_symbol_side_blocks,
    get_router_research_exit_profile,
)


def _features(**overrides):
    base = {
        "eligible_count": 24,
        "btc_trend_ema20": "BULLISH",
        "btc_spread_pct": 1.2,
        "regime_15m": "ranging",
        "regime_confidence": 0.7,
    }
    base.update(overrides)
    return AdaptiveRouterFeatures(**base)


def test_router_shields_when_eligible_breadth_is_too_low():
    router = AdaptiveRegimeRouter(neutral_breadth_threshold=8)

    decision = router.decide(_features(eligible_count=5))

    assert decision.preset == "shield"
    assert "eligible breadth" in decision.reason


def test_router_uses_guarded_bear_branch_for_deep_bear_regime():
    router = AdaptiveRegimeRouter()

    decision = router.decide(
        _features(
            eligible_count=18,
            btc_trend_ema20="BEARISH",
            btc_spread_pct=-3.5,
            regime_15m="trending_high_vol",
        )
    )

    assert decision.preset == "short_only_bounce_daily_pt15_maker_top50_toxicblk"


def test_router_uses_bounce_preset_for_confident_range_regime():
    router = AdaptiveRegimeRouter()

    decision = router.decide(_features(regime_15m="ranging", regime_confidence=0.8))

    assert decision.preset == "bounce_daily_pt15_maker"


def test_short_only_preset_blocks_longs_and_toxic_shorts():
    blocks = get_router_recommended_symbol_side_blocks(
        "short_only_bounce_daily_pt15_maker_top50_toxicblk"
    )

    assert ("*", "LONG") in blocks
    assert (BEARISH_TOXIC_SHORT_BLACKLIST[0], "SHORT") in blocks


def test_router_exit_profile_override_is_research_only_metadata():
    profile = get_router_research_exit_profile(
        "short_only_bounce_daily_pt15_maker_top50_toxicblk",
        guarded_bear_override="no_ac_trail3",
    )

    assert profile["close_profitable_auto"] is False
    assert profile["trailing_stop_atr"] == 3.0
    assert profile["profile_name"].endswith("no_ac_trail3")


def test_rolling_router_state_is_sortable_by_session_start():
    state = RollingRouterState(
        session_start_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        session_date_utc7="2026-01-01T07:00:00+07:00",
        preset="bounce_daily_pt15_maker",
        reason="test",
        features=_features(),
        allowed_symbols=frozenset({"BTCUSDT"}),
    )

    assert state.allowed_symbols == frozenset({"BTCUSDT"})
