import React from 'react';
import { Zap, Lock, Activity } from 'lucide-react';

interface Shark {
  symbol: string;
  price: number;
  change_24h: number;
  score: number;
  status: string;
  active_pnl: number;
  signal_type?: string;
}

interface SharkRadarProps {
  sharks: Shark[];
  onSelect: (symbol: string) => void;
  selectedSymbol: string;
}

export const SharkRadar: React.FC<SharkRadarProps> = ({ sharks, onSelect, selectedSymbol }) => {
  return (
    <div className="bg-gray-900 border-r border-gray-800 h-full flex flex-col w-80">
      <div className="p-4 border-b border-gray-800 flex justify-between items-center">
        <h2 className="text-xl font-bold text-white flex items-center gap-2">
          <Zap className="w-5 h-5 text-yellow-400" /> Shark Radar
        </h2>
        <span className="text-xs bg-gray-800 text-gray-400 px-2 py-1 rounded">
          {sharks.length} Targets
        </span>
      </div>

      <div className="flex-1 overflow-y-auto">
        {sharks.map((shark) => (
          <div
            key={shark.symbol}
            onClick={() => onSelect(shark.symbol)}
            className={`p-4 border-b border-gray-800 cursor-pointer transition-colors hover:bg-gray-800 ${
              selectedSymbol === shark.symbol ? 'bg-gray-800 border-l-4 border-l-yellow-400' : ''
            }`}
          >
            <div className="flex justify-between items-start mb-2">
              <div>
                <div className="font-bold text-white text-lg">{shark.symbol.replace('USDT', '')}</div>
                <div className={`text-xs ${shark.change_24h >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  ${shark.price.toLocaleString()} ({shark.change_24h >= 0 ? '+' : ''}{shark.change_24h}%)
                </div>
              </div>
              <StatusBadge status={shark.status} />
            </div>

            <div className="space-y-2">
              {/* Score Bar */}
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-500 w-8">Score</span>
                <div className="flex-1 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full ${getScoreColor(shark.score)}`}
                    style={{ width: `${shark.score}%` }}
                  />
                </div>
                <span className="text-xs text-gray-300 w-6 text-right">{shark.score}</span>
              </div>

              {/* Active PnL (if in position) */}
              {shark.status === 'IN_POSITION' && (
                <div className="flex justify-between items-center bg-gray-900/50 p-1.5 rounded">
                  <span className="text-xs text-gray-400">Unr. PnL</span>
                  <span className={`text-sm font-mono font-bold ${shark.active_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {shark.active_pnl >= 0 ? '+' : ''}${shark.active_pnl.toFixed(2)}
                  </span>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

const StatusBadge = ({ status }: { status: string }) => {
  switch (status) {
    case 'HUNTING':
      return <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-blue-900/30 text-blue-400 border border-blue-800 flex items-center gap-1"><Activity className="w-3 h-3" /> HUNTING</span>;
    case 'IN_POSITION':
      return <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-green-900/30 text-green-400 border border-green-800 flex items-center gap-1"><Zap className="w-3 h-3" /> ACTIVE</span>;
    case 'COOLDOWN':
      return <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-red-900/30 text-red-400 border border-red-800 flex items-center gap-1"><Lock className="w-3 h-3" /> BLOCKED</span>;
    default:
      return null;
  }
};

const getScoreColor = (score: number) => {
  if (score >= 80) return 'bg-green-500 shadow-[0_0_10px_rgba(34,197,94,0.5)]';
  if (score >= 50) return 'bg-yellow-500';
  return 'bg-gray-500';
};
