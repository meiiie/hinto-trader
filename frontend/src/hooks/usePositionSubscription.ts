/**
 * usePositionSubscription - SOTA Multi-Position Realtime Prices Hook
 *
 * Automatically subscribes to all position symbols for realtime price updates.
 * Uses priceOnly mode for non-active symbols to minimize bandwidth.
 *
 * Features:
 * - Extracts unique symbols from positions
 * - Sends subscribe message with priceOnly symbols
 * - Manages reference counting for cleanup
 * - Handles position changes (open/close)
 *
 * **Feature: multi-position-realtime-prices**
 * **Validates: Requirements 1.1, 1.2, 1.3**
 */

import { useEffect, useMemo, useRef, useCallback } from 'react';
import { useMarketStore } from '../stores/marketStore';

// Position interface (matches backend)
export interface Position {
    id: string;
    symbol: string;
    side: 'LONG' | 'SHORT';
    entry_price: number;
    current_price?: number;
    quantity: number;
    unrealized_pnl?: number;
    // ... other fields
}

interface UsePositionSubscriptionOptions {
    /** WebSocket reference from useWebSocket hook */
    wsRef: React.MutableRefObject<WebSocket | null>;
    /** Positions to subscribe to */
    positions: Position[];
}

/**
 * Hook to manage position symbol subscriptions.
 * Automatically subscribes to all position symbols when Portfolio mounts.
 */
export const usePositionSubscription = ({ wsRef, positions }: UsePositionSubscriptionOptions) => {
    const {
        activeSymbol,
        subscribedSymbols,
        addSubscription,
        removeSubscription,
        incrementRefCount,
        decrementRefCount,
    } = useMarketStore();

    // Track previous position symbols for change detection
    const prevPositionSymbolsRef = useRef<Set<string>>(new Set());

    // Extract unique symbols from positions (memoized)
    const positionSymbols = useMemo(() => {
        const symbols = new Set<string>();
        positions.forEach(p => {
            if (p.symbol) {
                symbols.add(p.symbol.toLowerCase());
            }
        });
        return symbols;
    }, [positions]);

    // Send subscription update to backend
    const sendSubscription = useCallback(() => {
        if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
            return;
        }

        const activeSymbolLower = activeSymbol.toLowerCase();

        // Full mode: active chart symbol
        const fullSymbols = [activeSymbolLower];

        // Price-only mode: position symbols that are NOT the active symbol
        const priceOnlySymbols = Array.from(positionSymbols).filter(
            s => s !== activeSymbolLower
        );

        // Only send if there are priceOnly symbols to subscribe to
        // (active symbol is always subscribed via useWebSocket)
        if (priceOnlySymbols.length > 0 || positionSymbols.size > 0) {
            wsRef.current.send(JSON.stringify({
                type: 'subscribe',
                symbols: fullSymbols,
                priceOnly: priceOnlySymbols
            }));

            console.log(`📊 Position subscription: full=[${fullSymbols}], priceOnly=[${priceOnlySymbols}]`);
        }
    }, [wsRef, activeSymbol, positionSymbols]);

    // Effect: Handle position changes
    useEffect(() => {
        const prevSymbols = prevPositionSymbolsRef.current;

        // Find new symbols (added positions)
        const newSymbols = new Set<string>();
        positionSymbols.forEach(s => {
            if (!prevSymbols.has(s)) {
                newSymbols.add(s);
            }
        });

        // Find removed symbols (closed positions)
        const removedSymbols = new Set<string>();
        prevSymbols.forEach(s => {
            if (!positionSymbols.has(s)) {
                removedSymbols.add(s);
            }
        });

        // Update ref counts for new symbols
        newSymbols.forEach(symbol => {
            incrementRefCount(symbol);
            addSubscription(symbol);
        });

        // Update ref counts for removed symbols
        removedSymbols.forEach(symbol => {
            const shouldUnsubscribe = decrementRefCount(symbol);
            if (shouldUnsubscribe) {
                removeSubscription(symbol);
            }
        });

        // Send subscription update if symbols changed
        if (newSymbols.size > 0 || removedSymbols.size > 0) {
            sendSubscription();
        }

        // Update previous symbols ref
        prevPositionSymbolsRef.current = new Set(positionSymbols);

    }, [positionSymbols, incrementRefCount, decrementRefCount, addSubscription, removeSubscription, sendSubscription]);

    // Effect: Re-subscribe when activeSymbol changes
    useEffect(() => {
        sendSubscription();
    }, [activeSymbol, sendSubscription]);

    // Effect: Subscribe on WebSocket connect/reconnect
    useEffect(() => {
        const ws = wsRef.current;
        if (!ws) return;

        const handleOpen = () => {
            // Re-subscribe after reconnect
            sendSubscription();
        };

        ws.addEventListener('open', handleOpen);

        // If already open, subscribe now
        if (ws.readyState === WebSocket.OPEN) {
            sendSubscription();
        }

        return () => {
            ws.removeEventListener('open', handleOpen);
        };
    }, [wsRef, sendSubscription]);

    // Cleanup on unmount
    useEffect(() => {
        return () => {
            // Decrement ref counts for all position symbols
            positionSymbols.forEach(symbol => {
                const shouldUnsubscribe = decrementRefCount(symbol);
                if (shouldUnsubscribe) {
                    removeSubscription(symbol);
                }
            });
        };
    }, []); // Empty deps - only run on unmount

    return {
        subscribedSymbols,
        positionSymbols: Array.from(positionSymbols),
    };
};

export default usePositionSubscription;
