/**
 * API Configuration - Centralized endpoint management
 *
 * SOTA Best Practice: Environment-based configuration
 * All API URLs are managed here to enable easy deployment to different environments.
 *
 * Usage:
 *   import { API_BASE_URL, WS_BASE_URL, apiUrl } from '@/config/api';
 *
 *   fetch(apiUrl('/trades/portfolio'))
 *   new WebSocket(wsUrl('/ws/stream/btcusdt'))
 */

const DEFAULT_API_URL = 'http://127.0.0.1:8000';
const DEFAULT_WS_URL = 'ws://127.0.0.1:8000';

// Helper to get dynamic base URL (for LAN access functionality)
const getBaseUrl = () => {
    const envUrl = import.meta.env.VITE_API_URL;
    if (envUrl) return envUrl;

    if (typeof window !== 'undefined') {
        const hostname = window.location.hostname;
        if (hostname === 'localhost' || hostname === '127.0.0.1') {
            return DEFAULT_API_URL;
        }
        if (hostname) {
            return `${window.location.protocol}//${hostname}:8000`;
        }
    }

    return DEFAULT_API_URL;
};

const getWsUrl = () => {
    const envUrl = import.meta.env.VITE_WS_URL;
    if (envUrl) return envUrl;

    if (typeof window !== 'undefined') {
        const hostname = window.location.hostname;
        if (hostname === 'localhost' || hostname === '127.0.0.1') {
            return DEFAULT_WS_URL;
        }
        if (hostname) {
            const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            return `${wsProtocol}//${hostname}:8000`;
        }
    }

    return DEFAULT_WS_URL;
};

// Base URLs from environment variables or dynamic detection
export const API_BASE_URL = getBaseUrl();
export const WS_BASE_URL = getWsUrl();

// Lambda URL for Dynamic IP Whitelist (Auto-Unlock Access).
// VITE_* values are public in the browser bundle; do not put private API keys here.
export const LAMBDA_UNLOCK_URL = import.meta.env.VITE_LAMBDA_UNLOCK_URL || '';
export const LAMBDA_SECRET_KEY = import.meta.env.VITE_LAMBDA_SECRET_KEY || '';

/**
 * Build full API URL
 * @param path - API path (e.g., '/trades/portfolio')
 * @returns Full URL (e.g., 'http://127.0.0.1:8000/trades/portfolio')
 */
export const apiUrl = (path: string): string => {
    // Ensure path starts with /
    const normalizedPath = path.startsWith('/') ? path : `/${path}`;
    return `${API_BASE_URL}${normalizedPath}`;
};

/**
 * Build full WebSocket URL
 * @param path - WS path (e.g., '/ws/stream/btcusdt')
 * @returns Full URL (e.g., 'ws://127.0.0.1:8000/ws/stream/btcusdt')
 */
export const wsUrl = (path: string): string => {
    // Ensure path starts with /
    const normalizedPath = path.startsWith('/') ? path : `/${path}`;
    return `${WS_BASE_URL}${normalizedPath}`;
};

