import React, { useMemo } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer } from 'recharts';
import { BacktestChart } from '../components/backtest/BacktestChart';
import THEME from '../styles/theme';
import { useBacktestStore } from '../stores/backtestStore';

// Design tokens - Apple-level consistency with App.tsx
const C = {
  up: THEME.status.buy,
  down: THEME.status.sell,
  yellow: THEME.accent.yellow,
  bg: THEME.bg.primary,
  card: THEME.bg.tertiary,
  border: THEME.border.primary,
  text1: THEME.text.primary,
  text2: THEME.text.secondary,
  text3: THEME.text.tertiary,
};

// Professional SVG Icons
const Icons = {
  Settings: ({ size = 14, color = 'currentColor' }: { size?: number; color?: string }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" /><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
    </svg>
  ),
  ChartBar: ({ size = 48, color = 'currentColor' }: { size?: number; color?: string }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 3v18h18" /><path d="M18 17V9" /><path d="M13 17V5" /><path d="M8 17v-3" />
    </svg>
  ),
  Bolt: ({ size = 12, color = 'currentColor' }: { size?: number; color?: string }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill={color} stroke="none">
      <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
    </svg>
  ),
  Target: ({ size = 12, color = 'currentColor' }: { size?: number; color?: string }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" /><circle cx="12" cy="12" r="6" /><circle cx="12" cy="12" r="2" />
    </svg>
  ),
  TrendUp: ({ size = 12, color = 'currentColor' }: { size?: number; color?: string }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="23 6 13.5 15.5 8.5 10.5 1 18" /><polyline points="17 6 23 6 23 12" />
    </svg>
  ),
  TrendDown: ({ size = 12, color = 'currentColor' }: { size?: number; color?: string }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="23 18 13.5 8.5 8.5 13.5 1 6" /><polyline points="17 18 23 18 23 12" />
    </svg>
  ),
  Download: ({ size = 14, color = 'currentColor' }: { size?: number; color?: string }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" />
    </svg>
  ),
  Shark: ({ size = 14, color = 'currentColor' }: { size?: number; color?: string }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 12c0-3 2.5-6 7-6 3 0 5 1.5 7 4l6-4v12l-6-4c-2 2.5-4 4-7 4-4.5 0-7-3-7-6z" />
      <path d="M10 10v4" />
    </svg>
  ),
  Crosshair: ({ size = 14, color = 'currentColor' }: { size?: number; color?: string }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" /><line x1="22" y1="12" x2="18" y2="12" /><line x1="6" y1="12" x2="2" y2="12" /><line x1="12" y1="6" x2="12" y2="2" /><line x1="12" y1="22" x2="12" y2="18" />
    </svg>
  ),
  // SOTA: Additional icons for stats cards
  DollarSign: ({ size = 14, color = 'currentColor' }: { size?: number; color?: string }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="1" x2="12" y2="23" /><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
    </svg>
  ),
  Percent: ({ size = 14, color = 'currentColor' }: { size?: number; color?: string }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="19" y1="5" x2="5" y2="19" /><circle cx="6.5" cy="6.5" r="2.5" /><circle cx="17.5" cy="17.5" r="2.5" />
    </svg>
  ),
  Scale: ({ size = 14, color = 'currentColor' }: { size?: number; color?: string }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3v18M4 6l16 0M4 6l2 6h12l2-6" /><circle cx="6" cy="12" r="2" /><circle cx="18" cy="12" r="2" />
    </svg>
  ),
  Layers: ({ size = 14, color = 'currentColor' }: { size?: number; color?: string }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="12 2 2 7 12 12 22 7 12 2" /><polyline points="2 17 12 22 22 17" /><polyline points="2 12 12 17 22 12" />
    </svg>
  ),
  Banknote: ({ size = 14, color = 'currentColor' }: { size?: number; color?: string }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="6" width="20" height="12" rx="2" /><circle cx="12" cy="12" r="2" /><path d="M6 12h.01M18 12h.01" />
    </svg>
  ),
};

// Trade type inferred from BacktestResult.trades via Zustand store

