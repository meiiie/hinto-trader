import React from 'react';
import {
    ClipboardList,
    BarChart3,
    TrendingUp,
    Activity,
    Target,
    Shield,
    Hand,
    RefreshCcw,
    FileText,
    Clock
} from 'lucide-react';
import { THEME, formatPrice, formatVietnamDate } from '../../styles/theme';
import {
    PaginatedTrades,
    PerformanceData,
    SignalRecord,
    AnalyticsTab
} from '../TradeHistory';

interface TradeHistoryMobileProps {
    activeTab: AnalyticsTab;
    setActiveTab: (tab: AnalyticsTab) => void;
    trades: PaginatedTrades | null;
    performance: PerformanceData | null;
    signals: SignalRecord[];
    tradingMode: string;
    itemsPerPage?: number;
    onPageChange?: (page: number) => void;
    currentPage?: number;
    isLoading: boolean;
}

const COLORS = {
    bg: THEME.bg.primary,
    bgSecondary: THEME.bg.secondary,
    bgTertiary: THEME.bg.tertiary,
    textPrimary: THEME.text.primary,
    textSecondary: THEME.text.secondary,
    textTertiary: THEME.text.tertiary,
    buy: THEME.status.buy,
    sell: THEME.status.sell,
    yellow: THEME.accent.yellow,
    border: THEME.border.primary
};

const MobileTab: React.FC<{
    label: string;
    icon: React.ReactNode;
    isActive: boolean;
    onClick: () => void;
}> = ({ label, icon, isActive, onClick }) => (
    <div
        onClick={onClick}
        style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '12px 4px',
            cursor: 'pointer',
            borderBottom: isActive ? `2px solid ${COLORS.yellow}` : '2px solid transparent',
            color: isActive ? COLORS.textPrimary : COLORS.textTertiary,
            transition: 'all 0.2s',
            background: isActive ? `${COLORS.yellow}10` : 'transparent'
        }}
    >
        <div style={{ marginBottom: 4 }}>{icon}</div>
        <div style={{ fontSize: 11, fontWeight: 600 }}>{label}</div>
    </div>
);

// Helper to get exit reason style
const getExitReasonBadge = (reason: string | null) => {
    if (!reason) return <span style={{ color: COLORS.textTertiary }}>-</span>;

    const config: Record<string, { color: string, label: string, Icon: React.FC<{ size?: number }> }> = {
        'TAKE_PROFIT': { color: COLORS.buy, label: 'TP', Icon: Target },
        'STOP_LOSS': { color: COLORS.sell, label: 'SL', Icon: Shield },
        'MANUAL_CLOSE': { color: THEME.status.info, label: 'Manual', Icon: Hand },
        'SIGNAL_REVERSAL': { color: COLORS.yellow, label: 'Flip', Icon: RefreshCcw },
    };

    const conf = config[reason] || { color: COLORS.textTertiary, label: reason, Icon: FileText };
    const Icon = conf.Icon;

    return (
        <span style={{
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            fontSize: 10,
            fontWeight: 700,
            color: conf.color,
            backgroundColor: `${conf.color}15`,
            padding: '2px 6px',
            borderRadius: 4,
            marginLeft: 8
        }}>
            <Icon size={10} />
            {conf.label}
        </span>
    );
};

