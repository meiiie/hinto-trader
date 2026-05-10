import React, { useMemo } from 'react';
import { ReplaySnapshot } from '../../types/replay';

interface SharkTankBoardProps {
    snapshot: ReplaySnapshot | null;
    className?: string;
}

const SharkTankBoard: React.FC<SharkTankBoardProps> = ({ snapshot, className }) => {
    const [expandedSymbol, setExpandedSymbol] = React.useState<string | null>(null);

    const combinedList = useMemo(() => {
        if (!snapshot) return [];

        const list: any[] = [];

        // 1. Active Positions (Top Priority)
        snapshot.active_positions.forEach((p) => {
            list.push({
                symbol: p.symbol,
                status: 'ACTIVE',
                side: p.side,
                price: p.entry_price,
                info: `PnL: Calculating...`, // In a real app we'd need current price to calc PnL
                original: p,
                type: 'position'
            });
        });

        // 2. Pending Orders
        snapshot.pending_orders.forEach((o) => {
            list.push({
                symbol: o.symbol,
                status: o.status === 'LOCKED' ? 'LOCKED' : 'PENDING',
                side: o.side,
                price: o.target_price,
                info: `Conf: ${o.confidence.toFixed(2)}`,
                original: o,
                type: 'order'
            });
        });

        // 3. Rejections / Recycles (From Events) - Only show if relevant or recent?
        // Let's filter to only show 'REJECT' or 'RECYCLE' if we want history, but maybe clutter for board.
        // For board, let's stick to Active/Pending for main view, and Events in details?
        // Actually, user wants to see "rejections" too.
        snapshot.events.forEach((e) => {
            if (e.type === 'REJECT' || e.type === 'RECYCLE') {
                list.push({
                    symbol: e.symbol || e.killed, // Handle recycle 'killed'
                    status: e.type,
                    side: '-',
                    price: 0,
                    info: e.reason || (e.type === 'RECYCLE' ? `Swapped for ${e.new}` : ''),
                    original: e,
                    type: 'event'
                });
            }
        });

        return list;
    }, [snapshot]);

    const toggleExpand = (symbol: string) => {
        setExpandedSymbol(prev => prev === symbol ? null : symbol);
    };

    if (!snapshot) {
        return (
            <div className={`p-4 bg-gray-900 rounded-lg text-white ${className}`}>
                <h3 className="text-xl font-bold mb-4 text-cyan-400">🦈 Shark Tank Board</h3>
                <p className="text-gray-500">Waiting for data...</p>
            </div>
        );
    }

    return (
        <div className={`p-4 bg-gray-900 rounded-lg text-white ${className} border border-gray-700 h-full flex flex-col`}>
            <div className="flex justify-between items-center mb-4 border-b border-gray-700 pb-2">
                <h3 className="text-xl font-bold text-cyan-400 flex items-center gap-2">
                    <span>🦈</span> Shark Tank Board
                </h3>
                <div className="text-right">
                    <div className="text-xs text-gray-400">Balance</div>
                    <div className="font-mono text-lg text-green-400">${snapshot.balance.toFixed(2)}</div>
                </div>
            </div>

            <div className="overflow-y-auto flex-1 custom-scrollbar">
                <table className="w-full text-sm">
                    <thead className="text-gray-500 border-b border-gray-800 sticky top-0 bg-gray-900">
                        <tr>
                            <th className="text-left py-2">Symbol</th>
                            <th className="text-center py-2">Side</th>
                            <th className="text-center py-2">Status</th>
                            <th className="text-right py-2">Info</th>
                        </tr>
                    </thead>
                    <tbody>
                        {combinedList.length === 0 ? (
                            <tr>
                                <td colSpan={4} className="text-center py-8 text-gray-600 italic">
                                    No activity in the tank
                                </td>
                            </tr>
                        ) : combinedList.map((item, idx) => (
                            <React.Fragment key={`${item.symbol}-${idx}`}>
                                <tr
                                    className={`border-b border-gray-800 hover:bg-gray-800 transition-colors cursor-pointer ${expandedSymbol === item.symbol ? 'bg-gray-800' : ''}`}
                                    onClick={() => toggleExpand(item.symbol)}
                                >
                                    <td className="py-2 font-mono font-bold text-cyan-200">{item.symbol}</td>
                                    <td className={`text-center py-2 font-bold ${item.side === 'LONG' ? 'text-green-500' : item.side === 'SHORT' ? 'text-red-500' : 'text-gray-500'}`}>
                                        {item.side === 'LONG' ? '▲' : item.side === 'SHORT' ? '▼' : '-'}
                                    </td>
                                    <td className="text-center py-2">
                                        <StatusBadge status={item.status} />
                                    </td>
                                    <td className="text-right py-2 text-xs text-gray-400 font-mono">
                                        {item.info}
                                    </td>
                                </tr>
                                {expandedSymbol === item.symbol && (
                                    <tr className="bg-gray-800/50">
                                        <td colSpan={4} className="p-3 text-xs text-gray-300">
                                            <div className="grid grid-cols-2 gap-4">
                                                <div>
                                                    <div className="text-gray-500 font-bold mb-1">STRATEGY INFO</div>
                                                    <div className="flex justify-between">
                                                        <span>Entry Price:</span>
                                                        <span className="font-mono text-white">{item.price > 0 ? `$${item.price}` : 'N/A'}</span>
                                                    </div>
                                                    {item.original.confidence && (
                                                        <div className="flex justify-between">
                                                            <span>Confidence:</span>
                                                            <span className="font-mono text-yellow-400">{(item.original.confidence * 100).toFixed(1)}%</span>
                                                        </div>
                                                    )}
                                                    {item.original.sl > 0 && (
                                                        <div className="flex justify-between">
                                                            <span>Stop Loss:</span>
                                                            <span className="font-mono text-red-400">${item.original.sl}</span>
                                                        </div>
                                                    )}
                                                    {item.original.tp_hit > 0 && (
                                                        <div className="flex justify-between">
                                                            <span>TP Hit:</span>
                                                            <span className="font-mono text-green-400">${item.original.tp_hit}</span>
                                                        </div>
                                                    )}
                                                </div>
                                                <div>
                                                    <div className="text-gray-500 font-bold mb-1">EVENT LOG</div>
                                                    {/* Find events for this symbol in the snapshot */}
                                                    <div className="max-h-24 overflow-y-auto">
                                                        {snapshot.events
                                                            .filter(e => e.symbol === item.symbol || e.killed === item.symbol || e.new === item.symbol)
                                                            .map((e, i) => (
                                                                <div key={i} className="mb-1 border-l-2 border-gray-600 pl-2">
                                                                    <span className={`font-bold ${e.type === 'ACCEPT' ? 'text-green-400' : e.type === 'REJECT' ? 'text-red-400' : 'text-gray-400'}`}>
                                                                        {e.type}
                                                                    </span>
                                                                    <span className="ml-2 text-gray-400">{e.reason || e.msg}</span>
                                                                </div>
                                                            ))
                                                        }
                                                        {snapshot.events.filter(e => e.symbol === item.symbol || e.killed === item.symbol || e.new === item.symbol).length === 0 && (
                                                            <div className="italic text-gray-500">No recent events</div>
                                                        )}
                                                    </div>
                                                </div>
                                            </div>
                                        </td>
                                    </tr>
                                )}
                            </React.Fragment>
                        ))}
                    </tbody>
                </table>
            </div>

            <div className="mt-4 pt-2 border-t border-gray-700 text-xs text-gray-500 flex justify-between">
                <span>Slots: {snapshot.active_positions.length + snapshot.pending_orders.length}/5</span>
                <span>Events: {snapshot.events.length}</span>
            </div>
        </div>
    );
};

const StatusBadge = ({ status }: { status: string }) => {
    let color = 'bg-gray-700 text-gray-300';
    switch (status) {
        case 'ACTIVE': color = 'bg-green-900 text-green-300 border border-green-700'; break;
        case 'PENDING': color = 'bg-yellow-900 text-yellow-300 border border-yellow-700'; break;
        case 'LOCKED': color = 'bg-blue-900 text-blue-300 border border-blue-700'; break;
        case 'REJECT': color = 'bg-red-900 text-red-300 border border-red-700'; break;
        case 'RECYCLE': color = 'bg-purple-900 text-purple-300 border border-purple-700'; break;
    }
    return (
        <span className={`px-2 py-0.5 rounded textxs font-bold ${color}`}>
            {status}
        </span>
    );
};

export default SharkTankBoard;
