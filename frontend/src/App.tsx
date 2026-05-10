import { useEffect, useState, useCallback, useRef } from 'react';
import { Radio, FileText, TestTube } from 'lucide-react';
import './App.css';
// SOTA: Zustand store for multi-symbol data + shared WebSocket
import {
  useActiveData1m,
  useActiveData15m,
  useActiveData1h,
  useActiveSignal,
  useActiveStateChange,
  useConnectionState,
  useActiveSymbol
} from './stores/marketStore';
import { useWebSocket } from './hooks/useWebSocket';
import CandleChart from './components/CandleChart';
import Portfolio from './components/Portfolio';
import TradeHistory from './components/TradeHistory';
import Settings from './components/Settings';
import StrategyMonitor from './components/StrategyMonitor';
import SignalLogItem from './components/SignalLogItem';
import SignalCard, { TradingSignal } from './components/SignalCard';
import ErrorBoundary from './components/ErrorBoundary';
import StateIndicator, { TradingState } from './components/StateIndicator';
import { MomentumWidget } from './components/MomentumWidget';
import TokenIcon from './components/TokenIcon';
import TokenSelector from './components/TokenSelector';
import Backtest from './pages/Backtest';
import BacktestPlayer from './components/backtest/BacktestPlayer'; // SOTA: Replay Visualizer
import Analytics from './components/Analytics';  // SOTA: Analytics dashboard
import EnvironmentBanner from './components/EnvironmentBanner';
import { SignalToastProvider } from './components/SignalToast';  // SOTA: Toast notifications
import StartTradingModal from './components/StartTradingModal';  // SOTA: Safe Mode modal
import { THEME, formatPrice as themeFormatPrice } from './styles/theme';
import { apiUrl, ENDPOINTS } from './config/api';
import UnlockAccessButton from './components/UnlockAccessButton';
// ADAPTIVE UI: Breakpoint system for mobile/desktop
import { BreakpointProvider } from './providers/BreakpointProvider';
import { useBreakpoint } from './hooks/useBreakpoint';
import BottomNavigation from './components/navigation/BottomNavigation';
import { MobileHeader } from './components/navigation/MobileHeader';
import { MobileTokenSelector } from './components/MobileTokenSelector';

type Timeframe = '1m' | '15m' | '1h';

interface SystemStatus {
  status: string;
  timestamp: string;
  service: string;
  version: string;
  // SOTA (Jan 2026): Data readiness for chart loading optimization
  data_ready?: boolean;
  ready_symbol_count?: number;
  startup_status?: string;
}

interface SignalLog {
  id: number;
  time: string;
  action: string;
  adx: number;
  trend: 'BULLISH' | 'BEARISH' | 'NEUTRAL';
}

type Tab = 'chart' | 'portfolio' | 'history' | 'settings' | 'backtest' | 'replay' | 'home' | 'markets' | 'trade' | 'more' | 'analytics';

// Design tokens - using THEME for consistency (Phase C)
const C = {
  up: THEME.status.buy,
  down: THEME.status.sell,
  yellow: THEME.accent.yellow,
  bg: THEME.bg.primary,
  card: THEME.bg.tertiary,
  sidebar: THEME.bg.primary,
  border: THEME.border.primary,
  text1: THEME.text.primary,
  text2: THEME.text.secondary,
  text3: THEME.text.tertiary,
  // Phase C: Spacing
  spacing: THEME.spacing,
};

