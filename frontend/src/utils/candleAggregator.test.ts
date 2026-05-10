/**
 * Property-Based Tests for Client-Side Candle Aggregation
 *
 * **Feature: desktop-trading-dashboard, Property 1: Client-Side Candle Aggregation Correctness**
 * **Validates: Requirements 2.5**
 *
 * Tests that for any sequence of 1-minute candles, aggregation to 15m/1h SHALL:
 * - Produce candles with correct start times (floor(time / interval) * interval)
 * - Preserve the first open price of the period
 * - Track the highest high and lowest low
 * - Use the last close as the aggregated close
 */

import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import {
    Timeframe,
    getCandleStartTime,
    getIntervalSeconds,
    aggregateCandle,
    aggregateCandles,
    isInSameCandlePeriod,
    getTimeUntilNextCandle
} from './candleAggregator';
// Candle type is used implicitly in the arbitrary definitions

// Arbitrary for generating valid candles
const candleArbitrary = fc.record({
    time: fc.integer({ min: 1600000000, max: 1700000000 }), // Unix timestamps
    open: fc.float({ min: 10000, max: 100000, noNaN: true }),
    high: fc.float({ min: 10000, max: 100000, noNaN: true }),
    low: fc.float({ min: 10000, max: 100000, noNaN: true }),
    close: fc.float({ min: 10000, max: 100000, noNaN: true }),
    volume: fc.float({ min: 0, max: 10000, noNaN: true })
}).map(c => ({
    ...c,
    // Ensure OHLC validity: high >= max(open, close), low <= min(open, close)
    high: Math.max(c.high, c.open, c.close),
    low: Math.min(c.low, c.open, c.close)
}));

const timeframeArbitrary = fc.constantFrom<Timeframe>('1m', '15m', '1h');

