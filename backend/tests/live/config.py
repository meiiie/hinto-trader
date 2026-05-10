"""
Live Trading Test Configuration
Shared settings matching backtest parameters.
"""

import os
import sys

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
load_dotenv()


# =============================================================================
# TRADING PARAMETERS (Match Backtest)
# =============================================================================

class TradingConfig:
    """Configuration matching backtest ExecutionSimulator."""

    # Fees (Binance Futures VIP 0)
    MAKER_FEE_PCT = 0.02   # 0.02% for limit orders
    TAKER_FEE_PCT = 0.05   # 0.05% for market/SL/TP

    # Position Sizing
    RISK_PER_TRADE = 0.01  # 1% of balance per trade
    MAX_ORDER_VALUE = 50000.0  # Tier 1 cap

    # Leverage
    DEFAULT_LEVERAGE = 10
    MAX_LEVERAGE = 20

    # Entry Logic (Liquidity Sniper)
    ENTRY_OFFSET_PCT = 0.001  # 0.1% below swing low for BUY

    # Stop Loss
    SL_PCT = 0.005  # 0.5% from entry

    # Take Profit
    TP1_PCT = 0.02  # 2% from entry (4:1 R:R)
    TP1_CLOSE_PCT = 0.60  # Close 60% at TP1

    # Breakeven
    BREAKEVEN_TRIGGER_R = 1.5  # Move to BE at 1.5R profit
    BREAKEVEN_BUFFER_PCT = 0.0005  # 0.05% buffer above entry

    # Trailing Stop
    TRAILING_STOP_ATR_MULT = 4.0  # ATR × 4

    # Risk Management
    MAX_POSITIONS = 3
    MAINTENANCE_MARGIN_RATE = 0.004  # 0.4%

    # Testnet Config
    TEST_SYMBOL = "BTCUSDT"
    TEST_SIZE_USDT = 100.0  # Small test size


# =============================================================================
# API CLIENT FACTORY
# =============================================================================

def get_testnet_client():
    """Get BinanceFuturesClient configured for testnet."""
    from src.infrastructure.api.binance_futures_client import BinanceFuturesClient

    return BinanceFuturesClient(
        api_key=os.getenv("BINANCE_TESTNET_API_KEY"),
        api_secret=os.getenv("BINANCE_TESTNET_API_SECRET"),
        use_testnet=True
    )


def get_production_client():
    """Get BinanceFuturesClient configured for production."""
    from src.infrastructure.api.binance_futures_client import BinanceFuturesClient

    return BinanceFuturesClient(
        api_key=os.getenv("BINANCE_API_KEY"),
        api_secret=os.getenv("BINANCE_API_SECRET"),
        use_testnet=False
    )


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def calculate_entry_sl_tp(current_price: float, side: str, config: TradingConfig = None):
    """Calculate entry, SL, TP prices matching backtest logic."""
    config = config or TradingConfig()

    # BTCUSDT tick size = 0.10, so round to 1 decimal place
    if side == "BUY":
        entry = round(current_price * (1 - config.ENTRY_OFFSET_PCT), 1)
        sl = round(entry * (1 - config.SL_PCT), 1)
        tp1 = round(entry * (1 + config.TP1_PCT), 1)
    else:
        entry = round(current_price * (1 + config.ENTRY_OFFSET_PCT), 1)
        sl = round(entry * (1 + config.SL_PCT), 1)
        tp1 = round(entry * (1 - config.TP1_PCT), 1)

    return {
        'entry': entry,
        'stop_loss': sl,
        'take_profit_1': tp1,
        'risk_reward': abs(tp1 - entry) / abs(entry - sl) if entry != sl else 0
    }


def calculate_position_size(balance: float, entry_price: float,
                            stop_loss: float, config: TradingConfig = None):
    """Calculate position size matching backtest risk management."""
    config = config or TradingConfig()

    # Risk amount = balance × risk_per_trade
    risk_amount = balance * config.RISK_PER_TRADE

    # Risk per unit = abs(entry - SL)
    risk_per_unit = abs(entry_price - stop_loss)

    if risk_per_unit <= 0:
        return 0.0

    # Raw size
    raw_size = risk_amount / risk_per_unit

    # Apply leverage
    notional = raw_size * entry_price
    leveraged_notional = min(notional, balance * config.DEFAULT_LEVERAGE)
    leveraged_notional = min(leveraged_notional, config.MAX_ORDER_VALUE)

    # Final size
    size = leveraged_notional / entry_price

    return round(size, 3)


def print_separator(title: str = ""):
    """Print formatted separator."""
    print("\n" + "=" * 60)
    if title:
        print(f"📊 {title}")
        print("=" * 60)
