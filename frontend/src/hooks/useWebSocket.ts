/**
 * useWebSocket - SOTA Shared WebSocket Connection Hook
 *
 * Single WebSocket connection that routes data to Zustand store.
 * All symbols share one connection (matches backend SharedBinanceClient).
 *
 * Features:
 * - Single connection for all symbols
 * - Client-side routing by symbol
 * - Exponential backoff reconnection
 * - Heartbeat monitoring
 * - Data gap handling
 * - SOTA (Jan 2026): Multi-position realtime prices with subscription recovery
 */

import { useEffect, useRef, useCallback } from 'react';
import { wsUrl, apiUrl, ENDPOINTS } from '../config/api';
import { useMarketStore, MarketData, Signal, StateChange } from '../stores/marketStore';

// ============================================================================
// Configuration
// ============================================================================

const PING_INTERVAL = 30000; // 30 seconds
const REST_FALLBACK_THRESHOLD = 10000; // 10 seconds - switch to REST if WS unavailable
const REST_POLL_INTERVAL = 5000; // 5 seconds - REST polling interval when WS down

/**
 * Calculate exponential backoff delay
 */
const calculateBackoffDelay = (retryCount: number): number => {
    const baseDelay = 1000;
    const maxDelay = 30000;
    return Math.min(baseDelay * Math.pow(2, retryCount), maxDelay);
};

// ============================================================================
// Hook Implementation
// ============================================================================

