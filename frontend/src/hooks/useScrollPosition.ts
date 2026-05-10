/**
 * useScrollPosition - Hook for preserving scroll position per tab
 * SOTA: Binance UI Refined 2025
 *
 * Features:
 * - Save scroll position per tab (REQ-10.5)
 * - Restore scroll position on tab switch
 * - Uses sessionStorage for persistence within session
 * - Debounced scroll listener for performance
 */

import { useEffect, useRef, useCallback } from 'react';

interface ScrollPosition {
  x: number;
  y: number;
}

interface UseScrollPositionOptions {
  /** Unique key for this scroll context (e.g., tab name) */
  key: string;
  /** Element to track scroll on (defaults to window) */
  element?: HTMLElement | null;
  /** Debounce delay in ms (default: 100) */
  debounceMs?: number;
  /** Whether to persist to sessionStorage (default: true) */
  persist?: boolean;
}

// In-memory cache for scroll positions (faster than sessionStorage)
const scrollCache = new Map<string, ScrollPosition>();

/**
 * Get scroll position from cache or storage
 */
const getStoredPosition = (key: string, persist: boolean): ScrollPosition => {
  // Check memory cache first
  const cached = scrollCache.get(key);
  if (cached) return cached;

  // Check sessionStorage
  if (persist && typeof sessionStorage !== 'undefined') {
    try {
      const stored = sessionStorage.getItem(`scroll_${key}`);
      if (stored) {
        const position = JSON.parse(stored) as ScrollPosition;
        scrollCache.set(key, position);
        return position;
      }
    } catch {
      // Ignore parse errors
    }
  }

  return { x: 0, y: 0 };
};

/**
 * Save scroll position to cache and storage
 */
const savePosition = (key: string, position: ScrollPosition, persist: boolean): void => {
  scrollCache.set(key, position);

  if (persist && typeof sessionStorage !== 'undefined') {
    try {
      sessionStorage.setItem(`scroll_${key}`, JSON.stringify(position));
    } catch {
      // Ignore storage errors (quota exceeded, etc.)
    }
  }
};

/**
 * useScrollPosition Hook
 * Preserves and restores scroll position for a given key
 */
export const useScrollPosition = ({
  key,
  element,
  debounceMs = 100,
  persist = true,
}: UseScrollPositionOptions): {
  /** Manually save current scroll position */
  saveScrollPosition: () => void;
  /** Manually restore scroll position */
  restoreScrollPosition: () => void;
  /** Clear saved scroll position */
  clearScrollPosition: () => void;
} => {
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isRestoringRef = useRef(false);

  /**
   * Get current scroll position from element or window
   */
  const getCurrentPosition = useCallback((): ScrollPosition => {
    if (element) {
      return { x: element.scrollLeft, y: element.scrollTop };
    }
    if (typeof window !== 'undefined') {
      return { x: window.scrollX, y: window.scrollY };
    }
    return { x: 0, y: 0 };
  }, [element]);

  /**
   * Save current scroll position
   */
  const saveScrollPosition = useCallback(() => {
    if (isRestoringRef.current) return; // Don't save while restoring
    const position = getCurrentPosition();
    savePosition(key, position, persist);
  }, [key, persist, getCurrentPosition]);

  /**
   * Restore scroll position
   */
  const restoreScrollPosition = useCallback(() => {
    const position = getStoredPosition(key, persist);

    isRestoringRef.current = true;

    if (element) {
      element.scrollTo({ left: position.x, top: position.y, behavior: 'instant' });
    } else if (typeof window !== 'undefined') {
      window.scrollTo({ left: position.x, top: position.y, behavior: 'instant' });
    }

    // Reset flag after a short delay
    requestAnimationFrame(() => {
      isRestoringRef.current = false;
    });
  }, [key, persist, element]);

  /**
   * Clear saved scroll position
   */
  const clearScrollPosition = useCallback(() => {
    scrollCache.delete(key);
    if (persist && typeof sessionStorage !== 'undefined') {
      sessionStorage.removeItem(`scroll_${key}`);
    }
  }, [key, persist]);

  /**
   * Debounced scroll handler
   */
  const handleScroll = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }

    timeoutRef.current = setTimeout(() => {
      saveScrollPosition();
    }, debounceMs);
  }, [saveScrollPosition, debounceMs]);

  /**
   * Set up scroll listener and restore position on mount
   */
  useEffect(() => {
    const target = element || (typeof window !== 'undefined' ? window : null);
    if (!target) return;

    // Restore position on mount
    restoreScrollPosition();

    // Add scroll listener
    target.addEventListener('scroll', handleScroll, { passive: true });

    return () => {
      target.removeEventListener('scroll', handleScroll);

      // Save position on unmount
      saveScrollPosition();

      // Clear timeout
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, [element, handleScroll, restoreScrollPosition, saveScrollPosition]);

  return {
    saveScrollPosition,
    restoreScrollPosition,
    clearScrollPosition,
  };
};

/**
 * useTabScrollPosition - Simplified hook for tab-based scroll preservation
 * Automatically manages scroll position when activeTab changes
 */
export const useTabScrollPosition = (
  activeTab: string,
  containerRef?: React.RefObject<HTMLElement | null>
): void => {
  const prevTabRef = useRef<string>(activeTab);

  useEffect(() => {
    const container = containerRef?.current;

    // Save scroll position of previous tab
    if (prevTabRef.current !== activeTab) {
      const prevPosition = container
        ? { x: container.scrollLeft, y: container.scrollTop }
        : { x: window.scrollX, y: window.scrollY };

      savePosition(prevTabRef.current, prevPosition, true);
    }

    // Restore scroll position of new tab
    const savedPosition = getStoredPosition(activeTab, true);

    requestAnimationFrame(() => {
      if (container) {
        container.scrollTo({ left: savedPosition.x, top: savedPosition.y, behavior: 'instant' });
      } else {
        window.scrollTo({ left: savedPosition.x, top: savedPosition.y, behavior: 'instant' });
      }
    });

    prevTabRef.current = activeTab;
  }, [activeTab, containerRef]);
};

export default useScrollPosition;
