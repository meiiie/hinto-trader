"""
Unit Tests for Order Manager

Tests order placement, TTL tracking, and cancellation logic.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, patch

order_manager_module = pytest.importorskip(
    "src.application.backtest_live.core.order_manager",
    reason="legacy backtest_live order manager module is not available in this codebase",
)
OrderManager = order_manager_module.OrderManager
PendingOrder = order_manager_module.PendingOrder


@pytest.fixture
def mock_binance_client():
    """Create mock Binance client."""
    client = Mock()
    client.create_order = AsyncMock()
    client.cancel_order = AsyncMock()
    return client


@pytest.fixture
def order_manager(mock_binance_client):
    """Create order manager with default settings."""
    return OrderManager(
        binance_client=mock_binance_client,
        default_ttl_minutes=50,
        enable_backup_sl=True,
        backup_sl_distance_pct=0.02
    )


class TestOrderPlacement:
    """Test order placement functionality."""

    @pytest.mark.asyncio
    async def test_place_limit_order_long(self, order_manager, mock_binance_client):
        """Test placing LONG LIMIT order."""
        # Mock exchange response
        mock_binance_client.create_order.return_value = {
            'orderId': '12345',
            'status': 'NEW'
        }

        order = await order_manager.place_limit_order(
            symbol='BTCUSDT',
            side='LONG',
            target_price=100.0,
            quantity=1.0,
            stop_loss=95.0,
            confidence=0.85
        )

        # Verify order created
        assert order is not None
        assert order.symbol == 'BTCUSDT'
        assert order.side == 'LONG'
        assert order.target_price == 100.0
        assert order.quantity == 1.0
        assert order.confidence == 0.85
        assert order.exchange_order_id == '12345'

        # Verify exchange call (first call is LIMIT order)
        assert mock_binance_client.create_order.call_count == 2  # LIMIT + backup SL
        call_args = mock_binance_client.create_order.call_args_list[0][1]  # First call
        assert call_args['symbol'] == 'BTCUSDT'
        assert call_args['side'] == 'BUY'
        assert call_args['type'] == 'LIMIT'
        assert call_args['price'] == 100.0

    @pytest.mark.asyncio
    async def test_place_limit_order_short(self, order_manager, mock_binance_client):
        """Test placing SHORT LIMIT order."""
        mock_binance_client.create_order.return_value = {
            'orderId': '12346',
            'status': 'NEW'
        }

        order = await order_manager.place_limit_order(
            symbol='ETHUSDT',
            side='SHORT',
            target_price=2000.0,
            quantity=0.5,
            stop_loss=2100.0,
            confidence=0.90
        )

        assert order is not None
        assert order.side == 'SHORT'

        # Verify SHORT uses SELL (first call is LIMIT order)
        call_args = mock_binance_client.create_order.call_args_list[0][1]
        assert call_args['side'] == 'SELL'

    @pytest.mark.asyncio
    async def test_place_order_with_backup_sl(self, order_manager, mock_binance_client):
        """Test backup SL placement."""
        # Mock responses for both LIMIT and STOP orders
        mock_binance_client.create_order.side_effect = [
            {'orderId': '12345', 'status': 'NEW'},  # LIMIT order
            {'orderId': '12346', 'status': 'NEW'}   # STOP order
        ]

        order = await order_manager.place_limit_order(
            symbol='BTCUSDT',
            side='LONG',
            target_price=100.0,
            quantity=1.0,
            stop_loss=95.0
        )

        # Verify backup SL was placed
        assert order.backup_sl_order_id == '12346'
        assert mock_binance_client.create_order.call_count == 2

        # Verify backup SL parameters
        backup_call = mock_binance_client.create_order.call_args_list[1][1]
        assert backup_call['type'] == 'STOP_MARKET'
        assert backup_call['stopPrice'] == 98.0  # 100 * (1 - 0.02)

    @pytest.mark.asyncio
    async def test_place_order_without_backup_sl(self, mock_binance_client):
        """Test order placement without backup SL."""
        order_manager = OrderManager(
            binance_client=mock_binance_client,
            enable_backup_sl=False
        )

        mock_binance_client.create_order.return_value = {
            'orderId': '12345',
            'status': 'NEW'
        }

        order = await order_manager.place_limit_order(
            symbol='BTCUSDT',
            side='LONG',
            target_price=100.0,
            quantity=1.0,
            stop_loss=95.0
        )

        # Verify no backup SL
        assert order.backup_sl_order_id is None
        assert mock_binance_client.create_order.call_count == 1

    @pytest.mark.asyncio
    async def test_place_order_failure(self, order_manager, mock_binance_client):
        """Test order placement failure handling."""
        mock_binance_client.create_order.side_effect = Exception("API Error")

        order = await order_manager.place_limit_order(
            symbol='BTCUSDT',
            side='LONG',
            target_price=100.0,
            quantity=1.0,
            stop_loss=95.0
        )

        # Should return None on failure
        assert order is None


class TestTTLTracking:
    """Test TTL (Time-To-Live) tracking."""

    @pytest.mark.asyncio
    async def test_order_with_ttl(self, order_manager, mock_binance_client):
        """Test order with TTL expiry."""
        mock_binance_client.create_order.return_value = {
            'orderId': '12345',
            'status': 'NEW'
        }

        order = await order_manager.place_limit_order(
            symbol='BTCUSDT',
            side='LONG',
            target_price=100.0,
            quantity=1.0,
            stop_loss=95.0,
            ttl_minutes=50
        )

        # Verify TTL set
        assert order.expires_at is not None
        expected_expiry = order.created_at + timedelta(minutes=50)
        assert abs((order.expires_at - expected_expiry).total_seconds()) < 1

    @pytest.mark.asyncio
    async def test_order_without_ttl(self, order_manager, mock_binance_client):
        """Test order without TTL (GTC)."""
        mock_binance_client.create_order.return_value = {
            'orderId': '12345',
            'status': 'NEW'
        }

        # Create order manager with TTL=0 (GTC)
        order_manager_gtc = OrderManager(
            binance_client=mock_binance_client,
            default_ttl_minutes=0
        )

        order = await order_manager_gtc.place_limit_order(
            symbol='BTCUSDT',
            side='LONG',
            target_price=100.0,
            quantity=1.0,
            stop_loss=95.0
        )

        # Verify no expiry
        assert order.expires_at is None
        assert not order.is_expired

    def test_is_expired_property(self):
        """Test is_expired property."""
        # Not expired
        order = PendingOrder(
            order_id='test',
            symbol='BTCUSDT',
            side='LONG',
            order_type='LIMIT',
            target_price=100.0,
            quantity=1.0,
            stop_loss=95.0,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(minutes=10)
        )
        assert not order.is_expired

        # Expired
        order_expired = PendingOrder(
            order_id='test',
            symbol='BTCUSDT',
            side='LONG',
            order_type='LIMIT',
            target_price=100.0,
            quantity=1.0,
            stop_loss=95.0,
            created_at=datetime.utcnow() - timedelta(minutes=60),
            expires_at=datetime.utcnow() - timedelta(minutes=10)
        )
        assert order_expired.is_expired

    @pytest.mark.asyncio
    async def test_check_ttl_expiry(self, order_manager, mock_binance_client):
        """Test TTL expiry checking."""
        # Place order
        mock_binance_client.create_order.return_value = {
            'orderId': '12345',
            'status': 'NEW'
        }

        order = await order_manager.place_limit_order(
            symbol='BTCUSDT',
            side='LONG',
            target_price=100.0,
            quantity=1.0,
            stop_loss=95.0,
            ttl_minutes=50
        )

        # Manually set expiry to past
        order.expires_at = datetime.utcnow() - timedelta(minutes=1)

        # Check expiry
        expired_symbols = await order_manager.check_ttl_expiry()

        # Verify order was cancelled
        assert 'BTCUSDT' in expired_symbols
        assert 'BTCUSDT' not in order_manager.pending_orders
        assert order_manager._orders_expired == 1


class TestOrderCancellation:
    """Test order cancellation."""

    @pytest.mark.asyncio
    async def test_cancel_order(self, order_manager, mock_binance_client):
        """Test order cancellation."""
        # Place order
        mock_binance_client.create_order.return_value = {
            'orderId': '12345',
            'status': 'NEW'
        }

        await order_manager.place_limit_order(
            symbol='BTCUSDT',
            side='LONG',
            target_price=100.0,
            quantity=1.0,
            stop_loss=95.0
        )

        # Cancel order
        success = await order_manager.cancel_order('BTCUSDT', reason="Test")

        # Verify cancellation
        assert success
        assert 'BTCUSDT' not in order_manager.pending_orders
        assert order_manager._orders_cancelled == 1

        # Verify exchange calls
        assert mock_binance_client.cancel_order.call_count == 2  # LIMIT + backup SL

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_order(self, order_manager):
        """Test cancelling non-existent order."""
        success = await order_manager.cancel_order('BTCUSDT')

        assert not success
        assert order_manager._orders_cancelled == 0

    @pytest.mark.asyncio
    async def test_cancel_order_failure(self, order_manager, mock_binance_client):
        """Test order cancellation failure."""
        # Place order
        mock_binance_client.create_order.return_value = {
            'orderId': '12345',
            'status': 'NEW'
        }

        await order_manager.place_limit_order(
            symbol='BTCUSDT',
            side='LONG',
            target_price=100.0,
            quantity=1.0,
            stop_loss=95.0
        )

        # Mock cancellation failure
        mock_binance_client.cancel_order.side_effect = Exception("API Error")

        success = await order_manager.cancel_order('BTCUSDT')

        # Should return False on failure
        assert not success


class TestOrderTracking:
    """Test order tracking functionality."""

    @pytest.mark.asyncio
    async def test_mark_filled(self, order_manager, mock_binance_client):
        """Test marking order as filled."""
        # Place order
        mock_binance_client.create_order.return_value = {
            'orderId': '12345',
            'status': 'NEW'
        }

        await order_manager.place_limit_order(
            symbol='BTCUSDT',
            side='LONG',
            target_price=100.0,
            quantity=1.0,
            stop_loss=95.0
        )

        # Mark filled
        success = order_manager.mark_filled('BTCUSDT')

        # Verify
        assert success
        assert 'BTCUSDT' not in order_manager.pending_orders
        assert order_manager._orders_filled == 1

    @pytest.mark.asyncio
    async def test_get_pending_order(self, order_manager, mock_binance_client):
        """Test getting pending order."""
        # Place order
        mock_binance_client.create_order.return_value = {
            'orderId': '12345',
            'status': 'NEW'
        }

        await order_manager.place_limit_order(
            symbol='BTCUSDT',
            side='LONG',
            target_price=100.0,
            quantity=1.0,
            stop_loss=95.0,
            confidence=0.85
        )

        # Get order
        order = order_manager.get_pending_order('BTCUSDT')

        assert order is not None
        assert order.symbol == 'BTCUSDT'
        assert order.confidence == 0.85

    @pytest.mark.asyncio
    async def test_get_all_pending(self, order_manager, mock_binance_client):
        """Test getting all pending orders."""
        # Place multiple orders
        mock_binance_client.create_order.return_value = {
            'orderId': '12345',
            'status': 'NEW'
        }

        await order_manager.place_limit_order(
            symbol='BTCUSDT',
            side='LONG',
            target_price=100.0,
            quantity=1.0,
            stop_loss=95.0
        )

        await order_manager.place_limit_order(
            symbol='ETHUSDT',
            side='LONG',
            target_price=2000.0,
            quantity=0.5,
            stop_loss=1900.0
        )

        # Get all
        all_orders = order_manager.get_all_pending()

        assert len(all_orders) == 2
        assert 'BTCUSDT' in all_orders
        assert 'ETHUSDT' in all_orders

    @pytest.mark.asyncio
    async def test_get_worst_pending(self, order_manager, mock_binance_client):
        """Test getting worst pending order (lowest confidence)."""
        # Place orders with different confidence
        mock_binance_client.create_order.return_value = {
            'orderId': '12345',
            'status': 'NEW'
        }

        await order_manager.place_limit_order(
            symbol='BTCUSDT',
            side='LONG',
            target_price=100.0,
            quantity=1.0,
            stop_loss=95.0,
            confidence=0.85
        )

        await order_manager.place_limit_order(
            symbol='ETHUSDT',
            side='LONG',
            target_price=2000.0,
            quantity=0.5,
            stop_loss=1900.0,
            confidence=0.70  # Worst
        )

        await order_manager.place_limit_order(
            symbol='BNBUSDT',
            side='LONG',
            target_price=300.0,
            quantity=2.0,
            stop_loss=285.0,
            confidence=0.90
        )

        # Get worst
        worst = order_manager.get_worst_pending()

        assert worst is not None
        assert worst.symbol == 'ETHUSDT'
        assert worst.confidence == 0.70


class TestStatistics:
    """Test statistics tracking."""

    @pytest.mark.asyncio
    async def test_get_stats(self, order_manager, mock_binance_client):
        """Test getting statistics."""
        # Place and fill some orders
        mock_binance_client.create_order.return_value = {
            'orderId': '12345',
            'status': 'NEW'
        }

        await order_manager.place_limit_order(
            symbol='BTCUSDT',
            side='LONG',
            target_price=100.0,
            quantity=1.0,
            stop_loss=95.0
        )

        await order_manager.place_limit_order(
            symbol='ETHUSDT',
            side='LONG',
            target_price=2000.0,
            quantity=0.5,
            stop_loss=1900.0
        )

        order_manager.mark_filled('BTCUSDT')

        # Get stats
        stats = order_manager.get_stats()

        assert stats['pending_count'] == 1
        assert stats['orders_placed'] == 2
        assert stats['orders_filled'] == 1
        assert stats['default_ttl_minutes'] == 50
        assert stats['backup_sl_enabled'] is True
