"""
Application Services - Business Logic Layer

Core services for the trading system:
- RealtimeService: Orchestrates real-time data flow (import directly to avoid circular import)
- PaperTradingService: Paper trading simulation
- SignalGenerator: Trading signal generation
- Various calculators: TP, SL, Entry, Confidence

NOTE: RealtimeService is NOT exported here to avoid circular imports.
Import it directly: from src.application.services.realtime_service import RealtimeService
"""

from .paper_trading_service import PaperTradingService
from .tp_calculator import TPCalculator
from .stop_loss_calculator import StopLossCalculator
from .confidence_calculator import ConfidenceCalculator
from .smart_entry_calculator import SmartEntryCalculator
from .entry_price_calculator import EntryPriceCalculator

__all__ = [
    # NOTE: RealtimeService excluded to avoid circular import
    # Import directly: from src.application.services.realtime_service import RealtimeService
    'PaperTradingService',
    'TPCalculator',
    'StopLossCalculator',
    'ConfidenceCalculator',
    'SmartEntryCalculator',
    'EntryPriceCalculator',
]
