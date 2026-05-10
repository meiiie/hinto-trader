"""
Test 2: Full Trade Cycle
End-to-end test matching backtest execution flow.

Flow:
1. Calculate Entry/SL/TP (matching backtest)
2. Place LIMIT entry order
3. Wait for fill
4. Place bracket orders (SL + TP)
5. Monitor position
6. Handle TP1 hit → Move to Breakeven
"""

import time
from config import (
    get_testnet_client,
    TradingConfig,
    calculate_entry_sl_tp,
    calculate_position_size,
    print_separator
)
from src.infrastructure.api.binance_futures_client import (
    OrderSide, OrderType, TimeInForce
)


class FullTradeTest:
    """Simulates complete trade cycle matching backtest."""

    def __init__(self):
        self.config = TradingConfig()
        self.client = get_testnet_client()
        self.symbol = self.config.TEST_SYMBOL
        self.active_orders = {}

    def setup(self):
        """Initialize trading setup."""
        print_separator("SETUP")

        # Set leverage
        try:
            self.client.set_leverage(self.symbol, self.config.DEFAULT_LEVERAGE)
            print(f"✅ Leverage: {self.config.DEFAULT_LEVERAGE}x")
        except Exception as e:
            print(f"⚠️ Leverage: {e}")

        # Set margin type to ISOLATED
        try:
            self.client.set_margin_type(self.symbol, "ISOLATED")
            print("✅ Margin: ISOLATED")
        except Exception as e:
            print(f"⚠️ Margin type: {e}")

        # Show balance
        balance = self.client.get_usdt_balance()
        print(f"💰 Available Balance: ${balance:,.2f}")

        return balance

    def calculate_trade_params(self, side: str = "BUY"):
        """Calculate trade parameters matching backtest logic."""
        print_separator("TRADE CALCULATION")

        # Get current price
        current_price = self.client.get_ticker_price(self.symbol)
        print(f"📈 Current {self.symbol} Price: ${current_price:,.2f}")

        # Calculate entry, SL, TP
        prices = calculate_entry_sl_tp(current_price, side, self.config)
        print(f"\n📋 Trade Plan ({side}):")
        print(f"   Entry: ${prices['entry']:,.2f}")
        print(f"   Stop Loss: ${prices['stop_loss']:,.2f} ({self.config.SL_PCT*100}%)")
        print(f"   Take Profit: ${prices['take_profit_1']:,.2f} ({self.config.TP1_PCT*100}%)")
        print(f"   R:R Ratio: {prices['risk_reward']:.1f}:1")

        # Calculate position size
        balance = self.client.get_usdt_balance()
        size = calculate_position_size(
            balance,
            prices['entry'],
            prices['stop_loss'],
            self.config
        )

        notional = size * prices['entry']
        print(f"\n💰 Position Sizing:")
        print(f"   Balance: ${balance:,.2f}")
        print(f"   Risk: {self.config.RISK_PER_TRADE*100}% = ${balance * self.config.RISK_PER_TRADE:.2f}")
        print(f"   Size: {size} BTC")
        print(f"   Notional: ${notional:,.2f}")
        print(f"   Leverage Used: {notional/balance:.1f}x")

        return {
            **prices,
            'size': size,
            'notional': notional,
            'side': side
        }

    def place_entry_order(self, params):
        """Place limit entry order."""
        print_separator("PLACING ENTRY ORDER")

        side = OrderSide.BUY if params['side'] == "BUY" else OrderSide.SELL

        print(f"📤 Entry Order:")
        print(f"   Type: LIMIT (GTC)")
        print(f"   Side: {params['side']}")
        print(f"   Price: ${params['entry']:,.2f}")
        print(f"   Qty: {params['size']} BTC")

        try:
            order = self.client.create_order(
                symbol=self.symbol,
                side=side,
                order_type=OrderType.LIMIT,
                quantity=params['size'],
                price=params['entry'],
                time_in_force=TimeInForce.GTC
            )
            self.active_orders['entry'] = order.order_id
            print(f"\n✅ Entry Order Placed!")
            print(f"   Order ID: {order.order_id}")
            print(f"   Status: {order.status}")
            return order
        except Exception as e:
            print(f"\n❌ Error: {e}")
            return None

    def wait_for_fill(self, order_id: int, timeout: int = 300):
        """Wait for order to fill."""
        print_separator("WAITING FOR FILL")
        print(f"⏳ Waiting up to {timeout}s for entry fill...")

        start = time.time()
        while time.time() - start < timeout:
            try:
                order = self.client.get_order(self.symbol, order_id)
                if order.status == "FILLED":
                    print(f"\n✅ Order Filled!")
                    print(f"   Avg Price: ${order.avg_price:,.2f}")
                    print(f"   Executed: {order.executed_qty}")
                    return order
                elif order.status in ["CANCELED", "EXPIRED", "REJECTED"]:
                    print(f"\n❌ Order {order.status}")
                    return None

                # Status update
                elapsed = int(time.time() - start)
                print(f"   [{elapsed}s] Status: {order.status}", end="\r")
                time.sleep(5)

            except Exception as e:
                print(f"\n⚠️ Check error: {e}")
                time.sleep(5)

        print(f"\n⏰ Timeout - Order not filled")
        return None

    def place_bracket_orders(self, params, filled_qty: float):
        """Place SL and TP orders after entry fill."""
        print_separator("PLACING BRACKET ORDERS")

        exit_side = OrderSide.SELL if params['side'] == "BUY" else OrderSide.BUY

        # TP1 quantity (60%)
        tp1_qty = round(filled_qty * self.config.TP1_CLOSE_PCT, 3)
        # Remaining quantity for trailing (40%)
        trailing_qty = round(filled_qty - tp1_qty, 3)

        print(f"📋 Bracket Orders:")
        print(f"   TP1: {tp1_qty} BTC @ ${params['take_profit_1']:,.2f} (60%)")
        print(f"   SL: {filled_qty} BTC @ ${params['stop_loss']:,.2f} (full)")

        orders = {}

        # 1. Stop Loss (full position)
        try:
            sl_order = self.client.create_order(
                symbol=self.symbol,
                side=exit_side,
                order_type=OrderType.STOP_MARKET,
                quantity=filled_qty,
                stop_price=params['stop_loss'],
                reduce_only=True
            )
            orders['stop_loss'] = sl_order.order_id
            self.active_orders['stop_loss'] = sl_order.order_id
            print(f"✅ SL Order: #{sl_order.order_id}")
        except Exception as e:
            print(f"❌ SL Error: {e}")

        # 2. Take Profit 1 (60%)
        try:
            tp_order = self.client.create_order(
                symbol=self.symbol,
                side=exit_side,
                order_type=OrderType.TAKE_PROFIT_MARKET,
                quantity=tp1_qty,
                stop_price=params['take_profit_1'],
                reduce_only=True
            )
            orders['take_profit_1'] = tp_order.order_id
            self.active_orders['take_profit_1'] = tp_order.order_id
            print(f"✅ TP1 Order: #{tp_order.order_id}")
        except Exception as e:
            print(f"❌ TP1 Error: {e}")

        return orders

    def monitor_position(self, params):
        """Monitor position and handle exits."""
        print_separator("MONITORING POSITION")
        print("👀 Watching position... (Ctrl+C to stop)")

        try:
            while True:
                # Get position
                positions = self.client.get_positions(self.symbol)
                active = [p for p in positions if abs(p.position_amt) > 0]

                if not active:
                    print("\n✅ Position Closed!")
                    break

                pos = active[0]
                pnl_pct = (pos.unrealized_pnl / (abs(pos.position_amt) * pos.entry_price)) * 100

                # Get open orders (returns list of dicts)
                orders = self.client.get_open_orders(self.symbol)

                print(f"   Pos: {pos.position_amt:.3f} | PnL: ${pos.unrealized_pnl:+.2f} ({pnl_pct:+.2f}%) | Orders: {len(orders)}   ", end="\r")

                # Check if TP1 was hit (TP order no longer exists but position reduced)
                # TODO: Implement breakeven logic

                time.sleep(3)

        except KeyboardInterrupt:
            print("\n\n⏹️ Monitoring stopped")

    def move_to_breakeven(self, params, remaining_qty: float):
        """Move SL to entry after TP1 hit (matching backtest)."""
        print_separator("MOVE TO BREAKEVEN")

        exit_side = OrderSide.SELL if params['side'] == "BUY" else OrderSide.BUY

        # Cancel old SL
        if 'stop_loss' in self.active_orders:
            try:
                self.client.cancel_order(self.symbol, self.active_orders['stop_loss'])
                print(f"✅ Cancelled old SL: #{self.active_orders['stop_loss']}")
            except Exception as e:
                print(f"⚠️ Cancel SL: {e}")

        # New SL at entry + buffer
        buffer = params['entry'] * self.config.BREAKEVEN_BUFFER_PCT
        be_price = round(params['entry'] + buffer, 1) if params['side'] == "BUY" else round(params['entry'] - buffer, 1)

        print(f"📋 Breakeven SL:")
        print(f"   Price: ${be_price:,.2f} (entry + buffer)")
        print(f"   Qty: {remaining_qty}")

        try:
            sl_order = self.client.create_order(
                symbol=self.symbol,
                side=exit_side,
                order_type=OrderType.STOP_MARKET,
                quantity=remaining_qty,
                stop_price=be_price,
                reduce_only=True
            )
            self.active_orders['stop_loss'] = sl_order.order_id
            print(f"✅ Breakeven SL: #{sl_order.order_id}")
            return sl_order
        except Exception as e:
            print(f"❌ Error: {e}")
            return None

    def cleanup(self):
        """Cancel all orders and close positions."""
        print_separator("CLEANUP")

        try:
            self.client.cancel_all_orders(self.symbol)
            print("✅ Cancelled all orders")
        except Exception as e:
            print(f"⚠️ Cancel: {e}")

        positions = self.client.get_positions(self.symbol)
        active = [p for p in positions if abs(p.position_amt) > 0]
        for p in active:
            try:
                side = OrderSide.SELL if p.position_amt > 0 else OrderSide.BUY
                self.client.create_order(
                    symbol=p.symbol,
                    side=side,
                    order_type=OrderType.MARKET,
                    quantity=abs(p.position_amt),
                    reduce_only=True
                )
                print(f"✅ Closed {p.symbol}")
            except Exception as e:
                print(f"⚠️ Close: {e}")

    def run_full_cycle(self, side: str = "BUY"):
        """Run complete trade cycle."""
        print("\n" + "=" * 60)
        print(f"🚀 FULL TRADE CYCLE - {side}")
        print("=" * 60)

        # 1. Setup
        self.setup()

        # 2. Calculate params
        params = self.calculate_trade_params(side)

        # Confirm
        confirm = input("\n⚡ Execute trade? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("❌ Cancelled")
            return

        # 3. Place entry
        entry_order = self.place_entry_order(params)
        if not entry_order:
            return

        # 4. Wait for fill (or use market for instant test)
        print("\n💡 Options:")
        print("   1. Wait for limit fill")
        print("   2. Cancel and use market order (instant)")
        choice = input("\nChoice: ").strip()

        if choice == "2":
            # Cancel limit order first
            try:
                self.client.cancel_order(self.symbol, entry_order.order_id)
                print("✅ Cancelled limit order")
            except Exception as e:
                print(f"⚠️ Cancel: {e}")

            # Place market order
            side_enum = OrderSide.BUY if side == "BUY" else OrderSide.SELL
            market_order = self.client.create_order(
                symbol=self.symbol,
                side=side_enum,
                order_type=OrderType.MARKET,
                quantity=params['size']
            )

            # SOTA: Wait-and-Query pattern (market orders don't return avg_price immediately)
            print("⏳ Waiting for market order fill...")
            filled_qty = 0.0
            avg_price = 0.0

            for attempt in range(10):  # Max 10 attempts, 1 second each
                time.sleep(1)
                try:
                    order_data = self.client.get_order(self.symbol, market_order.order_id)
                    status = order_data.get('status', '')
                    if status == "FILLED":
                        filled_qty = float(order_data.get('executedQty', 0))
                        avg_price = float(order_data.get('avgPrice', 0))
                        print(f"✅ Market Order FILLED!")
                        print(f"   Avg Price: ${avg_price:,.2f}")
                        print(f"   Executed Qty: {filled_qty}")
                        break
                    else:
                        print(f"   [{attempt+1}s] Status: {status}...", end="\r")
                except Exception as e:
                    print(f"   Query error: {e}")

            if filled_qty == 0:
                # Fallback: Get from position
                print("⚠️ Fetching from position...")
                positions = self.client.get_positions(self.symbol)
                active = [p for p in positions if abs(p.position_amt) > 0]
                if active:
                    filled_qty = abs(active[0].position_amt)
                    avg_price = active[0].entry_price
                    print(f"✅ Position found: {filled_qty} @ ${avg_price:,.2f}")
                else:
                    print("❌ No position found!")
                    return
        else:
            filled_order = self.wait_for_fill(entry_order.order_id)
            if not filled_order:
                return
            filled_qty = float(filled_order.executed_qty)

        # Validate filled_qty before placing bracket orders
        if filled_qty <= 0:
            print("❌ Error: No filled quantity, cannot place bracket orders")
            return

        # 5. Place bracket orders
        self.place_bracket_orders(params, filled_qty)

        # 6. Monitor
        self.monitor_position(params)

        print("\n✅ Trade Cycle Complete!")


def main():
    tester = FullTradeTest()

    print("\n" + "=" * 60)
    print("🧪 FULL TRADE CYCLE TEST - Binance Futures Testnet")
    print("=" * 60)

    while True:
        print("\n📋 Menu:")
        print("  1. Run BUY Trade Cycle")
        print("  2. Run SELL Trade Cycle")
        print("  3. Move to Breakeven (Manual)")
        print("  4. Cleanup")
        print("  0. Exit")

        choice = input("\nChoice: ").strip()

        if choice == "1":
            tester.run_full_cycle("BUY")
        elif choice == "2":
            tester.run_full_cycle("SELL")
        elif choice == "3":
            # TODO: Implement manual BE trigger
            print("💡 Run after TP1 hit to move SL to breakeven")
        elif choice == "4":
            tester.cleanup()
        elif choice == "0":
            print("👋 Goodbye!")
            break


if __name__ == "__main__":
    main()
