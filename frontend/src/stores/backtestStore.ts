/**
 * SOTA Backtest Store
 *
 * Zustand store for persisting backtest state across tab switches.
 * Prevents data loss when user navigates away from Quant Lab.
 *
 * Features:
 * - Persist backtest results globally
 * - Cache selected symbols and params
 * - Preserve Top 10 tokens list
 */

import { create } from 'zustand';

// ============================================================================
// Types
// ============================================================================

export interface BacktestTrade {
    trade_id: string;
    symbol: string;
    side: string;
    entry_price: number;
    exit_price: number;
    entry_time: string;
    exit_time: string;
    pnl_usd: number;
    pnl_pct: number;
    exit_reason: string;
    position_size: number;
    leverage_at_entry: number;
    // SOTA: Funding rate tracking
    funding_cost?: number;
    // SOTA: Position sizing
    notional_value?: number;
    // SOTA: Optional fields for detailed trade display
    quantity?: number;
    margin_used?: number;
}

export interface BacktestStats {
    total_trades: number;
    win_rate: number;
    net_return_pct: number;
    net_return_usd: number;
    initial_balance: number;
    final_balance: number;
    winning_trades: number;
    losing_trades: number;
    // SOTA: Funding rate metrics
    funding_net?: number;
    funding_paid?: number;
    funding_received?: number;
}

export interface CandleData {
    time: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume?: number;
}

export interface EquityPoint {
    time: string;
    balance: number;
}

export interface BacktestResult {
    symbols: string[];
    stats: BacktestStats;
    trades: BacktestTrade[];
    equity: EquityPoint[];
    candles: Record<string, CandleData[]>;
    indicators: Record<string, {
        vwap: (number | null)[];
        bb_upper: (number | null)[];
        bb_lower: (number | null)[];
    }>;
}

export type DateMode = 'days' | 'custom';

export type MarketMode = 'spot' | 'futures';

export interface BacktestParams {
    interval: string;
    // Market mode: spot or futures
    market_mode: MarketMode;
    // Date mode selection
    dateMode: DateMode;
    days: number;         // Used when dateMode === 'days'
    startDate: string;    // Used when dateMode === 'custom' (ISO date string)
    endDate: string;      // Used when dateMode === 'custom' (ISO date string)
    // Trading params
    balance: number;
    risk: number;
    enable_cb: boolean;
    max_pos: number;
    leverage: number;
    max_order: number;
    max_losses: number;
    cb_cooldown: number;
    drawdown_limit: number;
}

export interface TopToken {
    rank: number;
    symbol: string;
    base: string;
    quote: string;
    name: string;
    volume_24h?: number;
    price_change_pct?: number;
    last_price?: number;
}

// SOTA: Dark Period Presets (Stress Testing)
export const DARK_PERIODS = {
    COVID_CRASH: {
        name: 'COVID Crash',
        description: 'March 2020 - BTC dropped 50% in 1 day',
        startDate: '2020-03-01',
        endDate: '2020-03-31',
    },
    LUNA_COLLAPSE: {
        name: 'Luna Collapse',
        description: 'May 2022 - UST depegged, $45B wiped',
        startDate: '2022-05-01',
        endDate: '2022-05-31',
    },
    FTX_COLLAPSE: {
        name: 'FTX Collapse',
        description: 'Nov 2022 - Exchange bankruptcy, BTC below $16K',
        startDate: '2022-11-01',
        endDate: '2022-11-30',
    },
};

// Helper: Get date N days ago in ISO format
const getDateDaysAgo = (days: number): string => {
    const date = new Date();
    date.setDate(date.getDate() - days);
    return date.toISOString().split('T')[0];
};

const getTodayDate = (): string => new Date().toISOString().split('T')[0];

// Default params matching CLI: --top 10 --days 30 --balance 1000 --leverage 10 --no-cb
const DEFAULT_PARAMS: BacktestParams = {
    interval: '15m',
    market_mode: 'futures',  // SOTA: Default to futures for accurate data
    dateMode: 'days',
    days: 30,
    startDate: getDateDaysAgo(30),
    endDate: getTodayDate(),
    balance: 1000,
    risk: 0.01,
    enable_cb: false,
    max_pos: 10,
    leverage: 10,
    max_order: 50000,
    max_losses: 5,
    cb_cooldown: 4,
    drawdown_limit: 0.15,
};

