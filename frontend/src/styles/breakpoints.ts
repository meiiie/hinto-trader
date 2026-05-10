/**
 * Adaptive UI Breakpoint System
 * SOTA: Binance UI Refined 2025 + Material Design 3 Expressive
 *
 * Breakpoint definitions for responsive layout switching
 * Mobile-first approach with touch-optimized thresholds
 */

// Breakpoint values in pixels
export const BREAKPOINTS = {
  mobile: 0,      // 0 - 767px: Single column, bottom nav
  tablet: 768,    // 768 - 1023px: 2-column, collapsible panel
  desktop: 1024,  // 1024 - 1439px: 3-column, full layout
  wide: 1440,     // 1440px+: Wide desktop with extra space
} as const;

// Device type categories
export type DeviceType = 'mobile' | 'tablet' | 'desktop';

// Platform detection types
export type Platform = 'android' | 'ios' | 'desktop';

/**
 * Complete breakpoint state interface
 * Used by BreakpointProvider and useBreakpoint hook
 */
export interface BreakpointState {
  width: number;
  height: number;
  deviceType: DeviceType;
  isMobile: boolean;
  isTablet: boolean;
  isDesktop: boolean;
  isTouch: boolean;
  platform: Platform;
}

/**
 * Safe area insets for mobile devices
 * Handles notch (iOS) and navigation bar (Android)
 */
export interface SafeAreaInsets {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

/**
 * Get device type based on screen width
 * @param width - Current viewport width in pixels
 * @returns DeviceType - 'mobile' | 'tablet' | 'desktop'
 */
export const getDeviceType = (width: number): DeviceType => {
  if (width < BREAKPOINTS.tablet) {
    return 'mobile';
  }
  if (width < BREAKPOINTS.desktop) {
    return 'tablet';
  }
  return 'desktop';
};

/**
 * Check if width falls within mobile breakpoint
 * @param width - Current viewport width
 */
export const isMobileWidth = (width: number): boolean => {
  return width < BREAKPOINTS.tablet;
};

/**
 * Check if width falls within tablet breakpoint
 * @param width - Current viewport width
 */
export const isTabletWidth = (width: number): boolean => {
  return width >= BREAKPOINTS.tablet && width < BREAKPOINTS.desktop;
};

/**
 * Check if width falls within desktop breakpoint
 * @param width - Current viewport width
 */
export const isDesktopWidth = (width: number): boolean => {
  return width >= BREAKPOINTS.desktop;
};

/**
 * Detect touch capability
 * Checks multiple methods for cross-browser compatibility
 */
export const detectTouch = (): boolean => {
  if (typeof window === 'undefined') return false;

  return (
    'ontouchstart' in window ||
    navigator.maxTouchPoints > 0 ||
    // @ts-ignore - Legacy check for older browsers
    (navigator.msMaxTouchPoints && navigator.msMaxTouchPoints > 0)
  );
};

/**
 * Detect platform from user agent
 * @returns Platform - 'android' | 'ios' | 'desktop'
 */
export const detectPlatform = (): Platform => {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') {
    return 'desktop';
  }

  const ua = navigator.userAgent.toLowerCase();

  if (/android/i.test(ua)) {
    return 'android';
  }

  if (/iphone|ipad|ipod/i.test(ua)) {
    return 'ios';
  }

  return 'desktop';
};

/**
 * Calculate complete breakpoint state from window dimensions
 * Used by BreakpointProvider for initial state and resize updates
 */
export const calculateBreakpointState = (): BreakpointState => {
  if (typeof window === 'undefined') {
    // SSR fallback - default to desktop
    return {
      width: 1024,
      height: 768,
      deviceType: 'desktop',
      isMobile: false,
      isTablet: false,
      isDesktop: true,
      isTouch: false,
      platform: 'desktop',
    };
  }

  const width = window.innerWidth;
  const height = window.innerHeight;
  const deviceType = getDeviceType(width);

  return {
    width,
    height,
    deviceType,
    isMobile: deviceType === 'mobile',
    isTablet: deviceType === 'tablet',
    isDesktop: deviceType === 'desktop',
    isTouch: detectTouch(),
    platform: detectPlatform(),
  };
};

/**
 * Media query strings for CSS-in-JS usage
 * Example: @media ${MEDIA_QUERIES.mobile} { ... }
 */
export const MEDIA_QUERIES = {
  mobile: `(max-width: ${BREAKPOINTS.tablet - 1}px)`,
  tablet: `(min-width: ${BREAKPOINTS.tablet}px) and (max-width: ${BREAKPOINTS.desktop - 1}px)`,
  desktop: `(min-width: ${BREAKPOINTS.desktop}px)`,
  wide: `(min-width: ${BREAKPOINTS.wide}px)`,
  touch: '(hover: none) and (pointer: coarse)',
  mouse: '(hover: hover) and (pointer: fine)',
} as const;

export default BREAKPOINTS;
