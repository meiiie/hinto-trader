/**
 * SOTA Multi-Symbol Market Store
 *
 * Zustand store for managing real-time market data across multiple symbols.
 * Following Binance patterns for high-frequency trading terminals (Dec 2025).
 *
 * Features:
 * - Per-symbol data isolation (no cross-contamination)
 * - Instant symbol switching (cached data)
 * - Multi-timeframe support (1m, 15m, 1h)
 * - Signal management per symbol
 * - Connection state tracking
 */

import { create } from 'zustand';
import { subscribeWithSelector } from 'zustand/middleware';

// ============================================================================
// Types
// ============================================================================

export interface LiquidityZone {
    zone_low: number;
    zone_high: number;
    zone_type: string;
    strength: number;
    touch_count: number;
}

export interface LiquidityZonesResult {
    stop_loss_clusters: LiquidityZone[];
    take_profit_zones: LiquidityZone[];
    breakout_zones: LiquidityZone[];
}

export interface SFPResult {
    type: string; // 'bullish', 'bearish', 'none'
    swing_price: number;
    penetration_pct: number;
    rejection_strength: number;
    volume_ratio: number;
    confidence: number;
}

export interface MarketData {
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
    timestamp: string;
    time?: number;
    change_percent?: number;
    rsi?: number;
    vwap?: number;
    bollinger?: {
        upper_band: number;
        lower_band: number;
        middle_band: number;
    };
    liquidity_zones?: LiquidityZonesResult;
    sfp?: SFPResult;
    velocity?: {
        value: number;
        is_fomo: boolean;
        is_crash: boolean;
    };
}

export interface Signal {
    id?: string;
    type: 'BUY' | 'SELL';
    symbol?: string; // SOTA FIX: Signal carries its symbol
    price: number;
    entry_price: number;
    stop_loss: number;
    take_profit: number;
    confidence: number;
    risk_reward_ratio: number;
    timestamp: string;
    reason?: string;
    status?: 'generated' | 'pending' | 'executed' | 'expired' | 'rejected';
}

export interface StateChange {
    from_state: string;
    to_state: string;
    reason?: string;
    timestamp: string;
    order_id?: string | null;
    position_id?: string | null;
    cooldown_remaining?: number;
}

export interface SymbolData {
    data1m: MarketData | null;
    data15m: MarketData | null;
    data1h: MarketData | null;
    signal: Signal | null;
    stateChange: StateChange | null;
    lastUpdate: number;
    historicalLoaded: boolean;
}

export interface ConnectionState {
    isConnected: boolean;
    isReconnecting: boolean;
    retryCount: number;
    nextRetryIn: number;
    error: string | null;
}

// SOTA (Jan 2026): Position price data for multi-position realtime prices
export interface PositionPrice {
    price: number;
    timestamp: number;  // Unix timestamp in ms
}

// ============================================================================
// Store Interface
// ============================================================================

// SOTA: Market mode type for Spot/Futures toggle
export type MarketMode = 'spot' | 'futures';

interface MarketStore {
    // Active symbol
    activeSymbol: string;

    // SOTA: Market mode (Spot/Futures)
    marketMode: MarketMode;

    // Per-symbol data storage
    symbolData: Record<string, SymbolData>;

    // Connection state (shared across all symbols)
    connection: ConnectionState;

    // Available symbols (from backend)
    availableSymbols: string[];

    // SOTA (Jan 2026): Multi-position realtime prices
    // Position prices for non-active symbols (lightweight, from price_update messages)
    positionPrices: Record<string, PositionPrice>;
    // Currently subscribed symbols (for reference counting)
    subscribedSymbols: Set<string>;
    // Reference count per symbol (for subscription management)
    symbolRefCount: Record<string, number>;

    // Actions
    setActiveSymbol: (symbol: string) => void;
    setMarketMode: (mode: MarketMode) => void;
    clearSymbolData: (symbol: string) => void;
    updateCandle: (symbol: string, timeframe: '1m' | '15m' | '1h', data: MarketData) => void;
    updateSignal: (symbol: string, signal: Signal) => void;
    updateStateChange: (symbol: string, stateChange: StateChange) => void;
    setHistoricalLoaded: (symbol: string, loaded: boolean) => void;
    setConnection: (state: Partial<ConnectionState>) => void;
    setAvailableSymbols: (symbols: string[]) => void;

