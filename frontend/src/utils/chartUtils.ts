/**
 * Chart Utility Functions
 *
 * Pure utility functions for chart data processing.
 * Extracted from CandleChart.tsx for better testability and reusability.
 */

import { Time } from 'lightweight-charts';
import { VN_TIMEZONE_OFFSET } from './chartConstants';

/**
 * Convert UTC timestamp to Vietnam time for display
 * @param utcTimestamp - Unix timestamp in seconds (UTC)
 * @returns Time object for lightweight-charts in Vietnam timezone
 */
export const toVietnamTime = (utcTimestamp: number): Time => {
    // Add Vietnam offset to get local display time
    // lightweight-charts expects Unix seconds
    return (utcTimestamp + VN_TIMEZONE_OFFSET) as Time;
};

/**
 * Safely parse any timestamp format to Unix seconds
 * Handles: ISO string, Date object, milliseconds, or seconds
 *
 * @param timestamp - Unknown format timestamp
 * @returns Unix timestamp in seconds, or 0 if invalid
 */
export const safeParseTimestamp = (timestamp: unknown): number => {
    if (!timestamp) return 0;

    // Handle Date object
    if (timestamp instanceof Date) {
        return Math.floor(timestamp.getTime() / 1000);
    }

    // Handle string (ISO format)
    if (typeof timestamp === 'string') {
        const parsed = Date.parse(timestamp);
        if (!isNaN(parsed)) {
            return Math.floor(parsed / 1000);
        }
        return 0;
    }

    // Handle number
    if (typeof timestamp === 'number') {
        // If > 10 billion, it's milliseconds; convert to seconds
        if (timestamp > 10000000000) {
            return Math.floor(timestamp / 1000);
        }
        return timestamp;
    }

    return 0;
};

/**
 * Format price with Vietnamese locale
 * @param price - Price value to format
 * @returns Formatted price string
 */
export const formatPrice = (price: number): string => {
    if (price === undefined || price === null || isNaN(price)) {
        return '---';
    }
    return new Intl.NumberFormat('en-US', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    }).format(price);
};

/**
 * Get current time in Vietnam timezone as formatted string
 * @returns Formatted time string (HH:MM:SS)
 */
export const getCurrentVietnamTime = (): string => {
    const now = new Date();
    return now.toLocaleTimeString('vi-VN', {
        timeZone: 'Asia/Ho_Chi_Minh',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    });
};

/**
 * Calculate timeframe interval in seconds
 * @param timeframe - Timeframe string (1m, 15m, 1h)
 * @returns Interval duration in seconds
 */
export const getTimeframeSeconds = (timeframe: string): number => {
    switch (timeframe) {
        case '1m': return 60;
        case '15m': return 900;
        case '1h': return 3600;
        default: return 60;
    }
};

/**
 * Deduplicate chart data by time
 * lightweight-charts requires strictly ascending timestamps
 *
 * @param data - Array of chart data with time property
 * @returns Deduplicated array
 */
export const deduplicateByTime = <T extends { time: Time | number }>(data: T[]): T[] => {
    const seenTimes = new Set<number>();
    return data.filter(item => {
        const t = item.time as number;
        if (seenTimes.has(t)) return false;
        seenTimes.add(t);
        return true;
    });
};
