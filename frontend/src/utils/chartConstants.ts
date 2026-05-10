/**
 * Chart Constants and Types
 *
 * Shared constants, colors, and TypeScript interfaces for chart components.
 * Extracted from CandleChart.tsx for better maintainability.
 */

import { Time } from 'lightweight-charts';

// Binance Color Scheme
export const CHART_COLORS = {
    background: '#0B0E11',
    cardBg: '#181A20',
    grid: '#333B47',
    textPrimary: '#EAECEF',
    textSecondary: '#929AA5',
    textTertiary: '#707A8A',
    buy: '#2EBD85',
    sell: '#F6465D',
    buyBg: 'rgba(46, 189, 133, 0.1)',
    sellBg: 'rgba(246, 70, 93, 0.1)',
    vwap: '#F0B90B',
    bollinger: '#2962FF',
    line: '#2B2F36',
} as const;

// Vietnam Timezone offset (UTC+7)
export const VN_TIMEZONE_OFFSET = 7 * 60 * 60; // 7 hours in seconds

// Timeframe types
export type Timeframe = '1m' | '15m' | '1h';

// OHLCV data structure
export interface ChartData {
    time: number;
    open: number;
    high: number;
    low: number;
    close: number;
    volume?: number;
    vwap?: number;
    bb_upper?: number;
    bb_lower?: number;
    bb_middle?: number;
}

// Signal data structure
export interface ChartSignal {
    type: 'BUY' | 'SELL';
    price: number;
    entry_price: number;
    stop_loss: number;
    take_profit: number;
    confidence: number;
    risk_reward_ratio: number;
    timestamp: string;
    reason?: string;
}

// Signal marker for chart display
export interface SignalMarker {
    time: Time;
    position: 'aboveBar' | 'belowBar';
    color: string;
    shape: 'arrowUp' | 'arrowDown';
    text: string;
    size: number;
    id: string;
    signal: ChartSignal;
}

// Position for price lines
export interface OpenPosition {
    id: string;
    symbol: string;
    side: 'LONG' | 'SHORT';
    entry_price: number;
    stop_loss: number;
    take_profit: number;
}
