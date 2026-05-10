"""
Client Subscription Manager for Multi-Position Realtime Prices

**Feature: multi-position-realtime-prices**
**Validates: Requirements 3.1, 3.2, 3.4**

Manages per-client WebSocket subscriptions with:
- Full mode: Complete candle data + indicators (for active chart symbol)
- Price-only mode: Lightweight price updates (for portfolio positions)
- Throttling: Max 2 updates/second per symbol in price_only mode

Design Pattern: Subscription Manager with Throttling
- Tracks which symbols each client wants and in which mode
- Prevents bandwidth waste by throttling price_only updates
- Backward compatible: clients without priceOnly field work as before
"""

import asyncio
import logging
import time
from typing import Dict, List, Set, Optional, Any
from dataclasses import dataclass, field
from enum import Enum


logger = logging.getLogger(__name__)


class SubscriptionMode(Enum):
    """Subscription modes for symbols."""
    FULL = "full"           # Full candle data + indicators
    PRICE_ONLY = "price_only"  # Lightweight price updates only


@dataclass
class ClientSubscription:
    """Tracks a single client's subscriptions."""
    client_id: str
    # Symbols in full mode (receive candles + indicators)
    full_symbols: Set[str] = field(default_factory=set)
    # Symbols in price_only mode (receive only price updates)
    price_only_symbols: Set[str] = field(default_factory=set)
    # Last price update time per symbol (for throttling)
    last_price_update: Dict[str, float] = field(default_factory=dict)

    def get_all_symbols(self) -> Set[str]:
        """Get all subscribed symbols (both modes)."""
        return self.full_symbols | self.price_only_symbols

    def get_mode(self, symbol: str) -> Optional[SubscriptionMode]:
        """Get subscription mode for a symbol."""
        symbol_lower = symbol.lower()
        if symbol_lower in self.full_symbols:
            return SubscriptionMode.FULL
        if symbol_lower in self.price_only_symbols:
            return SubscriptionMode.PRICE_ONLY
        return None

    def is_subscribed(self, symbol: str) -> bool:
        """Check if subscribed to symbol in any mode."""
        return symbol.lower() in self.get_all_symbols()


