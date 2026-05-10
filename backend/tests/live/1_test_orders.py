"""
Test 1: Order Types Test
Tests all order types individually on Binance Futures Testnet.

Order Types:
- LIMIT (GTC) - Entry orders
- MARKET - Immediate execution
- STOP_MARKET - Stop Loss
- TAKE_PROFIT_MARKET - Take Profit
"""

from config import get_testnet_client, TradingConfig, print_separator
from src.infrastructure.api.binance_futures_client import (
    OrderSide, OrderType, TimeInForce
)


def test_limit_order(client, config):
    """Test LIMIT order (GTC) - Used for entries."""
    print_separator("TEST: LIMIT ORDER")

    # Get current price
    ticker = client.get_ticker_price(config.TEST_SYMBOL)
    current_price = float(ticker['price'])
    print(f"Current {config.TEST_SYMBOL} price: ${current_price:,.2f}")

    # Calculate limit price (0.5% below - unlikely to fill immediately)
    limit_price = round(current_price * 0.995, 1)
    quantity = round(config.TEST_SIZE_USDT / current_price, 3)

    print(f"\n📋 Order Details:")
    print(f"   Type: LIMIT (GTC)")
    print(f"   Side: BUY")
    print(f"   Price: ${limit_price:,.2f}")
    print(f"   Qty: {quantity} BTC")

    try:
        order = client.create_order(
            symbol=config.TEST_SYMBOL,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=quantity,
            price=limit_price,
            time_in_force=TimeInForce.GTC
        )
        print(f"\n✅ Order Created!")
        print(f"   Order ID: {order.order_id}")
        print(f"   Status: {order.status}")
        return order.order_id
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return None


