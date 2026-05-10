import { useState, useEffect } from 'react';

// Design tokens
const C = {
  up: '#0ECB81',
  down: '#F6465D',
  yellow: '#F0B90B',
  bg: '#0B0E11',
  card: '#1E2329',
  border: '#2B3139',
  text1: '#EAECEF',
  text2: '#848E9C',
  text3: '#5E6673',
};

export interface TradingSignal {
  id: string;  // Backend UUID or custom fallback
  type: 'BUY' | 'SELL';
  symbol: string;
  priority?: 'HIGH' | 'MEDIUM' | 'LOW'; // SOTA: Signal Priority
  timestamp: string;  // generated_at
  entry: number;
  stopLoss: number;
  takeProfit1: number;
  takeProfit2?: number;
  takeProfit3?: number;
  confidence: number; // 0-100
  rrRatio: number;
  strategy: string;
  reasons?: string[]; // SOTA: Display detailed logic (including HTF)
  indicators: {
    vwap?: number;
    rsi?: number;
    adx?: number;
    stochK?: number;
    stochD?: number;
  };
  status?: 'generated' | 'pending' | 'executed' | 'expired' | 'rejected';
  // Execution tracking fields (from backend)
  pendingAt?: string;
  executedAt?: string;
  executionLatencyMs?: number;
  orderId?: string;
}

interface SignalCardProps {
  signal: TradingSignal | null;
  currentPrice: number;
  onExecute?: (signal: TradingSignal) => void;
  onDismiss?: () => void;
  compact?: boolean; // SOTA: Compact mode for mobile
}

