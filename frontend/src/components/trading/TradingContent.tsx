/**
 * TradingContent - Content component for trading views
 * SOTA: Binance UI Refined 2025
 *
 * This component renders the main trading content (chart, ticker, panels)
 * and is used by both MobileLayout and DesktopLayout.
 *
 * It receives all necessary props from the parent App component.
 */

import React from 'react';
import { THEME } from '../../styles/theme';
import { useBreakpoint } from '../../hooks/useBreakpoint';
import CandleChart from '../CandleChart';
import TokenIcon from '../TokenIcon';
import SignalCard, { TradingSignal } from '../SignalCard';
import ErrorBoundary from '../ErrorBoundary';


// Design tokens
const C = {
    up: THEME.status.buy,
    down: THEME.status.sell,
    yellow: THEME.accent.yellow,
    bg: THEME.bg.primary,
    card: THEME.bg.tertiary,
    sidebar: THEME.bg.primary,
    border: THEME.border.primary,
    text1: THEME.text.primary,
    text2: THEME.text.secondary,
    text3: THEME.text.tertiary,
};

interface MarketData {
    close: number;
    high: number;
    low: number;
    vwap?: number;
    change_percent?: number;
}



export interface TradingContentProps {
    selectedSymbol: string;
    selectedTimeframe: '1m' | '15m' | '1h';
    onTimeframeChange: (tf: '1m' | '15m' | '1h') => void;
    marketData: MarketData | null;
    activeSignal: TradingSignal | null;
    onExecuteSignal: () => void;
    onDismissSignal: () => void;
    // Format helpers
    formatPrice: (price: number) => string;
}

/**
 * TradingContent Component
 * Renders chart + ticker bar + sidebars for desktop, simplified for mobile
 */
export const TradingContent: React.FC<TradingContentProps> = ({
    selectedSymbol,
    selectedTimeframe,
    onTimeframeChange,
    marketData,
    activeSignal,
    onExecuteSignal,
    onDismissSignal,
    formatPrice,
}) => {
    const { isMobile } = useBreakpoint();

    const priceColor = marketData?.change_percent && marketData.change_percent >= 0
        ? C.up : C.down;

    // Simplified layout for mobile
    if (isMobile) {
        return (
            <div style={{
                display: 'flex',
                flexDirection: 'column',
                height: '100%',
                overflow: 'hidden',
            }}>
                {/* Mobile Ticker Bar */}
                <div style={{
                    height: '36px',
                    flexShrink: 0,
                    display: 'flex',
                    alignItems: 'center',
                    padding: '0 12px',
                    gap: '12px',
                    fontSize: '12px',
                    backgroundColor: C.card,
                    borderBottom: `1px solid ${C.border}`,
                }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <TokenIcon symbol={selectedSymbol.replace('usdt', '').toUpperCase()} size={20} />
                        <span style={{ fontWeight: 700, color: C.text1, fontSize: '14px' }}>
                            {selectedSymbol.replace('usdt', '/USDT').toUpperCase()}
                        </span>
                    </div>
                    <div style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 700, color: priceColor, fontSize: '16px' }}>
                        ${marketData ? formatPrice(marketData.close) : '---'}
                    </div>
                    <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: '12px', color: priceColor }}>
                        {marketData?.change_percent !== undefined
                            ? `${marketData.change_percent >= 0 ? '+' : ''}${marketData.change_percent.toFixed(2)}%`
                            : '---'}
                    </div>
                </div>

                {/* Mobile Chart - Full width */}
                <div style={{ flex: 1, overflow: 'hidden', minHeight: 0 }}>
                    <ErrorBoundary>
                        <CandleChart
                            timeframe={selectedTimeframe}
                            onTimeframeChange={onTimeframeChange}
                        />
                    </ErrorBoundary>
                </div>

                {/* Mobile Signal Card (if active) */}
                {activeSignal && (
                    <div style={{
                        position: 'absolute',
                        bottom: 56 + 12, // Above bottom nav
                        left: 12,
                        right: 12,
                        zIndex: 100,
                    }}>
                        <SignalCard
                            signal={activeSignal}
                            currentPrice={marketData?.close || 0}
                            onExecute={onExecuteSignal}
                            onDismiss={onDismissSignal}
                        />
                    </div>
                )}
            </div>
        );
    }

    // Desktop layout - return null (handled by App.tsx for now)
    // This allows progressive migration
    return null;
};

export default TradingContent;
