/**
 * useBreakpoint Hook - Access breakpoint context
 * SOTA: Binance UI Refined 2025
 *
 * Returns current breakpoint state and responsive utility
 * Must be used within BreakpointProvider
 */

import { useContext } from 'react';
import { BreakpointContext, BreakpointContextValue } from '../providers/BreakpointProvider';

/**
 * Hook to access breakpoint state and responsive utility
 *
 * @returns BreakpointContextValue containing:
 * - width: Current viewport width
 * - height: Current viewport height
 * - deviceType: 'mobile' | 'tablet' | 'desktop'
 * - isMobile: true if mobile breakpoint
 * - isTablet: true if tablet breakpoint
 * - isDesktop: true if desktop breakpoint
 * - isTouch: true if touch device
 * - platform: 'android' | 'ios' | 'desktop'
 * - responsive: Utility function for responsive values
 *
 * @throws Error if used outside BreakpointProvider
 *
 * @example
 * const { isMobile, responsive } = useBreakpoint();
 *
 * return (
 *   <div style={{
 *     padding: responsive(12, 16, 24),
 *     fontSize: responsive(14, 13, 12),
 *   }}>
 *     {isMobile ? <MobileView /> : <DesktopView />}
 *   </div>
 * );
 */
export const useBreakpoint = (): BreakpointContextValue => {
  const context = useContext(BreakpointContext);

  if (!context) {
    throw new Error(
      'useBreakpoint must be used within a BreakpointProvider. ' +
      'Wrap your app with <BreakpointProvider> in App.tsx or main.tsx'
    );
  }

  return context;
};

/**
 * Hook to check if current device is mobile
 * Convenience wrapper for common use case
 *
 * @returns boolean - true if mobile breakpoint
 *
 * @example
 * const isMobile = useIsMobile();
 * if (isMobile) {
 *   return <MobileComponent />;
 * }
 */
export const useIsMobile = (): boolean => {
  const { isMobile } = useBreakpoint();
  return isMobile;
};

/**
 * Hook to check if current device is tablet
 *
 * @returns boolean - true if tablet breakpoint
 */
export const useIsTablet = (): boolean => {
  const { isTablet } = useBreakpoint();
  return isTablet;
};

/**
 * Hook to check if current device is desktop
 *
 * @returns boolean - true if desktop breakpoint
 */
export const useIsDesktop = (): boolean => {
  const { isDesktop } = useBreakpoint();
  return isDesktop;
};

/**
 * Hook to get responsive value selector
 *
 * @returns responsive function
 *
 * @example
 * const responsive = useResponsive();
 * const padding = responsive(12, 16, 24);
 */
export const useResponsive = () => {
  const { responsive } = useBreakpoint();
  return responsive;
};

export default useBreakpoint;
