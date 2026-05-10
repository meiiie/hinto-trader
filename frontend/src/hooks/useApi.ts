/**
 * useApi - Custom hook for API calls
 *
 * Centralizes all API calls to follow Clean Architecture.
 * Components should use this hook instead of direct fetch() calls.
 */

import { useState, useCallback } from 'react';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

interface ApiState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

interface UseApiReturn<T> extends ApiState<T> {
  execute: () => Promise<T | null>;
  reset: () => void;
}

/**
 * Generic API hook for GET requests
 */
export function useApiGet<T>(endpoint: string): UseApiReturn<T> {
  const [state, setState] = useState<ApiState<T>>({
    data: null,
    loading: false,
    error: null,
  });

  const execute = useCallback(async (): Promise<T | null> => {
    setState(prev => ({ ...prev, loading: true, error: null }));

    try {
      const response = await fetch(`${API_BASE_URL}${endpoint}`);

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      setState({ data, loading: false, error: null });
      return data;
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      setState({ data: null, loading: false, error: errorMessage });
      return null;
    }
  }, [endpoint]);

  const reset = useCallback(() => {
    setState({ data: null, loading: false, error: null });
  }, []);

  return { ...state, execute, reset };
}

/**
 * Generic API hook for POST requests
 */
export function useApiPost<T, B = unknown>(endpoint: string): {
  data: T | null;
  loading: boolean;
  error: string | null;
  execute: (body: B) => Promise<T | null>;
  reset: () => void;
} {
  const [state, setState] = useState<ApiState<T>>({
    data: null,
    loading: false,
    error: null,
  });

  const execute = useCallback(async (body: B): Promise<T | null> => {
    setState(prev => ({ ...prev, loading: true, error: null }));

    try {
      const response = await fetch(`${API_BASE_URL}${endpoint}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      setState({ data, loading: false, error: null });
      return data;
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      setState({ data: null, loading: false, error: errorMessage });
      return null;
    }
  }, [endpoint]);

  const reset = useCallback(() => {
    setState({ data: null, loading: false, error: null });
  }, []);

  return { ...state, execute, reset };
}

// ============================================
// Specific API hooks for each domain
// ============================================

export interface HealthStatus {
  status: string;
  timestamp: string;
}

export function useHealthCheck() {
  return useApiGet<HealthStatus>('/api/health');
}

export interface SettingsData {
  symbol: string;
  interval: string;
  risk_per_trade: number;
  max_positions: number;
  auto_trading: boolean;
}

export function useSettings() {
  const get = useApiGet<SettingsData>('/api/settings');
  const post = useApiPost<SettingsData, Partial<SettingsData>>('/api/settings');

  return {
    settings: get.data,
    loading: get.loading || post.loading,
    error: get.error || post.error,
    fetchSettings: get.execute,
    updateSettings: post.execute,
  };
}

export interface PortfolioData {
  balance: number;
  positions: Array<{
    id: string;
    symbol: string;
    side: string;
    quantity: number;
    entry_price: number;
    current_price: number;
    unrealized_pnl: number;
  }>;
}

export function usePortfolio() {
  return useApiGet<PortfolioData>('/api/portfolio');
}

export interface TradeHistoryItem {
  id: string;
  symbol: string;
  side: string;
  entry_price: number;
  exit_price: number;
  quantity: number;
  realized_pnl: number;
  open_time: string;
  close_time: string;
}

export function useTradeHistory(limit: number = 50) {
  return useApiGet<TradeHistoryItem[]>(`/api/trades/history?limit=${limit}`);
}

export interface PerformanceMetrics {
  total_trades: number;
  win_rate: number;
  total_pnl: number;
  avg_win: number;
  avg_loss: number;
  profit_factor: number;
}

export function usePerformanceMetrics() {
  return useApiGet<PerformanceMetrics>('/api/performance');
}

export interface CandleData {
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export function useHistoricalCandles(symbol: string, interval: string, limit: number = 100) {
  return useApiGet<CandleData[]>(`/api/market/candles?symbol=${symbol}&interval=${interval}&limit=${limit}`);
}