def test_market_order(client, config):
    """Test MARKET order - Immediate execution."""
    print_separator("TEST: MARKET ORDER")

    ticker = client.get_ticker_price(config.TEST_SYMBOL)
    current_price = float(ticker['price'])
    quantity = round(config.TEST_SIZE_USDT / current_price, 3)

    print(f"\n📋 Order Details:")
    print(f"   Type: MARKET")
    print(f"   Side: BUY")
    print(f"   Qty: {quantity} BTC (~${config.TEST_SIZE_USDT})")

    confirm = input("\n⚠️ This will execute immediately. Proceed? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("❌ Cancelled")
        return None

    try:
        order = client.create_order(
            symbol=config.TEST_SYMBOL,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=quantity
        )
        print(f"\n✅ Order Filled!")
        print(f"   Order ID: {order.order_id}")
        print(f"   Avg Price: ${order.avg_price:,.2f}")
        print(f"   Executed: {order.executed_qty} BTC")
        return order.order_id
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return None


def test_stop_market_order(client, config):
    """Test STOP_MARKET order - Used for Stop Loss."""
    print_separator("TEST: STOP_MARKET ORDER (Stop Loss)")

    # First check if we have a position
    positions = client.get_positions(config.TEST_SYMBOL)
    active = [p for p in positions if abs(p.position_amt) > 0]

    if not active:
        print("⚠️ No open position. Placing a MARKET order first...")
        test_market_order(client, config)
        positions = client.get_positions(config.TEST_SYMBOL)
        active = [p for p in positions if abs(p.position_amt) > 0]

    if not active:
        print("❌ Could not open position for testing")
        return None

    pos = active[0]
    print(f"\n📈 Current Position:")
    print(f"   {pos.symbol}: {pos.position_amt} @ ${pos.entry_price:,.2f}")

    # Calculate SL price (0.5% below entry)
    sl_price = round(pos.entry_price * (1 - config.SL_PCT), 1)
    exit_side = OrderSide.SELL if pos.position_amt > 0 else OrderSide.BUY
    qty = abs(pos.position_amt)

    print(f"\n📋 Stop Loss Order:")
    print(f"   Type: STOP_MARKET")
    print(f"   Stop Price: ${sl_price:,.2f} (-{config.SL_PCT*100}%)")
    print(f"   Qty: {qty}")
    print(f"   Reduce Only: True")

    confirm = input("\nPlace Stop Loss? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("❌ Cancelled")
        return None

    try:
        order = client.create_order(
            symbol=config.TEST_SYMBOL,
            side=exit_side,
            order_type=OrderType.STOP_MARKET,
            quantity=qty,
            stop_price=sl_price,
            reduce_only=True
        )
        print(f"\n✅ Stop Loss Placed!")
        print(f"   Order ID: {order.order_id}")
        print(f"   Status: {order.status}")
        return order.order_id
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return None


def test_take_profit_order(client, config):
    """Test TAKE_PROFIT_MARKET order."""
    print_separator("TEST: TAKE_PROFIT_MARKET ORDER")

    positions = client.get_positions(config.TEST_SYMBOL)
    active = [p for p in positions if abs(p.position_amt) > 0]

    if not active:
        print("⚠️ No open position. Open one first.")
        return None

    pos = active[0]
    print(f"\n📈 Current Position:")
    print(f"   {pos.symbol}: {pos.position_amt} @ ${pos.entry_price:,.2f}")

    # Calculate TP price (2% above entry)
    tp_price = round(pos.entry_price * (1 + config.TP1_PCT), 1)
    exit_side = OrderSide.SELL if pos.position_amt > 0 else OrderSide.BUY
    qty = abs(pos.position_amt)

    print(f"\n📋 Take Profit Order:")
    print(f"   Type: TAKE_PROFIT_MARKET")
    print(f"   TP Price: ${tp_price:,.2f} (+{config.TP1_PCT*100}%)")
    print(f"   Qty: {qty}")

    confirm = input("\nPlace Take Profit? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("❌ Cancelled")
        return None

    try:
        order = client.create_order(
            symbol=config.TEST_SYMBOL,
            side=exit_side,
            order_type=OrderType.TAKE_PROFIT_MARKET,
            quantity=qty,
            stop_price=tp_price,
            reduce_only=True
        )
        print(f"\n✅ Take Profit Placed!")
        print(f"   Order ID: {order.order_id}")
        print(f"   Status: {order.status}")
        return order.order_id
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return None


def show_status(client, config):
    """Show current account status."""
    print_separator("ACCOUNT STATUS")

    balance = client.get_usdt_balance()
    print(f"\n💰 USDT Available: ${balance:,.2f}")

    print("\n📈 Positions:")
    positions = client.get_positions()
    active = [p for p in positions if abs(p.position_amt) > 0]
    if active:
        for p in active:
            print(f"   {p.symbol}: {p.position_amt} @ ${p.entry_price:,.2f} | PnL: ${p.unrealized_pnl:,.2f}")
    else:
        print("   (No positions)")

    print("\n📋 Open Orders:")
    orders = client.get_open_orders()
    if orders:
        for o in orders:
            print(f"   {o.symbol} {o.side} {o.type}: {o.quantity} @ ${o.price if o.price else 'MARKET'}")
    else:
        print("   (No open orders)")


def cleanup(client, config):
    """Cancel all orders and close positions."""
    print_separator("CLEANUP")

    # Cancel orders
    try:
        client.cancel_all_orders(config.TEST_SYMBOL)
        print("✅ Cancelled all orders")
    except Exception as e:
        print(f"⚠️ Cancel orders: {e}")

    # Close positions
    positions = client.get_positions(config.TEST_SYMBOL)
    active = [p for p in positions if abs(p.position_amt) > 0]
    for p in active:
        try:
            side = OrderSide.SELL if p.position_amt > 0 else OrderSide.BUY
            client.create_order(
                symbol=p.symbol,
                side=side,
                order_type=OrderType.MARKET,
                quantity=abs(p.position_amt),
                reduce_only=True
            )
            print(f"✅ Closed {p.symbol} position")
        except Exception as e:
            print(f"⚠️ Close position: {e}")


def main():
    """Main test menu."""
    print("\n" + "=" * 60)
    print("🧪 ORDER TYPES TEST - Binance Futures Testnet")
    print("=" * 60)

    config = TradingConfig()
    client = get_testnet_client()

    # Set leverage
    try:
        client.set_leverage(config.TEST_SYMBOL, config.DEFAULT_LEVERAGE)
        print(f"✅ Leverage: {config.DEFAULT_LEVERAGE}x")
    except Exception as e:
        print(f"⚠️ Leverage: {e}")

    while True:
        print("\n📋 Test Menu:")
        print("  1. Show Status")
        print("  2. Test LIMIT Order (Entry)")
        print("  3. Test MARKET Order")
        print("  4. Test STOP_MARKET Order (Stop Loss)")
        print("  5. Test TAKE_PROFIT_MARKET Order")
        print("  6. Cleanup (Cancel & Close All)")
        print("  0. Exit")

        choice = input("\nChoice: ").strip()

        if choice == "1":
            show_status(client, config)
        elif choice == "2":
            test_limit_order(client, config)
        elif choice == "3":
            test_market_order(client, config)
        elif choice == "4":
            test_stop_market_order(client, config)
        elif choice == "5":
            test_take_profit_order(client, config)
        elif choice == "6":
            cleanup(client, config)
        elif choice == "0":
            print("👋 Goodbye!")
            break


if __name__ == "__main__":
    main()
