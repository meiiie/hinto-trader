/**
 * DesktopLayout - 3-column layout for desktop devices
 * SOTA: Binance UI Refined 2025
 *
 * Features:
 * - 3-column layout: sidebar + main content + panel
 * - Header navigation
 * - Full trading interface
 *
 * This layout preserves the existing App.tsx desktop layout structure
 */

import React, { ReactNode } from 'react';
import { HeaderNavigation } from '../components/navigation/HeaderNavigation';
import { THEME } from '../styles/theme';
import { Tab } from './AdaptiveLayout';

export interface DesktopLayoutProps {
  children: ReactNode;
  activeTab: Tab;
  onTabChange: (tab: Tab) => void;
}

/**
 * DesktopLayout Component
 * 3-column layout with full trading interface
 */
export const DesktopLayout: React.FC<DesktopLayoutProps> = ({
  children,
  activeTab,
  onTabChange,
}) => {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100vh',
      width: '100%',
      backgroundColor: THEME.bg.primary,
      color: THEME.text.primary,
      overflow: 'hidden',
    }}>
      {/* Header with Navigation */}
      <HeaderNavigation
        activeTab={activeTab}
        onTabChange={onTabChange}
      />

      {/* Main Content Area */}
      <main style={{
        flex: 1,
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
      }}>
        {children}
      </main>
    </div>
  );
};

export default DesktopLayout;