function App() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>('chart');

  // ADAPTIVE UI: Breakpoint detection for mobile/desktop
  const { isMobile } = useBreakpoint();

  // SOTA: Environment mode from backend
  const [currentEnv, setCurrentEnv] = useState<'paper' | 'testnet' | 'live'>('paper');

  // Phase D: Lifted timeframe state for price synchronization
  const [selectedTimeframe, setSelectedTimeframe] = useState<Timeframe>('15m');

  // SOTA: Use Zustand store for multi-symbol data
  const selectedSymbol = useActiveSymbol();
  const marketData = useActiveData1m();
  const data15m = useActiveData15m();
  const data1h = useActiveData1h();
  const wsSignal = useActiveSignal();
  const stateChange = useActiveStateChange();
  const connection = useConnectionState();
  const { reconnectNow } = useWebSocket();

  // Derive connection state for backward compatibility
  const isConnected = connection.isConnected;
  const reconnectState = {
    isReconnecting: connection.isReconnecting,
    retryCount: connection.retryCount,
    nextRetryIn: connection.nextRetryIn,
  };

  // SOTA: Log symbol changes for debugging
  // SOTA: Log symbol changes for debugging AND Update Title
  useEffect(() => {
    console.log(`📊 Active symbol: ${selectedSymbol}`);
    // SEO / Tab Polish: Show Real-time price in tab title
    // Format: Price | SYMBOL - Hinto
    const price = marketData?.close;
    const formattedPrice = price ? price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '---';
    document.title = `${formattedPrice} | ${selectedSymbol.toUpperCase()} - Hinto`;
  }, [selectedSymbol, marketData?.close]);

  // Keep title updated even if only price changes (optimized)
  useEffect(() => {
    if (marketData?.close) {
      const price = marketData.close.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      document.title = `${price} | ${selectedSymbol.toUpperCase()} - Hinto`;
    }
  }, [marketData?.close, selectedSymbol]);

  // Compute current price data based on selected timeframe
  // Fallback to 1m data if timeframe-specific data not available
  const currentData = selectedTimeframe === '1m' ? marketData
    : selectedTimeframe === '15m' ? (data15m || marketData)
      : (data1h || marketData);
  const [signalLogs, setSignalLogs] = useState<SignalLog[]>([
    { id: 1, time: '18:40:05', action: 'INIT', adx: 0, trend: 'NEUTRAL' },
    { id: 2, time: '18:40:06', action: 'CONN', adx: 0, trend: 'NEUTRAL' },
    { id: 3, time: '18:40:10', action: 'SCAN', adx: 32, trend: 'BULLISH' },
  ]);
  const [activeSignal, setActiveSignal] = useState<TradingSignal | null>(null);
  const [lastSignalId, setLastSignalId] = useState<string | null>(null);
  const lastSignalTimestampRef = useRef<number>(0);  // Track last signal time for dedup
  const signalDismissTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);  // Auto-dismiss timer
  const lastEntryPriceRef = useRef<number>(0);  // Track last entry price for dedup

  // P2: Signal history with localStorage persistence (max 50 signals)
  // TODO: Display signal history in UI (P3)
  const [_signalHistory, setSignalHistory] = useState<TradingSignal[]>(() => {
    try {
      const stored = localStorage.getItem('signalHistory');
      const history = stored ? JSON.parse(stored) : [];
      console.log(`📜 Loaded ${history.length} signals from history`);
      return history;
    } catch {
      return [];
    }
  });

  // Fix 2: Clear signal based on state machine transitions (event-driven, not polling)

  // SOTA: Centralized header stats (Balance & Signal Count)
  const [virtualBalance, setVirtualBalance] = useState<number>(0);
  const [totalSignals, setTotalSignals] = useState<number>(0);

  // LIVE TRADING: Toggle state
  const [isLiveTrading, setIsLiveTrading] = useState<boolean>(false);

  // SOTA SAFE MODE: Show modal on startup until user activates trading
  const [showSafeModeModal, setShowSafeModeModal] = useState<boolean>(true);

  // Restore: Clear signal state on transition
  useEffect(() => {
    if (stateChange) {
      // Clear signal when transitioning to COOLDOWN or SCANNING
      if (stateChange.to_state === 'COOLDOWN' || stateChange.to_state === 'SCANNING') {
        setActiveSignal(null);
        setLastSignalId(null);
      }
    }
  }, [stateChange]);

  const [mobileSearchOpen, setMobileSearchOpen] = useState(false);

  useEffect(() => {
    const fetchHeaderStats = async () => {
      try {
        const [pRes, sRes, liveRes] = await Promise.all([
          fetch(apiUrl(ENDPOINTS.PORTFOLIO)),
          fetch(apiUrl(ENDPOINTS.SIGNAL_HISTORY(1, 1, 30))),
          fetch(apiUrl(ENDPOINTS.LIVE_STATUS))  // SOTA: Check live trading mode
        ]);

        if (pRes.ok) {
          const pData = await pRes.json();
          // SOTA FIX: API returns { balance: number, ... } at top level
          setVirtualBalance(pData.balance !== undefined ? pData.balance : (pData.state?.balance || 0));
        }

        if (sRes.ok) {
          const sData = await sRes.json();
          // Fix: API returns { signals: [], pagination: { total: X } }
          setTotalSignals(sData.pagination?.total || sData.total || 0);
        }

        // SOTA: Update live trading status from backend
        if (liveRes.ok) {
          const liveData = await liveRes.json();
          const serviceMode = String(liveData.mode || '').toLowerCase();
          setIsLiveTrading(liveData.enabled === true && serviceMode !== 'paper');
        }

        // SOTA: Fetch current environment
        try {
          const envRes = await fetch(apiUrl(ENDPOINTS.SYSTEM.CONFIG));
          if (envRes.ok) {
            const envData = await envRes.json();
            const env = envData.environment?.toLowerCase() || 'paper';
            console.log(`🌍 Environment from backend: ${env}`);
            setCurrentEnv(env as 'paper' | 'testnet' | 'live');
          } else {
            console.warn(`⚠️ /system/config returned ${envRes.status}`);
          }
        } catch (err) {
          console.error('❌ Failed to fetch environment:', err);
        }
      } catch (error) {
        console.error('Failed to fetch header stats:', error);
      }
    };

    fetchHeaderStats();
    // SOTA FIX (Jan 2026): Increased from 5s to 30s to prevent polling flood
    // Root cause: 5s interval with 4 endpoints = 0.8 calls/sec = 32s cascade delays
    // WebSocket balance_update handles real-time balance; polling is fallback only
    const interval = setInterval(fetchHeaderStats, 30000); // 30s fallback
    return () => clearInterval(interval);
  }, []);

  // Convert WebSocket signal to TradingSignal format and update activeSignal
  useEffect(() => {
    if (wsSignal && wsSignal.type) {
      console.log('📡 WebSocket signal received:', wsSignal);

      try {
        const signalTimestamp = wsSignal.timestamp
          ? new Date(wsSignal.timestamp).getTime()
          : Date.now();

        // Prefer backend UUID if available, fallback to custom signalId
        const signalId = wsSignal.id || `${wsSignal.type}-${signalTimestamp}`;

        // Allow new signal if:
        // 1. Different signal ID (backend UUID), OR
        // 2. Timestamp differs by > 60s, OR
        // 3. Same type but DIFFERENT entry_price (new signal generation)
        const timeDiff = signalTimestamp - lastSignalTimestampRef.current;
        const entryPrice = wsSignal.entry_price || wsSignal.price || 0;
        const entryPriceDiff = Math.abs(entryPrice - lastEntryPriceRef.current);
        const isNewSignal = signalId !== lastSignalId || timeDiff > 60000 || entryPriceDiff > 10;

        if (isNewSignal) {
          setLastSignalId(signalId);
          lastSignalTimestampRef.current = signalTimestamp;
          lastEntryPriceRef.current = entryPrice;

          const price = wsSignal.entry_price || wsSignal.price || 0;
          const isBuy = wsSignal.type === 'BUY';

          // Safely extract take_profit (may be object with tp1, tp2, tp3 or number)
          let takeProfit1 = isBuy ? price * 1.015 : price * 0.985;
          if (wsSignal.take_profit) {
            const tp = wsSignal.take_profit as number | { tp1?: number };
            if (typeof tp === 'object' && tp.tp1) {
              takeProfit1 = tp.tp1;
            } else if (typeof tp === 'number') {
              takeProfit1 = tp;
            }
          }

          // Convert backend signal format to frontend TradingSignal format
          const tradingSignal: TradingSignal = {
            id: signalId,
            type: wsSignal.type as 'BUY' | 'SELL',
            symbol: wsSignal.symbol || selectedSymbol || 'btcusdt',
            timestamp: wsSignal.timestamp || new Date().toISOString(),
            entry: price,
            stopLoss: wsSignal.stop_loss || (isBuy ? price * 0.985 : price * 1.015),
            takeProfit1: takeProfit1,
            takeProfit2: isBuy ? price * 1.025 : price * 0.975,
            takeProfit3: isBuy ? price * 1.04 : price * 0.96,
            confidence: Math.round((wsSignal.confidence || 0.7) * 100),
            rrRatio: wsSignal.risk_reward_ratio || 1.5,
            strategy: 'Trend Pullback',
            indicators: {
              rsi: marketData?.rsi,
              adx: 32,
              stochK: 25,
              stochD: 30,
            },
            status: wsSignal.status || 'generated'  // Backend signal status
          };

          setActiveSignal(tradingSignal);

          // P2: Add to signal history (newest first, max 50)
          setSignalHistory(prev => {
            const newHistory = [tradingSignal, ...prev].slice(0, 50);
            localStorage.setItem('signalHistory', JSON.stringify(newHistory));
            return newHistory;
          });

          // Clear any existing auto-dismiss timer
          if (signalDismissTimeoutRef.current) {
            clearTimeout(signalDismissTimeoutRef.current);
          }

          // Auto-dismiss after 5 minutes if not executed/dismissed
          signalDismissTimeoutRef.current = setTimeout(() => {
            console.log('⏰ Auto-dismissing signal after 5 minutes');
            setActiveSignal(null);
            setLastSignalId(null);  // Allow new signals of same type
          }, 5 * 60 * 1000);

          // Add to signal logs
          const now = new Date();
          const timeStr = now.toLocaleTimeString('vi-VN', {
            hour: '2-digit', minute: '2-digit', second: '2-digit',
            timeZone: 'Asia/Ho_Chi_Minh'
          });
          setSignalLogs(prev => [...prev.slice(-49), {
            id: Date.now(),
            time: timeStr,
            action: wsSignal.type,
            adx: 32,
            trend: isBuy ? 'BULLISH' : 'BEARISH'
          }]);

          console.log('📡 New signal processed:', tradingSignal);
        }
      } catch (err) {
        console.error('❌ Error processing WebSocket signal:', err, wsSignal);
      }
    }
    // Note: marketData?.rsi removed from deps - we use current value when signal arrives
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsSignal, lastSignalId]);

  // Cleanup auto-dismiss timer on unmount
  useEffect(() => {
    return () => {
      if (signalDismissTimeoutRef.current) {
        clearTimeout(signalDismissTimeoutRef.current);
      }
    };
  }, []);

  // Execute trade handler - calls backend API to execute pending order at market price
  const handleExecuteTrade = useCallback(async (_signal: TradingSignal) => {
    try {
      // Step 1: Get pending orders to find the matching one
      const portfolioResponse = await fetch(apiUrl(ENDPOINTS.PORTFOLIO));
      const portfolioData = await portfolioResponse.json();

      // Find pending order (status === 'PENDING')
      const pendingOrders = portfolioData.open_positions?.filter(
        (p: { status: string }) => p.status === 'PENDING'
      ) || [];

      if (pendingOrders.length === 0) {
        alert('No pending orders to execute. Signal may have expired.');
        return;
      }

      // Use the most recent pending order
      const pendingOrder = pendingOrders[0];
      const positionId = pendingOrder.id;

      // Step 2: Execute at market price
      const response = await fetch(apiUrl(ENDPOINTS.EXECUTE_TRADE(positionId)), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      const result = await response.json();

      if (result.success) {
        console.log('✅ Trade executed at market:', result);
        alert(
          `✅ Order Filled!\n\n` +
          `Side: ${result.side}\n` +
          `Fill Price: $${result.fill_price?.toFixed(2)} (market)\n` +
          `Original Entry: $${result.original_entry?.toFixed(2)}\n` +
          `Size: $${result.size_usd?.toFixed(2)}`
        );
        setActiveSignal(null);
      } else {
        alert(`❌ Execution failed: ${result.error}`);
      }
    } catch (err) {
      console.error('Trade execution error:', err);
      alert('Failed to execute trade - check console for details');
    }
  }, []);

  // Bottom panel removed - keyboard shortcuts and resize effects no longer needed

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const response = await fetch(apiUrl(ENDPOINTS.SYSTEM_STATUS));
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const data = await response.json();
        setStatus(data);

        const now = new Date();
        const timeStr = now.toLocaleTimeString('vi-VN', {
          hour: '2-digit', minute: '2-digit', second: '2-digit',
          timeZone: 'Asia/Ho_Chi_Minh'
        });

        const adx = Math.floor(Math.random() * 30) + 20;
        // SOTA: Use ref to get current marketData without adding to deps
        const trend: 'BULLISH' | 'BEARISH' | 'NEUTRAL' = 'NEUTRAL';
        setSignalLogs(prev => {
          const newId = Date.now() + Math.random();
          return [...prev.slice(-49), { id: newId, time: timeStr, action: 'SCAN', adx, trend }];
        });
      } catch (err) {
        console.error("Failed to fetch status:", err);
      }
    };
    fetchStatus();
    const interval = setInterval(fetchStatus, 15000); // SOTA: Only poll on interval, not on every WebSocket update
    return () => clearInterval(interval);
  }, []);  // SOTA: Only poll on interval, not on every WebSocket update

  const tabs: { id: Tab; label: string }[] = [
    { id: 'chart', label: 'Chart' },
    { id: 'portfolio', label: 'Portfolio' },
    { id: 'backtest', label: 'Quant Lab' },
    { id: 'replay', label: 'Replay' }, // SOTA: New Replay Tab
    { id: 'analytics', label: 'Analytics' },  // SOTA: Analytics Dashboard
    { id: 'history', label: 'History' },
    { id: 'settings', label: 'Settings' },
  ];

  const formatPrice = (price: number | undefined | null) => {
    if (price === undefined || price === null) return '--';
    return themeFormatPrice(price);
  };

  const trendBias = marketData && marketData.vwap
    ? (marketData.close > marketData.vwap ? 'LONG' : 'SHORT')
    : 'NEUTRAL';
  const adxValue = 32;
  const isLive = status?.status === 'ok';
  const priceColor = marketData?.change_percent && marketData.change_percent >= 0 ? C.up : C.down;

  return (
    <SignalToastProvider>
      {/* SOTA SAFE MODE: Show modal if in safe mode (TESTNET/LIVE only) */}
      {showSafeModeModal && currentEnv !== 'paper' && (
        <StartTradingModal onActivated={() => setShowSafeModeModal(false)} />
      )}
      <div className="app-container" style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100vh',
        overflow: 'hidden',
        userSelect: 'none',
        backgroundColor: C.bg,
        color: C.text1,
        fontFamily: "'Inter', system-ui, sans-serif",
      }}>

        {/* SOTA: Environment Banner with Mode Selector + Kill Switch - Compact on mobile */}
        <EnvironmentBanner showModeSelector={true} showKillSwitch={true} compact={isMobile} />

        {/* HEADER - Hidden on mobile (uses MobileHeader instead) */}
        {!isMobile && (
          <header style={{
            height: '48px',
            flexShrink: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '0 16px',
            backgroundColor: C.card,
            borderBottom: isLiveTrading ? '1px solid #ef4444' : `1px solid ${C.border}`,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '32px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ fontWeight: 700, fontSize: '20px', letterSpacing: 0, color: C.yellow }}>Hinto</span>
                <span style={{
                  fontSize: '10px',
                  textTransform: 'uppercase',
                  fontWeight: 700,
                  letterSpacing: '0.1em',
                  padding: '2px 6px',
                  borderRadius: '4px',
                  border: `1px solid ${C.border}`,
                  color: C.text2,
                }}>Pro</span>
                {/* ... existing badge code ... */}
              </div>
              {/* Multi-Token Selector */}
              <TokenSelector />
              <nav style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                {tabs.map((tab) => (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    style={{
                      padding: '6px 12px',
                      fontSize: '14px',
                      fontWeight: 500,
                      borderRadius: '6px',
                      border: 'none',
                      cursor: 'pointer',
                      transition: 'all 0.2s',
                      backgroundColor: activeTab === tab.id ? C.border : 'transparent',
                      color: activeTab === tab.id ? C.yellow : C.text2,
                    }}
                  >
                    {tab.label}
                  </button>
                ))}
              </nav>
            </div>
            {/* ... rest of header ... */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: '10px', textTransform: 'uppercase', fontWeight: 700, color: isLiveTrading ? '#ef4444' : C.text3 }}>
                  {isLiveTrading ? 'REAL Balance' : 'Virtual Balance'}
                </div>
                <div style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 700, color: isLiveTrading ? '#ef4444' : C.up }}>
                  {new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(virtualBalance)}
                </div>
              </div>

              {/* Mode Indicator (Read-only - controlled by backend .env) */}
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  padding: '6px 12px',
                  borderRadius: '6px',
                  border: currentEnv === 'live' ? '2px solid #ef4444'
                    : currentEnv === 'testnet' ? '1px solid #f59e0b'
                      : `1px solid ${C.border}`,
                  backgroundColor: currentEnv === 'live' ? 'rgba(239, 68, 68, 0.15)'
                    : currentEnv === 'testnet' ? 'rgba(245, 158, 11, 0.15)'
                      : 'transparent',
                  color: currentEnv === 'live' ? '#ef4444'
                    : currentEnv === 'testnet' ? '#f59e0b'
                      : C.text2,
                  fontWeight: 600,
                  fontSize: '12px',
                }}
              >
                {currentEnv === 'live' ? (
                  <><Radio size={14} style={{ animation: 'pulse 1.5s infinite' }} /> LIVE</>
                ) : currentEnv === 'testnet' ? (
                  <><TestTube size={14} /> TESTNET</>
                ) : (
                  <><FileText size={14} /> PAPER</>
                )}
              </div>

              {/* Signal History Count */}
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: '10px', textTransform: 'uppercase', fontWeight: 700, color: C.text3 }}>History</div>
                <div style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 700, color: C.yellow }}>{totalSignals} signals</div>
              </div>

              {/* State Machine Indicator */}
              <StateIndicator
                state={(stateChange?.to_state || 'SCANNING') as TradingState}
                orderId={stateChange?.order_id}
                positionId={stateChange?.position_id}
                reason={stateChange?.reason}
                cooldownRemaining={stateChange?.cooldown_remaining}
              />

              {/* Unlock Access Button - Auto-update Security Group with current IP */}
              <UnlockAccessButton compact />

              <div style={{ height: '32px', width: '1px', backgroundColor: C.border }} />
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{
                  width: '8px',
                  height: '8px',
                  borderRadius: '50%',
                  backgroundColor: isLive ? C.up : C.down,
                  boxShadow: isLive ? `0 0 8px ${C.up}` : 'none',
                }} />
                <span style={{ fontSize: '12px', fontWeight: 700, letterSpacing: '0.05em', color: isLive ? C.up : C.down }}>
                  {isLive ? 'LIVE' : 'OFF'}
                </span>
              </div>
            </div>
          </header>
        )}

        {/* Mobile Header (Only on mobile) */}
        {isMobile && (
          <MobileHeader
            currentEnv={currentEnv}
            isConnected={status?.status === 'ok'}
            symbol={selectedSymbol?.toUpperCase()}
            price={marketData?.close}
            priceChange={marketData?.change_percent}
            onTokenSearch={() => setMobileSearchOpen(true)}
          />
        )}

        {/* Mobile Token Selector Overlay */}
        {isMobile && (
          <MobileTokenSelector
            isOpen={mobileSearchOpen}
            onClose={() => setMobileSearchOpen(false)}
          />
        )}

        {/* MAIN CONTENT AREA */}
        {/* MAIN CONTENT AREA */}
        <main style={{
          flex: 1,
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          position: 'relative',
          // SOTA Mobile Layout: Ensure chart fits exactly without double scrollbars
          height: isMobile ? 'calc(100dvh - 48px - 60px)' : (isLiveTrading ? 'calc(100vh - 80px)' : 'calc(100vh - 48px)'),
          // ADAPTIVE UI: Add padding for bottom nav on mobile
          paddingBottom: isMobile ? 'calc(60px + env(safe-area-inset-bottom))' : 0,
        }}>
          {activeTab === 'chart' ? (
            <>
              {/* ////////////////////////////////////////////////// */}
              {/* CHART SECTION */}
              {/* ////////////////////////////////////////////////// */}

              {/* MOBILE LAYOUT - Scrollable container with Chart + Market Health */}
              <div className="mobile-only" style={{
                height: '100%',
                overflowY: 'auto',
                WebkitOverflowScrolling: 'touch',
                backgroundColor: C.bg
              }}>
                {/* Chart Container */}
                <div style={{
                  height: '72%',
                  minHeight: 350,
                  maxHeight: 500,
                  position: 'relative',
                  borderBottom: `1px solid ${C.border}`,
                }}>
                  <ErrorBoundary>
                    <CandleChart
                      timeframe={selectedTimeframe}
                      onTimeframeChange={setSelectedTimeframe}
                      isMobile={true}
                    />
                  </ErrorBoundary>
                </div>

                {/* Content below Chart */}
                <div style={{ padding: '12px' }}>
                  {/* Signal Card - Compact Mode */}
                  {activeSignal && (
                    <div style={{ marginBottom: 12 }}>
                      <SignalCard
                        signal={activeSignal}
                        currentPrice={currentData?.close || 0}
                        onExecute={handleExecuteTrade}
                        onDismiss={() => setActiveSignal(null)}
                        compact={true}
                      />
                    </div>
                  )}

                  {/* Market Health (Strategy Monitor) */}
                  <div style={{
                    background: '#0d0d0f',
                    borderRadius: 10,
                    border: `1px solid ${C.border}`,
                    marginBottom: 12,
                  }}>
                    <StrategyMonitor
                      trendBias={trendBias}
                      adxValue={adxValue}
                      stochRsiValue={marketData?.rsi || 50}
                    />
                  </div>

                  {/* Live Feed - Compact Mobile Version */}
                  <div style={{
                    background: '#0d0d0f',
                    borderRadius: 10,
                    border: `1px solid ${C.border}`,
                    marginBottom: 12,
                    overflow: 'hidden',
                  }}>
                    {/* Header */}
                    <div style={{
                      padding: '8px 12px',
                      fontSize: 10,
                      fontWeight: 700,
                      textTransform: 'uppercase',
                      letterSpacing: '0.05em',
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      borderBottom: `1px solid ${C.border}`,
                      color: C.text3,
                    }}>
                      <span>Live Feed</span>
                      <span style={{
                        fontFamily: 'monospace',
                        fontSize: 9,
                        padding: '2px 6px',
                        borderRadius: 4,
                        backgroundColor: C.border
                      }}>
                        {signalLogs.length}
                      </span>
                    </div>

                    {/* Logs - Show last 5 */}
                    <div style={{
                      padding: '6px 12px',
                      fontFamily: 'monospace',
                      fontSize: 10,
                      maxHeight: 100,
                      overflowY: 'auto',
                    }}>
                      {signalLogs.length > 0 ? (
                        signalLogs.slice(-5).map((log) => (
                          <SignalLogItem key={log.id} time={log.time} action={log.action} adx={log.adx} trend={log.trend} />
                        ))
                      ) : (
                        <div style={{ color: C.text3, textAlign: 'center', padding: 8 }}>
                          Waiting for signals...
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Footer Spacing for bottom nav */}
                  <div style={{ height: 70 }} />
                </div>
              </div>

              {/* ////////////////////////////////////////////////// */}
              {/* DESKTOP LAYOUT - Original layout with ticker bar + sidebar */}
              {/* ////////////////////////////////////////////////// */}
              {/* TICKER BAR - Desktop only */}
              <div className="desktop-only" style={{
                height: '40px',
                flexShrink: 0,
                display: 'flex',
                alignItems: 'center',
                padding: '0 16px',
                gap: '24px',
                fontSize: '14px',
                backgroundColor: C.card,
                borderBottom: `1px solid ${C.border}`,
              }}>
                {/* Token with icon - SOTA: Dynamic based on activeSymbol */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <TokenIcon symbol={selectedSymbol.replace('usdt', '').toUpperCase()} size={24} />
                  <span style={{ fontWeight: 700, color: C.text1 }}>{selectedSymbol.replace('usdt', '/USDT').toUpperCase()}</span>
                  <span style={{
                    fontSize: '10px',
                    padding: '2px 6px',
                    borderRadius: '4px',
                    fontWeight: 500,
                    backgroundColor: 'rgba(240,185,11,0.15)',
                    color: C.yellow,
                  }}>{selectedTimeframe}</span>
                </div>
                {/* Price - uses currentData based on timeframe */}
                <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: '18px', fontWeight: 700, color: priceColor }}>
                  ${currentData ? formatPrice(currentData.close) : '---'}
                </div>
                <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: '14px', color: priceColor }}>
                  {currentData?.change_percent !== undefined ? `${currentData.change_percent >= 0 ? '+' : ''}${currentData.change_percent.toFixed(2)}%` : '---'}
                </div>
                <div style={{ display: 'flex', gap: '16px', fontSize: '12px', color: C.text2 }}>
                  <span>H: <span style={{ fontFamily: "'JetBrains Mono', monospace", color: C.text1 }}>{currentData?.high ? formatPrice(currentData.high) : '---'}</span></span>
                  <span>L: <span style={{ fontFamily: "'JetBrains Mono', monospace", color: C.text1 }}>{currentData?.low ? formatPrice(currentData.low) : '---'}</span></span>
                  <span>RSI: <span style={{ fontFamily: "'JetBrains Mono', monospace", color: (marketData?.rsi || 50) > 70 ? C.down : (marketData?.rsi || 50) < 30 ? C.up : C.text1 }}>{marketData?.rsi?.toFixed(1) || '---'}</span></span>
                  <span>VWAP: <span style={{ fontFamily: "'JetBrains Mono', monospace", color: C.yellow }}>{marketData?.vwap ? formatPrice(marketData.vwap) : '---'}</span></span>
                </div>
                {/* SOTA: Momentum Velocity Widget - grouped with indicators */}
                <MomentumWidget />
                <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '12px' }}>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <div style={{
                      width: '6px',
                      height: '6px',
                      borderRadius: '50%',
                      backgroundColor: isConnected ? C.up : (reconnectState.isReconnecting ? C.yellow : C.down),
                      animation: reconnectState.isReconnecting ? 'pulse 1s infinite' : 'none'
                    }} />
                    <span style={{
                      fontSize: '12px',
                      fontWeight: 500,
                      color: isConnected ? C.up : (reconnectState.isReconnecting ? C.yellow : C.down)
                    }}>
                      {isConnected ? 'LIVE' : (reconnectState.isReconnecting ? `Reconnecting ${reconnectState.nextRetryIn}s...` : 'DISCONNECTED')}
                    </span>
                    {!isConnected && (
                      <button
                        onClick={reconnectNow}
                        style={{
                          marginLeft: '8px',
                          padding: '2px 8px',
                          fontSize: '10px',
                          fontWeight: 600,
                          color: '#000',
                          backgroundColor: C.yellow,
                          border: 'none',
                          borderRadius: '4px',
                          cursor: 'pointer',
                        }}
                      >
                        Reconnect
                      </button>
                    )}
                  </div>
                </div>
              </div>

              {/* Trading View Layout - Desktop only */}
              <div className="desktop-only-flex" style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>

                {/* LEFT: Chart + Bottom Panel */}
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, minWidth: 0, borderRight: `1px solid ${C.border}`, overflow: 'hidden' }}>
                  <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
                    <ErrorBoundary>
                      <CandleChart
                        timeframe={selectedTimeframe}
                        onTimeframeChange={setSelectedTimeframe}
                      />
                    </ErrorBoundary>
                  </div>

                  {/* Bottom Panel removed - Use Portfolio tab for positions */}
                </div>

                {/* RIGHT SIDEBAR */}
                <aside style={{ width: '320px', flexShrink: 0, display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'hidden', backgroundColor: C.sidebar, borderLeft: `1px solid ${C.border}` }}>

                  <StrategyMonitor trendBias={trendBias} adxValue={adxValue} stochRsiValue={marketData?.rsi || 50} />

                  {/* Active Signal Card */}
                  <div style={{ padding: '12px', borderBottom: `1px solid ${C.border}` }}>
                    <SignalCard
                      signal={activeSignal}
                      currentPrice={marketData?.close || 0}
                      onExecute={handleExecuteTrade}
                      onDismiss={() => setActiveSignal(null)}
                    />
                    {/* Simulate button removed - Use Settings > Debug tab instead */}
                  </div>

                  {/* Signal Logs */}
                  <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'hidden' }}>
                    <div style={{
                      padding: '8px 12px',
                      fontSize: '10px',
                      fontWeight: 700,
                      textTransform: 'uppercase',
                      letterSpacing: '0.05em',
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      flexShrink: 0,
                      backgroundColor: C.sidebar,
                      borderBottom: `1px solid ${C.border}`,
                      color: C.text3,
                    }}>
                      <span>Live Feed</span>
                      <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: '9px', padding: '2px 6px', borderRadius: '4px', backgroundColor: C.border }}>
                        {signalLogs.length}
                      </span>
                    </div>

                    <div style={{ flex: 1, overflowY: 'auto', padding: '4px 12px', fontFamily: "'JetBrains Mono', monospace" }}>
                      {signalLogs.slice(-30).map((log) => (
                        <SignalLogItem key={log.id} time={log.time} action={log.action} adx={log.adx} trend={log.trend} />
                      ))}
                    </div>
                  </div>

                  {/* Mode Badge */}
                  <div style={{
                    flexShrink: 0,
                    padding: '8px 12px',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    fontSize: '10px',
                    borderTop: `1px solid ${C.border}`,
                    backgroundColor: C.sidebar,
                  }}>
                    <span style={{ color: C.text3 }}>Mode</span>
                    <span style={{
                      padding: '2px 8px',
                      borderRadius: '4px',
                      fontWeight: 700,
                      letterSpacing: '0.05em',
                      backgroundColor: currentEnv === 'live' ? 'rgba(239, 68, 68, 0.15)'
                        : currentEnv === 'testnet' ? 'rgba(245, 158, 11, 0.15)'
                          : 'rgba(34, 197, 94, 0.15)',
                      color: currentEnv === 'live' ? '#ef4444'
                        : currentEnv === 'testnet' ? '#f59e0b'
                          : '#22c55e',
                    }}>{currentEnv.toUpperCase()}</span>
                  </div>
                </aside>
              </div>
            </>
          ) : (
            // Non-Chart Tabs
            activeTab === 'replay' && !isMobile ? (
              // SOTA: REPLAY TAB - Full Screen Layout
              <div style={{ flex: 1, minHeight: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
                <BacktestPlayer />
              </div>
            ) : (
              // Standard Scrolling Layout for Portfolio, Settings, etc.
              <div style={{ height: '100%', overflowY: 'auto', padding: '16px' }}>
                <div style={{ maxWidth: '1152px', margin: '0 auto' }}>
                  {activeTab === 'portfolio' && <Portfolio />}
                  {activeTab === 'backtest' && <Backtest />}
                  {activeTab === 'analytics' && <Analytics />}
                  {activeTab === 'history' && <TradeHistory />}
                  {activeTab === 'settings' && <Settings />}
                </div>
              </div>
            )
          )}
        </main>

        {/* ADAPTIVE UI: Bottom Navigation for Mobile - 4 functional tabs */}
        {
          isMobile && (
            <BottomNavigation
              activeTab={activeTab}
              onTabChange={setActiveTab}
            />
          )
        }
      </div >
    </SignalToastProvider >
  );
}

/**
 * App wrapper with BreakpointProvider
 * This enables responsive breakpoint detection throughout the app
 */
function AppWithProviders() {
  return (
    <BreakpointProvider>
      <App />
    </BreakpointProvider>
  );
}

export default AppWithProviders;