    // SOTA (Jan 2026): Multi-position realtime prices actions
    updatePositionPrice: (symbol: string, price: number, timestamp: number) => void;
    addSubscription: (symbol: string) => void;
    removeSubscription: (symbol: string) => void;
    incrementRefCount: (symbol: string) => void;
    decrementRefCount: (symbol: string) => boolean; // returns true if should unsubscribe
    getPositionPrice: (symbol: string) => PositionPrice | null;

    // SOTA FIX v2 (Jan 2026): Portfolio cache invalidation for SL_UPDATE events
    portfolioCacheVersion: number;
    invalidatePortfolioCache: () => void;

    // Selectors (computed)
    getActiveData: () => SymbolData | null;
    getDataForSymbol: (symbol: string) => SymbolData | null;
}

// ============================================================================
// Initial State
// ============================================================================

const DEFAULT_SYMBOL = 'btcusdt';

const createEmptySymbolData = (): SymbolData => ({
    data1m: null,
    data15m: null,
    data1h: null,
    signal: null,
    stateChange: null,
    lastUpdate: 0,
    historicalLoaded: false,
});

const initialConnectionState: ConnectionState = {
    isConnected: false,
    isReconnecting: false,
    retryCount: 0,
    nextRetryIn: 0,
    error: null,
};

// ============================================================================
// Store Implementation
// ============================================================================

