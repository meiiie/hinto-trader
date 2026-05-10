import React from 'react';
// SOTA: Use Zustand store for multi-symbol data
import { useActiveData1m, useActiveSymbol, useConnectionState } from '../stores/marketStore';

const PriceTicker: React.FC = () => {
    // SOTA: Use Zustand selectors for active symbol data
    const data = useActiveData1m();
    const activeSymbol = useActiveSymbol();
    const connection = useConnectionState();
    const isConnected = connection.isConnected;

    // Format symbol for display (btcusdt -> BTC/USDT)
    const displaySymbol = activeSymbol.replace('usdt', '/USDT').toUpperCase();

    const formatPrice = (price: number) => {
        return new Intl.NumberFormat('en-US', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        }).format(price);
    };

    return (
        <div className="bg-zinc-950/90 backdrop-blur-sm border border-zinc-800 rounded-lg p-3 min-w-[200px]">
            {/* Header */}
            <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                    <span className="text-sm font-bold text-white">{displaySymbol}</span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-400 font-medium">
                        Perp
                    </span>
                </div>
                <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-emerald-400 animate-pulse' : 'bg-rose-400'}`} />
            </div>

            {data ? (
                <>
                    {/* Price */}
                    <div className="text-2xl font-bold font-mono text-white tracking-tight">
                        ${formatPrice(data.close)}
                    </div>

                    {/* Change */}
                    {data.change_percent !== undefined && (
                        <div className={`text-sm font-mono font-medium ${data.change_percent >= 0 ? 'text-emerald-400' : 'text-rose-400'
                            }`}>
                            {data.change_percent >= 0 ? '+' : ''}{data.change_percent.toFixed(2)}%
                        </div>
                    )}

                    {/* Indicators Row */}
                    <div className="flex gap-3 mt-2 pt-2 border-t border-zinc-800">
                        <div>
                            <div className="text-[10px] text-zinc-500 uppercase">RSI</div>
                            <div className={`text-xs font-mono font-medium ${(data.rsi || 0) > 70 ? 'text-rose-400' :
                                (data.rsi || 0) < 30 ? 'text-emerald-400' : 'text-zinc-300'
                                }`}>
                                {data.rsi?.toFixed(1) || '-'}
                            </div>
                        </div>
                        <div>
                            <div className="text-[10px] text-zinc-500 uppercase">VWAP</div>
                            <div className="text-xs font-mono font-medium text-yellow-500">
                                {data.vwap ? formatPrice(data.vwap) : '-'}
                            </div>
                        </div>
                    </div>
                </>
            ) : (
                <div className="text-zinc-500 text-sm animate-pulse">Connecting...</div>
            )}
        </div>
    );
};

export default PriceTicker;
