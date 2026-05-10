// SOTA Phase 2: Mobile Navigation Component
import React from 'react';
import { THEME } from '../../styles/theme'; // Use centralized theme

// Icons (using Lucide React for consistent UI)
import { BarChart2, LayoutList, History, Settings } from 'lucide-react';

interface BottomNavigationProps {
  activeTab: string;
  onTabChange: (tab: any) => void;
}

/**
 * Bottom Navigation Bar (Mobile Only)
 * - Fixed at bottom
 * - 4 Key Tabs: Chart, Positions (Portfolio), History, Settings
 * - SOTA: Uses CSS env(safe-area-inset-bottom) for iPhone/Android Gesture Bar
 */
const BottomNavigation: React.FC<BottomNavigationProps> = ({ activeTab, onTabChange }) => {
  // Tab definitions
  const tabs = [
    { id: 'chart', label: 'Chart', icon: BarChart2 },
    { id: 'portfolio', label: 'Positions', icon: LayoutList },
    { id: 'history', label: 'History', icon: History },
    { id: 'settings', label: 'Settings', icon: Settings },
  ];

  return (
    <nav style={{
      position: 'fixed',
      bottom: 0,
      left: 0,
      right: 0,
      height: 'auto', // Allow height to grow with padding
      minHeight: '60px',
      backgroundColor: THEME.bg.secondary,
      borderTop: `1px solid ${THEME.border.primary}`,
      display: 'flex',
      justifyContent: 'space-around',
      alignItems: 'center',
      zIndex: 1000,
      // SOTA: Handle Safe Area for iPhone X+ / Android Gestures
      paddingBottom: 'env(safe-area-inset-bottom, 16px)',
      paddingTop: '8px',
    }}>
      {tabs.map((tab) => {
        const isActive = activeTab === tab.id;
        const Icon = tab.icon;
        const activeColor = THEME.accent.yellow;
        const inactiveColor = THEME.text.secondary;

        return (
          <div
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '4px',
              cursor: 'pointer',
              flex: 1,
              opacity: isActive ? 1 : 0.5,
              transition: 'opacity 0.2s',
              paddingBottom: '8px', // Visual balance above safe area
            }}
          >
            <Icon size={20} color={isActive ? activeColor : inactiveColor} />
            <span style={{
              fontSize: '10px',
              fontWeight: isActive ? 600 : 400,
              color: isActive ? activeColor : inactiveColor,
            }}>
              {tab.label}
            </span>
          </div>
        );
      })}
    </nav>
  );
};

export default BottomNavigation;
