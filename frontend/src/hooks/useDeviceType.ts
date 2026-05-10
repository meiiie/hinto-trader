/**
 * useDeviceType Hook - Detect touch capability and platform
 * SOTA: Binance UI Refined 2025
 *
 * Provides device-specific information for adaptive UI
 * Independent of breakpoint system for flexibility
 */

import { useState, useEffect } from 'react';
import { Platform, detectTouch, detectPlatform } from '../styles/breakpoints';

export interface DeviceTypeInfo {
  /** True if device supports touch input */
  isTouch: boolean;
  /** Platform: 'android' | 'ios' | 'desktop' */
  platform: Platform;
  /** True if running on Android */
  isAndroid: boolean;
  /** True if running on iOS */
  isIOS: boolean;
  /** True if running on desktop (not mobile) */
  isDesktopPlatform: boolean;
  /** True if device prefers reduced motion */
  prefersReducedMotion: boolean;
  /** Device pixel ratio for high-DPI displays */
  devicePixelRatio: number;
}

/**
 * Hook to detect device type, touch capability, and platform
 *
 * @returns DeviceTypeInfo object with device characteristics
 *
 * @example
 * const { isTouch, platform, isAndroid } = useDeviceType();
 *
 * // Use tap instead of hover on touch devices
 * const interactionMode = isTouch ? 'tap' : 'hover';
 *
 * // Platform-specific styling
 * if (isAndroid) {
 *   // Apply Android-specific styles
 * }
 */
export const useDeviceType = (): DeviceTypeInfo => {
  const [deviceInfo, setDeviceInfo] = useState<DeviceTypeInfo>(() => {
    // Initial state - SSR safe
    if (typeof window === 'undefined') {
      return {
        isTouch: false,
        platform: 'desktop',
        isAndroid: false,
        isIOS: false,
        isDesktopPlatform: true,
        prefersReducedMotion: false,
        devicePixelRatio: 1,
      };
    }

    const platform = detectPlatform();
    const prefersReducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches ?? false;

    return {
      isTouch: detectTouch(),
      platform,
      isAndroid: platform === 'android',
      isIOS: platform === 'ios',
      isDesktopPlatform: platform === 'desktop',
      prefersReducedMotion,
      devicePixelRatio: window.devicePixelRatio || 1,
    };
  });

  useEffect(() => {
    if (typeof window === 'undefined') return;

    // Listen for reduced motion preference changes
    const motionQuery = window.matchMedia?.('(prefers-reduced-motion: reduce)');

    const handleMotionChange = (e: MediaQueryListEvent) => {
      setDeviceInfo(prev => ({
        ...prev,
        prefersReducedMotion: e.matches,
      }));
    };

    // Modern browsers
    if (motionQuery?.addEventListener) {
      motionQuery.addEventListener('change', handleMotionChange);
    }

    return () => {
      if (motionQuery?.removeEventListener) {
        motionQuery.removeEventListener('change', handleMotionChange);
      }
    };
  }, []);

  return deviceInfo;
};

/**
 * Hook to check if device supports touch
 * Convenience wrapper
 *
 * @returns boolean - true if touch device
 */
export const useIsTouch = (): boolean => {
  const { isTouch } = useDeviceType();
  return isTouch;
};

/**
 * Hook to get current platform
 *
 * @returns Platform - 'android' | 'ios' | 'desktop'
 */
export const usePlatform = (): Platform => {
  const { platform } = useDeviceType();
  return platform;
};

/**
 * Hook to check if user prefers reduced motion
 * Use this to disable animations for accessibility
 *
 * @returns boolean - true if reduced motion preferred
 */
export const usePrefersReducedMotion = (): boolean => {
  const { prefersReducedMotion } = useDeviceType();
  return prefersReducedMotion;
};

export default useDeviceType;
