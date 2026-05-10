import React, { useEffect, useRef } from 'react';
import { createChart, ColorType, IChartApi, CandlestickSeries } from 'lightweight-charts';

interface TradingChartProps {
  symbol: string;
  data: any[]; // Candle data
  markers?: any[]; // Buy/Sell arrows
  lines?: any[]; // Horizontal lines (Limit, SL, TP)
}

export const TradingChart: React.FC<TradingChartProps> = ({ symbol, data, markers }) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#111827' }, // gray-900
        textColor: '#9CA3AF',
      },
      grid: {
        vertLines: { color: '#1F2937' },
        horzLines: { color: '#1F2937' },
      },
      width: chartContainerRef.current.clientWidth,
      height: chartContainerRef.current.clientHeight,
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
      },
    });

    const candlestickSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#22C55E',
      downColor: '#EF4444',
      borderVisible: false,
      wickUpColor: '#22C55E',
      wickDownColor: '#EF4444',
    });

    // Mock Data for visualization if empty
    const initialData = data.length > 0 ? data : [
      { time: '2025-12-31', open: 100, high: 105, low: 98, close: 102 },
      { time: '2026-01-01', open: 102, high: 103, low: 95, close: 96 },
      { time: '2026-01-02', open: 96, high: 100, low: 94, close: 99 },
    ];

    candlestickSeries.setData(initialData);

    if (markers) {
      (candlestickSeries as any).setMarkers(markers);
    }

    chartRef.current = chart;

    // Resize handler
    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
          height: chartContainerRef.current.clientHeight
        });
      }
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [symbol]); // Re-render when symbol changes

  return (
    <div className="flex-1 h-full relative bg-gray-900 flex flex-col">
      <div className="absolute top-4 left-4 z-10">
        <h1 className="text-4xl font-black text-gray-800 tracking-tighter select-none pointer-events-none">
          {symbol.replace('USDT', '')}
        </h1>
      </div>
      <div ref={chartContainerRef} className="w-full h-full" />
    </div>
  );
};
