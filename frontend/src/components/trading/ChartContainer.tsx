/**
 * ChartContainer - Responsive chart wrapper
 * SOTA: Binance UI Refined 2025 + Material Design 3
 *
 * Features:
 * - Full viewport width on mobile (REQ-6.1)
 * - Pinch-to-zoom on touch devices (REQ-6.2)
 * - Tap for crosshair on mobile, hover on desktop (REQ-6.3)
 * - Responsive timeframe selector (REQ-6.4)
 * - Maintain aspect ratio across breakpoints (REQ-6.5)
 * - GPU-accelerated animations (REQ-10.2)
 */

import React, { useState, useCallback, useMemo } from 'react';
import { useBreakpoint } from '../../hooks/useBreakpoint';
import { useSafeArea } from '../../hooks/useSafeArea';
import CandleChart from '../CandleChart';

type Timeframe = '1m' | '15m' | '1h';

interface ChartContainerProps {
  initialTimeframe?: Timeframe;
  onTimeframeChange?: (tf: Timeframe) => void;
  /** Height override - defaults to responsive calculation */
  height?: string | number;
  /** Show timeframe selector */
  showTimeframeSelector?: boolean;
}

// --- COLORS ---
const COLORS = {
  bgPrimary: 'rgb(24, 26, 32)',
  bgSecondary: 'rgb(30, 35, 41)',
  bgTertiary: 'rgb(43, 49, 57)',
  textPrimary: 'rgb(234, 236, 239)',
  textSecondary: 'rgb(132, 142, 156)',
  textTertiary: 'rgb(94, 102, 115)',
  accent: 'rgb(240, 185, 11)',
};

/**
 * Check if device prefers reduced motion
 */
const prefersReducedMotion = (): boolean => {
  if (typeof window === 'undefined') return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
};

const TIMEFRAMES: { value: Timeframe; label: string }[] = [
  { value: '1m', label: '1m' },
  { value: '15m', label: '15m' },
  { value: '1h', label: '1H' },
];

/**
 * TimeframeSelectorMobile - Horizontal scrollable selector for mobile
 * Uses transform for smooth button state transitions (REQ-10.2)
 */
const TimeframeSelectorMobile: React.FC<{
  value: Timeframe;
  onChange: (tf: Timeframe) => void;
}> = ({ value, onChange }) => {
  const reducedMotion = prefersReducedMotion();
  const transitionDuration = reducedMotion ? '0.1s' : '0.2s';

  return (
    <div style={{
      display: 'flex',
      gap: 8,
      padding: '8px 12px',
      overflowX: 'auto',
      WebkitOverflowScrolling: 'touch',
      scrollbarWidth: 'none',
      msOverflowStyle: 'none',
    }}>
      {TIMEFRAMES.map(tf => (
        <button
          key={tf.value}
          onClick={() => onChange(tf.value)}
          style={{
            padding: '8px 16px',
            minWidth: 48,
            minHeight: 36,
            fontSize: 13,
            fontWeight: value === tf.value ? 700 : 500,
            color: value === tf.value ? COLORS.accent : COLORS.textSecondary,
            background: value === tf.value ? `${COLORS.accent}15` : 'transparent',
            border: `1px solid ${value === tf.value ? COLORS.accent : COLORS.bgTertiary}`,
            borderRadius: 6,
            cursor: 'pointer',
            // GPU-accelerated transitions using transform and opacity
            transition: `color ${transitionDuration} ease, background ${transitionDuration} ease, border-color ${transitionDuration} ease, transform ${transitionDuration} ease`,
            transform: value === tf.value ? 'scale(1)' : 'scale(0.98)',
            whiteSpace: 'nowrap',
            // Prevent layout shift
            willChange: 'transform',
          }}
        >
          {tf.label}
        </button>
      ))}
    </div>
  );
};

/**
 * TimeframeSelectorDesktop - Compact tabs for desktop
 * Uses transform for smooth button state transitions (REQ-10.2)
 */
const TimeframeSelectorDesktop: React.FC<{
  value: Timeframe;
  onChange: (tf: Timeframe) => void;
}> = ({ value, onChange }) => {
  const reducedMotion = prefersReducedMotion();
  const transitionDuration = reducedMotion ? '0.05s' : '0.15s';

  return (
    <div style={{
      display: 'flex',
      gap: 4,
      padding: '4px 8px',
      background: COLORS.bgSecondary,
      borderRadius: 4,
    }}>
      {TIMEFRAMES.map(tf => (
        <button
          key={tf.value}
          onClick={() => onChange(tf.value)}
          style={{
            padding: '4px 10px',
            fontSize: 11,
            fontWeight: value === tf.value ? 600 : 400,
            color: value === tf.value ? COLORS.textPrimary : COLORS.textTertiary,
            background: value === tf.value ? COLORS.bgTertiary : 'transparent',
            border: 'none',
            borderRadius: 3,
            cursor: 'pointer',
            // GPU-accelerated transitions
            transition: `color ${transitionDuration} ease, background ${transitionDuration} ease`,
          }}
        >
          {tf.label}
        </button>
      ))}
    </div>
  );
};


