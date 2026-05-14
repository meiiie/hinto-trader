import React, { useState } from 'react';
import { ChevronDown, ChevronUp, BarChart2, Clock, Eye, Zap } from 'lucide-react';
import { TokenChip } from './TokenChip';
import { formatPrice } from '../styles/theme';
import useMarketStore from '../stores/marketStore';

// --- COLORS (Hinto Pro Style - Synced with Project) ---
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

interface PositionSymbol {
    symbol: string;
    side: 'LONG' | 'SHORT';
    pnl: number;
    // SOTA (Jan 2026): Added for realtime PnL calculation
    entry_price?: number;
    quantity?: number;
}

interface PendingSymbol {
    symbol: string;
    side: string;
    entry_price: number;
    distance_pct: number | null;
    locked: boolean;
    confidence?: number | null;  // NEW: Signal confidence (0-1)
    rank?: number;        // NEW: Position in confidence ranking
}

interface QueuedSignal {
    symbol: string;
    direction: 'buy' | 'sell';
    confidence: number;
    queued_at: string;
}

export interface SharkTankWatchlistProps {
    maxPositions: number;
    currentPositions: number;
    availableSlots: number;
    leverage: number;
    availableMargin: number;
    tradingMode: 'PAPER' | 'TESTNET' | 'LIVE';
    watchedTokens: string[];
    positionSymbols: PositionSymbol[];
    pendingSymbols: PendingSymbol[];
    // SOTA: Batch queue signals (transient, ~5 sec lifetime)
    queuedSignals?: QueuedSignal[];
    onTokenClick?: (symbol: string) => void;
}

/**
 * SharkTankWatchlist - Professional 50-symbol watchlist with collapsible sections
 *
 * SOTA Features:
 * - Positions section with PnL
 * - Pending section with LOCKED indicator (PROXIMITY SENTRY)
 * - Watching section (collapsible, 50 symbols)
 * - Click-to-switch chart functionality
 */