// ============================================================================
// Store Interface
// ============================================================================

interface BacktestStore {
    // State
    result: BacktestResult | null;
    params: BacktestParams;
    selectedSymbols: string[];
    topTokens: TopToken[];
    loading: boolean;
    loadingTokens: boolean;
    error: string;
    tradePage: number;

    // Actions
    setResult: (result: BacktestResult | null) => void;
    setParams: (params: Partial<BacktestParams>) => void;
    setSelectedSymbols: (symbols: string[]) => void;
    setTopTokens: (tokens: TopToken[]) => void;
    setLoading: (loading: boolean) => void;
    setLoadingTokens: (loading: boolean) => void;
    setError: (error: string) => void;
    setTradePage: (page: number) => void;
    incrementTradePage: () => void;

    // Preset Actions
    applySharkTankPreset: () => void;
    applySniperPreset: () => void;

    // Reset
    clearResult: () => void;
    reset: () => void;
}

// ============================================================================
// Store Implementation
// ============================================================================

export const useBacktestStore = create<BacktestStore>((set, get) => ({
    // Initial State
    result: null,
    params: DEFAULT_PARAMS,
    selectedSymbols: ['BTCUSDT'],
    topTokens: [],
    loading: false,
    loadingTokens: false,
    error: '',
    tradePage: 1,

    // Actions
    setResult: (result) => set({ result, tradePage: 1 }),
    setParams: (params) => set((state) => ({ params: { ...state.params, ...params } })),
    setSelectedSymbols: (selectedSymbols) => set({ selectedSymbols }),
    setTopTokens: (topTokens) => set({ topTokens }),
    setLoading: (loading) => set({ loading }),
    setLoadingTokens: (loadingTokens) => set({ loadingTokens }),
    setError: (error) => set({ error }),
    setTradePage: (tradePage) => set({ tradePage }),
    incrementTradePage: () => set((state) => ({ tradePage: state.tradePage + 1 })),

    // Preset: Shark Tank (matches CLI --top 10 --days 30 --balance 1000 --leverage 10 --no-cb)
    applySharkTankPreset: () => {
        const { topTokens } = get();
        set({
            selectedSymbols: topTokens.slice(0, 10).map(t => t.symbol),
            params: {
                interval: '15m',
                market_mode: 'futures',
                dateMode: 'days',
                days: 30,
                startDate: getDateDaysAgo(30),
                endDate: getTodayDate(),
                balance: 1000,
                risk: 0.01,
                enable_cb: false,
                max_pos: 10,
                leverage: 10,
                max_order: 50000,
                max_losses: 5,
                cb_cooldown: 4,
                drawdown_limit: 0.15,
            },
        });
    },

    // Preset: Sniper (smaller capital, safer settings)
    applySniperPreset: () => {
        const { topTokens } = get();
        set({
            selectedSymbols: topTokens.slice(0, 3).map(t => t.symbol),
            params: {
                interval: '15m',
                market_mode: 'futures',
                dateMode: 'days',
                days: 14,
                startDate: getDateDaysAgo(14),
                endDate: getTodayDate(),
                balance: 500,
                risk: 0.02,
                enable_cb: true,
                max_pos: 3,
                leverage: 5,
                max_order: 10000,
                max_losses: 3,
                cb_cooldown: 4,
                drawdown_limit: 0.10,
            },
        });
    },

    // Clear result only
    clearResult: () => set({ result: null, error: '', tradePage: 1 }),

    // Full reset
    reset: () => set({
        result: null,
        params: DEFAULT_PARAMS,
        selectedSymbols: ['BTCUSDT'],
        loading: false,
        error: '',
        tradePage: 1,
    }),
}));

// Export DEFAULT_PARAMS for reference
export { DEFAULT_PARAMS };
