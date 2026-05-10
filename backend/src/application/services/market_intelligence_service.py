import json
import os
import logging
import math
from typing import Tuple

class MarketIntelligenceService:
    def __init__(self, data_path: str = "backend/data/market_intelligence.json"):
        self.logger = logging.getLogger(__name__)
        # Fix path relative to execution
        if not os.path.exists(data_path):
            # Try absolute path fallback or relative to script
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            data_path = os.path.join(base_dir, "data", "market_intelligence.json")

        self.data_path = data_path
        self._data = {}
        self.reload_data()

    def reload_data(self):
        if os.path.exists(self.data_path):
            with open(self.data_path, 'r') as f:
                self._data = json.load(f)
        else:
            print(f"⚠️ Market Intelligence file not found at {self.data_path}")

    def sanitize_order(self, symbol: str, price: float, quantity: float) -> Tuple[float, float]:
        info = self._data.get(symbol, {}).get("rules", {})
        if not info:
            return price, quantity

        # 1. Round Quantity (Step Size)
        step_size = info.get("step_size", 0)
        precision_qty = info.get("qty_precision", 0)

        if step_size > 0:
            sanitized_qty = (quantity // step_size) * step_size
            sanitized_qty = float(f"{sanitized_qty:.{precision_qty}f}")
        else:
            sanitized_qty = quantity

        # 2. Round Price (Tick Size)
        tick_size = info.get("tick_size", 0)
        precision_price = info.get("price_precision", 0)

        if tick_size > 0:
            sanitized_price = round(price / tick_size) * tick_size
            sanitized_price = float(f"{sanitized_price:.{precision_price}f}")
        else:
            sanitized_price = price

        return sanitized_price, sanitized_qty
