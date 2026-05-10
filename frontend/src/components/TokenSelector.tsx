/**
 * TokenSelector Component - Multi-Token Dropdown
 *
 * SOTA Pattern: Dropdown for selecting active trading token
 * Fetches available tokens from GET /market/symbols
 * Uses Zustand store for global state management
 */

import { useState, useEffect, useRef } from 'react';
import { TokenIcon } from './TokenIcon';
import { useMarketStore, useActiveSymbol } from '../stores/marketStore';
import { API_BASE_URL } from '../config/api';

interface SymbolInfo {
    symbol: string;
    display: string;
    base: string;
    quote: string;
    name: string;
}

interface SymbolsResponse {
    symbols: SymbolInfo[];
    count: number;
    default: string;
}

export const TokenSelector = () => {
    // SOTA: Use Zustand store instead of Context
    const selectedSymbol = useActiveSymbol();
    const setActiveSymbol = useMarketStore((state) => state.setActiveSymbol);
    const setAvailableSymbols = useMarketStore((state) => state.setAvailableSymbols);
    const clearSymbolData = useMarketStore((state) => state.clearSymbolData);

    const [symbols, setSymbols] = useState<SymbolInfo[]>([]);
    const [fullSymbolList, setFullSymbolList] = useState<SymbolInfo[]>([]);  // SOTA: Keep full list for filtering
    const [isOpen, setIsOpen] = useState(false);
    const [isLoading, setIsLoading] = useState(true);
    const dropdownRef = useRef<HTMLDivElement>(null);

    // Fetch available symbols from backend
    useEffect(() => {
        const fetchSymbols = async () => {
            try {
                const response = await fetch(`${API_BASE_URL}/market/symbols`);
                const data: SymbolsResponse = await response.json();

                // Sort alphabetically by Base symbol
                const sorted = data.symbols.sort((a, b) => a.base.localeCompare(b.base));

                setSymbols(sorted);
                setFullSymbolList(sorted);

                // SOTA: Update store with available symbols
                setAvailableSymbols(data.symbols.map(s => s.symbol));

                // Set default if not already set
                if (!selectedSymbol && data.default) {
                    setActiveSymbol(data.default);
                }
            } catch (error) {
                console.error('Failed to fetch symbols:', error);
                // Fallback to default
                setSymbols([
                    { symbol: 'btcusdt', display: 'BTCUSDT', base: 'BTC', quote: 'USDT', name: 'Bitcoin' },
                    { symbol: 'ethusdt', display: 'ETHUSDT', base: 'ETH', quote: 'USDT', name: 'Ethereum' },
                ]);
            } finally {
                setIsLoading(false);
            }
        };

        fetchSymbols();
    }, [selectedSymbol, setActiveSymbol, setAvailableSymbols]);

    // Close dropdown when clicking outside
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
                setIsOpen(false);
            }
        };

        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    const currentSymbol = symbols.find(s => s.symbol === selectedSymbol) || symbols[0];

    const handleSelect = (symbol: string) => {
        // SOTA FIX: Clear data for NEW symbol to ensure fresh history load
        // This prevents "Cannot update oldest data" error by removing any stale state
        clearSymbolData(symbol);

        setActiveSymbol(symbol);
        setIsOpen(false);
    };

    if (isLoading) {
        return (
            <div className="token-selector loading">
                <div className="spinner" />
            </div>
        );
    }

    return (
        <div className="token-selector" ref={dropdownRef}>
            <button
                className="token-selector-button"
                onClick={() => setIsOpen(!isOpen)}
            >
                {currentSymbol && (
                    <>
                        <TokenIcon symbol={currentSymbol.base} size={20} />
                        <span className="token-base">{currentSymbol.base}</span>
                        <span className="token-name">/{currentSymbol.quote}</span>
                        <svg className={`chevron ${isOpen ? 'open' : ''}`} width="12" height="12" viewBox="0 0 12 12">
                            <path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" strokeWidth="1.5" fill="none" />
                        </svg>
                    </>
                )}
            </button>

            {isOpen && (
                <div className="token-dropdown">
                    {/* SOTA: Search Bar for 50+ Symbols */}
                    <div className="search-container">
                        <svg width="14" height="14" viewBox="0 0 16 16" style={{ opacity: 0.5 }}>
                            <path d="M11.742 10.344a6.5 6.5 0 1 0-1.397 1.398h-.001c.03.04.062.078.098.115l3.85 3.85a1 1 0 0 0 1.415-1.414l-3.85-3.85a1.007 1.007 0 0 0-.115-.1zM12 6.5a5.5 5.5 0 1 1-11 0 5.5 5.5 0 0 1 11 0z" fill="currentColor" />
                        </svg>
                        <input
                            type="text"
                            placeholder="Search token..."
                            className="search-input"
                            autoFocus
                            onChange={(e) => {
                                const term = e.target.value.toLowerCase();
                                const filtered = fullSymbolList.filter((s: SymbolInfo) =>
                                    s.base.toLowerCase().includes(term) ||
                                    s.name.toLowerCase().includes(term)
                                );
                                setSymbols(filtered);
                                // Reset if empty
                                if (!term) setSymbols(fullSymbolList);
                            }}
                        />
                    </div>

                    <div className="token-list">
                        {symbols.map((symbol) => (
                            <button
                                key={symbol.symbol}
                                className={`token-option ${symbol.symbol === selectedSymbol ? 'active' : ''}`}
                                onClick={() => handleSelect(symbol.symbol)}
                            >
                                <TokenIcon symbol={symbol.base} size={20} />
                                <div className="token-info">
                                    <span className="token-base">{symbol.base}</span>
                                    <span className="token-name">{symbol.name}</span>
                                </div>
                                {symbol.symbol === selectedSymbol && (
                                    <svg className="check" width="16" height="16" viewBox="0 0 16 16">
                                        <path d="M3 8L6.5 11.5L13 4.5" stroke="#00C853" strokeWidth="2" fill="none" />
                                    </svg>
                                )}
                            </button>
                        ))}
                        {symbols.length === 0 && (
                            <div className="no-results">No tokens found</div>
                        )}
                    </div>
                </div>
            )}

            <style>{`
                .token-selector {
                    position: relative;
                }

                .token-selector-button {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    padding: 8px 12px;
                    background: rgba(255, 255, 255, 0.05);
                    border: 1px solid rgba(255, 255, 255, 0.1);
                    border-radius: 8px;
                    color: #fff;
                    cursor: pointer;
                    transition: all 0.2s ease;
                }

                .token-selector-button:hover {
                    background: rgba(255, 255, 255, 0.1);
                    border-color: rgba(255, 255, 255, 0.2);
                }

                .token-base {
                    font-weight: 600;
                    font-size: 14px;
                }

                .token-name {
                    color: rgba(255, 255, 255, 0.6);
                    font-size: 13px;
                }

                .chevron {
                    transition: transform 0.2s ease;
                }

                .chevron.open {
                    transform: rotate(180deg);
                }

                .token-dropdown {
                    position: absolute;
                    top: 100%;
                    left: 0;
                    margin-top: 4px;
                    width: 280px;
                    background: #1a1a2e;
                    border: 1px solid rgba(255, 255, 255, 0.1);
                    border-radius: 12px;
                    padding: 8px;
                    z-index: 1000;
                    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.6);
                    backdrop-filter: blur(12px);
                    display: flex;
                    flex-direction: column;
                    gap: 8px;
                }

                .search-container {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    padding: 8px 12px;
                    background: rgba(0, 0, 0, 0.2);
                    border-radius: 8px;
                    margin-bottom: 4px;
                }

                .search-input {
                    background: transparent;
                    border: none;
                    color: #fff;
                    width: 100%;
                    outline: none;
                    font-size: 13px;
                }

                .token-list {
                    max-height: 300px;
                    overflow-y: auto;
                    display: flex;
                    flex-direction: column;
                    gap: 2px;
                }

                .token-list::-webkit-scrollbar {
                    width: 4px;
                }

                .token-list::-webkit-scrollbar-thumb {
                    background: rgba(255, 255, 255, 0.1);
                    border-radius: 2px;
                }

                .token-option {
                    display: flex;
                    align-items: center;
                    gap: 12px;
                    width: 100%;
                    padding: 8px 12px;
                    background: transparent;
                    border: none;
                    border-radius: 8px;
                    color: #fff;
                    cursor: pointer;
                    transition: background 0.15s ease;
                    text-align: left;
                }

                .token-option:hover {
                    background: rgba(255, 255, 255, 0.05);
                }

                .token-option.active {
                    background: rgba(0, 200, 83, 0.15);
                    border: 1px solid rgba(0, 200, 83, 0.2);
                }

                .token-info {
                    display: flex;
                    flex-direction: column;
                    align-items: flex-start;
                    flex: 1;
                }

                .token-info .token-name {
                    font-size: 11px;
                }

                .check {
                    margin-left: auto;
                }

                .no-results {
                    padding: 20px;
                    text-align: center;
                    color: rgba(255, 255, 255, 0.4);
                    font-size: 13px;
                }

                .spinner {
                    width: 20px;
                    height: 20px;
                    border: 2px solid rgba(255, 255, 255, 0.2);
                    border-top-color: #fff;
                    border-radius: 50%;
                    animation: spin 1s linear infinite;
                }

                @keyframes spin {
                    to { transform: rotate(360deg); }
                }
            `}</style>
        </div>
    );
};

export default TokenSelector;
