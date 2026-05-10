/**
 * OrderPanelMobile - Bottom sheet order form for mobile
 * SOTA: Binance UI Refined 2025 + Material Design 3
 *
 * Features:
 * - Wrap order form in BottomSheet (REQ-8.1)
 * - Trigger from Trade tab or chart action (REQ-8.5)
 * - Use ResponsiveButton and ResponsiveInput
 * - Quick order entry with preset amounts
 */

import React, { useState, useCallback, useMemo } from 'react';
import { BottomSheet } from '../common/BottomSheet';
import { ResponsiveButton } from '../common/ResponsiveButton';
import { ResponsiveInput } from '../common/ResponsiveInput';
import { formatPrice } from '../../styles/theme';
import { TrendingUp, TrendingDown, DollarSign } from 'lucide-react';

type OrderSide = 'LONG' | 'SHORT';
type OrderType = 'MARKET' | 'LIMIT';

interface OrderPanelMobileProps {
  isOpen: boolean;
  onClose: () => void;
  symbol: string;
  currentPrice: number;
  availableBalance: number;
  leverage: number;
  onSubmitOrder: (order: OrderData) => Promise<void>;
}

interface OrderData {
  symbol: string;
  side: OrderSide;
  type: OrderType;
  quantity: number;
  price?: number;
  stopLoss?: number;
  takeProfit?: number;
  leverage: number;
}

// --- COLORS ---
const COLORS = {
  buy: 'rgb(14, 203, 129)',
  sell: 'rgb(246, 70, 93)',
  yellow: 'rgb(240, 185, 11)',
  bgPrimary: 'rgb(24, 26, 32)',
  bgSecondary: 'rgb(30, 35, 41)',
  bgTertiary: 'rgb(43, 49, 57)',
  textPrimary: 'rgb(234, 236, 239)',
  textSecondary: 'rgb(132, 142, 156)',
  textTertiary: 'rgb(94, 102, 115)',
};

// Preset margin percentages
const MARGIN_PRESETS = [10, 25, 50, 75, 100];

/**
 * OrderPanelMobile - Main component
 */
