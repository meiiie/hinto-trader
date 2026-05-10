/**
 * BottomSheet - Slide-up panel for mobile
 * SOTA: Binance UI Refined 2025 + Material Design 3
 *
 * Features:
 * - Snap points: peek (20vh), half (50vh), full (90vh) (REQ-8.3)
 * - Drag-to-dismiss gesture (REQ-8.2)
 * - Backdrop with dim + scroll block (REQ-8.4)
 * - Smooth animation transitions
 * - GPU-accelerated animations using transform (REQ-10.2)
 */

import React, { useState, useRef, useEffect, ReactNode, useCallback, useMemo } from 'react';
import { THEME } from '../../styles/theme';

export type SnapPoint = 'peek' | 'half' | 'full';

interface BottomSheetProps {
  isOpen: boolean;
  onClose: () => void;
  snapPoints?: SnapPoint[];
  initialSnap?: SnapPoint;
  children: ReactNode;
  title?: string;
}

const SNAP_HEIGHTS: Record<SnapPoint, string> = {
  peek: '25vh',
  half: '50vh',
  full: '90vh',
};

const SNAP_VALUES: Record<SnapPoint, number> = {
  peek: 25,
  half: 50,
  full: 90,
};

/**
 * Check if device prefers reduced motion
 */
const prefersReducedMotion = (): boolean => {
  if (typeof window === 'undefined') return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
};

/**
 * BottomSheet Component
 * Slide-up panel with drag gestures
 */
