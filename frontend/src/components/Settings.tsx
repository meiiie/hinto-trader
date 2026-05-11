import React, { useState, useEffect, useCallback } from 'react';
import { THEME } from '../styles/theme';
import { apiUrl, ENDPOINTS } from '../config/api';
import { useBreakpoint } from '../hooks/useBreakpoint';
import { ListFilter, AlertTriangle, GitMerge, Settings as SettingsIcon } from 'lucide-react';

interface TradingSettings {
    risk_percent: number;
    max_positions: number;
    leverage: number;
    auto_execute: boolean;
    smart_recycling: boolean; // SOTA: Zombie Killer logic
    execution_ttl_minutes: number; // SOTA: TTL Configuration
    // NOTE: rr_ratio removed - not used by backtest engine (SL/TP from strategy)
}

// SOTA Phase 26: Token Watchlist type
interface TokenWatchlistItem {
    symbol: string;
    enabled: boolean;
    alias: string | null;
}

/**
 * Settings Component - Binance Style with Inline Styles
 * SOTA Phase 26: Enhanced with Token Watchlist
 * SOTA Adaptive UI: Responsive for mobile/desktop
 */
const Settings: React.FC = () => {
    // SOTA: Adaptive UI - detect mobile for responsive layout
    const { isMobile, responsive } = useBreakpoint();

    const [settings, setSettings] = useState<TradingSettings>({
        risk_percent: 1.0,           // SOTA: Aligned with --risk 0.01 (1%)
        max_positions: 10,           // SOTA: Aligned with --max-pos 10
        leverage: 2,
        auto_execute: false,
        smart_recycling: false,      // SOTA: Default OFF (TTL45 Standard)
        execution_ttl_minutes: 45    // SOTA: Default 45m
    });
    const [tokenWatchlist, setTokenWatchlist] = useState<TokenWatchlistItem[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [isSaving, setIsSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [saveSuccess, setSaveSuccess] = useState(false);


    const fetchSettings = useCallback(async () => {
        try {
            const response = await fetch(apiUrl(ENDPOINTS.SETTINGS));
            if (response.ok) {
                const data = await response.json();
                setSettings(data);
            }

            // SOTA Phase 26: Fetch token watchlist
            const tokensRes = await fetch(apiUrl(ENDPOINTS.TOKENS));
            if (tokensRes.ok) {
                const tokensData = await tokensRes.json();
                setTokenWatchlist(tokensData.tokens || []);
            }
        } catch (err) {
            setError('Không thể tải cài đặt');
        } finally {
            setIsLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchSettings();
    }, [fetchSettings]);

    // SOTA Phase 26: Toggle token enabled/disabled
    const handleTokenToggle = async (symbol: string) => {
        const updatedTokens = tokenWatchlist.map(t =>
            t.symbol === symbol ? { ...t, enabled: !t.enabled } : t
        );
        setTokenWatchlist(updatedTokens);

        try {
            await fetch(apiUrl(ENDPOINTS.TOKENS), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tokens: updatedTokens })
            });
        } catch (err) {
            setError('Không thể cập nhật token');
        }
    };

    // SOTA Phase 26b: Add new token
    const [newTokenSymbol, setNewTokenSymbol] = useState('');
    const [isAddingToken, setIsAddingToken] = useState(false);
    const [activeTab, setActiveTab] = useState<'tokens' | 'risk' | 'strategy' | 'reconfigure'>('tokens');
    const [searchResults, setSearchResults] = useState<string[]>([]);
    const [showSearchDropdown, setShowSearchDropdown] = useState(false);

    const [topCoinsLimit, setTopCoinsLimit] = useState(10);
    // SOTA: Top Volume Pairs for weekly .env update
    const [topVolumeData, setTopVolumeData] = useState<{ symbols: string[], env_format: string, fetched_at: string } | null>(null);
    // SOTA (Jan 2026): Auto Select result for persistent display
    const [autoSelectResult, setAutoSelectResult] = useState<{ symbols: string[], env_format: string, count: number } | null>(null);

    // Search tokens with debounce
    useEffect(() => {
        if (newTokenSymbol.length < 2) {
            setSearchResults([]);
            setShowSearchDropdown(false);
            return;
        }

        const timer = setTimeout(async () => {
            try {
                const res = await fetch(apiUrl(ENDPOINTS.TOKENS_SEARCH(newTokenSymbol, 10)));
                if (res.ok) {
                    const data = await res.json();
                    setSearchResults(data.symbols || []);
                    setShowSearchDropdown(data.symbols?.length > 0);
                }
            } catch (err) {
                setSearchResults([]);
            }
        }, 300);

        return () => clearTimeout(timer);
    }, [newTokenSymbol]);



    const handleAddToken = async () => {
        if (!newTokenSymbol.trim()) return;

        setIsAddingToken(true);
        setError(null);

        try {
            // Validate with Binance API
            const validateRes = await fetch(apiUrl(ENDPOINTS.TOKENS_VALIDATE(newTokenSymbol)));
            const validateData = await validateRes.json();

            if (!validateData.valid) {
                setError(validateData.message);
                setIsAddingToken(false);
                return;
            }

            // Add token
            const addRes = await fetch(apiUrl(ENDPOINTS.TOKENS_ADD), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ symbol: newTokenSymbol })
            });

            if (addRes.ok) {
                const data = await addRes.json();
                setTokenWatchlist(data.tokens || []);
                setNewTokenSymbol('');

                // SOTA: Notify user about backend restart requirement for streams
                alert(`✅ Đã thêm token ${newTokenSymbol} thành công!\n\n⚠️ Lưu ý: Cần restart backend để tạo stream mới.\nToken sẽ xuất hiện trong dropdown sau khi restart.`);
            } else {
                const err = await addRes.json();
                setError(err.detail || 'Không thể thêm token');
            }
        } catch (err) {
            setError('Lỗi khi thêm token');
        } finally {
            setIsAddingToken(false);
        }
    };

    const handleRemoveToken = async (symbol: string) => {
        if (!confirm(`Xóa token ${symbol}?`)) return;

        try {
            const res = await fetch(apiUrl(ENDPOINTS.TOKENS_REMOVE(symbol)), {
                method: 'DELETE'
            });

            if (res.ok) {
                const data = await res.json();
                setTokenWatchlist(data.tokens || []);
            } else {
                const err = await res.json();
                setError(err.detail || 'Không thể xóa token');
            }
        } catch (err) {
            setError('Lỗi khi xóa token');
        }
    };


    const handleSave = async () => {
        setIsSaving(true);
        setError(null);
        setSaveSuccess(false);
        try {
            const response = await fetch(apiUrl(ENDPOINTS.SETTINGS), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settings)
            });
            if (response.ok) {
                setSaveSuccess(true);
                setTimeout(() => setSaveSuccess(false), 3000);
            } else {
                throw new Error('Failed to save');
            }
        } catch (err) {
            setError('Không thể lưu cài đặt');
        } finally {
            setIsSaving(false);
        }
    };

    const handleReset = async () => {
        if (!confirm('Reset tài khoản paper trading? Điều này sẽ xóa tất cả giao dịch và đặt lại số dư về $10,000.')) {
            return;
        }
        try {
            const response = await fetch(apiUrl(ENDPOINTS.RESET_TRADES), { method: 'POST' });
            if (response.ok) {
                alert('Đã reset tài khoản thành công!');
            }
        } catch (err) {
            setError('Không thể reset tài khoản');
        }
    };



    // SOTA: Responsive Styles
    const containerStyle: React.CSSProperties = {
        backgroundColor: THEME.bg.secondary,
        border: isMobile ? 'none' : `1px solid ${THEME.border.primary}`,
        borderRadius: isMobile ? 0 : '8px',
        padding: responsive(12, 14, 16),
    };

    const sectionStyle: React.CSSProperties = {
        display: 'flex',
        flexDirection: 'column',
        gap: responsive(10, 11, 12),
    };

    const headerStyle: React.CSSProperties = {
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        paddingBottom: '12px',
        borderBottom: `1px solid ${THEME.border.primary}`,
        marginBottom: '16px',
    };

    const inputStyle: React.CSSProperties = {
        width: '100%',
        backgroundColor: THEME.bg.vessel,
        border: `1px solid ${THEME.border.input}`,
        color: THEME.text.primary,
        borderRadius: '4px',
        padding: responsive('10px 14px', '9px 13px', '8px 12px'),
        fontSize: responsive(15, 14, 14),
        minHeight: isMobile ? 44 : 36, // Touch-friendly on mobile
        outline: 'none',
    };

    const labelStyle: React.CSSProperties = {
        display: 'block',
        fontSize: responsive(13, 12, 12),
        color: THEME.text.tertiary,
        marginBottom: '4px',
    };

    // SOTA: Single column on mobile, 2 columns on desktop (REQ-9.1, REQ-9.2)
    const gridStyle: React.CSSProperties = {
        display: 'grid',
        gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr',
        gap: responsive(12, 14, 16),
    };

    const cardStyle: React.CSSProperties = {
        backgroundColor: THEME.bg.vessel,
        borderRadius: '4px',
        padding: responsive(10, 9, 8),
    };

    // SOTA: Larger buttons on mobile (REQ-9.3)
    const buttonStyle = (bg: string, color: string): React.CSSProperties => ({
        padding: responsive('10px 18px', '9px 17px', '8px 16px'),
        fontSize: responsive(13, 12, 12),
        fontWeight: 700,
        borderRadius: '4px',
        border: 'none',
        cursor: 'pointer',
        backgroundColor: bg,
        color: color,
        transition: 'opacity 0.2s',
        minHeight: isMobile ? 44 : 36, // Touch-friendly
    });

    if (isLoading) {
        return (
            <div style={containerStyle}>
                <div style={{ ...sectionStyle, gap: '16px' }}>
                    <div style={{ height: '16px', backgroundColor: THEME.bg.vessel, borderRadius: '4px', width: '33%' }}></div>
                    {[...Array(4)].map((_, i) => (
                        <div key={i} style={{ height: '40px', backgroundColor: THEME.bg.vessel, borderRadius: '4px' }}></div>
                    ))}
                </div>
            </div>
        );
    }

    return (
        <div style={containerStyle}>
            {/* Header */}
            <div style={headerStyle}>
                <h2 style={{ fontSize: '18px', fontWeight: 700, color: THEME.text.primary, margin: 0 }}>Bảng Điều Khiển</h2>
                {saveSuccess && (
                    <span style={{ fontSize: '12px', color: THEME.status.buy }}>✓ Đã lưu</span>
                )}
            </div>

            {/* SOTA Phase 26b: Tabbed Navigation with Professional SVG Icons */}
            <div style={{
                display: 'flex',
                gap: '8px', // Increased gap for mobile
                marginBottom: '16px',
                borderBottom: `1px solid ${THEME.border.primary}`,
                paddingBottom: '12px',
                overflowX: 'auto',
                whiteSpace: 'nowrap',
                WebkitOverflowScrolling: 'touch',
                scrollbarWidth: 'none', // Hide scrollbar Firefox
                msOverflowStyle: 'none' // Hide scrollbar IE/Edge
            }}>
                {[
                    {
                        key: 'tokens',
                        label: 'Token & Pairlist',
                        icon: <ListFilter size={14} />
                    },
                    {
                        key: 'risk',
                        label: 'Rủi ro',
                        icon: <AlertTriangle size={14} />
                    },
                    {
                        key: 'strategy',
                        label: 'Chiến lược',
                        icon: <GitMerge size={14} />
                    },
                    {
                        key: 'reconfigure',
                        label: 'Cấu hình lại',
                        icon: <SettingsIcon size={14} />
                    }
                ].map(tab => (
                    <button
                        key={tab.key}
                        onClick={() => setActiveTab(tab.key as typeof activeTab)}
                        style={{
                            padding: '8px 16px',
                            fontSize: '12px',
                            fontWeight: 600,
                            borderRadius: '4px',
                            border: 'none',
                            cursor: 'pointer',
                            backgroundColor: activeTab === tab.key ? THEME.accent.yellow : 'transparent',
                            color: activeTab === tab.key ? '#000' : THEME.text.secondary,
                            transition: 'all 0.2s',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '6px',
                        }}
                    >
                        {tab.icon}
                        {tab.label}
                    </button>
                ))}
            </div>

            {/* Tab Content: Token Management */}
            {activeTab === 'tokens' && (
                <div style={sectionStyle}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <h3 style={{ fontSize: '14px', fontWeight: 600, color: THEME.text.secondary, margin: 0 }}>
                            Token Watchlist
                        </h3>
                        <span style={{ fontSize: '11px', color: THEME.text.tertiary }}>
                            {tokenWatchlist.filter(t => t.enabled).length}/{tokenWatchlist.length} đang bật
                        </span>
                    </div>

                    {/* Add Token Form with Search Dropdown */}
                    <div style={{ position: 'relative', margin: '12px 0' }}>
                        <div style={{ display: 'flex', gap: '8px' }}>
                            <input
                                type="text"
                                placeholder="Gõ để tìm token (VD: XRP, DOT...)"
                                value={newTokenSymbol}
                                onChange={(e) => setNewTokenSymbol(e.target.value.toUpperCase())}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter') handleAddToken();
                                    if (e.key === 'Escape') setShowSearchDropdown(false);
                                }}
                                onFocus={() => searchResults.length > 0 && setShowSearchDropdown(true)}
                                onBlur={() => setTimeout(() => setShowSearchDropdown(false), 200)}
                                style={{
                                    flex: 1,
                                    padding: '8px 12px',
                                    fontSize: '12px',
                                    borderRadius: '4px',
                                    border: `1px solid ${THEME.border.input}`,
                                    backgroundColor: THEME.bg.vessel,
                                    color: THEME.text.primary,
                                    outline: 'none',
                                }}
                            />
                            <button
                                onClick={handleAddToken}
                                disabled={isAddingToken || !newTokenSymbol.trim()}
                                style={{
                                    padding: '8px 16px',
                                    fontSize: '12px',
                                    fontWeight: 600,
                                    borderRadius: '4px',
                                    border: 'none',
                                    cursor: newTokenSymbol.trim() ? 'pointer' : 'not-allowed',
                                    backgroundColor: THEME.status.buy,
                                    color: '#fff',
                                    opacity: newTokenSymbol.trim() ? 1 : 0.5,
                                }}
                            >
                                {isAddingToken ? '...' : '+ Thêm'}
                            </button>
                        </div>

                        {/* Search Dropdown */}
                        {showSearchDropdown && searchResults.length > 0 && (
                            <div style={{
                                position: 'absolute',
                                top: '100%',
                                left: 0,
                                right: 60,
                                backgroundColor: THEME.bg.vessel,
                                border: `1px solid ${THEME.border.primary}`,
                                borderRadius: '4px',
                                marginTop: '4px',
                                maxHeight: '200px',
                                overflowY: 'auto',
                                zIndex: 10,
                                boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
                            }}>
                                {searchResults.map((symbol) => (
                                    <div
                                        key={symbol}
                                        onClick={() => {
                                            setNewTokenSymbol(symbol);
                                            setShowSearchDropdown(false);
                                        }}
                                        style={{
                                            padding: '8px 12px',
                                            fontSize: '12px',
                                            color: THEME.text.primary,
                                            cursor: 'pointer',
                                            borderBottom: `1px solid ${THEME.border.primary}`,
                                        }}
                                        onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = THEME.bg.tertiary)}
                                        onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                                    >
                                        <span style={{ fontWeight: 600 }}>{symbol.replace('USDT', '')}</span>
                                        <span style={{ color: THEME.text.tertiary }}> / USDT</span>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>

                    <p style={{ fontSize: '11px', color: THEME.text.tertiary, margin: '4px 0 12px 0' }}>
                        Bật/tắt token để nhận hoặc bỏ qua tín hiệu. Token default không thể xóa.
                    </p>

                    <div style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))',
                        gap: '10px'
                    }}>
                        {tokenWatchlist.map((token) => {
                            const isDefault = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'TAOUSDT', 'FETUSDT', 'ONDOUSDT'].includes(token.symbol);
                            return (
                                <div
                                    key={token.symbol}
                                    style={{
                                        padding: '12px',
                                        borderRadius: '8px',
                                        backgroundColor: token.enabled ? 'rgba(14,203,129,0.1)' : THEME.bg.vessel,
                                        border: `1px solid ${token.enabled ? THEME.status.buy : THEME.border.primary}`,
                                        textAlign: 'center',
                                        position: 'relative',
                                    }}
                                >
                                    {/* Delete button for custom tokens */}
                                    {!isDefault && (
                                        <button
                                            onClick={() => handleRemoveToken(token.symbol)}
                                            style={{
                                                position: 'absolute',
                                                top: '4px',
                                                right: '4px',
                                                width: '18px',
                                                height: '18px',
                                                borderRadius: '50%',
                                                border: 'none',
                                                backgroundColor: THEME.status.sell,
                                                color: '#fff',
                                                fontSize: '10px',
                                                cursor: 'pointer',
                                                display: 'flex',
                                                alignItems: 'center',
                                                justifyContent: 'center',
                                            }}
                                        >
                                            ×
                                        </button>
                                    )}
                                    <div
                                        onClick={() => handleTokenToggle(token.symbol)}
                                        style={{ cursor: 'pointer' }}
                                    >
                                        <div style={{
                                            fontSize: responsive(14, 13, 13),
                                            fontWeight: 700,
                                            color: token.enabled ? THEME.text.primary : THEME.text.tertiary
                                        }}>
                                            {token.symbol.replace('USDT', '')}
                                        </div>
                                        <div style={{
                                            fontSize: responsive(11, 10, 10),
                                            color: THEME.text.tertiary,
                                            marginTop: '2px'
                                        }}>
                                            {token.alias || token.symbol}
                                        </div>
                                        {/* SOTA: Larger toggle on mobile (REQ-9.3) */}
                                        <div style={{
                                            marginTop: '8px',
                                            width: isMobile ? '48px' : '32px',
                                            height: isMobile ? '26px' : '18px',
                                            borderRadius: isMobile ? '13px' : '9px',
                                            backgroundColor: token.enabled ? THEME.status.buy : THEME.bg.tertiary,
                                            margin: '8px auto 0',
                                            position: 'relative',
                                            transition: 'background-color 0.2s',
                                        }}>
                                            <div style={{
                                                position: 'absolute',
                                                top: isMobile ? '3px' : '2px',
                                                left: token.enabled ? (isMobile ? '25px' : '16px') : (isMobile ? '3px' : '2px'),
                                                width: isMobile ? '20px' : '14px',
                                                height: isMobile ? '20px' : '14px',
                                                borderRadius: '50%',
                                                backgroundColor: '#fff',
                                                transition: 'left 0.2s',
                                            }} />
                                        </div>
                                    </div>
                                </div>
                            );
                        })}
                    </div>

                    {/* SOTA: Top Volume Pairs for Weekly Update */}
                    <div style={{ marginTop: '20px', padding: '16px', backgroundColor: THEME.bg.vessel, borderRadius: '8px', border: `1px solid ${THEME.border.primary}` }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                            <h4 style={{ fontSize: '13px', fontWeight: 600, color: THEME.accent.yellow, margin: 0 }}>
                                📊 Top Volume Pairs (Weekly Update)
                            </h4>
                            <button
                                onClick={async () => {
                                    try {
                                        const res = await fetch(apiUrl(ENDPOINTS.TOP_VOLUME_PAIRS(10)));
                                        if (res.ok) {
                                            const data = await res.json();
                                            setTopVolumeData(data);
                                        }
                                    } catch (err) {
                                        console.error('Failed to fetch top volume:', err);
                                    }
                                }}
                                style={{
                                    padding: '6px 12px',
                                    fontSize: '11px',
                                    fontWeight: 600,
                                    borderRadius: '4px',
                                    border: 'none',
                                    cursor: 'pointer',
                                    backgroundColor: THEME.status.info,
                                    color: '#fff',
                                }}
                            >
                                🔄 Fetch Top 10
                            </button>
                        </div>

                        {topVolumeData && (
                            <>
                                <div style={{ fontSize: '11px', color: THEME.text.tertiary, marginBottom: '8px' }}>
                                    Fetched: {new Date(topVolumeData.fetched_at).toLocaleString()}
                                </div>
                                <div style={{
                                    display: 'flex',
                                    flexWrap: 'wrap',
                                    gap: '6px',
                                    marginBottom: '12px'
                                }}>
                                    {topVolumeData.symbols?.map((symbol: string, idx: number) => (
                                        <span key={symbol} style={{
                                            padding: '4px 8px',
                                            fontSize: '11px',
                                            fontWeight: 600,
                                            borderRadius: '4px',
                                            backgroundColor: idx < 3 ? THEME.alpha.buyBg : THEME.bg.tertiary,
                                            color: idx < 3 ? THEME.status.buy : THEME.text.secondary,
                                        }}>
                                            #{idx + 1} {symbol.replace('USDT', '')}
                                        </span>
                                    ))}
                                </div>
                                <div style={{
                                    backgroundColor: THEME.bg.primary,
                                    padding: '10px',
                                    borderRadius: '4px',
                                    fontFamily: 'monospace',
                                    fontSize: '11px',
                                    color: THEME.accent.yellow,
                                    wordBreak: 'break-all',
                                }}>
                                    {topVolumeData.env_format}
                                </div>
                                <button
                                    onClick={() => {
                                        navigator.clipboard.writeText(topVolumeData.env_format);
                                        alert('✅ Copied to clipboard! Paste to your .env file and restart backend.');
                                    }}
                                    style={{
                                        marginTop: '8px',
                                        padding: '8px 16px',
                                        fontSize: '12px',
                                        fontWeight: 600,
                                        borderRadius: '4px',
                                        border: 'none',
                                        cursor: 'pointer',
                                        backgroundColor: THEME.status.info,
                                        color: '#fff',
                                        width: '100%',
                                    }}
                                >
                                    📋 Copy to Clipboard
                                </button>
                            </>
                        )}

                        {/* SOTA (Jan 2026): Auto Select Top N - Direct Save to .env */}
                        <div style={{
                            marginTop: '16px',
                            padding: '12px',
                            backgroundColor: 'rgba(240, 185, 11, 0.1)',
                            borderRadius: '8px',
                            border: `1px solid ${THEME.accent.yellow}`
                        }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                                <h5 style={{ fontSize: '12px', fontWeight: 600, color: THEME.accent.yellow, margin: 0 }}>
                                    🚀 Auto Select Top N (Shark Tank Mode)
                                </h5>
                            </div>
                            <p style={{ fontSize: '11px', color: THEME.text.tertiary, margin: '0 0 12px 0' }}>
                                Fetch top N symbols by 24h volume and save directly to .env. Restart required after.
                            </p>
                            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                                <select
                                    value={topCoinsLimit}
                                    onChange={(e) => setTopCoinsLimit(Number(e.target.value))}
                                    style={{
                                        padding: '8px 12px',
                                        fontSize: '12px',
                                        borderRadius: '4px',
                                        border: `1px solid ${THEME.border.input}`,
                                        backgroundColor: THEME.bg.vessel,
                                        color: THEME.text.primary,
                                        cursor: 'pointer',
                                    }}
                                >
                                    {[10, 20, 30, 50, 75, 100].map(n => (
                                        <option key={n} value={n}>Top {n}</option>
                                    ))}
                                </select>
                                <button
                                    onClick={async () => {
                                        try {
                                            const res = await fetch(apiUrl(ENDPOINTS.AUTO_SELECT_SYMBOLS(topCoinsLimit)), {
                                                method: 'POST'
                                            });
                                            const data = await res.json();
                                            if (data.success) {
                                                // SOTA: Use backend instruction (Saved vs Manual)
                                                setAutoSelectResult({
                                                    symbols: data.symbols,
                                                    env_format: data.env_format,
                                                    count: data.count
                                                });

                                                if (data.saved) {
                                                    alert(data.instruction || '✅ Saved to .env! Please restart backend.');
                                                } else {
                                                    // Fallback for manual copy
                                                    await navigator.clipboard.writeText(data.env_format);
                                                    alert(data.instruction || '✅ Copied to clipboard! Please save to .env manually.');
                                                }
                                            } else {
                                                alert(`❌ Error: ${data.error}`);
                                            }
                                        } catch (err) {
                                            alert('❌ Failed to fetch symbols');
                                        }
                                    }}
                                    style={{
                                        flex: 1,
                                        padding: '10px 16px',
                                        fontSize: '12px',
                                        fontWeight: 700,
                                        borderRadius: '4px',
                                        border: 'none',
                                        cursor: 'pointer',
                                        backgroundColor: THEME.accent.yellow,
                                        color: '#000',
                                    }}
                                >
                                    🦈 Fetch Top N Symbols
                                </button>
                            </div>

                            {/* SOTA: Persistent Display Area for Copy */}
                            {autoSelectResult && (
                                <div style={{ marginTop: '12px' }}>
                                    <div style={{
                                        display: 'flex',
                                        alignItems: 'center',
                                        justifyContent: 'space-between',
                                        marginBottom: '8px'
                                    }}>
                                        <span style={{ fontSize: '11px', color: THEME.status.buy, fontWeight: 600 }}>
                                            ✅ {autoSelectResult.count} symbols fetched
                                        </span>
                                        <button
                                            onClick={async () => {
                                                await navigator.clipboard.writeText(autoSelectResult.env_format);
                                                alert('📋 Copied to clipboard!');
                                            }}
                                            style={{
                                                padding: '4px 8px',
                                                fontSize: '10px',
                                                fontWeight: 600,
                                                borderRadius: '4px',
                                                border: 'none',
                                                cursor: 'pointer',
                                                backgroundColor: THEME.status.info,
                                                color: '#fff',
                                            }}
                                        >
                                            📋 Copy Again
                                        </button>
                                    </div>
                                    <div style={{
                                        backgroundColor: THEME.bg.primary,
                                        padding: '10px',
                                        borderRadius: '4px',
                                        fontFamily: 'monospace',
                                        fontSize: '10px',
                                        color: THEME.accent.yellow,
                                        wordBreak: 'break-all',
                                        maxHeight: '80px',
                                        overflowY: 'auto',
                                    }}>
                                        {autoSelectResult.env_format}
                                    </div>
                                    <div style={{
                                        display: 'flex',
                                        flexWrap: 'wrap',
                                        gap: '4px',
                                        marginTop: '8px',
                                        maxHeight: '60px',
                                        overflowY: 'auto'
                                    }}>
                                        {autoSelectResult.symbols.slice(0, 20).map((sym, idx) => (
                                            <span key={sym} style={{
                                                padding: '2px 6px',
                                                fontSize: '9px',
                                                fontWeight: 600,
                                                borderRadius: '3px',
                                                backgroundColor: idx < 3 ? THEME.alpha.buyBg : THEME.bg.tertiary,
                                                color: idx < 3 ? THEME.status.buy : THEME.text.tertiary,
                                            }}>
                                                {sym.replace('USDT', '')}
                                            </span>
                                        ))}
                                        {autoSelectResult.symbols.length > 20 && (
                                            <span style={{ fontSize: '9px', color: THEME.text.tertiary }}>
                                                +{autoSelectResult.symbols.length - 20} more
                                            </span>
                                        )}
                                    </div>
                                    <p style={{ fontSize: '10px', color: THEME.text.tertiary, margin: '8px 0 0 0' }}>
                                        ⚠️ Paste into your project <code>.env</code> file and restart backend.
                                    </p>
                                </div>
                            )}
                        </div>

                        {!topVolumeData && !autoSelectResult && (
                            <p style={{ fontSize: '11px', color: THEME.text.tertiary, margin: '12px 0 0 0' }}>
                                Click "Fetch Top 10" to preview or "Fetch Top N Symbols" to get symbols for .env.
                            </p>
                        )}
                    </div>
                </div>
            )
            }

            {/* Tab Content: Risk Management */}
            {
                activeTab === 'risk' && (
                    <>
                        {/* Divider */}
                        <div style={{ marginTop: '16px', paddingTop: '16px', borderTop: `1px solid ${THEME.border.primary}` }} />

                        {/* Risk Management */}
                        <div style={sectionStyle}>
                            <h3 style={{ fontSize: '14px', fontWeight: 600, color: THEME.text.secondary, margin: 0 }}>Quản lý rủi ro</h3>

                            <div style={gridStyle}>
                                <div>
                                    <label style={labelStyle}>Rủi ro mỗi lệnh (%)</label>
                                    <input
                                        type="number"
                                        min="0.1"
                                        max="10"
                                        step="0.1"
                                        value={settings.risk_percent}
                                        onChange={(e) => setSettings(s => ({ ...s, risk_percent: parseFloat(e.target.value) || 0 }))}
                                        style={{ ...inputStyle, borderColor: THEME.status.info }}
                                    />
                                </div>
                                {/* NOTE: rr_ratio removed - backtest uses SL/TP from strategy signal */}
                            </div>

                            <div style={gridStyle}>
                                <div>
                                    <label style={labelStyle}>Số vị thế tối đa</label>
                                    <input
                                        type="number"
                                        min="1"
                                        max="100" // SOTA: Scaled for Shark Tank
                                        value={settings.max_positions}
                                        onChange={(e) => setSettings(s => ({ ...s, max_positions: parseInt(e.target.value) || 1 }))}
                                        style={inputStyle}
                                    />
                                </div>
                                <div>
                                    <label style={labelStyle}>Đòn bẩy</label>
                                    <select
                                        value={settings.leverage}
                                        onChange={(e) => setSettings(s => ({ ...s, leverage: parseInt(e.target.value) }))}
                                        style={inputStyle}
                                    >
                                        <option value={1}>1x</option>
                                        <option value={2}>2x</option>
                                    </select>
                                </div>
                                <div>
                                    <label style={labelStyle}>TTL Lệnh (phút)</label>
                                    <input
                                        type="number"
                                        min="1"
                                        max="1440"
                                        value={settings.execution_ttl_minutes || 45} // Fallback to 45 if undefined
                                        onChange={(e) => setSettings(s => ({ ...s, execution_ttl_minutes: parseInt(e.target.value) || 45 }))}
                                        style={inputStyle}
                                    />
                                </div>
                            </div>

                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <input
                                    type="checkbox"
                                    id="autoExecute"
                                    checked={settings.auto_execute}
                                    onChange={(e) => setSettings(s => ({ ...s, auto_execute: e.target.checked }))}
                                    style={{ width: '16px', height: '16px', accentColor: THEME.accent.yellow }}
                                />
                                <label htmlFor="autoExecute" style={{ fontSize: '14px', color: THEME.text.secondary }}>
                                    Tự động thực hiện tín hiệu
                                </label>
                            </div>

                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '8px' }}>
                                <input
                                    type="checkbox"
                                    id="smartRecycling"
                                    checked={settings.smart_recycling ?? true}
                                    onChange={(e) => setSettings(s => ({ ...s, smart_recycling: e.target.checked }))}
                                    style={{ width: '16px', height: '16px', accentColor: THEME.status.buy }}
                                />
                                <label htmlFor="smartRecycling" style={{ fontSize: '14px', color: THEME.text.secondary }}>
                                    ♻️ Smart Recycling (Thay thế tín hiệu yếu khi đầy)
                                </label>
                            </div>
                        </div>

                        {/* Actions */}
                        <div style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            marginTop: '16px',
                            paddingTop: '16px',
                            borderTop: `1px solid ${THEME.border.primary}`
                        }}>
                            <button
                                onClick={handleReset}
                                style={{
                                    ...buttonStyle(THEME.alpha.sellBg, THEME.status.sell),
                                    border: `1px solid ${THEME.status.sell}`,
                                }}
                            >
                                Reset tài khoản
                            </button>
                            <button
                                onClick={handleSave}
                                disabled={isSaving}
                                style={{
                                    ...buttonStyle(THEME.accent.yellow, '#000'),
                                    opacity: isSaving ? 0.5 : 1,
                                }}
                            >
                                {isSaving ? 'Đang lưu...' : 'Lưu cài đặt'}
                            </button>
                        </div>
                    </>
                )
            }

            {/* Tab Content: Strategy */}
            {
                activeTab === 'strategy' && (
                    <div style={sectionStyle}>
                        <h3 style={{ fontSize: '14px', fontWeight: 600, color: THEME.text.secondary, margin: 0 }}>Cấu hình Chiến lược Trading</h3>
                        <p style={{ fontSize: '11px', color: THEME.text.tertiary, margin: '4px 0 12px 0' }}>
                            Các tham số SL/TP và trailing theo chuẩn SOTA Institutional (hiện tại chỉ hiển thị - cấu hình trong backend)
                        </p>

                        {/* Risk-Reward Settings */}
                        <div style={{ marginBottom: '16px' }}>
                            <div style={{ fontSize: '12px', color: THEME.accent.yellow, fontWeight: 600, marginBottom: '8px' }}>
                                📊 Cấu hình SL/TP
                            </div>
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px' }}>
                                <div style={cardStyle}>
                                    <div style={{ fontSize: '12px', color: THEME.text.tertiary }}>Stop Loss</div>
                                    <div style={{ fontFamily: 'monospace', color: THEME.status.sell, fontWeight: 700 }}>0.5%</div>
                                </div>
                                <div style={cardStyle}>
                                    <div style={{ fontSize: '12px', color: THEME.text.tertiary }}>Take Profit</div>
                                    <div style={{ fontFamily: 'monospace', color: THEME.status.buy, fontWeight: 700 }}>2.0%</div>
                                </div>
                                <div style={cardStyle}>
                                    <div style={{ fontSize: '12px', color: THEME.text.tertiary }}>Risk:Reward</div>
                                    <div style={{ fontFamily: 'monospace', color: THEME.accent.yellow, fontWeight: 700 }}>1:4</div>
                                </div>
                            </div>
                        </div>

                        {/* Trailing Stop Settings */}
                        <div style={{ marginBottom: '16px' }}>
                            <div style={{ fontSize: '12px', color: THEME.status.info, fontWeight: 600, marginBottom: '8px' }}>
                                📈 Trailing Stop & Breakeven
                            </div>
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px' }}>
                                <div style={cardStyle}>
                                    <div style={{ fontSize: '12px', color: THEME.text.tertiary }}>ATR Trailing Mult</div>
                                    <div style={{ fontFamily: 'monospace', color: THEME.status.info }}>4.0x</div>
                                </div>
                                <div style={cardStyle}>
                                    <div style={{ fontSize: '12px', color: THEME.text.tertiary }}>Breakeven Trigger</div>
                                    <div style={{ fontFamily: 'monospace', color: THEME.status.info }}>1.5R</div>
                                </div>
                                <div style={cardStyle}>
                                    <div style={{ fontSize: '12px', color: THEME.text.tertiary }}>Partial TP</div>
                                    <div style={{ fontFamily: 'monospace', color: THEME.status.buy }}>60% @ TP1</div>
                                </div>
                            </div>
                        </div>

                        {/* Indicator Settings */}
                        <div>
                            <div style={{ fontSize: '12px', color: THEME.status.purple, fontWeight: 600, marginBottom: '8px' }}>
                                📉 Tham số Kỹ thuật
                            </div>
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px' }}>
                                <div style={cardStyle}>
                                    <div style={{ fontSize: '12px', color: THEME.text.tertiary }}>VWAP</div>
                                    <div style={{ fontFamily: 'monospace', color: THEME.accent.yellow }}>Period: 14</div>
                                </div>
                                <div style={cardStyle}>
                                    <div style={{ fontSize: '12px', color: THEME.text.tertiary }}>Bollinger Bands</div>
                                    <div style={{ fontFamily: 'monospace', color: THEME.status.info }}>20, 2σ</div>
                                </div>
                                <div style={cardStyle}>
                                    <div style={{ fontSize: '12px', color: THEME.text.tertiary }}>Swing Lookback</div>
                                    <div style={{ fontFamily: 'monospace', color: THEME.status.purple }}>20 bars</div>
                                </div>
                            </div>
                        </div>

                        {/* Note */}
                        <div style={{
                            marginTop: '16px',
                            padding: '12px',
                            backgroundColor: 'rgba(240, 185, 11, 0.1)',
                            borderRadius: '6px',
                            border: '1px solid rgba(240, 185, 11, 0.3)'
                        }}>
                            <p style={{ fontSize: '11px', color: THEME.text.secondary, margin: 0 }}>
                                💡 <b>Lưu ý:</b> Để thay đổi các tham số này, chỉnh sửa trong <code>backend/src/application/di_container.py</code> hoặc file <code>.env</code>.
                            </p>
                        </div>
                    </div>
                )
            }



            {/* Top Coins Display */}


            {/* Current Blacklist */}


            {/* Add to Blacklist */}



            {/* Tab Content: Reconfigure - Reopen Setup Wizard */}
            {
                activeTab === 'reconfigure' && (
                    <div style={sectionStyle}>
                        <h3 style={{ fontSize: '14px', fontWeight: 600, color: THEME.text.secondary, margin: 0, marginBottom: '16px' }}>
                            Cấu Hình Lại Ứng Dụng
                        </h3>

                        <div style={{
                            padding: '16px',
                            backgroundColor: 'rgba(240,185,11,0.1)',
                            borderRadius: '8px',
                            border: '1px solid rgba(240,185,11,0.3)',
                            marginBottom: '16px'
                        }}>
                            <p style={{ fontSize: '12px', color: THEME.text.secondary, margin: 0, lineHeight: 1.6 }}>
                                Mở lại Setup Wizard để thay đổi:
                            </p>
                            <ul style={{ fontSize: '12px', color: THEME.text.tertiary, margin: '8px 0 0 0', paddingLeft: '20px' }}>
                                <li>API Keys (Binance)</li>
                                <li>Symbols giao dịch</li>
                                <li>Thông số chiến lược (SL/TP/Trailing)</li>
                                <li>Chế độ (Paper/Testnet/Live)</li>
                            </ul>
                        </div>

                        <button
                            onClick={async () => {
                                const tauriWindow = window as any;
                                if (tauriWindow.__TAURI__) {
                                    try {
                                        await tauriWindow.__TAURI__.core.invoke('show_setup');
                                    } catch (e) {
                                        console.error('Failed to open Setup Wizard:', e);
                                        setError('Không thể mở Setup Wizard');
                                    }
                                } else {
                                    // Web mode - redirect to setup
                                    window.location.href = '/setup.html';
                                }
                            }}
                            style={{
                                padding: '12px 24px',
                                fontSize: '14px',
                                fontWeight: 600,
                                borderRadius: '8px',
                                border: 'none',
                                cursor: 'pointer',
                                backgroundColor: THEME.accent.yellow,
                                color: '#000',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '8px',
                                transition: 'opacity 0.2s',
                            }}
                        >
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <circle cx="12" cy="12" r="3" />
                                <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z" />
                            </svg>
                            Mở Setup Wizard
                        </button>
                    </div>
                )
            }

            {/* Error Message */}
            {
                error && (
                    <div style={{
                        marginTop: '16px',
                        padding: '8px',
                        borderRadius: '4px',
                        backgroundColor: THEME.alpha.sellBg,
                        color: THEME.status.sell,
                        fontSize: '12px'
                    }}>
                        {error}
                    </div>
                )
            }
        </div >
    );
};

export default Settings;
