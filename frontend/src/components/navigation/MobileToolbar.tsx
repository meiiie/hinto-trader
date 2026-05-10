/**
 * MobileToolbar - Compact toolbar for mobile with essential controls
 * SOTA: Binance Mobile UI Pattern 2026
 *
 * Features:
 * - Balance display (32px height)
 * - Signal count
 * - IP Update button (UnlockAccessButton compact)
 */

import React from 'react';
import { Wallet, Activity } from 'lucide-react';
import { THEME } from '../../styles/theme';
import { UnlockAccessButton } from '../UnlockAccessButton';

export interface MobileToolbarProps {
    balance: number;
    isLiveTrading: boolean;
    signalCount: number;
}

/**
 * MobileToolbar Component
 * Compact toolbar below header with critical trading info
 */
export const MobileToolbar: React.FC<MobileToolbarProps> = ({
    balance,
    isLiveTrading,
    signalCount,
}) => {
    const balanceColor = isLiveTrading ? '#ef4444' : THEME.status.buy;

    return (
        <div style={{
            height: 36,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '0 12px',
            backgroundColor: THEME.bg.secondary,
            borderBottom: `1px solid ${THEME.border.primary}`,
            gap: 8,
        }}>
            {/* Balance */}
            <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
            }}>
                <Wallet size={14} color={balanceColor} />
                <span style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: 12,
                    fontWeight: 600,
                    color: balanceColor,
                }}>
                    {new Intl.NumberFormat('en-US', {
                        style: 'currency',
                        currency: 'USD',
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2,
                    }).format(balance)}
                </span>
                <span style={{
                    fontSize: 9,
                    fontWeight: 700,
                    textTransform: 'uppercase',
                    color: THEME.text.tertiary,
                }}>
                    {isLiveTrading ? 'Real' : 'Virtual'}
                </span>
            </div>

            {/* Signal Count */}
            <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: 4,
            }}>
                <Activity size={12} color={THEME.accent.yellow} />
                <span style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: 11,
                    fontWeight: 600,
                    color: THEME.text.secondary,
                }}>
                    {signalCount}
                </span>
                <span style={{
                    fontSize: 9,
                    color: THEME.text.tertiary,
                }}>
                    signals
                </span>
            </div>

            {/* IP Update Button - Compact */}
            <UnlockAccessButton compact />
        </div>
    );
};

export default MobileToolbar;
