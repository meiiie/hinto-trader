import React, { useState, useEffect } from 'react';
import { THEME } from '../styles/theme';
import { apiUrl, ENDPOINTS } from '../config/api';

interface SystemStatus {
    status: string;
    service: string;
    version: string;
    uptime?: number;
    connections?: number;
}

interface ReconnectState {
    isReconnecting: boolean;
    retryCount: number;
    nextRetryIn: number;
}

interface ConnectionStatusProps {
    isConnected: boolean;
    error?: string | null;
    reconnectState?: ReconnectState;
    onReconnectNow?: () => void;
}

/**
 * Connection Status Component - Binance Style
 * Shows Online/Offline/Reconnecting indicator with countdown
 *
 * **Feature: desktop-trading-dashboard**
 * **Validates: Requirements 1.1 - WebSocket connection status**
 */
const ConnectionStatus: React.FC<ConnectionStatusProps> = ({
    isConnected,
    error,
    reconnectState,
    onReconnectNow
}) => {
    const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);

    useEffect(() => {
        const fetchStatus = async () => {
            try {
                const response = await fetch(apiUrl(ENDPOINTS.SYSTEM_STATUS));
                if (response.ok) {
                    const data = await response.json();
                    setSystemStatus(data);
                }
            } catch (err) {
                console.error('Failed to fetch system status:', err);
            }
        };

        fetchStatus();
        const interval = setInterval(fetchStatus, 30000);
        return () => clearInterval(interval);
    }, []);

    const isReconnecting = reconnectState?.isReconnecting || false;

    const getStatusConfig = () => {
        if (isConnected) {
            return {
                color: THEME.status.buy,
                bg: THEME.alpha.buyBg,
                text: 'Live',
                icon: '🟢',
                showPulse: true
            };
        }
        if (isReconnecting) {
            const countdown = reconnectState?.nextRetryIn || 0;
            const retryNum = (reconnectState?.retryCount || 0) + 1;
            return {
                color: THEME.accent.yellow,
                bg: THEME.alpha.warningBg,
                text: `Reconnecting in ${countdown}s... (attempt ${retryNum})`,
                icon: '🟡',
                showPulse: true
            };
        }
        return {
            color: THEME.status.sell,
            bg: THEME.alpha.sellBg,
            text: 'Disconnected',
            icon: '🔴',
            showPulse: false
        };
    };

    const status = getStatusConfig();
    const showReconnectButton = !isConnected && onReconnectNow;

    return (
        <div
            style={{
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                borderRadius: '8px',
                padding: '8px 12px',
                backgroundColor: THEME.bg.secondary
            }}
        >
            {/* Status Indicator */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <div
                    style={{
                        width: '8px',
                        height: '8px',
                        borderRadius: '50%',
                        backgroundColor: status.color,
                        animation: status.showPulse ? 'pulse 2s infinite' : 'none'
                    }}
                />
                <span
                    style={{
                        fontSize: '12px',
                        fontWeight: 500,
                        color: status.color
                    }}
                >
                    {status.text}
                </span>
            </div>

            {/* Reconnect Now Button */}
            {showReconnectButton && (
                <>
                    <div style={{ width: '1px', height: '16px', backgroundColor: THEME.border.primary }} />
                    <button
                        onClick={onReconnectNow}
                        style={{
                            padding: '4px 8px',
                            fontSize: '11px',
                            fontWeight: 600,
                            color: THEME.text.primary,
                            backgroundColor: THEME.accent.yellow,
                            border: 'none',
                            borderRadius: '4px',
                            cursor: 'pointer',
                            transition: 'opacity 0.2s'
                        }}
                        onMouseOver={(e) => e.currentTarget.style.opacity = '0.8'}
                        onMouseOut={(e) => e.currentTarget.style.opacity = '1'}
                    >
                        Reconnect Now
                    </button>
                </>
            )}

            {/* Divider */}
            <div style={{ width: '1px', height: '16px', backgroundColor: THEME.border.primary }} />

            {/* Service Info */}
            {systemStatus && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: THEME.text.tertiary }}>
                    <span style={{ fontWeight: 600, color: THEME.text.secondary }}>{systemStatus.service}</span>
                    <span>v{systemStatus.version}</span>
                </div>
            )}

            {/* Error Message */}
            {error && (
                <>
                    <div style={{ width: '1px', height: '16px', backgroundColor: THEME.border.primary }} />
                    <span style={{ fontSize: '12px', color: THEME.status.sell }}>{error}</span>
                </>
            )}

            {/* CSS for pulse animation */}
            <style>{`
                @keyframes pulse {
                    0%, 100% { opacity: 1; }
                    50% { opacity: 0.5; }
                }
            `}</style>
        </div>
    );
};

export default ConnectionStatus;