// Pre-defined endpoint paths for consistency
export const ENDPOINTS = {
    // Market data
    MARKET_HISTORY: (symbol: string, limit: number = 100) =>
        `/market/history?symbol=${symbol}&limit=${limit}`,
    WS_HISTORY: (symbol: string, timeframe: string, limit: number = 1) =>
        `/ws/history/${symbol}?timeframe=${timeframe}&limit=${limit}`,
    WS_STREAM: (symbol: string) => `/ws/stream/${symbol}`,

    // Trading
    PORTFOLIO: '/trades/portfolio',
    // SOTA Phase 24c: Server-side filtering support
    TRADE_HISTORY: (
        page: number = 1,
        limit: number = 20,
        symbol?: string,
        side?: string,
        pnl_filter?: string
    ) => {
        const params = new URLSearchParams();
        params.append('page', page.toString());
        params.append('limit', limit.toString());
        if (symbol) params.append('symbol', symbol);
        if (side) params.append('side', side);
        if (pnl_filter) params.append('pnl_filter', pnl_filter);
        return `/trades/history?${params.toString()}`;
    },
    // SOTA Phase 24c: Bulk export endpoint
    TRADE_EXPORT: (
        symbol?: string,
        side?: string,
        pnl_filter?: string,
        page_from: number = 1,
        page_to?: number
    ) => {
        const params = new URLSearchParams();
        params.append('page_from', page_from.toString());
        if (page_to) params.append('page_to', page_to.toString());
        if (symbol) params.append('symbol', symbol);
        if (side) params.append('side', side);
        if (pnl_filter) params.append('pnl_filter', pnl_filter);
        return `/trades/export?${params.toString()}`;
    },
    EXECUTE_TRADE: (positionId: string) => `/trades/execute/${positionId}`,
    CLOSE_POSITION: (positionId: string) => `/trades/close/${positionId}`,
    CANCEL_PENDING_ORDER: (orderId: string) => `/trades/pending/${orderId}`,
    CANCEL_ALL_PENDING: '/trades/pending',
    RESET_TRADES: '/trades/reset',
    SIMULATE_TRADE: '/trades/simulate',

    // System (SOTA: Environment management)
    SYSTEM: {
        STATUS: '/system/status',
        CONFIG: '/system/config',
        MODE: (mode: string) => `/system/mode/${mode}`,
        EMERGENCY_STOP: '/system/emergency/stop',
        // SOTA: User Data Stream endpoints
        STREAM_START: '/system/stream/start',
        STREAM_STOP: '/system/stream/stop',
        STREAM_STATUS: '/system/stream/status'
    },

    // Performance
    PERFORMANCE: (days: number) => `/trades/performance?days=${days}`,
    EQUITY_CURVE: (days: number, resolution: string = 'trade') =>
        `/trades/equity-curve?days=${days}&resolution=${resolution}`,

    // Signals (SOTA Phase 25: Filtered signal history with analytics)
    SIGNAL_HISTORY: (
        page: number = 1,
        limit: number = 50,
        days: number = 30,
        symbol?: string,
        signal_type?: string,
        status?: string,
        min_confidence?: number
    ) => {
        const params = new URLSearchParams();
        params.append('page', page.toString());
        params.append('limit', limit.toString());
        params.append('days', days.toString());
        if (symbol) params.append('symbol', symbol);
        if (signal_type) params.append('signal_type', signal_type);
        if (status) params.append('status', status);
        if (min_confidence !== undefined) params.append('min_confidence', min_confidence.toString());
        return `/signals/history?${params.toString()}`;
    },
    SIGNAL_EXPORT: (
        days: number = 30,
        format: string = 'csv',
        symbol?: string,
        signal_type?: string,
        status?: string
    ) => {
        const params = new URLSearchParams();
        params.append('days', days.toString());
        params.append('format', format);
        if (symbol) params.append('symbol', symbol);
        if (signal_type) params.append('signal_type', signal_type);
        if (status) params.append('status', status);
        return `/signals/export?${params.toString()}`;
    },
    SIGNAL_PENDING: '/signals/pending',

    // System
    SYSTEM_STATUS: '/system/status',

    // Settings
    SETTINGS: '/settings',
    TOKENS: '/settings/tokens',  // SOTA Phase 26: Token watchlist
    TOKENS_VALIDATE: (symbol: string) => `/settings/tokens/validate?symbol=${symbol}`,
    TOKENS_SEARCH: (q: string = '', limit: number = 20) => `/settings/tokens/search?q=${q}&limit=${limit}`,
    TOKENS_ADD: '/settings/tokens/add',
    TOKENS_REMOVE: (symbol: string) => `/settings/tokens/${symbol}`,

    // Live Trading
    LIVE_TOGGLE: '/live/toggle',
    LIVE_STATUS: '/live/toggle-status',

    // SOTA: Shark Tank Dashboard
    SHARK_TANK_STATUS: '/live/shark-tank/status',

    // SOTA P2: Dynamic Pairlists
    TOP_TOKENS: (
        limit: number = 10,
        minVolumeUsd: number = 10_000_000,
        maxVolatilityPct: number = 50
    ) => `/market/top-tokens?limit=${limit}&min_volume_usd=${minVolumeUsd}&max_volatility_pct=${maxVolatilityPct}`,

    // SOTA P2: Blacklist Management
    BLACKLIST: '/market/blacklist',
    BLACKLIST_ADD: (symbol: string, reason: string = 'MANUAL') =>
        `/market/blacklist/${symbol}?reason=${reason}`,
    BLACKLIST_REMOVE: (symbol: string) => `/market/blacklist/${symbol}`,

    // SOTA: Top Volume Pairs (for weekly .env update)
    TOP_VOLUME_PAIRS: (limit: number = 10) => `/market/top-volume?limit=${limit}`,

    // SOTA (Jan 2026): Auto-select top N symbols and save to .env
    AUTO_SELECT_SYMBOLS: (n: number = 50) => `/config/symbols/auto-select?n=${n}`,

    // v6.3.0: Institutional Analytics (Binance Truth)
    ANALYTICS: {
        SUMMARY: (version?: string, days?: number) => {
            const params = new URLSearchParams();
            if (version) params.append('version', version);
            if (days) params.append('days', days.toString());
            const qs = params.toString();
            return `/analytics/summary${qs ? `?${qs}` : ''}`;
        },
        SESSIONS: (version?: string) =>
            `/analytics/sessions${version ? `?version=${version}` : ''}`,
        SYMBOLS: (version?: string) =>
            `/analytics/symbols${version ? `?version=${version}` : ''}`,
        DIRECTIONS: (version?: string) =>
            `/analytics/directions${version ? `?version=${version}` : ''}`,
        EQUITY: (version?: string, days?: number) => {
            const params = new URLSearchParams();
            if (version) params.append('version', version);
            if (days) params.append('days', days.toString());
            const qs = params.toString();
            return `/analytics/equity${qs ? `?${qs}` : ''}`;
        },
        SIGNIFICANCE: (version?: string) =>
            `/analytics/significance${version ? `?version=${version}` : ''}`,
        DEAD_ZONES: (version?: string) =>
            `/analytics/dead-zones${version ? `?version=${version}` : ''}`,
        TODAY: '/analytics/today',
        SNAPSHOTS: (days: number = 30) => `/analytics/snapshots?days=${days}`,
        RECONCILE: '/analytics/reconcile',
        DAILY_REPORT: '/analytics/daily-report',
    },
};

export default {
    API_BASE_URL,
    WS_BASE_URL,
    apiUrl,
    wsUrl,
    ENDPOINTS,
};
