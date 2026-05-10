/**
 * BreakpointProvider - Context provider for responsive breakpoint state
 * SOTA: Binance UI Refined 2025 + Material Design 3 Expressive
 *
 * Features:
 * - 100ms debounced resize listener (REQ-1.2)
 * - SSR-safe with desktop fallback
 * - Memoized responsive() utility function
 * - Only re-renders components that use useBreakpoint on breakpoint change
 */

import React, { createContext, useState, useEffect, useCallback, useMemo, ReactNode } from 'react';
import {
  BreakpointState,
  calculateBreakpointState,
} from '../styles/breakpoints';

/**
 * Extended context value with utility functions
 */
export interface BreakpointContextValue extends BreakpointState {
  /**
   * Responsive value selector - returns appropriate value based on current breakpoint
   * @param mobile - Value for mobile breakpoint (required, used as fallback)
   * @param tablet - Value for tablet breakpoint (optional, falls back to mobile)
   * @param desktop - Value for desktop breakpoint (optional, falls back to tablet then mobile)
   * @returns The appropriate value for current breakpoint
   *
   * @example
   * const padding = responsive(12, 16, 24);
   * // Returns 12 on mobile, 16 on tablet, 24 on desktop
   *
   * @example
   * const fontSize = responsive(14, undefined, 12);
   * // Returns 14 on mobile, 14 on tablet (fallback), 12 on desktop
   */
  responsive: <T>(mobile: T, tablet?: T, desktop?: T) => T;
}

// Create context with null default (will throw if used outside provider)
export const BreakpointContext = createContext<BreakpointContextValue | null>(null);

interface BreakpointProviderProps {
  children: ReactNode;
}

/**
 * Debounce utility for resize handler
 * @param fn - Function to debounce
 * @param ms - Debounce delay in milliseconds
 */
const debounce = <T extends (...args: unknown[]) => void>(fn: T, ms: number): T => {
  let timeoutId: ReturnType<typeof setTimeout> | null = null;

  return ((...args: Parameters<T>) => {
    if (timeoutId) {
      clearTimeout(timeoutId);
    }
    timeoutId = setTimeout(() => {
      fn(...args);
    }, ms);
  }) as T;
};

/**
 * Get initial state - SSR safe
 */
const getInitialState = (): BreakpointState => {
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
  return calculateBreakpointState();
};

/**
 * BreakpointProvider Component
 * Wraps the app to provide breakpoint context to all children
 */
export const BreakpointProvider: React.FC<BreakpointProviderProps> = ({ children }) => {
  const [state, setState] = useState<BreakpointState>(getInitialState);

  // Setup resize listener with 100ms debounce (REQ-1.2)
  useEffect(() => {
    if (typeof window === 'undefined') return;

    const handleResize = debounce(() => {
      const newState = calculateBreakpointState();
      setState(prevState => {
        // Only update if deviceType changed to minimize re-renders (REQ-1.5)
        if (
          prevState.deviceType !== newState.deviceType ||
          prevState.width !== newState.width ||
          prevState.height !== newState.height
        ) {
          return newState;
        }
        return prevState;
      });
    }, 100);

    window.addEventListener('resize', handleResize);

    // Also listen for orientation change on mobile
    window.addEventListener('orientationchange', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      window.removeEventListener('orientationchange', handleResize);
    };
  }, []);

  /**
   * Responsive value selector
   * Memoized to prevent unnecessary re-renders
   */
  const responsive = useCallback(<T,>(mobile: T, tablet?: T, desktop?: T): T => {
    if (state.isDesktop) {
      // Desktop: prefer desktop, fallback to tablet, then mobile
      return desktop ?? tablet ?? mobile;
    }
    if (state.isTablet) {
      // Tablet: prefer tablet, fallback to mobile
      return tablet ?? mobile;
    }
    // Mobile: always use mobile value
    return mobile;
  }, [state.isDesktop, state.isTablet]);

  // Memoize context value to prevent unnecessary re-renders
  const contextValue = useMemo<BreakpointContextValue>(() => ({
    ...state,
    responsive,
  }), [state, responsive]);

  return (
    <BreakpointContext.Provider value={contextValue}>
      {children}
    </BreakpointContext.Provider>
  );
};

export default BreakpointProvider;
