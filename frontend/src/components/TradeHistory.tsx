import React, { useState, useEffect, useCallback, useRef, memo } from 'react';
import { THEME, formatPrice, formatVietnamDate, calculateDuration } from '../styles/theme';
import { apiUrl, ENDPOINTS } from '../config/api';
// SOTA: Professional SVG icons
import {
    ClipboardList,
    Inbox,
    Target,
    Shield,
    Hand,
    RefreshCcw,
    Link2,
    FileText,
    TrendingUp,
    TrendingDown,
    BarChart3,
    BarChart2,
    Flame,
    Snowflake,
    Download,
    Filter,
    Activity
} from 'lucide-react';
// SOTA Phase 24: Recharts for analytics visualizations
import { PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';

export interface Trade {
    id: string;
    symbol: string;
    side: 'LONG' | 'SHORT';
    status: string;
    entry_price: number;
    quantity: number;
    margin: number;
    stop_loss: number;
    take_profit: number;
    open_time: string;
    close_time: string | null;
    realized_pnl: number;
    exit_reason: string | null;
}

export interface PaginatedTrades {
    trades: Trade[];
    total: number;
    page: number;
    limit: number;
    total_pages: number;
}

// SOTA Phase 24: Exit Reason Analytics
export interface ExitReasonStatsData {
    reason: string;
    count: number;
    win_rate: number;
    avg_pnl: number;
    total_pnl: number;
    avg_duration_minutes: number;
}

// SOTA Phase 24: Risk Metrics
export interface RiskMetricsData {
    sharpe_ratio: number;
    sortino_ratio: number;
    calmar_ratio: number;
    recovery_factor: number;
}

// SOTA Phase 24: Streak Stats
export interface StreakStatsData {
    current_streak: number;
    max_consecutive_wins: number;
    max_consecutive_losses: number;
    avg_winner_duration_minutes: number;
    avg_loser_duration_minutes: number;
}

export interface SymbolStats {
    symbol: string;
    total_trades: number;
    winning_trades: number;
    losing_trades: number;
    win_rate: number;
    total_pnl: number;
    profit_factor: number;
    long_trades: number;
    short_trades: number;
    long_win_rate: number;
    short_win_rate: number;
    best_side: string;
}

// SOTA: Full analytics data from backend /trades/performance
export interface PerformanceData {
    total_trades: number;
    winning_trades: number;
    losing_trades: number;
    win_rate: number;
    profit_factor: number;
    max_drawdown: number;
    total_pnl: number;
    average_rr: number;
    expectancy: number;
    average_win: number;
    average_loss: number;
    largest_win: number;
    largest_loss: number;
    per_symbol: Record<string, SymbolStats>;
    // Phase 24: Bot Behavior Analytics
    exit_reason_stats: Record<string, ExitReasonStatsData>;
    risk_metrics: RiskMetricsData;
    streak_stats: StreakStatsData;
}

// Tab type for analytics
export type AnalyticsTab = 'overview' | 'per_token' | 'history' | 'signals';

// SOTA Phase 25: Enhanced Signal from backend API with full indicator data
export interface SignalRecord {
    id: string;
    symbol: string;
    signal_type: 'buy' | 'sell';
    status: string;
    confidence: number;
    confidence_level: 'high' | 'medium' | 'low';
    price: number;
    entry_price: number | null;
    stop_loss: number | null;
    tp_levels: { tp1?: number; tp2?: number; tp3?: number } | null;
    position_size: number | null;
    risk_reward_ratio: number | null;
    // SOTA: Full indicator data for analysis
    indicators: {
        rsi?: number;
        adx?: number;
        stoch_k?: number;
        stoch_d?: number;
        vwap_distance?: number;
        bb_position?: string;
        volume_ratio?: number;
        regime?: string;
        ema7?: number;
        ema25?: number;
        [key: string]: unknown;  // Allow additional indicators
    };
    reasons: string[];
    generated_at: string;
    pending_at: string | null;
    executed_at: string | null;
    expired_at: string | null;
    order_id: string | null;
    execution_latency_ms: number | null;
}

// SOTA Phase 25: Paginated signals response
export interface PaginatedSignals {
    signals: SignalRecord[];
    pagination: {
        page: number;
        limit: number;
        total: number;
        total_pages: number;
    };
}


/**
 * Trade History Component - Binance SOTA Professional Style
 *
 * SOTA Features (Dec 2025):
 * - Professional SVG icons (Lucide)
 * - Analytics dashboard with Win Rate, Profit Factor, Expectancy
 * - Per-symbol breakdown table
 * - Tabbed interface
 */

// SOTA: Reusable Metric Card Component - Memoized to prevent parent re-render propagation
const MetricCard = memo<{
    label: string;
    value: string;
    color?: string;
    subtext?: string;
    icon?: React.ReactNode;
    small?: boolean;
}>(({ label, value, color, subtext, icon, small }) => (
    <div style={{
        backgroundColor: THEME.bg.vessel,
        borderRadius: '8px',
        padding: small ? '12px' : '16px',
        border: `1px solid ${THEME.border.primary}`,
    }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }}>
            {icon && <span style={{ color: color || THEME.text.tertiary }}>{icon}</span>}
            <span style={{ fontSize: '11px', color: THEME.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.5px' }}>{label}</span>
        </div>
        <div style={{ fontSize: small ? '16px' : '20px', fontWeight: 700, color: color || THEME.text.primary, fontFamily: "'JetBrains Mono', monospace" }}>
            {value}
        </div>
        {subtext && <div style={{ fontSize: '10px', color: THEME.text.tertiary, marginTop: '2px' }}>{subtext}</div>}
    </div>
));
MetricCard.displayName = 'MetricCard';

// SOTA Phase 26: Mobile Optimization
import { TradeHistoryMobile } from './trading/TradeHistoryMobile';
import { useBreakpoint } from '../hooks/useBreakpoint';

// SOTA Fix: Memoized to prevent re-render from parent WebSocket updates
const TradeHistoryInner: React.FC = () => {
    const { isMobile } = useBreakpoint(); // SOTA: Responsive check
    const [trades, setTrades] = useState<PaginatedTrades | null>(null);
    const [performance, setPerformance] = useState<PerformanceData | null>(null);
    const [currentPage, setCurrentPage] = useState(1);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [activeTab, setActiveTab] = useState<AnalyticsTab>('overview');
    // SOTA Phase 24c: Server-side filter states
    const [filterSymbol, setFilterSymbol] = useState<string>('');
    const [filterSide, setFilterSide] = useState<string>('');
    const [filterPnl, setFilterPnl] = useState<string>('');
    // Store all unique symbols for filter dropdown
    const [allSymbols, setAllSymbols] = useState<string[]>([]);
    // SOTA: Trading mode indicator
    const [tradingMode, setTradingMode] = useState<string>('PAPER');
    // SOTA Phase 25: Enhanced signal history with filtering and pagination
    const [signals, setSignals] = useState<SignalRecord[]>([]);
    const [signalsLoading, setSignalsLoading] = useState(false);
    const [signalPage, setSignalPage] = useState(1);
    const [signalPagination, setSignalPagination] = useState<{ total: number; total_pages: number }>({ total: 0, total_pages: 0 });
    // SOTA Phase 25: Signal filter states
    const [signalFilterSymbol, setSignalFilterSymbol] = useState<string>('');
    const [signalFilterType, setSignalFilterType] = useState<string>('');
    const [signalFilterStatus, setSignalFilterStatus] = useState<string>('');
    // SOTA Phase 25: Expandable row state
    const [expandedSignalId, setExpandedSignalId] = useState<string | null>(null);
    const signalLimit = 10;
    const limit = 10;

    // SOTA Fix: useRef to track symbols initialization without causing re-renders
    const symbolsInitializedRef = useRef(false);

    // SOTA Phase 24c: Fetch trades with server-side filtering
    // FIX: Removed allSymbols.length from deps to prevent infinite loop
    const fetchTrades = useCallback(async (page: number) => {
        setIsLoading(true);
        try {
            const response = await fetch(apiUrl(ENDPOINTS.TRADE_HISTORY(
                page, limit,
                filterSymbol || undefined,
                filterSide || undefined,
                filterPnl || undefined
            )));
            if (!response.ok) throw new Error('Failed to fetch trades');
            const data = await response.json();
            setTrades(data);
            // SOTA: Update trading mode from API response
            if (data.trading_mode) {
                setTradingMode(data.trading_mode);
            }
            // SOTA Fix: Use ref to track initialization (doesn't cause re-render)
            if (!symbolsInitializedRef.current && data.trades.length > 0) {
                const uniqueSymbols = [...new Set(data.trades.map((t: Trade) => t.symbol))] as string[];
                setAllSymbols(uniqueSymbols);
                symbolsInitializedRef.current = true;
            }
            setError(null);
        } catch (err) {
            setError('Không thể tải lịch sử giao dịch');
        } finally {
            setIsLoading(false);
        }
    }, [filterSymbol, filterSide, filterPnl]);  // Removed allSymbols.length

    // SOTA: Fetch performance analytics
    const fetchPerformance = useCallback(async () => {
        try {
            const response = await fetch(apiUrl(ENDPOINTS.PERFORMANCE(365)));
            if (response.ok) {
                const data = await response.json();
                setPerformance(data);
            }
        } catch (err) {
            console.error('Failed to fetch performance:', err);
        }
    }, []);

    // SOTA Phase 25: Fetch signals with server-side filtering and pagination
    const fetchSignals = useCallback(async (page: number = 1) => {
        setSignalsLoading(true);
        try {
            const response = await fetch(apiUrl(ENDPOINTS.SIGNAL_HISTORY(
                page,
                signalLimit,
                30,  // days
                signalFilterSymbol || undefined,
                signalFilterType || undefined,
                signalFilterStatus || undefined
            )));
            if (response.ok) {
                const data: PaginatedSignals = await response.json();
                setSignals(data.signals || []);
                setSignalPagination({
                    total: data.pagination.total,
                    total_pages: data.pagination.total_pages
                });
            }
        } catch (err) {
            console.error('Failed to fetch signals:', err);
        } finally {
            setSignalsLoading(false);
        }
    }, [signalFilterSymbol, signalFilterType, signalFilterStatus]);

    // SOTA Phase 24c: Refetch when filters or page change
    useEffect(() => {
        setCurrentPage(1); // Reset to page 1 when filters change
    }, [filterSymbol, filterSide, filterPnl]);

    // SOTA Phase 25: Reset signal page when signal filters change
    useEffect(() => {
        setSignalPage(1);
    }, [signalFilterSymbol, signalFilterType, signalFilterStatus]);

    // SOTA Fix: Fetch performance ONCE on mount (not on every pagination)
    useEffect(() => {
        fetchPerformance();
    }, [fetchPerformance]);

    // SOTA Phase 25: Fetch signals when signals tab is active or filters/page change
    useEffect(() => {
        if (activeTab === 'signals') {
            fetchSignals(signalPage);
        }
    }, [activeTab, signalPage, fetchSignals]);

    // SOTA Phase 4: WebSocket listener for real-time signal updates
    useEffect(() => {
        if (activeTab !== 'signals') return;

        const wsUrl = `ws://localhost:8000/ws/stream/btcusdt`;
        let ws: WebSocket | null = null;

        try {
            ws = new WebSocket(wsUrl);

            ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    if (data.type === 'signal' && data.signal) {
                        console.log('📡 TradeHistory: Real-time signal received:', data.signal);

                        // SOTA: Prepend new signal to the list (real-time update)
                        const newSignal: SignalRecord = {
                            id: data.signal.id || `sig_${Date.now()}`,
                            symbol: data.signal.symbol || data.symbol,
                            signal_type: data.signal.signal_type,
                            status: 'GENERATED',
                            confidence: data.signal.confidence || 0.7,
                            confidence_level: (data.signal.confidence || 0.7) > 0.8 ? 'high' : (data.signal.confidence || 0.7) > 0.6 ? 'medium' : 'low',
                            price: data.signal.price || data.signal.entry_price || 0,
                            entry_price: data.signal.entry_price || null,
                            stop_loss: data.signal.stop_loss || null,
                            tp_levels: data.signal.tp_levels || null,
                            position_size: null,
                            risk_reward_ratio: data.signal.risk_reward_ratio || null,
                            indicators: data.signal.indicators || {},
                            reasons: data.signal.reasons || [],
                            generated_at: data.signal.timestamp || new Date().toISOString(),
                            pending_at: null,
                            executed_at: null,
                            expired_at: null,
                            order_id: null,
                            execution_latency_ms: null
                        };

                        setSignals(prev => [newSignal, ...prev].slice(0, signalLimit));
                        // Don't update pagination total - will sync on next API fetch
                    }
                } catch (e) {
                    // Silent - may be other event types
                }
            };

            ws.onopen = () => console.log('📡 TradeHistory WS connected (signals tab)');
            ws.onclose = () => console.log('📡 TradeHistory WS disconnected');
            ws.onerror = () => { }; // Silent
        } catch (e) {
            // WebSocket unavailable
        }

        return () => {
            if (ws) ws.close();
        };
    }, [activeTab]);

    // SOTA Fix: Fetch trades when page or filters change (separate from performance)
    useEffect(() => {
        fetchTrades(currentPage);
    }, [currentPage, fetchTrades]);

    // SOTA: Calculate exit price from entry and P&L
    const calculateExitPrice = (trade: Trade): number | null => {
        if (!trade.quantity || trade.quantity === 0) return null;
        const pnlPerUnit = trade.realized_pnl / trade.quantity;
        return trade.side === 'LONG'
            ? trade.entry_price + pnlPerUnit
            : trade.entry_price - pnlPerUnit;
    };

    // SOTA: Calculate P&L percentage
    const calculatePnlPercent = (trade: Trade): number => {
        if (!trade.margin || trade.margin === 0) return 0;
        return (trade.realized_pnl / trade.margin) * 100;
    };

    // SOTA: Professional exit reason badges with SVG icons
    const getExitReasonBadge = (reason: string | null) => {
        if (!reason) return <span style={{ color: THEME.text.tertiary }}>-</span>;

        const config: Record<string, { bg: string; color: string; label: string; Icon: React.FC<{ size?: number }> }> = {
            'TAKE_PROFIT': { bg: THEME.alpha.buyBg, color: THEME.status.buy, label: 'Chốt lời', Icon: Target },
            'STOP_LOSS': { bg: THEME.alpha.sellBg, color: THEME.status.sell, label: 'Cắt lỗ', Icon: Shield },
            'MANUAL_CLOSE': { bg: THEME.alpha.infoBg, color: THEME.status.info, label: 'Đóng tay', Icon: Hand },
            'SIGNAL_REVERSAL': { bg: THEME.alpha.warningBg, color: THEME.accent.yellow, label: 'Đảo chiều', Icon: RefreshCcw },
            'MERGED': { bg: 'rgba(128,128,128,0.15)', color: THEME.text.secondary, label: 'Merged', Icon: Link2 },
        };

        const c = config[reason] || { bg: THEME.bg.vessel, color: THEME.text.tertiary, label: reason, Icon: FileText };

        return (
            <span style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                padding: '4px 8px',
                borderRadius: '4px',
                fontSize: '10px',
                fontWeight: 600,
                backgroundColor: c.bg,
                color: c.color,
                whiteSpace: 'nowrap',
            }}>
                <c.Icon size={12} />
                <span>{c.label}</span>
            </span>
        );
    };

    // Container style
    const containerStyle: React.CSSProperties = {
        backgroundColor: THEME.bg.secondary,
        border: `1px solid ${THEME.border.primary}`,
        borderRadius: '8px',
        padding: '20px',
    };

    // Table header style
    const thStyle = (align: 'left' | 'center' | 'right' = 'left', width?: string): React.CSSProperties => ({
        padding: '12px 10px',
        fontSize: '11px',
        color: THEME.text.tertiary,
        fontWeight: 600,
        textAlign: align,
        textTransform: 'uppercase',
        letterSpacing: '0.5px',
        width,
        position: 'sticky',
        top: 0,
        backgroundColor: THEME.bg.tertiary,
        borderBottom: `2px solid ${THEME.border.primary}`,
    });

    // Table cell style
    const tdStyle = (align: 'left' | 'center' | 'right' = 'left'): React.CSSProperties => ({
        padding: '12px 10px',
        textAlign: align,
        fontSize: '12px',
    });

    if (isLoading && !trades) {
        return (
            <div style={containerStyle}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    <div style={{ height: '20px', backgroundColor: THEME.bg.vessel, borderRadius: '4px', width: '200px' }}></div>
                    {[...Array(5)].map((_, i) => (
                        <div key={i} style={{ height: '52px', backgroundColor: THEME.bg.vessel, borderRadius: '4px' }}></div>
                    ))}
                </div>
            </div>
        );
    }

    if (error) {
        return (
            <div style={{ ...containerStyle, borderColor: THEME.status.sell }}>
                <p style={{ fontSize: '14px', color: THEME.status.sell, margin: 0 }}>{error}</p>
            </div>
        );
    }

    if (isMobile) {
        return (
            <TradeHistoryMobile
                activeTab={activeTab}
                setActiveTab={setActiveTab}
                trades={trades}
                performance={performance}
                signals={signals}
                tradingMode={tradingMode}
                currentPage={currentPage}
                onPageChange={setCurrentPage}
                isLoading={isLoading}
            />
        );
    }

    return (
        <div style={containerStyle}>
            {/* Header with SVG Icon */}
            <div style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                paddingBottom: '16px',
                borderBottom: `1px solid ${THEME.border.primary}`,
                marginBottom: '16px'
            }}>
                <h2 style={{
                    fontSize: '18px',
                    fontWeight: 700,
                    color: THEME.text.primary,
                    margin: 0,
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    lineHeight: 1, // SOTA Fix: Ensure icon alignment
                }}>
                    <ClipboardList size={20} style={{ color: THEME.accent.yellow }} />
                    Lịch sử giao dịch
                    {/* SOTA: Trading mode badge */}
                    <span style={{
                        fontSize: '10px',
                        fontWeight: 600,
                        padding: '2px 8px',
                        borderRadius: '4px',
                        marginLeft: '8px',
                        backgroundColor: tradingMode === 'LIVE' ? THEME.alpha.sellBg : tradingMode === 'TESTNET' ? THEME.alpha.warningBg : THEME.alpha.infoBg,
                        color: tradingMode === 'LIVE' ? THEME.status.sell : tradingMode === 'TESTNET' ? THEME.accent.yellow : THEME.status.info,
                    }}>
                        {tradingMode}
                    </span>
                </h2>
                <span style={{
                    fontSize: '12px',
                    color: THEME.text.tertiary,
                    backgroundColor: THEME.bg.vessel,
                    padding: '4px 12px',
                    borderRadius: '12px',
                }}>
                    {trades?.total || 0} giao dịch
                </span>
            </div>

            {/* SOTA: Tab Navigation */}
            <div style={{ display: 'flex', gap: '8px', marginBottom: '20px' }}>
                {(['overview', 'per_token', 'history', 'signals'] as AnalyticsTab[]).map((tab) => {
                    const tabConfig = {
                        overview: { label: 'Tổng quan', Icon: BarChart3 },
                        per_token: { label: 'Theo Token', Icon: TrendingUp },
                        history: { label: 'Lịch sử', Icon: ClipboardList },
                        signals: { label: 'Tín hiệu', Icon: Activity }
                    };
                    const { label, Icon } = tabConfig[tab];
                    const isActive = activeTab === tab;
                    return (
                        <button
                            key={tab}
                            onClick={() => setActiveTab(tab)}
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '6px',
                                padding: '8px 16px',
                                borderRadius: '6px',
                                border: 'none',
                                cursor: 'pointer',
                                fontSize: '12px',
                                fontWeight: 600,
                                lineHeight: 1, // SOTA Fix: Ensure icon alignment
                                backgroundColor: isActive ? THEME.accent.yellow : THEME.bg.vessel,
                                color: isActive ? '#000' : THEME.text.secondary,
                                transition: 'all 0.2s',
                            }}
                        >
                            <Icon size={14} />
                            {label}
                        </button>
                    );
                })}
            </div>

            {/* SOTA: Overview Tab - Analytics Dashboard */}
            {activeTab === 'overview' && performance && (
                <div style={{ marginBottom: '20px' }}>
                    {/* Core Metrics Row */}
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', marginBottom: '16px' }}>
                        <MetricCard
                            label="Win Rate"
                            value={`${performance.win_rate ?? 0}%`}
                            color={(performance.win_rate ?? 0) >= 50 ? THEME.status.buy : THEME.status.sell}
                            icon={<Target size={16} />}
                        />
                        <MetricCard
                            label="Profit Factor"
                            value={(performance.profit_factor ?? 0).toFixed(2)}
                            color={(performance.profit_factor ?? 0) >= 1.75 ? THEME.status.buy : THEME.status.sell}
                            subtext={(performance.profit_factor ?? 0) >= 2 ? 'Xuất sắc' : (performance.profit_factor ?? 0) >= 1.75 ? 'Tốt' : 'Cần cải thiện'}
                            icon={<BarChart3 size={16} />}
                        />
                        <MetricCard
                            label="Total P&L"
                            value={`$${(performance.total_pnl ?? 0).toFixed(2)}`}
                            color={(performance.total_pnl ?? 0) >= 0 ? THEME.status.buy : THEME.status.sell}
                            icon={(performance.total_pnl ?? 0) >= 0 ? <TrendingUp size={16} /> : <TrendingDown size={16} />}
                        />
                        <MetricCard
                            label="Expectancy"
                            value={`$${(performance.expectancy ?? 0).toFixed(2)}`}
                            color={(performance.expectancy ?? 0) >= 0 ? THEME.status.buy : THEME.status.sell}
                            subtext="$/lệnh"
                            icon={<Target size={16} />}
                        />
                    </div>

                    {/* SOTA Phase 24: Risk Metrics Row */}
                    {performance.risk_metrics && (
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', marginTop: '16px', marginBottom: '16px' }}>
                            <MetricCard
                                label="Sharpe Ratio"
                                value={performance.risk_metrics.sharpe_ratio.toFixed(2)}
                                color={performance.risk_metrics.sharpe_ratio >= 1 ? THEME.status.buy : THEME.text.secondary}
                                subtext={performance.risk_metrics.sharpe_ratio >= 2 ? 'Xuất sắc' : performance.risk_metrics.sharpe_ratio >= 1 ? 'Tốt' : 'Thấp'}
                                small
                            />
                            <MetricCard
                                label="Sortino Ratio"
                                value={performance.risk_metrics.sortino_ratio.toFixed(2)}
                                color={performance.risk_metrics.sortino_ratio >= 1.5 ? THEME.status.buy : THEME.text.secondary}
                                small
                            />
                            <MetricCard
                                label="Calmar Ratio"
                                value={performance.risk_metrics.calmar_ratio.toFixed(2)}
                                color={performance.risk_metrics.calmar_ratio >= 3 ? THEME.status.buy : THEME.text.secondary}
                                small
                            />
                            <MetricCard
                                label="Recovery Factor"
                                value={performance.risk_metrics.recovery_factor.toFixed(2)}
                                color={performance.risk_metrics.recovery_factor >= 3 ? THEME.status.buy : THEME.text.secondary}
                                small
                            />
                        </div>
                    )}

                    {/* SOTA Phase 24: Streak Indicator */}
                    {performance.streak_stats && (
                        <div style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '16px',
                            padding: '12px 16px',
                            backgroundColor: THEME.bg.vessel,
                            borderRadius: '8px',
                            marginBottom: '16px',
                            border: `1px solid ${THEME.border.primary}`
                        }}>
                            {/* Current Streak */}
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                {performance.streak_stats.current_streak > 0 ? (
                                    <Flame size={20} style={{ color: '#FF6B35' }} />
                                ) : performance.streak_stats.current_streak < 0 ? (
                                    <Snowflake size={20} style={{ color: '#00D1FF' }} />
                                ) : (
                                    <Target size={20} style={{ color: THEME.text.tertiary }} />
                                )}
                                <span style={{
                                    fontSize: '14px',
                                    fontWeight: 700,
                                    color: performance.streak_stats.current_streak > 0 ? THEME.status.buy : performance.streak_stats.current_streak < 0 ? THEME.status.sell : THEME.text.secondary
                                }}>
                                    {performance.streak_stats.current_streak > 0
                                        ? `${performance.streak_stats.current_streak} Thắng liên tiếp`
                                        : performance.streak_stats.current_streak < 0
                                            ? `${Math.abs(performance.streak_stats.current_streak)} Thua liên tiếp`
                                            : 'Neutral'}
                                </span>
                            </div>
                            <div style={{ height: '20px', width: '1px', backgroundColor: THEME.border.primary }} />
                            <div style={{ fontSize: '11px', color: THEME.text.tertiary }}>
                                Max Win Streak: <span style={{ color: THEME.status.buy, fontWeight: 600 }}>{performance.streak_stats.max_consecutive_wins}</span>
                            </div>
                            <div style={{ fontSize: '11px', color: THEME.text.tertiary }}>
                                Max Loss Streak: <span style={{ color: THEME.status.sell, fontWeight: 600 }}>{performance.streak_stats.max_consecutive_losses}</span>
                            </div>
                        </div>
                    )}

                    {/* SOTA Phase 24: Exit Reason Analytics Table */}
                    {performance.exit_reason_stats && Object.keys(performance.exit_reason_stats).length > 0 && (
                        <div style={{ marginBottom: '16px' }}>
                            <h3 style={{ fontSize: '14px', fontWeight: 600, color: THEME.text.primary, marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <BarChart2 size={16} style={{ color: THEME.accent.yellow }} />
                                Thống kê theo Lý do đóng lệnh
                            </h3>
                            <div style={{ overflowX: 'auto' }}>
                                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                                    <thead>
                                        <tr>
                                            <th style={thStyle('left')}>Lý do</th>
                                            <th style={thStyle('right')}>Số lệnh</th>
                                            <th style={thStyle('right')}>Win Rate</th>
                                            <th style={thStyle('right')}>Avg P&L</th>
                                            <th style={thStyle('right')}>Total P&L</th>
                                            <th style={thStyle('right')}>Avg Duration</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {Object.values(performance.exit_reason_stats).map((stat, idx) => (
                                            <tr key={stat.reason} style={{ borderBottom: `1px solid ${THEME.border.secondary}`, backgroundColor: idx % 2 === 0 ? 'transparent' : 'rgba(30,35,41,0.3)' }}>
                                                <td style={{ ...tdStyle('left'), fontWeight: 600 }}>
                                                    {getExitReasonBadge(stat.reason)}
                                                </td>
                                                <td style={tdStyle('right')}>{stat.count}</td>
                                                <td style={{ ...tdStyle('right'), color: stat.win_rate >= 50 ? THEME.status.buy : THEME.status.sell, fontWeight: 600 }}>
                                                    {stat.win_rate.toFixed(1)}%
                                                </td>
                                                <td style={{ ...tdStyle('right'), color: stat.avg_pnl >= 0 ? THEME.status.buy : THEME.status.sell }}>
                                                    ${stat.avg_pnl.toFixed(2)}
                                                </td>
                                                <td style={{ ...tdStyle('right'), color: stat.total_pnl >= 0 ? THEME.status.buy : THEME.status.sell, fontWeight: 600 }}>
                                                    ${stat.total_pnl.toFixed(2)}
                                                </td>
                                                <td style={{ ...tdStyle('right'), color: THEME.text.tertiary }}>
                                                    {stat.avg_duration_minutes >= 60
                                                        ? `${Math.floor(stat.avg_duration_minutes / 60)}h ${Math.round(stat.avg_duration_minutes % 60)}m`
                                                        : `${Math.round(stat.avg_duration_minutes)}m`}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    )}

                    {/* SOTA Phase 24: Charts Row - Glassblur Tech Style */}
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                        {/* Exit Reason Pie Chart */}
                        {performance.exit_reason_stats && Object.keys(performance.exit_reason_stats).length > 0 && (
                            <div style={{
                                backgroundColor: THEME.bg.vessel,
                                borderRadius: '8px',
                                padding: '16px',
                                border: `1px solid ${THEME.border.primary}`,
                                backdropFilter: 'blur(8px)'
                            }}>
                                <h4 style={{ fontSize: '11px', color: THEME.text.tertiary, marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Exit Reason Distribution</h4>
                                <ResponsiveContainer width="100%" height={200}>
                                    <PieChart>
                                        <Pie
                                            data={Object.values(performance.exit_reason_stats).map(s => ({ name: s.reason, value: s.count }))}
                                            cx="50%"
                                            cy="50%"
                                            outerRadius={70}
                                            innerRadius={45}
                                            dataKey="value"
                                            strokeWidth={1}
                                            stroke={THEME.bg.primary}
                                        >
                                            {Object.values(performance.exit_reason_stats).map((_, index) => (
                                                <Cell key={index} fill={[THEME.status.buy, THEME.status.sell, THEME.accent.yellow, '#1E90FF'][index % 4]} />
                                            ))}
                                        </Pie>
                                        <Tooltip
                                            contentStyle={{
                                                backgroundColor: THEME.bg.secondary,
                                                border: `1px solid ${THEME.border.primary}`,
                                                borderRadius: '6px',
                                                padding: '8px 12px'
                                            }}
                                            labelStyle={{ color: THEME.text.primary, fontWeight: 600, fontSize: '12px' }}
                                            itemStyle={{ color: THEME.text.secondary, fontSize: '11px' }}
                                        />
                                    </PieChart>
                                </ResponsiveContainer>
                            </div>
                        )}

                        {/* P&L by Symbol Bar Chart */}
                        {performance.per_symbol && Object.keys(performance.per_symbol).length > 0 && (
                            <div style={{
                                backgroundColor: THEME.bg.vessel,
                                borderRadius: '8px',
                                padding: '16px',
                                border: `1px solid ${THEME.border.primary}`,
                                backdropFilter: 'blur(8px)'
                            }}>
                                <h4 style={{ fontSize: '11px', color: THEME.text.tertiary, marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>P&L by Token</h4>
                                <ResponsiveContainer width="100%" height={200}>
                                    <BarChart data={Object.values(performance.per_symbol).map(s => ({ name: s.symbol, pnl: s.total_pnl }))}>
                                        <XAxis
                                            dataKey="name"
                                            tick={{ fill: THEME.text.tertiary, fontSize: 10 }}
                                            axisLine={{ stroke: THEME.border.primary }}
                                            tickLine={false}
                                        />
                                        <YAxis
                                            tick={{ fill: THEME.text.tertiary, fontSize: 10 }}
                                            axisLine={{ stroke: THEME.border.primary }}
                                            tickLine={false}
                                        />
                                        <Tooltip
                                            contentStyle={{
                                                backgroundColor: THEME.bg.secondary,
                                                border: `1px solid ${THEME.border.primary}`,
                                                borderRadius: '6px',
                                                padding: '8px 12px'
                                            }}
                                            labelStyle={{ color: THEME.text.primary, fontWeight: 600, fontSize: '12px' }}
                                            formatter={(value) => [`$${Number(value ?? 0).toFixed(2)}`, 'P&L']}
                                        />
                                        <Bar dataKey="pnl" radius={[3, 3, 0, 0]}>
                                            {Object.values(performance.per_symbol).map((s, index) => (
                                                <Cell key={index} fill={s.total_pnl >= 0 ? THEME.status.buy : THEME.status.sell} />
                                            ))}
                                        </Bar>
                                    </BarChart>
                                </ResponsiveContainer>
                            </div>
                        )}
                    </div>
                </div>
            )}

            {/* SOTA: Per Token Tab */}
            {activeTab === 'per_token' && performance && Object.keys(performance.per_symbol).length > 0 && (
                <div style={{ overflowX: 'auto', marginBottom: '20px' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                        <thead>
                            <tr>
                                <th style={thStyle('left')}>Symbol</th>
                                <th style={thStyle('right')}>Trades</th>
                                <th style={thStyle('right')}>Win Rate</th>
                                <th style={thStyle('right')}>Net P&L</th>
                                <th style={thStyle('right')}>Profit Factor</th>
                                <th style={thStyle('center')}>LONG WR</th>
                                <th style={thStyle('center')}>SHORT WR</th>
                                <th style={thStyle('center')}>Best Side</th>
                            </tr>
                        </thead>
                        <tbody>
                            {Object.values(performance.per_symbol).map((sym, idx) => (
                                <tr key={sym.symbol} style={{ borderBottom: `1px solid ${THEME.border.secondary}`, backgroundColor: idx % 2 === 0 ? 'transparent' : 'rgba(30,35,41,0.3)' }}>
                                    <td style={{ ...tdStyle('left'), fontWeight: 700 }}>{sym.symbol}</td>
                                    <td style={tdStyle('right')}>{sym.total_trades}</td>
                                    <td style={{ ...tdStyle('right'), color: sym.win_rate >= 50 ? THEME.status.buy : THEME.status.sell }}>{sym.win_rate}%</td>
                                    <td style={{ ...tdStyle('right'), color: sym.total_pnl >= 0 ? THEME.status.buy : THEME.status.sell, fontWeight: 600 }}>${sym.total_pnl.toFixed(2)}</td>
                                    <td style={{ ...tdStyle('right'), color: sym.profit_factor >= 1.75 ? THEME.status.buy : THEME.text.secondary }}>{sym.profit_factor === Infinity ? '∞' : sym.profit_factor.toFixed(2)}</td>
                                    <td style={{ ...tdStyle('center'), color: THEME.status.buy }}>{sym.long_win_rate}%</td>
                                    <td style={{ ...tdStyle('center'), color: THEME.status.sell }}>{sym.short_win_rate}%</td>
                                    <td style={tdStyle('center')}>
                                        {sym.best_side !== '-' && (
                                            <span style={{
                                                padding: '2px 8px',
                                                borderRadius: '4px',
                                                fontSize: '10px',
                                                fontWeight: 600,
                                                backgroundColor: sym.best_side === 'LONG' ? THEME.alpha.buyBg : THEME.alpha.sellBg,
                                                color: sym.best_side === 'LONG' ? THEME.status.buy : THEME.status.sell
                                            }}>{sym.best_side}</span>
                                        )}
                                        {sym.best_side === '-' && <span style={{ color: THEME.text.tertiary }}>-</span>}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            {/* History Tab - Trade Table */}
            {activeTab === 'history' && (
                <>
                    {/* SOTA Phase 24b: Filter Bar */}
                    <div style={{
                        display: 'flex',
                        gap: '12px',
                        marginBottom: '16px',
                        alignItems: 'center',
                        padding: '12px 16px',
                        backgroundColor: 'rgba(24, 26, 32, 0.6)',
                        borderRadius: '8px',
                        border: '1px solid rgba(255,255,255,0.05)'
                    }}>
                        <Filter size={16} style={{ color: THEME.text.tertiary }} />

                        {/* Token Filter */}
                        <select
                            value={filterSymbol}
                            onChange={(e) => setFilterSymbol(e.target.value)}
                            style={{
                                backgroundColor: THEME.bg.vessel,
                                color: THEME.text.primary,
                                border: `1px solid ${THEME.border.primary}`,
                                borderRadius: '6px',
                                padding: '6px 10px',
                                fontSize: '12px',
                                cursor: 'pointer',
                                outline: 'none'
                            }}
                        >
                            <option value="">Tất cả Token</option>
                            {allSymbols.map(sym => (
                                <option key={sym} value={sym.toLowerCase()}>{sym.toUpperCase().replace('USDT', '')}</option>
                            ))}
                        </select>

                        {/* Side Filter */}
                        <select
                            value={filterSide}
                            onChange={(e) => setFilterSide(e.target.value)}
                            style={{
                                backgroundColor: THEME.bg.vessel,
                                color: THEME.text.primary,
                                border: `1px solid ${THEME.border.primary}`,
                                borderRadius: '6px',
                                padding: '6px 10px',
                                fontSize: '12px',
                                cursor: 'pointer',
                                outline: 'none'
                            }}
                        >
                            <option value="">Tất cả Side</option>
                            <option value="LONG">LONG</option>
                            <option value="SHORT">SHORT</option>
                        </select>

                        {/* SOTA Phase 24c: P&L Filter */}
                        <select
                            value={filterPnl}
                            onChange={(e) => setFilterPnl(e.target.value)}
                            style={{
                                backgroundColor: THEME.bg.vessel,
                                color: THEME.text.primary,
                                border: `1px solid ${THEME.border.primary}`,
                                borderRadius: '6px',
                                padding: '6px 10px',
                                fontSize: '12px',
                                cursor: 'pointer',
                                outline: 'none'
                            }}
                        >
                            <option value="">Tất cả P&L</option>
                            <option value="profit">Lãi</option>
                            <option value="loss">Lỗ</option>
                        </select>

                        {/* Spacer */}
                        <div style={{ flex: 1 }} />

                        {/* SOTA Phase 24c: Bulk Export Button */}
                        <button
                            onClick={async () => {
                                try {
                                    // Fetch ALL matching trades from export endpoint
                                    const response = await fetch(apiUrl(ENDPOINTS.TRADE_EXPORT(
                                        filterSymbol || undefined,
                                        filterSide || undefined,
                                        filterPnl || undefined
                                    )));
                                    if (!response.ok) {
                                        let errorMessage = 'Export failed';
                                        try {
                                            const errorData = await response.json();
                                            errorMessage = errorData.detail || errorData.message || 'Unknown server error';
                                        } catch (e) {
                                            errorMessage = `Status ${response.status}: ${response.statusText}`;
                                        }
                                        throw new Error(errorMessage);
                                    } const data = await response.json();

                                    const headers = ['Thời gian', 'Cặp', 'Loại', 'Margin', 'Entry', 'P&L', 'Lý do'];
                                    const rows = data.trades.map((t: Trade) => [
                                        t.close_time ? formatVietnamDate(t.close_time) : '',
                                        t.symbol,
                                        t.side,
                                        `$${t.margin.toFixed(2)}`,
                                        `$${t.entry_price.toFixed(4)}`,
                                        `$${t.realized_pnl.toFixed(2)}`,
                                        t.exit_reason || ''
                                    ]);
                                    const csv = [headers.join(','), ...rows.map((r: string[]) => r.join(','))].join('\n');
                                    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
                                    const url = URL.createObjectURL(blob);
                                    const a = document.createElement('a');
                                    a.href = url;
                                    a.download = `trade_history_all_${new Date().toISOString().split('T')[0]}.csv`;
                                    a.click();
                                    URL.revokeObjectURL(url);
                                } catch (err) {
                                    const errorMsg = err instanceof Error ? err.message : 'Unknown error';
                                    console.error('Export failed:', err);
                                    alert(`Export thất bại: ${errorMsg}`);
                                }
                            }}
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '6px',
                                padding: '8px 14px',
                                backgroundColor: THEME.accent.yellow,
                                color: '#000',
                                border: 'none',
                                borderRadius: '6px',
                                fontSize: '12px',
                                fontWeight: 600,
                                cursor: 'pointer',
                                transition: 'all 0.2s'
                            }}
                        >
                            <Download size={14} />
                            Export All
                        </button>
                    </div>

                    {trades?.trades.length === 0 ? (
                        <div style={{
                            display: 'flex',
                            flexDirection: 'column',
                            alignItems: 'center',
                            justifyContent: 'center',
                            padding: '48px',
                            color: THEME.text.tertiary
                        }}>
                            <Inbox size={48} style={{ marginBottom: '16px', opacity: 0.5 }} />
                            <div>Chưa có giao dịch nào</div>
                        </div>
                    ) : (
                        <div style={{ overflowX: 'auto', maxHeight: '500px', overflowY: 'auto' }}>
                            <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '800px' }}>
                                <thead>
                                    <tr>
                                        <th style={thStyle('left', '100px')}>Thời gian</th>
                                        <th style={thStyle('left', '90px')}>Cặp</th>
                                        <th style={thStyle('center', '70px')}>Loại</th>
                                        <th style={thStyle('right', '80px')}>Margin</th>
                                        <th style={thStyle('right', '100px')}>Entry</th>
                                        <th style={thStyle('right', '100px')}>Exit</th>
                                        <th style={thStyle('right', '120px')}>P&L</th>
                                        <th style={thStyle('center', '70px')}>Thời lượng</th>
                                        <th style={thStyle('center', '90px')}>Lý do</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {trades?.trades.map((trade, index) => {
                                        const exitPrice = calculateExitPrice(trade);
                                        const pnlPercent = calculatePnlPercent(trade);
                                        const isProfitable = trade.realized_pnl >= 0;

                                        return (
                                            <tr
                                                key={trade.id}
                                                style={{
                                                    borderBottom: `1px solid ${THEME.border.secondary}`,
                                                    backgroundColor: index % 2 === 0 ? 'transparent' : 'rgba(30,35,41,0.3)',
                                                    transition: 'background-color 0.15s',
                                                }}
                                                onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'rgba(240,185,11,0.05)'}
                                                onMouseLeave={(e) => e.currentTarget.style.backgroundColor = index % 2 === 0 ? 'transparent' : 'rgba(30,35,41,0.3)'}
                                            >
                                                {/* Time */}
                                                <td style={{ ...tdStyle('left'), fontFamily: "'JetBrains Mono', monospace", fontSize: '11px', color: THEME.text.secondary }}>
                                                    {formatVietnamDate(trade.close_time || trade.open_time)}
                                                </td>

                                                {/* Symbol - SOTA: Always uppercase */}
                                                <td style={{ ...tdStyle('left'), fontWeight: 700, color: THEME.text.primary }}>
                                                    {trade.symbol.toUpperCase()}
                                                </td>

                                                {/* Side */}
                                                <td style={tdStyle('center')}>
                                                    <span style={{
                                                        display: 'inline-block',
                                                        padding: '4px 10px',
                                                        borderRadius: '4px',
                                                        fontSize: '10px',
                                                        fontWeight: 700,
                                                        backgroundColor: trade.side === 'LONG' ? THEME.alpha.buyBg : THEME.alpha.sellBg,
                                                        color: trade.side === 'LONG' ? THEME.status.buy : THEME.status.sell
                                                    }}>
                                                        {trade.side === 'LONG' ? 'MUA' : 'BÁN'}
                                                    </span>
                                                </td>

                                                {/* Margin - NEW COLUMN */}
                                                <td style={{ ...tdStyle('right'), fontFamily: "'JetBrains Mono', monospace", fontSize: '11px', color: THEME.text.secondary }}>
                                                    ${formatPrice(trade.margin)}
                                                </td>

                                                {/* Entry Price */}
                                                <td style={{ ...tdStyle('right'), fontFamily: "'JetBrains Mono', monospace", color: THEME.text.primary }}>
                                                    ${formatPrice(trade.entry_price)}
                                                </td>

                                                {/* Exit Price - SOTA: Calculated */}
                                                <td style={{ ...tdStyle('right'), fontFamily: "'JetBrains Mono', monospace", color: THEME.text.secondary }}>
                                                    {exitPrice !== null ? `$${formatPrice(exitPrice)}` : '-'}
                                                </td>

                                                {/* P&L - SOTA: Both $ and % */}
                                                <td style={{ ...tdStyle('right') }}>
                                                    <div style={{
                                                        display: 'flex',
                                                        flexDirection: 'column',
                                                        alignItems: 'flex-end',
                                                        gap: '2px'
                                                    }}>
                                                        <span style={{
                                                            fontFamily: "'JetBrains Mono', monospace",
                                                            fontWeight: 700,
                                                            color: isProfitable ? THEME.status.buy : THEME.status.sell
                                                        }}>
                                                            {isProfitable ? '+' : ''}{formatPrice(trade.realized_pnl)}
                                                        </span>
                                                        <span style={{
                                                            fontFamily: "'JetBrains Mono', monospace",
                                                            fontSize: '10px',
                                                            color: isProfitable ? THEME.status.buy : THEME.status.sell,
                                                            opacity: 0.8
                                                        }}>
                                                            ({pnlPercent >= 0 ? '+' : ''}{pnlPercent.toFixed(2)}%)
                                                        </span>
                                                    </div>
                                                </td>

                                                {/* Duration */}
                                                <td style={{ ...tdStyle('center'), fontFamily: "'JetBrains Mono', monospace", fontSize: '11px', color: THEME.text.tertiary }}>
                                                    {calculateDuration(trade.open_time, trade.close_time)}
                                                </td>

                                                {/* Exit Reason */}
                                                <td style={tdStyle('center')}>
                                                    {getExitReasonBadge(trade.exit_reason)}
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                    )}

                    {/* Pagination - SOTA: Page numbers */}
                    {trades && trades.total_pages > 1 && (
                        <div style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            marginTop: '16px',
                            paddingTop: '16px',
                            borderTop: `1px solid ${THEME.border.primary}`
                        }}>
                            <span style={{ fontSize: '12px', color: THEME.text.tertiary }}>
                                Trang {trades.page} / {trades.total_pages}
                            </span>
                            <div style={{ display: 'flex', gap: '4px' }}>
                                {/* Previous */}
                                <button
                                    onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                                    disabled={currentPage === 1}
                                    style={{
                                        padding: '8px 12px',
                                        fontSize: '12px',
                                        borderRadius: '4px',
                                        border: 'none',
                                        cursor: currentPage === 1 ? 'not-allowed' : 'pointer',
                                        backgroundColor: THEME.bg.vessel,
                                        color: THEME.text.secondary,
                                        opacity: currentPage === 1 ? 0.5 : 1,
                                    }}
                                >
                                    ←
                                </button>

                                {/* Page Numbers */}
                                {(() => {
                                    const pages = [];
                                    const totalPages = trades.total_pages;
                                    const current = currentPage;

                                    // Calculate visible page range
                                    let start = Math.max(1, current - 2);
                                    let end = Math.min(totalPages, start + 4);
                                    start = Math.max(1, end - 4);

                                    for (let i = start; i <= end; i++) {
                                        pages.push(
                                            <button
                                                key={i}
                                                onClick={() => setCurrentPage(i)}
                                                style={{
                                                    padding: '8px 12px',
                                                    fontSize: '12px',
                                                    fontWeight: currentPage === i ? 700 : 400,
                                                    borderRadius: '4px',
                                                    border: 'none',
                                                    cursor: 'pointer',
                                                    backgroundColor: currentPage === i ? THEME.accent.yellow : THEME.bg.vessel,
                                                    color: currentPage === i ? '#000' : THEME.text.secondary,
                                                    minWidth: '36px',
                                                }}
                                            >
                                                {i}
                                            </button>
                                        );
                                    }
                                    return pages;
                                })()}

                                {/* Next */}
                                <button
                                    onClick={() => setCurrentPage(p => Math.min(trades.total_pages, p + 1))}
                                    disabled={currentPage === trades.total_pages}
                                    style={{
                                        padding: '8px 12px',
                                        fontSize: '12px',
                                        borderRadius: '4px',
                                        border: 'none',
                                        cursor: currentPage === trades.total_pages ? 'not-allowed' : 'pointer',
                                        backgroundColor: THEME.bg.vessel,
                                        color: THEME.text.secondary,
                                        opacity: currentPage === trades.total_pages ? 0.5 : 1,
                                    }}
                                >
                                    →
                                </button>
                            </div>
                        </div>
                    )}
                </>
            )}

            {/* SOTA Phase 25: Enhanced Signals Tab with Filter, Pagination, Expandable Rows */}
            {activeTab === 'signals' && (
                <div style={containerStyle}>
                    {/* Header with export button */}
                    <div style={{ marginBottom: '16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <h3 style={{ fontSize: '14px', fontWeight: 600, color: THEME.text.primary, margin: 0 }}>
                            Lịch sử tín hiệu (30 ngày gần nhất)
                        </h3>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                            <span style={{ fontSize: '11px', color: THEME.text.tertiary }}>
                                {signalPagination.total} tín hiệu
                            </span>
                            <button
                                onClick={() => {
                                    const exportUrl = apiUrl(ENDPOINTS.SIGNAL_EXPORT(
                                        30, 'csv',
                                        signalFilterSymbol || undefined,
                                        signalFilterType || undefined,
                                        signalFilterStatus || undefined
                                    ));
                                    window.open(exportUrl, '_blank');
                                }}
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '6px',
                                    padding: '6px 12px',
                                    borderRadius: '6px',
                                    border: `1px solid ${THEME.border.primary}`,
                                    backgroundColor: THEME.bg.vessel,
                                    color: THEME.text.secondary,
                                    fontSize: '11px',
                                    fontWeight: 600,
                                    cursor: 'pointer',
                                }}
                            >
                                <Download size={14} />
                                Export CSV
                            </button>
                        </div>
                    </div>

                    {/* SOTA Phase 25: Filter Bar */}
                    <div style={{
                        display: 'flex',
                        gap: '12px',
                        marginBottom: '16px',
                        alignItems: 'center',
                        padding: '12px 16px',
                        backgroundColor: 'rgba(24, 26, 32, 0.6)',
                        borderRadius: '8px',
                        border: '1px solid rgba(255,255,255,0.05)'
                    }}>
                        <Filter size={16} style={{ color: THEME.text.tertiary }} />

                        {/* Symbol Filter */}
                        <select
                            value={signalFilterSymbol}
                            onChange={(e) => setSignalFilterSymbol(e.target.value)}
                            style={{
                                backgroundColor: THEME.bg.vessel,
                                color: THEME.text.primary,
                                border: `1px solid ${THEME.border.primary}`,
                                borderRadius: '6px',
                                padding: '6px 10px',
                                fontSize: '12px',
                                cursor: 'pointer',
                                outline: 'none'
                            }}
                        >
                            <option value="">Tất cả Symbol</option>
                            {allSymbols.map(sym => (
                                <option key={sym} value={sym.toLowerCase()}>{sym.toUpperCase()}</option>
                            ))}
                        </select>

                        {/* Type Filter */}
                        <select
                            value={signalFilterType}
                            onChange={(e) => setSignalFilterType(e.target.value)}
                            style={{
                                backgroundColor: THEME.bg.vessel,
                                color: THEME.text.primary,
                                border: `1px solid ${THEME.border.primary}`,
                                borderRadius: '6px',
                                padding: '6px 10px',
                                fontSize: '12px',
                                cursor: 'pointer',
                                outline: 'none'
                            }}
                        >
                            <option value="">Tất cả Loại</option>
                            <option value="buy">MUA</option>
                            <option value="sell">BÁN</option>
                        </select>

                        {/* Status Filter */}
                        <select
                            value={signalFilterStatus}
                            onChange={(e) => setSignalFilterStatus(e.target.value)}
                            style={{
                                backgroundColor: THEME.bg.vessel,
                                color: THEME.text.primary,
                                border: `1px solid ${THEME.border.primary}`,
                                borderRadius: '6px',
                                padding: '6px 10px',
                                fontSize: '12px',
                                cursor: 'pointer',
                                outline: 'none'
                            }}
                        >
                            <option value="">Tất cả Status</option>
                            <option value="generated">Generated</option>
                            <option value="pending">Pending</option>
                            <option value="executed">Executed</option>
                            <option value="expired">Expired</option>
                        </select>
                    </div>

                    {signalsLoading ? (
                        <div style={{ textAlign: 'center', padding: '40px', color: THEME.text.tertiary }}>
                            Đang tải...
                        </div>
                    ) : signals.length === 0 ? (
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '60px 20px' }}>
                            <Activity size={48} style={{ color: THEME.text.tertiary, marginBottom: '16px', display: 'block' }} />
                            <p style={{ fontSize: '14px', color: THEME.text.tertiary, margin: 0, textAlign: 'center' }}>
                                Chưa có tín hiệu nào phù hợp
                            </p>
                        </div>
                    ) : (
                        <>
                            <div style={{ overflowX: 'auto' }}>
                                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                                    <thead>
                                        <tr style={{ backgroundColor: THEME.bg.tertiary }}>
                                            <th style={thStyle('left', '30px')}></th>
                                            <th style={thStyle('left')}>THỜI GIAN</th>
                                            <th style={thStyle('left')}>SYMBOL</th>
                                            <th style={thStyle('center')}>LOẠI</th>
                                            <th style={thStyle('center')}>STATUS</th>
                                            <th style={thStyle('right')}>GIÁ</th>
                                            <th style={thStyle('right')}>ENTRY</th>
                                            <th style={thStyle('right')}>SL</th>
                                            <th style={thStyle('center')}>R:R</th>
                                            <th style={thStyle('center')}>CONF</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {signals.map((signal) => (
                                            <React.Fragment key={signal.id}>
                                                {/* Main row - Clickable to expand */}
                                                <tr
                                                    onClick={() => setExpandedSignalId(expandedSignalId === signal.id ? null : signal.id)}
                                                    style={{
                                                        borderBottom: expandedSignalId === signal.id ? 'none' : `1px solid ${THEME.border.primary}`,
                                                        cursor: 'pointer',
                                                        backgroundColor: expandedSignalId === signal.id ? 'rgba(240,185,11,0.05)' : 'transparent',
                                                        transition: 'background-color 0.2s'
                                                    }}
                                                >
                                                    <td style={{ ...tdStyle('left'), padding: '8px' }}>
                                                        <BarChart2
                                                            size={14}
                                                            style={{
                                                                color: expandedSignalId === signal.id ? THEME.accent.yellow : THEME.text.tertiary,
                                                                transform: expandedSignalId === signal.id ? 'rotate(0deg)' : 'rotate(-90deg)',
                                                                transition: 'transform 0.2s'
                                                            }}
                                                        />
                                                    </td>
                                                    <td style={tdStyle('left')}>
                                                        <span style={{ color: THEME.text.secondary, fontSize: '11px' }}>
                                                            {signal.generated_at ? formatVietnamDate(signal.generated_at) : '-'}
                                                        </span>
                                                    </td>
                                                    <td style={tdStyle('left')}>
                                                        <span style={{ fontWeight: 600, color: THEME.text.primary }}>
                                                            {signal.symbol}
                                                        </span>
                                                    </td>
                                                    <td style={tdStyle('center')}>
                                                        <span style={{
                                                            padding: '3px 8px',
                                                            borderRadius: '4px',
                                                            fontSize: '10px',
                                                            fontWeight: 700,
                                                            backgroundColor: signal.signal_type === 'buy' ? THEME.alpha.buyBg : THEME.alpha.sellBg,
                                                            color: signal.signal_type === 'buy' ? THEME.status.buy : THEME.status.sell,
                                                        }}>
                                                            {signal.signal_type === 'buy' ? 'MUA' : 'BÁN'}
                                                        </span>
                                                    </td>
                                                    <td style={tdStyle('center')}>
                                                        <span style={{
                                                            padding: '3px 8px',
                                                            borderRadius: '4px',
                                                            fontSize: '10px',
                                                            fontWeight: 600,
                                                            backgroundColor: signal.status === 'executed' ? THEME.alpha.buyBg
                                                                : signal.status === 'expired' ? THEME.alpha.sellBg
                                                                    : THEME.bg.vessel,
                                                            color: signal.status === 'executed' ? THEME.status.buy
                                                                : signal.status === 'expired' ? THEME.status.sell
                                                                    : THEME.text.secondary,
                                                        }}>
                                                            {signal.status.toUpperCase()}
                                                        </span>
                                                    </td>
                                                    <td style={tdStyle('right')}>
                                                        <span style={{ fontFamily: 'JetBrains Mono, monospace', color: THEME.text.primary }}>
                                                            ${formatPrice(signal.price)}
                                                        </span>
                                                    </td>
                                                    <td style={tdStyle('right')}>
                                                        <span style={{ fontFamily: 'JetBrains Mono, monospace', color: THEME.accent.yellow }}>
                                                            {signal.entry_price ? `$${formatPrice(signal.entry_price)}` : '-'}
                                                        </span>
                                                    </td>
                                                    <td style={tdStyle('right')}>
                                                        <span style={{ fontFamily: 'JetBrains Mono, monospace', color: THEME.status.sell }}>
                                                            {signal.stop_loss ? `$${formatPrice(signal.stop_loss)}` : '-'}
                                                        </span>
                                                    </td>
                                                    <td style={tdStyle('center')}>
                                                        <span style={{ fontWeight: 600, color: THEME.text.secondary }}>
                                                            {signal.risk_reward_ratio ? `1:${signal.risk_reward_ratio.toFixed(1)}` : '-'}
                                                        </span>
                                                    </td>
                                                    <td style={tdStyle('center')}>
                                                        <span style={{
                                                            fontWeight: 600,
                                                            color: signal.confidence >= 0.8 ? THEME.status.buy
                                                                : signal.confidence >= 0.65 ? THEME.accent.yellow
                                                                    : THEME.text.tertiary
                                                        }}>
                                                            {(signal.confidence * 100).toFixed(0)}%
                                                        </span>
                                                    </td>
                                                </tr>

                                                {/* SOTA Phase 25: Expandable Row - Indicators & Reasons */}
                                                {expandedSignalId === signal.id && (
                                                    <tr>
                                                        <td colSpan={10} style={{ padding: 0 }}>
                                                            <div style={{
                                                                padding: '16px 20px',
                                                                backgroundColor: 'rgba(24, 26, 32, 0.8)',
                                                                borderBottom: `1px solid ${THEME.border.primary}`,
                                                            }}>
                                                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
                                                                    {/* Indicators Section */}
                                                                    <div>
                                                                        <h4 style={{
                                                                            fontSize: '11px',
                                                                            color: THEME.text.tertiary,
                                                                            textTransform: 'uppercase',
                                                                            marginBottom: '12px',
                                                                            display: 'flex',
                                                                            alignItems: 'center',
                                                                            gap: '6px'
                                                                        }}>
                                                                            <BarChart3 size={14} />
                                                                            Indicators tại thời điểm signal
                                                                        </h4>
                                                                        <div style={{
                                                                            display: 'grid',
                                                                            gridTemplateColumns: 'repeat(3, 1fr)',
                                                                            gap: '8px',
                                                                            fontSize: '11px'
                                                                        }}>
                                                                            {signal.indicators && Object.entries(signal.indicators).map(([key, value]) => (
                                                                                <div key={key} style={{
                                                                                    padding: '6px 8px',
                                                                                    backgroundColor: THEME.bg.vessel,
                                                                                    borderRadius: '4px',
                                                                                    display: 'flex',
                                                                                    justifyContent: 'space-between'
                                                                                }}>
                                                                                    <span style={{ color: THEME.text.tertiary }}>{key}:</span>
                                                                                    <span style={{ color: THEME.text.primary, fontFamily: 'JetBrains Mono, monospace' }}>
                                                                                        {typeof value === 'number' ? value.toFixed(2) : String(value)}
                                                                                    </span>
                                                                                </div>
                                                                            ))}
                                                                        </div>
                                                                    </div>

                                                                    {/* Reasons/Conditions Section */}
                                                                    <div>
                                                                        <h4 style={{
                                                                            fontSize: '11px',
                                                                            color: THEME.text.tertiary,
                                                                            textTransform: 'uppercase',
                                                                            marginBottom: '12px',
                                                                            display: 'flex',
                                                                            alignItems: 'center',
                                                                            gap: '6px'
                                                                        }}>
                                                                            <Target size={14} />
                                                                            Điều kiện đã đạt ({signal.reasons?.length || 0})
                                                                        </h4>
                                                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                                                            {signal.reasons && signal.reasons.length > 0 ? (
                                                                                signal.reasons.map((reason, idx) => (
                                                                                    <div key={idx} style={{
                                                                                        display: 'flex',
                                                                                        alignItems: 'center',
                                                                                        gap: '8px',
                                                                                        fontSize: '11px',
                                                                                        padding: '4px 8px',
                                                                                        backgroundColor: THEME.bg.vessel,
                                                                                        borderRadius: '4px'
                                                                                    }}>
                                                                                        <Target size={12} style={{ color: THEME.status.buy, flexShrink: 0 }} />
                                                                                        <span style={{ color: THEME.text.secondary }}>{reason}</span>
                                                                                    </div>
                                                                                ))
                                                                            ) : (
                                                                                <span style={{ color: THEME.text.tertiary, fontSize: '11px' }}>
                                                                                    Không có thông tin điều kiện
                                                                                </span>
                                                                            )}
                                                                        </div>
                                                                    </div>
                                                                </div>

                                                                {/* TP Levels */}
                                                                {signal.tp_levels && (
                                                                    <div style={{ marginTop: '12px', display: 'flex', gap: '16px', fontSize: '11px' }}>
                                                                        {signal.tp_levels.tp1 && (
                                                                            <span style={{ color: THEME.text.tertiary }}>
                                                                                TP1: <span style={{ color: THEME.status.buy }}>${formatPrice(signal.tp_levels.tp1)}</span>
                                                                            </span>
                                                                        )}
                                                                        {signal.tp_levels.tp2 && (
                                                                            <span style={{ color: THEME.text.tertiary }}>
                                                                                TP2: <span style={{ color: THEME.status.buy }}>${formatPrice(signal.tp_levels.tp2)}</span>
                                                                            </span>
                                                                        )}
                                                                        {signal.tp_levels.tp3 && (
                                                                            <span style={{ color: THEME.text.tertiary }}>
                                                                                TP3: <span style={{ color: THEME.status.buy }}>${formatPrice(signal.tp_levels.tp3)}</span>
                                                                            </span>
                                                                        )}
                                                                    </div>
                                                                )}
                                                            </div>
                                                        </td>
                                                    </tr>
                                                )}
                                            </React.Fragment>
                                        ))}
                                    </tbody>
                                </table>
                            </div>

                            {/* SOTA Phase 25: Signal Pagination */}
                            {signalPagination.total_pages > 1 && (
                                <div style={{
                                    display: 'flex',
                                    justifyContent: 'space-between',
                                    alignItems: 'center',
                                    marginTop: '16px',
                                    paddingTop: '16px',
                                    borderTop: `1px solid ${THEME.border.primary}`
                                }}>
                                    <span style={{ fontSize: '12px', color: THEME.text.tertiary }}>
                                        Trang {signalPage} / {signalPagination.total_pages}
                                    </span>
                                    <div style={{ display: 'flex', gap: '4px' }}>
                                        <button
                                            onClick={() => setSignalPage(p => Math.max(1, p - 1))}
                                            disabled={signalPage === 1}
                                            style={{
                                                padding: '8px 12px',
                                                fontSize: '12px',
                                                borderRadius: '4px',
                                                border: 'none',
                                                cursor: signalPage === 1 ? 'not-allowed' : 'pointer',
                                                backgroundColor: THEME.bg.vessel,
                                                color: THEME.text.secondary,
                                                opacity: signalPage === 1 ? 0.5 : 1,
                                            }}
                                        >
                                            ←
                                        </button>
                                        {(() => {
                                            const pages = [];
                                            const totalPages = signalPagination.total_pages;
                                            let start = Math.max(1, signalPage - 2);
                                            let end = Math.min(totalPages, start + 4);
                                            start = Math.max(1, end - 4);

                                            for (let i = start; i <= end; i++) {
                                                pages.push(
                                                    <button
                                                        key={i}
                                                        onClick={() => setSignalPage(i)}
                                                        style={{
                                                            padding: '8px 12px',
                                                            fontSize: '12px',
                                                            fontWeight: signalPage === i ? 700 : 400,
                                                            borderRadius: '4px',
                                                            border: 'none',
                                                            cursor: 'pointer',
                                                            backgroundColor: signalPage === i ? THEME.accent.yellow : THEME.bg.vessel,
                                                            color: signalPage === i ? '#000' : THEME.text.secondary,
                                                            minWidth: '36px',
                                                        }}
                                                    >
                                                        {i}
                                                    </button>
                                                );
                                            }
                                            return pages;
                                        })()}
                                        <button
                                            onClick={() => setSignalPage(p => Math.min(signalPagination.total_pages, p + 1))}
                                            disabled={signalPage === signalPagination.total_pages}
                                            style={{
                                                padding: '8px 12px',
                                                fontSize: '12px',
                                                borderRadius: '4px',
                                                border: 'none',
                                                cursor: signalPage === signalPagination.total_pages ? 'not-allowed' : 'pointer',
                                                backgroundColor: THEME.bg.vessel,
                                                color: THEME.text.secondary,
                                                opacity: signalPage === signalPagination.total_pages ? 0.5 : 1,
                                            }}
                                        >
                                            →
                                        </button>
                                    </div>
                                </div>
                            )}
                        </>
                    )}
                </div>
            )}
        </div>
    );
};

// SOTA: Wrap with memo to prevent parent re-render propagation
const TradeHistory = memo(TradeHistoryInner);
TradeHistory.displayName = 'TradeHistory';

export default TradeHistory;
