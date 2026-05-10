/**
 * WebSocketStatus - Connection status indicator for realtime data
 *
 * SOTA (Jan 2026): Multi-position realtime prices
 * Shows connection status: 🟢 Live / 🟡 Reconnecting / 🔴 Polling
 */

import React from 'react';
import { useConnectionState } from '../stores/marketStore';

const COLORS = {
    live: 'rgb(14, 203, 129)',      // Green
    reconnecting: 'rgb(240, 185, 11)', // Yellow
    polling: 'rgb(246, 70, 93)',    // Red
    textSecondary: 'rgb(132, 142, 156)',
};

interface WebSocketStatusProps {
    compact?: boolean;  // Show only icon without text
}

export const WebSocketStatus: React.FC<WebSocketStatusProps> = ({ compact = false }) => {
    const connection = useConnectionState();

    // Determine status
    const getStatus = () => {
        if (connection.isConnected) {
            return { icon: '🟢', text: 'Live', color: COLORS.live };
        } else if (connection.isReconnecting) {
            return {
                icon: '🟡',
                text: `Reconnecting${connection.nextRetryIn > 0 ? ` (${connection.nextRetryIn}s)` : '...'}`,
                color: COLORS.reconnecting
            };
        } else {
            return { icon: '🔴', text: 'Disconnected', color: COLORS.polling };
        }
    };

    const status = getStatus();

    if (compact) {
        return (
            <span
                title={`WebSocket: ${status.text}`}
                style={{
                    fontSize: '12px',
                    cursor: 'help'
                }}
            >
                {status.icon}
            </span>
        );
    }

    return (
        <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            fontSize: '11px',
            color: COLORS.textSecondary
        }}>
            <span style={{ fontSize: '10px' }}>{status.icon}</span>
            <span style={{ color: status.color, fontWeight: 500 }}>
                {status.text}
            </span>
            {connection.error && (
                <span style={{ color: COLORS.polling, fontSize: '10px' }}>
                    ({connection.error})
                </span>
            )}
        </div>
    );
};

export default WebSocketStatus;
