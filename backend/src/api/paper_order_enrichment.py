"""Helpers for exposing paper pending-order signal quality in API responses."""

from __future__ import annotations

import time
from typing import Dict, Iterable, List, Optional, Tuple

from src.application.services.signal_lifecycle_service import SignalLifecycleService
from src.domain.entities.paper_position import PaperPosition
from src.domain.entities.trading_signal import TradingSignal


_PUBLIC_PRICE_CACHE: Dict[str, Tuple[float, float]] = {}
_PUBLIC_PRICE_CACHE_TTL_SECONDS = 3.0


def calculate_risk_reward_ratio(
    side: str,
    entry_price: Optional[float],
    stop_loss: Optional[float],
    take_profit: Optional[float],
) -> Optional[float]:
    """Calculate R:R from pending-order prices."""
    if not entry_price or entry_price <= 0 or not stop_loss or not take_profit:
        return None

    risk = abs(entry_price - stop_loss)
    reward = abs(take_profit - entry_price)
    if risk <= 0 or reward <= 0:
        return None

    # Side is kept in the signature because callers pass both LONG/SHORT and
    # BUY/SELL. Absolute risk/reward is correct for both directions here.
    _ = side
    return reward / risk


def calculate_distance_pct(
    entry_price: Optional[float],
    current_price: Optional[float],
) -> Optional[float]:
    if not entry_price or entry_price <= 0 or not current_price or current_price <= 0:
        return None
    return abs(current_price - entry_price) / entry_price * 100


def resolve_paper_order_current_price(order: PaperPosition, market_data_repo=None) -> float:
    """Resolve current price from hot cache, latest candles, then Binance public REST."""
    if market_data_repo:
        try:
            current_price = market_data_repo.get_realtime_price(order.symbol) or 0.0
            if current_price > 0:
                return current_price

            latest = market_data_repo.get_latest_candles(order.symbol, "1m", limit=1)
            if not latest:
                latest = market_data_repo.get_latest_candles(order.symbol, "15m", limit=1)
            if latest:
                return latest[0].close
        except Exception:
            pass

    try:
        import requests

        symbol = order.symbol.upper()
        cached = _PUBLIC_PRICE_CACHE.get(symbol)
        now = time.monotonic()
        if cached and now - cached[1] <= _PUBLIC_PRICE_CACHE_TTL_SECONDS:
            return cached[0]

        response = requests.get(
            "https://fapi.binance.com/fapi/v1/ticker/price",
            params={"symbol": symbol},
            timeout=3,
        )
        response.raise_for_status()
        price = float(response.json().get("price", 0.0))
        if price > 0:
            _PUBLIC_PRICE_CACHE[symbol] = (price, now)
        return price
    except Exception:
        return 0.0


def confidence_level(confidence: Optional[float]) -> Optional[str]:
    if confidence is None:
        return None
    if confidence >= 0.80:
        return "high"
    if confidence >= 0.65:
        return "medium"
    return "low"


def build_signal_cache(
    orders: Iterable[PaperPosition],
    lifecycle_service: Optional[SignalLifecycleService],
    days: int = 2,
    limit_per_symbol: int = 100,
) -> Dict[str, List[TradingSignal]]:
    """Load recent signals for the symbols represented by pending orders."""
    if not lifecycle_service:
        return {}

    symbols = sorted({(order.symbol or "").upper() for order in orders if order.symbol})
    cache: Dict[str, List[TradingSignal]] = {}

    for symbol in symbols:
        try:
            cache[symbol] = lifecycle_service.get_filtered_signal_history(
                days=days,
                limit=limit_per_symbol,
                offset=0,
                symbol=symbol,
            )
        except Exception:
            cache[symbol] = []

    return cache


def enrich_paper_order(
    order: PaperPosition,
    signal_cache: Optional[Dict[str, List[TradingSignal]]] = None,
) -> dict:
    """
    Return signal quality fields for a paper order.

    New orders persist these fields directly. Older pending rows are recovered by
    matching their symbol, side, entry, SL, and TP against recent signal history.
    """
    matched_signal = _find_matching_signal(order, signal_cache or {})

    confidence = getattr(order, "confidence", None)
    if confidence is None and matched_signal:
        confidence = matched_signal.confidence

    risk_reward_ratio = getattr(order, "risk_reward_ratio", None)
    if risk_reward_ratio is None and matched_signal:
        risk_reward_ratio = matched_signal.risk_reward_ratio
    if risk_reward_ratio is None:
        risk_reward_ratio = calculate_risk_reward_ratio(
            order.side,
            order.entry_price,
            order.stop_loss,
            order.take_profit,
        )

    source_signal_id = getattr(order, "signal_id", None)
    if not source_signal_id and matched_signal:
        source_signal_id = matched_signal.id

    level = getattr(order, "confidence_level", None)
    if not level and matched_signal:
        level = matched_signal.confidence_level.value
    if not level:
        level = confidence_level(confidence)

    return {
        "signal_id": source_signal_id or order.id[:8],
        "confidence": confidence,
        "confidence_level": level,
        "risk_reward_ratio": risk_reward_ratio,
    }


def _find_matching_signal(
    order: PaperPosition,
    signal_cache: Dict[str, List[TradingSignal]],
) -> Optional[TradingSignal]:
    symbol = (order.symbol or "").upper()
    order_side = _side_to_signal_type(order.side)
    if not symbol or not order_side:
        return None

    candidates = signal_cache.get(symbol, [])
    best: Optional[TradingSignal] = None
    best_score = -1

    for signal in candidates:
        if signal.signal_type.value != order_side:
            continue

        score = 0
        if _price_close(order.entry_price, signal.entry_price or signal.price):
            score += 4
        if _price_close(order.stop_loss, signal.stop_loss):
            score += 2

        signal_tp1 = None
        if signal.tp_levels:
            signal_tp1 = signal.tp_levels.get("tp1")
        if _price_close(order.take_profit, signal_tp1):
            score += 2

        # Require at least the entry price to line up. That prevents an older
        # same-symbol signal from being attached to a different pending order.
        if score >= 4 and score > best_score:
            best = signal
            best_score = score

    return best


def _side_to_signal_type(side: str) -> Optional[str]:
    normalized = (side or "").upper()
    if normalized in {"LONG", "BUY"}:
        return "buy"
    if normalized in {"SHORT", "SELL"}:
        return "sell"
    return None


def _price_close(left: Optional[float], right: Optional[float]) -> bool:
    if left is None or right is None:
        return False
    left = float(left)
    right = float(right)
    tolerance = max(1e-8, abs(right) * 0.0001)
    return abs(left - right) <= tolerance
