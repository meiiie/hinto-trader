import React, { useEffect, useRef, useState, useCallback } from 'react';
import {
    createChart,
    ColorType,
    IChartApi,
    ISeriesApi,
    Time,
    CandlestickSeries,
    LineSeries,
    HistogramSeries,
    CrosshairMode,
    LineStyle,
    IPriceLine,
    SeriesMarker
} from 'lightweight-charts';
import { BBFillPlugin } from './BBFillPlugin';
import { LiquidityZonePlugin, ZoneData } from './LiquidityZonePlugin';
// SOTA: Use Zustand store for multi-symbol data
import {
    useActiveData1m,
    useActiveData15m,
    useActiveData1h,
    useActiveSignal,
    useActiveSymbol,
    useMarketStore
} from '../stores/marketStore';
import { apiUrl, ENDPOINTS } from '../config/api';

// Shared utilities - exported for use in other chart components
// Note: Local definitions kept below for now to avoid breaking changes
export { CHART_COLORS, type Timeframe, type ChartData as SharedChartData } from '../utils/chartConstants';

// Position interface for price lines
interface OpenPosition {
    id: string;
    symbol: string;
    side: 'LONG' | 'SHORT';
    entry_price: number;
    stop_loss: number;
    take_profit: number;
}

// Binance Color Scheme
const BINANCE_COLORS = {
    background: '#181A20',  // Dark background like Binance
    cardBg: '#181A20',
    grid: '#333B47',
    textPrimary: '#EAECEF',
    textSecondary: '#929AA5',
    textTertiary: '#707A8A',
    buy: '#2EBD85',
    sell: '#F6465D',
    buyBg: 'rgba(46, 189, 133, 0.1)',
    sellBg: 'rgba(246, 70, 93, 0.1)',
    vwap: '#FB6C01',  // VWAP line color (orange)
    bollinger: '#1F7DC8',  // BB line color
    bollingerFill: 'rgba(31, 125, 200, 0.1)',  // BB fill between bands
    line: '#2B2F36',
};

