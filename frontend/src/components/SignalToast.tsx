/**
 * SignalToast - Real-time Signal Notification Component
 *
 * SOTA: Custom toast system for signal notifications.
 * Shows animated toast when new trading signals are received.
 */

import React, { useState, useEffect, useCallback, createContext, useContext } from 'react';

// --- TYPES ---
export interface SignalToastData {
    id: string;
    symbol: string;
    signalType: 'buy' | 'sell';
    entryPrice: number;
    stopLoss?: number;
    confidence?: number;
}

interface Toast {
    id: string;
    data: SignalToastData;
    createdAt: number;
}

// --- TOAST CONTEXT ---
interface ToastContextType {
    showSignalToast: (data: SignalToastData) => void;
}

const ToastContext = createContext<ToastContextType | null>(null);

export const useSignalToast = () => {
    const context = useContext(ToastContext);
    if (!context) {
        throw new Error('useSignalToast must be used within SignalToastProvider');
    }
    return context;
};

// --- COLORS ---
const COLORS = {
    buy: 'rgb(14, 203, 129)',
    sell: 'rgb(246, 70, 93)',
    bgPrimary: 'rgb(24, 26, 32)',
    bgSecondary: 'rgb(30, 35, 41)',
    textPrimary: 'rgb(234, 236, 239)',
    textSecondary: 'rgb(132, 142, 156)',
};

// --- TOAST ITEM COMPONENT ---
const ToastItem: React.FC<{ toast: Toast; onClose: (id: string) => void }> = ({ toast, onClose }) => {
    const { data } = toast;
    const isLong = data.signalType === 'buy';
    const sideColor = isLong ? COLORS.buy : COLORS.sell;

    useEffect(() => {
        // Auto dismiss after 5 seconds
        const timer = setTimeout(() => {
            onClose(toast.id);
        }, 5000);
        return () => clearTimeout(timer);
    }, [toast.id, onClose]);

    return (
        <div
            style={{
                background: COLORS.bgSecondary,
                border: `1px solid ${sideColor}`,
                borderRadius: '8px',
                padding: '12px 16px',
                boxShadow: `0 4px 20px ${sideColor}40`,
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                animation: 'slideIn 0.3s ease-out',
                minWidth: '280px',
            }}
        >
            {/* Icon */}
            <div style={{
                width: '40px',
                height: '40px',
                borderRadius: '8px',
                background: `${sideColor}20`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: '18px'
            }}>
                {isLong ? '📈' : '📉'}
            </div>

            {/* Content */}
            <div style={{ flex: 1 }}>
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    marginBottom: '4px'
                }}>
                    <span style={{
                        fontWeight: 700,
                        color: COLORS.textPrimary,
                        fontSize: '13px'
                    }}>
                        {data.symbol}
                    </span>
                    <span style={{
                        padding: '2px 6px',
                        borderRadius: '4px',
                        fontSize: '10px',
                        fontWeight: 700,
                        background: `${sideColor}30`,
                        color: sideColor
                    }}>
                        {isLong ? 'LONG' : 'SHORT'}
                    </span>
                </div>
                <div style={{
                    fontSize: '11px',
                    color: COLORS.textSecondary
                }}>
                    Entry: <span style={{
                        color: COLORS.textPrimary,
                        fontFamily: 'monospace'
                    }}>
                        ${data.entryPrice?.toFixed(2) || '0.00'}
                    </span>
                    {data.confidence && (
                        <span style={{ marginLeft: '8px' }}>
                            Conf: <span style={{ color: sideColor }}>
                                {(data.confidence * 100).toFixed(0)}%
                            </span>
                        </span>
                    )}
                </div>
            </div>

            {/* Close Button */}
            <button
                onClick={() => onClose(toast.id)}
                style={{
                    background: 'transparent',
                    border: 'none',
                    color: COLORS.textSecondary,
                    cursor: 'pointer',
                    fontSize: '16px',
                    padding: '4px',
                }}
            >
                ✕
            </button>
        </div>
    );
};

// --- TOAST PROVIDER ---
export const SignalToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [toasts, setToasts] = useState<Toast[]>([]);

    const showSignalToast = useCallback((data: SignalToastData) => {
        const newToast: Toast = {
            id: data.id || `toast_${Date.now()}`,
            data,
            createdAt: Date.now(),
        };

        setToasts(prev => {
            // Limit to 3 toasts max
            const updated = [newToast, ...prev].slice(0, 3);
            return updated;
        });

        console.log(`🎯 Signal Toast: ${data.signalType.toUpperCase()} ${data.symbol} @ $${data.entryPrice}`);
    }, []);

    const handleClose = useCallback((id: string) => {
        setToasts(prev => prev.filter(t => t.id !== id));
    }, []);

    // SOTA: Listen for custom events from Portfolio component
    useEffect(() => {
        const handleToastEvent = (event: CustomEvent<SignalToastData>) => {
            showSignalToast(event.detail);
        };

        window.addEventListener('signalToast', handleToastEvent as EventListener);

        return () => {
            window.removeEventListener('signalToast', handleToastEvent as EventListener);
        };
    }, [showSignalToast]);

    return (
        <ToastContext.Provider value={{ showSignalToast }}>
            {children}

            {/* Toast Container - Fixed position at top-right */}
            {toasts.length > 0 && (
                <div style={{
                    position: 'fixed',
                    top: '80px',
                    right: '20px',
                    zIndex: 9999,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '8px',
                }}>
                    {toasts.map(toast => (
                        <ToastItem
                            key={toast.id}
                            toast={toast}
                            onClose={handleClose}
                        />
                    ))}
                </div>
            )}

            {/* CSS Animation */}
            <style>{`
                @keyframes slideIn {
                    from {
                        opacity: 0;
                        transform: translateX(100%);
                    }
                    to {
                        opacity: 1;
                        transform: translateX(0);
                    }
                }
            `}</style>
        </ToastContext.Provider>
    );
};

export default SignalToastProvider;
