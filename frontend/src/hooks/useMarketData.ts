import { useState, useEffect, useRef, useCallback } from 'react';
import { apiUrl, wsUrl, ENDPOINTS } from '../config/api';

interface MarketData {
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
    timestamp: string;
    time?: number;  // Unix timestamp for chart updates
    change_percent?: number;
    rsi?: number;
    vwap?: number;
    bollinger?: {
        upper_band: number;
        lower_band: number;
        middle_band: number;
    };
    [key: string]: any;
}

interface Signal {
    id?: string;  // Backend UUID
    type: 'BUY' | 'SELL';
    price: number;
    entry_price: number;
    stop_loss: number;
    take_profit: number;
    confidence: number;
    risk_reward_ratio: number;
    timestamp: string;  // From backend generated_at
    reason?: string;
    status?: 'generated' | 'pending' | 'executed' | 'expired' | 'rejected';
}

interface ReconnectState {
    isReconnecting: boolean;
    retryCount: number;
    nextRetryIn: number;
}

interface StateChange {
    from_state: string;
    to_state: string;
    reason?: string;
    timestamp: string;
    order_id?: string | null;
    position_id?: string | null;
    cooldown_remaining?: number;  // candles remaining in cooldown
}

interface UseMarketDataReturn {
    data: MarketData | null;      // 1m candle data (realtime)
    data15m: MarketData | null;   // 15m candle data (from backend aggregation)
    data1h: MarketData | null;    // 1h candle data (from backend aggregation)
    signal: Signal | null;
    stateChange: StateChange | null;
    isConnected: boolean;
    error: string | null;
    reconnectState: ReconnectState;
    reconnectNow: () => void;
}

/**
 * Calculate exponential backoff delay
 * Formula: delay = min(1000 * (2 ** retries), 30000)
 * Start: 1s, Cap: 30s
 */
const calculateBackoffDelay = (retryCount: number): number => {
    const baseDelay = 1000; // 1 second
    const maxDelay = 30000; // 30 seconds cap
    return Math.min(baseDelay * Math.pow(2, retryCount), maxDelay);
};

/**
 * Custom hook for WebSocket market data streaming
 *
 * **Feature: desktop-trading-dashboard**
 * **Validates: Requirements 1.1, 1.2, 1.3, 1.4**
 */
