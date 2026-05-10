/**
 * SymbolContext - Global Selected Symbol State
 *
 * SOTA Pattern: React Context for cross-component symbol state
 *
 * When symbol changes:
 * 1. Chart subscribes to new WebSocket stream
 * 2. Portfolio fetches positions for selected symbol
 * 3. Price ticker updates
 */

import { createContext, useContext, useState, useCallback, ReactNode } from 'react';

interface SymbolContextType {
    selectedSymbol: string;
    setSelectedSymbol: (symbol: string) => void;
}

const SymbolContext = createContext<SymbolContextType | undefined>(undefined);

export const SymbolProvider = ({ children }: { children: ReactNode }) => {
    // Default to BTCUSDT
    const [selectedSymbol, setSelectedSymbolState] = useState<string>('btcusdt');

    const setSelectedSymbol = useCallback((symbol: string) => {
        const lowercaseSymbol = symbol.toLowerCase();
        setSelectedSymbolState(lowercaseSymbol);

        // Optional: Persist to localStorage
        localStorage.setItem('selectedSymbol', lowercaseSymbol);
    }, []);

    // Load from localStorage on mount
    useState(() => {
        const saved = localStorage.getItem('selectedSymbol');
        if (saved) {
            setSelectedSymbolState(saved);
        }
    });

    return (
        <SymbolContext.Provider value={{ selectedSymbol, setSelectedSymbol }}>
            {children}
        </SymbolContext.Provider>
    );
};

export const useSymbol = (): SymbolContextType => {
    const context = useContext(SymbolContext);
    if (context === undefined) {
        throw new Error('useSymbol must be used within a SymbolProvider');
    }
    return context;
};

export default SymbolContext;
