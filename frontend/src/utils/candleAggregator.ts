/**
 * Client-Side Candle Aggregator
 *
 * Aggregates 1-minute candles into higher timeframes (15m, 1h)
 * using the formula: floor(time / intervalSeconds) * intervalSeconds
 *
 * **Feature: desktop-trading-dashboard**
 * **Validates: Requirements 2.5**
 */

export interface Candle {
    time: number;  // Unix timestamp in seconds
    open: number;
    high: number;
    low: number;
    close: number;
    volume?: number;
}

export type Timeframe = '1m' | '15m' | '1h';

/**
 * Get interval in seconds for a timeframe
 */
export function getIntervalSeconds(timeframe: Timeframe): number {
    switch (timeframe) {
        case '1m': return 60;
        case '15m': return 900;  // 15 * 60
        case '1h': return 3600;  // 60 * 60
        default: return 60;
    }
}

/**
 * Calculate the start time of a candle for a given timeframe
 * Uses formula: floor(time / intervalSeconds) * intervalSeconds
 *
 * @param timestamp - Unix timestamp in seconds
 * @param timeframe - Target timeframe
 * @returns Start time of the candle period
 */
export function getCandleStartTime(timestamp: number, timeframe: Timeframe): number {
    const intervalSeconds = getIntervalSeconds(timeframe);
    return Math.floor(timestamp / intervalSeconds) * intervalSeconds;
}

/**
 * Aggregate a 1-minute candle into an existing candle or create a new one
 *
 * @param existingCandle - Current forming candle (or null for new)
 * @param newData - New 1-minute candle data
 * @param timeframe - Target timeframe
 * @returns Updated or new candle
 */
export function aggregateCandle(
    existingCandle: Candle | null,
    newData: Candle,
    timeframe: Timeframe
): { candle: Candle; isNewCandle: boolean } {
    const candleStartTime = getCandleStartTime(newData.time, timeframe);

    // Check if this belongs to the same candle period
    if (existingCandle && existingCandle.time === candleStartTime) {
        // Update existing candle
        return {
            candle: {
                time: candleStartTime,
                open: existingCandle.open,  // Keep original open
                high: Math.max(existingCandle.high, newData.high),
                low: Math.min(existingCandle.low, newData.low),
                close: newData.close,  // Update close to latest
                volume: (existingCandle.volume || 0) + (newData.volume || 0)
            },
            isNewCandle: false
        };
    } else {
        // New candle period started
        return {
            candle: {
                time: candleStartTime,
                open: newData.open,
                high: newData.high,
                low: newData.low,
                close: newData.close,
                volume: newData.volume || 0
            },
            isNewCandle: true
        };
    }
}

/**
 * Aggregate multiple 1-minute candles into a higher timeframe
 *
 * @param candles1m - Array of 1-minute candles (sorted by time ascending)
 * @param timeframe - Target timeframe
 * @returns Array of aggregated candles
 */
export function aggregateCandles(candles1m: Candle[], timeframe: Timeframe): Candle[] {
    if (timeframe === '1m') {
        return candles1m;  // No aggregation needed
    }

    const aggregated: Map<number, Candle> = new Map();

    for (const candle of candles1m) {
        const startTime = getCandleStartTime(candle.time, timeframe);
        const existing = aggregated.get(startTime);

        if (existing) {
            // Update existing aggregated candle
            aggregated.set(startTime, {
                time: startTime,
                open: existing.open,
                high: Math.max(existing.high, candle.high),
                low: Math.min(existing.low, candle.low),
                close: candle.close,
                volume: (existing.volume || 0) + (candle.volume || 0)
            });
        } else {
            // Create new aggregated candle
            aggregated.set(startTime, {
                time: startTime,
                open: candle.open,
                high: candle.high,
                low: candle.low,
                close: candle.close,
                volume: candle.volume || 0
            });
        }
    }

    // Convert to array and sort by time
    return Array.from(aggregated.values()).sort((a, b) => a.time - b.time);
}

/**
 * Check if a timestamp belongs to the current candle period
 *
 * @param timestamp - Unix timestamp to check
 * @param currentCandleTime - Start time of current candle
 * @param timeframe - Timeframe
 * @returns true if timestamp is in the same candle period
 */
export function isInSameCandlePeriod(
    timestamp: number,
    currentCandleTime: number,
    timeframe: Timeframe
): boolean {
    return getCandleStartTime(timestamp, timeframe) === currentCandleTime;
}

/**
 * Get the next candle start time
 *
 * @param currentTime - Current candle start time
 * @param timeframe - Timeframe
 * @returns Next candle start time
 */
export function getNextCandleTime(currentTime: number, timeframe: Timeframe): number {
    return currentTime + getIntervalSeconds(timeframe);
}

/**
 * Calculate time remaining until next candle
 *
 * @param currentTimestamp - Current Unix timestamp
 * @param timeframe - Timeframe
 * @returns Seconds remaining until next candle
 */
export function getTimeUntilNextCandle(currentTimestamp: number, timeframe: Timeframe): number {
    const intervalSeconds = getIntervalSeconds(timeframe);
    const currentCandleStart = getCandleStartTime(currentTimestamp, timeframe);
    const nextCandleStart = currentCandleStart + intervalSeconds;
    return nextCandleStart - currentTimestamp;
}