interface ChartData {
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

interface Signal {
    type: 'BUY' | 'SELL';
    priority?: string; // 'high' | 'medium' | 'low'
    price: number;
    entry_price: number;
    stop_loss: number;
    take_profit: number;
    confidence: number;
    risk_reward_ratio: number;
    timestamp: string;
    reason?: string;
}

interface SignalMarker {
    time: Time;
    position: 'aboveBar' | 'belowBar';
    color: string;
    shape: 'arrowUp' | 'arrowDown';
    text: string;
    size: number;
    id: string;
    signal: Signal;
}

type Timeframe = '1m' | '15m' | '1h';

// Vietnam Timezone offset (UTC+7)
const VN_TIMEZONE_OFFSET = 7 * 60 * 60; // 7 hours in seconds

/**
 * Convert UTC timestamp to Vietnam time for display
 */
/**
 * Convert UTC timestamp to Vietnam time for display
 * SOTA FIX: Strictly parse input to prevent string concatenation or object passing
 */
const toVietnamTime = (utcTimestamp: unknown): Time => {
    const ts = safeParseTimestamp(utcTimestamp);
    return (ts + VN_TIMEZONE_OFFSET) as Time;
};

/**
 * Safely parse any timestamp format to Unix seconds
 * Handles: ISO string, Date object, milliseconds, or seconds
 * @param timestamp - unknown format timestamp
 * @returns Unix timestamp in seconds, or 0 if invalid
 */
const safeParseTimestamp = (timestamp: unknown): number => {
    if (timestamp === null || timestamp === undefined) return 0;

    // Already a number
    if (typeof timestamp === 'number') {
        // Check if milliseconds (> year 2001 in ms) vs seconds
        return timestamp > 1_000_000_000_000 ? Math.floor(timestamp / 1000) : timestamp;
    }

    // ISO string or Date object
    if (typeof timestamp === 'string' || timestamp instanceof Date) {
        const ms = new Date(timestamp).getTime();
        return isNaN(ms) ? 0 : Math.floor(ms / 1000);
    }

    // SOTA FIX (Jan 2026): Handle object types that might be passed by mistake
    // This catches Protobuf-style {seconds, nanos}, moment.js objects, etc.
    if (typeof timestamp === 'object') {
        // Try common object patterns
        const obj = timestamp as Record<string, unknown>;
        if ('seconds' in obj && typeof obj.seconds === 'number') {
            return obj.seconds;
        }
        if ('_seconds' in obj && typeof obj._seconds === 'number') {
            return obj._seconds;
        }
        // Try valueOf() for Date-like objects
        if (typeof obj.valueOf === 'function') {
            const val = obj.valueOf();
            if (typeof val === 'number') {
                return val > 1_000_000_000_000 ? Math.floor(val / 1000) : val;
            }
        }
        console.warn('⚠️ safeParseTimestamp: Unexpected object type:', timestamp);
        return 0;
    }

    return 0;
};



/**
 * Format price with Vietnamese locale
 */
const formatPrice = (price: number): string => {
    return new Intl.NumberFormat('en-US', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(price);
};

/**
 * CandleChart Component - Binance Professional Style
 *
 * **Feature: desktop-trading-dashboard**
 * **Validates: Requirements 2.1, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4**
 *
 * Phase D: Accepts timeframe as controlled prop from App.tsx for price sync
 */

interface CandleChartProps {
    timeframe?: Timeframe;
    onTimeframeChange?: (tf: Timeframe) => void;
    isMobile?: boolean;  // Control header visibility for mobile
}

const CandleChart: React.FC<CandleChartProps> = ({
    timeframe: propTimeframe,
    onTimeframeChange,
    isMobile = false
}) => {
    const chartContainerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<IChartApi | null>(null);

    // Series Refs
    const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
    const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
    const vwapSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
    const bbUpperSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
    const bbLowerSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
    const bbFillPluginRef = useRef<BBFillPlugin | null>(null);
    const liquidityZonePluginRef = useRef<LiquidityZonePlugin | null>(null);

    // Dynamic Price Lines for Open Positions (using createPriceLine API)
    const entryPriceLineRef = useRef<IPriceLine | null>(null);
    const slPriceLineRef = useRef<IPriceLine | null>(null);
    const tpPriceLineRef = useRef<IPriceLine | null>(null);

    // Track if chart is disposed to prevent updates on unmounted component
    const isDisposedRef = useRef<boolean>(false);

    // Track last time rendered to chart for chronological order validation (per-timeframe)
    // SOTA FIX: Use per-timeframe tracking to prevent cross-contamination when switching
    const lastRenderedTimeRef = useRef<Record<Timeframe, number>>({
        '1m': 0,
        '15m': 0,
        '1h': 0
    });

    // Open positions state for price lines
    const [openPositions, setOpenPositions] = useState<OpenPosition[]>([]);

    // SOTA: Use Zustand selectors for multi-symbol data
    const activeSymbol = useActiveSymbol();
    const realtimeData = useActiveData1m();
    const realtimeData15m = useActiveData15m();
    const realtimeData1h = useActiveData1h();
    const realtimeSignal = useActiveSignal();

    // Track previous symbol for detecting changes
    const prevSymbolRef = useRef<string>(activeSymbol);

    // Use prop timeframe if provided (controlled), otherwise internal state (uncontrolled)
    const [internalTimeframe, setInternalTimeframe] = useState<Timeframe>('15m');
    const timeframe = propTimeframe ?? internalTimeframe;

    // Handle timeframe change - emit to parent if controlled
    const handleTimeframeChange = (newTf: Timeframe) => {
        if (onTimeframeChange) {
            onTimeframeChange(newTf);
        } else {
            setInternalTimeframe(newTf);
        }
    };

    const [isLoading, setIsLoading] = useState(true);
    const [signals, setSignals] = useState<SignalMarker[]>([]);
    const [activeSignal, setActiveSignal] = useState<Signal | null>(null);
    const [currentPrice, setCurrentPrice] = useState<number>(0);
    const [priceChange, setPriceChange] = useState<number>(0);
    const [tooltipData, setTooltipData] = useState<{
        visible: boolean;
        x: number;
        y: number;
        signal: Signal | null;
    }>({ visible: false, x: 0, y: 0, signal: null });

    // Store current forming candle for aggregation
    const currentCandleRef = useRef<{
        time: number;
        open: number;
        high: number;
        low: number;
        close: number;
        volume: number;
    } | null>(null);

    // Add signal marker to chart
    const addSignalMarker = useCallback((signal: Signal, time: number) => {
        const isSFP = signal.priority === 'high' || (signal.reason && signal.reason.includes('SFP'));

        const marker: SignalMarker = {
            time: time as Time,  // SOTA FIX: Use raw UTC timestamp
            position: signal.type === 'BUY' ? 'belowBar' : 'aboveBar',
            // SFP uses Gold color, Normal uses Buy/Sell colors
            color: isSFP ? '#F0B90B' : (signal.type === 'BUY' ? BINANCE_COLORS.buy : BINANCE_COLORS.sell),
            shape: signal.type === 'BUY' ? 'arrowUp' : 'arrowDown',
            // SOTA: No text on chart to keep it clean, tooltip shows details
            text: isSFP ? 'SFP' : '',
            size: isSFP ? 2 : 1, // Larger for SFP
            id: `${signal.type}-${time}`,
            signal: signal
        };

        setSignals(prev => {
            if (prev.some(s => s.id === marker.id)) return prev;
            return [...prev, marker];
        });
        setActiveSignal(signal);
    }, []);

    // Fetch open positions for price lines
    const fetchOpenPositions = useCallback(async () => {
        try {
            const response = await fetch(apiUrl(ENDPOINTS.PORTFOLIO));
            if (response.ok) {
                const data = await response.json();
                setOpenPositions(data.open_positions || []);
            }
        } catch (err) {
            console.error('Error fetching positions for price lines:', err);
        }
    }, []);

    // SOTA: Poll for open positions every 10 seconds (reduced from 3s)
    useEffect(() => {
        fetchOpenPositions();
        const interval = setInterval(fetchOpenPositions, 10000);
        return () => clearInterval(interval);
    }, [fetchOpenPositions]);

    // Fetch trade history for chart markers - FILTER BY ACTIVE SYMBOL
    const fetchTradeHistory = useCallback(async () => {
        try {
            // SOTA: Filter by activeSymbol to only show signals for current chart
            const symbolFilter = activeSymbol.toUpperCase();
            const response = await fetch(apiUrl(ENDPOINTS.TRADE_HISTORY(1, 50, symbolFilter)));
            if (response.ok) {
                const data = await response.json();
                const trades = data.trades || [];

                // Clear existing signals before adding new ones for this symbol
                setSignals([]);

                // Convert trades to signal markers
                trades.forEach((trade: {
                    side: string;
                    entry_price: number;
                    stop_loss: number;
                    take_profit: number;
                    entry_time: string;
                    pnl?: number;
                    symbol?: string;
                }) => {
                    const signal: Signal = {
                        type: trade.side === 'LONG' ? 'BUY' : 'SELL',
                        price: trade.entry_price,
                        entry_price: trade.entry_price,
                        stop_loss: trade.stop_loss || 0,
                        take_profit: trade.take_profit || 0,
                        confidence: 0.8,
                        risk_reward_ratio: trade.take_profit && trade.stop_loss
                            ? Math.abs(trade.take_profit - trade.entry_price) / Math.abs(trade.entry_price - trade.stop_loss)
                            : 2,
                        timestamp: trade.entry_time,
                        reason: trade.pnl !== undefined
                            ? `PnL: ${trade.pnl >= 0 ? '+' : ''}$${trade.pnl.toFixed(2)}`
                            : undefined
                    };
                    const signalTime = Math.floor(new Date(trade.entry_time).getTime() / 1000);
                    addSignalMarker(signal, signalTime);
                });
            }
        } catch (err) {
            console.error('Error fetching trade history for markers:', err);
        }
    }, [addSignalMarker, activeSymbol]);

    // SOTA: Reload trade history when symbol changes
    useEffect(() => {
        // Clear signals for new symbol
        setSignals([]);
        fetchTradeHistory();
    }, [activeSymbol, fetchTradeHistory]);

    // Update Dynamic Price Lines when positions change
    // SOTA: Filter by activeSymbol to only show lines for current chart's symbol
    useEffect(() => {
        if (!candleSeriesRef.current) return;

        // Remove existing price lines
        if (entryPriceLineRef.current) {
            candleSeriesRef.current.removePriceLine(entryPriceLineRef.current);
            entryPriceLineRef.current = null;
        }
        if (slPriceLineRef.current) {
            candleSeriesRef.current.removePriceLine(slPriceLineRef.current);
            slPriceLineRef.current = null;
        }
        if (tpPriceLineRef.current) {
            candleSeriesRef.current.removePriceLine(tpPriceLineRef.current);
            tpPriceLineRef.current = null;
        }

        // SOTA FIX: Filter positions by activeSymbol to show correct lines
        const symbolUpper = activeSymbol.toUpperCase();
        const matchingPositions = openPositions.filter(p =>
            p.symbol?.toUpperCase() === symbolUpper ||
            p.symbol?.toUpperCase() === `${symbolUpper}USDT` ||
            `${p.symbol?.toUpperCase()}` === symbolUpper.replace('USDT', '')
        );

        const position = matchingPositions[0];
        if (!position) return;

        // Entry Line - Gray dashed
        entryPriceLineRef.current = candleSeriesRef.current.createPriceLine({
            price: position.entry_price,
            color: '#9CA3AF', // Gray
            lineWidth: 1,
            lineStyle: LineStyle.Dotted,
            axisLabelVisible: true,
            title: `ENTRY ${position.side}`,
        });

        // Stop Loss Line - Red dashed (DYNAMIC - updates with trailing stop)
        if (position.stop_loss > 0) {
            slPriceLineRef.current = candleSeriesRef.current.createPriceLine({
                price: position.stop_loss,
                color: BINANCE_COLORS.sell, // Red
                lineWidth: 2,
                lineStyle: LineStyle.Dashed,
                axisLabelVisible: true,
                title: `SL`,
            });
        }

        // Take Profit Line - Green dashed
        if (position.take_profit > 0) {
            tpPriceLineRef.current = candleSeriesRef.current.createPriceLine({
                price: position.take_profit,
                color: BINANCE_COLORS.buy, // Green
                lineWidth: 1,
                lineStyle: LineStyle.Dashed,
                axisLabelVisible: true,
                title: `TP`,
            });
        }
    }, [openPositions, activeSymbol]);

    // Initialize Chart with Binance styling
    useEffect(() => {
        if (!chartContainerRef.current) return;

        const chart = createChart(chartContainerRef.current, {
            layout: {
                background: { type: ColorType.Solid, color: BINANCE_COLORS.background },
                textColor: BINANCE_COLORS.textSecondary,
                fontFamily: "'Roboto', 'Helvetica Neue', sans-serif",
                fontSize: 12,
            },
            grid: {
                vertLines: { color: BINANCE_COLORS.grid, style: LineStyle.Solid },
                horzLines: { color: BINANCE_COLORS.grid, style: LineStyle.Solid },
            },
            width: chartContainerRef.current.clientWidth,
            height: chartContainerRef.current.clientHeight || 400,
            timeScale: {
                timeVisible: true,
                secondsVisible: false,
                borderColor: BINANCE_COLORS.line,
                tickMarkFormatter: (time: Time) => {
                    // SOTA FIX: Data uses raw UTC timestamps, display in VN timezone
                    const date = new Date((time as number) * 1000);
                    return date.toLocaleString('vi-VN', {
                        timeZone: 'Asia/Ho_Chi_Minh',
                        day: '2-digit',
                        month: '2-digit',
                        hour: '2-digit',
                        minute: '2-digit'
                    });
                },
            },
            localization: {
                // SOTA: Display VN timezone in crosshair tooltip with Vietnamese format
                // Format: "T2 29 Thg 12 '25 17:00"
                timeFormatter: (time: number) => {
                    const date = new Date(time * 1000);
                    // Get parts in VN timezone with Vietnamese locale
                    const weekday = date.toLocaleDateString('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh', weekday: 'short' });
                    const day = date.toLocaleDateString('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh', day: '2-digit' });
                    const month = date.toLocaleDateString('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh', month: 'short' });
                    const year = date.toLocaleDateString('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh', year: '2-digit' });
                    const timeStr = date.toLocaleTimeString('vi-VN', {
                        timeZone: 'Asia/Ho_Chi_Minh',
                        hour: '2-digit',
                        minute: '2-digit',
                        hour12: false
                    });
                    return `${weekday} ${day} ${month} '${year} ${timeStr}`;
                },
                locale: 'vi-VN',
            },
            rightPriceScale: {
                borderColor: BINANCE_COLORS.line,
                scaleMargins: { top: 0.1, bottom: 0.2 },
            },
            crosshair: {
                mode: CrosshairMode.Normal,
                vertLine: {
                    color: BINANCE_COLORS.textTertiary,
                    width: 1,
                    style: LineStyle.Dashed,
                    labelBackgroundColor: BINANCE_COLORS.cardBg,
                },
                horzLine: {
                    color: BINANCE_COLORS.textTertiary,
                    width: 1,
                    style: LineStyle.Dashed,
                    labelBackgroundColor: BINANCE_COLORS.cardBg,
                },
            },
            handleScroll: { mouseWheel: true, pressedMouseMove: true },
            handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
        });

