import { useState, useCallback } from 'react';
import { LAMBDA_UNLOCK_URL, LAMBDA_SECRET_KEY } from '../config/api';

export interface UnlockResult {
  success: boolean;
  message: string;
  ip?: string;
  ports?: number[];
}

/**
 * SOTA: Fetch client's IPv4 address from external service.
 * This ensures we always get IPv4, even if client is on IPv6 network.
 * EC2 only accepts IPv4 connections, so we must use IPv4 for Security Group rules.
 */
async function getClientIPv4(): Promise<string | null> {
  const IPV4_SERVICES = [
    'https://api.ipify.org?format=text',      // Primary - IPv4 only
    'https://ipv4.icanhazip.com',              // Fallback 1
    'https://api4.my-ip.io/ip.txt',            // Fallback 2
  ];

  for (const url of IPV4_SERVICES) {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 5000);

      const response = await fetch(url, {
        signal: controller.signal,
        mode: 'cors'
      });
      clearTimeout(timeoutId);

      const ip = (await response.text()).trim();

      // Validate IPv4 format: xxx.xxx.xxx.xxx
      if (/^(\d{1,3}\.){3}\d{1,3}$/.test(ip)) {
        console.log(`[UnlockAccess] Got IPv4 from ${url}: ${ip}`);
        return ip;
      }
    } catch (e) {
      console.warn(`[UnlockAccess] Failed to fetch IPv4 from ${url}:`, e);
    }
  }

  console.error('[UnlockAccess] Could not fetch IPv4 from any service');
  return null;
}

export function useUnlockAccess() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<UnlockResult | null>(null);

  const isConfigured = Boolean(LAMBDA_UNLOCK_URL && LAMBDA_SECRET_KEY);

  const unlock = useCallback(async (): Promise<UnlockResult> => {
    // Check configuration
    if (!LAMBDA_UNLOCK_URL || !LAMBDA_SECRET_KEY) {
      const errorResult: UnlockResult = {
        success: false,
        message: 'Lambda unlock is not configured. Check your local frontend env.'
      };
      setResult(errorResult);
      return errorResult;
    }

    setLoading(true);
    setResult(null);

    try {
      // SOTA: Fetch IPv4 first to ensure we always use IPv4 for EC2 connection
      const ipv4 = await getClientIPv4();

      if (!ipv4) {
        const errorResult: UnlockResult = {
          success: false,
          message: 'Could not detect your IPv4 address'
        };
        setResult(errorResult);
        return errorResult;
      }

      // Call Lambda with explicit IPv4 parameter
      const response = await fetch(
        `${LAMBDA_UNLOCK_URL}?key=${encodeURIComponent(LAMBDA_SECRET_KEY)}&ipv4=${encodeURIComponent(ipv4)}`,
        {
          method: 'GET',
          mode: 'cors',
        }
      );

      const data = await response.json();

      if (response.ok && data.success) {
        const successResult: UnlockResult = {
          success: true,
          message: data.message || 'Access granted!',
          ip: data.ip,
          ports: data.ports
        };
        setResult(successResult);
        return successResult;
      } else {
        const errorResult: UnlockResult = {
          success: false,
          message: data.error || `Failed (${response.status})`
        };
        setResult(errorResult);
        return errorResult;
      }
    } catch (error) {
      const networkError: UnlockResult = {
        success: false,
        message: error instanceof Error ? error.message : 'Network error'
      };
      setResult(networkError);
      return networkError;
    } finally {
      setLoading(false);
    }
  }, []);

  const clearResult = useCallback(() => {
    setResult(null);
  }, []);

  return {
    unlock,
    loading,
    result,
    clearResult,
    isConfigured
  };
}