describe('CandleAggregator', () => {
    describe('getCandleStartTime', () => {
        /**
         * Property: Start time is always a multiple of interval seconds
         *
         * **Feature: desktop-trading-dashboard, Property 1: Client-Side Candle Aggregation Correctness**
         * **Validates: Requirements 2.5**
         */
        it('should return a time that is a multiple of interval seconds', () => {
            fc.assert(
                fc.property(
                    fc.integer({ min: 1600000000, max: 1700000000 }),
                    timeframeArbitrary,
                    (timestamp, timeframe) => {
                        const startTime = getCandleStartTime(timestamp, timeframe);
                        const interval = getIntervalSeconds(timeframe);

                        expect(startTime % interval).toBe(0);
                    }
                ),
                { numRuns: 100 }
            );
        });

        /**
         * Property: Start time is always <= original timestamp
         *
         * **Feature: desktop-trading-dashboard, Property 1: Client-Side Candle Aggregation Correctness**
         * **Validates: Requirements 2.5**
         */
        it('should return a time <= original timestamp', () => {
            fc.assert(
                fc.property(
                    fc.integer({ min: 1600000000, max: 1700000000 }),
                    timeframeArbitrary,
                    (timestamp, timeframe) => {
                        const startTime = getCandleStartTime(timestamp, timeframe);

                        expect(startTime).toBeLessThanOrEqual(timestamp);
                    }
                ),
                { numRuns: 100 }
            );
        });

        /**
         * Property: Start time + interval > original timestamp
         *
         * **Feature: desktop-trading-dashboard, Property 1: Client-Side Candle Aggregation Correctness**
         * **Validates: Requirements 2.5**
         */
        it('should return a time where startTime + interval > timestamp', () => {
            fc.assert(
                fc.property(
                    fc.integer({ min: 1600000000, max: 1700000000 }),
                    timeframeArbitrary,
                    (timestamp, timeframe) => {
                        const startTime = getCandleStartTime(timestamp, timeframe);
                        const interval = getIntervalSeconds(timeframe);

                        expect(startTime + interval).toBeGreaterThan(timestamp);
                    }
                ),
                { numRuns: 100 }
            );
        });
    });

    describe('aggregateCandle', () => {
        /**
         * Property: Aggregating preserves the first open price
         *
         * **Feature: desktop-trading-dashboard, Property 1: Client-Side Candle Aggregation Correctness**
         * **Validates: Requirements 2.5**
         */
        it('should preserve the first open price when updating', () => {
            fc.assert(
                fc.property(
                    candleArbitrary,
                    candleArbitrary,
                    timeframeArbitrary,
                    (firstCandle, secondCandle, timeframe) => {
                        // Make second candle in same period
                        const interval = getIntervalSeconds(timeframe);
                        const startTime = getCandleStartTime(firstCandle.time, timeframe);
                        const adjustedSecond = {
                            ...secondCandle,
                            time: startTime + Math.floor(interval / 2) // Middle of period
                        };

                        const firstResult = aggregateCandle(null, { ...firstCandle, time: startTime }, timeframe);
                        const secondResult = aggregateCandle(firstResult.candle, adjustedSecond, timeframe);

                        // Open should be preserved from first candle
                        expect(secondResult.candle.open).toBe(firstResult.candle.open);
                    }
                ),
                { numRuns: 50 }
            );
        });

        /**
         * Property: High is always the maximum of all highs
         *
         * **Feature: desktop-trading-dashboard, Property 1: Client-Side Candle Aggregation Correctness**
         * **Validates: Requirements 2.5**
         */
        it('should track the highest high', () => {
            fc.assert(
                fc.property(
                    candleArbitrary,
                    candleArbitrary,
                    timeframeArbitrary,
                    (firstCandle, secondCandle, timeframe) => {
                        const interval = getIntervalSeconds(timeframe);
                        const startTime = getCandleStartTime(firstCandle.time, timeframe);
                        const adjustedSecond = {
                            ...secondCandle,
                            time: startTime + Math.floor(interval / 2)
                        };

                        const firstResult = aggregateCandle(null, { ...firstCandle, time: startTime }, timeframe);
                        const secondResult = aggregateCandle(firstResult.candle, adjustedSecond, timeframe);

                        const expectedHigh = Math.max(firstResult.candle.high, adjustedSecond.high);
                        expect(secondResult.candle.high).toBe(expectedHigh);
                    }
                ),
                { numRuns: 50 }
            );
        });

        /**
         * Property: Low is always the minimum of all lows
         *
         * **Feature: desktop-trading-dashboard, Property 1: Client-Side Candle Aggregation Correctness**
         * **Validates: Requirements 2.5**
         */
        it('should track the lowest low', () => {
            fc.assert(
                fc.property(
                    candleArbitrary,
                    candleArbitrary,
                    timeframeArbitrary,
                    (firstCandle, secondCandle, timeframe) => {
                        const interval = getIntervalSeconds(timeframe);
                        const startTime = getCandleStartTime(firstCandle.time, timeframe);
                        const adjustedSecond = {
                            ...secondCandle,
                            time: startTime + Math.floor(interval / 2)
                        };

                        const firstResult = aggregateCandle(null, { ...firstCandle, time: startTime }, timeframe);
                        const secondResult = aggregateCandle(firstResult.candle, adjustedSecond, timeframe);

                        const expectedLow = Math.min(firstResult.candle.low, adjustedSecond.low);
                        expect(secondResult.candle.low).toBe(expectedLow);
                    }
                ),
                { numRuns: 50 }
            );
        });

        /**
         * Property: Close is always the last candle's close
         *
         * **Feature: desktop-trading-dashboard, Property 1: Client-Side Candle Aggregation Correctness**
         * **Validates: Requirements 2.5**
         */
        it('should use the last close as aggregated close', () => {
            fc.assert(
                fc.property(
                    candleArbitrary,
                    candleArbitrary,
                    timeframeArbitrary,
                    (firstCandle, secondCandle, timeframe) => {
                        const interval = getIntervalSeconds(timeframe);
                        const startTime = getCandleStartTime(firstCandle.time, timeframe);
                        const adjustedSecond = {
                            ...secondCandle,
                            time: startTime + Math.floor(interval / 2)
                        };

                        const firstResult = aggregateCandle(null, { ...firstCandle, time: startTime }, timeframe);
                        const secondResult = aggregateCandle(firstResult.candle, adjustedSecond, timeframe);

                        expect(secondResult.candle.close).toBe(adjustedSecond.close);
                    }
                ),
                { numRuns: 50 }
            );
        });

        /**
         * Property: New candle period creates new candle
         *
         * **Feature: desktop-trading-dashboard, Property 1: Client-Side Candle Aggregation Correctness**
         * **Validates: Requirements 2.5**
         */
        it('should create new candle when period changes', () => {
            fc.assert(
                fc.property(
                    candleArbitrary,
                    candleArbitrary,
                    timeframeArbitrary,
                    (firstCandle, secondCandle, timeframe) => {
                        const interval = getIntervalSeconds(timeframe);
                        const startTime = getCandleStartTime(firstCandle.time, timeframe);

                        // Put second candle in next period
                        const nextPeriodCandle = {
                            ...secondCandle,
                            time: startTime + interval + 1
                        };

                        const firstResult = aggregateCandle(null, { ...firstCandle, time: startTime }, timeframe);
                        const secondResult = aggregateCandle(firstResult.candle, nextPeriodCandle, timeframe);

                        expect(secondResult.isNewCandle).toBe(true);
                        expect(secondResult.candle.open).toBe(nextPeriodCandle.open);
                    }
                ),
                { numRuns: 50 }
            );
        });
    });

    describe('aggregateCandles', () => {
        /**
         * Property: Aggregated candles are sorted by time
         *
         * **Feature: desktop-trading-dashboard, Property 1: Client-Side Candle Aggregation Correctness**
         * **Validates: Requirements 2.5**
         */
        it('should return candles sorted by time ascending', () => {
            fc.assert(
                fc.property(
                    fc.array(candleArbitrary, { minLength: 1, maxLength: 100 }),
                    fc.constantFrom<Timeframe>('15m', '1h'),
                    (candles, timeframe) => {
                        // Sort input candles by time
                        const sortedInput = [...candles].sort((a, b) => a.time - b.time);
                        const aggregated = aggregateCandles(sortedInput, timeframe);

                        for (let i = 1; i < aggregated.length; i++) {
                            expect(aggregated[i].time).toBeGreaterThan(aggregated[i - 1].time);
                        }
                    }
                ),
                { numRuns: 30 }
            );
        });

        /**
         * Property: All aggregated candle times are multiples of interval
         *
         * **Feature: desktop-trading-dashboard, Property 1: Client-Side Candle Aggregation Correctness**
         * **Validates: Requirements 2.5**
         */
        it('should have all candle times as multiples of interval', () => {
            fc.assert(
                fc.property(
                    fc.array(candleArbitrary, { minLength: 1, maxLength: 50 }),
                    fc.constantFrom<Timeframe>('15m', '1h'),
                    (candles, timeframe) => {
                        const sortedInput = [...candles].sort((a, b) => a.time - b.time);
                        const aggregated = aggregateCandles(sortedInput, timeframe);
                        const interval = getIntervalSeconds(timeframe);

                        for (const candle of aggregated) {
                            expect(candle.time % interval).toBe(0);
                        }
                    }
                ),
                { numRuns: 30 }
            );
        });

        /**
         * Property: 1m timeframe returns input unchanged (identity)
         *
         * **Feature: desktop-trading-dashboard, Property 1: Client-Side Candle Aggregation Correctness**
         * **Validates: Requirements 2.5**
         */
        it('should return input unchanged for 1m timeframe', () => {
            fc.assert(
                fc.property(
                    fc.array(candleArbitrary, { minLength: 1, maxLength: 20 }),
                    (candles) => {
                        const aggregated = aggregateCandles(candles, '1m');

                        expect(aggregated.length).toBe(candles.length);
                        expect(aggregated).toEqual(candles);
                    }
                ),
                { numRuns: 30 }
            );
        });
    });

    describe('isInSameCandlePeriod', () => {
        /**
         * Property: Same period check is consistent with getCandleStartTime
         *
         * **Feature: desktop-trading-dashboard, Property 1: Client-Side Candle Aggregation Correctness**
         * **Validates: Requirements 2.5**
         */
        it('should be consistent with getCandleStartTime', () => {
            fc.assert(
                fc.property(
                    fc.integer({ min: 1600000000, max: 1700000000 }),
                    fc.integer({ min: 1600000000, max: 1700000000 }),
                    timeframeArbitrary,
                    (timestamp1, timestamp2, timeframe) => {
                        const startTime1 = getCandleStartTime(timestamp1, timeframe);
                        const startTime2 = getCandleStartTime(timestamp2, timeframe);

                        const inSamePeriod = isInSameCandlePeriod(timestamp2, startTime1, timeframe);

                        expect(inSamePeriod).toBe(startTime1 === startTime2);
                    }
                ),
                { numRuns: 100 }
            );
        });
    });

    describe('getTimeUntilNextCandle', () => {
        /**
         * Property: Time until next candle is always positive and <= interval
         *
         * **Feature: desktop-trading-dashboard, Property 1: Client-Side Candle Aggregation Correctness**
         * **Validates: Requirements 2.5**
         */
        it('should return positive value <= interval', () => {
            fc.assert(
                fc.property(
                    fc.integer({ min: 1600000000, max: 1700000000 }),
                    timeframeArbitrary,
                    (timestamp, timeframe) => {
                        const timeUntil = getTimeUntilNextCandle(timestamp, timeframe);
                        const interval = getIntervalSeconds(timeframe);

                        expect(timeUntil).toBeGreaterThan(0);
                        expect(timeUntil).toBeLessThanOrEqual(interval);
                    }
                ),
                { numRuns: 100 }
            );
        });
    });
});