export const useWebSocket = () => {
    const wsRef = useRef<WebSocket | null>(null);
    const reconnectTimeoutRef = useRef<number | undefined>(undefined);
    const countdownIntervalRef = useRef<number | undefined>(undefined);
    const pingIntervalRef = useRef<number | undefined>(undefined);
    const heartbeatIntervalRef = useRef<number | undefined>(undefined);
    const restFallbackIntervalRef = useRef<number | undefined>(undefined);
    const disconnectedAtRef = useRef<number | null>(null);
    const isUnmountingRef = useRef(false);
    const retryCountRef = useRef(0);
    const lastUpdatePerSymbolRef = useRef<Record<string, number>>({});

    // SOTA FIX (Jan 2026): Use ref for activeSymbol to prevent stale closure
    // This ensures ws.onmessage always has the CURRENT activeSymbol value
    const activeSymbolRef = useRef<string>('btcusdt');

    // SOTA (Jan 2026): Track position symbols for subscription recovery
    const positionSymbolsRef = useRef<string[]>([]);

    // Get store actions
    const {
        updateCandle,
        updateSignal,
        updateStateChange,
        setConnection,
        activeSymbol,
        updatePositionPrice,
    } = useMarketStore();

    // SOTA FIX: Keep ref synced with activeSymbol from store
    // This ensures callback always has current value, preventing stale closure
    activeSymbolRef.current = activeSymbol;

    // Clear all timers
    const clearTimers = useCallback(() => {
        if (reconnectTimeoutRef.current) {
            clearTimeout(reconnectTimeoutRef.current);
            reconnectTimeoutRef.current = undefined;
        }
        if (countdownIntervalRef.current) {
            clearInterval(countdownIntervalRef.current);
            countdownIntervalRef.current = undefined;
        }
        if (pingIntervalRef.current) {
            clearInterval(pingIntervalRef.current);
            pingIntervalRef.current = undefined;
        }
        if (heartbeatIntervalRef.current) {
            clearInterval(heartbeatIntervalRef.current);
            heartbeatIntervalRef.current = undefined;
        }
        if (restFallbackIntervalRef.current) {
            clearInterval(restFallbackIntervalRef.current);
            restFallbackIntervalRef.current = undefined;
        }
    }, []);

    // SOTA (Jan 2026): REST fallback for position prices when WS unavailable
    const startRestFallback = useCallback(() => {
        if (restFallbackIntervalRef.current) return; // Already running

        console.log('🔄 Starting REST fallback for position prices...');
        setConnection({ error: 'Using REST fallback' });

        const fetchPrices = async () => {
            const symbols = positionSymbolsRef.current;
            if (symbols.length === 0) return;

            try {
                // Fetch prices from backend REST endpoint
                const response = await fetch(apiUrl(ENDPOINTS.PORTFOLIO));
                if (response.ok) {
                    const data = await response.json();
                    const positions = data.open_positions || [];

                    // Update position prices from REST data
                    positions.forEach((pos: { symbol: string; current_price: number }) => {
                        if (pos.symbol && pos.current_price) {
                            updatePositionPrice(
                                pos.symbol.toLowerCase(),
                                pos.current_price,
                                Date.now()
                            );
                        }
                    });
                }
            } catch (err) {
                console.error('REST fallback fetch failed:', err);
            }
        };

        // Fetch immediately, then poll
        fetchPrices();
        restFallbackIntervalRef.current = window.setInterval(fetchPrices, REST_POLL_INTERVAL);
    }, [setConnection, updatePositionPrice]);

    const stopRestFallback = useCallback(() => {
        if (restFallbackIntervalRef.current) {
            clearInterval(restFallbackIntervalRef.current);
            restFallbackIntervalRef.current = undefined;
            console.log('✅ Stopped REST fallback - WS reconnected');
        }
    }, []);

    // SOTA (Jan 2026): Fetch positions and recover subscriptions after reconnect
    const recoverSubscriptions = useCallback(async (ws: WebSocket) => {
        try {
            // Fetch current positions from REST
            const response = await fetch(apiUrl(ENDPOINTS.PORTFOLIO));
            if (!response.ok) return;

            const data = await response.json();
            const positions = data.open_positions || [];

            // Extract unique symbols
            const positionSymbols = [...new Set(
                positions.map((p: { symbol: string }) => p.symbol.toLowerCase())
            )] as string[];

            // Store for future reference
            positionSymbolsRef.current = positionSymbols;

            // Send subscription with recovered position symbols
            const activeSymbolLower = activeSymbolRef.current.toLowerCase();
            const priceOnlySymbols = positionSymbols.filter(s => s !== activeSymbolLower);

            if (ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({
                    type: 'subscribe',
                    symbols: [activeSymbolLower],
                    priceOnly: priceOnlySymbols
                }));
                console.log(`📊 Recovered subscriptions: full=[${activeSymbolLower}], priceOnly=[${priceOnlySymbols}]`);
            }
        } catch (err) {
            console.error('Failed to recover subscriptions:', err);
        }
    }, []);

    // Schedule reconnect with exponential backoff
    const scheduleReconnect = useCallback(() => {
        if (isUnmountingRef.current) return;

        const delay = calculateBackoffDelay(retryCountRef.current);
        let remainingTime = Math.ceil(delay / 1000);

        console.log(`Scheduling reconnect in ${remainingTime}s (attempt ${retryCountRef.current + 1})`);

        setConnection({
            isReconnecting: true,
            retryCount: retryCountRef.current,
            nextRetryIn: remainingTime,
        });

        // SOTA (Jan 2026): Track disconnection time for REST fallback
        if (!disconnectedAtRef.current) {
            disconnectedAtRef.current = Date.now();
        }

        // Check if we should start REST fallback
        const disconnectedDuration = Date.now() - disconnectedAtRef.current;
        if (disconnectedDuration >= REST_FALLBACK_THRESHOLD && !restFallbackIntervalRef.current) {
            startRestFallback();
        }

        // Countdown timer
        countdownIntervalRef.current = window.setInterval(() => {
            remainingTime -= 1;
            if (remainingTime >= 0) {
                setConnection({ nextRetryIn: remainingTime });
            }
        }, 1000);

        // Actual reconnect
        reconnectTimeoutRef.current = window.setTimeout(() => {
            if (countdownIntervalRef.current) {
                clearInterval(countdownIntervalRef.current);
                countdownIntervalRef.current = undefined;
            }
            retryCountRef.current += 1;
            connect();
        }, delay);
    }, [setConnection, startRestFallback]);

    // Main connect function - connects to activeSymbol's stream
    const connect = useCallback(() => {
        if (isUnmountingRef.current) return;

        clearTimers();

        try {
            // Connect to symbol-specific stream endpoint
            // SOTA: Backend broadcasts data for this symbol only
            const wsAddress = wsUrl(ENDPOINTS.WS_STREAM(activeSymbol));
            console.log(`🔌 Connecting to WebSocket for ${activeSymbol}: ${wsAddress}`);

            const ws = new WebSocket(wsAddress);
            wsRef.current = ws;

            ws.onopen = () => {
                console.log(`✅ WebSocket Connected for ${activeSymbol}`);
                setConnection({
                    isConnected: true,
                    isReconnecting: false,
                    retryCount: 0,
                    nextRetryIn: 0,
                    error: null,
                });
                retryCountRef.current = 0;

                // SOTA (Jan 2026): Clear disconnection tracking and stop REST fallback
                disconnectedAtRef.current = null;
                stopRestFallback();

                // SOTA (Jan 2026): FreqTrade-style - Send SUBSCRIBE message
                // This tells backend which symbol we want, enabling server-side filtering
                const currentSymbol = activeSymbolRef.current.toLowerCase();
                ws.send(JSON.stringify({
                    type: 'subscribe',
                    symbols: [currentSymbol]
                }));
                console.log(`📝 Sent SUBSCRIBE for: ${currentSymbol}`);

                // SOTA (Jan 2026): Recover position subscriptions after reconnect
                recoverSubscriptions(ws);

                // Start ping interval
                pingIntervalRef.current = window.setInterval(() => {
                    if (wsRef.current?.readyState === WebSocket.OPEN) {
                        wsRef.current.send(JSON.stringify({ type: 'ping' }));
                    }
                }, PING_INTERVAL);
            };

            ws.onmessage = (event) => {
                try {
                    const parsedData = JSON.parse(event.data);

                    // SOTA FIX (Jan 2026): Defense-in-depth symbol validation
                    // 1. Extract symbol from message - backend MUST include it
                    // 2. Reject data for wrong symbols (backend shouldn't send, but be safe)
                    const messageSymbol = parsedData.symbol?.toLowerCase();

                    // SOTA FIX: Use ref to get CURRENT activeSymbol (not stale closure)
                    const currentActiveSymbol = activeSymbolRef.current.toLowerCase();

                    // For candle events, REQUIRE symbol in message (no fallback)
                    if (parsedData.type === 'candle' || parsedData.type === 'snapshot' ||
                        parsedData.type === 'candle_15m' || parsedData.type === 'candle_1h') {

                        if (!messageSymbol) {
                            console.warn('⚠️ Rejected candle data without symbol field');
                            return;
                        }

                        // CRITICAL: Only process data for activeSymbol!
                        // This prevents price mixing even if backend sends wrong data
                        if (messageSymbol !== currentActiveSymbol) {
                            console.debug(`🛡️ Filtered: ${parsedData.type} for ${messageSymbol} (active=${currentActiveSymbol})`);
                            return;
                        }
                    }

                    // SOTA FIX (Jan 2026): Use ref for ALL events, not just candles!
                    // Previous bug: activeSymbol was stale closure for non-candle events
                    const symbol = messageSymbol || currentActiveSymbol;

                    // SOTA: ALSO filter SIGNAL events - signals for wrong symbol should be ignored!
                    if (parsedData.type === 'signal') {
                        if (messageSymbol && messageSymbol !== currentActiveSymbol) {
                            console.debug(`🛡️ Filtered signal for ${messageSymbol} (active=${currentActiveSymbol})`);
                            return;
                        }
                    }

                    // Update last update time for this symbol
                    lastUpdatePerSymbolRef.current[symbol] = Date.now();

                    // Route message by type
                    if (parsedData.type === 'signal') {
                        if (parsedData.signal && typeof parsedData.signal === 'object') {
                            const rawType = parsedData.signal.type || '';
                            const normalizedSignal: Signal = {
                                ...parsedData.signal,
                                type: typeof rawType === 'string' ? rawType.toUpperCase() as 'BUY' | 'SELL' : rawType,
                            };
                            updateSignal(symbol, normalizedSignal);
                        }
                    } else if (parsedData.type === 'candle' || parsedData.type === 'snapshot') {
                        const candleData = extractCandleData(parsedData);
                        updateCandle(symbol, '1m', candleData);

                        // Also process embedded signal if present
                        if (parsedData.signal && typeof parsedData.signal === 'object') {
                            const rawType = parsedData.signal.type || '';
                            const normalizedSignal: Signal = {
                                ...parsedData.signal,
                                type: typeof rawType === 'string' ? rawType.toUpperCase() as 'BUY' | 'SELL' : rawType,
                            };
                            updateSignal(symbol, normalizedSignal);
                        }
                    } else if (parsedData.type === 'candle_15m') {
                        const candleData = extractCandleData(parsedData);
                        updateCandle(symbol, '15m', candleData);
                    } else if (parsedData.type === 'candle_1h') {
                        const candleData = extractCandleData(parsedData);
                        updateCandle(symbol, '1h', candleData);
                    } else if (parsedData.type === 'state_change') {
                        const stateChange: StateChange = {
                            from_state: parsedData.from_state || parsedData.data?.from_state || '',
                            to_state: parsedData.to_state || parsedData.data?.to_state || '',
                            reason: parsedData.reason || parsedData.data?.reason,
                            timestamp: parsedData.timestamp || new Date().toISOString(),
                            order_id: parsedData.order_id,
                            position_id: parsedData.position_id,
                            cooldown_remaining: parsedData.cooldown_remaining,
                        };
                        updateStateChange(symbol, stateChange);
                    } else if (parsedData.type === 'price_update') {
                        // SOTA (Jan 2026): Multi-position realtime prices
                        // Handle lightweight price updates for portfolio positions
                        const priceSymbol = parsedData.symbol?.toLowerCase();
                        const price = parsedData.price;
                        const timestamp = parsedData.ts || Date.now();

                        if (priceSymbol && typeof price === 'number') {
                            updatePositionPrice(priceSymbol, price, timestamp);
                        }
                    } else if (parsedData.type === 'position_opened') {
                        // SOTA (Jan 2026): Position opened event - add to subscription
                        const positionData = parsedData.position;
                        if (positionData?.symbol) {
                            const posSymbol = positionData.symbol.toLowerCase();
                            console.log(`📈 Position opened: ${posSymbol}`);
                            // Add to priceOnly subscription
                            useMarketStore.getState().addSubscription(posSymbol);
                            useMarketStore.getState().incrementRefCount(posSymbol);
                        }
                    } else if (parsedData.type === 'position_closed') {
                        // SOTA (Jan 2026): Position closed event - remove from subscription
                        const positionData = parsedData.position;
                        if (positionData?.symbol) {
                            const posSymbol = positionData.symbol.toLowerCase();
                            console.log(`📉 Position closed: ${posSymbol}`);
                            // Decrement ref count and remove if zero
                            const shouldRemove = useMarketStore.getState().decrementRefCount(posSymbol);
                            if (shouldRemove) {
                                useMarketStore.getState().removeSubscription(posSymbol);
                            }
                        }
                    } else if (parsedData.type === 'position_updated') {
                        // SOTA (Jan 2026): Position updated event - just log for now
                        const positionData = parsedData.position;
                        if (positionData?.symbol) {
                            console.log(`📊 Position updated: ${positionData.symbol.toLowerCase()}`);
                        }
                    } else if (parsedData.type === 'sl_update' || parsedData.type === 'SL_UPDATE') {
                        // SOTA FIX v2 (Jan 2026): SL update event - trigger portfolio refresh
                        // This enables real-time UI update when SL changes (breakeven/trailing)
                        const slSymbol = parsedData.symbol?.toUpperCase();
                        const newSl = parsedData.new_sl;
                        const oldSl = parsedData.old_sl;
                        const reason = parsedData.reason;

                        console.log(`🛡️ SL_UPDATE: ${slSymbol} ${oldSl?.toFixed(4)} → ${newSl?.toFixed(4)} (${reason})`);

                        // Trigger portfolio refresh by invalidating cache
                        // The Portfolio component will refetch on next render
                        useMarketStore.getState().invalidatePortfolioCache?.();
                    } else if (parsedData.type === 'pong') {
                        // Ping response - ignore
                    }
                } catch (err) {
                    console.error('Failed to parse WebSocket message:', err);
                }
            };

            ws.onclose = () => {
                console.log('WebSocket Disconnected');
                setConnection({ isConnected: false });
                wsRef.current = null;

                // SOTA (Jan 2026): Track disconnection time
                if (!disconnectedAtRef.current) {
                    disconnectedAtRef.current = Date.now();
                }

                if (!isUnmountingRef.current) {
                    scheduleReconnect();
                }
            };

            ws.onerror = (err) => {
                console.error('WebSocket Error:', err);
                setConnection({ error: 'Connection error' });
                ws.close();
            };

        } catch (err) {
            console.error('Connection failed:', err);
            setConnection({ error: 'Failed to create connection' });

            if (!isUnmountingRef.current) {
                scheduleReconnect();
            }
        }
    }, [clearTimers, scheduleReconnect, setConnection, updateCandle, updateSignal, updateStateChange, activeSymbol, stopRestFallback, recoverSubscriptions]);

    // Manual reconnect function
    const reconnectNow = useCallback(() => {
        console.log('Manual reconnect triggered');
        clearTimers();
        retryCountRef.current = 0;
        setConnection({
            isReconnecting: false,
            retryCount: 0,
            nextRetryIn: 0,
        });
        connect();
    }, [clearTimers, connect, setConnection]);

    // SOTA (Jan 2026): Multi-position realtime prices
    // Function to update subscription with priceOnly symbols
    const updateSubscription = useCallback((fullSymbols: string[], priceOnlySymbols: string[]) => {
        // Store position symbols for recovery
        positionSymbolsRef.current = priceOnlySymbols;

        if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify({
                type: 'subscribe',
                symbols: fullSymbols.map(s => s.toLowerCase()),
                priceOnly: priceOnlySymbols.map(s => s.toLowerCase())
            }));
            console.log(`📝 Updated subscription: full=${fullSymbols}, priceOnly=${priceOnlySymbols}`);
        }
    }, []);

    // Track previous symbol to detect changes
    const prevSymbolRef = useRef(activeSymbol);

    // Effect: Connect on mount AND handle symbol changes
    useEffect(() => {
        isUnmountingRef.current = false;

        // If symbol changed while connected, send SUBSCRIBE instead of reconnecting
        // SOTA (Jan 2026): FreqTrade pattern - update subscription in place
        if (prevSymbolRef.current !== activeSymbol && wsRef.current?.readyState === WebSocket.OPEN) {
            console.log(`📊 Symbol changed: ${prevSymbolRef.current} → ${activeSymbol}, sending SUBSCRIBE...`);

            // Send SUBSCRIBE to update server-side subscription
            wsRef.current.send(JSON.stringify({
                type: 'subscribe',
                symbols: [activeSymbol.toLowerCase()]
            }));
            console.log(`📝 Sent SUBSCRIBE for: ${activeSymbol}`);

            prevSymbolRef.current = activeSymbol;
            return;  // Don't reconnect, subscription update is enough
        }

        prevSymbolRef.current = activeSymbol;

        // Only connect if not already connected
        if (!wsRef.current || wsRef.current.readyState === WebSocket.CLOSED) {
            connect();
        }

        return () => {
            isUnmountingRef.current = true;
            clearTimers();
            if (wsRef.current) {
                wsRef.current.close();
            }
        };
    }, [connect, clearTimers, activeSymbol]);  // SOTA: Handle symbol change

    return { reconnectNow, updateSubscription, wsRef };
};

// ============================================================================
// Helper Functions
// ============================================================================

function extractCandleData(parsedData: any): MarketData {
    const open = parsedData.open || parsedData.candle?.open || 0;
    const close = parsedData.close || parsedData.candle?.close || 0;
    let changePercent = parsedData.change_percent || parsedData.candle?.change_percent;

    if (changePercent === undefined && open > 0) {
        changePercent = ((close - open) / open) * 100;
    }

    return {
        open,
        high: parsedData.high || parsedData.candle?.high || 0,
        low: parsedData.low || parsedData.candle?.low || 0,
        close,
        volume: parsedData.volume || parsedData.candle?.volume || 0,
        timestamp: parsedData.timestamp || parsedData.candle?.timestamp || new Date().toISOString(),
        time: parsedData.time || Math.floor(Date.now() / 1000),
        change_percent: changePercent,
        vwap: parsedData.vwap || parsedData.data?.vwap,
        bollinger: parsedData.bollinger || parsedData.data?.bollinger,
        rsi: parsedData.rsi || parsedData.data?.rsi,
    };
}

export default useWebSocket;
