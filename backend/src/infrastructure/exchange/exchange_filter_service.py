"""
ExchangeFilterService - Infrastructure Layer

SOTA: Fetch and apply Binance exchange filters to prevent API errors.
Implements Freqtrade-style quantity/price sanitization with Decimal precision.

Key Filters:
- LOT_SIZE: minQty, stepSize (quantity constraints)
- PRICE_FILTER: tickSize (price precision)
- MIN_NOTIONAL: minimum order value in USDT

This service MUST be initialized at startup and injected into LiveTradingService.

Reference:
- Binance API: https://binance-docs.github.io/apidocs/futures/en/#filters
- Freqtrade: amount_to_precision(), price_to_precision()
- CCXT: TICK_SIZE precision mode
"""

import logging
import math
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from typing import Dict, Optional, Tuple
from dataclasses import dataclass


@dataclass
class SymbolFilters:
    """
    Filters for a single trading symbol.

    All values stored as Decimal for precision.

    SOTA: Binance has TWO different lot size filters:
    - LOT_SIZE: For LIMIT orders (typically higher maxQty)
    - MARKET_LOT_SIZE: For MARKET/STOP_MARKET orders (typically lower maxQty)
    """
    symbol: str
    min_qty: Decimal
    max_qty: Decimal           # LOT_SIZE maxQty (for LIMIT orders)
    step_size: Decimal
    min_price: Decimal
    max_price: Decimal
    tick_size: Decimal
    min_notional: Decimal
    qty_precision: int
    price_precision: int
    # SOTA: MARKET_LOT_SIZE for MARKET/STOP_MARKET orders
    market_max_qty: Decimal = None  # If None, use max_qty as fallback