export const TradeHistoryMobile: React.FC<TradeHistoryMobileProps> = ({
    activeTab,
    setActiveTab,
    trades,
    performance,
    signals,
    tradingMode,
    currentPage = 1,
    onPageChange,
    isLoading
}) => {

    const renderOverview = () => {
        if (!performance) return <div style={{ padding: 20, textAlign: 'center', color: COLORS.textTertiary }}>No data available</div>;

        return (
            <div style={{ padding: 16 }}>
                {/* Trading Mode Badge */}
                <div style={{
                    display: 'flex',
                    justifyContent: 'center',
                    marginBottom: 16
                }}>
                    <span style={{
                        fontSize: 11,
                        fontWeight: 600,
                        padding: '4px 12px',
                        borderRadius: 12,
                        backgroundColor: COLORS.bgTertiary,
                        color: COLORS.textSecondary,
                        display: 'flex',
                        alignItems: 'center',
                        gap: 6
                    }}>
                        {tradingMode === 'LIVE' ? <Activity size={12} color={COLORS.buy} /> : <Clock size={12} />}
                        {tradingMode} MODE
                    </span>
                </div>

                {/* Key Metrics Grid */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
                    <div style={{ background: COLORS.bgSecondary, padding: 16, borderRadius: 12, border: `1px solid ${COLORS.border}` }}>
                        <div style={{ fontSize: 11, color: COLORS.textTertiary, marginBottom: 4 }}>WIN RATE</div>
                        <div style={{ fontSize: 20, fontWeight: 700, color: (performance.win_rate || 0) >= 50 ? COLORS.buy : COLORS.sell }}>
                            {(performance.win_rate || 0).toFixed(1)}%
                        </div>
                    </div>
                    <div style={{ background: COLORS.bgSecondary, padding: 16, borderRadius: 12, border: `1px solid ${COLORS.border}` }}>
                        <div style={{ fontSize: 11, color: COLORS.textTertiary, marginBottom: 4 }}>PROFIT FACTOR</div>
                        <div style={{ fontSize: 20, fontWeight: 700, color: (performance.profit_factor || 0) >= 1.5 ? COLORS.buy : COLORS.textPrimary }}>
                            {(performance.profit_factor || 0).toFixed(2)}
                        </div>
                    </div>
                    <div style={{ background: COLORS.bgSecondary, padding: 16, borderRadius: 12, border: `1px solid ${COLORS.border}` }}>
                        <div style={{ fontSize: 11, color: COLORS.textTertiary, marginBottom: 4 }}>TOTAL P&L</div>
                        <div style={{ fontSize: 20, fontWeight: 700, color: (performance.total_pnl || 0) >= 0 ? COLORS.buy : COLORS.sell }}>
                            ${(performance.total_pnl || 0).toFixed(2)}
                        </div>
                    </div>
                    <div style={{ background: COLORS.bgSecondary, padding: 16, borderRadius: 12, border: `1px solid ${COLORS.border}` }}>
                        <div style={{ fontSize: 11, color: COLORS.textTertiary, marginBottom: 4 }}>EXPECTANCY</div>
                        <div style={{ fontSize: 20, fontWeight: 700, color: (performance.expectancy || 0) >= 0 ? COLORS.buy : COLORS.sell }}>
                            ${(performance.expectancy || 0).toFixed(2)}
                        </div>
                    </div>
                </div>

                {/* Recent Streak */}
                {performance.streak_stats && (
                    <div style={{
                        background: COLORS.bgSecondary,
                        padding: '12px 16px',
                        borderRadius: 12,
                        border: `1px solid ${COLORS.border}`,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between'
                    }}>
                        <span style={{ fontSize: 12, color: COLORS.textSecondary }}>Current Streak</span>
                        <span style={{
                            fontSize: 14,
                            fontWeight: 700,
                            color: performance.streak_stats.current_streak > 0 ? COLORS.buy : COLORS.sell
                        }}>
                            {performance.streak_stats.current_streak > 0 ? `🔥 ${performance.streak_stats.current_streak} Wins` : `❄️ ${Math.abs(performance.streak_stats.current_streak)} Losses`}
                        </span>
                    </div>
                )}
            </div>
        );
    };

    const renderHistory = () => {
        if (!trades || trades.trades.length === 0) {
            return (
                <div style={{ padding: 40, textAlign: 'center', color: COLORS.textTertiary }}>
                    <div style={{ marginBottom: 10 }}>📭</div>
                    No trades found
                </div>
            );
        }

        return (
            <div style={{ padding: 16 }}>
                {trades.trades.map((trade) => (
                    <div key={trade.id} style={{
                        background: COLORS.bgSecondary,
                        borderRadius: 12,
                        padding: 16,
                        marginBottom: 12,
                        border: `1px solid ${COLORS.border}`
                    }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                            <div style={{ display: 'flex', alignItems: 'center' }}>
                                <span style={{ fontWeight: 700, fontSize: 15, color: COLORS.textPrimary }}>
                                    {trade.symbol.replace('USDT', '')}
                                </span>
                                <span style={{
                                    fontSize: 10,
                                    fontWeight: 700,
                                    marginLeft: 8,
                                    color: trade.side === 'LONG' ? COLORS.buy : COLORS.sell,
                                    background: trade.side === 'LONG' ? `${COLORS.buy}15` : `${COLORS.sell}15`,
                                    padding: '2px 6px',
                                    borderRadius: 4
                                }}>
                                    {trade.side}
                                </span>
                                {getExitReasonBadge(trade.exit_reason)}
                            </div>
                            <div style={{
                                fontWeight: 700,
                                fontSize: 15,
                                color: trade.realized_pnl >= 0 ? COLORS.buy : COLORS.sell
                            }}>
                                {trade.realized_pnl >= 0 ? '+' : ''}{trade.realized_pnl.toFixed(2)}
                            </div>
                        </div>

                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: COLORS.textTertiary }}>
                            <div>
                                Info: {formatVietnamDate(trade.close_time || trade.open_time)}
                            </div>
                            <div>
                                Entry: {formatPrice(trade.entry_price)}
                            </div>
                        </div>
                    </div>
                ))}

                {/* Simple Pagination */}
                {onPageChange && trades.total_pages > 1 && (
                    <div style={{ display: 'flex', justifyContent: 'center', gap: 12, marginTop: 24, paddingBottom: 20 }}>
                        <button
                            disabled={currentPage === 1}
                            onClick={() => onPageChange(currentPage - 1)}
                            style={{
                                padding: '8px 16px',
                                background: COLORS.bgTertiary,
                                border: 'none',
                                borderRadius: 8,
                                color: COLORS.textPrimary,
                                opacity: currentPage === 1 ? 0.5 : 1
                            }}
                        >
                            Prev
                        </button>
                        <span style={{ display: 'flex', alignItems: 'center', fontSize: 12 }}>
                            Page {currentPage} / {trades.total_pages}
                        </span>
                        <button
                            disabled={currentPage === trades.total_pages}
                            onClick={() => onPageChange(currentPage + 1)}
                            style={{
                                padding: '8px 16px',
                                background: COLORS.bgTertiary,
                                border: 'none',
                                borderRadius: 8,
                                color: COLORS.textPrimary,
                                opacity: currentPage === trades.total_pages ? 0.5 : 1
                            }}
                        >
                            Next
                        </button>
                    </div>
                )}
            </div>
        );
    };

    const renderSignals = () => {
        if (signals.length === 0) {
            return (
                <div style={{ padding: 40, textAlign: 'center', color: COLORS.textTertiary }}>
                    <div style={{ marginBottom: 10 }}>📡</div>
                    No signals recorded
                </div>
            );
        }

        return (
            <div style={{ padding: 16 }}>
                {signals.map((signal) => (
                    <div key={signal.id} style={{
                        background: COLORS.bgSecondary,
                        borderRadius: 12,
                        padding: 16,
                        marginBottom: 12,
                        border: `1px solid ${COLORS.border}`
                    }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                <span style={{ fontWeight: 700, fontSize: 14 }}>{signal.symbol.replace('USDT', '')}</span>
                                <span style={{
                                    fontSize: 10,
                                    padding: '2px 6px',
                                    borderRadius: 4,
                                    fontWeight: 700,
                                    background: signal.signal_type === 'buy' ? `${COLORS.buy}20` : `${COLORS.sell}20`,
                                    color: signal.signal_type === 'buy' ? COLORS.buy : COLORS.sell
                                }}>
                                    {signal.signal_type.toUpperCase()}
                                </span>
                            </div>
                            <span style={{ fontSize: 11, color: COLORS.textTertiary }}>
                                {new Date(signal.generated_at).toLocaleTimeString()}
                            </span>
                        </div>

                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                            <span style={{ color: COLORS.textSecondary }}>Confidence</span>
                            <span style={{
                                fontWeight: 600,
                                color: signal.confidence >= 0.8 ? COLORS.buy : COLORS.yellow
                            }}>
                                {Math.round(signal.confidence * 100)}%
                            </span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginTop: 4 }}>
                            <span style={{ color: COLORS.textSecondary }}>Price</span>
                            <span style={{ color: COLORS.textPrimary }}>{formatPrice(signal.price)}</span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginTop: 4 }}>
                            <span style={{ color: COLORS.textSecondary }}>Reason</span>
                            <span style={{ color: COLORS.textTertiary, maxWidth: '60%', textAlign: 'right', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                {signal.reasons[0] || '-'}
                            </span>
                        </div>
                    </div>
                ))}

                {/* Pagination for signals could go here if props provided */}
            </div>
        );
    };

    return (
        <div style={{ background: COLORS.bg, minHeight: '100%', paddingBottom: 20 }}>
            {/* Header / Tabs */}
            <div style={{
                position: 'sticky',
                top: 0,
                zIndex: 10,
                background: COLORS.bgSecondary,
                borderBottom: `1px solid ${COLORS.border}`,
                display: 'flex',
                boxShadow: '0 4px 12px rgba(0,0,0,0.1)'
            }}>
                <MobileTab
                    label="Overview"
                    icon={<BarChart3 size={18} />}
                    isActive={activeTab === 'overview'}
                    onClick={() => setActiveTab('overview')}
                />
                <MobileTab
                    label="History"
                    icon={<ClipboardList size={18} />}
                    isActive={activeTab === 'history'}
                    onClick={() => setActiveTab('history')}
                />
                <MobileTab
                    label="Tokens"
                    icon={<TrendingUp size={18} />}
                    isActive={activeTab === 'per_token'}
                    onClick={() => setActiveTab('per_token')}
                />
                <MobileTab
                    label="Signals"
                    icon={<Activity size={18} />}
                    isActive={activeTab === 'signals'}
                    onClick={() => setActiveTab('signals')}
                />
            </div>

            {/* Content Area */}
            <div style={{ minHeight: 'calc(100vh - 120px)' }}>
                {isLoading ? (
                    <div style={{ padding: 40, display: 'flex', justifyContent: 'center' }}>
                        <div style={{
                            width: 24,
                            height: 24,
                            border: `2px solid ${COLORS.yellow}`,
                            borderTopColor: 'transparent',
                            borderRadius: '50%',
                            animation: 'spin 1s linear infinite'
                        }} />
                    </div>
                ) : (
                    <>
                        {activeTab === 'overview' && renderOverview()}
                        {activeTab === 'history' && renderHistory()}
                        {activeTab === 'signals' && renderSignals()}
                        {activeTab === 'per_token' && (
                            <div style={{ padding: 40, textAlign: 'center', color: COLORS.textTertiary }}>
                                <div style={{ fontSize: 12 }}>Per-Token stats optimized for desktop.</div>
                                <div style={{ fontSize: 12, marginTop: 4 }}>Check Overview for summaries.</div>
                            </div>
                        )}
                    </>
                )}
            </div>

            <style>
                {`
                @keyframes spin {
                    to { transform: rotate(360deg); }
                }
                `}
            </style>
        </div>
    );
};
