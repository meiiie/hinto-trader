"""
WarmupManager - Application Layer

Manages cold start data warm-up for the trading bot.

Responsibilities:
- Load historical candles from REST API
- Process candles through indicators WITHOUT triggering signals
- Handle VWAP daily reset at 00:00 UTC
- Report warm-up status and indicator values

Critical Rules:
1. NEVER trigger trading signals during warm-up
2. VWAP must reset at 00:00 UTC boundary
3. Load enough data for all indicators (1000 candles ~10 days)
"""

import logging
import time
from datetime import datetime, timezone
from typing import List, Optional, Any, TYPE_CHECKING

from ...domain.entities.candle import Candle
from ...domain.entities.state_models import WarmupResult
from ...domain.interfaces import (
    IRestClient,
    IVWAPCalculator,
    IStochRSICalculator,
    IADXCalculator,
)

if TYPE_CHECKING:
    from ...infrastructure.aggregation.data_aggregator import DataAggregator


class WarmupManager:
    """
    Manages cold start data warm-up.

    Usage:
        manager = WarmupManager(rest_client, vwap_calc, stoch_calc, adx_calc)
        result = await manager.warmup(symbol="btcusdt", interval="15m", limit=1000)
        if result.success:
            print(f"VWAP: {result.vwap_value}")
    """

    def __init__(
        self,
        rest_client: IRestClient,
        vwap_calculator: IVWAPCalculator,
        stoch_rsi_calculator: IStochRSICalculator,
        adx_calculator: IADXCalculator,
        aggregator: Optional['DataAggregator'] = None
    ):
        """
        Initialize WarmupManager.

        Args:
            rest_client: REST API client for fetching historical data
            vwap_calculator: VWAP calculator instance
            stoch_rsi_calculator: StochRSI calculator instance
            adx_calculator: ADX calculator instance
            aggregator: Data aggregator (optional)
        """
        self.rest_client = rest_client
        self.vwap_calculator = vwap_calculator
        self.stoch_rsi_calculator = stoch_rsi_calculator
        self.adx_calculator = adx_calculator
        self.aggregator = aggregator

        self._is_warming_up = False
        self._candles_processed = 0

        self.logger = logging.getLogger(__name__)

    @property
    def is_warming_up(self) -> bool:
        """Check if warm-up is in progress."""
        return self._is_warming_up

    async def warmup(
        self,
        symbol: str = "btcusdt",
        interval: str = "15m",
        limit: int = 1000
    ) -> WarmupResult:
        """
        Perform cold start warm-up.

        Loads historical candles and processes them through indicators
        WITHOUT triggering any trading signals.

        Args:
            symbol: Trading symbol
            interval: Candle interval (default: 15m for ~10 days with 1000 candles)
            limit: Number of candles to load

        Returns:
            WarmupResult with status and indicator values
        """
        self._is_warming_up = True
        self._candles_processed = 0
        start_time = time.time()

        self.logger.info(f"🔄 Starting warm-up: {symbol} {interval} x{limit}")

        try:
            # Step 1: Fetch historical candles
            candles = self._fetch_historical_candles(symbol, interval, limit)

            if not candles:
                return WarmupResult(
                    success=False,
                    error="Failed to fetch historical candles"
                )

            self.logger.info(f"📊 Loaded {len(candles)} historical candles")

            # Step 2: Process candles through indicators (NO SIGNALS!)
            self._process_candles_for_warmup(candles)

            # Step 3: Get current indicator values
            vwap_value = self._get_current_vwap(candles)
            stoch_k, stoch_d = self._get_current_stoch_rsi(candles)
            adx_value = self._get_current_adx(candles)

            duration = time.time() - start_time

            result = WarmupResult(
                success=True,
                candles_processed=len(candles),
                vwap_value=vwap_value,
                stoch_rsi_k=stoch_k,
                stoch_rsi_d=stoch_d,
                adx_value=adx_value,
                duration_seconds=duration
            )

            self.logger.info(f"✅ {result}")
            return result

        except Exception as e:
            self.logger.error(f"❌ Warm-up failed: {e}", exc_info=True)
            return WarmupResult(
                success=False,
                candles_processed=self._candles_processed,
                duration_seconds=time.time() - start_time,
                error=str(e)
            )
        finally:
            self._is_warming_up = False

    def _fetch_historical_candles(
        self,
        symbol: str,
        interval: str,
        limit: int
    ) -> List[Candle]:
        """
        Fetch historical candles from REST API.

        Args:
            symbol: Trading symbol
            interval: Candle interval
            limit: Number of candles

        Returns:
            List of Candle entities
        """
        try:
            candles = self.rest_client.get_klines(
                symbol=symbol,
                interval=interval,
                limit=limit
            )
            return candles or []
        except Exception as e:
            self.logger.error(f"Failed to fetch candles: {e}")
            return []

    def _process_candles_for_warmup(self, candles: List[Candle]) -> None:
        """
        Process candles through indicators WITHOUT triggering signals.

        This is the critical warm-up loop. We update indicators but
        NEVER generate or publish trading signals.

        Args:
            candles: List of historical candles
        """
        prev_date: Optional[datetime] = None

        for candle in candles:
            # Check for VWAP daily reset (00:00 UTC)
            current_date = candle.timestamp.date() if candle.timestamp.tzinfo else \
                          candle.timestamp.replace(tzinfo=timezone.utc).date()

            if prev_date and current_date != prev_date:
                # New day - reset VWAP
                self._reset_vwap_for_new_day()
                self.logger.debug(f"VWAP reset at day boundary: {current_date}")

            prev_date = current_date

            # Feed to aggregator if available (for multi-timeframe)
            if self.aggregator:
                # Note: is_closed=True for historical data
                self.aggregator.add_candle_1m(candle, is_closed=True)

            self._candles_processed += 1

        self.logger.debug(f"Processed {self._candles_processed} candles for warm-up")

    def _reset_vwap_for_new_day(self) -> None:
        """
        Reset VWAP calculator for new trading day.

        VWAP resets at 00:00 UTC each day.
        """
        if hasattr(self.vwap_calculator, 'reset'):
            self.vwap_calculator.reset()
        elif hasattr(self.vwap_calculator, '_cumulative_volume'):
            # Manual reset if no reset method
            self.vwap_calculator._cumulative_volume = 0.0
            self.vwap_calculator._cumulative_vwap = 0.0

    def _get_current_vwap(self, candles: List[Candle]) -> float:
        """Get current VWAP value after warm-up."""
        try:
            result = self.vwap_calculator.calculate_vwap(candles)
            return result.vwap if result else 0.0
        except Exception as e:
            self.logger.warning(f"Failed to get VWAP: {e}")
            return 0.0

    def _get_current_stoch_rsi(self, candles: List[Candle]) -> tuple:
        """Get current StochRSI K and D values."""
        try:
            result = self.stoch_rsi_calculator.calculate_stoch_rsi(candles)
            if result:
                return result.k_value, result.d_value
            return 0.0, 0.0
        except Exception as e:
            self.logger.warning(f"Failed to get StochRSI: {e}")
            return 0.0, 0.0

    def _get_current_adx(self, candles: List[Candle]) -> float:
        """Get current ADX value."""
        try:
            result = self.adx_calculator.calculate_adx(candles)
            return result.adx_value if result else 0.0
        except Exception as e:
            self.logger.warning(f"Failed to get ADX: {e}")
            return 0.0

    def check_vwap_daily_reset(self, candle: Candle, prev_candle: Optional[Candle]) -> bool:
        """
        Check if VWAP should reset based on candle timestamps.

        Args:
            candle: Current candle
            prev_candle: Previous candle

        Returns:
            True if VWAP was reset
        """
        if not prev_candle:
            return False

        # Get dates in UTC
        current_date = candle.timestamp.date() if candle.timestamp.tzinfo else \
                      candle.timestamp.replace(tzinfo=timezone.utc).date()
        prev_date = prev_candle.timestamp.date() if prev_candle.timestamp.tzinfo else \
                   prev_candle.timestamp.replace(tzinfo=timezone.utc).date()

        if current_date != prev_date:
            self._reset_vwap_for_new_day()
            self.logger.info(f"🔄 VWAP reset for new day: {current_date}")
            return True

        return False

    def __repr__(self) -> str:
        return f"WarmupManager(warming_up={self._is_warming_up}, processed={self._candles_processed})"