class ExchangeFilterService:
    """
    Service to fetch and apply Binance exchange filters.

    CRITICAL for live trading to prevent:
    - APIError(code=-1013): Filter failure
    - LOT_SIZE violations
    - MIN_NOTIONAL violations
    - PRICE_FILTER violations

    Usage:
        # At startup
        filter_service = ExchangeFilterService()
        filter_service.load_filters(binance_client)

        # Before placing orders
        qty = filter_service.sanitize_quantity("BTCUSDT", raw_qty)
        price = filter_service.sanitize_price("BTCUSDT", raw_price)
        is_valid, error = filter_service.validate_order("BTCUSDT", qty, price)
    """

    def __init__(self, use_testnet: bool = False):
        self.logger = logging.getLogger(__name__)
        self.use_testnet = use_testnet
        self._filters: Dict[str, SymbolFilters] = {}
        self._loaded = False

        # Default fallbacks for unknown symbols
        self._default_filters = SymbolFilters(
            symbol="DEFAULT",
            min_qty=Decimal("0.001"),
            max_qty=Decimal("1000000"),
            step_size=Decimal("0.001"),
            min_price=Decimal("0.01"),
            max_price=Decimal("1000000"),
            tick_size=Decimal("0.01"),
            min_notional=Decimal("5.0"),
            qty_precision=3,
            price_precision=2
        )

    def load_filters(self, binance_client) -> bool:
        """
        Load exchange info and cache filters for all symbols.

        MUST be called once at startup before any trading.

        Args:
            binance_client: BinanceFuturesClient instance

        Returns:
            True if loaded successfully
        """
        try:
            self.logger.info("📊 Loading exchange filters from Binance...")

            # Fetch full exchange info
            exchange_info = binance_client.get_exchange_info()

            symbols_data = exchange_info.get('symbols', [])
            loaded_count = 0

            for symbol_info in symbols_data:
                sym = symbol_info.get('symbol', '')

                # Only process USDT perpetual pairs
                if not sym.endswith('USDT'):
                    continue

                # Build filter dictionary
                filters = {f['filterType']: f for f in symbol_info.get('filters', [])}

                # Extract LOT_SIZE (for LIMIT orders)
                lot_size = filters.get('LOT_SIZE', {})
                min_qty = Decimal(str(lot_size.get('minQty', '0.001')))
                max_qty = Decimal(str(lot_size.get('maxQty', '1000000')))
                step_size = Decimal(str(lot_size.get('stepSize', '0.001')))

                # SOTA: Extract MARKET_LOT_SIZE (for MARKET/STOP_MARKET orders)
                # This filter often has LOWER maxQty than LOT_SIZE!
                market_lot_size = filters.get('MARKET_LOT_SIZE', {})
                market_max_qty = Decimal(str(market_lot_size.get('maxQty', max_qty)))

                # Extract PRICE_FILTER
                price_filter = filters.get('PRICE_FILTER', {})
                min_price = Decimal(str(price_filter.get('minPrice', '0.01')))
                max_price = Decimal(str(price_filter.get('maxPrice', '1000000')))
                tick_size = Decimal(str(price_filter.get('tickSize', '0.01')))

                # Extract MIN_NOTIONAL
                min_notional_filter = filters.get('MIN_NOTIONAL', {})
                min_notional = Decimal(str(min_notional_filter.get('notional', '5.0')))

                # Extract precision
                qty_precision = int(symbol_info.get('quantityPrecision', 3))
                price_precision = int(symbol_info.get('pricePrecision', 2))

                self._filters[sym] = SymbolFilters(
                    symbol=sym,
                    min_qty=min_qty,
                    max_qty=max_qty,
                    step_size=step_size,
                    min_price=min_price,
                    max_price=max_price,
                    tick_size=tick_size,
                    min_notional=min_notional,
                    qty_precision=qty_precision,
                    price_precision=price_precision,
                    market_max_qty=market_max_qty  # SOTA: For STOP_MARKET orders
                )
                loaded_count += 1

            self._loaded = True
            self.logger.info(f"✅ Loaded filters for {loaded_count} USDT pairs")

            # Log some examples for debugging
            for sym in ['BTCUSDT', 'ETHUSDT', 'DOGEUSDT', '1000PEPEUSDT']:
                if sym in self._filters:
                    f = self._filters[sym]
                    self.logger.debug(
                        f"   {sym}: minQty={f.min_qty}, step={f.step_size}, "
                        f"tick={f.tick_size}, minNotional={f.min_notional}"
                    )

            return True

        except Exception as e:
            self.logger.error(f"❌ Failed to load exchange filters: {e}")
            self._loaded = False
            return False

    def load_from_file(self, file_path: str = None) -> bool:
        """
        Load filters from market_intelligence.json file.

        This is FASTER than calling Binance API and uses verified data.
        The file is generated by: python backend/scripts/get_market_intelligence.py

        Args:
            file_path: Path to JSON file (default: backend/data/market_intelligence.json)

        Returns:
            True if loaded successfully
        """
        import json
        import os

        if file_path is None:
            # Default path relative to project root
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
            file_path = os.path.join(base_dir, "data", "market_intelligence.json")

        try:
            if not os.path.exists(file_path):
                self.logger.warning(f"⚠️ Filter cache not found: {file_path}")
                return False

            self.logger.info(f"📊 Loading filters from cache: {file_path}")

            with open(file_path, 'r') as f:
                data = json.load(f)

            loaded_count = 0

            for sym, info in data.items():
                rules = info.get('rules', {})

                self._filters[sym] = SymbolFilters(
                    symbol=sym,
                    min_qty=Decimal(str(rules.get('min_qty', 0.001))),
                    max_qty=Decimal(str(rules.get('max_qty', 1000000))),
                    step_size=Decimal(str(rules.get('step_size', 0.001))),
                    min_price=Decimal('0'),
                    max_price=Decimal('1000000'),
                    tick_size=Decimal(str(rules.get('tick_size', 0.01))),
                    min_notional=Decimal(str(rules.get('min_notional', 5.0))),
                    qty_precision=int(rules.get('qty_precision', 3)),
                    price_precision=int(rules.get('price_precision', 2))
                )
                loaded_count += 1

            self._loaded = True
            self.logger.info(f"✅ Loaded filters for {loaded_count} symbols from cache")

            # Log examples
            for sym in ['BTCUSDT', 'DOGEUSDT', '1000PEPEUSDT']:
                if sym in self._filters:
                    f = self._filters[sym]
                    self.logger.info(
                        f"   {sym}: minQty={f.min_qty}, step={f.step_size}, "
                        f"minNotional={f.min_notional}"
                    )

            return True

        except Exception as e:
            self.logger.error(f"❌ Failed to load filters from file: {e}")
            return False

    def get_filters(self, symbol: str) -> SymbolFilters:
        """Get filters for a symbol, with fallback to defaults."""
        return self._filters.get(symbol.upper(), self._default_filters)

    def sanitize_quantity(self, symbol: str, quantity: float, apply_max_cap: bool = True) -> float:
        """
        Round quantity to valid stepSize using floor division.

        SOTA Algorithm (Freqtrade-style):
        1. Convert to Decimal for precision
        2. Floor to nearest stepSize (don't exceed intended quantity)
        3. Clamp to min/max limits (max limit is optional)
        4. Return as float

        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            quantity: Raw quantity to sanitize
            apply_max_cap: If True, cap quantity at max_qty

        Returns:
            Sanitized quantity that passes LOT_SIZE filter
        """
        filters = self.get_filters(symbol)

        # Convert to Decimal for precision
        d_qty = Decimal(str(quantity))
        d_step = filters.step_size

        if d_step == 0:
            return quantity

        # Floor to nearest step (never exceed intended quantity)
        # This is critical for risk management - we never want to over-trade
        steps = (d_qty / d_step).quantize(Decimal('1'), rounding=ROUND_DOWN)
        sanitized = steps * d_step

        # Clamp to limits
        sanitized = max(sanitized, filters.min_qty)
        if apply_max_cap:
            sanitized = min(sanitized, filters.max_qty)

        # Convert back to float with proper precision
        result = float(round(sanitized, filters.qty_precision))

        self.logger.debug(
            f"🔢 {symbol}: qty {quantity} → {result} "
            f"(step={filters.step_size}, min={filters.min_qty}, cap={apply_max_cap})"
        )

        return result

    def sanitize_price(self, symbol: str, price: float) -> float:
        """
        Round price to valid tickSize.

        Uses ROUND_HALF_UP for price (less directional bias than floor).

        Args:
            symbol: Trading pair
            price: Raw price to sanitize

        Returns:
            Sanitized price that passes PRICE_FILTER
        """
        filters = self.get_filters(symbol)

        d_price = Decimal(str(price))
        d_tick = filters.tick_size

        if d_tick == 0:
            return price

        # Round to nearest tick (for price, we use normal rounding)
        steps = (d_price / d_tick).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        sanitized = steps * d_tick

        # Clamp to limits
        sanitized = max(sanitized, filters.min_price)
        sanitized = min(sanitized, filters.max_price)

        result = float(round(sanitized, filters.price_precision))

        return result

    def validate_order(
        self,
        symbol: str,
        quantity: float,
        price: float
    ) -> Tuple[bool, str]:
        """
        Validate order against all filters before sending to exchange.

        Checks:
        1. LOT_SIZE: quantity >= minQty, valid stepSize
        2. PRICE_FILTER: valid tickSize
        3. MIN_NOTIONAL: quantity * price >= minNotional

        Args:
            symbol: Trading pair
            quantity: Order quantity (should be pre-sanitized)
            price: Order price (should be pre-sanitized)

        Returns:
            (is_valid, error_message)
        """
        filters = self.get_filters(symbol)

        d_qty = Decimal(str(quantity))
        d_price = Decimal(str(price))

        # 1. Check minimum quantity
        if d_qty < filters.min_qty:
            return False, f"Quantity {quantity} < minQty {filters.min_qty}"

        # 2. Check maximum quantity
        if d_qty > filters.max_qty:
            return False, f"Quantity {quantity} > maxQty {filters.max_qty}"

        # 3. Check quantity step (should be zero after sanitization)
        remainder = d_qty % filters.step_size
        if remainder != 0:
            return False, f"Quantity {quantity} not multiple of stepSize {filters.step_size}"

        # 4. Check minimum notional
        notional = d_qty * d_price
        if notional < filters.min_notional:
            return False, f"Notional ${float(notional):.2f} < minNotional ${filters.min_notional}"

        return True, ""

    def split_quantity(self, symbol: str, total_quantity: float) -> list[float]:
        """
        SOTA: Split a large quantity into multiple chunks respecting MAX_QTY.
        Uses LOT_SIZE filter (for LIMIT orders).

        Example:
        - Total: 56.61, Max: 50.0 -> Returns: [50.0, 6.61]
        - Total: 150.0, Max: 50.0 -> Returns: [50.0, 50.0, 50.0]

        Args:
            symbol: Trading pair
            total_quantity: Total quantity to split

        Returns:
            List of valid quantity chunks
        """
        filters = self.get_filters(symbol)
        chunks = []

        # 1. Sanitize the total first to ensure it's a valid multiple of step_size
        # SOTA: Do NOT apply max cap here, as we are about to split it
        remaining = Decimal(str(self.sanitize_quantity(symbol, total_quantity, apply_max_cap=False)))
        max_qty = filters.max_qty

        if max_qty <= 0:
            return [float(remaining)]

        while remaining > 0:
            if remaining > max_qty:
                # Add a full max_qty chunk
                chunks.append(float(max_qty))
                remaining -= max_qty
            else:
                # Add the remainder
                # Sanitize again to be safe against float drift, though Decimal handles it well
                final_chunk = float(remaining)
                if final_chunk > 0:
                    chunks.append(final_chunk)
                break

        return chunks

    def split_quantity_market(self, symbol: str, total_quantity: float) -> list[float]:
        """
        SOTA: Split quantity for MARKET/STOP_MARKET orders.
        Uses MARKET_LOT_SIZE filter which often has LOWER maxQty than LOT_SIZE.

        This is CRITICAL for STOP_MARKET orders that get -4005 errors!

        Args:
            symbol: Trading pair
            total_quantity: Total quantity to split

        Returns:
            List of valid quantity chunks for MARKET orders
        """
        filters = self.get_filters(symbol)
        chunks = []

        # Sanitize first (no max cap)
        remaining = Decimal(str(self.sanitize_quantity(symbol, total_quantity, apply_max_cap=False)))

        # Use MARKET_LOT_SIZE maxQty (fallback to LOT_SIZE if not set)
        max_qty = filters.market_max_qty if filters.market_max_qty else filters.max_qty

        self.logger.info(f"🔀 MARKET SPLIT: {symbol} qty={total_quantity}, market_maxQty={max_qty}")

        if max_qty <= 0:
            return [float(remaining)]

        while remaining > 0:
            if remaining > max_qty:
                chunks.append(float(max_qty))
                remaining -= max_qty
            else:
                final_chunk = float(remaining)
                if final_chunk > 0:
                    chunks.append(final_chunk)
                break

        return chunks

    def get_min_quantity(self, symbol: str) -> float:
        """Get minimum order quantity for a symbol."""
        filters = self.get_filters(symbol)
        return float(filters.min_qty)

    def get_min_notional(self, symbol: str) -> float:
        """Get minimum notional value for a symbol."""
        filters = self.get_filters(symbol)
        return float(filters.min_notional)

    def calculate_min_quantity_for_notional(
        self,
        symbol: str,
        price: float,
        target_notional: float = None
    ) -> float:
        """
        Calculate minimum quantity needed to meet MIN_NOTIONAL.

        Useful for small capital accounts.

        Args:
            symbol: Trading pair
            price: Current price
            target_notional: Target value (default: use minNotional)

        Returns:
            Minimum quantity needed, sanitized to stepSize
        """
        filters = self.get_filters(symbol)

        target = Decimal(str(target_notional)) if target_notional else filters.min_notional
        d_price = Decimal(str(price))

        if d_price == 0:
            return 0

        # Calculate raw quantity
        min_qty_for_notional = target / d_price

        # Use max of this and minQty
        required_qty = max(min_qty_for_notional, filters.min_qty)

        # Sanitize up (ceiling) to ensure we meet notional
        d_step = filters.step_size
        steps = (required_qty / d_step).quantize(Decimal('1'), rounding=ROUND_DOWN)

        # Add one step if below target
        sanitized = steps * d_step
        while sanitized * d_price < target:
            sanitized += d_step

        return float(round(sanitized, filters.qty_precision))

    @property
    def is_loaded(self) -> bool:
        """Check if filters have been loaded."""
        return self._loaded

    def get_stats(self) -> Dict:
        """Get service statistics for monitoring."""
        return {
            "loaded": self._loaded,
            "symbols_count": len(self._filters),
            "use_testnet": self.use_testnet
        }