export const OrderPanelMobile: React.FC<OrderPanelMobileProps> = ({
  isOpen,
  onClose,
  symbol,
  currentPrice,
  availableBalance,
  leverage,
  onSubmitOrder,
}) => {
  const [side, setSide] = useState<OrderSide>('LONG');
  const [orderType, setOrderType] = useState<OrderType>('MARKET');
  const [marginPercent, setMarginPercent] = useState(25);
  const [limitPrice, setLimitPrice] = useState('');
  const [stopLoss, setStopLoss] = useState('');
  const [takeProfit, setTakeProfit] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const sideColor = side === 'LONG' ? COLORS.buy : COLORS.sell;

  // Calculate order values
  const margin = useMemo(() => {
    return (availableBalance * marginPercent) / 100;
  }, [availableBalance, marginPercent]);

  const quantity = useMemo(() => {
    const price = orderType === 'LIMIT' && limitPrice ? parseFloat(limitPrice) : currentPrice;
    if (!price || price <= 0) return 0;
    return (margin * leverage) / price;
  }, [margin, leverage, currentPrice, orderType, limitPrice]);

  const notionalValue = useMemo(() => {
    return quantity * currentPrice;
  }, [quantity, currentPrice]);

  /**
   * Handle order submission
   */
  const handleSubmit = useCallback(async () => {
    if (isSubmitting || quantity <= 0) return;

    setIsSubmitting(true);
    try {
      await onSubmitOrder({
        symbol,
        side,
        type: orderType,
        quantity,
        price: orderType === 'LIMIT' ? parseFloat(limitPrice) : undefined,
        stopLoss: stopLoss ? parseFloat(stopLoss) : undefined,
        takeProfit: takeProfit ? parseFloat(takeProfit) : undefined,
        leverage,
      });
      onClose();
    } catch (error) {
      console.error('Order submission failed:', error);
    } finally {
      setIsSubmitting(false);
    }
  }, [isSubmitting, quantity, symbol, side, orderType, limitPrice, stopLoss, takeProfit, leverage, onSubmitOrder, onClose]);

  /**
   * Reset form when closing
   */
  const handleClose = useCallback(() => {
    setMarginPercent(25);
    setLimitPrice('');
    setStopLoss('');
    setTakeProfit('');
    onClose();
  }, [onClose]);

  return (
    <BottomSheet
      isOpen={isOpen}
      onClose={handleClose}
      snapPoints={['half', 'full']}
      initialSnap="half"
      title={`${side} ${symbol}`}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {/* Side Toggle */}
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={() => setSide('LONG')}
            style={{
              flex: 1,
              padding: '12px 16px',
              fontSize: 14,
              fontWeight: 700,
              color: side === 'LONG' ? '#000' : COLORS.buy,
              background: side === 'LONG' ? COLORS.buy : `${COLORS.buy}15`,
              border: `1px solid ${COLORS.buy}`,
              borderRadius: 8,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 8,
            }}
          >
            <TrendingUp size={18} />
            Long
          </button>
          <button
            onClick={() => setSide('SHORT')}
            style={{
              flex: 1,
              padding: '12px 16px',
              fontSize: 14,
              fontWeight: 700,
              color: side === 'SHORT' ? '#fff' : COLORS.sell,
              background: side === 'SHORT' ? COLORS.sell : `${COLORS.sell}15`,
              border: `1px solid ${COLORS.sell}`,
              borderRadius: 8,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 8,
            }}
          >
            <TrendingDown size={18} />
            Short
          </button>
        </div>

        {/* Order Type Toggle */}
        <div style={{ display: 'flex', gap: 8 }}>
          {(['MARKET', 'LIMIT'] as OrderType[]).map(type => (
            <button
              key={type}
              onClick={() => setOrderType(type)}
              style={{
                flex: 1,
                padding: '8px 12px',
                fontSize: 12,
                fontWeight: orderType === type ? 600 : 400,
                color: orderType === type ? COLORS.textPrimary : COLORS.textTertiary,
                background: orderType === type ? COLORS.bgTertiary : 'transparent',
                border: `1px solid ${COLORS.bgTertiary}`,
                borderRadius: 6,
                cursor: 'pointer',
              }}
            >
              {type}
            </button>
          ))}
        </div>

        {/* Limit Price (if LIMIT order) */}
        {orderType === 'LIMIT' && (
          <ResponsiveInput
            label="Limit Price"
            type="number"
            value={limitPrice}
            onChange={(e) => setLimitPrice(e.target.value)}
            placeholder={currentPrice.toString()}
            leftIcon={<DollarSign size={16} />}
          />
        )}

        {/* Margin Presets */}
        <div>
          <div style={{
            fontSize: 12,
            color: COLORS.textSecondary,
            marginBottom: 8,
            display: 'flex',
            justifyContent: 'space-between',
          }}>
            <span>Margin</span>
            <span style={{ color: COLORS.textPrimary, fontFamily: 'monospace' }}>
              ${margin.toFixed(2)}
            </span>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {MARGIN_PRESETS.map(preset => (
              <button
                key={preset}
                onClick={() => setMarginPercent(preset)}
                style={{
                  flex: 1,
                  padding: '8px 4px',
                  fontSize: 12,
                  fontWeight: marginPercent === preset ? 600 : 400,
                  color: marginPercent === preset ? sideColor : COLORS.textTertiary,
                  background: marginPercent === preset ? `${sideColor}15` : COLORS.bgTertiary,
                  border: marginPercent === preset ? `1px solid ${sideColor}` : `1px solid ${COLORS.bgTertiary}`,
                  borderRadius: 4,
                  cursor: 'pointer',
                }}
              >
                {preset}%
              </button>
            ))}
          </div>
        </div>

        {/* TP/SL Inputs */}
        <div style={{ display: 'flex', gap: 12 }}>
          <ResponsiveInput
            label="Take Profit"
            type="number"
            value={takeProfit}
            onChange={(e) => setTakeProfit(e.target.value)}
            placeholder="Optional"
            size="sm"
          />
          <ResponsiveInput
            label="Stop Loss"
            type="number"
            value={stopLoss}
            onChange={(e) => setStopLoss(e.target.value)}
            placeholder="Optional"
            size="sm"
          />
        </div>

        {/* Order Summary */}
        <div style={{
          padding: 12,
          background: COLORS.bgPrimary,
          borderRadius: 8,
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
        }}>
          <SummaryRow label="Entry Price" value={`$${formatPrice(currentPrice)}`} />
          <SummaryRow label="Quantity" value={quantity.toFixed(4)} />
          <SummaryRow label="Notional Value" value={`$${notionalValue.toFixed(2)}`} />
          <SummaryRow label="Leverage" value={`${leverage}x`} highlight />
        </div>

        {/* Submit Button */}
        <ResponsiveButton
          variant={side === 'LONG' ? 'primary' : 'danger'}
          size="lg"
          fullWidth
          loading={isSubmitting}
          onClick={handleSubmit}
          disabled={quantity <= 0}
          style={{
            background: sideColor,
            marginTop: 8,
          }}
        >
          {side === 'LONG' ? 'Open Long' : 'Open Short'}
        </ResponsiveButton>

        {/* Available Balance */}
        <div style={{
          textAlign: 'center',
          fontSize: 11,
          color: COLORS.textTertiary,
        }}>
          Available: <span style={{ color: COLORS.textSecondary, fontFamily: 'monospace' }}>
            ${formatPrice(availableBalance)}
          </span>
        </div>
      </div>
    </BottomSheet>
  );
};

/**
 * SummaryRow - Key-value display for order summary
 */
const SummaryRow: React.FC<{
  label: string;
  value: string;
  highlight?: boolean;
}> = ({ label, value, highlight }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
    <span style={{ fontSize: 12, color: COLORS.textTertiary }}>{label}</span>
    <span style={{
      fontSize: 13,
      fontWeight: highlight ? 600 : 400,
      color: highlight ? COLORS.yellow : COLORS.textPrimary,
      fontFamily: 'monospace',
    }}>
      {value}
    </span>
  </div>
);

export default OrderPanelMobile;
