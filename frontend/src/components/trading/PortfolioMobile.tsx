// ... imports
import React, { useState, useCallback, useRef } from 'react';
import { formatPrice } from '../../styles/theme';
import { TokenIcon } from '../TokenIcon';
import { ResponsiveButton } from '../common/ResponsiveButton';
import useMarketStore from '../../stores/marketStore';
import SharkTankWatchlist from '../SharkTankWatchlist';
import {
  ChevronDown,
  ChevronUp,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  Shield,
  Target,
  Clock,
  XCircle,
  Briefcase
} from 'lucide-react';

// --- INTERFACES --- (Keep existing Position interfaces)
interface TpSlData {
  stop_loss: number | null;
  take_profit: number | null;
}

interface LocalTpSl extends TpSlData {
  source?: 'signal' | 'watermark' | 'pending' | 'unknown';
  backup_sl?: number | null;
  local_first_mode?: boolean;
}

interface ExchangeTpSl extends TpSlData {
  sl_order_id?: string | null;
  tp_order_id?: string | null;
  is_backup_only?: boolean;
}

export interface Position {
  id: string;
  symbol: string;
  side: 'LONG' | 'SHORT';
  status: string;
  entry_price: number;
  quantity: number;
  leverage: number;
  margin: number;
  stop_loss: number;
  take_profit: number;
  local_tpsl?: LocalTpSl;
  exchange_tpsl?: ExchangeTpSl;
  entry_time?: string;
  unrealized_pnl: number;
  roe_pct: number;
  current_price: number;
  current_value: number;
  size?: number;
  is_orphan?: boolean;
  local_first_mode?: boolean;
}

export interface PendingOrder {
  id: string;
  symbol: string;
  side: 'LONG' | 'SHORT' | 'BUY' | 'SELL';
  entry_price: number;
  size: number;
  quantity?: number;
  stop_loss: number;
  take_profits?: number[];
  take_profit?: number;
  category?: string; // limit, stop_market, etc.
  open_time?: string;
  created_at?: string;
  margin?: number;
  leverage?: number;
  confidence?: number | null;
  confidence_level?: 'high' | 'medium' | 'low' | null;
  risk_reward_ratio?: number | null;
  current_price?: number;
  distance_pct?: number | null;
}

interface BalanceInfo {
  wallet_balance: number;
  available_balance: number;
  unrealized_pnl: number;
  margin_balance?: number;
}

// SOTA: SharkTank Status (for mobile display)
interface SharkTankStatus {
  max_positions: number;
  current_positions: number;
  available_slots: number;
  leverage: number;
  available_margin: number;
  trading_mode?: 'PAPER' | 'TESTNET' | 'LIVE';
  watched_tokens?: string[];
  position_symbols?: Array<{
    symbol: string;
    side: 'LONG' | 'SHORT';
    pnl: number;
    entry_price?: number;
    quantity?: number;
    // SOTA FIX (Jan 2026): Breakeven display fields
    current_sl?: number;
    initial_sl?: number;
    phase?: string;
    is_breakeven?: boolean;
  }>;
  pending_symbols?: Array<{ symbol: string; side: string; entry_price: number; distance_pct: number | null; locked: boolean; confidence?: number | null; rank?: number; risk_reward_ratio?: number | null }>;
  pending_list?: Array<{ symbol: string; direction: 'buy' | 'sell'; confidence: number; queued_at: string }>;
}

