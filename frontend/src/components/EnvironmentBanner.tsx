import React, { useEffect, useState } from 'react';
import { AlertTriangle, Shield, TestTube, FileText, Power, Loader2 } from 'lucide-react';
import { apiUrl, ENDPOINTS } from '../config/api';

interface EnvironmentConfig {
    environment: 'paper' | 'testnet' | 'live';
    execution_mode?: 'paper' | 'paper_real' | 'testnet' | 'live';
    is_paper_real?: boolean;
    is_production: boolean;
    real_ordering_enabled?: boolean;
    market_data_source?: string;
    execution_venue?: string;
    db_path: string;
    warning: string | null;
}

interface EnvironmentBannerProps {
    showModeSelector?: boolean;
    showKillSwitch?: boolean;
    compact?: boolean;  // Compact mode for mobile - hide mode selector buttons
    onModeChange?: (newMode: string, balance: number) => void;
}

/**
 * Environment Banner Component
 *
 * SOTA: Always-visible indicator of current trading environment.
 * - Paper: Green (safe)
 * - Testnet: Yellow (demo money)
 * - Live: Red flashing (real money!)
 *
 * Features:
 * - Mode switching with loading modal
 * - Per-environment cache preservation
 * - Emergency kill switch
 */
const EnvironmentBanner: React.FC<EnvironmentBannerProps> = ({
    showModeSelector = true,
    showKillSwitch = true,
    compact = false,
    onModeChange
}) => {
    const [config, setConfig] = useState<EnvironmentConfig | null>(null);
    const [loading, setLoading] = useState(true);
    const [switching, setSwitching] = useState(false);
    const [switchingTo, setSwitchingTo] = useState<string | null>(null);
    const [killSwitchActive, setKillSwitchActive] = useState(false);

    // Fetch current environment
    const fetchConfig = async () => {
        try {
            const response = await fetch(apiUrl(ENDPOINTS.SYSTEM.CONFIG));
            const data = await response.json();
            setConfig(data);
        } catch (error) {
            console.error('Failed to fetch environment config:', error);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchConfig();
        // Poll every 30 seconds
        const interval = setInterval(fetchConfig, 30000);
        return () => clearInterval(interval);
    }, []);

    // Switch mode (paper ↔ testnet only) - kept for future UI integration
    // @ts-expect-error Intentionally unused, preserved for future mode switching UI
    const _switchMode = async (newMode: 'paper' | 'testnet') => {
        if (config?.environment === 'live') {
            alert('Cannot switch from Live mode at runtime. Restart the server.');
            return;
        }

        if (config?.environment === newMode) {
            return; // Already in this mode
        }

        setSwitching(true);
        setSwitchingTo(newMode);

        try {
            const response = await fetch(apiUrl(ENDPOINTS.SYSTEM.MODE(newMode)), {
                method: 'POST'
            });
            const result = await response.json();

            if (result.success) {
                await fetchConfig();

                // Notify parent of mode change with new balance
                if (onModeChange) {
                    onModeChange(newMode, result.balance || 0);
                }

                // Force refresh header stats after mode switch
                window.dispatchEvent(new CustomEvent('mode-changed', {
                    detail: { mode: newMode, balance: result.balance }
                }));
            } else {
                alert(result.error || 'Failed to switch mode');
            }
        } catch (error) {
            console.error('Failed to switch mode:', error);
            alert('Failed to switch mode');
        } finally {
            setSwitching(false);
            setSwitchingTo(null);
        }
    };

    // Emergency stop
    const handleEmergencyStop = async () => {
        if (!confirm('🚨 EMERGENCY STOP?\n\nThis will:\n- Cancel ALL orders\n- Close ALL positions\n- Disable trading\n\nAre you sure?')) {
            return;
        }

        setKillSwitchActive(true);
        try {
            const response = await fetch(apiUrl(ENDPOINTS.SYSTEM.EMERGENCY_STOP), {
                method: 'POST'
            });
            const result = await response.json();

            if (result.success) {
                alert('🚨 Emergency Stop Complete!\n\nAll orders cancelled, positions closed, trading disabled.');
            } else {
                alert(`Emergency Stop had errors:\n${result.errors?.join('\n') || 'Unknown error'}`);
            }
        } catch (error) {
            console.error('Emergency stop failed:', error);
            alert('Failed to execute emergency stop!');
        } finally {
            setKillSwitchActive(false);
        }
    };

    if (loading) {
        return (
            <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                padding: '8px 16px',
                backgroundColor: '#1a1a2e',
                borderBottom: '2px solid #333',
                color: '#888',
                fontSize: '13px'
            }}>
                <Loader2 size={16} style={{ animation: 'spin 1s linear infinite', marginRight: '8px' }} />
                Loading environment...
            </div>
        );
    }

    if (!config) {
        return null;
    }

    const isPaperReal = config.environment === 'paper' && (
        config.execution_mode === 'paper_real' || config.is_paper_real === true
    );

    const envConfig = {
        paper: {
            icon: <FileText size={16} />,
            label: isPaperReal ? 'PAPER-REAL MODE' : 'PAPER MODE',
            description: isPaperReal ? 'Live Binance data, simulated orders' : 'Simulated Trading',
            bgColor: isPaperReal ? '#10231f' : '#1a472a',
            borderColor: isPaperReal ? '#10b981' : '#22c55e',
            textColor: isPaperReal ? '#34d399' : '#22c55e'
        },
        testnet: {
            icon: <TestTube size={16} />,
            label: 'TESTNET MODE',
            description: 'Binance Demo',
            bgColor: '#422006',
            borderColor: '#f59e0b',
            textColor: '#f59e0b'
        },
        live: {
            icon: <AlertTriangle size={16} />,
            label: '⚠️ LIVE MODE',
            description: 'REAL MONEY!',
            bgColor: '#450a0a',
            borderColor: '#ef4444',
            textColor: '#ef4444'
        }
    };

    const current = envConfig[config.environment];

    return (
        <>
            {/* Switching Modal Overlay */}
            {switching && (
                <div style={{
                    position: 'fixed',
                    top: 0,
                    left: 0,
                    right: 0,
                    bottom: 0,
                    backgroundColor: 'rgba(0, 0, 0, 0.8)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    zIndex: 9999
                }}>
                    <div style={{
                        backgroundColor: '#1a1a2e',
                        borderRadius: '12px',
                        padding: '32px 48px',
                        textAlign: 'center',
                        border: '1px solid #333',
                        boxShadow: '0 20px 60px rgba(0, 0, 0, 0.5)',
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        justifyContent: 'center',
                        minWidth: '280px'
                    }}>
                        <div style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            marginBottom: '16px'
                        }}>
                            <Loader2
                                size={48}
                                style={{
                                    animation: 'spin 1s linear infinite',
                                    color: switchingTo === 'testnet' ? '#f59e0b' : '#22c55e'
                                }}
                            />
                        </div>
                        <div style={{
                            fontSize: '18px',
                            fontWeight: 600,
                            color: '#fff',
                            marginBottom: '8px'
                        }}>
                            Switching to {switchingTo?.toUpperCase()}...
                        </div>
                        <div style={{ fontSize: '13px', color: '#888' }}>
                            Initializing services and connecting to Binance
                        </div>
                    </div>
                </div>
            )}

            <div
                className={`env-banner ${config.environment} ${config.is_production ? 'flashing' : ''}`}
                style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '8px 16px',
                    backgroundColor: current.bgColor,
                    borderBottom: `2px solid ${current.borderColor}`,
                    color: current.textColor,
                    fontWeight: 600,
                    fontSize: '13px'
                }}
            >
                {/* Left: Environment indicator */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    {current.icon}
                    <span>{current.label}</span>
                    <span style={{ opacity: 0.7, fontWeight: 400 }}>- {current.description}</span>
                </div>

                {/* Center: Mode indicator (Read-Only - controlled by .env) - Hidden in compact mode */}
                {showModeSelector && !compact && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <button
                            disabled={true}
                            title="Mode được cấu hình trong .env file"
                            style={{
                                padding: '4px 12px',
                                borderRadius: '4px',
                                border: '1px solid',
                                borderColor: config.environment === 'paper' ? '#22c55e' : '#555',
                                backgroundColor: config.environment === 'paper' ? '#1a472a' : 'transparent',
                                color: config.environment === 'paper' ? '#22c55e' : '#555',
                                cursor: 'not-allowed',
                                fontSize: '12px',
                                opacity: config.environment === 'paper' ? 1 : 0.5,
                                transition: 'all 0.2s'
                            }}
                        >
                            {isPaperReal ? 'Paper-Real' : 'Paper'}
                        </button>
                        <button
                            disabled={true}
                            title="Mode được cấu hình trong .env file"
                            style={{
                                padding: '4px 12px',
                                borderRadius: '4px',
                                border: '1px solid',
                                borderColor: config.environment === 'testnet' ? '#f59e0b' : '#555',
                                backgroundColor: config.environment === 'testnet' ? '#422006' : 'transparent',
                                color: config.environment === 'testnet' ? '#f59e0b' : '#555',
                                cursor: 'not-allowed',
                                fontSize: '12px',
                                opacity: config.environment === 'testnet' ? 1 : 0.5,
                                transition: 'all 0.2s'
                            }}
                        >
                            Testnet
                        </button>
                        <button
                            disabled={true}
                            title="Mode được cấu hình trong .env file"
                            style={{
                                padding: '4px 12px',
                                borderRadius: '4px',
                                border: '1px solid',
                                borderColor: config.environment === 'live' ? '#ef4444' : '#555',
                                backgroundColor: config.environment === 'live' ? '#450a0a' : 'transparent',
                                color: config.environment === 'live' ? '#ef4444' : '#555',
                                cursor: 'not-allowed',
                                fontSize: '12px',
                                opacity: config.environment === 'live' ? 1 : 0.5,
                                transition: 'all 0.2s'
                            }}
                        >
                            Live 🔒
                        </button>
                        <span style={{
                            opacity: 0.4,
                            fontSize: '10px',
                            marginLeft: '4px',
                            fontStyle: 'italic'
                        }}>
                            (from .env)
                        </span>
                    </div>
                )}

                {/* Live or paper-real safety notice */}
                {config.environment === 'live' && (
                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px',
                        animation: 'pulse 1s infinite'
                    }}>
                        <Shield size={16} />
                        <span>Real money at risk!</span>
                    </div>
                )}
                {isPaperReal && (
                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px'
                    }}>
                        <Shield size={16} />
                        <span>No real orders</span>
                    </div>
                )}

                {/* Right: Kill Switch */}
                {showKillSwitch && (
                    <button
                        onClick={handleEmergencyStop}
                        disabled={killSwitchActive}
                        title="Emergency Stop - Cancel all orders, close all positions"
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '6px',
                            padding: '6px 12px',
                            borderRadius: '4px',
                            border: '2px solid #ef4444',
                            backgroundColor: killSwitchActive ? '#ef4444' : '#450a0a',
                            color: '#fff',
                            cursor: 'pointer',
                            fontWeight: 600,
                            fontSize: '12px',
                            transition: 'all 0.2s'
                        }}
                    >
                        <Power size={14} />
                        {killSwitchActive ? 'STOPPING...' : 'KILL SWITCH'}
                    </button>
                )}

                <style>{`
                    @keyframes pulse {
                        0%, 100% { opacity: 1; }
                        50% { opacity: 0.5; }
                    }
                    @keyframes spin {
                        from { transform: rotate(0deg); }
                        to { transform: rotate(360deg); }
                    }
                    .env-banner.flashing {
                        animation: flash 1s infinite;
                    }
                    @keyframes flash {
                        0%, 100% { background-color: #450a0a; }
                        50% { background-color: #7f1d1d; }
                    }
                `}</style>
            </div>
        </>
    );
};

export default EnvironmentBanner;
