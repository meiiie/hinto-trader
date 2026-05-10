
import React from 'react';

interface SignalLogItemProps {
  time: string;
  action: string;
  adx?: number;
  trend: 'BULLISH' | 'BEARISH' | 'NEUTRAL';
}

/**
 * SignalLogItem - Inline styles for guaranteed fixed columns
 */
const SignalLogItem: React.FC<SignalLogItemProps> = ({ time, action, adx, trend }) => {
  const trendColor = trend === 'BULLISH' ? '#10B981' : trend === 'BEARISH' ? '#F43F5E' : '#5E6673';
  const trendLabel = trend === 'BULLISH' ? 'BULL' : trend === 'BEARISH' ? 'BEAR' : '---';

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      padding: '4px 0',
      borderBottom: '1px solid rgba(39,39,42,0.5)',
      fontSize: '10px',
      fontFamily: "'JetBrains Mono', monospace",
      minHeight: '20px',
    }}>
      {/* Time - 60px fixed */}
      <span style={{ width: '60px', flexShrink: 0, color: '#71717a' }}>{time}</span>

      {/* Action - 40px fixed */}
      <span style={{ width: '40px', flexShrink: 0, color: '#a1a1aa', fontWeight: 600 }}>{action}</span>

      {/* ADX - 50px fixed */}
      <span style={{ width: '50px', flexShrink: 0, color: '#F0B90B' }}>
        {adx && adx > 0 ? `${adx}` : ''}
      </span>

      {/* Trend - remaining space, right aligned */}
      <span style={{ flex: 1, textAlign: 'right', color: trendColor, fontWeight: 700 }}>
        {trendLabel}
      </span>
    </div>
  );
};

export default SignalLogItem;
