/**
 * ResponsiveButton - Touch-optimized button component
 * SOTA: Binance UI Refined 2025 + Apple HIG
 *
 * Features:
 * - Mobile: minHeight 44px, minWidth 44px (REQ-5.1)
 * - Desktop: minHeight 32px
 * - Variants: primary, secondary, danger
 * - Sizes: sm, md, lg with responsive heights
 */

import React, { ButtonHTMLAttributes } from 'react';
import { useBreakpoint } from '../../hooks/useBreakpoint';
import { THEME } from '../../styles/theme';

export type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost';
export type ButtonSize = 'sm' | 'md' | 'lg';

interface ResponsiveButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  fullWidth?: boolean;
  loading?: boolean;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
}

/**
 * Get variant-specific styles
 */
const getVariantStyles = (variant: ButtonVariant, disabled?: boolean) => {
  if (disabled) {
    return {
      backgroundColor: THEME.bg.vessel,
      color: THEME.text.disabled,
      border: 'none',
    };
  }

  switch (variant) {
    case 'primary':
      return {
        backgroundColor: THEME.accent.gold,
        color: '#000',
        border: 'none',
      };
    case 'secondary':
      return {
        backgroundColor: 'transparent',
        color: THEME.text.primary,
        border: `1px solid ${THEME.border.primary}`,
      };
    case 'danger':
      return {
        backgroundColor: THEME.status.sell,
        color: '#fff',
        border: 'none',
      };
    case 'ghost':
      return {
        backgroundColor: 'transparent',
        color: THEME.text.secondary,
        border: 'none',
      };
    default:
      return {
        backgroundColor: THEME.accent.gold,
        color: '#000',
        border: 'none',
      };
  }
};

/**
 * ResponsiveButton Component
 * Touch-friendly button with responsive sizing
 */
export const ResponsiveButton: React.FC<ResponsiveButtonProps> = ({
  variant = 'primary',
  size = 'md',
  fullWidth = false,
  loading = false,
  leftIcon,
  rightIcon,
  children,
  disabled,
  style,
  ...props
}) => {
  const { isMobile, responsive } = useBreakpoint();

  // Touch-friendly sizing (REQ-5.1)
  const heights: Record<ButtonSize, number> = {
    sm: responsive(40, 36, 32),
    md: responsive(48, 44, 40),
    lg: responsive(56, 52, 48),
  };

  const paddings: Record<ButtonSize, string> = {
    sm: responsive('8px 16px', '6px 12px', '4px 10px'),
    md: responsive('12px 20px', '10px 16px', '8px 14px'),
    lg: responsive('16px 24px', '14px 20px', '12px 18px'),
  };

  const fontSizes: Record<ButtonSize, number> = {
    sm: responsive(14, 13, 12),
    md: responsive(15, 14, 13),
    lg: responsive(16, 15, 14),
  };

  const variantStyles = getVariantStyles(variant, disabled || loading);

  return (
    <button
      disabled={disabled || loading}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
        minHeight: heights[size],
        minWidth: isMobile ? 44 : 32, // Touch target minimum (REQ-5.5)
        padding: paddings[size],
        fontSize: fontSizes[size],
        fontWeight: 600,
        borderRadius: responsive(8, 6, 4),
        cursor: disabled || loading ? 'not-allowed' : 'pointer',
        width: fullWidth ? '100%' : 'auto',
        transition: 'all 0.2s ease',
        opacity: loading ? 0.7 : 1,
        ...variantStyles,
        ...style,
      }}
      {...props}
    >
      {loading ? (
        <span style={{
          width: 16,
          height: 16,
          border: '2px solid currentColor',
          borderTopColor: 'transparent',
          borderRadius: '50%',
          animation: 'spin 0.8s linear infinite',
        }} />
      ) : (
        <>
          {leftIcon && <span style={{ display: 'flex' }}>{leftIcon}</span>}
          {children}
          {rightIcon && <span style={{ display: 'flex' }}>{rightIcon}</span>}
        </>
      )}
    </button>
  );
};

export default ResponsiveButton;
