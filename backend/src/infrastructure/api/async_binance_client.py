
import os
import time
import hmac
import hashlib
import logging
import asyncio
import aiohttp
from typing import Optional, Dict, Any, List
from urllib.parse import urlencode

class AsyncBinanceFuturesClient:
    """
    SOTA Async Binance Futures Client (aiohttp) - SINGLETON.

    CRITICAL FIX (Jan 2026): Uses SHARED ClientSession with high connection limits
    to enable parallel loading of 50+ symbols.

    Replaces synchronous 'requests' library to eliminate thread blocking.
    Patterns matched to Freqtrade's ccxt.async_support.
    """

    _instance: Optional['AsyncBinanceFuturesClient'] = None
    _shared_session: Optional[aiohttp.ClientSession] = None
    _shared_connector: Optional[aiohttp.TCPConnector] = None

    PRODUCTION_BASE_URL = "https://fapi.binance.com"
    TESTNET_BASE_URL = "https://testnet.binancefuture.com"

    def __new__(cls, *args, **kwargs):
        """Singleton pattern - ensures one shared session for all services."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    @classmethod
    def reset_singleton(cls):
        """
        SOTA (Jan 2026): Force reset singleton for fresh initialization.

        Call this ONCE at backend startup to ensure fresh credentials are loaded.
        This is critical when:
        - API keys have changed
        - IP whitelist has been updated
        - Backend is restarting but Python process persists (e.g., uvicorn reload)

        Usage in main.py lifespan:
            AsyncBinanceFuturesClient.reset_singleton()
        """
        import logging
        logger = logging.getLogger(__name__)

        # Close existing session if any
        if cls._shared_session and not cls._shared_session.closed:
            import asyncio
            try:
                # Try graceful close
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(cls._shared_session.close())
                else:
                    loop.run_until_complete(cls._shared_session.close())
            except Exception as e:
                logger.warning(f"Session close warning: {e}")

        # Reset all class-level state
        cls._instance = None
        cls._shared_session = None
        cls._shared_connector = None

        logger.info("🔄 AsyncBinanceFuturesClient singleton RESET - fresh init on next call")

    def __init__(self, use_testnet: Optional[bool] = None):
        # Only initialize once
        if getattr(self, '_initialized', False):
            return
        self._initialized = True

        self.logger = logging.getLogger(__name__)

        # 1. Determine Environment
        if use_testnet is not None:
            self.use_testnet = use_testnet
        else:
            env = os.getenv("ENV", "paper").lower()
            self.use_testnet = (env == "testnet")

        # 2. Key Loading with Strip (Critical Fix)
        if self.use_testnet:
            self.api_key = (os.getenv("BINANCE_TESTNET_API_KEY") or "").strip()
            self.api_secret = (os.getenv("BINANCE_TESTNET_API_SECRET") or "").strip()
            self.base_url = self.TESTNET_BASE_URL
        else:
            self.api_key = (os.getenv("BINANCE_API_KEY") or "").strip()
            self.api_secret = (os.getenv("BINANCE_API_SECRET") or "").strip()
            self.base_url = self.PRODUCTION_BASE_URL

        if not self.api_key or not self.api_secret:
            # Paper mode might not need keys, but Live/Testnet does.
            # We warn but don't crash, caller validates.
            pass

        self._time_offset = 0
        self.logger.info("🔧 AsyncBinanceFuturesClient SINGLETON initialized")

    async def _get_session(self) -> aiohttp.ClientSession:
        """
        SOTA: Returns SHARED session with optimized connection pooling.

        Key settings for 50+ parallel symbol loading:
        - limit=200: Max total connections (Binance allows many)
        - limit_per_host=100: Connections to fapi.binance.com
        - ttl_dns_cache=300: DNS caching
        """
        if AsyncBinanceFuturesClient._shared_session is None or AsyncBinanceFuturesClient._shared_session.closed:
            # Create shared connector with high limits
            AsyncBinanceFuturesClient._shared_connector = aiohttp.TCPConnector(
                limit=200,  # Total connections
                limit_per_host=100,  # Connections per host (Binance)
                ttl_dns_cache=300,  # DNS cache 5 min
                enable_cleanup_closed=True
            )

            headers = {
                "X-MBX-APIKEY": self.api_key,
                "Content-Type": "application/x-www-form-urlencoded"
            }

            timeout = aiohttp.ClientTimeout(total=30, connect=10)

            AsyncBinanceFuturesClient._shared_session = aiohttp.ClientSession(
                headers=headers,
                connector=AsyncBinanceFuturesClient._shared_connector,
                timeout=timeout
            )
            self.logger.info("🔌 Created SHARED aiohttp session (limit=200, per_host=100)")

        return AsyncBinanceFuturesClient._shared_session

    async def close(self):
        """Close the shared session (call only on shutdown)."""
        if AsyncBinanceFuturesClient._shared_session:
            await AsyncBinanceFuturesClient._shared_session.close()
            AsyncBinanceFuturesClient._shared_session = None
            self.logger.info("🔌 Closed shared aiohttp session")

    async def _sync_server_time(self):
        try:
            url = f"{self.base_url}/fapi/v1/time"
            session = await self._get_session()
            async with session.get(url) as resp:
                data = await resp.json()
                server_time = data['serverTime']
                local_time = int(time.time() * 1000)
                self._time_offset = server_time - local_time
                self.logger.info(f"⏱️ Async Time Sync: {self._time_offset}ms")
        except Exception as e:
            self.logger.warning(f"Time sync failed: {e}")

    def _get_timestamp(self) -> int:
        return int(time.time() * 1000) + self._time_offset

    def _sign(self, params: Dict[str, Any]) -> str:
        query_string = urlencode(params)
        return hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    async def _send_signed_request(self, method: str, endpoint: str, params: Dict[str, Any] = None) -> Any:
        session = await self._get_session()
        url = f"{self.base_url}{endpoint}"

        # Retry Logic
        for i in range(3):
            try:
                # Prepare Params
                current_params = params.copy() if params else {}
                current_params["timestamp"] = self._get_timestamp()
                current_params["recvWindow"] = 5000
                current_params["signature"] = self._sign(current_params)

                async with session.request(method, url, params=current_params) as response:
                    text = await response.text()

                    if response.status == 200:
                        return await response.json()

                    # Error Handling
                    if response.status == 429:
                        self.logger.warning("Rate limit (429). Sleeping 1s...")
                        await asyncio.sleep(1)
                        continue

                    if response.status == 400 and '-1021' in text:
                         # Timestamp error
                        await self._sync_server_time()
                        continue

                    response.raise_for_status()

            except Exception as e:
                if i == 2: raise
                self.logger.warning(f"Request failed: {e}. Retrying ({i+1}/3)")
                await asyncio.sleep(0.5)

    # ==========================
    # PUBLIC ENDPOINTS
    # ==========================
    async def get_klines(self, symbol: str, interval: str, limit: int = 500) -> List[Dict]:
        # SOTA HYBRID: Klines ALWAYS from LIVE (testnet has limited/stale data)
        url = f"{self.PRODUCTION_BASE_URL}/fapi/v1/klines"
        params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
        session = await self._get_session()
        async with session.get(url, params=params) as resp:
            data = await resp.json()
            # Convert to dict format to match existing system expectation if needed
            # [time, open, high, low, close, volume, ...]
            # Return raw list for processing by caller
            return data

    # ==========================
    # PRIVATE ENDPOINTS
    # ==========================
    async def get_account_info(self) -> Dict:
        return await self._send_signed_request("GET", "/fapi/v3/account")

    async def get_usdt_balance(self) -> float:
        info = await self.get_account_info()
        for asset in info.get('assets', []):
            if asset['asset'] == 'USDT':
                return float(asset['walletBalance'])
        return 0.0

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        """Get all open orders for a symbol or all symbols."""
        endpoint = "/fapi/v1/openOrders"
        params = {}
        if symbol:
            params["symbol"] = symbol.upper()
        return await self._send_signed_request("GET", endpoint, params)

    async def get_positions(self) -> List[Dict]:
        """Get all open positions (risk)."""
        endpoint = "/fapi/v2/positionRisk"
        all_positions = await self._send_signed_request("GET", endpoint)
        # Filter for relevant positions if needed (or return all)
        return all_positions

    async def create_order(self, symbol: str, side: str, type: str, quantity: float,
                          price: Optional[float] = None, stop_price: Optional[float] = None,
                          reduce_only: bool = False, time_in_force: str = "GTC") -> Dict:
        """Create a new order."""
        endpoint = "/fapi/v1/order"
        params = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": type.upper(),
            "quantity": quantity
        }
        if price:
            params["price"] = price
        if stop_price:
            params["stopPrice"] = stop_price
        if reduce_only:
            params["reduceOnly"] = "true"
        # SOTA FIX: timeInForce is ONLY for LIMIT orders, NOT for STOP_MARKET
        if time_in_force and type.upper() == "LIMIT":
            params["timeInForce"] = time_in_force

        return await self._send_signed_request("POST", endpoint, params)

    async def cancel_order(self, symbol: str, order_id: int) -> Dict:
        """Cancel a specific order."""
        endpoint = "/fapi/v1/order"
        params = {
            "symbol": symbol.upper(),
            "orderId": order_id
        }
        return await self._send_signed_request("DELETE", endpoint, params)

    async def cancel_all_orders(self, symbol: str) -> Dict:
        """Cancel all open orders for a symbol."""
        endpoint = "/fapi/v1/allOpenOrders"
        params = {
            "symbol": symbol.upper()
        }
        return await self._send_signed_request("DELETE", endpoint, params)

    async def create_batch_orders(self, batch_orders: List[Dict]) -> List[Dict]:
        """Create multiple orders in a single request."""
        import json
        endpoint = "/fapi/v1/batchOrders"
        # batchOrders param requires JSON stringified list
        params = {
            "batchOrders": json.dumps(batch_orders)
        }
        return await self._send_signed_request("POST", endpoint, params)

    async def create_algo_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        stop_price: float,
        reduce_only: bool = True,
        close_position: bool = False
    ) -> Dict:
        """
        SOTA (Jan 2026): Create conditional orders using Algo Order API.

        Binance migrated STOP_MARKET, TAKE_PROFIT_MARKET to Algo Service
        on Dec 9, 2025. The old /fapi/v1/order endpoint returns -4120.

        Args:
            symbol: Trading pair
            side: BUY or SELL (exit direction)
            order_type: STOP_MARKET, TAKE_PROFIT_MARKET, etc.
            quantity: Position size
            stop_price: Trigger price
            reduce_only: If True, only reduces existing position
            close_position: If True, closes entire position

        Returns:
            Algo order response dict
        """
        endpoint = "/fapi/v1/algoOrder"
        params = {
            "algoType": "CONDITIONAL",
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": order_type.upper(),
            "triggerprice": str(stop_price),  # SOTA FIX: Binance requires 'triggerprice' not 'stopPrice'
            "workingType": "CONTRACT_PRICE"
        }

        if close_position:
            params["closePosition"] = "true"
        else:
            params["quantity"] = str(quantity)
            if reduce_only:
                params["reduceOnly"] = "true"

        return await self._send_signed_request("POST", endpoint, params)

    async def get_open_algo_orders(self, symbol: str) -> List[Dict]:
        """
        SOTA: Get open Algo Orders (STOP_MARKET, etc.)

        Args:
            symbol: Symbol to check

        Returns:
            List of algo order dicts
        """
        # SOTA FIX (Jan 2026): Correct endpoint is /fapi/v1/openAlgoOrders (not /algoOrders)
        endpoint = "/fapi/v1/openAlgoOrders"
        params = {
            "algoType": "CONDITIONAL"
        }
        if symbol:
            params["symbol"] = symbol.upper()
        return await self._send_signed_request("GET", endpoint, params)

    async def cancel_algo_order(self, symbol: str, algo_id: int) -> Dict:
        """
        SOTA: Cancel an Algo Order by algoId.

        Args:
            symbol: Symbol
            algo_id: Algo Order ID (not standard orderId)

        Returns:
            Response dict
        """
        endpoint = "/fapi/v1/algoOrder"
        params = {
            "symbol": symbol.upper(),
            "algoId": algo_id
        }
        return await self._send_signed_request("DELETE", endpoint, params)