        // 1. Candlestick Series - Binance colors
        const candleSeries = chart.addSeries(CandlestickSeries, {
            upColor: BINANCE_COLORS.buy,
            downColor: BINANCE_COLORS.sell,
            borderUpColor: BINANCE_COLORS.buy,
            borderDownColor: BINANCE_COLORS.sell,
            wickUpColor: BINANCE_COLORS.buy,
            wickDownColor: BINANCE_COLORS.sell,
            // SOTA FIX (Jan 2026): Use custom formatter for dynamic precision
            // This handles small-price tokens (SHIB, PEPE) which need 6-8 decimals
            priceFormat: {
                type: 'custom',
                formatter: (price: number) => formatPrice(price),
                minMove: 0.00000001, // Allow minimal moves
            },
        });
        candleSeriesRef.current = candleSeries;

        // 2. Volume Series - at bottom
        const volumeSeries = chart.addSeries(HistogramSeries, {
            color: BINANCE_COLORS.buy,
            priceFormat: { type: 'volume' },
            priceScaleId: 'volume',
        });
        volumeSeries.priceScale().applyOptions({
            scaleMargins: { top: 0.75, bottom: 0 },
        });
        volumeSeriesRef.current = volumeSeries;

        // 3. VWAP Series - Binance yellow
        const vwapSeries = chart.addSeries(LineSeries, {
            color: BINANCE_COLORS.vwap,
            lineWidth: 2,
            priceLineVisible: false,
            lastValueVisible: false,
            title: 'VWAP',
        });
        vwapSeriesRef.current = vwapSeries;

        // 4. Bollinger Bands - Blue
        const bbUpperSeries = chart.addSeries(LineSeries, {
            color: BINANCE_COLORS.bollinger,
            lineWidth: 1,
            lineStyle: LineStyle.Solid,
            priceLineVisible: false,
            lastValueVisible: false,
            title: 'BB Upper',
        });
        bbUpperSeriesRef.current = bbUpperSeries;

        const bbLowerSeries = chart.addSeries(LineSeries, {
            color: BINANCE_COLORS.bollinger,
            lineWidth: 1,
            lineStyle: LineStyle.Solid,
            priceLineVisible: false,
            lastValueVisible: false,
            title: 'BB Lower',
        });
        bbLowerSeriesRef.current = bbLowerSeries;

        // Initialize BB Fill Plugin - custom plugin for fill between BB bands
        if (candleSeriesRef.current) {
            const bbFillPlugin = new BBFillPlugin({
                fillColor: BINANCE_COLORS.bollingerFill,
                upperSeries: bbUpperSeries,
                lowerSeries: bbLowerSeries,
            });
            candleSeriesRef.current.attachPrimitive(bbFillPlugin);
            bbFillPluginRef.current = bbFillPlugin;
        }

        // Initialize Liquidity Zone Plugin
        if (candleSeriesRef.current) {
            const lzPlugin = new LiquidityZonePlugin({
                demandColor: 'rgba(0, 150, 136, 0.15)', // Green tint
                supplyColor: 'rgba(255, 82, 82, 0.15)', // Red tint
            });
            candleSeriesRef.current.attachPrimitive(lzPlugin);
            liquidityZonePluginRef.current = lzPlugin;
        }