export const useMarketStore = create<MarketStore>()(
    subscribeWithSelector((set, get) => ({
        // Initial state
        activeSymbol: DEFAULT_SYMBOL,
        marketMode: 'futures' as MarketMode,  // SOTA: Default to futures for accurate data
        symbolData: {
            [DEFAULT_SYMBOL]: createEmptySymbolData(),
        },
        connection: initialConnectionState,
        availableSymbols: ['btcusdt', 'ethusdt', 'solusdt', 'bnbusdt', 'taousdt', 'fetusdt', 'ondousdt'],

        // SOTA (Jan 2026): Multi-position realtime prices initial state
        positionPrices: {},
        subscribedSymbols: new Set<string>(),
        symbolRefCount: {},

        // SOTA FIX v2 (Jan 2026): Portfolio cache version for SL_UPDATE events
        portfolioCacheVersion: 0,

        // Set active symbol (for UI)
        setActiveSymbol: (symbol: string) => {
            const normalizedSymbol = symbol.toLowerCase();
            set((state) => {
                // Ensure symbol data slot exists
                if (!state.symbolData[normalizedSymbol]) {
                    return {
                        activeSymbol: normalizedSymbol,
                        symbolData: {
                            ...state.symbolData,
                            [normalizedSymbol]: createEmptySymbolData(),
                        },
                    };
                }
                return { activeSymbol: normalizedSymbol };
            });

            console.log(`📊 Active symbol changed to: ${normalizedSymbol}`);
        },

        // SOTA: Set market mode (Spot/Futures)
        setMarketMode: (mode: MarketMode) => {
            set({ marketMode: mode });
            console.log(`🌐 Market mode changed to: ${mode.toUpperCase()}`);
        },



        // Update candle data for a specific symbol and timeframe
        updateCandle: (symbol: string, timeframe: '1m' | '15m' | '1h', data: MarketData) => {
            const normalizedSymbol = symbol.toLowerCase();
            const timeframeKey = timeframe === '1m' ? 'data1m'
                : timeframe === '15m' ? 'data15m'
                    : 'data1h';

            // SOTA: Skip update if data hasn't changed (shallow equality on key primitives)
            // This prevents unnecessary React re-renders when WebSocket sends duplicate data
            const existing = get().symbolData[normalizedSymbol]?.[timeframeKey];
            if (existing && existing.close === data.close && existing.time === data.time) {
                return; // Data unchanged, skip Zustand set() to prevent re-renders
            }

            set((state) => {
                const existingData = state.symbolData[normalizedSymbol] || createEmptySymbolData();

                return {
                    symbolData: {
                        ...state.symbolData,
                        [normalizedSymbol]: {
                            ...existingData,
                            [timeframeKey]: data,
                            lastUpdate: Date.now(),
                        },
                    },
                };
            });
        },

        // Update signal for a specific symbol
        updateSignal: (symbol: string, signal: Signal) => {
            const normalizedSymbol = symbol.toLowerCase();

            set((state) => {
                const existingData = state.symbolData[normalizedSymbol] || createEmptySymbolData();

                return {
                    symbolData: {
                        ...state.symbolData,
                        [normalizedSymbol]: {
                            ...existingData,
                            signal,
                            lastUpdate: Date.now(),
                        },
                    },
                };
            });

            console.log(`🎯 Signal updated for ${normalizedSymbol}:`, signal.type);
        },

        // Update state change for a specific symbol
        updateStateChange: (symbol: string, stateChange: StateChange) => {
            const normalizedSymbol = symbol.toLowerCase();

            set((state) => {
                const existingData = state.symbolData[normalizedSymbol] || createEmptySymbolData();

                return {
                    symbolData: {
                        ...state.symbolData,
                        [normalizedSymbol]: {
                            ...existingData,
                            stateChange,
                        },
                    },
                };
            });
        },

        // Mark historical data as loaded for a symbol
        setHistoricalLoaded: (symbol: string, loaded: boolean) => {
            const normalizedSymbol = symbol.toLowerCase();

            set((state) => {
                const existingData = state.symbolData[normalizedSymbol] || createEmptySymbolData();

                return {
                    symbolData: {
                        ...state.symbolData,
                        [normalizedSymbol]: {
                            ...existingData,
                            historicalLoaded: loaded,
                        },
                    },
                };
            });
        },

        // Update connection state
        setConnection: (connectionUpdate: Partial<ConnectionState>) => {
            set((state) => ({
                connection: {
                    ...state.connection,
                    ...connectionUpdate,
                },
            }));
        },

        // Set available symbols from backend
        setAvailableSymbols: (symbols: string[]) => {
            set({ availableSymbols: symbols.map(s => s.toLowerCase()) });
        },

        // Clear data for a specific symbol
        clearSymbolData: (symbol: string) => {
            const normalizedSymbol = symbol.toLowerCase();

            set((state) => ({
                symbolData: {
                    ...state.symbolData,
                    [normalizedSymbol]: createEmptySymbolData(),
                },
            }));
        },

        // SOTA (Jan 2026): Multi-position realtime prices actions

        // Update position price from price_update message
        updatePositionPrice: (symbol: string, price: number, timestamp: number) => {
            const normalizedSymbol = symbol.toLowerCase();

            set((state) => ({
                positionPrices: {
                    ...state.positionPrices,
                    [normalizedSymbol]: { price, timestamp },
                },
            }));
        },

        // Add symbol to subscribed set
        addSubscription: (symbol: string) => {
            const normalizedSymbol = symbol.toLowerCase();

            set((state) => {
                const newSet = new Set(state.subscribedSymbols);
                newSet.add(normalizedSymbol);
                return { subscribedSymbols: newSet };
            });
        },

        // Remove symbol from subscribed set
        removeSubscription: (symbol: string) => {
            const normalizedSymbol = symbol.toLowerCase();

            set((state) => {
                const newSet = new Set(state.subscribedSymbols);
                newSet.delete(normalizedSymbol);

                // Also clean up position price
                const newPrices = { ...state.positionPrices };
                delete newPrices[normalizedSymbol];

                return {
                    subscribedSymbols: newSet,
                    positionPrices: newPrices,
                };
            });
        },

        // Increment reference count for a symbol
        incrementRefCount: (symbol: string) => {
            const normalizedSymbol = symbol.toLowerCase();

            set((state) => ({
                symbolRefCount: {
                    ...state.symbolRefCount,
                    [normalizedSymbol]: (state.symbolRefCount[normalizedSymbol] || 0) + 1,
                },
            }));
        },

        // Decrement reference count, returns true if should unsubscribe (count reaches 0)
        decrementRefCount: (symbol: string) => {
            const normalizedSymbol = symbol.toLowerCase();
            const state = get();
            const currentCount = state.symbolRefCount[normalizedSymbol] || 0;
            const newCount = Math.max(0, currentCount - 1);

            set((state) => {
                const newRefCount = { ...state.symbolRefCount };
                if (newCount === 0) {
                    delete newRefCount[normalizedSymbol];
                } else {
                    newRefCount[normalizedSymbol] = newCount;
                }
                return { symbolRefCount: newRefCount };
            });

            return newCount === 0;
        },

        // Get position price for a symbol
        getPositionPrice: (symbol: string) => {
            const state = get();
            return state.positionPrices[symbol.toLowerCase()] || null;
        },

        // SOTA FIX v2 (Jan 2026): Invalidate portfolio cache to trigger refetch
        // Called when SL_UPDATE event received via WebSocket
        invalidatePortfolioCache: () => {
            set((state) => ({
                portfolioCacheVersion: state.portfolioCacheVersion + 1
            }));
            console.log('🔄 Portfolio cache invalidated - will refetch on next render');
        },

        // Get data for the currently active symbol
        getActiveData: () => {
            const state = get();
            return state.symbolData[state.activeSymbol] || null;
        },

        // Get data for a specific symbol
        getDataForSymbol: (symbol: string) => {
            const state = get();
            return state.symbolData[symbol.toLowerCase()] || null;
        },
    }))
);

