/**
 * MobileHeader - Compact header for mobile layout
 * SOTA: Binance UI Refined 2026
 *
 * Features:
 * - Compact height (48px)
 * - Symbol + price info (like Binance app)
 * - Token search button
 * - Environment badge
 * - Connection status indicator
 */

import React from 'react';
import { Zap, TestTube, Circle, Wifi, WifiOff, ChevronDown } from 'lucide-react';
import { THEME, formatPrice } from '../../styles/theme';
import { UnlockAccessButton } from '../UnlockAccessButton';

export interface MobileHeaderProps {
  currentEnv?: 'paper' | 'testnet' | 'live';
  isConnected?: boolean;
  symbol?: string;
  price?: number;
  priceChange?: number;
  onTokenSearch?: () => void;  // Callback to open token selector
}

/**
 * MobileHeader Component
 * Compact header for mobile devices with symbol + price
 */
export const MobileHeader: React.FC<MobileHeaderProps> = ({
  currentEnv = 'paper',
  isConnected = true,
  symbol = 'BTCUSDT',
  price,
  priceChange,
  onTokenSearch,
}) => {
  const priceColor = priceChange && priceChange >= 0 ? THEME.status.buy : THEME.status.sell;

  // Local formatPrice removed in favor of centralized theme utility

  return (
    <header style={{
      height: 48,
      flexShrink: 0,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '0 12px',
      backgroundColor: THEME.bg.secondary,
      borderBottom: `1px solid ${THEME.border.primary}`,
    }}>
      {/* Left: Symbol + Price (Binance style) - Clickable for token search */}
      <div
        onClick={onTokenSearch}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          cursor: onTokenSearch ? 'pointer' : 'default',
        }}
      >
        <span style={{
          fontWeight: 700,
          fontSize: 15,
          color: THEME.text.primary,
        }}>
          {symbol.replace('USDT', '/USDT')}
        </span>
        {/* Dropdown indicator for token search */}
        {onTokenSearch && (
          <ChevronDown size={14} color={THEME.text.tertiary} />
        )}
        {price && (
          <span style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontWeight: 600,
            fontSize: 13,
            color: priceColor,
            marginLeft: 4,
          }}>
            ${formatPrice(price)}
          </span>
        )}
        {priceChange !== undefined && (
          <span style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 10,
            color: priceColor,
            fontWeight: 500,
          }}>
            {priceChange >= 0 ? '+' : ''}{priceChange.toFixed(2)}%
          </span>
        )}
      </div>

      {/* Right: Unlock + Environment + Connection Status */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        {/* Unlock Access Button (IP Update) */}
        <UnlockAccessButton compact />

        {/* Environment Badge */}
        <span style={{
          display: 'flex',
          alignItems: 'center',
          gap: 3,
          fontSize: 9,
          textTransform: 'uppercase',
          fontWeight: 700,
          letterSpacing: '0.05em',
          padding: '2px 5px',
          borderRadius: 3,
          backgroundColor: currentEnv === 'live' ? 'rgba(239, 68, 68, 0.15)'
            : currentEnv === 'testnet' ? 'rgba(245, 158, 11, 0.15)'
              : 'rgba(34, 197, 94, 0.15)',
          color: currentEnv === 'live' ? '#ef4444'
            : currentEnv === 'testnet' ? '#f59e0b'
              : '#22c55e',
        }}>
          {currentEnv === 'live' ? (
            <><Zap size={8} fill="currentColor" /> LIVE</>
          ) : currentEnv === 'testnet' ? (
            <><TestTube size={8} /> TEST</>
          ) : (
            <><Circle size={6} fill="currentColor" /> PAPER</>
          )}
        </span>

        {/* Connection Status */}
        {isConnected ? (
          <Wifi size={14} color={THEME.status.buy} />
        ) : (
          <WifiOff size={14} color={THEME.status.sell} />
        )}
      </div>
    </header>
  );
};

export default MobileHeader;