class ClientSubscriptionManager:
    """
    Manages per-client WebSocket subscriptions.

    Features:
    - Track subscriptions per client (full mode vs price_only mode)
    - Throttling for price_only updates (500ms = max 2 updates/sec)
    - Thread-safe operations with asyncio lock
    - Backward compatible with existing subscribe messages

    Message Format (Extended):
    {
        "type": "subscribe",
        "symbols": ["btcusdt"],           # Full mode (candles + indicators)
        "priceOnly": ["ethusdt", "solusdt"]  # Price-only mode (lightweight)
    }

    Backward Compatible Format:
    {
        "type": "subscribe",
        "symbol": "btcusdt"    # Single symbol, full mode
    }
    or
    {
        "type": "subscribe",
        "symbols": ["btcusdt"]  # Multiple symbols, all full mode
    }
    """

    # Throttle interval in seconds (500ms = max 2 updates/sec per symbol)
    THROTTLE_INTERVAL = 0.5

    def __init__(self):
        # client_id -> ClientSubscription
        self._subscriptions: Dict[str, ClientSubscription] = {}
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()
        # Statistics
        self._total_updates = 0
        self._throttled_updates = 0

        logger.info("ClientSubscriptionManager initialized")

    async def update_subscription(self, client_id: str, message: dict) -> ClientSubscription:
        """
        Handle subscribe message from client.

        Supports both new multi-mode format and legacy format.

        Args:
            client_id: Client identifier
            message: Subscribe message dict

        Returns:
            Updated ClientSubscription

        Message formats supported:
        1. New format: { symbols: ['btcusdt'], priceOnly: ['ethusdt'] }
        2. Legacy: { symbol: 'btcusdt' }
        3. Legacy: { symbols: ['btcusdt', 'ethusdt'] }
        """
        async with self._lock:
            # Get or create subscription
            if client_id not in self._subscriptions:
                self._subscriptions[client_id] = ClientSubscription(client_id=client_id)

            sub = self._subscriptions[client_id]

            # Parse message - support multiple formats
            full_symbols: List[str] = []
            price_only_symbols: List[str] = []

            # New format: symbols + priceOnly
            if 'priceOnly' in message:
                # New multi-mode format
                full_symbols = message.get('symbols', [])
                price_only_symbols = message.get('priceOnly', [])

                # Handle single symbol in symbols field
                if isinstance(full_symbols, str):
                    full_symbols = [full_symbols]
                if isinstance(price_only_symbols, str):
                    price_only_symbols = [price_only_symbols]

            elif 'symbols' in message:
                # Legacy format: all symbols are full mode
                full_symbols = message.get('symbols', [])
                if isinstance(full_symbols, str):
                    full_symbols = [full_symbols]

            elif 'symbol' in message:
                # Legacy single symbol format
                full_symbols = [message.get('symbol')]

            # Normalize to lowercase
            full_symbols = [s.lower() for s in full_symbols if s]
            price_only_symbols = [s.lower() for s in price_only_symbols if s]

            # Remove duplicates: if symbol is in both, prefer full mode
            price_only_symbols = [s for s in price_only_symbols if s not in full_symbols]

            # Update subscription
            sub.full_symbols = set(full_symbols)
            sub.price_only_symbols = set(price_only_symbols)

            logger.info(f"📋 Subscription updated for {client_id}:")
            logger.info(f"   Full mode: {list(sub.full_symbols)}")
            logger.info(f"   Price-only: {list(sub.price_only_symbols)}")

            self._total_updates += 1

            return sub

    async def remove_client(self, client_id: str) -> None:
        """
        Remove client's subscriptions on disconnect.

        Args:
            client_id: Client to remove
        """
        async with self._lock:
            if client_id in self._subscriptions:
                del self._subscriptions[client_id]
                logger.debug(f"Removed subscriptions for {client_id}")

    def get_subscription(self, client_id: str) -> Optional[ClientSubscription]:
        """
        Get client's current subscription.

        Args:
            client_id: Client identifier

        Returns:
            ClientSubscription or None if not found
        """
        return self._subscriptions.get(client_id)

    def should_send_candle(self, client_id: str, symbol: str) -> bool:
        """
        Check if client should receive candle data for symbol.

        Only clients subscribed in FULL mode receive candle data.

        Args:
            client_id: Client identifier
            symbol: Symbol to check

        Returns:
            True if client should receive candle data
        """
        sub = self._subscriptions.get(client_id)
        if not sub:
            return False
        return sub.get_mode(symbol) == SubscriptionMode.FULL

    def should_send_price_update(self, client_id: str, symbol: str) -> bool:
        """
        Check if client should receive price update for symbol.

        Clients in PRICE_ONLY mode receive price updates (with throttling).
        Clients in FULL mode also receive price updates (no throttling needed,
        they get price from candle data).

        Args:
            client_id: Client identifier
            symbol: Symbol to check

        Returns:
            True if client should receive price update
        """
        sub = self._subscriptions.get(client_id)
        if not sub:
            return False
        return sub.is_subscribed(symbol)

    def should_throttle(self, client_id: str, symbol: str) -> bool:
        """
        Check if price_only update should be throttled.

        Throttling only applies to PRICE_ONLY mode.
        FULL mode clients get price from candle data, no throttling needed.

        Args:
            client_id: Client identifier
            symbol: Symbol to check

        Returns:
            True if update should be throttled (skipped)
        """
        sub = self._subscriptions.get(client_id)
        if not sub:
            return True  # No subscription = throttle

        symbol_lower = symbol.lower()

        # Only throttle price_only mode
        if sub.get_mode(symbol_lower) != SubscriptionMode.PRICE_ONLY:
            return False

        # Check throttle timing
        current_time = time.time()
        last_update = sub.last_price_update.get(symbol_lower, 0)

        if current_time - last_update < self.THROTTLE_INTERVAL:
            self._throttled_updates += 1
            return True

        return False

    def record_price_update(self, client_id: str, symbol: str) -> None:
        """
        Record that a price update was sent (for throttling).

        Args:
            client_id: Client identifier
            symbol: Symbol that was updated
        """
        sub = self._subscriptions.get(client_id)
        if sub:
            sub.last_price_update[symbol.lower()] = time.time()

    def get_clients_for_symbol(self, symbol: str, mode: Optional[SubscriptionMode] = None) -> List[str]:
        """
        Get list of client IDs subscribed to a symbol.

        Args:
            symbol: Symbol to check
            mode: Optional filter by subscription mode

        Returns:
            List of client IDs
        """
        symbol_lower = symbol.lower()
        clients = []

        for client_id, sub in self._subscriptions.items():
            if mode is None:
                if sub.is_subscribed(symbol_lower):
                    clients.append(client_id)
            elif mode == SubscriptionMode.FULL:
                if symbol_lower in sub.full_symbols:
                    clients.append(client_id)
            elif mode == SubscriptionMode.PRICE_ONLY:
                if symbol_lower in sub.price_only_symbols:
                    clients.append(client_id)

        return clients

    def get_all_subscribed_symbols(self) -> Set[str]:
        """
        Get all symbols that have at least one subscriber.

        Returns:
            Set of all subscribed symbols
        """
        all_symbols: Set[str] = set()
        for sub in self._subscriptions.values():
            all_symbols |= sub.get_all_symbols()
        return all_symbols

    def get_statistics(self) -> Dict[str, Any]:
        """Get manager statistics."""
        total_full = sum(len(s.full_symbols) for s in self._subscriptions.values())
        total_price_only = sum(len(s.price_only_symbols) for s in self._subscriptions.values())

        return {
            'total_clients': len(self._subscriptions),
            'total_full_subscriptions': total_full,
            'total_price_only_subscriptions': total_price_only,
            'total_updates': self._total_updates,
            'throttled_updates': self._throttled_updates,
            'throttle_rate': f"{(self._throttled_updates / max(1, self._total_updates)) * 100:.1f}%",
            'all_symbols': list(self.get_all_subscribed_symbols())
        }


# Global singleton instance
_subscription_manager_instance: Optional[ClientSubscriptionManager] = None


def get_subscription_manager() -> ClientSubscriptionManager:
    """Get or create the global ClientSubscriptionManager instance."""
    global _subscription_manager_instance
    if _subscription_manager_instance is None:
        _subscription_manager_instance = ClientSubscriptionManager()
    return _subscription_manager_instance