const Backtest: React.FC = () => {
  // SOTA: Zustand store for state persistence across tab switches
  const {
    result, setResult,
    params, setParams,
    selectedSymbols, setSelectedSymbols,
    topTokens, setTopTokens,
    loading, setLoading,
    loadingTokens, setLoadingTokens,
    error, setError,
    tradePage,
    incrementTradePage,
    applySharkTankPreset,
    applySniperPreset,
  } = useBacktestStore();

  const [showAdvanced, setShowAdvanced] = React.useState(false);
  const TRADES_PER_PAGE = 20;

  // SOTA: Fetch top tokens on mount
  const fetchTopTokens = async () => {
    setLoadingTokens(true);
    try {
      const res = await fetch('http://localhost:8000/market/top-tokens?limit=10');
      const data = await res.json();
      if (data.tokens) {
        setTopTokens(data.tokens);
      }
    } catch (err) {
      console.error('Failed to fetch top tokens:', err);
      // Fallback
      setTopTokens([
        { rank: 1, symbol: 'BTCUSDT', base: 'BTC', quote: 'USDT', name: 'Bitcoin' },
        { rank: 2, symbol: 'ETHUSDT', base: 'ETH', quote: 'USDT', name: 'Ethereum' },
        { rank: 3, symbol: 'SOLUSDT', base: 'SOL', quote: 'USDT', name: 'Solana' },
        { rank: 4, symbol: 'BNBUSDT', base: 'BNB', quote: 'USDT', name: 'BNB' },
        { rank: 5, symbol: 'XRPUSDT', base: 'XRP', quote: 'USDT', name: 'Ripple' },
      ]);
    } finally {
      setLoadingTokens(false);
    }
  };

  // Fetch on mount
  React.useEffect(() => {
    fetchTopTokens();
  }, []);


  // === Derived Metrics (useMemo for performance) ===
  const maxDrawdown = useMemo(() => {
    if (!result?.equity?.length) return 0;
    let peak = 0;
    let maxDD = 0;
    for (const point of result.equity) {
      if (point.balance > peak) peak = point.balance;
      const dd = peak > 0 ? (point.balance - peak) / peak : 0;
      if (dd < maxDD) maxDD = dd;
    }
    return maxDD * 100; // as percentage
  }, [result]);

  const profitFactor = useMemo(() => {
    if (!result?.trades?.length) return 0;
    let grossProfit = 0;
    let grossLoss = 0;
    for (const t of result.trades) {
      if (t.pnl_usd > 0) grossProfit += t.pnl_usd;
      else grossLoss += Math.abs(t.pnl_usd);
    }
    return grossLoss > 0 ? grossProfit / grossLoss : grossProfit > 0 ? Infinity : 0;
  }, [result]);

  // === Export CSV ===
  const exportCSV = () => {
    if (!result?.trades?.length) return;
    const headers = ['Trade ID', 'Symbol', 'Side', 'Entry Time', 'Exit Time', 'Entry Price', 'Exit Price', 'Qty', 'Margin ($)', 'Notional ($)', 'PnL ($)', 'PnL (%)', 'Reason', 'Leverage'];
    const rows = result.trades.map(t => [
      t.trade_id, t.symbol, t.side,
      new Date(t.entry_time).toISOString(),
      new Date(t.exit_time).toISOString(),
      t.entry_price.toFixed(4), t.exit_price.toFixed(4),
      t.quantity?.toFixed(4) || '',
      t.margin_used?.toFixed(2) || (t.notional_value && t.leverage_at_entry ? (t.notional_value / t.leverage_at_entry).toFixed(2) : ''),
      t.notional_value?.toFixed(2) || '',
      t.pnl_usd.toFixed(2), t.pnl_pct.toFixed(2),
      t.exit_reason, t.leverage_at_entry.toFixed(1)
    ]);
    const csv = [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `backtest_${selectedSymbols.join('_')}_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const runBacktest = async () => {
    setLoading(true);
    setError('');
    setResult(null);

    try {
      // SOTA Phase 1: Refresh Top 10 tokens when Shark Tank mode (10 symbols)
      let symbolsToRun = selectedSymbols;
      if (selectedSymbols.length >= 10) {
        setLoadingTokens(true);
        try {
          const res = await fetch('http://localhost:8000/market/top-tokens?limit=10');
          const data = await res.json();
          if (data.tokens && data.tokens.length > 0) {
            const freshSymbols = data.tokens.map((t: { symbol: string }) => t.symbol);
            setTopTokens(data.tokens);
            setSelectedSymbols(freshSymbols);
            symbolsToRun = freshSymbols;
          }
        } catch (err) {
          console.warn('Failed to refresh top tokens, using cached:', err);
        } finally {
          setLoadingTokens(false);
        }
      }

      // Calculate date range based on dateMode
      let startDate: Date;
      let endDate: Date;

      if (params.dateMode === 'days') {
        // Quick mode: calculate from days
        endDate = new Date();
        startDate = new Date();
        startDate.setDate(startDate.getDate() - params.days);
      } else {
        // Custom mode: use specified dates
        startDate = new Date(params.startDate);
        endDate = new Date(params.endDate);
      }

      const payload = {
        symbols: symbolsToRun,
        interval: params.interval,
        market_mode: params.market_mode,  // SOTA: Spot/Futures mode
        start_time: startDate.toISOString(),
        end_time: endDate.toISOString(),
        initial_balance: params.balance,
        risk_per_trade: params.risk,
        enable_circuit_breaker: params.enable_cb,
        max_positions: params.max_pos,
        // SOTA Hardcore params
        leverage: params.leverage,
        max_order_value: params.max_order,
        maintenance_margin_rate: 0.004, // Binance standard
        max_consecutive_losses: params.max_losses,
        cb_cooldown_hours: params.cb_cooldown,
        cb_drawdown_limit: params.drawdown_limit
      };

      const response = await fetch('http://localhost:8000/backtest/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!response.ok) {
        const errText = await response.text();
        throw new Error(`Error ${response.status}: ${errText}`);
      }

      const data = await response.json();
      setResult(data);
    } catch (err: any) {
      console.error(err);
      setError(err.message || 'Unknown error occurred');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: '24px', backgroundColor: C.bg, color: C.text1, minHeight: '100vh' }}>
      {/* Header - Apple-level minimal */}
      <div style={{ marginBottom: '24px' }}>
        <h1 style={{ fontSize: '20px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px', color: C.text1 }}>
          Quant Lab
        </h1>
        <p style={{ fontSize: '12px', color: C.text3, marginTop: '4px' }}>
          Institutional Backtest Engine • Limit Sniper Strategy
        </p>
      </div>

      {/* Control Panel - Refined */}
      <div style={{
        backgroundColor: C.card,
        padding: '16px',
        borderRadius: '8px',
        marginBottom: '24px',
        display: 'flex',
        gap: '16px',
        alignItems: 'flex-end',
        flexWrap: 'wrap',
        border: `1px solid ${C.border}`,
      }}>
        {/* Symbol */}
        {/* Symbol Selection with Presets */}
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: '16px' }}>
          <div>
            <label style={{ display: 'block', fontSize: '10px', color: C.text3, marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>Mode</label>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                onClick={applySharkTankPreset}
                disabled={topTokens.length === 0}
                style={{
                  padding: '8px 12px',
                  fontSize: '11px',
                  fontWeight: 600,
                  backgroundColor: selectedSymbols.length >= 10 ? C.yellow : 'transparent',
                  color: selectedSymbols.length >= 10 ? '#000' : C.text2,
                  border: `1px solid ${selectedSymbols.length >= 10 ? C.yellow : C.border}`,
                  borderRadius: '6px',
                  cursor: 'pointer',
                }}
              >
                <Icons.Shark size={14} color={selectedSymbols.length >= 10 ? '#000' : C.text2} /> Shark Tank (10)
              </button>
              <button
                onClick={applySniperPreset}
                disabled={topTokens.length === 0}
                style={{
                  padding: '8px 12px',
                  fontSize: '11px',
                  fontWeight: 600,
                  backgroundColor: selectedSymbols.length <= 3 && selectedSymbols.length > 0 ? C.up : 'transparent',
                  color: selectedSymbols.length <= 3 && selectedSymbols.length > 0 ? '#000' : C.text2,
                  border: `1px solid ${selectedSymbols.length <= 3 ? C.up : C.border}`,
                  borderRadius: '6px',
                  cursor: 'pointer',
                }}
              >
                <Icons.Crosshair size={14} color={selectedSymbols.length <= 3 && selectedSymbols.length > 0 ? '#000' : C.text2} /> Sniper (3)
              </button>
            </div>
          </div>
          <div style={{ flex: 1 }}>
            <label style={{ display: 'block', fontSize: '10px', color: C.text3, marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
              Symbols ({selectedSymbols.length}) {loadingTokens && '...'}
            </label>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', maxHeight: '60px', overflowY: 'auto' }}>
              {topTokens.map(token => (
                <button
                  key={token.symbol}
                  onClick={() => {
                    const newSymbols = selectedSymbols.includes(token.symbol)
                      ? selectedSymbols.filter(s => s !== token.symbol)
                      : [...selectedSymbols, token.symbol];
                    setSelectedSymbols(newSymbols);
                  }}
                  style={{
                    padding: '4px 8px',
                    fontSize: '11px',
                    fontWeight: 500,
                    backgroundColor: selectedSymbols.includes(token.symbol) ? C.yellow : C.bg,
                    color: selectedSymbols.includes(token.symbol) ? '#000' : C.text2,
                    border: `1px solid ${selectedSymbols.includes(token.symbol) ? C.yellow : C.border}`,
                    borderRadius: '4px',
                    cursor: 'pointer',
                  }}
                >
                  {token.base}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Market Mode Toggle - SOTA */}
        <div>
          <label style={{ display: 'block', fontSize: '10px', color: C.text3, marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>Market</label>
          <div style={{ display: 'flex', border: `1px solid ${C.border}`, borderRadius: '6px', overflow: 'hidden' }}>
            <button
              onClick={() => setParams({ ...params, market_mode: 'futures' })}
              style={{
                padding: '8px 12px',
                fontSize: '11px',
                fontWeight: 600,
                backgroundColor: params.market_mode === 'futures' ? '#f59e0b' : 'transparent',
                color: params.market_mode === 'futures' ? '#000' : C.text2,
                border: 'none',
                cursor: 'pointer',
              }}
            >
              FUTURES
            </button>
            <button
              onClick={() => setParams({ ...params, market_mode: 'spot' })}
              style={{
                padding: '8px 12px',
                fontSize: '11px',
                fontWeight: 600,
                backgroundColor: params.market_mode === 'spot' ? '#3b82f6' : 'transparent',
                color: params.market_mode === 'spot' ? '#fff' : C.text2,
                border: 'none',
                borderLeft: `1px solid ${C.border}`,
                cursor: 'pointer',
              }}
            >
              SPOT
            </button>
          </div>
        </div>

        {/* Interval */}
        <div>
          <label style={{ display: 'block', fontSize: '10px', color: C.text3, marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>Interval</label>
          <select
            value={params.interval}
            onChange={e => setParams({ ...params, interval: e.target.value })}
            style={{
              backgroundColor: C.bg,
              border: `1px solid ${C.border}`,
              borderRadius: '6px',
              padding: '8px 12px',
              color: C.text1,
              width: '80px',
              fontSize: '13px',
              cursor: 'pointer',
            }}
          >
            <option value="1m">1m</option>
            <option value="5m">5m</option>
            <option value="15m">15m</option>
            <option value="1h">1h</option>
            <option value="4h">4h</option>
          </select>
        </div>
        {/* Date Mode Toggle */}
        <div style={{ gridColumn: 'span 2' }}>
          <label style={{ display: 'block', fontSize: '10px', color: C.text3, marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>Period</label>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
            {/* Mode Toggle Buttons */}
            <div style={{ display: 'flex', border: `1px solid ${C.border}`, borderRadius: '6px', overflow: 'hidden' }}>
              <button
                onClick={() => setParams({ ...params, dateMode: 'days' })}
                style={{
                  padding: '8px 16px',
                  fontSize: '12px',
                  fontWeight: 600,
                  backgroundColor: params.dateMode === 'days' ? C.yellow : 'transparent',
                  color: params.dateMode === 'days' ? '#000' : C.text2,
                  border: 'none',
                  cursor: 'pointer',
                }}
              >
                Quick
              </button>
              <button
                onClick={() => setParams({ ...params, dateMode: 'custom' })}
                style={{
                  padding: '8px 16px',
                  fontSize: '12px',
                  fontWeight: 600,
                  backgroundColor: params.dateMode === 'custom' ? C.yellow : 'transparent',
                  color: params.dateMode === 'custom' ? '#000' : C.text2,
                  border: 'none',
                  cursor: 'pointer',
                }}
              >
                Custom
              </button>
            </div>

            {/* Quick Days Selection */}
            {params.dateMode === 'days' && (
              <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                {[7, 14, 30, 90].map(d => (
                  <button
                    key={d}
                    onClick={() => setParams({ ...params, days: d })}
                    style={{
                      padding: '8px 12px',
                      fontSize: '11px',
                      fontWeight: params.days === d ? 700 : 500,
                      backgroundColor: params.days === d ? C.yellow : C.bg,
                      color: params.days === d ? '#000' : C.text2,
                      border: `1px solid ${params.days === d ? C.yellow : C.border}`,
                      borderRadius: '4px',
                      cursor: 'pointer',
                    }}
                  >
                    {d}d
                  </button>
                ))}
                <span style={{ color: C.text3, margin: '0 4px' }}>or</span>
                <input
                  type="number"
                  min={1}
                  max={365}
                  value={params.days}
                  onChange={e => setParams({ ...params, days: Math.max(1, parseInt(e.target.value) || 30) })}
                  style={{
                    backgroundColor: C.bg,
                    border: `1px solid ${C.border}`,
                    borderRadius: '6px',
                    padding: '6px 10px',
                    color: C.text1,
                    fontSize: '12px',
                    width: '60px',
                    textAlign: 'center',
                    fontFamily: "'JetBrains Mono', monospace",
                  }}
                />
                <span style={{ color: C.text3, fontSize: '12px' }}>days</span>
              </div>
            )}

            {/* Custom Date Range */}
            {params.dateMode === 'custom' && (
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                <input
                  type="date"
                  value={params.startDate}
                  onChange={e => setParams({ ...params, startDate: e.target.value })}
                  style={{
                    backgroundColor: C.bg,
                    border: `1px solid ${C.border}`,
                    borderRadius: '6px',
                    padding: '6px 10px',
                    color: C.text1,
                    fontSize: '12px',
                  }}
                />
                <span style={{ color: C.text3 }}>→</span>
                <input
                  type="date"
                  value={params.endDate}
                  onChange={e => setParams({ ...params, endDate: e.target.value })}
                  style={{
                    backgroundColor: C.bg,
                    border: `1px solid ${C.border}`,
                    borderRadius: '6px',
                    padding: '6px 10px',
                    color: C.text1,
                    fontSize: '12px',
                  }}
                />
                {/* Dark Period Presets */}
                <div style={{ display: 'flex', gap: '4px', marginLeft: '8px' }}>
                  <button
                    onClick={() => setParams({ ...params, dateMode: 'custom', startDate: '2020-03-01', endDate: '2020-03-31' })}
                    title="COVID Crash - BTC -50% in 1 day"
                    style={{ padding: '4px 8px', fontSize: '9px', fontWeight: 600, backgroundColor: 'transparent', color: '#ef4444', border: '1px solid #ef4444', borderRadius: '4px', cursor: 'pointer' }}
                  >COVID</button>
                  <button
                    onClick={() => setParams({ ...params, dateMode: 'custom', startDate: '2022-05-01', endDate: '2022-05-31' })}
                    title="Luna Collapse - $45B wiped"
                    style={{ padding: '4px 8px', fontSize: '9px', fontWeight: 600, backgroundColor: 'transparent', color: '#ef4444', border: '1px solid #ef4444', borderRadius: '4px', cursor: 'pointer' }}
                  >LUNA</button>
                  <button
                    onClick={() => setParams({ ...params, dateMode: 'custom', startDate: '2022-11-01', endDate: '2022-11-30' })}
                    title="FTX Collapse - BTC below $16K"
                    style={{ padding: '4px 8px', fontSize: '9px', fontWeight: 600, backgroundColor: 'transparent', color: '#ef4444', border: '1px solid #ef4444', borderRadius: '4px', cursor: 'pointer' }}
                  >FTX</button>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Balance */}
        <div>
          <label style={{ display: 'block', fontSize: '10px', color: C.text3, marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>Capital</label>
          <input
            type="number"
            value={params.balance}
            onChange={e => setParams({ ...params, balance: parseFloat(e.target.value) })}
            style={{
              backgroundColor: C.bg,
              border: `1px solid ${C.border}`,
              borderRadius: '6px',
              padding: '8px 12px',
              color: C.text1,
              width: '100px',
              fontSize: '13px',
              fontFamily: "'JetBrains Mono', monospace",
            }}
          />
        </div>

        {/* Risk */}
        <div>
          <label style={{ display: 'block', fontSize: '10px', color: C.text3, marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>Risk %</label>
          <input
            type="number"
            step="0.01"
            value={params.risk}
            onChange={e => setParams({ ...params, risk: parseFloat(e.target.value) })}
            style={{
              backgroundColor: C.bg,
              border: `1px solid ${C.border}`,
              borderRadius: '6px',
              padding: '8px 12px',
              color: C.text1,
              width: '72px',
              fontSize: '13px',
              fontFamily: "'JetBrains Mono', monospace",
            }}
          />
        </div>

        {/* Divider */}
        <div style={{ height: '32px', width: '1px', backgroundColor: C.border }} />

        {/* Run Button - Apple style */}
        <button
          onClick={runBacktest}
          disabled={loading}
          style={{
            padding: '8px 20px',
            borderRadius: '6px',
            fontWeight: 600,
            fontSize: '13px',
            border: 'none',
            cursor: loading ? 'not-allowed' : 'pointer',
            backgroundColor: loading ? C.border : C.yellow,
            color: loading ? C.text3 : '#0B0E11',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            transition: 'all 0.2s',
          }}
        >
          {loading ? 'Running...' : 'Run Backtest'}
        </button>

        {/* SOTA Toggle - Apple style */}
        <button
          onClick={() => setShowAdvanced(!showAdvanced)}
          style={{
            padding: '8px 12px',
            borderRadius: '6px',
            fontSize: '11px',
            fontWeight: 600,
            border: `1px solid ${C.border}`,
            backgroundColor: 'transparent',
            color: C.text2,
            cursor: 'pointer',
            transition: 'all 0.2s',
          }}
        >
          {showAdvanced ? '▼ Hide' : '▶ Advanced'}
        </button>
      </div>

      {/* Advanced Specs Panel */}
      {
        showAdvanced && (
          <div style={{
            backgroundColor: C.card,
            padding: '16px',
            borderRadius: '8px',
            marginBottom: '24px',
            border: `1px solid rgba(240, 185, 11, 0.3)`,
          }}>
            <div style={{ fontSize: '10px', color: C.yellow, fontWeight: 700, marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.05em', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Icons.Settings size={12} color={C.yellow} /> Advanced Settings
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '16px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '10px', color: C.text3, marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>Leverage</label>
                <input type="number" value={params.leverage}
                  onChange={e => setParams({ ...params, leverage: parseFloat(e.target.value) })}
                  style={{ backgroundColor: C.bg, border: `1px solid ${C.border}`, borderRadius: '6px', padding: '8px 12px', color: C.text1, width: '100%', fontSize: '13px', fontFamily: "'JetBrains Mono', monospace" }} />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '10px', color: C.text3, marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>Liq Cap ($)</label>
                <input type="number" value={params.max_order}
                  onChange={e => setParams({ ...params, max_order: parseFloat(e.target.value) })}
                  style={{ backgroundColor: C.bg, border: `1px solid ${C.border}`, borderRadius: '6px', padding: '8px 12px', color: C.text1, width: '100%', fontSize: '13px', fontFamily: "'JetBrains Mono', monospace" }} />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '10px', color: C.text3, marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>Max Losses</label>
                <input type="number" value={params.max_losses}
                  onChange={e => setParams({ ...params, max_losses: parseInt(e.target.value) })}
                  style={{ backgroundColor: C.bg, border: `1px solid ${C.border}`, borderRadius: '6px', padding: '8px 12px', color: C.text1, width: '100%', fontSize: '13px', fontFamily: "'JetBrains Mono', monospace" }} />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '10px', color: C.text3, marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>Cooldown (h)</label>
                <input type="number" value={params.cb_cooldown}
                  onChange={e => setParams({ ...params, cb_cooldown: parseInt(e.target.value) })}
                  style={{ backgroundColor: C.bg, border: `1px solid ${C.border}`, borderRadius: '6px', padding: '8px 12px', color: C.text1, width: '100%', fontSize: '13px', fontFamily: "'JetBrains Mono', monospace" }} />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '10px', color: C.text3, marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>DD Limit (%)</label>
                <input type="number" step="0.01" value={params.drawdown_limit}
                  onChange={e => setParams({ ...params, drawdown_limit: parseFloat(e.target.value) })}
                  style={{ backgroundColor: C.bg, border: `1px solid ${C.border}`, borderRadius: '6px', padding: '8px 12px', color: C.text1, width: '100%', fontSize: '13px', fontFamily: "'JetBrains Mono', monospace" }} />
              </div>
            </div>
            <div style={{ marginTop: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <input type="checkbox" id="enable_cb" checked={params.enable_cb}
                onChange={e => setParams({ ...params, enable_cb: e.target.checked })}
                style={{ accentColor: C.yellow }} />
              <label htmlFor="enable_cb" style={{ fontSize: '12px', color: C.text2 }}>Enable Circuit Breaker</label>
            </div>
          </div>
        )
      }

      {/* Error */}
      {
        error && (
          <div style={{
            backgroundColor: 'rgba(127, 29, 29, 0.5)',
            border: `1px solid ${C.down}`,
            color: '#FCA5A5',
            padding: '16px',
            borderRadius: '8px',
            marginBottom: '24px',
            fontSize: '14px',
          }}>
            {error}
          </div>
        )
      }

      {/* Empty State */}
      {
        !result && !loading && (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '80px 0', textAlign: 'center' }}>
            <div style={{ marginBottom: '24px', opacity: 0.6 }}><Icons.ChartBar size={64} color={C.text3} /></div>
            <h2 style={{ fontSize: '20px', fontWeight: 600, color: C.text1, marginBottom: '8px' }}>Ready to Simulate</h2>
            <p style={{ fontSize: '14px', color: C.text2, maxWidth: '400px' }}>
              Configure parameters above and click <span style={{ color: C.yellow, fontWeight: 600 }}>"Run Backtest"</span> to analyze your strategy.
            </p>
            <div style={{ marginTop: '24px', display: 'flex', gap: '16px', fontSize: '12px', color: C.text3 }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><Icons.Bolt size={12} color={C.yellow} /> SOTA Engine</span>
              <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><Icons.Target size={12} color={C.up} /> Limit Sniper</span>
              <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><Icons.TrendUp size={12} color="#3B82F6" /> Hardcore Mode</span>
            </div>
          </div>
        )
      }

      {/* Loading State */}
      {
        loading && (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '80px 0' }}>
            <div style={{ width: '48px', height: '48px', border: `3px solid ${C.border}`, borderTopColor: C.yellow, borderRadius: '50%', animation: 'spin 1s linear infinite' }} />
            <p style={{ color: C.text2, marginTop: '24px' }}>Running backtest simulation...</p>
            <p style={{ color: C.text3, fontSize: '12px', marginTop: '8px' }}>Analyzing {params.startDate} to {params.endDate}</p>
          </div>
        )
      }

      {/* Results */}
      {
        result && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            {/* Stats Cards */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '16px' }}>
              <div style={{ backgroundColor: C.card, padding: '16px', borderRadius: '8px', border: `1px solid ${C.border}` }}>
                <div style={{ fontSize: '10px', color: C.text3, textTransform: 'uppercase', fontWeight: 600, marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <Icons.DollarSign size={12} color={C.text3} /> Net PnL
                </div>
                <div style={{ fontSize: '24px', fontWeight: 700, color: result.stats.net_return_usd >= 0 ? C.up : C.down, fontFamily: "'JetBrains Mono', monospace" }}>
                  {result.stats.net_return_usd >= 0 ? '+' : ''}${result.stats.net_return_usd.toFixed(2)}
                </div>
              </div>
              <div style={{ backgroundColor: C.card, padding: '16px', borderRadius: '8px', border: `1px solid ${C.border}` }}>
                <div style={{ fontSize: '10px', color: C.text3, textTransform: 'uppercase', fontWeight: 600, marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <Icons.Target size={12} color={C.text3} /> Win Rate
                </div>
                <div style={{ fontSize: '24px', fontWeight: 700, color: result.stats.win_rate > 50 ? C.up : C.down, fontFamily: "'JetBrains Mono', monospace" }}>
                  {result.stats.win_rate.toFixed(1)}%
                </div>
              </div>
              <div style={{ backgroundColor: C.card, padding: '16px', borderRadius: '8px', border: `1px solid ${C.border}` }}>
                <div style={{ fontSize: '10px', color: C.text3, textTransform: 'uppercase', fontWeight: 600, marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <Icons.TrendDown size={12} color={C.text3} /> Max Drawdown
                </div>
                <div style={{ fontSize: '24px', fontWeight: 700, color: C.down, fontFamily: "'JetBrains Mono', monospace" }}>
                  {maxDrawdown.toFixed(2)}%
                </div>
              </div>
              <div style={{ backgroundColor: C.card, padding: '16px', borderRadius: '8px', border: `1px solid ${C.border}` }}>
                <div style={{ fontSize: '10px', color: C.text3, textTransform: 'uppercase', fontWeight: 600, marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <Icons.Scale size={12} color={C.text3} /> Profit Factor
                </div>
                <div style={{ fontSize: '24px', fontWeight: 700, color: profitFactor >= 1.5 ? C.up : profitFactor >= 1 ? C.yellow : C.down, fontFamily: "'JetBrains Mono', monospace" }}>
                  {profitFactor === Infinity ? '∞' : profitFactor.toFixed(2)}
                </div>
              </div>
            </div>

            {/* Secondary Stats + Export */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', gap: '16px', fontSize: '13px' }}>
                <span style={{ color: C.text2 }}>Trades: <span style={{ color: C.text1, fontWeight: 700, fontFamily: "'JetBrains Mono', monospace" }}>{result.stats.total_trades}</span></span>
                <span style={{ color: C.up }}>Won: {result.stats.winning_trades}</span>
                <span style={{ color: C.down }}>Lost: {result.stats.losing_trades}</span>
                <span style={{ color: C.text2 }}>Balance: <span style={{ color: C.text1, fontFamily: "'JetBrains Mono', monospace" }}>${result.stats.final_balance.toFixed(2)}</span></span>
                {/* SOTA: Funding Net */}
                <span style={{ color: C.text2 }}>
                  Funding: <span style={{
                    color: (result.stats.funding_net || 0) >= 0 ? C.up : C.down,
                    fontFamily: "'JetBrains Mono', monospace"
                  }}>
                    {(result.stats.funding_net || 0) >= 0 ? '+' : ''}${(result.stats.funding_net || 0).toFixed(2)}
                  </span>
                </span>
              </div>
              <button
                onClick={exportCSV}
                style={{
                  padding: '8px 16px',
                  fontSize: '12px',
                  fontWeight: 600,
                  backgroundColor: 'transparent',
                  border: `1px solid ${C.border}`,
                  borderRadius: '6px',
                  color: C.text2,
                  cursor: 'pointer',
                }}
              >
                <Icons.Download size={14} color={C.text2} /> Export CSV
              </button>
            </div>

            {/* MAIN CHART (Lightweight Charts) */}
            <div style={{ backgroundColor: C.card, padding: '16px', borderRadius: '8px', border: `1px solid ${C.border}` }}>
              <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '16px', color: C.text1 }}>Price Action & Execution ({selectedSymbols[0] || 'N/A'})</h3>
              {result.candles[selectedSymbols[0]] ? (
                <BacktestChart
                  symbol={selectedSymbols[0]}
                  candles={result.candles[selectedSymbols[0]]}
                  trades={result.trades}
                  indicators={result.indicators ? result.indicators[selectedSymbols[0]] : undefined}
                />
              ) : (
                <div style={{ height: '256px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: C.text3 }}>No candle data for {selectedSymbols[0] || 'selected symbol'}</div>
              )}
            </div>

            {/* Equity Chart (Recharts) */}
            <div style={{ backgroundColor: C.card, padding: '16px', borderRadius: '8px', border: `1px solid ${C.border}` }}>
              <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '16px', color: C.text1 }}>Equity Curve</h3>
              <ResponsiveContainer width="100%" height={280}>
                <LineChart data={result.equity}>
                  <CartesianGrid strokeDasharray="3 3" stroke={C.border} />
                  <XAxis
                    dataKey="time"
                    tickFormatter={(ts) => new Date(ts).toLocaleDateString()}
                    stroke={C.text3}
                  />
                  <YAxis domain={['auto', 'auto']} stroke={C.text3} />
                  <RechartsTooltip
                    contentStyle={{ backgroundColor: C.card, border: `1px solid ${C.border}`, color: C.text1 }}
                    labelFormatter={(ts) => new Date(ts).toLocaleString()}
                    formatter={(value: any) => [`$${Number(value).toFixed(2)}`, 'Balance']}
                  />
                  <Line
                    type="monotone"
                    dataKey="balance"
                    stroke={C.up}
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 4 }}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>

            {/* Trade List */}
            <div style={{ backgroundColor: C.card, padding: '16px', borderRadius: '8px', border: `1px solid ${C.border}` }}>
              <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '16px', color: C.text1 }}>Trade History</h3>
              <div style={{ overflowX: 'auto', maxHeight: '384px', overflowY: 'auto' }}>
                <table style={{ width: '100%', textAlign: 'left', fontSize: '12px', color: C.text2 }}>
                  <thead style={{ backgroundColor: C.bg, color: C.text1, textTransform: 'uppercase', position: 'sticky', top: 0 }}>
                    <tr>
                      <th style={{ padding: '8px 12px' }}>Symbol</th>
                      <th style={{ padding: '8px 12px' }}>Side</th>
                      <th style={{ padding: '8px 12px' }}>Entry Time</th>
                      <th style={{ padding: '8px 12px' }}>Entry ($)</th>
                      <th style={{ padding: '8px 12px' }}>Exit ($)</th>
                      <th style={{ padding: '8px 12px' }}>Qty</th>
                      <th style={{ padding: '8px 12px', color: '#f59e0b' }}>Margin ($)</th>
                      <th style={{ padding: '8px 12px' }}>PnL ($)</th>
                      <th style={{ padding: '8px 12px' }}>Funding ($)</th>
                      <th style={{ padding: '8px 12px' }}>Leverage</th>
                      <th style={{ padding: '8px 12px' }}>Notional ($)</th>
                      <th style={{ padding: '8px 12px' }}>Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.trades.slice(0, tradePage * TRADES_PER_PAGE).map((t, idx) => (
                      <tr key={idx} style={{ borderBottom: `1px solid ${C.border}` }}>
                        <td style={{ padding: '8px 12px', fontWeight: 600, color: C.yellow }}>{t.symbol}</td>
                        <td style={{ padding: '8px 12px', fontWeight: 700, color: t.side === 'BUY' || t.side === 'LONG' ? C.up : C.down }}>{t.side}</td>
                        <td style={{ padding: '8px 12px' }}>{new Date(t.entry_time).toLocaleString()}</td>
                        <td style={{ padding: '8px 16px', fontFamily: "'JetBrains Mono', monospace" }}>${t.entry_price.toFixed(4)}</td>
                        <td style={{ padding: '8px 16px', fontFamily: "'JetBrains Mono', monospace" }}>{t.exit_price ? `$${t.exit_price.toFixed(4)}` : '-'}</td>
                        <td style={{ padding: '8px 16px', fontFamily: "'JetBrains Mono', monospace", color: C.text2 }}>
                          {t.quantity?.toFixed(4) || '-'}
                        </td>
                        <td style={{ padding: '8px 16px', fontFamily: "'JetBrains Mono', monospace", color: '#f59e0b', fontWeight: 600 }}>
                          {t.margin_used ? `$${t.margin_used.toFixed(2)}` : (t.notional_value && t.leverage_at_entry ? `$${(t.notional_value / t.leverage_at_entry).toFixed(2)}` : '-')}
                        </td>
                        <td style={{ padding: '8px 16px', fontWeight: 700, fontFamily: "'JetBrains Mono', monospace", color: t.pnl_usd > 0 ? C.up : t.pnl_usd < 0 ? C.down : C.text3 }}>
                          {t.pnl_usd ? `$${t.pnl_usd.toFixed(2)}` : '-'}
                        </td>
                        <td style={{ padding: '8px 16px', fontFamily: "'JetBrains Mono', monospace", color: (t.funding_cost || 0) > 0 ? C.down : (t.funding_cost || 0) < 0 ? C.up : C.text3 }}>
                          {t.funding_cost ? `$${t.funding_cost.toFixed(4)}` : '-'}
                        </td>
                        <td style={{ padding: '8px 16px', fontFamily: "'JetBrains Mono', monospace", color: C.yellow }}>
                          {t.leverage_at_entry ? `${t.leverage_at_entry.toFixed(1)}x` : '-'}
                        </td>
                        <td style={{ padding: '8px 16px', fontFamily: "'JetBrains Mono', monospace", color: C.text2 }}>
                          {t.notional_value ? `$${t.notional_value.toFixed(0)}` : '-'}
                        </td>
                        <td style={{ padding: '8px 16px' }}>
                          <span style={{ backgroundColor: C.bg, padding: '4px 8px', borderRadius: '4px', color: C.text2, fontSize: '11px' }}>{t.exit_reason}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {result.trades.length > tradePage * TRADES_PER_PAGE && (
                  <div style={{ textAlign: 'center', marginTop: '12px' }}>
                    <button
                      onClick={incrementTradePage}
                      style={{
                        padding: '8px 16px',
                        fontSize: '12px',
                        backgroundColor: C.bg,
                        border: `1px solid ${C.border}`,
                        borderRadius: '6px',
                        color: C.text2,
                        cursor: 'pointer',
                      }}
                    >
                      Load More ({result.trades.length - tradePage * TRADES_PER_PAGE} remaining)
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        )
      }
    </div>
  );
};

export default Backtest;
