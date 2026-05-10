import React from 'react';
import { useActiveData1m } from '../stores/marketStore';
import { THEME } from '../styles/theme';

export const MomentumWidget: React.FC = () => {
    const marketData = useActiveData1m();

    if (!marketData?.velocity) return null;

    const { value, is_fomo, is_crash } = marketData.velocity;
    const absValue = Math.abs(value);

    // Determine State and Color
    let stateLabel = 'Normal';
    let color = THEME.text.secondary;
    let bgColor = 'rgba(255,255,255,0.05)';

    if (is_fomo) {
        stateLabel = 'FOMO';
        color = '#F0B90B'; // Gold
        bgColor = 'rgba(240, 185, 11, 0.15)';
    } else if (is_crash) {
        stateLabel = 'CRASH';
        color = '#F6465D'; // Red
        bgColor = 'rgba(246, 70, 93, 0.15)';
    } else if (absValue > 0.5) {
        stateLabel = 'High Vol';
        color = '#2196F3'; // Blue
        bgColor = 'rgba(33, 150, 243, 0.15)';
    } else if (absValue < 0.1) {
        stateLabel = 'Low Vol';
        color = THEME.text.tertiary;
        bgColor = 'rgba(133, 133, 133, 0.15)';
    }

    // Format value
    const formattedValue = `${value > 0 ? '+' : ''}${value.toFixed(2)}%/m`;

    return (
        <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            padding: '6px 12px',
            borderRadius: '8px',
            backgroundColor: bgColor,
            border: `1px solid ${color}40`,
            minWidth: '120px',
        }}>
            {/* Icon Placeholder (Activity) */}
            <div style={{ color: color }}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>
                </svg>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column' }}>
                <span style={{
                    fontSize: '10px',
                    fontWeight: 700,
                    textTransform: 'uppercase',
                    color: THEME.text.tertiary,
                    lineHeight: 1
                }}>
                    Velocity
                </span>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span style={{
                        fontFamily: "'JetBrains Mono', monospace",
                        fontWeight: 700,
                        fontSize: '12px',
                        color: color
                    }}>
                        {formattedValue}
                    </span>
                    <span style={{
                        fontSize: '10px',
                        padding: '1px 4px',
                        borderRadius: '3px',
                        backgroundColor: color,
                        color: '#000',
                        fontWeight: 700
                    }}>
                        {stateLabel}
                    </span>
                </div>
            </div>
        </div>
    );
};
