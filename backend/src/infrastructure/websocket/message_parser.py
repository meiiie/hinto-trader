"""
Message Parser - Infrastructure Layer

Parses Binance WebSocket messages and converts them to domain entities.
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional
import logging

from ...domain.entities.candle import Candle


class BinanceMessageParser:
    """
    Parser for Binance WebSocket kline/candle messages.

    Converts raw JSON messages from Binance WebSocket API
    into domain Candle entities.
    """

    def __init__(self):
        """Initialize message parser"""
        self.logger = logging.getLogger(__name__)

    def parse_kline_message(self, message: Dict[str, Any]) -> Optional[Candle]:
        """
        Parse Binance kline message to Candle entity.

        Binance kline message format:
        {
          "e": "kline",
          "E": 1638747660000,
          "s": "BTCUSDT",
          "k": {
            "t": 1638747600000,  # Kline start time
            "T": 1638747659999,  # Kline close time
            "s": "BTCUSDT",
            "i": "1m",
            "o": "50000.00",     # Open price
            "c": "50100.00",     # Close price
            "h": "50200.00",     # High price
            "l": "49900.00",     # Low price
            "v": "100.5",        # Volume
            "x": false           # Is candle closed?
          }
        }

        Args:
            message: Raw message dict from WebSocket

        Returns:
            Candle entity if parsing successful, None otherwise
        """
        try:
            # Validate message structure
            if not self._validate_message(message):
                return None

            # Extract kline data
            kline = message.get('k', {})

            # SOTA FIX: Use timezone-aware datetime for correct .timestamp() conversion
            timestamp_ms = kline.get('t')
            timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)

            # Parse OHLCV data
            open_price = float(kline.get('o', 0))
            high_price = float(kline.get('h', 0))
            low_price = float(kline.get('l', 0))
            close_price = float(kline.get('c', 0))
            volume = float(kline.get('v', 0))

            # Check if candle is closed
            is_closed = kline.get('x', False)

            # Create Candle entity
            candle = Candle(
                timestamp=timestamp,
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=volume
            )

            self.logger.debug(
                f"Parsed candle: {timestamp.strftime('%H:%M:%S')} "
                f"O:{open_price:.2f} H:{high_price:.2f} "
                f"L:{low_price:.2f} C:{close_price:.2f} "
                f"V:{volume:.2f} Closed:{is_closed}"
            )

            return candle

        except ValueError as e:
            self.logger.error(f"Validation error parsing kline: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Error parsing kline message: {e}")
            return None


    def _validate_message(self, message: Dict[str, Any]) -> bool:
        """
        Validate Binance WebSocket message structure.

        Args:
            message: Raw message dict

        Returns:
            True if valid, False otherwise
        """
        # Check if it's a kline event
        if message.get('e') != 'kline':
            self.logger.warning(f"Not a kline message: {message.get('e')}")
            return False

        # Check if kline data exists
        if 'k' not in message:
            self.logger.error("Missing 'k' (kline data) in message")
            return False

        kline = message['k']

        # Check required fields
        required_fields = ['t', 'o', 'h', 'l', 'c', 'v']
        missing_fields = [field for field in required_fields if field not in kline]

        if missing_fields:
            self.logger.error(f"Missing required fields: {missing_fields}")
            return False

        return True

    def extract_metadata(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract metadata from kline message.

        Args:
            message: Raw message dict

        Returns:
            Dict with metadata (symbol, interval, is_closed, etc.)
        """
        kline = message.get('k', {})

        return {
            'event_type': message.get('e'),
            'event_time': datetime.fromtimestamp(message.get('E', 0) / 1000, tz=timezone.utc),
            'symbol': kline.get('s'),
            'interval': kline.get('i'),
            'is_closed': kline.get('x', False),
            'first_trade_id': kline.get('f'),
            'last_trade_id': kline.get('L'),
            'number_of_trades': kline.get('n', 0)
        }

    def is_candle_closed(self, message: Dict[str, Any]) -> bool:
        """
        Check if the candle in the message is closed.

        Args:
            message: Raw message dict

        Returns:
            True if candle is closed, False otherwise
        """
        kline = message.get('k', {})
        return kline.get('x', False)
