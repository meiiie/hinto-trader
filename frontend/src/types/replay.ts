export interface SharkTankEvent {
    type: 'REJECT' | 'RECYCLE' | 'ACCEPT' | 'INFO' | 'FILTER';
    symbol?: string;
    reason?: string;
    conf?: number;
    msg?: string;
    killed?: string;
    killed_conf?: number;
    new?: string;
    new_conf?: number;
    slots?: number;
}

export interface PendingOrder {
    symbol: string;
    side: 'LONG' | 'SHORT';
    target_price: number;
    confidence: number;
    status: 'PENDING' | 'LOCKED';
}

export interface ActivePosition {
    symbol: string;
    side: 'LONG' | 'SHORT';
    entry_price: number;
    sl: number;
    tp_hit: number;
}

export interface ReplaySnapshot {
    timestamp: string;
    balance: number;
    equity: number;
    active_positions: ActivePosition[];
    pending_orders: PendingOrder[];
    events: SharkTankEvent[];
}

export interface CandleData {
    time: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
}

export interface Indicators {
    bb_upper: (number | null)[];
    bb_lower: (number | null)[];
    vwap: (number | null)[];
    limit_sell: (number | null)[];
    limit_buy: (number | null)[];
}

export interface ReplayData {
    snapshots: ReplaySnapshot[];
    symbols: string[];
    interval: string;
    // SOTA (Jan 2026): Chart Data
    candles?: Record<string, CandleData[]>;
    indicators?: Record<string, Indicators>;
}
