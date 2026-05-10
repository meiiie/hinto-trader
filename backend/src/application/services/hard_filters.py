"""
HardFilters - Application Layer

Hard filters for signal validation using Game Theory approach.

Philosophy: Don't play when the odds are against you.
- ADX Filter: Skip choppy/sideways markets (ADX < 25)
- Spread Filter: Skip when spread is too wide (> 0.1%)

These filters are "hard" because they completely block trading,
unlike "soft" filters that just reduce confidence.

Expert Feedback 3 Update:
- Now accepts Config for configurable thresholds
- Uses config.book_ticker.max_age_seconds instead of hardcoded value
"""

import logging
from typing import Optional, TYPE_CHECKING

from ...domain.entities.state_models import FilterResult

if TYPE_CHECKING:
    from ...domain.interfaces import IBookTickerClient
    from ...config import Config


class HardFilters:
    """
    Hard filters for signal validation.

    Game Theory approach: Don't play when odds are against you.

    Usage:
        filters = HardFilters(adx_threshold=25, spread_threshold=0.001)

        # Check ADX before signal generation
        adx_result = filters.check_adx_filter(adx_value=20.5)
        if not adx_result.passed:
            print(f"Skipping: {adx_result.reason}")

        # Check spread before order placement
        spread_result = filters.check_spread_filter(bid=95000, ask=95150)
        if not spread_result.passed:
            print(f"Skipping: {spread_result.reason}")
    """

    # Default thresholds
    # ⚠️ TEMPORARY CHANGE (2025-12-22): ADX lowered from 25.0 to 20.0 for system testing
    # TODO: Revert to 25.0 after confirming system works correctly
    # Original value: DEFAULT_ADX_THRESHOLD = 25.0
    DEFAULT_ADX_THRESHOLD = 20.0
    DEFAULT_SPREAD_THRESHOLD = 0.001  # 0.1%
    DEFAULT_STALE_DATA_SECONDS = 5.0  # Max age for bookTicker data

    def __init__(
        self,
        adx_threshold: float = DEFAULT_ADX_THRESHOLD,
        spread_threshold: float = DEFAULT_SPREAD_THRESHOLD,
        book_ticker_client: Optional['IBookTickerClient'] = None,
        stale_data_seconds: float = DEFAULT_STALE_DATA_SECONDS,
        config: Optional['Config'] = None
    ):
        """
        Initialize HardFilters.

        Args:
            adx_threshold: Minimum ADX value for trending market (default: 25)
            spread_threshold: Maximum spread percentage (default: 0.1% = 0.001)
            book_ticker_client: BookTicker client for real bid/ask data (optional)
            stale_data_seconds: Max age for bookTicker data before considered stale
            config: Config object for configurable thresholds (Expert Feedback 3)
        """
        self.adx_threshold = adx_threshold
        self.spread_threshold = spread_threshold
        self._book_ticker_client = book_ticker_client
        self._config = config
        self.logger = logging.getLogger(__name__)

        # Use config value if available, otherwise use parameter/default
        if config and hasattr(config, 'book_ticker'):
            self._stale_data_seconds = config.book_ticker.max_age_seconds
            self.logger.info(
                f"Using config MAX_BOOK_TICKER_AGE_SECONDS: {self._stale_data_seconds}s"
            )
        else:
            self._stale_data_seconds = stale_data_seconds
        self.logger.info(
            f"HardFilters initialized: ADX>{adx_threshold}, Spread<{spread_threshold*100:.2f}%, "
            f"StaleData>{self._stale_data_seconds}s"
        )
        if book_ticker_client:
            self.logger.info("✅ BookTickerClient injected for real spread data")

    def check_adx_filter(
        self,
        adx_value: float,
        threshold: Optional[float] = None
    ) -> FilterResult:
        """
        Check if market is trending enough (ADX filter).

        ADX (Average Directional Index) measures trend strength:
        - ADX > 25: Strong trend (good for trend-following)
        - ADX < 25: Weak trend / choppy market (avoid trading)

        Args:
            adx_value: Current ADX value (0-100)
            threshold: Override default threshold (optional)

        Returns:
            FilterResult with pass/fail status

        Example:
            >>> filters = HardFilters()
            >>> result = filters.check_adx_filter(adx_value=30.5)
            >>> print(result)
            ADX: ✅ PASS (value=30.5000, threshold=25.0000)
        """
        threshold = threshold if threshold is not None else self.adx_threshold

        passed = adx_value >= threshold

        if passed:
            reason = f"ADX {adx_value:.1f} >= {threshold:.1f} (Trending market)"
        else:
            reason = f"ADX {adx_value:.1f} < {threshold:.1f} (Choppy/Sideways market - SKIP)"

        result = FilterResult(
            passed=passed,
            filter_name="ADX",
            value=adx_value,
            threshold=threshold,
            reason=reason
        )

        if not passed:
            self.logger.warning(f"🚫 {result}")
        else:
            self.logger.debug(f"✅ {result}")

        return result

    def check_spread_filter(
        self,
        bid: float,
        ask: float,
        threshold: Optional[float] = None
    ) -> FilterResult:
        """
        Check if spread is acceptable (Spread filter).

        Spread = (Ask - Bid) / Bid * 100%

        High spread indicates:
        - Low liquidity
        - High volatility (news events)
        - Market manipulation risk

        Args:
            bid: Current bid price
            ask: Current ask price
            threshold: Override default threshold (optional)

        Returns:
            FilterResult with pass/fail status

        Example:
            >>> filters = HardFilters()
            >>> result = filters.check_spread_filter(bid=95000, ask=95050)
            >>> print(result)
            Spread: ✅ PASS (value=0.0005, threshold=0.0010)
        """
        threshold = threshold if threshold is not None else self.spread_threshold

        # Calculate spread percentage
        if bid <= 0:
            return FilterResult(
                passed=False,
                filter_name="Spread",
                value=0.0,
                threshold=threshold,
                reason="Invalid bid price (<=0)"
            )

        spread_pct = (ask - bid) / bid

        passed = spread_pct <= threshold

        if passed:
            reason = f"Spread {spread_pct*100:.4f}% <= {threshold*100:.2f}% (Acceptable)"
        else:
            reason = f"Spread {spread_pct*100:.4f}% > {threshold*100:.2f}% (Too wide - SKIP)"

        result = FilterResult(
            passed=passed,
            filter_name="Spread",
            value=spread_pct,
            threshold=threshold,
            reason=reason
        )

        if not passed:
            self.logger.warning(f"🚫 {result}")
        else:
            self.logger.debug(f"✅ {result}")

        return result

    def check_all_filters(
        self,
        adx_value: float,
        bid: float,
        ask: float
    ) -> tuple:
        """
        Check all hard filters at once.

        Args:
            adx_value: Current ADX value
            bid: Current bid price
            ask: Current ask price

        Returns:
            Tuple of (all_passed: bool, results: list[FilterResult])
        """
        results = [
            self.check_adx_filter(adx_value),
            self.check_spread_filter(bid, ask)
        ]

        all_passed = all(r.passed for r in results)

        if not all_passed:
            failed = [r for r in results if not r.passed]
            self.logger.info(f"Hard filters blocked: {[r.filter_name for r in failed]}")

        return all_passed, results

    def check_spread_filter_realtime(
        self,
        symbol: str = "btcusdt",
        threshold: Optional[float] = None
    ) -> FilterResult:
        """
        Check spread using real bid/ask from BookTickerClient.

        This method uses real-time bid/ask data from the bookTicker stream
        instead of estimated values. It also checks data freshness.

        Args:
            symbol: Trading pair (default: 'btcusdt')
            threshold: Override default threshold (optional)

        Returns:
            FilterResult with pass/fail status

        Example:
            >>> filters = HardFilters(book_ticker_client=client)
            >>> result = filters.check_spread_filter_realtime("btcusdt")
            >>> if not result.passed:
            ...     print(f"Blocked: {result.reason}")
        """
        threshold = threshold if threshold is not None else self.spread_threshold

        # Check if BookTickerClient is available
        if not self._book_ticker_client:
            return FilterResult(
                passed=False,
                filter_name="Spread_Realtime",
                value=0.0,
                threshold=threshold,
                reason="No BookTickerClient configured - cannot check real spread"
            )

        # Check if data is fresh
        if not self._book_ticker_client.is_data_fresh(
            symbol=symbol,
            max_age_seconds=self._stale_data_seconds
        ):
            self.logger.warning(f"🚫 BookTicker data is stale for {symbol}")
            return FilterResult(
                passed=False,
                filter_name="Spread_Realtime",
                value=0.0,
                threshold=threshold,
                reason=f"Stale spread data (older than {self._stale_data_seconds}s) - SKIP"
            )

        # Get real bid/ask
        try:
            bid, ask = self._book_ticker_client.get_best_bid_ask(symbol)
        except ValueError as e:
            self.logger.warning(f"🚫 Cannot get bid/ask: {e}")
            return FilterResult(
                passed=False,
                filter_name="Spread_Realtime",
                value=0.0,
                threshold=threshold,
                reason=f"No bid/ask data available for {symbol}"
            )

        # Use existing spread filter logic with real data
        result = self.check_spread_filter(bid, ask, threshold)

        # Update filter name to indicate real data was used
        return FilterResult(
            passed=result.passed,
            filter_name="Spread_Realtime",
            value=result.value,
            threshold=result.threshold,
            reason=result.reason.replace("Spread", "Spread (Real)")
        )

    def set_book_ticker_client(self, client: 'IBookTickerClient') -> None:
        """
        Set or update the BookTickerClient.

        Args:
            client: BookTickerClient instance
        """
        self._book_ticker_client = client
        self.logger.info("✅ BookTickerClient updated")

    def has_book_ticker_client(self) -> bool:
        """Check if BookTickerClient is configured."""
        return self._book_ticker_client is not None

    def update_thresholds(
        self,
        adx_threshold: Optional[float] = None,
        spread_threshold: Optional[float] = None
    ) -> None:
        """
        Update filter thresholds at runtime.

        Args:
            adx_threshold: New ADX threshold (optional)
            spread_threshold: New spread threshold (optional)
        """
        if adx_threshold is not None:
            self.adx_threshold = adx_threshold
            self.logger.info(f"ADX threshold updated to {adx_threshold}")

        if spread_threshold is not None:
            self.spread_threshold = spread_threshold
            self.logger.info(f"Spread threshold updated to {spread_threshold*100:.2f}%")

    def get_config(self) -> dict:
        """Get current filter configuration."""
        return {
            'adx_threshold': self.adx_threshold,
            'spread_threshold': self.spread_threshold,
            'spread_threshold_pct': f"{self.spread_threshold*100:.2f}%",
            'has_book_ticker_client': self._book_ticker_client is not None,
            'stale_data_seconds': self._stale_data_seconds,
            'config_source': 'Config' if self._config else 'default'
        }

    def __repr__(self) -> str:
        book_ticker_status = "with_realtime" if self._book_ticker_client else "estimated"
        return (
            f"HardFilters(adx_threshold={self.adx_threshold}, "
            f"spread_threshold={self.spread_threshold*100:.2f}%, "
            f"spread_mode={book_ticker_status})"
        )