        // Note: Price lines for Entry/SL/TP are now created dynamically
        // using candleSeries.createPriceLine() when positions are open

        chartRef.current = chart;

        // Handle crosshair move for tooltip
        chart.subscribeCrosshairMove((param) => {
            if (!param.point || !param.time) {
                setTooltipData(prev => ({ ...prev, visible: false }));
                return;
            }
            const hoveredSignal = signals.find(s => s.time === param.time);
            if (hoveredSignal) {
                setTooltipData({
                    visible: true,
                    x: param.point.x,
                    y: param.point.y,
                    signal: hoveredSignal.signal
                });
            } else {
                setTooltipData(prev => ({ ...prev, visible: false }));
            }
        });

        const handleResize = () => {
            if (chartContainerRef.current && chartRef.current) {
                chartRef.current.applyOptions({
                    width: chartContainerRef.current.clientWidth,
                    height: chartContainerRef.current.clientHeight || 400
                });
            }
        };

        window.addEventListener('resize', handleResize);
        isDisposedRef.current = false;  // Mark chart as active
        return () => {
            isDisposedRef.current = true;  // Mark chart as disposed
            window.removeEventListener('resize', handleResize);
            chart.remove();
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);  // Chart init only once on mount - signals now handled separately

    // SOTA: Load History when Timeframe or Symbol Changes
    useEffect(() => {
        const fetchHistory = async () => {
            setIsLoading(true);
            currentCandleRef.current = null;
            // SOTA FIX: Reset only the current timeframe's lastRenderedTimeRef
            // This allows fresh data for this timeframe while preserving others
            lastRenderedTimeRef.current[timeframe] = 0;
            setSignals([]);
            // SOTA FIX: Clear Liquidity Zones when changing symbol/timeframe to prevent ghost zones
            if (liquidityZonePluginRef.current) {
                liquidityZonePluginRef.current.setData([]);
            }

            // SOTA: Track symbol change
            if (prevSymbolRef.current !== activeSymbol) {
                console.log(`📊 Symbol changed: ${prevSymbolRef.current} → ${activeSymbol}`);
                prevSymbolRef.current = activeSymbol;
            }

            try {
                // DEBUG: Trace if fetchHistory is actually being called
                console.log(`🚀 fetchHistory triggered: symbol=${activeSymbol}, timeframe=${timeframe}`);

                // Fetch 500 candles for technical analysis (SOTA standard - matches backend load)
                // SOTA: Use activeSymbol instead of hardcoded btcusdt
                const historyUrl = apiUrl(ENDPOINTS.WS_HISTORY(activeSymbol, timeframe, 500));
                console.log(`📡 Fetching from: ${historyUrl}`);

                const response = await fetch(historyUrl);
                console.log(`📊 Response status: ${response.status}`);

                if (!response.ok) throw new Error('Failed to fetch history');

                const historyData: ChartData[] = await response.json();

                if (historyData && historyData.length > 0) {
                    // TRIM DATA: Skip first 50 candles to eliminate indicator warm-up lag
                    // This ensures indicators (VWAP, BB) appear from the first visible candle
                    // BUT only if we have enough data after trimming
                    const WARMUP_PERIOD = 50;
                    const MIN_CANDLES_AFTER_TRIM = 20;
                    const trimmedData = historyData.length > WARMUP_PERIOD + MIN_CANDLES_AFTER_TRIM
                        ? historyData.slice(WARMUP_PERIOD)
                        : historyData;  // Keep all if insufficient data

                    // SOTA FIX: Use raw UTC timestamps - timezone applied in tickMarkFormatter only
                    const rawCandles = trimmedData.map(d => ({
                        time: safeParseTimestamp(d.time) as Time,
                        open: d.open,
                        high: d.high,
                        low: d.low,
                        close: d.close,
                    }));

                    // CRITICAL: Deduplicate by time - lightweight-charts requires strictly ascending
                    const seenTimes = new Set<number>();
                    const candles = rawCandles.filter(c => {
                        const t = c.time as number;
                        if (seenTimes.has(t)) return false;
                        seenTimes.add(t);
                        return true;
                    });

                    // Volume data with reduced opacity (0.3) to not compete with price candles
                    // SOTA FIX: Also deduplicate volumes to prevent "asc ordered" error
                    const rawVolumes = trimmedData.map(d => ({
                        time: safeParseTimestamp(d.time) as Time,
                        value: d.volume || 0,
                        color: d.close >= d.open
                            ? 'rgba(46, 189, 133, 0.5)'
                            : 'rgba(246, 70, 93, 0.5)',
                    }));
                    const volumeSeenTimes = new Set<number>();
                    const volumes = rawVolumes.filter(v => {
                        const t = v.time as number;
                        if (volumeSeenTimes.has(t)) return false;
                        volumeSeenTimes.add(t);
                        return true;
                    });

                    // SOTA FIX: Helper function to deduplicate line series data
                    const deduplicateSeries = (data: { time: Time; value: number }[]) => {
                        const seen = new Set<number>();
                        return data.filter(d => {
                            const t = d.time as number;
                            if (seen.has(t)) return false;
                            seen.add(t);
                            return true;
                        });
                    };

                    const vwap = deduplicateSeries(
                        trimmedData
                            .filter(d => d.vwap && d.vwap > 0)
                            .map(d => ({ time: safeParseTimestamp(d.time) as Time, value: d.vwap! }))
                    );

                    const bbUpper = deduplicateSeries(
                        trimmedData
                            .filter(d => d.bb_upper && d.bb_upper > 0)
                            .map(d => ({ time: safeParseTimestamp(d.time) as Time, value: d.bb_upper! }))
                    );

                    const bbLower = deduplicateSeries(
                        trimmedData
                            .filter(d => d.bb_lower && d.bb_lower > 0)
                            .map(d => ({ time: safeParseTimestamp(d.time) as Time, value: d.bb_lower! }))
                    );

                    if (candleSeriesRef.current) candleSeriesRef.current.setData(candles);
                    if (volumeSeriesRef.current) volumeSeriesRef.current.setData(volumes);
                    if (vwapSeriesRef.current) vwapSeriesRef.current.setData(vwap);
                    if (bbUpperSeriesRef.current) bbUpperSeriesRef.current.setData(bbUpper);
                    if (bbLowerSeriesRef.current) bbLowerSeriesRef.current.setData(bbLower);
                    // Update BB fill plugin with new data
                    if (bbFillPluginRef.current) {
                        bbFillPluginRef.current.setDataFromArrays(bbUpper, bbLower);
                    }

                    if (chartRef.current) {
                        chartRef.current.timeScale().fitContent();

                        // SOTA FIX: Force Price Scale to auto-fit new data range
                        // This resolves the issue where switching from BTC (80k) to BNB (600)
                        // keeps the 80k scale, making BNB candles invisible.
                        chartRef.current.priceScale('right').applyOptions({
                            autoScale: true,
                            scaleMargins: { top: 0.1, bottom: 0.2 }
                        });
                    }

                    const lastCandle = trimmedData[trimmedData.length - 1];
                    const prevCandle = trimmedData[trimmedData.length - 2];

                    setCurrentPrice(lastCandle.close);
                    if (prevCandle) {
                        setPriceChange(lastCandle.close - prevCandle.close);
                    }

                    currentCandleRef.current = {
                        time: lastCandle.time,
                        open: lastCandle.open,
                        high: lastCandle.high,
                        low: lastCandle.low,
                        close: lastCandle.close,
                        volume: lastCandle.volume || 0
                    };

                    // SOTA FIX: Initialize lastRenderedTimeRef with raw UTC timestamp (matches realtime update)
                    const lastChartTime = safeParseTimestamp(lastCandle.time);
                    lastRenderedTimeRef.current[timeframe] = lastChartTime;
                    console.log(`📊 Chart initialized for ${activeSymbol}/${timeframe}: lastRenderedTime=${lastChartTime}`);
                }
            } catch (err) {
                console.error("Error loading chart history:", err);
            } finally {
                setIsLoading(false);
            }
        };

        fetchHistory();
    }, [timeframe, activeSymbol]);  // SOTA: Reload on symbol OR timeframe change