/**
 * ChartContainer - Main component
 * Responsive wrapper for CandleChart with touch optimizations
 */
export const ChartContainer: React.FC<ChartContainerProps> = ({
  initialTimeframe = '15m',
  onTimeframeChange,
  height,
  showTimeframeSelector = true,
}) => {
  const { isMobile, isTouch } = useBreakpoint();
  const safeArea = useSafeArea();

  const [timeframe, setTimeframe] = useState<Timeframe>(initialTimeframe);

  /**
   * Handle timeframe change
   */
  const handleTimeframeChange = useCallback((tf: Timeframe) => {
    setTimeframe(tf);
    onTimeframeChange?.(tf);
  }, [onTimeframeChange]);

  /**
   * Calculate chart height based on device
   * Mobile: Full screen minus nav (56px) and header (48px)
   * Desktop: Fill available space
   */
  const chartHeight = useMemo(() => {
    if (height) return height;

    if (isMobile) {
      // Full viewport minus bottom nav (56px), header (48px), timeframe selector (44px), safe areas
      const mobileHeight = `calc(100vh - 56px - 48px - ${showTimeframeSelector ? 44 : 0}px - ${safeArea.top}px - ${safeArea.bottom}px)`;
      return mobileHeight;
    }

    // Desktop: fill container
    return '100%';
  }, [height, isMobile, safeArea, showTimeframeSelector]);

  /**
   * Container styles based on device
   */
  const containerStyle: React.CSSProperties = useMemo(() => ({
    display: 'flex',
    flexDirection: 'column',
    height: isMobile ? '100%' : '100%',
    width: '100%',
    background: COLORS.bgPrimary,
    borderRadius: isMobile ? 0 : 8,
    overflow: 'hidden',
  }), [isMobile]);

  return (
    <div style={containerStyle}>
      {/* Timeframe Selector */}
      {showTimeframeSelector && (
        <div style={{
          borderBottom: `1px solid ${COLORS.bgTertiary}`,
          background: COLORS.bgPrimary,
        }}>
          {isMobile ? (
            <TimeframeSelectorMobile
              value={timeframe}
              onChange={handleTimeframeChange}
            />
          ) : (
            <TimeframeSelectorDesktop
              value={timeframe}
              onChange={handleTimeframeChange}
            />
          )}
        </div>
      )}

      {/* Chart */}
      <div style={{
        flex: 1,
        minHeight: 0, // Important for flex child to shrink
        height: chartHeight,
        position: 'relative',
        // Touch optimizations
        touchAction: isTouch ? 'pan-x pan-y pinch-zoom' : 'auto',
      }}>
        <CandleChart
          timeframe={timeframe}
          onTimeframeChange={handleTimeframeChange}
        />

        {/* Mobile touch hint overlay - shows briefly on first load */}
        {isMobile && (
          <MobileTouchHint />
        )}
      </div>
    </div>
  );
};

/**
 * MobileTouchHint - Brief overlay showing touch gestures
 * Only shows once per session
 * Uses opacity and transform for GPU-accelerated fade (REQ-10.2)
 */
const MobileTouchHint: React.FC = () => {
  const [show, setShow] = React.useState(() => {
    // Check if hint was already shown this session
    if (typeof sessionStorage !== 'undefined') {
      return !sessionStorage.getItem('chartHintShown');
    }
    return true;
  });

  const [visible, setVisible] = React.useState(false);

  React.useEffect(() => {
    if (show) {
      // Trigger fade in
      requestAnimationFrame(() => setVisible(true));

      const timer = setTimeout(() => {
        setVisible(false);
        // Wait for fade out animation before removing
        setTimeout(() => {
          setShow(false);
          if (typeof sessionStorage !== 'undefined') {
            sessionStorage.setItem('chartHintShown', 'true');
          }
        }, 300);
      }, 3000);
      return () => clearTimeout(timer);
    }
  }, [show]);

  if (!show) return null;

  const reducedMotion = prefersReducedMotion();

  return (
    <div style={{
      position: 'absolute',
      bottom: 16,
      left: '50%',
      padding: '8px 16px',
      background: 'rgba(0, 0, 0, 0.8)',
      borderRadius: 8,
      fontSize: 12,
      color: COLORS.textSecondary,
      display: 'flex',
      alignItems: 'center',
      gap: 12,
      pointerEvents: 'none',
      // GPU-accelerated animation using transform and opacity
      transform: visible ? 'translateX(-50%) translateY(0)' : 'translateX(-50%) translateY(10px)',
      opacity: visible ? 1 : 0,
      transition: reducedMotion
        ? 'opacity 0.1s ease'
        : 'opacity 0.3s ease, transform 0.3s ease',
      willChange: 'opacity, transform',
    }}>
      <span>👆 Tap for crosshair</span>
      <span>🤏 Pinch to zoom</span>
    </div>
  );
};

export default ChartContainer;
