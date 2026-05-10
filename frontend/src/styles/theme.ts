/**
 * Binance-inspired Theme Constants
 * Shared across all components for consistent styling
 */

export const THEME = {
    // Background colors
    bg: {
        primary: '#0B0E11',      // Main background
        secondary: '#181A20',    // Card background
        tertiary: '#1E2329',     // Elevated elements
        vessel: '#29313D',       // Input/container background
        input: '#29313D',
    },

    // Text colors
    text: {
        primary: '#EAECEF',      // Main text
        secondary: '#929AA5',    // Secondary text
        tertiary: '#707A8A',     // Muted text
        disabled: '#4F5867',     // Disabled text
    },

    // Border/Line colors
    border: {
        primary: '#2B2F36',      // Main border
        secondary: '#333B47',    // Grid lines
        input: '#434C5A',        // Input border
    },

    // Status colors
    status: {
        buy: '#2EBD85',          // Green - Buy/Profit
        sell: '#F6465D',         // Red - Sell/Loss
        warning: '#F0B90B',      // Yellow - Warning/VWAP
        info: '#2962FF',         // Blue - Info/Bollinger
        purple: '#8B5CF6',       // Purple - StochRSI
    },

    // Background with alpha
    alpha: {
        buyBg: 'rgba(46, 189, 133, 0.1)',
        buyBg20: 'rgba(46, 189, 133, 0.2)',
        sellBg: 'rgba(246, 70, 93, 0.1)',
        sellBg20: 'rgba(246, 70, 93, 0.2)',
        warningBg: 'rgba(240, 185, 11, 0.1)',
        infoBg: 'rgba(41, 98, 255, 0.1)',
    },

    // Accent colors
    accent: {
        yellow: '#F0B90B',       // Binance yellow
        gold: '#FCD535',         // Button background
    },

    // ============================================================
    // PHASE C: SOTA Spacing & Layout System (Binance 2025 Standard)
    // ============================================================

    // Spacing system (4/8px grid - SOTA standard)
    spacing: {
        xs: 4,    // Tight spacing
        sm: 8,    // Small elements
        md: 16,   // Default spacing
        lg: 24,   // Sections
        xl: 32,   // Large sections
        xxl: 48,  // Page padding
    },

    // Component sizing (Desktop trading standard)
    sizing: {
        // Chart dimensions
        chart: {
            minWidth: 600,
            minHeight: 400,
            defaultHeight: 520,
        },
        // Sidebar panels
        sidebar: {
            width: 320,
            minWidth: 280,
            maxWidth: 400,
        },
        // Cards
        card: {
            minWidth: 280,
            padding: 16,
            borderRadius: 8,
        },
        // Header
        header: {
            height: 64,
            logoHeight: 28,
        },
        // State indicator
        stateIndicator: {
            minWidth: 200,
            height: 44,
        },
    },

    // Typography scale
    typography: {
        xs: 10,
        sm: 12,
        base: 14,
        md: 16,
        lg: 18,
        xl: 24,
        xxl: 32,
    },

    // Border radius
    radius: {
        sm: 4,
        md: 8,
        lg: 12,
        xl: 16,
        full: 9999,
    },

    // Shadows (for elevation)
    shadow: {
        sm: '0 1px 2px rgba(0,0,0,0.3)',
        md: '0 4px 12px rgba(0,0,0,0.4)',
        lg: '0 8px 24px rgba(0,0,0,0.5)',
    },

    // ============================================================
    // ADAPTIVE UI: Responsive Tokens (Mobile/Desktop)
    // SOTA: Binance UI Refined 2025 + Material Design 3 Expressive
    // ============================================================

    // Responsive spacing per breakpoint
    responsive: {
        spacing: {
            mobile: {
                xs: 4,
                sm: 8,
                md: 12,
                lg: 16,
                xl: 24,
                xxl: 32,
            },
            tablet: {
                xs: 4,
                sm: 8,
                md: 14,
                lg: 20,
                xl: 28,
                xxl: 40,
            },
            desktop: {
                xs: 4,
                sm: 8,
                md: 16,
                lg: 24,
                xl: 32,
                xxl: 48,
            },
        },
        // Touch-friendly sizing (REQ-2.2)
        touchTarget: {
            mobile: 44,    // Apple HIG minimum
            tablet: 40,
            desktop: 32,
        },
        // Typography scale per breakpoint (REQ-2.3)
        typography: {
            mobile: {
                xs: 11,
                sm: 13,
                base: 14,   // Increased from 12px for mobile readability
                md: 16,
                lg: 20,
                xl: 26,
                xxl: 34,
            },
            tablet: {
                xs: 10,
                sm: 12,
                base: 13,
                md: 15,
                lg: 18,
                xl: 24,
                xxl: 32,
            },
            desktop: {
                xs: 10,
                sm: 12,
                base: 12,
                md: 14,
                lg: 18,
                xl: 24,
                xxl: 32,
            },
        },
        // Border radius per breakpoint (REQ-2.4)
        radius: {
            mobile: {
                sm: 6,
                md: 10,
                lg: 14,
                xl: 20,
            },
            tablet: {
                sm: 5,
                md: 9,
                lg: 13,
                xl: 18,
            },
            desktop: {
                sm: 4,
                md: 8,
                lg: 12,
                xl: 16,
            },
        },
        // Component heights
        heights: {
            mobile: {
                button: {
                    sm: 40,
                    md: 48,
                    lg: 56,
                },
                input: 48,
                header: 56,
                bottomNav: 56,
            },
            tablet: {
                button: {
                    sm: 36,
                    md: 44,
                    lg: 52,
                },
                input: 44,
                header: 56,
                bottomNav: 0, // No bottom nav on tablet
            },
            desktop: {
                button: {
                    sm: 32,
                    md: 40,
                    lg: 48,
                },
                input: 40,
                header: 48,
                bottomNav: 0, // No bottom nav on desktop
            },
        },
    },
};