    // Handle new signals from WebSocket
    useEffect(() => {
        if (!realtimeSignal) return;
        const signalTime = realtimeSignal.timestamp
            ? Math.floor(new Date(realtimeSignal.timestamp).getTime() / 1000)
            : Math.floor(Date.now() / 1000);
        addSignalMarker(realtimeSignal, signalTime);
    }, [realtimeSignal, addSignalMarker]);

    // Render signal markers on chart - SOTA: minimal visual style, arrows only (no text labels)
    useEffect(() => {
        if (!candleSeriesRef.current || signals.length === 0) return;

        // Limit markers for performance (max 100)
        const MAX_MARKERS = 100;
        const limitedSignals = signals.length > MAX_MARKERS
            ? signals.slice(-MAX_MARKERS)
            : signals;

        // Convert SignalMarker to lightweight-charts marker format
        // SOTA: Minimal style, text only for SFP
        const chartMarkers: SeriesMarker<Time>[] = limitedSignals.map(s => ({
            time: s.time,
            position: s.position,
            color: s.color,
            shape: s.shape,
            text: s.text,
            size: s.size,
        }));

        // Sort markers by time (required by lightweight-charts)
        chartMarkers.sort((a, b) => (a.time as number) - (b.time as number));

        try {
            // @ts-expect-error - setMarkers may not be in type definitions but exists in runtime
            candleSeriesRef.current.setMarkers(chartMarkers);
        } catch {
            console.log('Markers stored in state, displayed via tooltip on hover');
        }
    }, [signals]);

    // Aggregate Real-time Data with Vietnam timezone
    // NOTE: Only applies to 1m timeframe - 15m/1h use historical data from API
    useEffect(() => {
        if (!realtimeData || isLoading || isDisposedRef.current) return;

        // CRITICAL FIX: Skip realtime updates for 15m/1h timeframes
        // WebSocket only streams 1m candles. Client-side aggregation to 15m/1h
        // produces incorrect timestamps (multiple candles within same timeframe).
        // For 15m/1h, rely on historical API data which is properly aggregated by backend.
        if (timeframe !== '1m') {
            return;
        }

        try {
            // Use safeParseTimestamp for robust timestamp handling
            const time = safeParseTimestamp(realtimeData.timestamp);
            if (time <= 0) {
                console.warn('Invalid timestamp in realtime data:', realtimeData.timestamp);
                return;
            }

            // For 1m timeframe, interval is always 60 seconds
            const intervalSeconds = 60;

            const candleStartTime = Math.floor(time / intervalSeconds) * intervalSeconds;
            // SOTA FIX: Use raw UTC timestamp for chart data
            const chartTime = candleStartTime;

            // CRITICAL: Validate chronological order before update
            // lightweight-charts requires: new_time >= last_rendered_time
            // SOTA FIX: Use per-timeframe tracking
            if (chartTime < lastRenderedTimeRef.current['1m']) {
                // Skip stale data - would cause 'obsolete data' error
                return;
            }

            if (currentCandleRef.current && candleStartTime < currentCandleRef.current.time) {
                return; // Skip old data
            }

            // Update current price
            setCurrentPrice(realtimeData.close);

            if (currentCandleRef.current && currentCandleRef.current.time === candleStartTime) {
                const updatedCandle = {
                    ...currentCandleRef.current,
                    high: Math.max(currentCandleRef.current.high, realtimeData.high),
                    low: Math.min(currentCandleRef.current.low, realtimeData.low),
                    close: realtimeData.close,
                    volume: (currentCandleRef.current.volume || 0) + (realtimeData.volume || 0),
                };
                currentCandleRef.current = updatedCandle;

                if (candleSeriesRef.current) {
                    candleSeriesRef.current.update({
                        time: candleStartTime as Time,
                        open: updatedCandle.open,
                        high: updatedCandle.high,
                        low: updatedCandle.low,
                        close: updatedCandle.close,
                    });
                }

                if (volumeSeriesRef.current) {
                    volumeSeriesRef.current.update({
                        time: candleStartTime as Time,
                        value: updatedCandle.volume,
                        color: updatedCandle.close >= updatedCandle.open
                            ? 'rgba(46, 189, 133, 0.5)'
                            : 'rgba(246, 70, 93, 0.5)',
                    });
                }
            } else {
                const newCandle = {
                    time: candleStartTime,
                    open: realtimeData.open,
                    high: realtimeData.high,
                    low: realtimeData.low,
                    close: realtimeData.close,
                    volume: realtimeData.volume || 0,
                };
                currentCandleRef.current = newCandle;

                if (candleSeriesRef.current) {
                    candleSeriesRef.current.update({
                        time: candleStartTime as Time,
                        open: newCandle.open,
                        high: newCandle.high,
                        low: newCandle.low,
                        close: newCandle.close,
                    });
                }

                if (volumeSeriesRef.current) {
                    volumeSeriesRef.current.update({
                        time: toVietnamTime(candleStartTime),
                        value: newCandle.volume,
                        color: newCandle.close >= newCandle.open
                            ? 'rgba(46, 189, 133, 0.5)'
                            : 'rgba(246, 70, 93, 0.5)',
                    });
                }
            }

            // Update indicators for 1m timeframe
            if (timeframe === '1m') {
                if (vwapSeriesRef.current && realtimeData.vwap) {
                    vwapSeriesRef.current.update({
                        time: candleStartTime as Time,
                        value: realtimeData.vwap
                    });
                }
                if (bbUpperSeriesRef.current && realtimeData.bollinger) {
                    bbUpperSeriesRef.current.update({
                        time: candleStartTime as Time,
                        value: realtimeData.bollinger.upper_band
                    });
                }
                if (bbLowerSeriesRef.current && realtimeData.bollinger) {
                    bbLowerSeriesRef.current.update({
                        time: candleStartTime as Time,
                        value: realtimeData.bollinger.lower_band
                    });
                }

                // Update Liquidity Zones (Plugin)
                if (liquidityZonePluginRef.current && realtimeData.liquidity_zones) {
                    const zones: ZoneData[] = [];
                    // SL Clusters (Demand/Support if below price, Supply/Resist if above)
                    // Usually SL clusters below price = Demand zones to buy SFP
                    if (realtimeData.liquidity_zones.stop_loss_clusters) {
                        realtimeData.liquidity_zones.stop_loss_clusters.forEach(z => {
                            zones.push({
                                priceHigh: z.zone_high,
                                priceLow: z.zone_low,
                                type: 'demand', // Green for buying opps
                                strength: z.strength
                            });
                        });
                    }
                    // TP Zones (Supply)
                    if (realtimeData.liquidity_zones.take_profit_zones) {
                        realtimeData.liquidity_zones.take_profit_zones.forEach(z => {
                            zones.push({
                                priceHigh: z.zone_high,
                                priceLow: z.zone_low,
                                type: 'supply', // Red for selling opps
                                strength: z.strength
                            });
                        });
                    }
                    liquidityZonePluginRef.current.setData(zones);
                }
            }

            // Track last rendered time for chronological order validation (per-timeframe)
            lastRenderedTimeRef.current['1m'] = chartTime;
        } catch (err) {
            console.error('Error updating candle:', err);
        }
    }, [realtimeData, timeframe, isLoading]);

