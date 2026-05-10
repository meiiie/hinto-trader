import React from 'react';

interface StrategyMonitorProps {
  trendBias: 'LONG' | 'SHORT' | 'NEUTRAL';
  adxValue: number;
  stochRsiValue: number;
}

/**
 * StrategyMonitor - Using inline styles for guaranteed rendering
 */
const StrategyMonitor: React.FC<StrategyMonitorProps> = ({
  trendBias,
  adxValue,
  stochRsiValue
}) => {
  // Colors
  const bull = '#10B981';
  const bear = '#F43F5E';
  const yellow = '#F0B90B';
  const muted = '#5E6673';
  const border = '#2B3139';

  // Bias
  const biasColor = trendBias === 'LONG' ? bull : trendBias === 'SHORT' ? bear : muted;
  const biasLabel = trendBias === 'LONG' ? 'BULLISH' : trendBias === 'SHORT' ? 'BEARISH' : 'NEUTRAL';

  // ADX
  const adxColor = adxValue >= 40 ? bull : adxValue >= 25 ? yellow : muted;
  const adxLabel = adxValue >= 40 ? 'Strong' : adxValue >= 25 ? 'Trend' : 'Weak';
  const adxPercent = Math.min(adxValue, 60) / 60 * 100;

  // StochRSI
  const rsiColor = stochRsiValue <= 20 ? bull : stochRsiValue >= 80 ? bear : yellow;
  const rsiLabel = stochRsiValue <= 20 ? 'Oversold' : stochRsiValue >= 80 ? 'Overbought' : 'Neutral';

  return (
    <div style={{
      padding: '12px',
      borderBottom: `1px solid ${border}`,
      backgroundColor: '#09090b',
      flexShrink: 0,
    }}>
      {/* Title */}
      <div style={{ fontSize: '10px', fontWeight: 700, color: muted, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '12px' }}>
        Market Health
      </div>

      {/* Market Bias */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
        <span style={{ fontSize: '10px', color: '#848E9C', textTransform: 'uppercase' }}>Market Bias</span>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          padding: '2px 8px',
          borderRadius: '4px',
          backgroundColor: `${biasColor}20`,
          border: `1px solid ${biasColor}40`,
        }}>
          <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: biasColor }} />
          <span style={{ fontSize: '11px', fontWeight: 900, color: biasColor, letterSpacing: '0.05em' }}>{biasLabel}</span>
        </div>
      </div>

      {/* ADX Trend Strength */}
      <div style={{ marginBottom: '12px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', fontWeight: 700, color: muted, marginBottom: '4px' }}>
          <span>TREND STRENGTH</span>
          <span style={{ color: adxColor }}>{adxValue} ({adxLabel})</span>
        </div>
        <div style={{ height: '6px', backgroundColor: '#1a1a1a', borderRadius: '3px', overflow: 'hidden' }}>
          <div style={{
            height: '100%',
            width: `${adxPercent}%`,
            backgroundColor: adxColor,
            borderRadius: '3px',
            transition: 'width 0.3s',
          }} />
        </div>
      </div>

      {/* Stoch RSI */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', fontWeight: 700, color: muted, marginBottom: '4px' }}>
          <span>STOCH RSI</span>
          <span style={{ color: rsiColor }}>{stochRsiValue.toFixed(0)} ({rsiLabel})</span>
        </div>
        <div style={{ height: '6px', backgroundColor: '#1a1a1a', borderRadius: '3px', overflow: 'hidden', position: 'relative' }}>
          {/* Zone markers */}
          <div style={{ position: 'absolute', left: '20%', top: 0, bottom: 0, width: '1px', backgroundColor: bull, opacity: 0.5 }} />
          <div style={{ position: 'absolute', left: '80%', top: 0, bottom: 0, width: '1px', backgroundColor: bear, opacity: 0.5 }} />
          <div style={{
            height: '100%',
            width: `${stochRsiValue}%`,
            backgroundColor: rsiColor,
            borderRadius: '3px',
            transition: 'width 0.3s',
          }} />
        </div>
      </div>
    </div>
  );
};

export default StrategyMonitor;