export const useMarketData = (symbol: string = 'btcusdt'): UseMarketDataReturn => {
    const [data, setData] = useState<MarketData | null>(null);
    const [data15m, setData15m] = useState<MarketData | null>(null);  // 15m candle
    const [data1h, setData1h] = useState<MarketData | null>(null);    // 1h candle
    const [signal, setSignal] = useState<Signal | null>(null);
    const [stateChange, setStateChange] = useState<StateChange | null>(null);
    const [isConnected, setIsConnected] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [reconnectState, setReconnectState] = useState<ReconnectState>({
        isReconnecting: false,
        retryCount: 0,
        nextRetryIn: 0,
    });

    const wsRef = useRef<WebSocket | null>(null);
    const reconnectTimeoutRef = useRef<number | undefined>(undefined);
    const countdownIntervalRef = useRef<number | undefined>(undefined);
    const isUnmountingRef = useRef(false);
    const retryCountRef = useRef(0);
    const lastUpdateTimeRef = useRef<string | null>(null);

    // SOTA FIX: Track last update time per timeframe for heartbeat monitoring
    const lastUpdatePerTimeframeRef = useRef<Record<string, number>>({
        '1m': Date.now(),
        '15m': Date.now(),
        '1h': Date.now()
    });

    // Heartbeat stale threshold (30 seconds)
    const HEARTBEAT_STALE_MS = 30000;

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
    }, []);

    // Fetch missing candles after reconnect (Data Gap Handling)
    const fetchMissingCandles = useCallback(async () => {
        if (!lastUpdateTimeRef.current) return;

        try {
            console.log('Fetching missing candles since:', lastUpdateTimeRef.current);
            // TODO: Implement full data gap filling
            // For now, just log the intent - can be expanded later
            const response = await fetch(apiUrl(ENDPOINTS.MARKET_HISTORY(symbol, 100)));
            if (response.ok) {
                const historyData = await response.json();
                console.log('Fetched history data:', historyData.length, 'candles');
            }
        } catch (err) {
            console.error('Failed to fetch missing candles:', err);
        }
    }, [symbol]);

    // SOTA FIX: Fallback REST fetch for specific timeframe when WS is quiet
    const fetchTimeframeCandle = useCallback(async (timeframe: string) => {
        try {
            console.log(`🔄 Heartbeat fallback: fetching ${timeframe} candle from REST API`);
            const response = await fetch(
                apiUrl(ENDPOINTS.WS_HISTORY('btcusdt', timeframe, 1))
            );
            if (response.ok) {
                const historyData = await response.json();
                if (historyData && historyData.length > 0) {
                    const latestCandle = historyData[historyData.length - 1];
                    const candleData: MarketData = {
                        open: latestCandle.open || 0,
                        high: latestCandle.high || 0,
                        low: latestCandle.low || 0,
                        close: latestCandle.close || 0,
                        volume: latestCandle.volume || 0,
                        timestamp: latestCandle.timestamp || new Date().toISOString(),
                        time: latestCandle.time || Math.floor(Date.now() / 1000),
                    };

                    // Update appropriate state based on timeframe
                    if (timeframe === '1m') {
                        setData(candleData);
                    } else if (timeframe === '15m') {
                        setData15m(candleData);
                    } else if (timeframe === '1h') {
                        setData1h(candleData);
                    }

                    // Update heartbeat timestamp
                    lastUpdatePerTimeframeRef.current[timeframe] = Date.now();
                    console.log(`✅ Heartbeat fallback: ${timeframe} candle updated`);
                }
            }
        } catch (err) {
            console.error(`Failed to fetch ${timeframe} candle:`, err);
        }
    }, []);

    // Schedule reconnect with exponential backoff
    const scheduleReconnect = useCallback(() => {
        if (isUnmountingRef.current) return;

        const delay = calculateBackoffDelay(retryCountRef.current);
        let remainingTime = Math.ceil(delay / 1000);

        console.log(`Scheduling reconnect in ${remainingTime}s (attempt ${retryCountRef.current + 1})`);

        setReconnectState({
            isReconnecting: true,
            retryCount: retryCountRef.current,
            nextRetryIn: remainingTime,
        });

        // Countdown timer
        countdownIntervalRef.current = window.setInterval(() => {
            remainingTime -= 1;
            if (remainingTime >= 0) {
                setReconnectState(prev => ({
                    ...prev,
                    nextRetryIn: remainingTime,
                }));
            }
        }, 1000);

        // Actual reconnect
        reconnectTimeoutRef.current = window.setTimeout(() => {
            clearTimers();
            retryCountRef.current += 1;
            connect();
        }, delay);
    }, [clearTimers]);

    const connect = useCallback(() => {
        if (isUnmountingRef.current) return;

        clearTimers();

        try {
            const wsAddress = wsUrl(ENDPOINTS.WS_STREAM(symbol));
            console.log(`Connecting to WebSocket: ${wsAddress}`);

            const ws = new WebSocket(wsAddress);
            wsRef.current = ws;

            ws.onopen = () => {
                console.log('WebSocket Connected');
                setIsConnected(true);
                setError(null);
                setReconnectState({
                    isReconnecting: false,
                    retryCount: 0,
                    nextRetryIn: 0,
                });
                retryCountRef.current = 0; // Reset retry count on success

                // Fetch missing candles if this is a reconnect
                if (lastUpdateTimeRef.current) {
                    fetchMissingCandles();
                }
            };

            ws.onmessage = (event) => {
                try {
                    const parsedData = JSON.parse(event.data);

                    if (parsedData.type === 'signal') {
                        try {
                            // Defensive: validate signal object exists
                            if (!parsedData.signal || typeof parsedData.signal !== 'object') {
                                console.warn('Invalid signal data received:', parsedData);
                                return;
                            }
                            // Normalize signal type to uppercase (backend sends lowercase)
                            const rawType = parsedData.signal.type || '';
                            const normalizedSignal = {
                                ...parsedData.signal,
                                type: typeof rawType === 'string' ? rawType.toUpperCase() : rawType
                            };
                            console.log('📡 Signal received and normalized:', normalizedSignal);
                            setSignal(normalizedSignal);
                        } catch (signalErr) {
                            console.error('Error processing signal:', signalErr, parsedData);
                        }
                    } else if (parsedData.type === 'candle' || parsedData.type === 'snapshot') {
                        const open = parsedData.open || parsedData.candle?.open || 0;
                        const close = parsedData.close || parsedData.candle?.close || 0;
                        let changePercent = parsedData.change_percent || parsedData.candle?.change_percent;

                        if (changePercent === undefined && open > 0) {
                            changePercent = ((close - open) / open) * 100;
                        }

                        const marketData: MarketData = {
                            open: open,
                            high: parsedData.high || parsedData.candle?.high || 0,
                            low: parsedData.low || parsedData.candle?.low || 0,
                            close: close,
                            volume: parsedData.volume || parsedData.candle?.volume || 0,
                            timestamp: parsedData.timestamp || parsedData.candle?.timestamp || new Date().toISOString(),
                            change_percent: changePercent,
                            vwap: parsedData.vwap || parsedData.data?.vwap,
                            bollinger: parsedData.bollinger || parsedData.data?.bollinger,
                            rsi: parsedData.rsi || parsedData.data?.rsi,
                            liquidity_zones: parsedData.liquidity_zones || parsedData.data?.liquidity_zones,
                            sfp: parsedData.sfp || parsedData.data?.sfp,
                        };
                        setData(marketData);
                        lastUpdateTimeRef.current = marketData.timestamp; // Track last update
                        lastUpdatePerTimeframeRef.current['1m'] = Date.now(); // Heartbeat update

                        if (parsedData.signal && typeof parsedData.signal === 'object') {
                            try {
                                // Normalize signal type to uppercase (backend sends lowercase)
                                const rawType = parsedData.signal.type || '';
                                const normalizedSignal = {
                                    ...parsedData.signal,
                                    type: typeof rawType === 'string' ? rawType.toUpperCase() : rawType
                                };
                                console.log('📡 Signal (in candle) received:', normalizedSignal);
                                setSignal(normalizedSignal);
                            } catch (signalErr) {
                                console.error('Error processing embedded signal:', signalErr);
                            }
                        }
                    } else if (parsedData.type === 'candle_15m') {
                        // 15-minute candle from backend aggregation
                        console.log('📊 15m candle received:', parsedData);
                        const candleData: MarketData = {
                            open: parsedData.open || 0,
                            high: parsedData.high || 0,
                            low: parsedData.low || 0,
                            close: parsedData.close || 0,
                            volume: parsedData.volume || 0,
                            timestamp: parsedData.timestamp || new Date().toISOString(),
                            time: parsedData.time || Math.floor(Date.now() / 1000),  // Unix timestamp
                        };
                        setData15m(candleData);
                        lastUpdatePerTimeframeRef.current['15m'] = Date.now(); // Heartbeat update
                    } else if (parsedData.type === 'candle_1h') {
                        // 1-hour candle from backend aggregation
                        console.log('📊 1h candle received:', parsedData);
                        const candleData: MarketData = {
                            open: parsedData.open || 0,
                            high: parsedData.high || 0,
                            low: parsedData.low || 0,
                            close: parsedData.close || 0,
                            volume: parsedData.volume || 0,
                            timestamp: parsedData.timestamp || new Date().toISOString(),
                            time: parsedData.time || Math.floor(Date.now() / 1000),  // Unix timestamp
                        };
                        setData1h(candleData);
                        lastUpdatePerTimeframeRef.current['1h'] = Date.now(); // Heartbeat update
                    } else if (parsedData.type === 'pong') {
                        // Ping response - ignore
                    } else if (parsedData.type === 'state_change') {
                        // State machine transition event
                        console.log('🔄 State change received:', parsedData);
                        setStateChange({
                            from_state: parsedData.from_state || parsedData.data?.from_state || '',
                            to_state: parsedData.to_state || parsedData.data?.to_state || '',
                            reason: parsedData.reason || parsedData.data?.reason,
                            timestamp: parsedData.timestamp || new Date().toISOString()
                        });
                    } else {
                        setData(parsedData);
                    }
                } catch (err) {
                    console.error('Failed to parse WebSocket message:', err);
                }
            };

            ws.onclose = () => {
                console.log('WebSocket Disconnected');
                setIsConnected(false);
                wsRef.current = null;

                // Auto-reconnect with exponential backoff
                if (!isUnmountingRef.current) {
                    scheduleReconnect();
                }
            };

            ws.onerror = (err) => {
                console.error('WebSocket Error:', err);
                setError('Connection error');
                ws.close();
            };

        } catch (err) {
            console.error('Connection failed:', err);
            setError('Failed to create connection');

            if (!isUnmountingRef.current) {
                scheduleReconnect();
            }
        }
    }, [symbol, clearTimers, scheduleReconnect, fetchMissingCandles]);

    // Manual reconnect function (Reconnect Now button)
    const reconnectNow = useCallback(() => {
        console.log('Manual reconnect triggered');
        clearTimers();
        retryCountRef.current = 0; // Reset retry count
        setReconnectState({
            isReconnecting: false,
            retryCount: 0,
            nextRetryIn: 0,
        });
        connect();
    }, [clearTimers, connect]);

    // Send ping to keep connection alive
    useEffect(() => {
        const pingInterval = setInterval(() => {
            if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
                wsRef.current.send(JSON.stringify({ type: 'ping' }));
            }
        }, 30000); // Ping every 30 seconds

        return () => clearInterval(pingInterval);
    }, []);

    // SOTA FIX: Heartbeat monitor - fallback REST fetch when WS is quiet
    useEffect(() => {
        const heartbeatInterval = setInterval(() => {
            const now = Date.now();
            const timeframes = ['1m', '15m', '1h'] as const;

            for (const tf of timeframes) {
                const lastUpdate = lastUpdatePerTimeframeRef.current[tf];
                const timeSinceUpdate = now - lastUpdate;

                // If no update for 30+ seconds and we're connected, fetch from REST
                if (timeSinceUpdate > HEARTBEAT_STALE_MS && isConnected) {
                    console.warn(`⚠️ Heartbeat: ${tf} stale (${Math.round(timeSinceUpdate / 1000)}s), triggering fallback fetch`);
                    fetchTimeframeCandle(tf);
                }
            }
        }, 10000); // Check every 10 seconds

        return () => clearInterval(heartbeatInterval);
    }, [isConnected, fetchTimeframeCandle]);

    useEffect(() => {
        isUnmountingRef.current = false;
        connect();

        return () => {
            isUnmountingRef.current = true;
            clearTimers();
            if (wsRef.current) {
                wsRef.current.close();
            }
        };
    }, [connect, clearTimers]);

    return { data, data15m, data1h, signal, stateChange, isConnected, error, reconnectState, reconnectNow };
};
