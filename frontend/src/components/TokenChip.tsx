import React from 'react';
import { TrendingUp, TrendingDown, Clock, Lock, Eye, RefreshCw } from 'lucide-react';

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

export type TokenState = 'position' | 'pending' | 'locked' | 'watching' | 'signal';

export interface TokenChipProps {
    symbol: string;
    state: TokenState;
    side?: 'LONG' | 'SHORT';
    pnl?: number;
    distancePct?: number;
    confidence?: number;  // NEW: Signal confidence (0-1)
    rank?: number;        // NEW: Position in ranking
    onClick?: () => void;
}

/**
 * TokenChip - Professional token display chip for Shark Tank Watchlist
 *
 * States:
 * - position: Active position with PnL
 * - pending: Pending order waiting to fill
 * - locked: Pending order near fill (PROXIMITY SENTRY)
 * - watching: Token being monitored
 * - signal: Token with active signal
 */
export const TokenChip: React.FC<TokenChipProps> = ({
    symbol,
    state,
    side,
    pnl = 0,
    distancePct,
    confidence,
    rank: _rank,  // Kept for future tooltip use
    onClick
}) => {
    // Determine colors based on state
    const getStateColors = () => {
        switch (state) {
            case 'position':
                return {
                    bg: side === 'LONG' ? `${COLORS.buy}20` : `${COLORS.sell}20`,
                    border: side === 'LONG' ? COLORS.buy : COLORS.sell,
                    glow: side === 'LONG' ? `0 0 8px ${COLORS.buy}40` : `0 0 8px ${COLORS.sell}40`
                };
            case 'pending':
                return {
                    bg: COLORS.bgTertiary,
                    border: COLORS.textTertiary,
                    glow: 'none'
                };
            case 'locked':
                return {
                    bg: `${COLORS.yellow}15`,
                    border: COLORS.yellow,
                    glow: `0 0 12px ${COLORS.yellow}30`
                };
            case 'signal':
                return {
                    bg: `${COLORS.yellow}25`,
                    border: COLORS.yellow,
                    glow: `0 0 15px ${COLORS.yellow}50`
                };
            case 'watching':
            default:
                return {
                    bg: COLORS.bgSecondary,
                    border: COLORS.bgTertiary,
                    glow: 'none'
                };
        }
    };

    const colors = getStateColors();
    const isLong = side === 'LONG';
    const sideColor = isLong ? COLORS.buy : COLORS.sell;

    // Get icon based on state
    const getIcon = () => {
        switch (state) {
            case 'position':
                return isLong
                    ? <TrendingUp size={12} color={COLORS.buy} />
                    : <TrendingDown size={12} color={COLORS.sell} />;
            case 'pending':
                return <Clock size={12} color={COLORS.textSecondary} />;
            case 'locked':
                return <Lock size={12} color={COLORS.yellow} />;
            case 'signal':
                return <RefreshCw size={12} color={COLORS.yellow} />;
            case 'watching':
            default:
                return <Eye size={11} color={COLORS.textTertiary} />;
        }
    };

    return (
        <div
            onClick={onClick}
            style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '5px',
                padding: '4px 10px',
                borderRadius: '6px',
                background: colors.bg,
                border: `1px solid ${colors.border}`,
                boxShadow: colors.glow,
                cursor: onClick ? 'pointer' : 'default',
                transition: 'all 0.2s ease',
                fontSize: '11px',
                fontWeight: 600,
            }}
            title={
                state === 'locked'
                    ? `🔒 LOCKED - ${distancePct?.toFixed(2)}% từ fill`
                    : state === 'pending'
                        ? `⏳ Pending @ ${distancePct?.toFixed(2)}% away`
                        : state === 'position'
                            ? `${side} | PnL: $${pnl?.toFixed(2)}`
                            : `👁️ Watching`
            }
        >
            {getIcon()}
            <span style={{
                color: state === 'position' ? sideColor : COLORS.textPrimary,
                letterSpacing: '0.3px'
            }}>
                {symbol}
            </span>

            {/* PnL for positions */}
            {state === 'position' && pnl !== undefined && (
                <span style={{
                    fontSize: '10px',
                    color: pnl >= 0 ? COLORS.buy : COLORS.sell,
                    fontFamily: 'monospace'
                }}>
                    {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}
                </span>
            )}

            {/* Distance + Confidence for pending/locked */}
            {(state === 'pending' || state === 'locked') && (
                <span style={{
                    fontSize: '9px',
                    color: state === 'locked' ? COLORS.yellow : COLORS.textTertiary,
                    fontFamily: 'monospace'
                }}>
                    {confidence !== undefined && (
                        <span style={{ color: COLORS.buy, marginRight: '3px' }}>
                            {(confidence * 100).toFixed(0)}%
                        </span>
                    )}
                    {distancePct !== undefined && (
                        <span>{distancePct.toFixed(1)}%</span>
                    )}
                </span>
            )}
        </div>
    );
};

export default TokenChip;
