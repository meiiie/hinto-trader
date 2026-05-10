/**
 * ResponsiveInput - Touch-optimized input component
 * SOTA: Binance UI Refined 2025 + Apple HIG
 *
 * Features:
 * - Mobile: minHeight 48px (REQ-5.2)
 * - Desktop: standard height
 * - Touch-friendly padding
 * - Support for prefix/suffix icons
 */

import React, { InputHTMLAttributes, forwardRef } from 'react';
import { useBreakpoint } from '../../hooks/useBreakpoint';
import { THEME } from '../../styles/theme';

interface ResponsiveInputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> {
  size?: 'sm' | 'md' | 'lg';
  fullWidth?: boolean;
  error?: boolean;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
  label?: string;
  helperText?: string;
}

/**
 * ResponsiveInput Component
 * Touch-friendly input with responsive sizing
 */
export const ResponsiveInput = forwardRef<HTMLInputElement, ResponsiveInputProps>(({
  size = 'md',
  fullWidth = true,
  error = false,
  leftIcon,
  rightIcon,
  label,
  helperText,
  style,
  ...props
}, ref) => {
  const { responsive } = useBreakpoint();

  // Touch-friendly sizing (REQ-5.2)
  const heights = {
    sm: responsive(40, 36, 32),
    md: responsive(48, 44, 40),
    lg: responsive(56, 52, 48),
  };

  const fontSizes = {
    sm: responsive(14, 13, 12),
    md: responsive(15, 14, 14),
    lg: responsive(16, 15, 14),
  };

  const paddings = {
    sm: responsive('8px 12px', '6px 10px', '4px 8px'),
    md: responsive('12px 16px', '10px 14px', '8px 12px'),
    lg: responsive('14px 18px', '12px 16px', '10px 14px'),
  };

  const borderColor = error ? THEME.status.sell : THEME.border.input;

  return (
    <div style={{ width: fullWidth ? '100%' : 'auto' }}>
      {/* Label */}
      {label && (
        <label style={{
          display: 'block',
          marginBottom: 6,
          fontSize: responsive(13, 12, 12),
          fontWeight: 500,
          color: THEME.text.secondary,
        }}>
          {label}
        </label>
      )}

      {/* Input Container */}
      <div style={{
        position: 'relative',
        display: 'flex',
        alignItems: 'center',
      }}>
        {/* Left Icon */}
        {leftIcon && (
          <span style={{
            position: 'absolute',
            left: 12,
            display: 'flex',
            alignItems: 'center',
            color: THEME.text.tertiary,
            pointerEvents: 'none',
          }}>
            {leftIcon}
          </span>
        )}

        {/* Input */}
        <input
          ref={ref}
          style={{
            width: '100%',
            minHeight: heights[size],
            padding: paddings[size],
            paddingLeft: leftIcon ? 40 : undefined,
            paddingRight: rightIcon ? 40 : undefined,
            fontSize: fontSizes[size],
            fontFamily: "'Inter', system-ui, sans-serif",
            color: THEME.text.primary,
            backgroundColor: THEME.bg.input,
            border: `1px solid ${borderColor}`,
            borderRadius: responsive(8, 6, 4),
            outline: 'none',
            transition: 'border-color 0.2s ease',
            ...style,
          }}
          {...props}
        />

        {/* Right Icon */}
        {rightIcon && (
          <span style={{
            position: 'absolute',
            right: 12,
            display: 'flex',
            alignItems: 'center',
            color: THEME.text.tertiary,
          }}>
            {rightIcon}
          </span>
        )}
      </div>

      {/* Helper Text */}
      {helperText && (
        <span style={{
          display: 'block',
          marginTop: 4,
          fontSize: responsive(12, 11, 11),
          color: error ? THEME.status.sell : THEME.text.tertiary,
        }}>
          {helperText}
        </span>
      )}
    </div>
  );
});

ResponsiveInput.displayName = 'ResponsiveInput';

export default ResponsiveInput;
