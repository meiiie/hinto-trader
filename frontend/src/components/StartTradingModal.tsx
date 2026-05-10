/**
 * StartTradingModal.tsx
 *
 * SOTA SAFE MODE Modal (Jan 2026)
 * Pattern: Two Sigma, Citadel - explicit user confirmation before trading
 *
 * Shows after backend restart to prevent ghost orders.
 * User must click "Bắt Đầu Trade" to activate trading.
 */

import React, { useState, useEffect } from 'react';
import { apiUrl } from '../config/api';
import { ShieldCheck, Rocket, Loader2, RefreshCw } from 'lucide-react';

const COLORS = {
    background: 'rgba(13, 17, 23, 0.95)',
    card: '#161b22',
    border: '#30363d',
    yellow: '#f0b90b',
    green: '#00c853',
    text: '#e6edf3',
    textSecondary: '#8b949e',
    overlay: 'rgba(0, 0, 0, 0.8)'
};

interface SafeModeStatus {
    safe_mode: boolean;
    enable_trading: boolean;
    mode: string;
    pending_signals: number;
    active_positions: number;
    trading_mode: string;
}

interface StartTradingModalProps {
    onActivated: () => void;
}

const StartTradingModal: React.FC<StartTradingModalProps> = ({ onActivated }) => {
    const [status, setStatus] = useState<SafeModeStatus | null>(null);
    const [loading, setLoading] = useState(true);
    const [activating, setActivating] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // Check safe mode status on mount
    useEffect(() => {
        checkSafeModeStatus();
    }, []);

    const checkSafeModeStatus = async () => {
        try {
            const response = await fetch(apiUrl('/live/safe-mode/status'));
            const data = await response.json();
            setStatus(data);
            setLoading(false);

            // If already trading, call onActivated
            if (data.enable_trading && !data.safe_mode) {
                onActivated();
            }
        } catch (err) {
            setError('Không thể kết nối backend');
            setLoading(false);
        }
    };

    const handleActivate = async () => {
        setActivating(true);
        setError(null);

        try {
            const response = await fetch(apiUrl('/live/safe-mode/activate?clear_old_data=true'), {
                method: 'POST'
            });

            if (!response.ok) {
                throw new Error('Kích hoạt thất bại');
            }

            const result = await response.json();
            console.log('🚀 Trading activated:', result);

            onActivated();
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Lỗi không xác định');
            setActivating(false);
        }
    };

    // Don't show if already trading
    if (status && status.enable_trading && !status.safe_mode) {
        return null;
    }

    if (loading) {
        return (
            <div style={{
                position: 'fixed',
                top: 0,
                left: 0,
                right: 0,
                bottom: 0,
                background: COLORS.overlay,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                zIndex: 9999
            }}>
                <div style={{ color: COLORS.text, fontSize: '18px', display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <RefreshCw className="animate-spin" size={24} />
                    Đang kiểm tra trạng thái...
                </div>
            </div>
        );
    }

    return (
        <div style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: COLORS.overlay,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 9999,
            backdropFilter: 'blur(8px)'
        }}>
            <div style={{
                background: COLORS.card,
                borderRadius: '16px',
                border: `1px solid ${COLORS.border}`,
                padding: '40px',
                maxWidth: '480px',
                width: '90%',
                textAlign: 'center',
                boxShadow: '0 20px 60px rgba(0, 0, 0, 0.5)'
            }}>
                {/* Icon */}
                <div style={{
                    marginBottom: '20px',
                    display: 'flex',
                    justifyContent: 'center'
                }}>
                    <ShieldCheck size={64} color={COLORS.yellow} />
                </div>

                {/* Title */}
                <h2 style={{
                    color: COLORS.yellow,
                    fontSize: '28px',
                    fontWeight: 'bold',
                    margin: '0 0 16px 0'
                }}>
                    Chế Độ An Toàn
                </h2>

                {/* Description */}
                <p style={{
                    color: COLORS.textSecondary,
                    fontSize: '16px',
                    lineHeight: '1.6',
                    margin: '0 0 24px 0'
                }}>
                    Backend vừa khởi động lại. Để tránh lệnh ma từ dữ liệu cũ,
                    hệ thống đang ở chế độ <strong style={{ color: COLORS.text }}>chỉ giám sát</strong>.
                    <br /><br />
                    Nhấn nút bên dưới để <strong style={{ color: COLORS.green }}>xóa dữ liệu cũ</strong> và bắt đầu giao dịch mới.
                </p>

                {/* Status Info */}
                {status && (
                    <div style={{
                        background: 'rgba(240, 185, 11, 0.1)',
                        border: `1px solid ${COLORS.yellow}`,
                        borderRadius: '8px',
                        padding: '16px',
                        marginBottom: '24px',
                        textAlign: 'left'
                    }}>
                        <div style={{ fontSize: '14px', color: COLORS.textSecondary }}>
                            📊 Mode: <span style={{ color: COLORS.text }}>{status.trading_mode?.toUpperCase()}</span>
                        </div>
                        <div style={{ fontSize: '14px', color: COLORS.textSecondary, marginTop: '8px' }}>
                            📍 Positions: <span style={{ color: COLORS.text }}>{status.active_positions}</span>
                        </div>
                        <div style={{ fontSize: '14px', color: COLORS.textSecondary, marginTop: '8px' }}>
                            ⏳ Pending signals (sẽ xóa): <span style={{ color: COLORS.yellow }}>{status.pending_signals}</span>
                        </div>
                    </div>
                )}

                {/* Error */}
                {error && (
                    <div style={{
                        background: 'rgba(244, 67, 54, 0.1)',
                        border: '1px solid #f44336',
                        borderRadius: '8px',
                        padding: '12px',
                        marginBottom: '24px',
                        color: '#f44336',
                        fontSize: '14px'
                    }}>
                        ❌ {error}
                    </div>
                )}

                {/* Activate Button */}
                <button
                    onClick={handleActivate}
                    disabled={activating}
                    style={{
                        background: activating
                            ? COLORS.textSecondary
                            : `linear-gradient(135deg, ${COLORS.yellow} 0%, #d4a00a 100%)`,
                        color: activating ? COLORS.text : '#000',
                        border: 'none',
                        borderRadius: '12px',
                        padding: '16px 40px',
                        fontSize: '18px',
                        fontWeight: 'bold',
                        cursor: activating ? 'not-allowed' : 'pointer',
                        transition: 'all 0.3s ease',
                        width: '100%',
                        boxShadow: activating ? 'none' : '0 4px 20px rgba(240, 185, 11, 0.4)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: '10px'
                    }}
                >
                    {activating ? (
                        <>
                            <Loader2 className="animate-spin" size={24} />
                            Đang kích hoạt...
                        </>
                    ) : (
                        <>
                            <Rocket size={24} />
                            Bắt Đầu Trade
                        </>
                    )}
                </button>

                {/* Warning */}
                <p style={{
                    color: COLORS.textSecondary,
                    fontSize: '12px',
                    marginTop: '16px',
                    fontStyle: 'italic'
                }}>
                    ⚠️ Nhấn nút sẽ xóa tất cả pending signals cũ và bắt đầu giao dịch mới
                </p>
            </div>
        </div>
    );
};

export default StartTradingModal;
