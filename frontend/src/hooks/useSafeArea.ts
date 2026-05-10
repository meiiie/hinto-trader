/**
 * useSafeArea Hook - Get safe area insets for mobile devices
 * SOTA: Handles notch (iOS) and navigation bar (Android)
 *
 * Uses CSS env() variables for safe-area-inset-*
 * Falls back to 0 if not supported
 */

import { useState, useEffect } from 'react';
import { SafeAreaInsets } from '../styles/breakpoints';

/**
 * CSS custom properties for safe area insets
 * These should be set in index.css or App.css:
 *
 * :root {
 *   --sat: env(safe-area-inset-top);
 *   --sar: env(safe-area-inset-right);
 *   --sab: env(safe-area-inset-bottom);
 *   --sal: env(safe-area-inset-left);
 * }
 */
const CSS_VARS = {
  top: '--sat',
  right: '--sar',
  bottom: '--sab',
  left: '--sal',
} as const;

/**
 * Parse CSS value to number (removes 'px' suffix)
 */
const parseCSSValue = (value: string): number => {
  const parsed = parseInt(value, 10);
  return isNaN(parsed) ? 0 : parsed;
};

/**
 * Get safe area insets from CSS custom properties
 * SOTA (Jan 2026): Added Android fallback for WebView compatibility
 */
const getSafeAreaInsets = (): SafeAreaInsets => {
  if (typeof window === 'undefined' || typeof document === 'undefined') {
    return { top: 0, right: 0, bottom: 0, left: 0 };
  }

  const computedStyle = getComputedStyle(document.documentElement);

  // Read from CSS env() variables
  let top = parseCSSValue(computedStyle.getPropertyValue(CSS_VARS.top) || '0');
  let right = parseCSSValue(computedStyle.getPropertyValue(CSS_VARS.right) || '0');
  let bottom = parseCSSValue(computedStyle.getPropertyValue(CSS_VARS.bottom) || '0');
  let left = parseCSSValue(computedStyle.getPropertyValue(CSS_VARS.left) || '0');

  // SOTA (Jan 2026): Android WebView fallback
  // Android system navigation bar is typically 48dp (48-56px)
  // If env() returns 0 on Android, apply sensible fallback
  const isAndroid = /Android/i.test(navigator.userAgent);
  // REMOVED isSmallScreen check - fails on large phones like S23 Ultra/iPhone Max (height > 900)
  // const isSmallScreen = window.innerHeight < 900;

  if (isAndroid) {
    // Android gesture navigation typically needs ~20px bottom inset
    // 3-button navigation needs ~48px
    // Check for gesture navigation by screen ratio
    const screenRatio = window.innerHeight / window.innerWidth;
    const hasGestureNav = screenRatio > 2.0; // Tall phones with gesture nav

    if (bottom === 0) {
      bottom = hasGestureNav ? 24 : 0; // Gesture nav hint area
    }
    if (top === 0) {
      // Status bar is typically 24-40dp on Android (punch hole)
      // Increased from 24 to 36 for safety
      top = 36;
    }
  }

  // iOS fallback (less common since Safari supports env() well)
  const isIOS = /iPhone|iPad|iPod/i.test(navigator.userAgent);
  if (isIOS && bottom === 0 && window.innerHeight > 800) {
    // iPhone X+ with home indicator
    bottom = 34;
    if (top === 0) {
      top = 47; // Notch area
    }
  }

  return { top, right, bottom, left };
};

/**
 * Hook to get safe area insets for mobile devices
 *
 * @returns SafeAreaInsets - { top, right, bottom, left } in pixels
 *
 * @example
 * const safeArea = useSafeArea();
 *
 * return (
 *   <div style={{
 *     paddingTop: safeArea.top,
 *     paddingBottom: safeArea.bottom + 56, // 56px for bottom nav
 *   }}>
 *     {children}
 *   </div>
 * );
 */
export const useSafeArea = (): SafeAreaInsets => {
  const [insets, setInsets] = useState<SafeAreaInsets>(() => getSafeAreaInsets());

  useEffect(() => {
    if (typeof window === 'undefined') return;

    // Re-calculate on resize (orientation change may affect safe areas)
    const handleResize = () => {
      // Small delay to ensure CSS has updated
      requestAnimationFrame(() => {
        setInsets(getSafeAreaInsets());
      });
    };

    // Initial calculation after mount
    handleResize();

    window.addEventListener('resize', handleResize);
    window.addEventListener('orientationchange', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      window.removeEventListener('orientationchange', handleResize);
    };
  }, []);

  return insets;
};

/**
 * Hook to get just the bottom safe area inset
 * Common use case for bottom navigation
 *
 * @returns number - Bottom safe area in pixels
 */
export const useSafeAreaBottom = (): number => {
  const { bottom } = useSafeArea();
  return bottom;
};

/**
 * Hook to get just the top safe area inset
 * Common use case for status bar / notch
 *
 * @returns number - Top safe area in pixels
 */
export const useSafeAreaTop = (): number => {
  const { top } = useSafeArea();
  return top;
};

export default useSafeArea;