export const SharkTankWatchlist: React.FC<SharkTankWatchlistProps> = ({
    maxPositions,
    currentPositions,
    availableSlots,
    leverage,
    availableMargin,
    tradingMode,
    watchedTokens,
    positionSymbols,
    pendingSymbols,
    queuedSignals = [],
    onTokenClick
}) => {
    const [isWatchingExpanded, setIsWatchingExpanded] = useState(false);

    // SOTA (Jan 2026): Subscribe to positionPrices for realtime PnL
    const positionPrices = useMarketStore(state => state.positionPrices);
    const symbolData = useMarketStore(state => state.symbolData);

    // Calculate watching tokens (exclude positions and pending)
    const activeSymbols = new Set([
        ...positionSymbols.map(p => p.symbol),
        ...pendingSymbols.map(p => p.symbol)
    ]);
    const watchingTokens = watchedTokens.filter(t => !activeSymbols.has(t));

    // SOTA (Jan 2026): Calculate realtime PnL for each position
    const getRealtimePnL = (pos: PositionSymbol): number => {
        // If no entry_price/quantity, fallback to static pnl
        if (!pos.entry_price || !pos.quantity) {
            return pos.pnl;
        }

        const symbolLower = (pos.symbol + 'usdt').toLowerCase();

        // Price fallback chain (same as PortfolioRow)
        const priceFromUpdate = positionPrices[symbolLower]?.price;
        const liveClose = symbolData[symbolLower]?.data1m?.close;
        const currentPrice = priceFromUpdate || liveClose;

        // If no realtime price available, use static pnl
        if (!currentPrice) {
            return pos.pnl;
        }

        // Calculate PnL
        const sideMultiplier = pos.side === 'LONG' ? 1 : -1;
        return (currentPrice - pos.entry_price) * pos.quantity * sideMultiplier;
    };

    // Slot progress
    const slotProgressPct = (currentPositions / maxPositions) * 100;
    const hasSlots = availableSlots > 0;

    // Mode badge colors
    const getModeColors = () => {
        switch (tradingMode) {
            case 'LIVE': return { bg: `${COLORS.sell}20`, color: COLORS.sell };
            case 'TESTNET': return { bg: `${COLORS.buy}20`, color: COLORS.buy };
            case 'PAPER':
            default: return { bg: `${COLORS.yellow}20`, color: COLORS.yellow };
        }
    };
    const modeColors = getModeColors();

    return (
        <div style={{
            background: `linear-gradient(135deg, ${COLORS.bgSecondary} 0%, ${COLORS.bgTertiary}50 100%)`,
            borderRadius: '12px',
            padding: '16px',
            marginBottom: '16px',
            border: `1px solid ${COLORS.yellow}30`
        }}>
            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <span style={{ fontSize: '15px', fontWeight: 700, color: COLORS.yellow }}>
                        🦈 SHARK TANK
                    </span>
                    {/* Mode Badge */}
                    <span style={{
                        fontSize: '10px',
                        fontWeight: 600,
                        padding: '3px 8px',
                        borderRadius: '4px',
                        background: modeColors.bg,
                        color: modeColors.color
                    }}>
                        {tradingMode}
                    </span>
                    {/* Leverage Badge */}
                    <span style={{
                        fontSize: '10px',
                        fontWeight: 600,
                        padding: '3px 8px',
                        borderRadius: '4px',
                        background: `${COLORS.yellow}20`,
                        color: COLORS.yellow
                    }}>
                        {leverage}x
                    </span>
                    {/* Smart Recycling Indicator */}
                    <span
                        title={availableSlots === 0
                            ? "♻️ Smart Recycling: Slots full - better signals will replace weaker pending orders"
                            : "🦈 Slots available - top signals will be executed"}
                        style={{
                            fontSize: '9px',
                            fontWeight: 600,
                            padding: '3px 8px',
                            borderRadius: '4px',
                            background: availableSlots === 0 ? `${COLORS.sell}20` : `${COLORS.buy}20`,
                            color: availableSlots === 0 ? COLORS.sell : COLORS.buy,
                            cursor: 'help'
                        }}
                    >
                        {availableSlots === 0 ? '♻️ RECYCLE' : '🦈 HUNTING'}
                    </span>
                </div>

                {/* Slots Display */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <span style={{ fontSize: '11px', color: COLORS.textSecondary }}>
                        Margin: <span style={{ color: COLORS.buy, fontWeight: 600 }}>${formatPrice(availableMargin)}</span>
                    </span>
                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        padding: '4px 10px',
                        borderRadius: '8px',
                        background: hasSlots ? `${COLORS.buy}15` : `${COLORS.sell}15`,
                        border: `1px solid ${hasSlots ? COLORS.buy : COLORS.sell}40`
                    }}>
                        {/* Progress Bar */}
                        <div style={{
                            width: '40px',
                            height: '4px',
                            borderRadius: '2px',
                            background: COLORS.bgTertiary,
                            overflow: 'hidden'
                        }}>
                            <div style={{
                                width: `${slotProgressPct}%`,
                                height: '100%',
                                background: hasSlots ? COLORS.buy : COLORS.sell,
                                transition: 'width 0.3s ease'
                            }} />
                        </div>
                        <span style={{
                            fontSize: '12px',
                            fontWeight: 700,
                            color: hasSlots ? COLORS.buy : COLORS.sell
                        }}>
                            {currentPositions}/{maxPositions}
                        </span>
                    </div>
                </div>
            </div>

            {/* QUEUED Section (Transient batch queue, ~5 sec) */}
            {queuedSignals.length > 0 && (
                <div style={{ marginBottom: '12px' }}>
                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        marginBottom: '8px',
                        fontSize: '11px',
                        color: COLORS.yellow
                    }}>
                        <Zap size={12} color={COLORS.yellow} />
                        <span>QUEUED ({queuedSignals.length})</span>
                        <span style={{
                            fontSize: '9px',
                            color: COLORS.textTertiary,
                            fontStyle: 'italic'
                        }}>
                            processing...
                        </span>
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                        {queuedSignals.map((sig, idx) => (
                            <div
                                key={`${sig.symbol}-${idx}`}
                                style={{
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: '5px',
                                    padding: '4px 10px',
                                    borderRadius: '6px',
                                    background: `${COLORS.yellow}15`,
                                    border: `1px solid ${COLORS.yellow}40`,
                                    boxShadow: `0 0 8px ${COLORS.yellow}20`,
                                    fontSize: '11px',
                                    animation: 'pulse 1.5s ease-in-out infinite'
                                }}
                                onClick={() => onTokenClick?.(sig.symbol + 'USDT')}
                            >
                                <Zap size={10} color={COLORS.yellow} />
                                <span style={{
                                    color: sig.direction === 'buy' ? COLORS.buy : COLORS.sell,
                                    fontWeight: 600
                                }}>
                                    {sig.symbol.replace('USDT', '')}
                                </span>
                                <span style={{
                                    fontSize: '9px',
                                    color: COLORS.textSecondary,
                                    fontFamily: 'monospace'
                                }}>
                                    {(sig.confidence * 100).toFixed(0)}%
                                </span>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Positions Section */}
            {positionSymbols.length > 0 && (
                <div style={{ marginBottom: '12px' }}>
                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        marginBottom: '8px',
                        fontSize: '11px',
                        color: COLORS.textSecondary
                    }}>
                        <BarChart2 size={12} color={COLORS.buy} />
                        <span>POSITIONS ({positionSymbols.length})</span>
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                        {positionSymbols.map((pos) => {
                            // SOTA (Jan 2026): Use realtime PnL
                            const realtimePnl = getRealtimePnL(pos);
                            return (
                                <TokenChip
                                    key={pos.symbol}
                                    symbol={pos.symbol}
                                    state="position"
                                    side={pos.side}
                                    pnl={realtimePnl}
                                    onClick={() => onTokenClick?.(pos.symbol + 'USDT')}
                                />
                            );
                        })}
                    </div>
                </div>
            )}

            {/* Pending Section */}
            {pendingSymbols.length > 0 && (
                <div style={{ marginBottom: '12px' }}>
                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        marginBottom: '8px',
                        fontSize: '11px',
                        color: COLORS.textSecondary
                    }}>
                        <Clock size={12} color={COLORS.yellow} />
                        <span>PENDING ({pendingSymbols.length})</span>
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                        {pendingSymbols.map((order) => (
                            <TokenChip
                                key={order.symbol}
                                symbol={order.symbol}
                                state={order.locked ? 'locked' : 'pending'}
                                side={['BUY', 'LONG'].includes(order.side) ? 'LONG' : 'SHORT'}
                                distancePct={order.distance_pct}
                                confidence={order.confidence}
                                rank={order.rank}
                                onClick={() => onTokenClick?.(order.symbol + 'USDT')}
                            />
                        ))}
                    </div>
                </div>
            )}

            {/* Watching Section (Collapsible) */}
            <div>
                <div
                    onClick={() => setIsWatchingExpanded(!isWatchingExpanded)}
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: '6px',
                        marginBottom: '8px',
                        fontSize: '11px',
                        color: COLORS.textSecondary,
                        cursor: 'pointer'
                    }}
                >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <Eye size={12} color={COLORS.textTertiary} />
                        <span>WATCHING ({watchingTokens.length})</span>
                    </div>
                    {isWatchingExpanded
                        ? <ChevronUp size={14} color={COLORS.textTertiary} />
                        : <ChevronDown size={14} color={COLORS.textTertiary} />
                    }
                </div>

                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                    {/* Show first 8 or all if expanded */}
                    {(isWatchingExpanded ? watchingTokens : watchingTokens.slice(0, 8)).map((token) => (
                        <TokenChip
                            key={token}
                            symbol={token}
                            state="watching"
                            onClick={() => onTokenClick?.(token + 'USDT')}
                        />
                    ))}

                    {/* Show "more" button if collapsed and there are more tokens */}
                    {!isWatchingExpanded && watchingTokens.length > 8 && (
                        <div
                            onClick={() => setIsWatchingExpanded(true)}
                            style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                padding: '4px 10px',
                                borderRadius: '6px',
                                background: COLORS.bgTertiary,
                                border: `1px solid ${COLORS.bgTertiary}`,
                                cursor: 'pointer',
                                fontSize: '10px',
                                color: COLORS.textTertiary,
                                fontWeight: 500
                            }}
                        >
                            +{watchingTokens.length - 8} more
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

export default SharkTankWatchlist;
