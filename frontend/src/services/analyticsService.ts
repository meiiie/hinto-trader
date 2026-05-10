/**
 * Analytics Service — v6.3.0 Binance Truth API Client
 *
 * Connects to main backend /analytics/* endpoints (same port as trading).
 * All data sourced from Binance API (not system logs).
 */

import { apiUrl } from '../config/api';

// ─── Response Types (match backend exactly) ───────────────────────────

export interface EquityPoint {
    trade_num: number;
    trade_time: number;
    symbol: string;
    net_pnl: number;
    cumulative_pnl: number;
    result: 'WIN' | 'LOSS';
}

export interface SignificanceResult {
    p_value: number;
    z_score: number;
    is_significant: boolean;
    observed_wr: number;
    breakeven_wr: number;
    edge_pp: number;
    trades_needed: number;
    message: string;
}

export interface RollingPoint {
    trade_num: number;
    rolling_wr: number;
    rolling_pnl: number;
}

export interface DailyBreakdown {
    date: string;
    trades: number;
    wins: number;
    losses: number;
    win_rate: number;
    net_pnl: number;
}

export interface RiskMetrics {
    sharpe_per_trade: number;
    sortino_per_trade: number;
    calmar_ratio: number;
    max_drawdown: number;
    max_drawdown_trades: number;
    current_streak: number;
    max_win_streak: number;
    max_loss_streak: number;
}

export interface AnalyticsSummary {
    total_trades: number;
    wins: number;
    losses: number;
    win_rate: number;
    profit_factor: number;
    total_net_pnl: number;
    total_gross_pnl: number;
    total_fees: number;
    fee_drag_pct: number;
    avg_win: number;
    avg_loss: number;
    rr_ratio: number;
    breakeven_wr: number;
    edge_pp: number;
    expectancy: number;
    largest_win: number;
    largest_loss: number;
    risk_metrics: RiskMetrics;
    equity_curve: EquityPoint[];
    significance: SignificanceResult;
    rolling: { window: number; points: RollingPoint[] };
    daily_breakdown: DailyBreakdown[];
    version_tag: string;
    days_filter: number | null;
    generated_at: string;
}

// ─── Session Types ────────────────────────────────────────────────────

export interface SlotData {
    slot: string;
    trades: number;
    wins: number;
    losses: number;
    win_rate: number;
    net_pnl: number;
}

export interface HourlyData {
    hour: number;
    label: string;
    trades: number;
    wins: number;
    losses: number;
    win_rate: number;
    net_pnl: number;
    in_dead_zone: boolean;
}

export interface ToxicGoldHour {
    hour: number;
    trades: number;
    win_rate: number;
    net_pnl: number;
}

export interface DeadZoneAnalysis {
    current_dead_zones: string[];
    non_dz_trades: number;
    non_dz_win_rate: number;
    non_dz_pnl: number;
    dz_trades_would_block: number;
    dz_would_block_wr: number;
    dz_would_block_pnl: number;
    dz_pnl_saved: number;
    toxic_hours: ToxicGoldHour[];
    gold_hours: ToxicGoldHour[];
}

export interface SessionData {
    slots: SlotData[];
    hourly: HourlyData[];
    dead_zone_analysis: DeadZoneAnalysis;
    total_trades: number;
}

// ─── Symbol Types ─────────────────────────────────────────────────────

export interface SymbolStats {
    symbol: string;
    classification: 'ALPHA+' | 'NEUTRAL' | 'TOXIC';
    trades: number;
    wins: number;
    losses: number;
    win_rate: number;
    net_pnl: number;
    gross_pnl: number;
    fees: number;
    avg_pnl: number;
    long_trades: number;
    long_wr: number;
    short_trades: number;
    short_wr: number;
}

export interface SymbolDecomposition {
    symbols: SymbolStats[];
    alpha: SymbolStats[];
    neutral: SymbolStats[];
    toxic: SymbolStats[];
    summary: {
        total_symbols: number;
        alpha_count: number;
        neutral_count: number;
        toxic_count: number;
        alpha_pnl: number;
        toxic_pnl: number;
    };
}

