/**
 * HeaderNavigation - Desktop/Tablet header with tab navigation
 * SOTA: Binance UI Refined 2025
 *
 * Features:
 * - Horizontal tabs for desktop/tablet
 * - Logo + branding
 * - Environment indicator
 * - Connection status
 */

import React from 'react';
import { Zap, TestTube, Circle } from 'lucide-react';
import { THEME } from '../../styles/theme';
import { Tab } from '../../layouts/AdaptiveLayout';

interface TabConfig {
  id: Tab;
  label: string;
}

const TABS: TabConfig[] = [
  { id: 'chart', label: 'Chart' },
  { id: 'portfolio', label: 'Portfolio' },
  { id: 'backtest', label: 'Quant Lab' },
  { id: 'history', label: 'History' },
  { id: 'settings', label: 'Settings' },
];

interface HeaderNavigationProps {
  activeTab: Tab;
  onTabChange: (tab: Tab) => void;
}

/**
 * HeaderNavigation Component
 * Desktop/Tablet header with horizontal tabs
 */
export const HeaderNavigation: React.FC<HeaderNavigationProps> = ({
  activeTab,
  onTabChange,
}) => {
  // TODO: Get these from context/props
  const currentEnv = 'paper' as 'paper' | 'testnet' | 'live';
  const isConnected = true;
  const virtualBalance = 10000;

  return (
    <header style={{
      height: 48,
      flexShrink: 0,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '0 16px',
      backgroundColor: THEME.bg.tertiary,
      borderBottom: `1px solid ${THEME.border.primary}`,
    }}>
      {/* Left: Logo + Tabs */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 32 }}>
        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{
            fontWeight: 700,
            fontSize: 20,
            letterSpacing: '-0.05em',
            color: THEME.accent.yellow,
          }}>
            Hinto
          </span>
          <span style={{
            fontSize: 10,
            textTransform: 'uppercase',
            fontWeight: 700,
            letterSpacing: '0.1em',
            padding: '2px 6px',
            borderRadius: 4,
            border: `1px solid ${THEME.border.primary}`,
            color: THEME.text.secondary,
          }}>
            Pro
          </span>

          {/* Environment Badge */}
          <span style={{
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            fontSize: 10,
            textTransform: 'uppercase',
            fontWeight: 700,
            letterSpacing: '0.1em',
            padding: '3px 8px',
            borderRadius: 4,
            backgroundColor: currentEnv === 'live' ? 'rgba(239, 68, 68, 0.15)'
              : currentEnv === 'testnet' ? 'rgba(245, 158, 11, 0.15)'
                : 'rgba(34, 197, 94, 0.15)',
            border: currentEnv === 'live' ? '1px solid #ef4444'
              : currentEnv === 'testnet' ? '1px solid #f59e0b'
                : '1px solid #22c55e',
            color: currentEnv === 'live' ? '#ef4444'
              : currentEnv === 'testnet' ? '#f59e0b'
                : '#22c55e',
          }}>
            {currentEnv === 'live' ? (
              <><Zap size={10} fill="currentColor" /> LIVE</>
            ) : currentEnv === 'testnet' ? (
              <><TestTube size={10} /> TESTNET</>
            ) : (
              <><Circle size={8} fill="currentColor" /> PAPER</>
            )}
          </span>
        </div>

        {/* Navigation Tabs */}
        <nav style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          {TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => onTabChange(tab.id)}
              style={{
                padding: '6px 12px',
                fontSize: 14,
                fontWeight: 500,
                borderRadius: 6,
                border: 'none',
                cursor: 'pointer',
                transition: 'all 0.2s',
                backgroundColor: activeTab === tab.id ? THEME.border.primary : 'transparent',
                color: activeTab === tab.id ? THEME.accent.yellow : THEME.text.secondary,
              }}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Right: Balance + Status */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        {/* Balance */}
        <div style={{ textAlign: 'right' }}>
          <div style={{
            fontSize: 10,
            textTransform: 'uppercase',
            fontWeight: 700,
            color: THEME.text.tertiary,
          }}>
            Virtual Balance
          </div>
          <div style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontWeight: 700,
            color: THEME.status.buy,
          }}>
            {new Intl.NumberFormat('en-US', {
              style: 'currency',
              currency: 'USD',
            }).format(virtualBalance)}
          </div>
        </div>

        {/* Divider */}
        <div style={{
          height: 32,
          width: 1,
          backgroundColor: THEME.border.primary,
        }} />

        {/* Connection Status */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            backgroundColor: isConnected ? THEME.status.buy : THEME.status.sell,
            boxShadow: isConnected ? `0 0 8px ${THEME.status.buy}` : 'none',
          }} />
          <span style={{
            fontSize: 12,
            fontWeight: 700,
            letterSpacing: '0.05em',
            color: isConnected ? THEME.status.buy : THEME.status.sell,
          }}>
            {isConnected ? 'LIVE' : 'OFF'}
          </span>
        </div>
      </div>
    </header>
  );
};

export default HeaderNavigation;
