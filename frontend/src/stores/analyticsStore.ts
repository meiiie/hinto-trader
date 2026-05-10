/**
 * Analytics Store — v6.3.0 Binance Truth
 *
 * Zustand store with stale-while-revalidate caching.
 * Parallel fetch for all analytics sections.
 */

import { create } from 'zustand';
import { analyticsApi } from '../services/analyticsService';
import type {
    AnalyticsSummary,
    SessionData,
    SymbolDecomposition,
    DirectionData,
    TodayMetrics,
    SnapshotData,
} from '../services/analyticsService';

const STALE_MS = 60_000; // 60s cache

interface AnalyticsState {
    // Data
    summary: AnalyticsSummary | null;
    sessions: SessionData | null;
    symbols: SymbolDecomposition | null;
    directions: DirectionData | null;
    today: TodayMetrics | null;
    snapshots: SnapshotData[];

    // UI
    isLoading: boolean;
    error: string | null;
    lastFetch: number;
    versionFilter: string | undefined;

    // Actions
    setVersionFilter: (v: string | undefined) => void;
    fetchAll: () => Promise<void>;
    fetchSummary: () => Promise<void>;
    fetchToday: () => Promise<void>;
    reconcile: () => Promise<{ trades_collected: number; new_trades: number } | null>;
}

export const useAnalyticsStore = create<AnalyticsState>((set, get) => ({
    summary: null,
    sessions: null,
    symbols: null,
    directions: null,
    today: null,
    snapshots: [],
    isLoading: false,
    error: null,
    lastFetch: 0,
    versionFilter: undefined,

    setVersionFilter: (v) => set({ versionFilter: v }),

    fetchAll: async () => {
        const { lastFetch, isLoading, versionFilter } = get();
        if (isLoading) return;
        if (Date.now() - lastFetch < STALE_MS) return;

        set({ isLoading: true, error: null });
        try {
            const [summary, sessions, symbols, directions, today, snapshotsRes] =
                await Promise.all([
                    analyticsApi.getSummary(versionFilter),
                    analyticsApi.getSessions(versionFilter),
                    analyticsApi.getSymbols(versionFilter),
                    analyticsApi.getDirections(versionFilter),
                    analyticsApi.getToday(),
                    analyticsApi.getSnapshots(30),
                ]);

            set({
                summary,
                sessions,
                symbols,
                directions,
                today,
                snapshots: snapshotsRes.snapshots || [],
                isLoading: false,
                lastFetch: Date.now(),
                error: null,
            });
        } catch (e: unknown) {
            const msg = e instanceof Error ? e.message : 'Analytics fetch failed';
            set({ isLoading: false, error: msg });
        }
    },

    fetchSummary: async () => {
        try {
            const { versionFilter } = get();
            const summary = await analyticsApi.getSummary(versionFilter);
            set({ summary });
        } catch (e: unknown) {
            const msg = e instanceof Error ? e.message : 'Summary fetch failed';
            set({ error: msg });
        }
    },

    fetchToday: async () => {
        try {
            const today = await analyticsApi.getToday();
            set({ today });
        } catch {
            // Silent — today is supplementary
        }
    },

    reconcile: async () => {
        try {
            const result = await analyticsApi.reconcile();
            // Refresh after reconcile
            set({ lastFetch: 0 });
            get().fetchAll();
            return result;
        } catch (e: unknown) {
            const msg = e instanceof Error ? e.message : 'Reconciliation failed';
            set({ error: msg });
            return null;
        }
    },
}));

export default useAnalyticsStore;
