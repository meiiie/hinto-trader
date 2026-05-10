import React, { useEffect, useRef } from 'react';
import { createChart, ColorType, IChartApi, ISeriesApi, Time, CandlestickSeries, HistogramSeries, LineSeries, LineStyle, CrosshairMode } from 'lightweight-charts';
import { CandleData, Indicators } from '../../types/replay';

// --- CONSTANTS & STYLES (MATCHING CANDLECHART.TSX) ---
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
    bollingerFill: 'rgba(31, 125, 200, 0.1)',
    line: '#2B2F36',
};

interface ReplayChartProps {
    symbol: string;
    data: CandleData[];
    indicators?: Indicators;
    currentTime?: string;
    markers?: any[]; // Buy/Sell arrows
    activePosition?: any; // PositionSnapshot
}

const ReplayChart: React.FC<ReplayChartProps> = (props) => {
    const { symbol, data, indicators, currentTime, activePosition } = props;
    const chartContainerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<IChartApi | null>(null);

    // Series Refs
    const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
    const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
    const bbUpperRef = useRef<ISeriesApi<"Line"> | null>(null);
    const bbLowerRef = useRef<ISeriesApi<"Line"> | null>(null);
    const vwapRef = useRef<ISeriesApi<"Line"> | null>(null);

    // Price Line Refs (for stability)
    const entryLineRef = useRef<any>(null);
    const slLineRef = useRef<any>(null);
    const tpLineRef = useRef<any>(null);

    // -------------------------------------------------------------------------
    // 1. INITIALIZE CHART (Binance Style)
    // -------------------------------------------------------------------------
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
            height: chartContainerRef.current.clientHeight,
            timeScale: {
                timeVisible: true,
                secondsVisible: false,
                borderColor: BINANCE_COLORS.line,
                tickMarkFormatter: (time: Time) => {
                    const date = new Date((time as number) * 1000);
                    return date.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', hour12: false });
                }
            },
            rightPriceScale: {
                borderColor: BINANCE_COLORS.line,
                scaleMargins: { top: 0.1, bottom: 0.2 }, // Leave room for volume
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
        });

        // 1. Candlestick Series
        const candleSeries = chart.addSeries(CandlestickSeries, {
            upColor: BINANCE_COLORS.buy,
            downColor: BINANCE_COLORS.sell,
            borderUpColor: BINANCE_COLORS.buy,
            borderDownColor: BINANCE_COLORS.sell,
            wickUpColor: BINANCE_COLORS.buy,
            wickDownColor: BINANCE_COLORS.sell,
        });
        candleSeriesRef.current = candleSeries;

        // 2. Volume Series
        const volumeSeries = chart.addSeries(HistogramSeries, {
            color: BINANCE_COLORS.grid, // Base color, will be colored by data
            priceFormat: { type: 'volume' },
            priceScaleId: 'volume', // Overlay at bottom
        });
        volumeSeries.priceScale().applyOptions({
            scaleMargins: { top: 0.8, bottom: 0 },
        });
        volumeSeriesRef.current = volumeSeries;

        // 3. Indicators
        bbUpperRef.current = chart.addSeries(LineSeries, {
            color: BINANCE_COLORS.bollinger,
            lineWidth: 1,
            title: 'BB Up',
            priceLineVisible: false,
            lastValueVisible: false
        });
        bbLowerRef.current = chart.addSeries(LineSeries, {
            color: BINANCE_COLORS.bollinger,
            lineWidth: 1,
            title: 'BB Low',
            priceLineVisible: false,
            lastValueVisible: false
        });
        vwapRef.current = chart.addSeries(LineSeries, {
            color: BINANCE_COLORS.vwap,
            lineWidth: 2,
            title: 'VWAP',
            priceLineVisible: false,
            lastValueVisible: false
        });

        chartRef.current = chart;

        const handleResize = () => {
            if (chartContainerRef.current) {
                chart.applyOptions({ width: chartContainerRef.current.clientWidth, height: chartContainerRef.current.clientHeight });
            }
        };
        window.addEventListener('resize', handleResize);

        return () => {
            window.removeEventListener('resize', handleResize);
            chart.remove();
        };
    }, []);

    // -------------------------------------------------------------------------
    // 2. MEMOIZE DATA PROCESSING (Performance)
    // -------------------------------------------------------------------------
    const { allCandles, allVolumes, allIndicators } = React.useMemo(() => {
        if (!data || data.length === 0) return { allCandles: [], allVolumes: [], allIndicators: {} };

        const c = data.map(d => ({
            time: (new Date(d.time).getTime() / 1000) as Time,
            open: d.open,
            high: d.high,
            low: d.low,
            close: d.close
        })).sort((a, b) => (a.time as number) - (b.time as number));

        const v = data.map(d => ({
            time: (new Date(d.time).getTime() / 1000) as Time,
            value: d.volume,
            color: d.close >= d.open ? 'rgba(46, 189, 133, 0.5)' : 'rgba(246, 70, 93, 0.5)'
        })).sort((a, b) => (a.time as number) - (b.time as number));

        const inds: any = {};
        if (indicators) {
            // Updated to accept (number | null)[]
            const processInd = (arr: (number | null)[]) => arr ? data.map((d, i) => ({
                time: (new Date(d.time).getTime() / 1000) as Time,
                value: arr[i] || NaN
            })).filter(x => !isNaN(x.value)) : [];

            inds.bb_upper = processInd(indicators.bb_upper!);
            inds.bb_lower = processInd(indicators.bb_lower!);
            inds.vwap = processInd(indicators.vwap!);
        }

        return { allCandles: c, allVolumes: v, allIndicators: inds };
    }, [data, indicators]);

    // -------------------------------------------------------------------------
    // 3. DYNAMIC RENDERING (Tick-by-Tick)
    // -------------------------------------------------------------------------
    useEffect(() => {
        if (!candleSeriesRef.current || allCandles.length === 0) return;

        let visibleCandles = allCandles;
        let visibleVolumes = allVolumes;
        let visibleIndicators: any = allIndicators;

        if (currentTime) {
            const currentTs = new Date(currentTime).getTime() / 1000;
            visibleCandles = allCandles.filter(d => (d.time as number) <= currentTs);
            visibleVolumes = allVolumes.filter(d => (d.time as number) <= currentTs);

            visibleIndicators = {};
            Object.keys(allIndicators).forEach(key => {
                visibleIndicators[key] = allIndicators[key].filter((d: any) => (d.time as number) <= currentTs);
            });
        }

        candleSeriesRef.current.setData(visibleCandles);
        if (volumeSeriesRef.current) volumeSeriesRef.current.setData(visibleVolumes);
        if (bbUpperRef.current && visibleIndicators.bb_upper) bbUpperRef.current.setData(visibleIndicators.bb_upper);
        if (bbLowerRef.current && visibleIndicators.bb_lower) bbLowerRef.current.setData(visibleIndicators.bb_lower);
        if (vwapRef.current && visibleIndicators.vwap) vwapRef.current.setData(visibleIndicators.vwap);

        // Auto-Scroll
        if (chartRef.current && visibleCandles.length > 0) {
            chartRef.current.timeScale().scrollToPosition(0, false);
        }

    }, [currentTime, allCandles, allVolumes, allIndicators]);

    // -------------------------------------------------------------------------
    // 4. TP/SL LINES (Isolated Effect)
    // -------------------------------------------------------------------------
    useEffect(() => {
        if (!candleSeriesRef.current) return;

        // Cleanup function helper
        const cleanupLines = () => {
            if (entryLineRef.current) { candleSeriesRef.current?.removePriceLine(entryLineRef.current); entryLineRef.current = null; }
            if (slLineRef.current) { candleSeriesRef.current?.removePriceLine(slLineRef.current); slLineRef.current = null; }
            if (tpLineRef.current) { candleSeriesRef.current?.removePriceLine(tpLineRef.current); tpLineRef.current = null; }
        };

        if (activePosition) {
            // If already drawn for the same position, do nothing?
            // Actually, we must redraw if properties change (trailing stop).
            // Simplified: Redraw on activePosition change (which happens on every snapshot tick if pnl changes, BUT we only care if SL/TP changes)

            // To prevent flickering: remove old, add new.
            // Since this effect ONLY runs when activePosition object changes,
            // and activePosition comes from snapshot which updates every tick...
            // WE MUST BE CAREFUL.
            // Ideally check if values actually changed.

            // For now, let's try strict redrawing. If it flickers, we can optimize.
            cleanupLines();

            // Entry
            entryLineRef.current = candleSeriesRef.current.createPriceLine({
                price: activePosition.entry_price,
                color: '#fbbf24', // Amber
                lineWidth: 1,
                lineStyle: LineStyle.Solid,
                axisLabelVisible: true,
                title: 'ENTRY',
            });

            // SL
            if (activePosition.sl > 0) {
                slLineRef.current = candleSeriesRef.current.createPriceLine({
                    price: activePosition.sl,
                    color: BINANCE_COLORS.sell,
                    lineWidth: 1,
                    lineStyle: LineStyle.Dashed,
                    axisLabelVisible: true,
                    title: `SL`,
                });
            }

            // TP: Check for 'tp', 'tp_price', or 'take_profit'
            const tp = activePosition.tp || activePosition.tp_price || activePosition.take_profit || 0;
            if (tp > 0) {
                tpLineRef.current = candleSeriesRef.current.createPriceLine({
                    price: tp,
                    color: BINANCE_COLORS.buy,
                    lineWidth: 1,
                    lineStyle: LineStyle.Dashed,
                    axisLabelVisible: true,
                    title: `TP`,
                });
            }

        } else {
            // No active position -> clear lines
            cleanupLines();
        }

    }, [activePosition?.symbol, activePosition?.entry_price, activePosition?.sl, activePosition?.tp, activePosition?.tp_price]);
    // ^ Dependency Optimization: Only re-run if key price values change.

    return (
        <div className="relative w-full h-full bg-[#181A20]">
            <div className="absolute top-2 left-2 z-10 bg-black/50 px-2 py-1 rounded text-cyan-400 font-bold font-mono">
                {symbol} {currentTime && <span className="text-gray-400 text-xs ml-2">{new Date(currentTime).toLocaleTimeString()}</span>}
            </div>
            <div ref={chartContainerRef} className="w-full h-full" />
        </div>
    );
};

export default ReplayChart;
