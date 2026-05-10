"""
AlgoOrderParser - SOTA Unified Parser for Binance Order Formats

Pattern: Adapter Pattern for API Response Normalization
Handles both regular orders and algo orders from Binance Futures API.

Background (Dec 9, 2025 Migration):
- Binance migrated conditional orders (STOP_MARKET, TAKE_PROFIT_MARKET) to Algo Service
- Regular orders: /fapi/v1/openOrders with fields: type, origQty, stopPrice, orderId
- Algo orders: /fapi/v1/openAlgoOrders with fields: orderType, quantity, triggerPrice, algoId

This parser provides unified access to both formats.
"""

from dataclasses import dataclass
from typing import Optional, Union, List, Dict, Any


class AlgoOrderParser:
    """
    SOTA: Unified parser for Binance order formats.

    Handles both:
    - Regular orders: type, origQty, stopPrice, orderId
    - Algo orders: orderType, quantity, triggerPrice, algoId

    Usage:
        order = {"orderType": "STOP_MARKET", "quantity": "0.001", "triggerPrice": "40000"}
        order_type = AlgoOrderParser.get_order_type(order)  # "STOP_MARKET"
        qty = AlgoOrderParser.get_quantity(order)  # 0.001
        price = AlgoOrderParser.get_trigger_price(order)  # 40000.0
    """

    # Order types that indicate Stop Loss
    SL_ORDER_TYPES = ('STOP_MARKET', 'STOP')

    # Order types that indicate Take Profit
    TP_ORDER_TYPES = ('TAKE_PROFIT_MARKET', 'TAKE_PROFIT')

    @staticmethod
    def get_order_type(order: Dict[str, Any]) -> str:
        """
        Get order type from either regular or algo order format.

        Regular orders use 'type', algo orders use 'orderType'.

        Args:
            order: Order dict from Binance API

        Returns:
            Order type string (e.g., 'STOP_MARKET', 'LIMIT', etc.)
        """
        return order.get('type') or order.get('orderType', '')

    @staticmethod
    def get_quantity(order: Dict[str, Any]) -> float:
        """
        Get quantity from either regular or algo order format.

        Regular orders use 'origQty', algo orders use 'quantity'.

        Args:
            order: Order dict from Binance API

        Returns:
            Order quantity as float
        """
        qty_str = order.get('origQty') or order.get('quantity', '0')
        try:
            return float(qty_str)
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def get_trigger_price(order: Dict[str, Any]) -> float:
        """
        Get trigger/stop price from either regular or algo order format.

        Regular orders use 'stopPrice', algo orders use 'triggerPrice'.

        Args:
            order: Order dict from Binance API

        Returns:
            Trigger price as float
        """
        price_str = order.get('stopPrice') or order.get('triggerPrice', '0')
        try:
            return float(price_str)
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def get_order_id(order: Dict[str, Any]) -> str:
        """
        Get order ID from either regular or algo order format.

        Regular orders use 'orderId', algo orders use 'algoId'.

        Args:
            order: Order dict from Binance API

        Returns:
            Order ID as string
        """
        order_id = order.get('orderId') or order.get('algoId', '')
        return str(order_id) if order_id else ''

    @staticmethod
    def get_symbol(order: Dict[str, Any]) -> str:
        """
        Get symbol from order.

        Args:
            order: Order dict from Binance API

        Returns:
            Symbol string (e.g., 'BTCUSDT')
        """
        return order.get('symbol', '')

    @staticmethod
    def get_side(order: Dict[str, Any]) -> str:
        """
        Get order side (BUY/SELL).

        Args:
            order: Order dict from Binance API

        Returns:
            Side string ('BUY' or 'SELL')
        """
        return order.get('side', '')

    @staticmethod
    def is_stop_loss(order: Dict[str, Any]) -> bool:
        """
        Check if order is a stop loss (STOP_MARKET or STOP).

        Args:
            order: Order dict from Binance API

        Returns:
            True if order is a stop loss type
        """
        order_type = AlgoOrderParser.get_order_type(order)
        return order_type in AlgoOrderParser.SL_ORDER_TYPES

    @staticmethod
    def is_take_profit(order: Dict[str, Any]) -> bool:
        """
        Check if order is a take profit (TAKE_PROFIT_MARKET or TAKE_PROFIT).

        Args:
            order: Order dict from Binance API

        Returns:
            True if order is a take profit type
        """
        order_type = AlgoOrderParser.get_order_type(order)
        return order_type in AlgoOrderParser.TP_ORDER_TYPES

    @staticmethod
    def is_reduce_only(order: Dict[str, Any]) -> bool:
        """
        Check if order is reduce-only.

        Handles both boolean and string formats from Binance API.
        Algo orders may return 'reduceOnly' as string 'true'/'false'.

        Args:
            order: Order dict from Binance API

        Returns:
            True if order is reduce-only
        """
        reduce = order.get('reduceOnly', False)
        if isinstance(reduce, str):
            return reduce.lower() == 'true'
        return bool(reduce)

    @staticmethod
    def is_algo_order(order: Dict[str, Any]) -> bool:
        """
        Check if order is from Algo Order API.

        Algo orders have 'algoId' field, regular orders have 'orderId'.

        Args:
            order: Order dict from Binance API

        Returns:
            True if order is from Algo Order API
        """
        return 'algoId' in order

    @staticmethod
    def get_status(order: Dict[str, Any]) -> str:
        """
        Get order status.

        Regular orders use 'status', algo orders use 'algoStatus'.

        Args:
            order: Order dict from Binance API

        Returns:
            Status string (e.g., 'NEW', 'WORKING', 'FILLED')
        """
        return order.get('status') or order.get('algoStatus', '')

    @staticmethod
    def filter_sl_orders(orders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filter orders to get only stop loss orders.

        Args:
            orders: List of order dicts

        Returns:
            List of stop loss orders
        """
        return [o for o in orders if AlgoOrderParser.is_stop_loss(o)]

    @staticmethod
    def filter_tp_orders(orders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filter orders to get only take profit orders.

        Args:
            orders: List of order dicts

        Returns:
            List of take profit orders
        """
        return [o for o in orders if AlgoOrderParser.is_take_profit(o)]

    @staticmethod
    def get_total_sl_quantity(orders: List[Dict[str, Any]]) -> float:
        """
        Calculate total quantity covered by stop loss orders.

        Args:
            orders: List of order dicts

        Returns:
            Total SL quantity
        """
        sl_orders = AlgoOrderParser.filter_sl_orders(orders)
        return sum(AlgoOrderParser.get_quantity(o) for o in sl_orders)

    @staticmethod
    def filter_by_symbol(orders: List[Dict[str, Any]], symbol: str) -> List[Dict[str, Any]]:
        """
        Filter orders by symbol.

        Args:
            orders: List of order dicts
            symbol: Symbol to filter by (e.g., 'BTCUSDT')

        Returns:
            List of orders for the specified symbol
        """
        symbol_upper = symbol.upper()
        return [o for o in orders if AlgoOrderParser.get_symbol(o).upper() == symbol_upper]


@dataclass
class UnifiedOrder:
    """
    Normalized order representation for internal use.

    Provides a consistent interface regardless of whether the order
    came from regular or algo order API.
    """
    order_id: str
    symbol: str
    order_type: str  # STOP_MARKET, TAKE_PROFIT_MARKET, LIMIT, etc.
    side: str        # BUY, SELL
    quantity: float
    trigger_price: float
    reduce_only: bool
    is_algo: bool    # True if from algo API
    status: str      # NEW, WORKING, FILLED, etc.

    @classmethod
    def from_dict(cls, order: Dict[str, Any]) -> 'UnifiedOrder':
        """
        Create UnifiedOrder from either regular or algo order dict.

        Args:
            order: Order dict from Binance API

        Returns:
            UnifiedOrder instance
        """
        return cls(
            order_id=AlgoOrderParser.get_order_id(order),
            symbol=AlgoOrderParser.get_symbol(order),
            order_type=AlgoOrderParser.get_order_type(order),
            side=AlgoOrderParser.get_side(order),
            quantity=AlgoOrderParser.get_quantity(order),
            trigger_price=AlgoOrderParser.get_trigger_price(order),
            reduce_only=AlgoOrderParser.is_reduce_only(order),
            is_algo=AlgoOrderParser.is_algo_order(order),
            status=AlgoOrderParser.get_status(order)
        )

    def is_stop_loss(self) -> bool:
        """Check if this order is a stop loss."""
        return self.order_type in AlgoOrderParser.SL_ORDER_TYPES

    def is_take_profit(self) -> bool:
        """Check if this order is a take profit."""
        return self.order_type in AlgoOrderParser.TP_ORDER_TYPES
