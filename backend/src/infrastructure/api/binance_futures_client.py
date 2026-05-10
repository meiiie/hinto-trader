"""
BinanceFuturesClient - Infrastructure Layer

SOTA Binance Futures API Client with HMAC-SHA256 Authentication.
Supports both Testnet and Production environments.

Features:
- HMAC-SHA256 request signing (Binance standard)
- Automatic testnet/production URL switching
- Order placement (LIMIT, MARKET)
- Position management
- Account balance queries
- Rate limit awareness

Reference: https://binance-docs.github.io/apidocs/futures/en/
"""

import os
import time
import hmac
import hashlib
import logging
import threading
import requests
from typing import Optional, Dict, Any, List
from urllib.parse import urlencode
from dataclasses import dataclass
from enum import Enum


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"
    STOP_MARKET = "STOP_MARKET"
    TAKE_PROFIT_MARKET = "TAKE_PROFIT_MARKET"


class PositionSide(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    BOTH = "BOTH"  # For one-way mode


class TimeInForce(Enum):
    GTC = "GTC"  # Good Till Cancel
    IOC = "IOC"  # Immediate Or Cancel
    FOK = "FOK"  # Fill Or Kill
    GTX = "GTX"  # Good Till Crossing (Post Only)


@dataclass
class FuturesOrder:
    """Represents a Binance Futures order."""
    order_id: int
    client_order_id: str
    symbol: str
    side: str
    type: str
    status: str
    price: float
    quantity: float
    executed_qty: float
    avg_price: float
    time_in_force: str
    reduce_only: bool = False
    time: int = 0  # SOTA: Order creation time (ms since epoch)
    stop_price: float = 0  # SOTA: Stop price for STOP_MARKET orders


@dataclass
class FuturesPosition:
    """Represents a Binance Futures position."""
    symbol: str
    position_side: str
    position_amt: float
    entry_price: float
    unrealized_pnl: float
    leverage: int
    liquidation_price: float
    margin_type: str
    mark_price: float = 0.0  # Current mark price
    margin: float = 0.0  # Position margin


@dataclass
class AccountBalance:
    """Represents account balance info."""
    asset: str
    wallet_balance: float
    available_balance: float
    unrealized_pnl: float
    margin_balance: float


class BinanceFuturesClient:
    """
    SOTA Binance Futures API Client.

    Implements institutional-grade API integration with:
    - HMAC-SHA256 authentication
    - Testnet/Production toggle
    - Comprehensive error handling
    - Rate limit awareness

    Usage:
        client = BinanceFuturesClient()  # Uses env vars

        # Place order
        order = client.create_order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=0.001,
            price=95000.0
        )

        # Get positions
        positions = client.get_positions()
    """

    # API Endpoints
    PRODUCTION_BASE_URL = "https://fapi.binance.com"
    TESTNET_BASE_URL = "https://testnet.binancefuture.com"

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        use_testnet: Optional[bool] = None,
        timeout: int = 5,  # SOTA FIX: Reduced from 10s to 5s for faster fail on testnet
        recv_window: int = 5000,
        filter_service: Optional[Any] = None  # SOTA: Inject ExchangeFilterService for dynamic precision
    ):
        """
        Initialize Binance Futures Client.

        Args:
            api_key: API key (defaults to env var)
            api_secret: API secret (defaults to env var)
            use_testnet: Use testnet (defaults to env var)
            timeout: Request timeout in seconds
            recv_window: Receive window for timestamp validation
        """
        self.logger = logging.getLogger(__name__)
        self.timeout = timeout
        self.recv_window = recv_window

        # SOTA: Determine testnet from ENV variable (priority) or explicit parameter
        if use_testnet is not None:
            self.use_testnet = use_testnet
        else:
            # Check new ENV variable first, fallback to old BINANCE_USE_TESTNET
            env = os.getenv("ENV", "paper").lower()
            if env == "testnet":
                self.use_testnet = True
            elif env == "live":
                self.use_testnet = False
            else:
                # Paper mode or fallback - check old variable
                self.use_testnet = os.getenv("BINANCE_USE_TESTNET", "true").lower() == "true"

        if self.use_testnet:
            self.api_key = (api_key or os.getenv("BINANCE_TESTNET_API_KEY", "")).strip()
            self.api_secret = (api_secret or os.getenv("BINANCE_TESTNET_API_SECRET", "")).strip()
            self.base_url = self.TESTNET_BASE_URL
            self.logger.warning("🧪 RUNNING IN TESTNET MODE - Using testnet.binancefuture.com")
        else:
            self.api_key = (api_key or os.getenv("BINANCE_API_KEY", "")).strip()
            self.api_secret = (api_secret or os.getenv("BINANCE_API_SECRET", "")).strip()
            self.base_url = self.PRODUCTION_BASE_URL
            env_mode = os.getenv("ENV", "paper").lower().strip()
            if env_mode == "paper":
                self.logger.info(
                    "PAPER mode using Binance mainnet market-data endpoint; order routing remains local."
                )
            else:
                self.logger.warning("🔴 RUNNING IN PRODUCTION MODE - Real money!")

        if not self.api_key or not self.api_secret:
            raise ValueError("API credentials not provided. Set env vars or pass directly.")

        # SOTA (Jan 2026): Inject ExchangeFilterService for dynamic precision
        self.filter_service = filter_service

        # SOTA FIX: Thread-local session storage
        # Root cause: requests.Session is NOT thread-safe when shared across concurrent asyncio.to_thread() calls
        # Solution: Each thread gets its own Session instance
        self._session_local = threading.local()

        self.logger.info(f"BinanceFuturesClient initialized | ENV={os.getenv('ENV', 'paper')} | Testnet: {self.use_testnet} | URL: {self.base_url}")

        # SOTA (Jan 2026): REMOVED blocking _sync_server_time() call!
        # Time sync now happens LAZILY on first signed request to avoid blocking constructor.
        # This is critical for fast startup with 50+ symbols.
        self._time_offset = 0
        self._time_synced = False

    # =========================================================================
    # THREAD-SAFE SESSION MANAGEMENT (SOTA FIX Jan 2026)
    # =========================================================================

    @property
    def _session(self) -> requests.Session:
        """
        Get thread-local Session instance.

        SOTA: Each thread gets its own Session to prevent contention
        when multiple asyncio.to_thread() calls run simultaneously.

        Root cause analysis: requests.Session shares connection pool state
        which causes 32s cascading delays when 4+ threads contend.
        """
        if not hasattr(self._session_local, 'session'):
            self._session_local.session = requests.Session()

            self.logger.info(
                "Binance session initialized | api_key_present=%s | key_len=%d",
                bool(self.api_key),
                len(self.api_key),
            )

            self._session_local.session.headers.update({
                "X-MBX-APIKEY": self.api_key,
                "Content-Type": "application/x-www-form-urlencoded"
            })
        return self._session_local.session

    # =========================================================================
    # AUTHENTICATION (HMAC-SHA256)
    # =========================================================================

    def _sync_server_time(self):
        """
        Sync local time with Binance server.

        SOTA: Fixes 'Timestamp outside recvWindow' error (-1021)
        by calculating offset between local and server time.
        """
        try:
            server_time = self.get_server_time()
            local_time = int(time.time() * 1000)
            self._time_offset = server_time - local_time
            self.logger.info(f"⏱️ Time offset synced: {self._time_offset}ms")
        except Exception as e:
            # SOTA FIX: Do NOT reset offset to 0 on failure!
            # If network is flaky, keeping old offset is safer than assuming 0 (which causes -1021)
            self.logger.warning(f"⚠️ Failed to sync server time: {e}. Keeping last known offset: {getattr(self, '_time_offset', 0)}ms")
            # self._time_offset = 0  <-- REMOVED THIS LINE


    def _get_timestamp(self) -> int:
        """Get current timestamp in milliseconds (adjusted for server time)."""
        if not hasattr(self, '_time_offset'):
            self._time_offset = 0
        return int(time.time() * 1000) + self._time_offset

    def _sign(self, params: Dict[str, Any]) -> str:
        """
        Create HMAC-SHA256 signature for request.

        Binance requires signature = HMAC_SHA256(secret, query_string)
        """
        query_string = urlencode(params)
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return signature

    def _send_signed_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Send authenticated request to Binance.

        SOTA Upgrade (Jan 2026): Added Self-Healing for -1021 Errors.
        Automatically resyncs server time and retries if timestamp drift detected.

        Args:
            method: HTTP method (GET, POST, DELETE)
            endpoint: API endpoint (e.g., /fapi/v1/order)
            params: Request parameters

        Returns:
            Response JSON

        Raises:
            Exception: If request fails after retries
        """
        MAX_RETRIES = 2  # SOTA FIX: Reduced from 3 to 2 for faster fail on testnet
        retry_count = 0
        last_error = None

        url = f"{self.base_url}{endpoint}"

        # SOTA (Jan 2026): Lazy time sync on first signed request
        # This avoids blocking in constructor while still preventing -1021 errors
        if not getattr(self, '_time_synced', False):
            try:
                self._sync_server_time()
                self._time_synced = True
            except Exception as e:
                self.logger.debug(f"Initial time sync deferred: {e}")

        while retry_count < MAX_RETRIES:
            try:
                # Prepare params (New timestamp every retry)
                current_params = params.copy() if params else {}
                current_params["timestamp"] = self._get_timestamp()
                current_params["recvWindow"] = self.recv_window
                current_params["signature"] = self._sign(current_params)

                if method == "GET":
                    response = self._session.get(url, params=current_params, timeout=self.timeout)
                elif method == "POST":
                    response = self._session.post(url, data=current_params, timeout=self.timeout)
                elif method == "DELETE":
                    response = self._session.delete(url, params=current_params, timeout=self.timeout)
                elif method == "PUT":
                    response = self._session.put(url, data=current_params, timeout=self.timeout)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                response.raise_for_status()
                return response.json()

            except requests.exceptions.HTTPError as e:
                # Parse Binance Error
                error_code = 0
                error_msg = str(e)
                try:
                    data = response.json()
                    error_code = data.get('code')
                    error_msg = data.get('msg')
                except:
                    pass

                # SOTA Self-Healing: Error -1021 (Timestamp ahead/behind)
                # This happens when network lag causes request to arrive late, or local clock drifts
                if error_code == -1021:
                    self.logger.warning(f"⏳ Timestamp drift detected (-1021). Syncing time... (Attempt {retry_count+1}/{MAX_RETRIES})")
                    self._sync_server_time()
                    retry_count += 1
                    time.sleep(0.5) # Slight backoff
                    continue

                # Server Errors (5xx) - Retryable
                if 500 <= response.status_code < 600:
                    self.logger.warning(f"🌐 Binance server error {response.status_code}. Retrying... ({retry_count+1}/{MAX_RETRIES})")
                    retry_count += 1
                    time.sleep(1)
                    continue

                # Client Errors (4xx) - Non-retryable (except 429 rate limit maybe)
                # Log detailed parameters for debugging
                debug_params = {k: v for k, v in current_params.items() if k not in ('signature', 'timestamp')}

                # SOTA FIX (Feb 2026): Downgrade -2011 (Unknown Order) to WARNING
                # This is benign during race conditions (e.g., SL hit vs Manual Cancel)
                if error_code == -2011:
                     self.logger.warning(f"⚠️ Order not found (-2011): Likely already closed/cancelled. Params: {debug_params}")
                else:
                     self.logger.error(f"❌ Binance Request Failed: Error {error_code}: {error_msg} | Params: {debug_params}")

                raise Exception(f"Binance Error {error_code}: {error_msg}")

            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                # Network Errors - Retryable
                self.logger.warning(f"🔌 Network error: {e}. Retrying... ({retry_count+1}/{MAX_RETRIES})")
                retry_count += 1
                time.sleep(1)
                last_error = e
                continue

            except Exception as e:
                self.logger.error(f"Request failed: {e}")
                raise

        raise Exception(f"Max retries exceeded: {last_error}")

    def _send_public_request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Send unauthenticated public request."""
        url = f"{self.base_url}{endpoint}"
        response = self._session.get(url, params=params or {}, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    # =========================================================================
    # ACCOUNT & BALANCE
    # =========================================================================

    def get_account_info(self) -> Dict[str, Any]:
        """
        Get comprehensive account information.

        SOTA (2025): Use /fapi/v3/account for accurate data.
        Returns totalWalletBalance, totalMarginBalance, totalUnrealizedProfit, etc.

        Returns:
            Complete account info dict
        """
        return self._send_signed_request("GET", "/fapi/v3/account")

    def get_account_balance(self) -> List[AccountBalance]:
        """
        Get futures account balance per asset.

        SOTA (2025): Use /fapi/v3/account for accurate marginBalance.
        This endpoint provides marginBalance directly, no manual calculation needed.

        Returns:
            List of AccountBalance for each asset
        """
        data = self.get_account_info()

        balances = []
        assets = data.get("assets", [])

        for item in assets:
            wallet_balance = float(item.get("walletBalance", 0))

            if wallet_balance > 0 or item.get("asset") == "USDT":
                balances.append(AccountBalance(
                    asset=item.get("asset"),
                    wallet_balance=wallet_balance,
                    available_balance=float(item.get("availableBalance", 0)),
                    unrealized_pnl=float(item.get("unrealizedProfit", 0)),
                    # SOTA: marginBalance comes directly from API
                    margin_balance=float(item.get("marginBalance", 0))
                ))

        return balances

    def get_usdt_balance(self) -> float:
        """
        Get USDT wallet balance (total funds in account).

        SOTA: This is the 'Số dư ví(USD)' in Binance Futures UI.
        This represents total deposited funds, not reduced by margin in use.

        Use get_usdt_available() for funds available for new trades.
        """
        balances = self.get_account_balance()
        for b in balances:
            if b.asset == "USDT":
                return b.wallet_balance
        return 0.0

    def get_usdt_available(self) -> float:
        """
        Get available USDT for new positions/withdrawal.

        SOTA: This is 'availableBalance' - reduced by margin used for open positions.
        Use this for position sizing calculations.
        """
        balances = self.get_account_balance()
        for b in balances:
            if b.asset == "USDT":
                return b.available_balance
        return 0.0

    def get_usdt_margin_balance(self) -> float:
        """
        Get USDT margin balance (wallet + unrealized PnL).

        SOTA: This is 'Số dư margin' in Binance Futures UI.
        Most accurate representation of current account value.
        """
        balances = self.get_account_balance()
        for b in balances:
            if b.asset == "USDT":
                return b.margin_balance
        return 0.0

    # =========================================================================
    # POSITIONS
    # =========================================================================

    def get_positions(self, symbol: Optional[str] = None) -> List[FuturesPosition]:
        """
        Get open positions.

        Args:
            symbol: Filter by symbol (optional)

        Returns:
            List of FuturesPosition
        """
        params = {}
        if symbol:
            params["symbol"] = symbol.upper()

        data = self._send_signed_request("GET", "/fapi/v2/positionRisk", params)

        positions = []
        for item in data:
            position_amt = float(item.get("positionAmt", 0))
            if position_amt != 0:  # Only include non-zero positions
                positions.append(FuturesPosition(
                    symbol=item.get("symbol"),
                    position_side=item.get("positionSide", "BOTH"),
                    position_amt=position_amt,
                    entry_price=float(item.get("entryPrice", 0)),
                    unrealized_pnl=float(item.get("unRealizedProfit", 0)),
                    leverage=int(item.get("leverage", 1)),
                    liquidation_price=float(item.get("liquidationPrice", 0)),
                    margin_type=item.get("marginType", "cross"),
                    mark_price=float(item.get("markPrice", 0)),
                    margin=float(item.get("isolatedMargin", 0)) or float(item.get("initialMargin", 0))
                ))

        return positions

    def get_position(self, symbol: str) -> Optional[FuturesPosition]:
        """Get specific position by symbol."""
        positions = self.get_positions(symbol)
        return positions[0] if positions else None

    # NOTE: get_open_orders() defined below (line ~987) — returns List[Dict]
    # Removed duplicate FuturesOrder version here (was dead code — Python uses last definition)

    # =========================================================================
    # ORDERS
    # =========================================================================

    def create_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        time_in_force: TimeInForce = TimeInForce.GTC,
        reduce_only: bool = False,
        position_side: PositionSide = PositionSide.BOTH,
        client_order_id: Optional[str] = None
    ) -> FuturesOrder:
        """
        Create a new futures order.

        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            side: BUY or SELL
            order_type: LIMIT, MARKET, STOP_MARKET, TAKE_PROFIT_MARKET
            quantity: Order quantity
            price: Limit price (required for LIMIT orders)
            stop_price: Stop price (for stop orders)
            time_in_force: GTC, IOC, FOK, GTX
            reduce_only: Only reduce position
            position_side: LONG, SHORT, BOTH
            client_order_id: Custom order ID

        Returns:
            FuturesOrder with order details
        """
        symbol_upper = symbol.upper()

        # SOTA (Jan 2026): Use Injected FilterService for Dynamic Precision
        # This eliminates the need to manually add each coin to a hardcoded map.
        # Falls back to heuristic logic if filter_service is not available.
        if self.filter_service and hasattr(self.filter_service, 'sanitize_quantity'):
            rounded_qty = self.filter_service.sanitize_quantity(symbol_upper, quantity)

            # For price, use sanitize_price if it's a priced order
            if price is not None and hasattr(self.filter_service, 'sanitize_price'):
                rounded_price = self.filter_service.sanitize_price(symbol_upper, price)
            else:
                rounded_price = price

            if stop_price is not None and hasattr(self.filter_service, 'sanitize_price'):
                rounded_stop = self.filter_service.sanitize_price(symbol_upper, stop_price)
            else:
                rounded_stop = stop_price

            # Get precision for string formatting from filter_service
            filters = self.filter_service.get_filters(symbol_upper)
            qty_precision = filters.qty_precision if filters else 0
            price_precision = filters.price_precision if filters else 2
        else:
            # FALLBACK: Hardcoded Precision Map (for backward compatibility)
            PRECISION = {
                'BTCUSDT': {'qty': 3, 'price': 1},
                'ETHUSDT': {'qty': 3, 'price': 2},
                'BNBUSDT': {'qty': 2, 'price': 2},
                'SOLUSDT': {'qty': 0, 'price': 2},
                'AVAXUSDT': {'qty': 0, 'price': 2},
                'TAOUSDT': {'qty': 2, 'price': 2},
                'FETUSDT': {'qty': 0, 'price': 4},
                'ONDOUSDT': {'qty': 0, 'price': 4},
                'XRPUSDT': {'qty': 1, 'price': 4},
                'PUMPUSDT': {'qty': 0, 'price': 6},
                'PIEVERSEUSDT': {'qty': 0, 'price': 6},
                'DOGEUSDT': {'qty': 0, 'price': 5},
                'SHIBUSDT': {'qty': 0, 'price': 7},
                'PEPEUSDT': {'qty': 0, 'price': 7},
                'BONKUSDT': {'qty': 0, 'price': 6},
                'GMTUSDT': {'qty': 0, 'price': 4}
            }

            if symbol_upper in PRECISION:
                prec = PRECISION[symbol_upper]
            elif price and price < 1.0:
                prec = {'qty': 0, 'price': 4}  # Meme coin profile
            elif price and price > 1000.0:
                prec = {'qty': 3, 'price': 2}  # BTC/ETH profile
            else:
                prec = {'qty': 1, 'price': 2}  # Mid-range profile

            import math
            qty_factor = 10 ** prec['qty']
            rounded_qty = math.floor(quantity * qty_factor) / qty_factor
            qty_precision = prec['qty']
            price_precision = prec['price']

            rounded_price = round(price, prec['price']) if price else None
            rounded_stop = round(stop_price, prec['price']) if stop_price else None

        params = {
            "symbol": symbol_upper,
            "side": side.value if isinstance(side, OrderSide) else side,
            "type": order_type.value if isinstance(order_type, OrderType) else order_type,
            "quantity": f"{rounded_qty:.{qty_precision}f}",
        }

        # SOTA FIX (Jan 2026): positionSide triggers Algo Order requirement for STOP_MARKET!
        # Binance migrated conditional orders to Algo Service on Dec 9, 2025.
        # For One-way Mode (BOTH), simply omit positionSide from STOP_MARKET/TAKE_PROFIT_MARKET.
        order_type_str = order_type.value if isinstance(order_type, OrderType) else str(order_type).upper()
        is_conditional = order_type_str in ('STOP_MARKET', 'TAKE_PROFIT_MARKET', 'STOP', 'TAKE_PROFIT', 'TRAILING_STOP_MARKET')
        if not is_conditional:
            params["positionSide"] = position_side.value if isinstance(position_side, PositionSide) else position_side

        if order_type == OrderType.LIMIT or order_type == "LIMIT":
            if price is None:
                raise ValueError("Price required for LIMIT orders")
            params["price"] = f"{rounded_price:.{price_precision}f}"
            params["timeInForce"] = time_in_force.value if isinstance(time_in_force, TimeInForce) else time_in_force

        if stop_price is not None:
            params["stopPrice"] = f"{rounded_stop:.{price_precision}f}"

        if reduce_only:
            params["reduceOnly"] = "true"

        if client_order_id:
            params["newClientOrderId"] = client_order_id

        self.logger.info(f"📤 Creating order: {side} {quantity} {symbol} @ {price or 'MARKET'}")

        data = self._send_signed_request("POST", "/fapi/v1/order", params)

        order = FuturesOrder(
            order_id=data.get("orderId"),
            client_order_id=data.get("clientOrderId", ""),
            symbol=data.get("symbol"),
            side=data.get("side"),
            type=data.get("type"),
            status=data.get("status"),
            price=float(data.get("price", 0)),
            quantity=float(data.get("origQty", 0)),
            executed_qty=float(data.get("executedQty", 0)),
            avg_price=float(data.get("avgPrice", 0)),
            time_in_force=data.get("timeInForce", ""),
            reduce_only=data.get("reduceOnly", False)
        )

        self.logger.info(f"✅ Order created: {order.order_id} | Status: {order.status}")
        return order

    def create_algo_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        stop_price: float,
        reduce_only: bool = True,
        close_position: bool = False
    ) -> Optional[dict]:
        """
        SOTA (Jan 2026): Create conditional orders using Algo Order API.

        Binance migrated STOP_MARKET, TAKE_PROFIT_MARKET, etc. to Algo Service
        on Dec 9, 2025. The old /fapi/v1/order endpoint returns -4120 for these.

        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            side: BUY or SELL (exit direction)
            order_type: STOP_MARKET, TAKE_PROFIT_MARKET, etc.
            quantity: Position size
            stop_price: Trigger price
            reduce_only: If True, only reduces existing position
            close_position: If True, closes entire position (ignores quantity)

        Returns:
            Order response dict or None on error
        """
        symbol_upper = symbol.upper()

        # Sanitize quantity using filter_service if available
        if self.filter_service and hasattr(self.filter_service, 'sanitize_quantity'):
            quantity = self.filter_service.sanitize_quantity(symbol_upper, quantity)
            stop_price = self.filter_service.sanitize_price(symbol_upper, stop_price)

        params = {
            "algoType": "CONDITIONAL",  # Required for STOP_MARKET
            "symbol": symbol_upper,
            "side": side.value if isinstance(side, OrderSide) else side,
            "type": order_type.value if isinstance(order_type, OrderType) else str(order_type).upper(),
            "triggerprice": str(stop_price),  # SOTA FIX: Binance requires 'triggerprice' not 'stopPrice'
            "workingType": "CONTRACT_PRICE"  # Use last price, not mark price
        }

        # closePosition=true closes entire position, cannot use with quantity/reduceOnly
        if close_position:
            params["closePosition"] = "true"
        else:
            params["quantity"] = str(quantity)
            if reduce_only:
                params["reduceOnly"] = "true"

        self.logger.info(f"📤 Creating Algo Order: {side} {quantity} {symbol} STOP@{stop_price}")

        try:
            data = self._send_signed_request("POST", "/fapi/v1/algoOrder", params)

            if data:
                algo_id = data.get("algoId") or data.get("orderId")
                self.logger.info(f"✅ Algo Order created: {symbol_upper} | ID: {algo_id}")
                return data
            return None

        except Exception as e:
            self.logger.error(f"❌ Algo Order failed: {e}")
            return None

    def cancel_algo_order(self, symbol: str, algo_id: str) -> bool:
        """
        SOTA (Jan 2026): Cancel a conditional order using Algo Order API.

        This is used to cancel backup SL on exchange when position closes
        (either via local SL hit or manual close).

        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            algo_id: Algo order ID to cancel (from create_algo_order response)

        Returns:
            True if cancelled successfully, False otherwise
        """
        symbol_upper = symbol.upper()

        params = {
            "symbol": symbol_upper,
            "algoId": str(algo_id)
        }

        self.logger.info(f"🚫 Cancelling Algo Order: {symbol_upper} | AlgoID: {algo_id}")

        try:
            data = self._send_signed_request("DELETE", "/fapi/v1/algoOrder", params)

            if data:
                self.logger.info(f"✅ Algo Order cancelled: {symbol_upper} | AlgoID: {algo_id}")
                return True
            return False

        except Exception as e:
            # Check if already cancelled or doesn't exist
            error_str = str(e)
            if "Order does not exist" in error_str or "-2011" in error_str:
                self.logger.info(f"ℹ️ Algo Order already cancelled or doesn't exist: {algo_id}")
                return True  # Treat as success - order is gone

            self.logger.error(f"❌ Cancel Algo Order failed: {e}")
            return False

    def get_open_algo_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        """
        SOTA (Jan 2026): Get open algo/conditional orders from Binance.

        Algo orders (STOP_MARKET, TAKE_PROFIT_MARKET) are separate from regular orders
        since Dec 2025 migration. Use this to display backup SL in UI.

        Args:
            symbol: Filter by symbol (optional)

        Returns:
            List of open algo orders
        """
        params = {}
        if symbol:
            params["symbol"] = symbol.upper()

        try:
            data = self._send_signed_request("GET", "/fapi/v1/openAlgoOrders", params)

            if data:
                orders = data.get("algoOrders", []) if isinstance(data, dict) else data
                self.logger.debug(f"📋 Fetched {len(orders)} open algo orders")
                return orders
            return []

        except Exception as e:
            self.logger.error(f"❌ Failed to get algo orders: {e}")
            return []

    def close_position(
        self,
        symbol: str,
        quantity: float,
        side: str = "LONG"
    ) -> FuturesOrder:
        """
        Close an open position using MARKET order with reduceOnly.

        SOTA: This is the safe way to close positions without opening new ones.

        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            quantity: Position size to close
            side: "LONG" to close long (sells), "SHORT" to close short (buys)

        Returns:
            FuturesOrder with close details
        """
        # To close LONG, we SELL. To close SHORT, we BUY.
        close_side = "SELL" if side.upper() == "LONG" else "BUY"

        self.logger.info(f"🔴 Closing {side} position: {quantity} {symbol}")

        params = {
            "symbol": symbol.upper(),
            "side": close_side,
            "type": "MARKET",
            "quantity": str(quantity),
            "reduceOnly": "true"  # Critical: prevent opening new position
        }

        data = self._send_signed_request("POST", "/fapi/v1/order", params)

        order = FuturesOrder(
            order_id=data.get("orderId"),
            client_order_id=data.get("clientOrderId", ""),
            symbol=data.get("symbol"),
            side=data.get("side"),
            type=data.get("type"),
            status=data.get("status"),
            price=float(data.get("price", 0)),
            quantity=float(data.get("origQty", 0)),
            executed_qty=float(data.get("executedQty", 0)),
            avg_price=float(data.get("avgPrice", 0)),
            time_in_force=data.get("timeInForce", ""),
            reduce_only=True
        )

        self.logger.info(f"✅ Position closed: {order.order_id} | Status: {order.status}")
        return order

    def place_bracket_orders(
        self,
        symbol: str,
        entry_side: OrderSide,
        quantity: float,
        stop_loss: float,
        take_profit: float
    ) -> Dict[str, Optional[FuturesOrder]]:
        """
        Place SL and TP orders for an open position.

        SOTA: This matches Paper Trading behavior where positions
        automatically have SL/TP monitoring.

        Args:
            symbol: Trading pair
            entry_side: Side of entry (BUY for LONG, SELL for SHORT)
            quantity: Position size
            stop_loss: Stop loss price
            take_profit: Take profit price

        Returns:
            Dict with 'sl_order' and 'tp_order' FuturesOrder objects
        """
        result = {"sl_order": None, "tp_order": None}

        # Exit side is opposite of entry
        exit_side = OrderSide.SELL if entry_side == OrderSide.BUY else OrderSide.BUY

        try:
            # Place Stop Loss (STOP_MARKET)
            if stop_loss > 0:
                sl_order = self.create_order(
                    symbol=symbol,
                    side=exit_side,
                    order_type=OrderType.STOP_MARKET,
                    quantity=quantity,
                    stop_price=stop_loss,
                    reduce_only=True
                )
                result["sl_order"] = sl_order
                self.logger.info(f"🛡️ SL order placed: {sl_order.order_id} @ {stop_loss}")

            # Place Take Profit (TAKE_PROFIT_MARKET)
            if take_profit > 0:
                tp_order = self.create_order(
                    symbol=symbol,
                    side=exit_side,
                    order_type=OrderType.TAKE_PROFIT_MARKET,
                    quantity=quantity,
                    stop_price=take_profit,
                    reduce_only=True
                )
                result["tp_order"] = tp_order
                self.logger.info(f"🎯 TP order placed: {tp_order.order_id} @ {take_profit}")

        except Exception as e:
            self.logger.error(f"Failed to place bracket orders: {e}")
            # Don't raise - return partial result

        return result

    def cancel_order(self, symbol: str, order_id: int) -> Dict:
        """
        Cancel an open order.

        Args:
            symbol: Trading pair
            order_id: Order ID to cancel

        Returns:
            Cancellation response
        """
        params = {
            "symbol": symbol.upper(),
            "orderId": order_id
        }

        self.logger.info(f"🚫 Cancelling order: {order_id}")
        data = self._send_signed_request("DELETE", "/fapi/v1/order", params)
        self.logger.info(f"✅ Order cancelled: {order_id}")
        return data

    def cancel_all_orders(self, symbol: str) -> Dict:
        """Cancel all open orders for a symbol."""
        params = {"symbol": symbol.upper()}
        return self._send_signed_request("DELETE", "/fapi/v1/allOpenOrders", params)

    def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        """Get all open orders."""
        params = {}
        if symbol:
            params["symbol"] = symbol.upper()
        return self._send_signed_request("GET", "/fapi/v1/openOrders", params)

    def get_order(self, symbol: str, order_id: int) -> Dict:
        """Get order details by ID."""
        params = {
            "symbol": symbol.upper(),
            "orderId": order_id
        }
        return self._send_signed_request("GET", "/fapi/v1/order", params)

    def get_trade_history(
        self,
        symbol: Optional[str] = None,
        limit: int = 100,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None
    ) -> List[Dict]:
        """
        Get user trade history from Binance.

        Args:
            symbol: Filter by symbol (optional)
            limit: Number of trades to return (max 1000)
            start_time: Start time in milliseconds
            end_time: End time in milliseconds

        Returns:
            List of trade records
        """
        params = {"limit": min(limit, 1000)}
        if symbol:
            params["symbol"] = symbol.upper()
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        try:
            return self._send_signed_request("GET", "/fapi/v1/userTrades", params)
        except Exception as e:
            self.logger.error(f"Failed to get trade history: {e}")
            return []

    def get_income_history(
        self,
        symbol: Optional[str] = None,
        income_type: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        Get income history (P&L, funding, etc).

        Args:
            symbol: Filter by symbol
            income_type: REALIZED_PNL, FUNDING_FEE, COMMISSION, etc
            limit: Number of records (max 1000)

        Returns:
            List of income records
        """
        params = {"limit": min(limit, 1000)}
        if symbol:
            params["symbol"] = symbol.upper()
        if income_type:
            params["incomeType"] = income_type

        try:
            return self._send_signed_request("GET", "/fapi/v1/income", params)
        except Exception as e:
            self.logger.error(f"Failed to get income history: {e}")
            return []

    # =========================================================================
    # LEVERAGE & MARGIN
    # =========================================================================

    def set_leverage(self, symbol: str, leverage: int) -> Dict:
        """
        Set leverage for a symbol.

        Args:
            symbol: Trading pair
            leverage: Leverage (1-125 depending on symbol)
        """
        params = {
            "symbol": symbol.upper(),
            "leverage": leverage
        }
        self.logger.info(f"⚙️ Setting leverage: {symbol} = {leverage}x")
        return self._send_signed_request("POST", "/fapi/v1/leverage", params)

    def set_margin_type(self, symbol: str, margin_type: str = "ISOLATED") -> Dict:
        """
        Set margin type for a symbol.

        Args:
            symbol: Trading pair
            margin_type: ISOLATED or CROSSED
        """
        params = {
            "symbol": symbol.upper(),
            "marginType": margin_type.upper()
        }
        try:
            return self._send_signed_request("POST", "/fapi/v1/marginType", params)
        except Exception as e:
            # Binance returns error if margin type already set
            if "No need to change margin type" in str(e):
                return {"msg": "Already set"}
            raise

    # =========================================================================
    # MARKET DATA (Public)
    # =========================================================================

    def get_ticker_price(self, symbol: str) -> float:
        """Get current price for symbol."""
        data = self._send_public_request("/fapi/v1/ticker/price", {"symbol": symbol.upper()})
        return float(data.get("price", 0))

    def get_book_ticker(self, symbol: str) -> tuple:
        """Get best bid/ask prices from order book.

        Returns:
            (bid_price, ask_price) tuple

        Raises:
            ValueError: If bid/ask prices are invalid (zero, negative, or inverted)
        """
        data = self._send_public_request("/fapi/v1/ticker/bookTicker", {"symbol": symbol.upper()})
        bid = float(data.get("bidPrice", 0))
        ask = float(data.get("askPrice", 0))
        if bid <= 0 or ask <= 0 or bid >= ask:
            raise ValueError(f"Invalid bookTicker for {symbol}: bid={bid}, ask={ask}")
        return bid, ask

    def get_exchange_info(self, symbol: Optional[str] = None) -> Dict:
        """Get exchange trading rules."""
        params = {}
        if symbol:
            params["symbol"] = symbol.upper()
        return self._send_public_request("/fapi/v1/exchangeInfo", params)

    def ping(self) -> bool:
        """Test connectivity."""
        try:
            self._send_public_request("/fapi/v1/ping")
            return True
        except:
            return False

    def get_server_time(self) -> int:
        """Get server time in milliseconds."""
        data = self._send_public_request("/fapi/v1/time")
        return data.get("serverTime", 0)

    # =========================================================================
    # UTILITIES
    # =========================================================================

    # NOTE: close_position method is defined at line 539 with signature:
    # close_position(self, symbol: str, quantity: float, side: str = "LONG")

    # =========================================================================
    # USER DATA STREAM (Listen Key Management)
    # =========================================================================

    def get_listen_key(self) -> str:
        """
        Get listen key for User Data Stream.

        The listen key is valid for 60 minutes. Call keep_alive_listen_key()
        every 30 minutes to extend validity.

        Returns:
            Listen key string
        """
        data = self._send_signed_request("POST", "/fapi/v1/listenKey")
        listen_key = data.get("listenKey", "")
        if listen_key:
            self.logger.info(f"🔑 Listen key obtained: {listen_key[:20]}...")
        return listen_key

    def keep_alive_listen_key(self, listen_key: str = None) -> bool:
        """
        Keep listen key alive (extend validity).

        Should be called every 30 minutes to prevent expiry.

        Args:
            listen_key: Listen key to keep alive (optional, Binance uses session)

        Returns:
            True if successful
        """
        try:
            self._send_signed_request("PUT", "/fapi/v1/listenKey")
            self.logger.debug("🔄 Listen key kept alive")
            return True
        except Exception as e:
            self.logger.error(f"Failed to keep listen key alive: {e}")
            return False

    def close_listen_key(self, listen_key: str = None) -> bool:
        """
        Close/invalidate listen key.

        Args:
            listen_key: Listen key to close (optional)

        Returns:
            True if successful
        """
        try:
            self._send_signed_request("DELETE", "/fapi/v1/listenKey")
            self.logger.info("🔒 Listen key closed")
            return True
        except Exception as e:
            self.logger.error(f"Failed to close listen key: {e}")
            return False

    # =========================================================================
    # BATCH ORDERS (Optional optimization)
    # =========================================================================

    def create_batch_orders(self, orders: List[Dict]) -> List[Dict]:
        """
        Place multiple orders in a single request.

        WARNING: NOT atomic - some orders may succeed while others fail.
        Max 5 orders per request.

        Args:
            orders: List of order parameter dicts

        Returns:
            List of order responses
        """
        import json

        if len(orders) > 5:
            raise ValueError("Maximum 5 orders per batch request")

        params = {
            "batchOrders": json.dumps(orders)
        }

        self.logger.info(f"📦 Sending batch orders: {len(orders)} orders")
        results = self._send_signed_request("POST", "/fapi/v1/batchOrders", params)

        # Log results
        for i, result in enumerate(results):
            if "orderId" in result:
                self.logger.info(f"  ✅ Order {i+1}: {result.get('orderId')}")
            else:
                self.logger.error(f"  ❌ Order {i+1} failed: {result}")

        return results

    def __repr__(self) -> str:
        mode = "TESTNET" if self.use_testnet else "PRODUCTION"
        return f"BinanceFuturesClient(mode={mode}, base_url={self.base_url})"
