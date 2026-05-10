"""
IWebSocketClient - Domain Interface

Abstract interface for WebSocket client operations.
Infrastructure layer provides concrete implementations (Binance, etc.).
"""

from abc import ABC, abstractmethod
from typing import Callable, Optional
from dataclasses import dataclass
from enum import Enum

from ..entities.candle import Candle


class ConnectionState(Enum):
    """WebSocket connection states."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


@dataclass
class ConnectionStatus:
    """WebSocket connection status."""
    is_connected: bool
    state: ConnectionState
    latency_ms: Optional[float] = None
    reconnect_count: int = 0
    last_message_time: Optional[float] = None


class IWebSocketClient(ABC):
    """
    Abstract interface for WebSocket client.

    Application layer uses this interface.
    Infrastructure layer (BinanceWebSocketClient) implements it.
    """

    @abstractmethod
    async def connect(self, symbol: str, interval: str) -> None:
        """Connect to WebSocket stream."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from WebSocket stream."""
        pass

    @abstractmethod
    def subscribe_candle(self, callback: Callable[[Candle, dict], None]) -> None:
        """Subscribe to candle updates."""
        pass

    @abstractmethod
    def get_connection_status(self) -> ConnectionStatus:
        """Get current connection status."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if connected."""
        pass
