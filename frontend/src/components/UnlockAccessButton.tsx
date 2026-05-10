/**
 * UnlockAccessButton Component
 *
 * Button to call AWS Lambda and update EC2 Security Group with current IP.
 * Shows loading state and result (success with IP or error message).
 */

import React, { useEffect } from 'react';
import { Unlock, Loader2, CheckCircle, XCircle, AlertTriangle } from 'lucide-react';
import { useUnlockAccess } from '../hooks/useUnlockAccess';

interface UnlockAccessButtonProps {
  compact?: boolean;  // Compact mode for header
}

export const UnlockAccessButton: React.FC<UnlockAccessButtonProps> = ({ compact = false }) => {
  const { unlock, loading, result, clearResult, isConfigured } = useUnlockAccess();

  // Auto-clear result after 10 seconds
  useEffect(() => {
    if (result) {
      const timer = setTimeout(clearResult, 10000);
      return () => clearTimeout(timer);
    }
  }, [result, clearResult]);

  // Not configured - show warning
  if (!isConfigured) {
    return (
      <div
        title="Lambda URL not configured. Add VITE_LAMBDA_UNLOCK_URL and VITE_LAMBDA_SECRET_KEY to .env.local"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '4px',
          padding: compact ? '4px 8px' : '6px 10px',
          borderRadius: '6px',
          border: '1px solid #f59e0b',
          background: 'rgba(245, 158, 11, 0.1)',
          color: '#f59e0b',
          fontSize: compact ? '10px' : '12px',
          cursor: 'help',
        }}
      >
        <AlertTriangle size={compact ? 12 : 14} />
        {!compact && <span>Unlock N/A</span>}
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
      <button
        onClick={unlock}
        disabled={loading}
        title="Update Security Group with your current IP"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          padding: compact ? '4px 8px' : '6px 12px',
          borderRadius: '6px',
          border: result?.success ? '1px solid #10b981' : '1px solid #3b82f6',
          background: result?.success ? 'rgba(16, 185, 129, 0.1)' : 'transparent',
          color: result?.success ? '#10b981' : '#3b82f6',
          cursor: loading ? 'wait' : 'pointer',
          fontSize: compact ? '10px' : '12px',
          fontWeight: 600,
          transition: 'all 0.2s',
        }}
      >
        {loading ? (
          <Loader2 size={compact ? 12 : 14} style={{ animation: 'spin 1s linear infinite' }} />
        ) : result?.success ? (
          <CheckCircle size={compact ? 12 : 14} />
        ) : (
          <Unlock size={compact ? 12 : 14} />
        )}
        {!compact && (result?.success ? 'Unlocked' : 'Unlock')}
      </button>

      {/* Result indicator */}
      {result && !compact && (
        <span
          style={{
            fontSize: '11px',
            color: result.success ? '#10b981' : '#ef4444',
            display: 'flex',
            alignItems: 'center',
            gap: '4px',
            maxWidth: '150px',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
          title={result.message}
        >
          {result.success ? (
            <>
              <CheckCircle size={12} />
              IP: {result.ip}
            </>
          ) : (
            <>
              <XCircle size={12} />
              {result.message}
            </>
          )}
        </span>
      )}

      {/* Compact mode result indicator (Clickable for mobile since no tooltip) */}
      {result && compact && (
        <span
          onClick={(e) => {
            e.stopPropagation();
            alert(result.success ? `✅ Access Granted!\nIP: ${result.ip}` : `❌ Failed: ${result.message}`);
          }}
          style={{
            fontSize: '10px',
            color: result.success ? '#10b981' : '#ef4444',
            cursor: 'pointer',
            padding: '2px 4px', // Touch target
          }}
          title={result.success ? `IP: ${result.ip}` : result.message}
        >
          {result.success ? '✓' : '✗'}
        </span>
      )}

      {/* CSS for spin animation */}
      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
};

export default UnlockAccessButton;