// ============================================================================
// Selector Hooks (Performance Optimized)
// ============================================================================

/**
 * Hook to get active symbol data with automatic re-render on change
 */
export const useActiveSymbolData = () => {
    return useMarketStore((state) => state.symbolData[state.activeSymbol] || null);
};

/**
 * Hook to get just the active symbol name
 */
export const useActiveSymbol = () => {
    return useMarketStore((state) => state.activeSymbol);
};

/**
 * Hook to get connection state
 */
export const useConnectionState = () => {
    return useMarketStore((state) => state.connection);
};

/**
 * Hook to get 1m data for active symbol
 */
export const useActiveData1m = () => {
    return useMarketStore((state) => {
        const symbolData = state.symbolData[state.activeSymbol];
        return symbolData?.data1m || null;
    });
};

/**
 * Hook to get 15m data for active symbol
 */
export const useActiveData15m = () => {
    return useMarketStore((state) => {
        const symbolData = state.symbolData[state.activeSymbol];
        return symbolData?.data15m || null;
    });
};

/**
 * Hook to get 1h data for active symbol
 */
export const useActiveData1h = () => {
    return useMarketStore((state) => {
        const symbolData = state.symbolData[state.activeSymbol];
        return symbolData?.data1h || null;
    });
};

/**
 * Hook to get signal for active symbol
 */
export const useActiveSignal = () => {
    return useMarketStore((state) => {
        const symbolData = state.symbolData[state.activeSymbol];
        return symbolData?.signal || null;
    });
};

/**
 * Hook to get state change for active symbol
 */
export const useActiveStateChange = () => {
    return useMarketStore((state) => {
        const symbolData = state.symbolData[state.activeSymbol];
        return symbolData?.stateChange || null;
    });
};

/**
 * SOTA (Jan 2026): Hook to get position price for a specific symbol
 * Used by Portfolio component for realtime PnL display
 */
export const usePositionPrice = (symbol: string) => {
    return useMarketStore((state) => state.positionPrices[symbol.toLowerCase()] || null);
};

/**
 * SOTA (Jan 2026): Hook to get all position prices
 */
export const usePositionPrices = () => {
    return useMarketStore((state) => state.positionPrices);
};

/**
 * SOTA (Jan 2026): Hook to get subscribed symbols
 */
export const useSubscribedSymbols = () => {
    return useMarketStore((state) => state.subscribedSymbols);
};

export default useMarketStore;
