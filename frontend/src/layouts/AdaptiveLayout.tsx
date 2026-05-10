/**
 * AdaptiveLayout - Layout switcher based on breakpoint
 * SOTA: Binance UI Refined 2025
 *
 * Renders appropriate layout component based on current device type:
 * - Mobile: Single column with bottom navigation
 * - Tablet: 2-column with collapsible panel
 * - Desktop: 3-column full layout
 */

import React, { ReactNode, Suspense } from 'react';
import { useBreakpoint } from '../hooks/useBreakpoint';
import { THEME } from '../styles/theme';
import { MobileLayout } from './MobileLayout';
import { TabletLayout } from './TabletLayout';
import { DesktopLayout } from './DesktopLayout';

// Tab types - shared across layouts
export type Tab = 'home' | 'markets' | 'trade' | 'chart' | 'portfolio' | 'history' | 'settings' | 'backtest' | 'more';

export interface LayoutProps {
  children: ReactNode;
  activeTab: Tab;
  onTabChange: (tab: Tab) => void;
}

interface AdaptiveLayoutProps extends LayoutProps {
  // Additional props for adaptive behavior
}

/**
 * Loading fallback component
 */
const LayoutFallback: React.FC = () => (
  <div style={{
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    height: '100vh',
    backgroundColor: THEME.bg.primary,
    color: THEME.text.secondary,
  }}>
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      gap: 12,
    }}>
      <div style={{
        width: 40,
        height: 40,
        border: `3px solid ${THEME.border.primary}`,
        borderTopColor: THEME.accent.yellow,
        borderRadius: '50%',
        animation: 'spin 1s linear infinite',
      }} />
      <span style={{ fontSize: 14 }}>Loading...</span>
    </div>
    <style>{`
      @keyframes spin {
        to { transform: rotate(360deg); }
      }
    `}</style>
  </div>
);

/**
 * AdaptiveLayout Component
 * Switches between Mobile/Tablet/Desktop layouts based on breakpoint
 */
export const AdaptiveLayout: React.FC<AdaptiveLayoutProps> = ({
  children,
  activeTab,
  onTabChange,
}) => {
  const { isMobile, isTablet, isDesktop } = useBreakpoint();

  // Render appropriate layout based on breakpoint
  // Only one layout is rendered at a time (Property 3: Layout Exclusivity)
  return (
    <Suspense fallback={<LayoutFallback />}>
      {isMobile && (
        <MobileLayout activeTab={activeTab} onTabChange={onTabChange}>
          {children}
        </MobileLayout>
      )}
      {isTablet && (
        <TabletLayout activeTab={activeTab} onTabChange={onTabChange}>
          {children}
        </TabletLayout>
      )}
      {isDesktop && (
        <DesktopLayout activeTab={activeTab} onTabChange={onTabChange}>
          {children}
        </DesktopLayout>
      )}
    </Suspense>
  );
};

export default AdaptiveLayout;
