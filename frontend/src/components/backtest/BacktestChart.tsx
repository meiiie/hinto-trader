import React, { useEffect, useRef, useMemo, memo } from 'react';
import { createChart, ColorType, IChartApi, ISeriesApi, Time, CandlestickSeries, LineSeries } from 'lightweight-charts';

interface CandleData {
    time: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume?: number;
}

interface Trade {
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
}

interface BacktestChartProps {
    symbol: string;
    candles: CandleData[];
    trades: Trade[];
    indicators?: {
        vwap: (number | null)[];
        bb_upper: (number | null)[];
        bb_lower: (number | null)[];
    };
}

const BacktestChartInner: React.FC<BacktestChartProps> = ({ symbol, candles, trades: _trades, indicators }) => {
    const chartContainerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<IChartApi | null>(null);
    const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
    const vwapSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
    const bbUpperRef = useRef<ISeriesApi<"Line"> | null>(null);
    const bbLowerRef = useRef<ISeriesApi<"Line"> | null>(null);

    // Memoize sorted candles to prevent reference changes
    const sortedCandles = useMemo(() =>
        [...candles].sort((a, b) => new Date(a.time).getTime() - new Date(b.time).getTime()),
        [candles]
    );

    // CHART INITIALIZATION - runs only once
    useEffect(() => {
        if (!chartContainerRef.current) return;

        const chart = createChart(chartContainerRef.current, {
            layout: {
                background: { type: ColorType.Solid, color: '#111827' },
                textColor: '#9CA3AF',
            },
            grid: {
                vertLines: { color: '#374151' },
                horzLines: { color: '#374151' },
            },
            width: chartContainerRef.current.clientWidth,
            height: 500,
            timeScale: {
                timeVisible: true,
                secondsVisible: false,
            },
        });

        chartRef.current = chart;

        // Create series (once)
        candleSeriesRef.current = chart.addSeries(CandlestickSeries, {
            upColor: '#10B981',
            downColor: '#EF4444',
            borderVisible: false,
            wickUpColor: '#10B981',
            wickDownColor: '#EF4444',
        });

        vwapSeriesRef.current = chart.addSeries(LineSeries, {
            color: '#F59E0B',
            lineWidth: 2,
            priceLineVisible: false,
            lastValueVisible: false,
        });

        bbUpperRef.current = chart.addSeries(LineSeries, {
            color: 'rgba(59, 130, 246, 0.5)',
            lineWidth: 1,
            priceLineVisible: false,
            lastValueVisible: false,
        });

        bbLowerRef.current = chart.addSeries(LineSeries, {
            color: 'rgba(59, 130, 246, 0.5)',
            lineWidth: 1,
            priceLineVisible: false,
            lastValueVisible: false,
        });

        const handleResize = () => {
            if (chartContainerRef.current && chartRef.current) {
                chartRef.current.applyOptions({ width: chartContainerRef.current.clientWidth });
            }
        };

        window.addEventListener('resize', handleResize);

        return () => {
            window.removeEventListener('resize', handleResize);
            chart.remove();
            chartRef.current = null;
        };
    }, []); // Empty deps - chart created once

    // DATA UPDATE - runs when data changes
    useEffect(() => {
        if (!candleSeriesRef.current || sortedCandles.length === 0) return;

        // Update candle data
        const chartData = sortedCandles.map(c => ({
            time: (new Date(c.time).getTime() / 1000) as Time,
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close,
        }));

        candleSeriesRef.current.setData(chartData);

        // Update VWAP
        if (indicators?.vwap && vwapSeriesRef.current) {
            const vwapData = sortedCandles
                .map((c, i) => {
                    const val = indicators.vwap[i];
                    return val !== null && val !== undefined
                        ? { time: (new Date(c.time).getTime() / 1000) as Time, value: val }
                        : null;
                })
                .filter((x): x is { time: Time; value: number } => x !== null);
            vwapSeriesRef.current.setData(vwapData);
        }

        // Update BB Upper
        if (indicators?.bb_upper && bbUpperRef.current) {
            const bbUpperData = sortedCandles
                .map((c, i) => {
                    const val = indicators.bb_upper[i];
                    return val !== null && val !== undefined
                        ? { time: (new Date(c.time).getTime() / 1000) as Time, value: val }
                        : null;
                })
                .filter((x): x is { time: Time; value: number } => x !== null);
            bbUpperRef.current.setData(bbUpperData);
        }

        // Update BB Lower
        if (indicators?.bb_lower && bbLowerRef.current) {
            const bbLowerData = sortedCandles
                .map((c, i) => {
                    const val = indicators.bb_lower[i];
                    return val !== null && val !== undefined
                        ? { time: (new Date(c.time).getTime() / 1000) as Time, value: val }
                        : null;
                })
                .filter((x): x is { time: Time; value: number } => x !== null);
            bbLowerRef.current.setData(bbLowerData);
        }

        // Fit content
        if (chartRef.current) {
            chartRef.current.timeScale().fitContent();
        }
    }, [sortedCandles, indicators]);

    return (
        <div className="w-full h-[500px] border border-gray-700 rounded-lg overflow-hidden relative">
            <div ref={chartContainerRef} className="w-full h-full" />
            <div className="absolute top-2 left-2 bg-gray-800/80 p-2 rounded text-xs text-white z-10 font-mono">
                <div className="font-bold text-lg">{symbol}</div>
                <div>candles: {candles.length}</div>
                {indicators && (
                    <div className="flex gap-2 mt-1">
                        <span className="text-yellow-500">■ VWAP</span>
                        <span className="text-blue-400">■ BBands</span>
                    </div>
                )}
            </div>
        </div>
    );
};

// SOTA: Memoize to prevent re-renders from parent state changes
export const BacktestChart = memo(BacktestChartInner);
BacktestChart.displayName = 'BacktestChart';
