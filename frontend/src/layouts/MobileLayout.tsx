/**
 * MobileLayout - Single column layout for mobile devices
 * SOTA: Binance UI Refined 2025 + Material Design 3 Expressive
 *
 * Features:
 * - Single column, full-width content
 * - Bottom navigation (5 tabs)
 * - Safe area handling for notch/navigation bar
 * - Compact header
 * - Scroll position preservation per tab (REQ-10.5)
 */

import React, { ReactNode, useRef } from 'react';
import { useSafeArea } from '../hooks/useSafeArea';
import { useTabScrollPosition } from '../hooks/useScrollPosition';
import { BottomNavigation, MobileHeader } from '../components/navigation';
import { THEME } from '../styles/theme';
import { Tab } from './AdaptiveLayout';

export interface MobileLayoutProps {
  children: ReactNode;
  activeTab: Tab;
  onTabChange: (tab: Tab) => void;
}

/**
 * MobileLayout Component
 * Single-column layout with bottom navigation
 */
export const MobileLayout: React.FC<MobileLayoutProps> = ({
  children,
  activeTab,
  onTabChange,
}) => {
  const safeArea = useSafeArea();
  const mainContentRef = useRef<HTMLElement>(null);

  // Preserve scroll position per tab (REQ-10.5)
  useTabScrollPosition(activeTab, mainContentRef);

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
      {/* Safe area top padding for notch */}
      {safeArea.top > 0 && (
        <div style={{
          height: safeArea.top,
          backgroundColor: THEME.bg.secondary,
          flexShrink: 0,
        }} />
      )}

      {/* Compact Mobile Header */}
      <MobileHeader />

      {/* Main Content - Scrollable with scroll position preservation */}
      <main
        ref={mainContentRef}
        style={{
          flex: 1,
          overflow: 'auto',
          paddingBottom: 'calc(60px + env(safe-area-inset-bottom))',
          WebkitOverflowScrolling: 'touch', // Smooth scrolling on iOS
        }}
      >
        {children}
      </main>

      {/* Bottom Navigation */}
      <BottomNavigation
        activeTab={activeTab as any}
        onTabChange={onTabChange}
      />
    </div>
  );
};

export default MobileLayout;