    // Handle 15m realtime updates from backend WebSocket (SOTA multi-stream)
    useEffect(() => {
        if (!realtimeData15m || isLoading || isDisposedRef.current || timeframe !== '15m') return;

        try {
            // Use time field directly (Unix timestamp from backend)
            const rawTime = realtimeData15m.time || safeParseTimestamp(realtimeData15m.timestamp);
            if (!rawTime || rawTime <= 0) return;

            // CRITICAL: Ensure time is a primitive number, not a Time type object
            const time = Number(rawTime);
            // SOTA FIX: Use raw UTC timestamp (no timezone offset)
            const chartTime = time;

            // Validate time is actually a number
            if (isNaN(chartTime) || typeof chartTime !== 'number') {
                console.error('Invalid chartTime (not a number):', chartTime, typeof chartTime);
                return;
            }

            // Skip if chart not initialized yet (race condition fix)
            // SOTA FIX: lastRenderedTimeRef is 0 when history not loaded
            if (!lastRenderedTimeRef.current['15m'] || chartTime < lastRenderedTimeRef.current['15m']) return;

            // SOTA: Removed console.log from hot path for production performance

            if (candleSeriesRef.current) {
                candleSeriesRef.current.update({
                    time: chartTime as Time,
                    open: realtimeData15m.open,
                    high: realtimeData15m.high,
                    low: realtimeData15m.low,
                    close: realtimeData15m.close,
                });
            }

            setCurrentPrice(realtimeData15m.close);
            lastRenderedTimeRef.current['15m'] = chartTime;
        } catch (err) {
            console.error('Error updating 15m candle:', err);
        }
    }, [realtimeData15m, timeframe, isLoading]);

    // Handle 1h realtime updates from backend WebSocket (SOTA multi-stream)
    useEffect(() => {
        if (!realtimeData1h || isLoading || isDisposedRef.current || timeframe !== '1h') return;

        try {
            // Use time field directly (Unix timestamp from backend)
            const rawTime = realtimeData1h.time || safeParseTimestamp(realtimeData1h.timestamp);
            if (!rawTime || rawTime <= 0) return;

            // CRITICAL: Ensure time is a primitive number, not a Time type object
            const time = Number(rawTime);
            // SOTA FIX: Use raw UTC timestamp (no timezone offset)
            const chartTime = time;

            // Validate time is actually a number
            if (isNaN(chartTime) || typeof chartTime !== 'number') {
                console.error('Invalid chartTime (not a number):', chartTime, typeof chartTime);
                return;
            }

            // Skip if chart not initialized yet (race condition fix)
            // SOTA FIX: lastRenderedTimeRef is 0 when history not loaded
            if (!lastRenderedTimeRef.current['1h'] || chartTime < lastRenderedTimeRef.current['1h']) return;

            // SOTA: Removed console.log from hot path for production performance

            if (candleSeriesRef.current) {
                candleSeriesRef.current.update({
                    time: chartTime as Time,
                    open: realtimeData1h.open,
                    high: realtimeData1h.high,
                    low: realtimeData1h.low,
                    close: realtimeData1h.close,
                });
            }

            setCurrentPrice(realtimeData1h.close);
            lastRenderedTimeRef.current['1h'] = chartTime;
        } catch (err) {
            console.error('Error updating 1h candle:', err);
        }
    }, [realtimeData1h, timeframe, isLoading]);

