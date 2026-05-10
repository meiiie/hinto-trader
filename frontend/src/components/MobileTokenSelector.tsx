import React, { useState, useEffect, useRef } from 'react';
import { TokenIcon } from './TokenIcon';
import { useMarketStore, useActiveSymbol } from '../stores/marketStore';
import { API_BASE_URL } from '../config/api';
import { X, Search, Check } from 'lucide-react';
import { THEME } from '../styles/theme';

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

interface MobileTokenSelectorProps {
    isOpen: boolean;
    onClose: () => void;
}

export const MobileTokenSelector: React.FC<MobileTokenSelectorProps> = ({ isOpen, onClose }) => {
    const selectedSymbol = useActiveSymbol();
    const setActiveSymbol = useMarketStore((state) => state.setActiveSymbol);
    const setAvailableSymbols = useMarketStore((state) => state.setAvailableSymbols);
    const clearSymbolData = useMarketStore((state) => state.clearSymbolData);

    const [symbols, setSymbols] = useState<SymbolInfo[]>([]);
    const [fullSymbolList, setFullSymbolList] = useState<SymbolInfo[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const inputRef = useRef<HTMLInputElement>(null);

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
                setAvailableSymbols(data.symbols.map(s => s.symbol));
            } catch (error) {
                console.error('Failed to fetch symbols:', error);
                // Fallback
                setSymbols([
                    { symbol: 'btcusdt', display: 'BTCUSDT', base: 'BTC', quote: 'USDT', name: 'Bitcoin' },
                    { symbol: 'ethusdt', display: 'ETHUSDT', base: 'ETH', quote: 'USDT', name: 'Ethereum' },
                ]);
            } finally {
                setIsLoading(false);
            }
        };

        if (isOpen) {
            fetchSymbols();
        }
    }, [isOpen, setAvailableSymbols]);

    // Auto-focus input when opened
    useEffect(() => {
        if (isOpen && inputRef.current) {
            setTimeout(() => inputRef.current?.focus(), 100);
        }
    }, [isOpen]);

    const handleSelect = (symbol: string) => {
        clearSymbolData(symbol);
        setActiveSymbol(symbol);
        onClose();
    };

    if (!isOpen) return null;

    return (
        <div style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: THEME.bg.primary,
            zIndex: 9999, // Highest z-index
            display: 'flex',
            flexDirection: 'column',
        }}>
            {/* Header */}
            <div style={{
                display: 'flex',
                alignItems: 'center',
                padding: '12px 16px',
                borderBottom: `1px solid ${THEME.border.primary}`,
                gap: 12
            }}>
                <div style={{
                    flex: 1,
                    display: 'flex',
                    alignItems: 'center',
                    backgroundColor: THEME.bg.vessel,
                    borderRadius: 8,
                    padding: '8px 12px',
                    border: `1px solid ${THEME.border.input}`
                }}>
                    <Search size={16} color={THEME.text.tertiary} />
                    <input
                        ref={inputRef}
                        type="text"
                        placeholder="Search coin (e.g. BTC, ETH)..."
                        style={{
                            background: 'transparent',
                            border: 'none',
                            color: THEME.text.primary,
                            fontSize: 14,
                            marginLeft: 8,
                            flex: 1,
                            outline: 'none'
                        }}
                        onChange={(e) => {
                            const term = e.target.value.toLowerCase();
                            const filtered = fullSymbolList.filter((s: SymbolInfo) =>
                                s.base.toLowerCase().includes(term) ||
                                s.name.toLowerCase().includes(term)
                            );
                            setSymbols(filtered);
                            if (!term) setSymbols(fullSymbolList);
                        }}
                    />
                </div>
                <button
                    onClick={onClose}
                    style={{
                        background: 'transparent',
                        border: 'none',
                        color: THEME.text.primary,
                        padding: 4,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center'
                    }}
                >
                    <X size={24} />
                </button>
            </div>

            {/* List */}
            <div style={{
                flex: 1,
                overflowY: 'auto',
                WebkitOverflowScrolling: 'touch',
                padding: '8px 0'
            }}>
                {isLoading ? (
                    <div style={{ padding: 20, textAlign: 'center', color: THEME.text.tertiary }}>Loading...</div>
                ) : symbols.length === 0 ? (
                    <div style={{ padding: 20, textAlign: 'center', color: THEME.text.tertiary }}>No results found</div>
                ) : (
                    symbols.map((symbol) => (
                        <div
                            key={symbol.symbol}
                            onClick={() => handleSelect(symbol.symbol)}
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                padding: '12px 16px',
                                borderBottom: `1px solid ${THEME.border.secondary}`,
                                backgroundColor: symbol.symbol === selectedSymbol ? THEME.bg.vessel : 'transparent',
                                cursor: 'pointer'
                            }}
                        >
                            <TokenIcon symbol={symbol.base} size={32} />
                            <div style={{ marginLeft: 12, flex: 1 }}>
                                <div style={{
                                    fontSize: 16,
                                    fontWeight: 700,
                                    color: THEME.text.primary
                                }}>
                                    {symbol.base}
                                    <span style={{ fontSize: 12, color: THEME.text.tertiary, fontWeight: 400, marginLeft: 4 }}>
                                        / {symbol.quote}
                                    </span>
                                </div>
                                <div style={{ fontSize: 12, color: THEME.text.tertiary }}>
                                    {symbol.name}
                                </div>
                            </div>
                            {symbol.symbol === selectedSymbol && (
                                <Check size={20} color={THEME.status.buy} />
                            )}
                        </div>
                    ))
                )}
            </div>
        </div>
    );
};
