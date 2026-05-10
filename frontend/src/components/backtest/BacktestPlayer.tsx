import React, { useState, useEffect, useRef, useCallback } from 'react';
import { ReplayData, ReplaySnapshot } from '../../types/replay';
import SharkTankBoard from './SharkTankBoard';
import ReplayChart from './ReplayChart';
import { FaPlay, FaPause, FaFolderOpen } from 'react-icons/fa';

const BacktestPlayer: React.FC = () => {
    const [replayData, setReplayData] = useState<ReplayData | null>(null);
    const [currentIndex, setCurrentIndex] = useState(0);
    const [isPlaying, setIsPlaying] = useState(false);
    const [speed, setSpeed] = useState(1);
    const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);

    const fileInputRef = useRef<HTMLInputElement>(null);
    const requestRef = useRef<number | undefined>(undefined);
    const lastTimeRef = useRef<number | undefined>(undefined);

    const loadFile = (event: React.ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = (e) => {
            try {
                const json = JSON.parse(e.target?.result as string);
                if (json.snapshots && Array.isArray(json.snapshots)) {
                    setReplayData(json);
                    setCurrentIndex(0);
                    setIsPlaying(false);
                    // Auto-select first symbol from data if available
                    if (json.symbols && json.symbols.length > 0) {
                        setSelectedSymbol(json.symbols[0]);
                    }
                } else {
                    alert("Invalid replay file format");
                }
            } catch (err) {
                console.error(err);
                alert("Failed to parse JSON");
            }
        };
        reader.readAsText(file);
    };

    const stepForward = useCallback(() => {
        if (!replayData) return;
        setCurrentIndex(prev => {
            if (prev >= replayData.snapshots.length - 1) {
                setIsPlaying(false);
                return prev;
            }
            return prev + 1;
        });
    }, [replayData]);

    const animate = (time: number) => {
        if (!isPlaying || !replayData) return;
        if (lastTimeRef.current !== undefined) {
            const deltaTime = time - lastTimeRef.current;
            if (deltaTime >= (1000 / speed)) {
                stepForward();
                lastTimeRef.current = time;
            }
        } else {
            lastTimeRef.current = time;
        }
        requestRef.current = requestAnimationFrame(animate);
    };

    useEffect(() => {
        if (isPlaying) requestRef.current = requestAnimationFrame(animate);
        else {
            if (requestRef.current) cancelAnimationFrame(requestRef.current);
            lastTimeRef.current = undefined;
        }
        return () => { if (requestRef.current) cancelAnimationFrame(requestRef.current); };
    }, [isPlaying, speed, stepForward]);

    const currentSnapshot: ReplaySnapshot | null = replayData ? replayData.snapshots[currentIndex] : null;

    return (
        <div className="flex h-full bg-gray-950 text-white overflow-hidden">
            {/* LEFT: Chart Area */}
            <div className="flex-1 flex flex-col border-r border-gray-800">
                <div className="flex-1 bg-gray-900 relative flex items-center justify-center min-h-0">
                    {/* Debug Log */}
                    {/* Chart Component Logic */}
                    {replayData && selectedSymbol ? (
                        (() => {
                            const candleData = replayData.candles?.[selectedSymbol] || replayData.candles?.[selectedSymbol.toLowerCase()];

                            // Safe check for active position
                            const activePos = currentSnapshot?.active_positions.find(
                                p => p.symbol === selectedSymbol || p.symbol.toLowerCase() === selectedSymbol.toLowerCase()
                            );

                            if (candleData) {
                                return (
                                    <ReplayChart
                                        symbol={selectedSymbol}
                                        data={candleData}
                                        indicators={replayData.indicators?.[selectedSymbol] || replayData.indicators?.[selectedSymbol.toLowerCase()]}
                                        currentTime={currentSnapshot?.timestamp}
                                        activePosition={activePos}
                                    />
                                );
                            }
                            return <div className="text-gray-500">No Data for {selectedSymbol}</div>;
                        })()
                    ) : (
                        <div className="text-center p-8 bg-gray-800/50 rounded-xl border border-gray-700/50 shadow-2xl">
                            {!replayData ? (
                                <div className="flex flex-col items-center gap-4">
                                    <div className="p-4 bg-cyan-500/10 rounded-full animate-pulse">
                                        <FaFolderOpen className="text-4xl text-cyan-400" />
                                    </div>
                                    <div>
                                        <h2 className="text-2xl font-bold text-white mb-2">Quant Lab Replay</h2>
                                        <p className="text-gray-400 text-sm">Load a backtest recording (.json) to replay the simulation</p>
                                    </div>
                                    <button
                                        onClick={() => fileInputRef.current?.click()}
                                        className="mt-2 px-8 py-3 bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 rounded-lg font-bold text-white shadow-lg transform hover:-translate-y-0.5 transition-all flex items-center gap-3"
                                    >
                                        Select Replay File
                                    </button>
                                    <input type="file" ref={fileInputRef} onChange={loadFile} accept=".json" className="hidden" />
                                </div>
                            ) : (
                                <div className="text-gray-400 animate-in fade-in zoom-in duration-300">
                                    <p className="text-xl font-medium text-cyan-400 mb-2">Ready to Replay</p>
                                    <p>Select a symbol from the Shark Tank Board to begin viewing</p>
                                </div>
                            )}
                        </div>
                    )}

                    {/* Overlay Info */}
                    {replayData && currentSnapshot && (
                        <div className="absolute top-4 left-4 pointer-events-none z-20">
                            <div className="bg-black/80 backdrop-blur-sm p-3 rounded-lg font-mono text-sm border border-gray-700/50 shadow-xl">
                                <div className="flex items-center gap-3 mb-1">
                                    <div className={`w-2 h-2 rounded-full ${isPlaying ? 'bg-green-500 animate-pulse' : 'bg-yellow-500'}`} />
                                    <span className="text-gray-400 uppercase text-xs font-bold tracking-wider">Simulation Time</span>
                                </div>
                                <div className="text-xl font-bold text-gray-100">{currentSnapshot.timestamp}</div>
                                <div className="text-xs text-gray-500 mt-1">Step: <span className="text-cyan-400">{currentIndex}</span> / {replayData.snapshots.length}</div>
                            </div>
                        </div>
                    )}
                </div>

                {/* Bottom Controls */}
                <div className="h-24 bg-gray-900 border-t border-gray-800 p-4 flex items-center gap-6">
                    <button
                        onClick={() => setIsPlaying(!isPlaying)}
                        className="w-12 h-12 rounded-full bg-cyan-600 hover:bg-cyan-500 flex items-center justify-center text-xl transition-all shadow-lg"
                        disabled={!replayData}
                    >
                        {isPlaying ? <FaPause /> : <FaPlay className="ml-1" />}
                    </button>

                    <div className="flex flex-col flex-1 gap-2">
                        <input
                            type="range"
                            min="0"
                            max={replayData ? replayData.snapshots.length - 1 : 100}
                            value={currentIndex}
                            onChange={(e) => { setIsPlaying(false); setCurrentIndex(parseInt(e.target.value)); }}
                            className="w-full h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer accent-cyan-500"
                            disabled={!replayData}
                        />
                        <div className="flex justify-between text-xs text-gray-500 font-mono">
                            <span>{replayData ? replayData.snapshots[0].timestamp : '00:00'}</span>
                            <span>{currentSnapshot ? currentSnapshot.timestamp : '--:--'}</span>
                            <span>{replayData ? replayData.snapshots[replayData.snapshots.length - 1].timestamp : 'End'}</span>
                        </div>
                    </div>

                    <div className="flex items-center gap-2 bg-gray-800 p-2 rounded-lg">
                        <div className="text-xs text-gray-400 font-bold px-2">SPEED</div>
                        {[1, 5, 10, 50].map(s => (
                            <button key={s} onClick={() => setSpeed(s)} className={`px-3 py-1 rounded text-xs font-bold ${speed === s ? 'bg-cyan-600' : 'bg-gray-700'}`}>{s}x</button>
                        ))}
                    </div>
                </div>
            </div>

            {/* RIGHT: Shark Tank Board */}
            <div className="w-[400px] h-full bg-gray-900 border-l border-gray-800 flex flex-col">
                <div className="p-4 border-b border-gray-800">
                    <h3 className="text-lg font-bold text-cyan-400">Simulated Symbols</h3>
                    <div className="flex flex-wrap gap-2 mt-2 max-h-32 overflow-y-auto">
                        {replayData?.symbols.map(sym => (
                            <button
                                key={sym}
                                onClick={() => setSelectedSymbol(sym)}
                                className={`text-xs px-2 py-1 rounded border ${selectedSymbol === sym ? 'bg-cyan-900 border-cyan-500 text-cyan-300' : 'bg-gray-800 border-gray-700 text-gray-400'}`}
                            >
                                {sym}
                            </button>
                        ))}
                    </div>
                </div>
                <div className="flex-1 overflow-hidden">
                    <SharkTankBoard snapshot={currentSnapshot} className="h-full border-none" />
                </div>
            </div>
        </div>
    );
};

export default BacktestPlayer;
