/**
 * TabletLayout - 2-column layout for tablet devices
 * SOTA: Binance UI Refined 2025
 *
 * Features:
 * - 2-column layout: main content + collapsible panel
 * - Header navigation (tabs)
 * - Collapsible side panel
 */

import React, { ReactNode, useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { HeaderNavigation } from '../components/navigation/HeaderNavigation';
import { THEME } from '../styles/theme';
import { Tab } from './AdaptiveLayout';

export interface TabletLayoutProps {
  children: ReactNode;
  activeTab: Tab;
  onTabChange: (tab: Tab) => void;
}

/**
 * TabletLayout Component
 * 2-column layout with collapsible panel
 */
export const TabletLayout: React.FC<TabletLayoutProps> = ({
  children,
  activeTab,
  onTabChange,
}) => {
  const [isPanelCollapsed, setIsPanelCollapsed] = useState(false);

  const panelWidth = isPanelCollapsed ? 48 : 280;

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
      <div style={{
        flex: 1,
        display: 'flex',
        overflow: 'hidden',
      }}>
        {/* Main Content */}
        <main style={{
          flex: 1,
          overflow: 'auto',
          minWidth: 0,
        }}>
          {children}
        </main>

        {/* Collapsible Side Panel */}
        <aside style={{
          width: panelWidth,
          flexShrink: 0,
          display: 'flex',
          flexDirection: 'column',
          backgroundColor: THEME.bg.secondary,
          borderLeft: `1px solid ${THEME.border.primary}`,
          transition: 'width 0.2s ease',
          overflow: 'hidden',
        }}>
          {/* Collapse Toggle */}
          <button
            onClick={() => setIsPanelCollapsed(!isPanelCollapsed)}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              height: 40,
              backgroundColor: 'transparent',
              border: 'none',
              borderBottom: `1px solid ${THEME.border.primary}`,
              color: THEME.text.secondary,
              cursor: 'pointer',
            }}
          >
            {isPanelCollapsed ? (
              <ChevronLeft size={20} />
            ) : (
              <ChevronRight size={20} />
            )}
          </button>

          {/* Panel Content */}
          {!isPanelCollapsed && (
            <div style={{
              flex: 1,
              overflow: 'auto',
              padding: 12,
            }}>
              {/* Panel content will be rendered here based on context */}
              <div style={{
                fontSize: 12,
                color: THEME.text.tertiary,
                textAlign: 'center',
                padding: 16,
              }}>
                Side Panel
              </div>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
};

export default TabletLayout;