export const BottomSheet: React.FC<BottomSheetProps> = ({
  isOpen,
  onClose,
  snapPoints = ['half', 'full'],
  initialSnap,
  children,
  title,
}) => {
  const [currentSnap, setCurrentSnap] = useState<SnapPoint>(initialSnap || snapPoints[0]);
  const [isDragging, setIsDragging] = useState(false);
  const [dragOffset, setDragOffset] = useState(0);
  const sheetRef = useRef<HTMLDivElement>(null);
  const startYRef = useRef(0);
  const startHeightRef = useRef(0);

  // Reset snap when opening
  useEffect(() => {
    if (isOpen) {
      setCurrentSnap(initialSnap || snapPoints[0]);
      setDragOffset(0);
      // Prevent body scroll when sheet is open
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }

    return () => {
      document.body.style.overflow = '';
    };
  }, [isOpen, initialSnap, snapPoints]);

  /**
   * Calculate nearest snap point based on current position
   */
  const calculateNearestSnap = useCallback((currentHeight: number): SnapPoint => {
    let nearest = snapPoints[0];
    let minDiff = Infinity;

    for (const snap of snapPoints) {
      const diff = Math.abs(SNAP_VALUES[snap] - currentHeight);
      if (diff < minDiff) {
        minDiff = diff;
        nearest = snap;
      }
    }

    return nearest;
  }, [snapPoints]);

  /**
   * Handle drag start
   */
  const handleDragStart = (clientY: number) => {
    setIsDragging(true);
    startYRef.current = clientY;
    startHeightRef.current = SNAP_VALUES[currentSnap];
  };

  /**
   * Handle drag move
   */
  const handleDragMove = (clientY: number) => {
    if (!isDragging) return;

    const deltaY = startYRef.current - clientY;
    const deltaPercent = (deltaY / window.innerHeight) * 100;
    const newHeight = startHeightRef.current + deltaPercent;

    // Clamp between 10% and 95%
    const clampedHeight = Math.max(10, Math.min(95, newHeight));
    setDragOffset(clampedHeight - SNAP_VALUES[currentSnap]);
  };

  /**
   * Handle drag end
   */
  const handleDragEnd = () => {
    if (!isDragging) return;

    setIsDragging(false);
    const currentHeight = SNAP_VALUES[currentSnap] + dragOffset;

    // Close if dragged below threshold
    if (currentHeight < 15) {
      onClose();
      return;
    }

    // Snap to nearest point
    const nearest = calculateNearestSnap(currentHeight);
    setCurrentSnap(nearest);
    setDragOffset(0);
  };

  // Touch event handlers
  const handleTouchStart = (e: React.TouchEvent) => {
    handleDragStart(e.touches[0].clientY);
  };

  const handleTouchMove = (e: React.TouchEvent) => {
    handleDragMove(e.touches[0].clientY);
  };

  const handleTouchEnd = () => {
    handleDragEnd();
  };

  // Mouse event handlers (for desktop testing)
  const handleMouseDown = (e: React.MouseEvent) => {
    handleDragStart(e.clientY);
  };

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      handleDragMove(e.clientY);
    };

    const handleMouseUp = () => {
      handleDragEnd();
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);

    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging]);

  if (!isOpen) return null;

  // Use reduced motion if user prefers
  const reducedMotion = prefersReducedMotion();
  const transitionDuration = reducedMotion ? '0.1s' : '0.3s';

  // Calculate transform for GPU-accelerated animation (REQ-10.2)
  // Using translateY instead of height changes for better performance
  const sheetTransform = useMemo(() => {
    if (isDragging) {
      const heightPercent = SNAP_VALUES[currentSnap] + dragOffset;
      const translateY = 100 - heightPercent;
      return `translateY(${translateY}%)`;
    }
    const translateY = 100 - SNAP_VALUES[currentSnap];
    return `translateY(${translateY}%)`;
  }, [isDragging, currentSnap, dragOffset]);

  return (
    <>
      {/* Backdrop - using opacity for GPU acceleration */}
      <div
        style={{
          position: 'fixed',
          inset: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.5)',
          zIndex: 999,
          opacity: 1,
          transition: `opacity ${transitionDuration} ease`,
          willChange: 'opacity',
        }}
        onClick={onClose}
      />

      {/* Sheet - using transform for GPU acceleration */}
      <div
        ref={sheetRef}
        style={{
          position: 'fixed',
          bottom: 0,
          left: 0,
          right: 0,
          height: '100vh', // Full height, controlled by transform
          transform: sheetTransform,
          backgroundColor: THEME.bg.secondary,
          borderTopLeftRadius: 16,
          borderTopRightRadius: 16,
          zIndex: 1000,
          transition: isDragging ? 'none' : `transform ${transitionDuration} cubic-bezier(0.32, 0.72, 0, 1)`,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          // GPU acceleration hints (use sparingly)
          willChange: isDragging ? 'transform' : 'auto',
          backfaceVisibility: 'hidden',
          WebkitBackfaceVisibility: 'hidden',
        }}
      >
        {/* Drag Handle */}
        <div
          onTouchStart={handleTouchStart}
          onTouchMove={handleTouchMove}
          onTouchEnd={handleTouchEnd}
          onMouseDown={handleMouseDown}
          style={{
            padding: '12px 0',
            cursor: 'grab',
            touchAction: 'none',
          }}
        >
          <div style={{
            width: 40,
            height: 4,
            backgroundColor: THEME.border.primary,
            borderRadius: 2,
            margin: '0 auto',
          }} />
        </div>

        {/* Title */}
        {title && (
          <div style={{
            padding: '0 16px 12px',
            borderBottom: `1px solid ${THEME.border.primary}`,
          }}>
            <h3 style={{
              margin: 0,
              fontSize: 16,
              fontWeight: 600,
              color: THEME.text.primary,
            }}>
              {title}
            </h3>
          </div>
        )}

        {/* Content - height based on snap point */}
        <div style={{
          flex: 1,
          overflow: 'auto',
          padding: 16,
          WebkitOverflowScrolling: 'touch',
          maxHeight: `calc(${SNAP_HEIGHTS[currentSnap]} - ${title ? '80px' : '44px'})`,
        }}>
          {children}
        </div>
      </div>
    </>
  );
};

export default BottomSheet;