// ─── Direction Types ──────────────────────────────────────────────────

export interface DirectionStats {
    direction: string;
    trades: number;
    wins: number;
    losses: number;
    win_rate: number;
    net_pnl: number;
    avg_win: number;
    avg_loss: number;
    rr_ratio: number;
}

export interface DirectionData {
    long: DirectionStats;
    short: DirectionStats;
    total_trades: number;
    long_pct: number;
    short_pct: number;
    recommendation: string;
}

// ─── Other Types ──────────────────────────────────────────────────────

export interface TodayMetrics {
    date: string;
    trades: number;
    wins: number;
    losses: number;
    win_rate: number;
    net_pnl: number;
}

export interface SnapshotData {
    snapshot_date: string;
    total_trades: number;
    win_rate: number;
    profit_factor: number;
    total_net_pnl: number;
    rr_ratio: number;
    edge_pp: number;
    sharpe_per_trade: number;
    max_drawdown: number;
    day_trades: number;
    day_net_pnl: number;
    day_win_rate: number;
    p_value: number;
    version_tag: string;
    created_at: string;
}

// ─── Service ──────────────────────────────────────────────────────────

async function fetchJson<T>(path: string, options?: RequestInit): Promise<T> {
    const res = await fetch(apiUrl(path), {
        ...options,
        headers: { 'Content-Type': 'application/json', ...options?.headers },
    });
    if (!res.ok) {
        const detail = await res.text().catch(() => res.statusText);
        throw new Error(`Analytics API ${res.status}: ${detail}`);
    }
    return res.json();
}

function buildQs(params: Record<string, string | number | undefined>): string {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
        if (v !== undefined && v !== null) qs.append(k, String(v));
    }
    const s = qs.toString();
    return s ? `?${s}` : '';
}

export const analyticsApi = {
    /** Full analytics report (WR, PF, R:R, edge, Sharpe, equity curve, significance) */
    getSummary: (version?: string, days?: number) =>
        fetchJson<AnalyticsSummary>(`/analytics/summary${buildQs({ version, days })}`),

    /** Session heatmap (30-min slots, hourly, dead zone analysis) */
    getSessions: (version?: string) =>
        fetchJson<SessionData>(`/analytics/sessions${buildQs({ version })}`),

    /** Per-symbol alpha decomposition */
    getSymbols: (version?: string) =>
        fetchJson<SymbolDecomposition>(`/analytics/symbols${buildQs({ version })}`),

    /** LONG vs SHORT direction split */
    getDirections: (version?: string) =>
        fetchJson<DirectionData>(`/analytics/directions${buildQs({ version })}`),

    /** Equity curve data points */
    getEquity: (version?: string, days?: number) =>
        fetchJson<{ equity_curve: EquityPoint[]; total_trades: number }>(
            `/analytics/equity${buildQs({ version, days })}`
        ),

    /** Statistical significance (Z-test) */
    getSignificance: (version?: string) =>
        fetchJson<SignificanceResult>(`/analytics/significance${buildQs({ version })}`),

    /** Dead zone effectiveness */
    getDeadZones: (version?: string) =>
        fetchJson<DeadZoneAnalysis>(`/analytics/dead-zones${buildQs({ version })}`),

    /** Today's quick metrics */
    getToday: () =>
        fetchJson<TodayMetrics>('/analytics/today'),

    /** Historical daily snapshots */
    getSnapshots: (days: number = 30) =>
        fetchJson<{ snapshots: SnapshotData[] }>(`/analytics/snapshots${buildQs({ days })}`),

    /** Trigger Binance trade reconciliation */
    reconcile: () =>
        fetchJson<{ trades_collected: number; new_trades: number }>('/analytics/reconcile', {
            method: 'POST',
        }),

    /** Trigger daily report generation */
    triggerDailyReport: () =>
        fetchJson<{ status: string; report_trades?: number }>('/analytics/daily-report', {
            method: 'POST',
        }),
};

export default analyticsApi;