interface PortfolioMobileProps {
  positions: Position[];
  pendingOrders: PendingOrder[];
  balance?: BalanceInfo;  // SOTA: Add balance display
  sharkTankStatus?: SharkTankStatus | null;  // SOTA: Shark Tank display
  onClosePosition: (id: string) => void;
  onCloseAllPositions: () => void;
  onCancelOrder: (idOrSymbol: string) => void;
  onCancelAllOrders: () => void;
  onRefresh: () => Promise<void>;
  isLoading?: boolean;
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

// --- SUB-COMPONENTS ---

/**
 * PositionCard - Individual position card with expand/collapse
 */
const PositionCard: React.FC<{
  position: Position;
  isExpanded: boolean;
  onToggle: () => void;
  onClose: () => void;
}> = ({ position, isExpanded, onToggle, onClose }) => {
  const symbolLower = position.symbol.toLowerCase();

  // SOTA: Multi-position realtime prices
  const positionPrice = useMarketStore(state => state.positionPrices[symbolLower]);
  const liveClose = useMarketStore(state => state.symbolData[symbolLower]?.data1m?.close);

  // Price fallback chain
  const currentPrice = positionPrice?.price || liveClose || position.current_price || position.entry_price;

  // Calculate PnL
  const sz = position.size || position.quantity || 0;
  const sideMultiplier = position.side === 'LONG' ? 1 : -1;
  const pnl = (currentPrice - position.entry_price) * sz * sideMultiplier;

  // ROE Calculation
  const margin = position.margin || (position.entry_price * sz / position.leverage);
  const roe = margin > 0 ? (pnl / margin) * 100 : 0;

  const sideColor = position.side === 'LONG' ? COLORS.buy : COLORS.sell;
  const pnlColor = pnl >= 0 ? COLORS.buy : COLORS.sell;

  // SOTA Dual TP/SL
  const localTp = position.local_tpsl?.take_profit || 0;
  const localSl = position.local_tpsl?.stop_loss || 0;
  const exchangeSl = position.exchange_tpsl?.stop_loss || 0;
  const isLocalFirst = position.local_first_mode || position.local_tpsl?.local_first_mode || false;

  return (
    <div
      style={{
        backgroundColor: COLORS.bgSecondary,
        borderRadius: 8, // More compact radius
        marginBottom: 8,
        border: `1px solid ${COLORS.bgTertiary}`,
        overflow: 'hidden',
      }}
    >
      {/* Card Header - Always visible */}
      <div
        onClick={onToggle}
        style={{
          padding: 16,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          cursor: 'pointer',
          background: isExpanded ? `${sideColor}10` : 'transparent',
        }}
      >
        {/* Left: Symbol + Side */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <TokenIcon symbol={position.symbol.replace('USDT', '')} size={36} />
          <div>
            <div style={{
              fontWeight: 700,
              fontSize: 16,
              color: COLORS.textPrimary,
              display: 'flex',
              alignItems: 'center',
              gap: 8,
            }}>
              {position.symbol}
              {position.side === 'LONG' ? (
                <TrendingUp size={14} color={COLORS.buy} />
              ) : (
                <TrendingDown size={14} color={COLORS.sell} />
              )}
            </div>
            <div style={{
              fontSize: 12,
              color: sideColor,
              fontWeight: 600,
              display: 'flex',
              alignItems: 'center',
              gap: 6,
            }}>
              {position.side} {position.leverage}x
              {isLocalFirst && (
                <span style={{
                  fontSize: 9,
                  padding: '1px 4px',
                  background: `${COLORS.buy}20`,
                  borderRadius: 3,
                  color: COLORS.buy,
                }}>
                  Local
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Right: PnL */}
        <div style={{ textAlign: 'right', display: 'flex', alignItems: 'center', gap: 12 }}>
          <div>
            <div style={{
              fontWeight: 700,
              fontSize: 18,
              color: pnlColor,
              fontFamily: 'monospace',
            }}>
              {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}
            </div>
            <div style={{
              fontSize: 12,
              color: pnlColor,
              fontFamily: 'monospace',
            }}>
              {roe >= 0 ? '+' : ''}{roe.toFixed(2)}%
            </div>
          </div>
          {isExpanded ? (
            <ChevronUp size={20} color={COLORS.textTertiary} />
          ) : (
            <ChevronDown size={20} color={COLORS.textTertiary} />
          )}
        </div>
      </div>

      {/* Expanded Details */}
      {isExpanded && (
        <div style={{
          padding: 16,
          paddingTop: 0,
          borderTop: `1px solid ${COLORS.bgTertiary}`,
        }}>
          {/* Price Info Grid */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(2, 1fr)',
            gap: 12,
            marginTop: 16,
          }}>
            <DetailItem label="Entry Price" value={`$${formatPrice(position.entry_price)}`} />
            <DetailItem label="Mark Price" value={`$${formatPrice(currentPrice)}`} highlight />
            <DetailItem label="Size" value={sz.toFixed(4)} />
            <DetailItem label="Margin" value={`$${margin.toFixed(2)}`} />
          </div>

          {/* TP/SL Section */}
          <div style={{
            marginTop: 16,
            padding: 12,
            background: COLORS.bgPrimary,
            borderRadius: 8,
          }}>
            <div style={{
              fontSize: 11,
              color: COLORS.textTertiary,
              marginBottom: 8,
              textTransform: 'uppercase',
              letterSpacing: 0.5,
              display: 'flex',
              alignItems: 'center',
              gap: 6,
            }}>
              <Target size={12} /> TP / SL
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              {/* Take Profit */}
              <div>
                <div style={{ fontSize: 10, color: COLORS.textTertiary, marginBottom: 2 }}>
                  Take Profit
                </div>
                <div style={{
                  fontSize: 14,
                  fontWeight: 600,
                  color: localTp > 0 ? COLORS.buy : COLORS.textTertiary,
                  fontFamily: 'monospace',
                }}>
                  {localTp > 0 ? `$${formatPrice(localTp)}` : '--'}
                </div>
              </div>

              {/* Stop Loss */}
              <div style={{ textAlign: 'right' }}>
                <div style={{
                  fontSize: 10,
                  color: COLORS.textTertiary,
                  marginBottom: 2,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'flex-end',
                  gap: 4
                }}>
                  Stop Loss
                  {/* SOTA ENHANCEMENT 2: sl_source badge */}
                  <span style={{
                    fontSize: 8,
                    padding: '1px 4px',
                    borderRadius: 3,
                    background: localSl > 0 ? `${COLORS.buy}20` : `${COLORS.sell}20`,
                    color: localSl > 0 ? COLORS.buy : COLORS.sell,
                    fontWeight: 600
                  }}>
                    {localSl > 0 ? '🟢 Local' : (exchangeSl > 0 ? '🔴 Backup' : '')}
                  </span>
                </div>
                <div style={{
                  fontSize: 14,
                  fontWeight: 600,
                  color: localSl > 0 ? COLORS.sell : COLORS.textTertiary,
                  fontFamily: 'monospace',
                }}>
                  {localSl > 0 ? `$${formatPrice(localSl)}` : '--'}
                </div>
              </div>
            </div>

            {/* Backup SL indicator */}
            {exchangeSl > 0 && (
              <div style={{
                marginTop: 8,
                paddingTop: 8,
                borderTop: `1px solid ${COLORS.bgTertiary}`,
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                fontSize: 11,
                color: COLORS.textTertiary,
              }}>
                <Shield size={12} />
                Backup SL: <span style={{ color: COLORS.sell, fontFamily: 'monospace' }}>
                  ${formatPrice(exchangeSl)}
                </span>
              </div>
            )}
          </div>

          {/* Close Button */}
          <ResponsiveButton
            variant="danger"
            fullWidth
            style={{ marginTop: 16 }}
            onClick={(e) => {
              e.stopPropagation();
              onClose();
            }}
          >
            Close Position
          </ResponsiveButton>
        </div>
      )}
    </div>
  );
};

/**
 * PendingOrderCard - Collapsible pending order card (SOTA Binance Accordion Pattern)
 */
const PendingOrderCard: React.FC<{
  order: PendingOrder;
  isExpanded: boolean;
  onToggle: () => void;
  onCancel: () => void;
}> = ({ order, isExpanded, onToggle, onCancel }) => {
  const isLong = ['LONG', 'BUY'].includes(order.side);
  const sideColor = isLong ? COLORS.buy : COLORS.sell;

  // SOTA FIX: Add Vietnam timezone explicitly
  const timeStr = order.open_time || order.created_at;
  const formattedTime = timeStr ? new Date(timeStr).toLocaleString('vi-VN', {
    timeZone: 'Asia/Ho_Chi_Minh',
    hour: '2-digit', minute: '2-digit',
    day: '2-digit', month: '2-digit'
  }) : '--';
  const confidenceText = typeof order.confidence === 'number'
    ? `${Math.round(order.confidence * 100)}%`
    : '--';
  const rrText = typeof order.risk_reward_ratio === 'number'
    ? `1:${order.risk_reward_ratio.toFixed(1)}`
    : '--';

  return (
    <div style={{
      backgroundColor: COLORS.bgSecondary,
      borderRadius: 10,
      marginBottom: 8,
      border: `1px solid ${COLORS.bgTertiary}`,
      overflow: 'hidden'
    }}>
      {/* Header: Always visible - Tap to expand */}
      <div
        onClick={onToggle}
        style={{
          padding: '12px 14px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          cursor: 'pointer',
          background: isExpanded ? `${sideColor}08` : 'transparent',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <TokenIcon symbol={order.symbol.replace('USDT', '')} size={28} />
          <div>
            <div style={{ fontWeight: 700, fontSize: 14, color: COLORS.textPrimary }}>
              {order.symbol}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{
                fontSize: 10,
                color: sideColor,
                fontWeight: 700,
                textTransform: 'uppercase'
              }}>
                {order.side}
              </span>
              <span style={{ fontSize: 10, color: COLORS.textTertiary }}>•</span>
              <span style={{ fontSize: 10, color: COLORS.yellow, fontFamily: 'monospace' }}>
                ${formatPrice(order.entry_price)}
              </span>
            </div>
          </div>
        </div>

        {/* Right: Time + Chevron */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 4, opacity: 0.6 }}>
            <Clock size={10} color={COLORS.textTertiary} />
            <span style={{ fontSize: 10, fontFamily: 'monospace', color: COLORS.textTertiary }}>
              {formattedTime}
            </span>
          </div>
          {isExpanded ? (
            <ChevronUp size={16} color={COLORS.textTertiary} />
          ) : (
            <ChevronDown size={16} color={COLORS.textTertiary} />
          )}
        </div>
      </div>

      {/* Expanded Details - Only show when expanded */}
      {isExpanded && (
        <div style={{
          padding: '12px 14px',
          borderTop: `1px solid ${COLORS.bgTertiary}`,
          background: COLORS.bgPrimary,
        }}>
          {/* Data Grid: Size | SL | Margin */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12, marginBottom: 12 }}>
            <DetailItem
              label="Size (USDT)"
              value={order.size.toLocaleString('en-US', { maximumFractionDigits: 2 })}
            />
            <DetailItem
              label="Stop Loss"
              value={order.stop_loss > 0 ? `$${formatPrice(order.stop_loss)}` : '--'}
            />
            <DetailItem
              label="Margin"
              value={order.margin ? `$${order.margin.toFixed(2)}` : '--'}
            />
            <DetailItem
              label="Confidence"
              value={confidenceText}
            />
            <DetailItem
              label="R:R"
              value={rrText}
            />
          </div>

          <ResponsiveButton
            variant="secondary"
            fullWidth
            onClick={(e: React.MouseEvent) => { e.stopPropagation(); onCancel(); }}
            style={{
              fontSize: 12,
              height: 32,
              border: `1px solid ${COLORS.sell}40`,
              color: COLORS.sell,
              background: 'transparent'
            }}
          >
            <XCircle size={12} style={{ marginRight: 4 }} /> Cancel
          </ResponsiveButton>
        </div>
      )}
    </div>
  );
};

/**
 * DetailItem - Key-value display
 */
const DetailItem: React.FC<{
  label: string;
  value: string;
  highlight?: boolean;
}> = ({ label, value, highlight }) => (
  <div>
    <div style={{
      fontSize: 10,
      color: COLORS.textTertiary,
      marginBottom: 2,
      textTransform: 'uppercase',
      letterSpacing: 0.5,
    }}>
      {label}
    </div>
    <div style={{
      fontSize: 14,
      fontWeight: 600,
      color: highlight ? COLORS.yellow : COLORS.textPrimary,
      fontFamily: 'monospace',
    }}>
      {value}
    </div>
  </div>
);


/**
 * PortfolioMobile - Main component
 * Card-based portfolio view with tabs for Positions and Open Orders
 */
export const PortfolioMobile: React.FC<PortfolioMobileProps> = ({
  positions,
  pendingOrders,
  balance,  // SOTA: Balance info
  sharkTankStatus,  // SOTA: Shark Tank display
  onClosePosition,
  onCloseAllPositions,
  onCancelOrder,
  onCancelAllOrders,
  onRefresh,
  isLoading = false,
}) => {
  const [activeTab, setActiveTab] = useState<'positions' | 'orders'>('positions');
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [expandedOrderId, setExpandedOrderId] = useState<string | null>(null);  // SOTA: For collapsible orders
  const [isRefreshing, setIsRefreshing] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const startYRef = useRef(0);
  const [pullDistance, setPullDistance] = useState(0);

  const PULL_THRESHOLD = 80;

  /**
   * Handle pull-to-refresh
   */
  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    if (containerRef.current?.scrollTop === 0) {
      startYRef.current = e.touches[0].clientY;
    }
  }, []);

  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    if (startYRef.current === 0) return;

    const currentY = e.touches[0].clientY;
    const diff = currentY - startYRef.current;

    if (diff > 0 && containerRef.current?.scrollTop === 0) {
      setPullDistance(Math.min(diff * 0.5, PULL_THRESHOLD * 1.5));
    }
  }, []);

  const handleTouchEnd = useCallback(async () => {
    if (pullDistance >= PULL_THRESHOLD && !isRefreshing) {
      setIsRefreshing(true);
      try {
        await onRefresh();
      } finally {
        setIsRefreshing(false);
      }
    }
    setPullDistance(0);
    startYRef.current = 0;
  }, [pullDistance, isRefreshing, onRefresh]);

  const handleToggle = useCallback((id: string) => {
    setExpandedId(prev => prev === id ? null : id);
  }, []);

  // Calculate total PnL
  const totalPnl = positions.reduce((sum, pos) => {
    const symbolLower = pos.symbol.toLowerCase();
    const positionPrice = useMarketStore.getState().positionPrices[symbolLower];
    const liveClose = useMarketStore.getState().symbolData[symbolLower]?.data1m?.close;
    const currentPrice = positionPrice?.price || liveClose || pos.current_price || pos.entry_price;
    const sz = pos.size || pos.quantity || 0;
    const sideMultiplier = pos.side === 'LONG' ? 1 : -1;
    return sum + (currentPrice - pos.entry_price) * sz * sideMultiplier;
  }, 0);

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        backgroundColor: COLORS.bgPrimary,
      }}
    >
      {/* SOTA: Shark Tank Watchlist - Mobile Version */}
      {sharkTankStatus && (
        <div style={{ padding: '8px 12px', borderBottom: `1px solid ${COLORS.bgTertiary}` }}>
          <SharkTankWatchlist
            maxPositions={sharkTankStatus.max_positions}
            currentPositions={sharkTankStatus.current_positions}
            availableSlots={sharkTankStatus.available_slots}
            leverage={sharkTankStatus.leverage}
            availableMargin={sharkTankStatus.available_margin}
            tradingMode={sharkTankStatus.trading_mode || 'PAPER'}
            watchedTokens={sharkTankStatus.watched_tokens || []}
            positionSymbols={sharkTankStatus.position_symbols || []}
            pendingSymbols={sharkTankStatus.pending_symbols || []}
            queuedSignals={sharkTankStatus.pending_list || []}
            onTokenClick={(symbol) => {
              window.dispatchEvent(new CustomEvent('switchSymbol', { detail: symbol }));
            }}
          />
        </div>
      )}

      {/* Mobile Tabs */}
      <div style={{
        display: 'flex',
        borderBottom: `1px solid ${COLORS.bgTertiary}`,
        backgroundColor: COLORS.bgSecondary,
      }}>
        <div
          onClick={() => setActiveTab('positions')}
          style={{
            flex: 1,
            textAlign: 'center',
            padding: '10px',
            fontSize: 13,
            fontWeight: 600,
            cursor: 'pointer',
            color: activeTab === 'positions' ? COLORS.textPrimary : COLORS.textTertiary,
            borderBottom: activeTab === 'positions' ? `2px solid ${COLORS.yellow}` : 'none'
          }}
        >
          Positions ({positions.length})
        </div>
        <div
          onClick={() => setActiveTab('orders')}
          style={{
            flex: 1,
            textAlign: 'center',
            padding: '10px',
            fontSize: 13,
            fontWeight: 600,
            cursor: 'pointer',
            color: activeTab === 'orders' ? COLORS.textPrimary : COLORS.textTertiary,
            borderBottom: activeTab === 'orders' ? `2px solid ${COLORS.yellow}` : 'none'
          }}
        >
          Orders ({pendingOrders.length})
        </div>
      </div>

      {/* Scrollable Content */}
      <div
        ref={containerRef}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
        style={{
          flex: 1,
          overflowY: 'auto',
          WebkitOverflowScrolling: 'touch',
          padding: 12,
          paddingTop: pullDistance > 0 ? pullDistance + 12 : 12,
          transition: pullDistance === 0 ? 'padding-top 0.3s ease' : 'none',
        }}
      >
        {/* Pull-to-refresh indicator */}
        {pullDistance > 0 && (
          <div style={{
            position: 'absolute',
            top: 40,
            left: 0,
            right: 0,
            height: pullDistance,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 10
          }}>
            <RefreshCw
              size={24}
              color={pullDistance >= PULL_THRESHOLD ? COLORS.buy : COLORS.textTertiary}
              style={{
                transform: `rotate(${pullDistance * 2}deg)`,
                transition: 'color 0.2s ease',
              }}
            />
          </div>
        )}

        {/* Refreshing indicator */}
        {(isRefreshing || isLoading) && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 12,
            marginBottom: 12,
          }}>
            <RefreshCw
              size={20}
              color={COLORS.buy}
              style={{ animation: 'spin 1s linear infinite' }}
            />
            <span style={{ marginLeft: 8, fontSize: 13, color: COLORS.textSecondary }}>
              {isLoading ? 'Loading...' : 'Refreshing...'}
            </span>
          </div>
        )}

        {activeTab === 'positions' ? (
          <>
            {/* SOTA Balance Summary Card (Binance Style) */}
            <div style={{
              background: 'linear-gradient(135deg, rgba(30, 35, 41, 0.9), rgba(24, 26, 32, 0.95))',
              backdropFilter: 'blur(12px)',
              borderRadius: 12,
              padding: 14,
              marginBottom: 12,
              border: `1px solid ${COLORS.bgTertiary}`,
            }}>
              {/* Balance Row */}
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(3, 1fr)',
                gap: 12,
                marginBottom: balance ? 12 : 0,
              }}>
                {/* Wallet Balance */}
                <div>
                  <div style={{ fontSize: 10, color: COLORS.textTertiary, textTransform: 'uppercase', marginBottom: 2 }}>
                    Wallet
                  </div>
                  <div style={{
                    fontSize: 14,
                    fontWeight: 700,
                    color: COLORS.textPrimary,
                    fontFamily: 'monospace',
                  }}>
                    ${balance?.wallet_balance?.toFixed(2) || '---'}
                  </div>
                </div>

                {/* Available Balance */}
                <div>
                  <div style={{ fontSize: 10, color: COLORS.textTertiary, textTransform: 'uppercase', marginBottom: 2 }}>
                    Available
                  </div>
                  <div style={{
                    fontSize: 14,
                    fontWeight: 700,
                    color: COLORS.yellow,
                    fontFamily: 'monospace',
                  }}>
                    ${balance?.available_balance?.toFixed(2) || '---'}
                  </div>
                </div>

                {/* Unrealized PnL */}
                <div>
                  <div style={{ fontSize: 10, color: COLORS.textTertiary, textTransform: 'uppercase', marginBottom: 2 }}>
                    Unrealized
                  </div>
                  <div style={{
                    fontSize: 14,
                    fontWeight: 700,
                    color: totalPnl >= 0 ? COLORS.buy : COLORS.sell,
                    fontFamily: 'monospace',
                  }}>
                    {totalPnl >= 0 ? '+' : ''}{totalPnl.toFixed(2)}
                  </div>
                </div>
              </div>
            </div>

            {/* Position Cards */}
            {positions.length === 0 ? (
              <div style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                padding: 48,
                color: COLORS.textTertiary,
              }}>
                <Briefcase size={36} style={{ marginBottom: 12, opacity: 0.3 }} />
                <div style={{ fontSize: 13 }}>No open positions</div>
              </div>
            ) : (
              positions.map(pos => (
                <PositionCard
                  key={pos.id}
                  position={pos}
                  isExpanded={expandedId === pos.id}
                  onToggle={() => handleToggle(pos.id)}
                  onClose={() => onClosePosition(pos.id)}
                />
              ))
            )}

            {/* Close All Button - MOVED TO BOTTOM */}
            {positions.length > 0 && (
              <div style={{ marginTop: 24, marginBottom: 40 }}>
                <ResponsiveButton
                  variant="danger"
                  fullWidth
                  onClick={onCloseAllPositions}
                  style={{
                    opacity: 0.8,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: 6,
                    height: 48,
                    fontSize: 14
                  }}
                >
                  <XCircle size={18} /> Close All Positions ({positions.length})
                </ResponsiveButton>
                <div style={{ textAlign: 'center', fontSize: 10, color: COLORS.textTertiary, marginTop: 8 }}>
                  Tap to close all open positions
                </div>
              </div>
            )}
          </>
        ) : (
          <>
            {/* Orders Tab */}
            {pendingOrders.length === 0 ? (
              <div style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                padding: 48,
                color: COLORS.textTertiary,
              }}>
                <Clock size={36} style={{ marginBottom: 12, opacity: 0.3 }} />
                <div style={{ fontSize: 13 }}>No open orders</div>
              </div>
            ) : (
              pendingOrders.map(order => (
                <PendingOrderCard
                  key={order.id}
                  order={order}
                  isExpanded={expandedOrderId === order.id}
                  onToggle={() => setExpandedOrderId(prev => prev === order.id ? null : order.id)}
                  onCancel={() => onCancelOrder(order.symbol)}
                />
              ))
            )}

            {/* Cancel All Button - MOVED TO BOTTOM */}
            {pendingOrders.length > 0 && (
              <div style={{ marginTop: 24, marginBottom: 40 }}>
                <ResponsiveButton
                  variant="secondary"
                  fullWidth
                  onClick={onCancelAllOrders}
                  style={{
                    border: `1px solid ${COLORS.sell}50`,
                    color: COLORS.sell,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: 6,
                    height: 44
                  }}
                >
                  <XCircle size={16} /> Cancel All Orders ({pendingOrders.length})
                </ResponsiveButton>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default PortfolioMobile;