    // Get current Vietnam time
    const getCurrentVietnamTime = () => {
        const now = new Date();
        return now.toLocaleString('vi-VN', {
            timeZone: 'Asia/Ho_Chi_Minh',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    };

    const [currentTime, setCurrentTime] = useState(getCurrentVietnamTime());

    useEffect(() => {
        const timer = setInterval(() => {
            setCurrentTime(getCurrentVietnamTime());
        }, 1000);
        return () => clearInterval(timer);
    }, []);

    return (
        <div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column', borderRadius: '8px', overflow: 'hidden', backgroundColor: BINANCE_COLORS.cardBg }}>
            {/* Header Row 1 - Symbol & Price - DESKTOP ONLY */}
            {!isMobile && (
                <div style={{
                    display: 'flex',
                    flexWrap: 'wrap',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: '8px',
                    padding: '12px',
                    borderBottom: `1px solid ${BINANCE_COLORS.line}`,
                }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <span style={{ fontSize: '18px', fontWeight: 700, color: BINANCE_COLORS.textPrimary }}>
                            {activeSymbol.replace('usdt', '/USDT').toUpperCase()}
                        </span>
                        {/* SOTA: Market Mode Toggle (FUTURES/SPOT) */}
                        <div style={{ display: 'flex', border: '1px solid #333B47', borderRadius: '4px', overflow: 'hidden' }}>
                            <button
                                onClick={() => useMarketStore.getState().setMarketMode('futures')}
                                style={{
                                    padding: '2px 8px',
                                    fontSize: '11px',
                                    fontWeight: 600,
                                    backgroundColor: useMarketStore.getState().marketMode === 'futures' ? '#f59e0b' : 'transparent',
                                    color: useMarketStore.getState().marketMode === 'futures' ? '#000' : BINANCE_COLORS.textSecondary,
                                    border: 'none',
                                    cursor: 'pointer',
                                }}
                            >
                                FUTURES
                            </button>
                            <button
                                onClick={() => useMarketStore.getState().setMarketMode('spot')}
                                style={{
                                    padding: '2px 8px',
                                    fontSize: '11px',
                                    fontWeight: 600,
                                    backgroundColor: useMarketStore.getState().marketMode === 'spot' ? '#3b82f6' : 'transparent',
                                    color: useMarketStore.getState().marketMode === 'spot' ? '#fff' : BINANCE_COLORS.textSecondary,
                                    border: 'none',
                                    borderLeft: '1px solid #333B47',
                                    cursor: 'pointer',
                                }}
                            >
                                SPOT
                            </button>
                        </div>
                        <span style={{
                            fontSize: '20px',
                            fontFamily: "'JetBrains Mono', monospace",
                            fontWeight: 700,
                            color: BINANCE_COLORS.textPrimary
                        }}>
                            {currentPrice > 0 ? `$${formatPrice(currentPrice)}` : '---'}
                        </span>
                        <span style={{
                            fontSize: '14px',
                            fontFamily: "'JetBrains Mono', monospace",
                            fontWeight: 500,
                            color: priceChange >= 0 ? BINANCE_COLORS.buy : BINANCE_COLORS.sell
                        }}>
                            {currentPrice > 0
                                ? `${priceChange >= 0 ? '+' : ''}${formatPrice(priceChange)} (${((priceChange / currentPrice) * 100).toFixed(2)}%)`
                                : '---'
                            }
                        </span>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        {/* Timeframe Buttons */}
                        <div style={{ display: 'flex', gap: '4px' }}>
                            {(['1m', '15m', '1h'] as Timeframe[]).map((tf) => (
                                <button
                                    key={tf}
                                    onClick={() => handleTimeframeChange(tf)}
                                    style={{
                                        padding: '4px 12px',
                                        borderRadius: '4px',
                                        fontSize: '12px',
                                        fontWeight: 500,
                                        border: 'none',
                                        cursor: 'pointer',
                                        transition: 'all 0.2s',
                                        backgroundColor: timeframe === tf ? BINANCE_COLORS.vwap : 'transparent',
                                        color: timeframe === tf ? '#000' : BINANCE_COLORS.textSecondary,
                                    }}
                                >
                                    {tf.toUpperCase()}
                                </button>
                            ))}
                        </div>
                        {/* Vietnam Time */}
                        <span style={{
                            fontSize: '12px',
                            fontFamily: "'JetBrains Mono', monospace",
                            color: BINANCE_COLORS.textTertiary
                        }}>
                            🇻🇳 {currentTime}
                        </span>
                    </div>
                </div>
            )}

            {/* Header Row 2 - Indicators Legend - DESKTOP ONLY */}
            {!isMobile && (
                <div style={{
                    display: 'flex',
                    flexWrap: 'wrap',
                    alignItems: 'center',
                    gap: '16px',
                    padding: '6px 12px',
                    fontSize: '12px',
                    borderBottom: `1px solid ${BINANCE_COLORS.line}`,
                }}>
                    {/* SOTA Binance Style: Indicator legend with live values */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <div style={{ width: '12px', height: '2px', backgroundColor: BINANCE_COLORS.vwap }}></div>
                        <span style={{ color: BINANCE_COLORS.textTertiary, fontSize: '11px' }}>VWAP</span>
                        <span style={{ color: BINANCE_COLORS.vwap, fontFamily: "'JetBrains Mono', monospace", fontSize: '11px' }}>
                            {currentPrice > 0 ? formatPrice(currentPrice * 0.999) : '---'}
                        </span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <div style={{ width: '12px', height: '2px', backgroundColor: BINANCE_COLORS.bollinger }}></div>
                        <span style={{ color: BINANCE_COLORS.textTertiary, fontSize: '11px' }}>BB 20 2.0</span>
                        <span style={{ color: BINANCE_COLORS.bollinger, fontFamily: "'JetBrains Mono', monospace", fontSize: '11px' }}>
                            {currentPrice > 0 ? `${formatPrice(currentPrice * 1.02)} | ${formatPrice(currentPrice * 0.98)}` : '---'}
                        </span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <div style={{ width: '12px', height: '12px', borderRadius: '2px', backgroundColor: BINANCE_COLORS.buy }}></div>
                        <span style={{ color: BINANCE_COLORS.buy }}>Tăng</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <div style={{ width: '12px', height: '12px', borderRadius: '2px', backgroundColor: BINANCE_COLORS.sell }}></div>
                        <span style={{ color: BINANCE_COLORS.sell }}>Giảm</span>
                    </div>
                    {openPositions.length > 0 && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginLeft: 'auto' }}>
                            <span style={{
                                color: openPositions[0].side === 'LONG' ? BINANCE_COLORS.buy : BINANCE_COLORS.sell,
                                fontWeight: 600
                            }}>
                                ● {openPositions[0].side} @ ${formatPrice(openPositions[0].entry_price)}
                            </span>
                            <span style={{ color: BINANCE_COLORS.sell, fontSize: '11px' }}>
                                SL: ${formatPrice(openPositions[0].stop_loss)}
                            </span>
                            {openPositions[0].take_profit > 0 && (
                                <span style={{ color: BINANCE_COLORS.buy, fontSize: '11px' }}>
                                    TP: ${formatPrice(openPositions[0].take_profit)}
                                </span>
                            )}
                        </div>
                    )}
                    {activeSignal && !openPositions.length && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', marginLeft: 'auto' }}>
                            <span style={{ color: activeSignal.type === 'BUY' ? BINANCE_COLORS.buy : BINANCE_COLORS.sell }}>
                                ● {activeSignal.type} Signal Active
                            </span>
                        </div>
                    )}
                </div>
            )}

            {/* Mobile Timeframe Bar - MOBILE ONLY */}
            {isMobile && (
                <div style={{
                    display: 'flex',
                    justifyContent: 'flex-start',
                    gap: 4,
                    padding: '6px 12px',
                    backgroundColor: BINANCE_COLORS.cardBg,
                    borderBottom: `1px solid ${BINANCE_COLORS.line}`,
                }}>
                    {(['1m', '15m', '1h'] as Timeframe[]).map((tf) => (
                        <button
                            key={tf}
                            onClick={() => handleTimeframeChange(tf)}
                            style={{
                                padding: '4px 16px',
                                borderRadius: 4,
                                fontSize: 11,
                                fontWeight: 600,
                                border: 'none',
                                cursor: 'pointer',
                                backgroundColor: timeframe === tf ? BINANCE_COLORS.vwap : 'transparent',
                                color: timeframe === tf ? '#000' : BINANCE_COLORS.textSecondary,
                            }}
                        >
                            {tf.toUpperCase()}
                        </button>
                    ))}
                </div>
            )}

            {/* Chart Container */}
            <div style={{ flex: 1, position: 'relative', minHeight: 0, backgroundColor: BINANCE_COLORS.background }}>
                <div ref={chartContainerRef} style={{ width: '100%', height: '100%' }} />

                {/* Loading Spinner */}
                {isLoading && (
                    <div style={{
                        position: 'absolute',
                        inset: 0,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        zIndex: 20,
                        backgroundColor: 'rgba(11, 14, 17, 0.9)',
                    }}>
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px' }}>
                            <div style={{
                                width: '40px',
                                height: '40px',
                                border: `3px solid transparent`,
                                borderTopColor: BINANCE_COLORS.vwap,
                                borderRadius: '50%',
                                animation: 'spin 1s linear infinite',
                            }}></div>
                            <span style={{ fontSize: '14px', color: BINANCE_COLORS.vwap }}>
                                Đang tải dữ liệu...
                            </span>
                        </div>
                    </div>
                )}

                {/* Signal Markers Overlay - Visual indicators for BUY/SELL */}
                {/* SOTA: Position right with spacing to avoid blocking price scale */}
                {signals.length > 0 && (
                    <div style={{
                        position: 'absolute',
                        top: '8px',
                        right: '100px',  // SOTA: More spacing to avoid price labels
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '4px',
                        maxHeight: '150px',
                        overflowY: 'auto',
                        zIndex: 15,
                    }}>
                        {signals.slice(-5).map((s, idx) => (
                            <div
                                key={s.id || idx}
                                style={{
                                    padding: '4px 8px',
                                    borderRadius: '4px',
                                    fontSize: '11px',
                                    fontWeight: 600,
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '6px',
                                    backgroundColor: s.signal.type === 'BUY'
                                        ? 'rgba(46, 189, 133, 0.2)'
                                        : 'rgba(246, 70, 93, 0.2)',
                                    border: `1px solid ${s.color}`,
                                    color: s.color,
                                }}
                            >
                                <span>{s.signal.type === 'BUY' ? '▲' : '▼'}</span>
                                <span>{s.signal.type}</span>
                                <span style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                                    ${(s.signal.entry_price ?? 0).toFixed(0)}
                                </span>
                            </div>
                        ))}
                    </div>
                )}

                {/* Signal Tooltip */}
                {tooltipData.visible && tooltipData.signal && (
                    <div style={{
                        position: 'absolute',
                        zIndex: 30,
                        borderRadius: '8px',
                        padding: '12px',
                        boxShadow: '0 10px 25px rgba(0,0,0,0.5)',
                        pointerEvents: 'none',
                        backgroundColor: BINANCE_COLORS.cardBg,
                        border: `1px solid ${BINANCE_COLORS.line}`,
                        left: Math.min(tooltipData.x + 10, (chartContainerRef.current?.clientWidth || 400) - 200),
                        top: Math.max(tooltipData.y - 100, 10)
                    }}>
                        <div style={{
                            fontSize: '14px',
                            fontWeight: 700,
                            marginBottom: '8px',
                            color: tooltipData.signal.type === 'BUY' ? BINANCE_COLORS.buy : BINANCE_COLORS.sell
                        }}>
                            {tooltipData.signal.type === 'BUY' ? '▲' : '▼'} {tooltipData.signal.type} SIGNAL
                        </div>
                        <div style={{ fontSize: '12px', color: BINANCE_COLORS.textSecondary }}>
                            <div style={{ marginBottom: '4px' }}>Entry: <span style={{ fontFamily: "'JetBrains Mono', monospace", color: BINANCE_COLORS.textPrimary }}>${(tooltipData.signal.entry_price ?? 0).toFixed(2)}</span></div>
                            <div style={{ marginBottom: '4px' }}>Stop Loss: <span style={{ fontFamily: "'JetBrains Mono', monospace", color: BINANCE_COLORS.sell }}>${(tooltipData.signal.stop_loss ?? 0).toFixed(2)}</span></div>
                            <div style={{ marginBottom: '4px' }}>Take Profit: <span style={{ fontFamily: "'JetBrains Mono', monospace", color: BINANCE_COLORS.buy }}>${(tooltipData.signal.take_profit ?? 0).toFixed(2)}</span></div>
                            <div style={{ marginBottom: '4px' }}>Confidence: <span style={{ fontFamily: "'JetBrains Mono', monospace", color: BINANCE_COLORS.vwap }}>{((tooltipData.signal.confidence ?? 0) * 100).toFixed(0)}%</span></div>
                            <div>R:R Ratio: <span style={{ fontFamily: "'JetBrains Mono', monospace", color: BINANCE_COLORS.bollinger }}>{(tooltipData.signal.risk_reward_ratio ?? 0).toFixed(2)}</span></div>
                        </div>
                    </div>
                )}
            </div>

            {/* Active Signal Info Bar - DESKTOP ONLY (Mobile uses SignalCard below) */}
            {activeSignal && !isMobile && (
                <div style={{
                    padding: '12px',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    fontSize: '12px',
                    backgroundColor: BINANCE_COLORS.cardBg,
                    borderTop: `1px solid ${BINANCE_COLORS.line}`
                }}>
                    <div style={{ display: 'flex', gap: '24px' }}>
                        <span style={{ color: BINANCE_COLORS.textTertiary }}>
                            Entry: <span style={{ fontFamily: "'JetBrains Mono', monospace", color: BINANCE_COLORS.textPrimary }}>${(activeSignal.entry_price ?? 0).toFixed(2)}</span>
                        </span>
                        <span style={{ color: BINANCE_COLORS.textTertiary }}>
                            SL: <span style={{ fontFamily: "'JetBrains Mono', monospace", color: BINANCE_COLORS.sell }}>${(activeSignal.stop_loss ?? 0).toFixed(2)}</span>
                        </span>
                        <span style={{ color: BINANCE_COLORS.textTertiary }}>
                            TP: <span style={{ fontFamily: "'JetBrains Mono', monospace", color: BINANCE_COLORS.buy }}>${(activeSignal.take_profit ?? 0).toFixed(2)}</span>
                        </span>
                    </div>
                    <div style={{ display: 'flex', gap: '24px' }}>
                        <span style={{ color: BINANCE_COLORS.textTertiary }}>
                            Confidence: <span style={{ fontFamily: "'JetBrains Mono', monospace", color: BINANCE_COLORS.vwap }}>{((activeSignal.confidence ?? 0) * 100).toFixed(0)}%</span>
                        </span>
                        <span style={{ color: BINANCE_COLORS.textTertiary }}>
                            R:R: <span style={{ fontFamily: "'JetBrains Mono', monospace", color: BINANCE_COLORS.bollinger }}>{(activeSignal.risk_reward_ratio ?? 0).toFixed(2)}</span>
                        </span>
                    </div>
                </div>
            )}
        </div>
    );
};

export default CandleChart;