export default function SignalCard({ signal, currentPrice, onExecute, onDismiss, compact = false }: SignalCardProps) {
  const [isExpanded, setIsExpanded] = useState(!compact); // Default collapsed on mobile compact
  const [countdown, setCountdown] = useState(60);

  // Auto-expand if NOT in compact mode, or manual toggle
  useEffect(() => {
    if (!compact) setIsExpanded(true);
  }, [compact]);

  // Countdown timer for signal validity
  useEffect(() => {
    if (!signal) return;
    setCountdown(60);
    const timer = setInterval(() => {
      setCountdown(prev => {
        if (prev <= 1) {
          clearInterval(timer);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [signal?.id]);

  if (!signal) {
    if (compact) return null; // Hide completely in compact mode if no signal
    return (
      <div style={{
        padding: '16px',
        backgroundColor: C.card,
        borderRadius: '8px',
        border: `1px solid ${C.border}`,
      }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', textAlign: 'center', color: C.text3, fontSize: '13px' }}>
          {/* Professional SVG Radar Icon with pulse animation */}
          <svg
            width="32"
            height="32"
            viewBox="0 0 24 24"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            style={{ marginBottom: '8px' }}
          >
            {/* Radar waves with animation */}
            <circle
              cx="12"
              cy="12"
              r="10"
              stroke={C.text3}
              strokeWidth="1"
              strokeOpacity="0.3"
              fill="none"
            />
            <circle
              cx="12"
              cy="12"
              r="6"
              stroke={C.text3}
              strokeWidth="1"
              strokeOpacity="0.5"
              fill="none"
            />
            <circle
              cx="12"
              cy="12"
              r="2"
              fill={C.yellow}
            />
            {/* Radar sweep line */}
            <line
              x1="12"
              y1="12"
              x2="12"
              y2="2"
              stroke={C.yellow}
              strokeWidth="1.5"
              strokeLinecap="round"
              style={{
                transformOrigin: '12px 12px',
                animation: 'spin 2s linear infinite',
              }}
            />
          </svg>
          <style>{`
            @keyframes spin {
              from { transform: rotate(0deg); }
              to { transform: rotate(360deg); }
            }
          `}</style>
          Waiting for signal...
        </div>
      </div>
    );
  }

  const isBuy = signal.type === 'BUY';
  const isHighPriority = signal.priority === 'HIGH';
  const signalColor = isBuy ? C.up : C.down;
  const borderColor = isHighPriority ? C.yellow : signalColor; // Gold border for High Priority
  const boxShadow = isHighPriority ? `0 0 30px ${C.yellow}66` : `0 0 20px ${signalColor}33`;

  const riskAmount = Math.abs(signal.entry - signal.stopLoss);
  const riskPercent = ((riskAmount / signal.entry) * 100).toFixed(2);
  const distanceToEntry = ((currentPrice - signal.entry) / signal.entry * 100).toFixed(2);

  const formatPrice = (price: number) => price.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });

  const getConfidenceColor = (conf: number) => {
    if (conf >= 80) return C.up;
    if (conf >= 60) return C.yellow;
    return C.down;
  };

  return (
    <div style={{
      backgroundColor: C.card,
      borderRadius: '8px',
      border: `1px solid ${borderColor}`,
      overflow: 'hidden',
      boxShadow: compact ? 'none' : boxShadow, // Reduce glow on mobile
      transition: 'all 0.3s ease-in-out',
      animation: isHighPriority && !compact ? 'pulse-border 2s infinite' : 'none'
    }}>
      <style>{`
        @keyframes pulse-border {
          0% { border-color: ${C.yellow}44; }
          50% { border-color: ${C.yellow}; }
          100% { border-color: ${C.yellow}44; }
        }
      `}</style>
      {/* Header */}
      <div
        onClick={() => setIsExpanded(!isExpanded)}
        style={{
          padding: compact ? '8px 12px' : '12px 16px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          backgroundColor: `${signalColor}15`,
          cursor: 'pointer',
          borderBottom: isExpanded ? `1px solid ${C.border}` : 'none',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: compact ? '8px' : '12px' }}>
          <div style={{
            width: compact ? '24px' : '32px',
            height: compact ? '24px' : '32px',
            borderRadius: '50%',
            backgroundColor: signalColor,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: compact ? '12px' : '16px',
            color: '#fff',
            fontWeight: 700
          }}>
            {isBuy ? '↑' : '↓'}
          </div>
          <div>
            <div style={{
              fontSize: compact ? '14px' : '16px',
              fontWeight: 700,
              color: signalColor,
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
            }}>
              {signal.type} {signal.symbol.toUpperCase()}
              {!compact && (
                <span style={{
                  fontSize: '10px',
                  padding: '2px 6px',
                  borderRadius: '4px',
                  backgroundColor: C.border,
                  color: C.text2,
                }}>
                  {signal.strategy}
                </span>
              )}
              {/* Compact Priority Badge */}
              {signal.priority && (
                <span style={{
                  fontSize: '9px',
                  padding: '2px 6px',
                  borderRadius: '4px',
                  backgroundColor: signal.priority === 'HIGH' ? '#ffc10733' : '#9e9e9e33',
                  color: signal.priority === 'HIGH' ? '#ffc107' : '#9e9e9e',
                  fontWeight: 800,
                  border: signal.priority === 'HIGH' ? '1px solid #ffc107' : 'none',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px'
                }}>
                  {signal.priority === 'HIGH' ? '!!!' : signal.priority}
                </span>
              )}
            </div>
            {!compact && (
              <div style={{ fontSize: '11px', color: C.text3 }}>
                {new Date(signal.timestamp).toLocaleTimeString()}
              </div>
            )}
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {/* Confidence Badge - simplified for compact */}
          <div style={{
            padding: compact ? '2px 6px' : '4px 10px',
            borderRadius: '12px',
            backgroundColor: `${getConfidenceColor(signal.confidence)}20`,
            border: `1px solid ${getConfidenceColor(signal.confidence)}`,
          }}>
            <span style={{
              fontSize: compact ? '10px' : '12px',
              fontWeight: 700,
              color: getConfidenceColor(signal.confidence)
            }}>
              {signal.confidence}%
            </span>
          </div>

          {/* Countdown */}
          <div style={{
            fontSize: compact ? '10px' : '11px',
            color: countdown < 15 ? C.down : C.text2,
            fontFamily: "'JetBrains Mono', monospace",
          }}>
            {countdown}s
          </div>

          <span style={{ color: C.text3, fontSize: '14px' }}>
            {isExpanded ? '▼' : '▶'}
          </span>
        </div>
      </div>

      {/* Body */}
      {isExpanded && (
        <div style={{ padding: compact ? '12px' : '16px' }}>
          {/* Price Levels - Grid Layout */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(4, 1fr)',
            gap: compact ? '8px' : '12px',
            marginBottom: compact ? '12px' : '16px',
          }}>
            <PriceLevel label="Entry" value={signal.entry} color={C.yellow} compact={compact} />
            <PriceLevel label="SL" value={signal.stopLoss} color={C.down} compact={compact} />
            <PriceLevel label="TP1" value={signal.takeProfit1} color={C.up} compact={compact} />
            <PriceLevel label="RR" value={signal.rrRatio} color={C.text1} isRatio compact={compact} />
          </div>

          {/* Stats Row - Hide on compact to save space */}
          {!compact && (
            <div style={{
              display: 'flex',
              justifyContent: 'space-between',
              padding: '12px',
              backgroundColor: C.bg,
              borderRadius: '6px',
              marginBottom: '16px',
            }}>
              <StatItem label="R:R Ratio" value={`1:${signal.rrRatio.toFixed(1)}`} />
              <StatItem label="Risk" value={`${riskPercent}%`} color={C.down} />
              <StatItem label="Distance" value={`${distanceToEntry}%`} />
              <StatItem label="Current" value={`$${formatPrice(currentPrice)}`} />
            </div>
          )}

          {/* Indicators - Hide on compact if not critical */}
          {!compact && signal.indicators && (
            <div style={{
              display: 'flex',
              gap: '16px',
              marginBottom: '16px',
              fontSize: '11px',
              color: C.text2,
            }}>
              {signal.indicators.rsi && (
                <span>RSI: <span style={{ color: C.text1 }}>{signal.indicators.rsi.toFixed(1)}</span></span>
              )}
              {signal.indicators.adx && (
                <span>ADX: <span style={{ color: C.text1 }}>{signal.indicators.adx.toFixed(1)}</span></span>
              )}
            </div>
          )}

          {/* Reasons List - Hide on compact unless crucial */}
          {!compact && signal.reasons && signal.reasons.length > 0 && (
            <div style={{
              marginBottom: '16px',
              padding: '10px',
              backgroundColor: C.bg,
              borderRadius: '6px',
              borderLeft: `2px solid ${signalColor}`
            }}>
              <div style={{ fontSize: '10px', color: C.text3, marginBottom: '6px', textTransform: 'uppercase', fontWeight: 700 }}>
                Signal Confluence
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                {signal.reasons.map((reason, idx) => (
                  <div key={idx} style={{
                    fontSize: '11px',
                    color: reason.includes('✓') ? C.up : reason.includes('✗') || reason.includes('🚫') ? C.down : C.text2,
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px'
                  }}>
                    {reason}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Action Buttons */}
          <div style={{ display: 'flex', gap: '12px' }}>
            <button
              onClick={() => onExecute?.(signal)}
              disabled={countdown === 0}
              style={{
                flex: 1,
                padding: compact ? '8px' : '12px',
                fontSize: compact ? '12px' : '14px',
                fontWeight: 700,
                borderRadius: '6px',
                border: 'none',
                cursor: countdown === 0 ? 'not-allowed' : 'pointer',
                backgroundColor: countdown === 0 ? C.border : signalColor,
                color: countdown === 0 ? C.text3 : '#000',
                transition: 'all 0.2s',
              }}
            >
              {countdown === 0 ? 'Expired' : `EXECUTE`}
            </button>
            <button
              onClick={onDismiss}
              style={{
                padding: compact ? '8px 16px' : '12px 20px',
                fontSize: compact ? '12px' : '14px',
                fontWeight: 500,
                borderRadius: '6px',
                border: `1px solid ${C.border}`,
                cursor: 'pointer',
                backgroundColor: 'transparent',
                color: C.text2,
              }}
            >
              Dismiss
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function PriceLevel({ label, value, color, isRatio = false, compact = false }: { label: string; value: number; color: string; isRatio?: boolean; compact?: boolean }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: compact ? '9px' : '10px', color: C.text3, marginBottom: '2px' }}>{label}</div>
      <div style={{
        fontSize: compact ? '12px' : '14px',
        fontWeight: 700,
        color,
        fontFamily: "'JetBrains Mono', monospace",
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis'
      }}>
        {isRatio ? `1:${value.toFixed(1)}` : `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
      </div>
    </div>
  );
}

function StatItem({ label, value, color = C.text1 }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: '10px', color: C.text3, marginBottom: '2px' }}>{label}</div>
      <div style={{ fontSize: '13px', fontWeight: 600, color }}>{value}</div>
    </div>
  );
}