/**
 * SOTA (Jan 2026): Format price with DYNAMIC precision based on magnitude
 * Low-value tokens show more decimals for accuracy
 * Matches Binance price display behavior
 */
export const formatPrice = (price: number | undefined | null, decimals?: number): string => {
    // Handle null/undefined/NaN gracefully
    if (price === undefined || price === null || isNaN(price)) return '--';

    // If decimals explicitly provided, use it
    if (decimals !== undefined) {
        return new Intl.NumberFormat('en-US', {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals
        }).format(price);
    }

    // SOTA: Dynamic precision based on price magnitude
    const absPrice = Math.abs(price);
    let precision: number;

    // Zero check
    if (absPrice === 0) return '0.00';

    if (absPrice < 0.000001) {
        precision = 8;  // Highly speculative MEME/SHITCOIN
    } else if (absPrice < 0.001) {
        precision = 7;  // $0.0001234
    } else if (absPrice < 0.01) {
        precision = 6;  // $0.001234
    } else if (absPrice < 1) {
        precision = 5;  // $0.12345
    } else if (absPrice < 10) {
        precision = 4;  // $1.2345
    } else if (absPrice < 1000) {
        precision = 2;  // $123.45 (Standard)
    } else {
        precision = 2;  // $90,640.50 (Maintain 2 decimals even for BTC)
    }

    // CRITICAL FIX: Ensure max >= min to prevent RangeError
    // We want at least 2 decimals for fiat-like feel, unless precision is explicitly lower (which we don't do anymore)
    const minDecimals = Math.min(2, precision);

    // SOTA: Format and then trim trailing zeros for compact display ("Thu ngắn lại")
    const formatted = new Intl.NumberFormat('en-US', {
        minimumFractionDigits: minDecimals,
        maximumFractionDigits: precision
    }).format(price);

    // For small numbers (< 1), trim unnecessary trailing zeros beyond minDecimals
    // e.g. 0.002500 -> 0.0025. But keep 2.50 -> 2.50
    if (absPrice < 1 && formatted.includes('.')) {
        return formatted.replace(/(\.[0-9]*?[1-9])0+$/, "$1");
    }

    return formatted;
};

/**
 * Format date to Vietnam timezone
 */
export const formatVietnamDate = (dateStr: string | null, options?: Intl.DateTimeFormatOptions): string => {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    const defaultOptions: Intl.DateTimeFormatOptions = {
        timeZone: 'Asia/Ho_Chi_Minh',
        day: '2-digit',
        month: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
    };
    return date.toLocaleString('vi-VN', { ...defaultOptions, ...options });
};

/**
 * Format time to Vietnam timezone
 */
export const formatVietnamTime = (dateStr: string): string => {
    const date = new Date(dateStr);
    return date.toLocaleTimeString('vi-VN', {
        timeZone: 'Asia/Ho_Chi_Minh',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    });
};

/**
 * Calculate duration between two dates
 */
export const calculateDuration = (openTime: string, closeTime: string | null): string => {
    if (!closeTime) return '-';
    const open = new Date(openTime).getTime();
    const close = new Date(closeTime).getTime();
    const diffMs = close - open;

    const hours = Math.floor(diffMs / (1000 * 60 * 60));
    const minutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));

    if (hours > 24) {
        const days = Math.floor(hours / 24);
        return `${days}d ${hours % 24}h`;
    }
    return `${hours}h ${minutes}m`;
};

export default THEME;
