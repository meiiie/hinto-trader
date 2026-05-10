import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { formatPrice } from '../styles/theme';
import { apiUrl, wsUrl, ENDPOINTS } from '../config/api';
import { TokenIcon } from './TokenIcon';
import { SharkTankWatchlist } from './SharkTankWatchlist';
import { ChevronDown, ChevronUp, XCircle, Briefcase, Clock, ChevronLeft, ChevronRight } from 'lucide-react';
import useMarketStore from '../stores/marketStore';
import { WebSocketStatus } from './WebSocketStatus';
import { useBreakpoint } from '../hooks/useBreakpoint';
import { PortfolioMobile } from './trading/PortfolioMobile';

// --- INTERFACES ---
// SOTA Dual TP/SL types
interface TpSlData {
    stop_loss: number | null;
    take_profit: number | null;
}

interface LocalTpSl extends TpSlData {
    source?: 'signal' | 'watermark' | 'pending' | 'unknown';
    backup_sl?: number | null;  // SOTA Local-First: Exchange backup SL (-2%)
    local_first_mode?: boolean;  // SOTA: Flag for Local-First pattern
}

interface ExchangeTpSl extends TpSlData {
    sl_order_id?: string | null;
    tp_order_id?: string | null;
    is_backup_only?: boolean;  // SOTA: True if this is just backup SL, not real SL
}

interface Position {
    id: string;
    symbol: string;
    side: 'LONG' | 'SHORT';
    status: string;
    entry_price: number;
    quantity: number;
    leverage: number;
    margin: number;
    stop_loss: number;      // Legacy (effective)
    take_profit: number;    // Legacy (effective)
    local_tpsl?: LocalTpSl;     // SOTA: From our tracking
    exchange_tpsl?: ExchangeTpSl; // SOTA: From Binance orders
    entry_time?: string;
    unrealized_pnl: number;
    roe_pct: number;
    current_price: number;
    current_value: number;
    size?: number;
    is_orphan?: boolean;
    local_first_mode?: boolean;  // SOTA: Top-level flag for Local-First mode
}

interface PendingOrder {
    id: string;
    symbol: string;
    // SOTA: Accept both formats - Binance uses BUY/SELL, Paper uses LONG/SHORT
    side: 'LONG' | 'SHORT' | 'BUY' | 'SELL';
    entry_price: number;
    size: number;
    quantity?: number;
    stop_loss: number;
    take_profits?: number[];
    take_profit?: number;
    created_at?: string;
    open_time?: string;
    margin?: number;
    leverage?: number;
}

// SOTA: Pending Signal interface for real-time signal display
interface PendingSignal {
    id: string;
    symbol: string;
    signal_type: 'buy' | 'sell';
    entry_price: number;
    stop_loss: number;
    confidence: number;
    generated_at?: string;
}

interface PortfolioData {
    wallet_balance: number;
    margin_balance: number;
    available_balance: number;
    unrealized_pnl: number;
    total_equity: number;
    open_positions: Position[];
    pending_orders: PendingOrder[];
    pending_signals: PendingSignal[];  // SOTA: Pending signals
    pending_signals_count: number;     // SOTA: Signal count
    realized_pnl: number;
}

// SOTA: Shark Tank Dashboard Interface
interface SharkTankStatus {
    enabled: boolean;
    max_positions: number;
    current_positions: number;
    available_slots: number;
    pending_signals: number;
    pending_list: Array<{
        symbol: string;
        direction: 'buy' | 'sell';
        confidence: number;
        queued_at: string;
    }>;
    available_margin: number;
    batch_interval_seconds: number;
    last_batch_time: string;
    trading_mode: 'PAPER' | 'TESTNET' | 'LIVE';  // SOTA: Mode indicator
    leverage: number;  // SOTA: Current leverage setting
    watched_tokens: string[];  // SOTA: Token watchlist like Quant Lab
    // SOTA (Jan 2026): Enhanced data for Shark Tank Watchlist UI
    // Added entry_price, quantity, and breakeven fields
    position_symbols: Array<{
        symbol: string;
        side: 'LONG' | 'SHORT';
        pnl: number;
        entry_price?: number;
        quantity?: number;
        // SOTA FIX (Jan 2026): Breakeven display fields
        current_sl?: number;
        initial_sl?: number;
        phase?: string;
        is_breakeven?: boolean;
    }>;
    pending_symbols: Array<{ symbol: string; side: string; entry_price: number; distance_pct: number; locked: boolean }>;
}

// --- COLORS (Hinto Pro Style - Synced with Project) ---
const COLORS = {
    buy: 'rgb(14, 203, 129)',
    sell: 'rgb(246, 70, 93)',
    yellow: 'rgb(240, 185, 11)',
    bgPrimary: 'rgb(24, 26, 32)',      // Project standard
    bgSecondary: 'rgb(30, 35, 41)',
    bgTertiary: 'rgb(43, 49, 57)',
    textPrimary: 'rgb(234, 236, 239)',
    textSecondary: 'rgb(132, 142, 156)',
    textTertiary: 'rgb(94, 102, 115)',
};

// --- STYLES ---
const glassContainer: React.CSSProperties = {
    background: COLORS.bgPrimary, // Solid background - synced with project
    border: `1px solid ${COLORS.bgTertiary}`,
    borderRadius: '12px',
    padding: '20px',
    height: '100%',
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
};

const thStyle = (align: 'left' | 'center' | 'right' = 'left'): React.CSSProperties => ({
    padding: '10px 8px',
    fontSize: '10px',
    color: COLORS.textTertiary,
    fontWeight: 600,
    textAlign: align,
    textTransform: 'uppercase',
    letterSpacing: '0.6px',
    background: COLORS.bgSecondary,
    borderBottom: `1px solid ${COLORS.bgTertiary}`,
    position: 'sticky' as const,
    top: 0,
    zIndex: 1,
});

const tdStyle = (align: 'left' | 'center' | 'right' = 'left'): React.CSSProperties => ({
    padding: '12px 8px',
    textAlign: align,
    fontSize: '12px',
});


const ITEMS_PER_PAGE = 10;

// --- SUB-COMPONENTS ---

// SOTA: Realtime Total PnL Card - Calculates total unrealized PnL from all positions using Mainnet prices
const RealtimePnLCard = React.memo(({ positions }: { positions: Position[] }) => {
    // Subscribe to all position symbols for realtime price updates
    const symbolData = useMarketStore(state => state.symbolData);
    // SOTA (Jan 2026): Also use positionPrices for non-active symbols
    const positionPrices = useMarketStore(state => state.positionPrices);

    // Calculate total PnL from all positions using Mainnet WebSocket prices
    const totalPnl = useMemo(() => {
        if (!positions || positions.length === 0) return 0;

        return positions.reduce((sum, pos) => {
            const symbol = pos.symbol.toLowerCase();
            // SOTA: Price fallback chain
            const priceFromUpdate = positionPrices[symbol]?.price;
            const liveClose = symbolData[symbol]?.data1m?.close;
            const currentPrice = priceFromUpdate || liveClose || pos.current_price || pos.entry_price;

            const sz = pos.size || pos.quantity || 0;
            const sideMultiplier = pos.side === 'LONG' ? 1 : -1;
            const pnl = (currentPrice - pos.entry_price) * sz * sideMultiplier;

            return sum + pnl;
        }, 0);
    }, [positions, symbolData, positionPrices]);

    const pnlColor = totalPnl >= 0 ? COLORS.buy : COLORS.sell;
    const sign = totalPnl >= 0 ? '+' : '';

    return (
        <div style={{ background: COLORS.bgSecondary, borderRadius: '6px', padding: '12px', border: `1px solid ${COLORS.bgTertiary}` }}>
            <div style={{ fontSize: '10px', color: COLORS.textTertiary, marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Unrealized PNL</div>
            <div style={{ fontSize: '14px', fontWeight: 700, color: pnlColor, fontFamily: 'monospace' }}>${sign}{totalPnl.toFixed(2)}</div>
        </div>
    );
});

// 1. Portfolio Row (Realtime SOTA)
// Extracts logic to dedicated component to prevent table re-renders
// and allows individual rows to subscribe to high-frequency price updates.
const PortfolioRow = React.memo(({ pos, index, onClose }: { pos: Position, index: number, onClose: (id: string) => void }) => {
    // SOTA (Jan 2026): Multi-position realtime prices
    // Subscribe to both symbolData (for active symbol) and positionPrices (for all positions)
    const symbolLower = pos.symbol.toLowerCase();

    // Price from candle data (only available for active symbol)
    const liveClose = useMarketStore(state =>
        state.symbolData[symbolLower]?.data1m?.close
    );

    // SOTA: Price from price_update messages (available for ALL position symbols)
    const positionPrice = useMarketStore(state =>
        state.positionPrices[symbolLower]
    );

    // SOTA: Price fallback chain (Property 7 from design.md)
    // 1. positionPrices[symbol]?.price (from price_update - fastest for non-active symbols)
    // 2. symbolData[symbol]?.data1m?.close (from candle, if activeSymbol)
    // 3. position.current_price (from REST API)
    // 4. position.entry_price (fallback)
    const currentPrice = positionPrice?.price || liveClose || pos.current_price || pos.entry_price;

    // SOTA: Check if price is stale (> 5 seconds old)
    const STALE_THRESHOLD = 5000; // 5 seconds
    const isPriceStale = positionPrice && (Date.now() - positionPrice.timestamp > STALE_THRESHOLD);

    // Determine price source for UI indicator
    const priceSource = positionPrice?.price ? 'realtime' : liveClose ? 'candle' : pos.current_price ? 'api' : 'entry';

    // Calculate PnL using Mainnet WebSocket prices (liveClose) for accuracy
    // User preference: Mainnet prices are more accurate than Testnet
    const sz = pos.size || pos.quantity || 0;
    const sideMultiplier = pos.side === 'LONG' ? 1 : -1;
    const pnl = (currentPrice - pos.entry_price) * sz * sideMultiplier;

    // ROE Calculation
    const margin = pos.margin || (pos.entry_price * sz / pos.leverage);
    const roe = margin > 0 ? (pnl / margin) * 100 : 0;

    const sideColor = pos.side === 'LONG' ? COLORS.buy : COLORS.sell;
    const pnlColor = pnl >= 0 ? COLORS.buy : COLORS.sell;

    // SOTA Dual TP/SL: Extract from both sources
    const localTp = pos.local_tpsl?.take_profit || 0;
    const localSl = pos.local_tpsl?.stop_loss || 0;
    const backupSl = pos.local_tpsl?.backup_sl || 0;  // SOTA: Backup SL (-2%)
    const isLocalFirst = pos.local_first_mode || pos.local_tpsl?.local_first_mode || false;
    const exchangeTp = pos.exchange_tpsl?.take_profit || 0;
    const exchangeSl = pos.exchange_tpsl?.stop_loss || 0;
    // Note: isBackupOnly removed - now we always show exchange SL as backup

    // Note: Effective values (tp/sl) removed as they were unused -
    // SOTA Dual display uses local* and exchange* separately

    // Check if synced (local matches exchange) - not relevant for Local-First mode
    const isSynced = !isLocalFirst && ((localSl > 0 && exchangeSl > 0) || (localTp > 0 && exchangeTp > 0));

    return (
        <tr style={{ borderBottom: `1px solid ${COLORS.bgTertiary}30`, background: index % 2 === 0 ? 'transparent' : `${COLORS.bgSecondary}50`, color: COLORS.textPrimary }}>
            <td style={tdStyle('left')}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <TokenIcon symbol={pos.symbol.replace('USDT', '')} size={18} />
                    <div><div style={{ fontWeight: 700 }}>{pos.symbol.toUpperCase()}</div>
                        <span style={{ fontSize: '10px', color: sideColor, fontWeight: 700 }}>{pos.side} {pos.leverage || 1}x</span>
                    </div>
                </div>
            </td>
            <td style={{ ...tdStyle('right'), fontFamily: 'monospace', fontSize: '11px' }}>{sz.toFixed(4)}</td>
            <td style={{ ...tdStyle('right'), fontFamily: 'monospace', fontSize: '11px' }}>${formatPrice(pos.entry_price)}</td>
            <td style={{ ...tdStyle('right'), fontFamily: 'monospace', fontSize: '11px', color: priceSource === 'realtime' || priceSource === 'candle' ? COLORS.textPrimary : COLORS.textTertiary }}>
                ${formatPrice(currentPrice)}
                {/* SOTA: Stale price indicator */}
                {isPriceStale && <span style={{ marginLeft: '4px', fontSize: '10px', color: COLORS.yellow }} title="Price may be stale">⚠️</span>}
            </td>
            <td style={{ ...tdStyle('right'), fontFamily: 'monospace', fontSize: '11px' }}>${margin.toFixed(2)}</td>

            {/* SOTA LOCAL-FIRST TP/SL DISPLAY (Jan 2026) */}
            <td style={{ ...tdStyle('right'), fontSize: '9px' }} title={
                pos.is_orphan
                    ? 'Vị thế mở trước khi bot khởi động - dùng API set-tpsl để thêm'
                    : isLocalFirst
                        ? `Local SL/TP (ẩn khỏi sàn)\nTP: $${localTp || '--'}\nSL: $${localSl || '--'}\nBackup SL: $${backupSl || exchangeSl || '--'} (-2%)`
                        : `Local: TP=$${localTp || '--'} SL=$${localSl || '--'}\nExchange: TP=$${exchangeTp || '--'} SL=$${exchangeSl || '--'}`
            }>
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '1px' }}>
                    {/* Local TP/SL (📍) - Primary display */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <span style={{ fontSize: '8px', opacity: 0.6 }}>📍</span>
                        <span style={{ color: COLORS.buy }}>{localTp > 0 ? `$${formatPrice(localTp)}` : '--'}</span>
                        <span style={{ color: COLORS.textTertiary }}>/</span>
                        <span style={{ color: COLORS.sell }}>{localSl > 0 ? `$${formatPrice(localSl)}` : '--'}</span>
                    </div>

                    {/* SOTA Local-First: ALWAYS show Backup SL when exchange has SL order */}
                    {/* Shows exchange SL as "Backup" since local SL is the real tracking value */}
                    {exchangeSl > 0 && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', opacity: 0.5 }}>
                            <span style={{ fontSize: '8px' }}>🛡️</span>
                            <span style={{ fontSize: '8px', color: COLORS.textTertiary }}>Backup:</span>
                            <span style={{ color: COLORS.sell, fontSize: '9px' }}>
                                ${formatPrice(exchangeSl)}
                            </span>
                            {/* Show -2% label only if backup SL is ~2% away from entry */}
                            {Math.abs((pos.entry_price - exchangeSl) / pos.entry_price) > 0.015 && (
                                <span style={{ fontSize: '7px', color: COLORS.textTertiary }}>(-2%)</span>
                            )}
                        </div>
                    )}

                    {/* Show TP from exchange if exists and no local TP */}
                    {exchangeTp > 0 && localTp === 0 && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', opacity: 0.6 }}>
                            <span style={{ fontSize: '8px' }}>🎯</span>
                            <span style={{ fontSize: '8px', color: COLORS.textTertiary }}>Exchange TP:</span>
                            <span style={{ color: COLORS.buy, fontSize: '9px' }}>
                                ${formatPrice(exchangeTp)}
                            </span>
                        </div>
                    )}

                    {/* Status indicators */}
                    {pos.is_orphan && localTp === 0 && localSl === 0 && (
                        <span style={{ fontSize: '7px', color: COLORS.yellow, opacity: 0.8 }}>⚠️ Orphan</span>
                    )}
                    {isLocalFirst && (
                        <span style={{ fontSize: '7px', color: COLORS.buy, opacity: 0.6 }}>🔒 Local-First</span>
                    )}
                    {isSynced && !isLocalFirst && (
                        <span style={{ fontSize: '7px', color: COLORS.buy, opacity: 0.6 }}>✓ Synced</span>
                    )}
                </div>
            </td>
            <td style={tdStyle('right')}>
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end' }}>
                    <span style={{ fontFamily: 'monospace', fontWeight: 700, color: pnlColor, fontSize: '12px' }}>{pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}</span>
                    <span style={{ fontFamily: 'monospace', fontSize: '10px', color: pnlColor }}>{roe.toFixed(2)}%</span>
                </div>
            </td>
            <td style={tdStyle('center')}><button onClick={() => onClose(pos.id)} style={{ padding: '4px 10px', fontSize: '10px', fontWeight: 600, borderRadius: '4px', border: `1px solid ${COLORS.bgTertiary}`, background: 'transparent', color: COLORS.textSecondary, cursor: 'pointer' }}>Close</button></td>
        </tr>
    );
});

const Portfolio: React.FC = () => {
    // SOTA: Adaptive UI - detect mobile for card-based view
    const { isMobile } = useBreakpoint();

    const [portfolio, setPortfolio] = useState<PortfolioData | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [isPendingExpanded, setIsPendingExpanded] = useState(true);
    const [pendingPage, setPendingPage] = useState(1);
    const [expandedOrderId, setExpandedOrderId] = useState<string | null>(null);

    // SOTA: Shark Tank Dashboard State
    const [sharkTankStatus, setSharkTankStatus] = useState<SharkTankStatus | null>(null);

    // SOTA Fix: useRef for WebSocket to prevent re-connection on re-render
    const wsRef = useRef<WebSocket | null>(null);

    // SOTA (Jan 2026): Multi-position realtime prices
    // Import and use the position subscription hook
    // Note: This is integrated inline since Portfolio already manages its own WebSocket
    // The hook will be used when we refactor to use the shared WebSocket from useWebSocket

    const fetchPortfolio = useCallback(async () => {
        try {
            const response = await fetch(apiUrl(ENDPOINTS.PORTFOLIO));
            if (!response.ok) throw new Error('Failed to fetch');
            const data = await response.json();
            setPortfolio({
                wallet_balance: data.balance ?? data.wallet_balance ?? 0,
                margin_balance: data.margin_balance ?? data.equity ?? 0,
                available_balance: data.available ?? data.available_balance ?? data.balance ?? 0,  // SOTA: Backend returns 'available'
                unrealized_pnl: data.unrealized_pnl ?? 0,
                total_equity: data.equity ?? data.margin_balance ?? 0,
                realized_pnl: data.realized_pnl ?? 0,
                open_positions: data.open_positions || [],
                pending_orders: data.pending_orders || [],
                pending_signals: data.pending_signals || [],      // SOTA: Pending signals
                pending_signals_count: data.pending_signals_count ?? 0
            });
            setError(null);
        } catch (err) {
            console.error(err);
            setError('Unable to load portfolio');
        } finally {
            setIsLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchPortfolio();

        // SOTA: Fetch Shark Tank status
        const fetchSharkTankStatus = async () => {
            try {
                const res = await fetch(apiUrl(ENDPOINTS.SHARK_TANK_STATUS));
                if (res.ok) {
                    const data = await res.json();
                    setSharkTankStatus(data);
                }
            } catch (e) {
                console.debug('Shark Tank status fetch failed:', e);
            }
        };
        fetchSharkTankStatus();

        // SOTA: Fallback REST polling every 30 seconds (reduced from 10s to lower API load)
        const interval = setInterval(fetchPortfolio, 30000);

        // SOTA FIX (Jan 2026): Increase from 5s to 30s to prevent polling flood
        const sharkTankInterval = setInterval(fetchSharkTankStatus, 30000);

        // SOTA Fix: WebSocket listener using useRef (prevents re-connection on re-render)
        // Connect to existing market stream - balance_update events are broadcast to ALL clients
        // SOTA (Jan 2026): Use centralized config instead of hardcoded URL
        const wsAddress = wsUrl(ENDPOINTS.WS_STREAM('btcusdt'));

        // Only create WS if not already connected
        if (!wsRef.current || wsRef.current.readyState === WebSocket.CLOSED) {
            try {
                wsRef.current = new WebSocket(wsAddress);
                wsRef.current.onmessage = (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        // Listen for balance_update events (broadcast to all connected clients)
                        if (data.type === 'balance_update') {
                            console.log('📡 Real-time balance update:', data);
                            setPortfolio(prev => prev ? {
                                ...prev,
                                wallet_balance: data.wallet_balance ?? prev.wallet_balance,
                                unrealized_pnl: data.unrealized_pnl ?? prev.unrealized_pnl,
                                total_equity: data.margin_balance ?? prev.total_equity,
                                margin_balance: data.margin_balance ?? prev.margin_balance,
                                available_balance: data.available_balance ?? prev.available_balance,
                            } : null);
                        }

                        // SOTA: Listen for signal events - add to pending signals
                        if (data.type === 'signal' && data.signal) {
                            console.log('🎯 Real-time signal received:', data.signal);
                            const newSignal: PendingSignal = {
                                id: data.signal.id || `sig_${Date.now()}`,
                                symbol: data.signal.symbol || data.symbol,
                                signal_type: data.signal.signal_type,
                                entry_price: data.signal.entry_price || data.signal.price,
                                stop_loss: data.signal.stop_loss || 0,
                                confidence: data.signal.confidence || 0.7,
                                generated_at: data.signal.timestamp || new Date().toISOString()
                            };

                            setPortfolio(prev => prev ? {
                                ...prev,
                                pending_signals: [newSignal, ...(prev.pending_signals || [])].slice(0, 10),
                                pending_signals_count: (prev.pending_signals_count || 0) + 1
                            } : null);

                            // SOTA: Show toast notification for new signal
                            try {
                                const toastEvent = new CustomEvent('signalToast', {
                                    detail: {
                                        id: newSignal.id,
                                        symbol: newSignal.symbol,
                                        signalType: newSignal.signal_type,
                                        entryPrice: newSignal.entry_price,
                                        stopLoss: newSignal.stop_loss,
                                        confidence: newSignal.confidence
                                    }
                                });
                                window.dispatchEvent(toastEvent);
                            } catch (e) {
                                // Toast optional
                            }
                            console.log(`🎯 NEW SIGNAL: ${newSignal.signal_type.toUpperCase()} ${newSignal.symbol} @ $${newSignal.entry_price}`);
                        }

                        // SOTA (Jan 2026): Multi-position realtime prices
                        // Handle price_update messages for portfolio positions
                        if (data.type === 'price_update') {
                            const symbol = data.symbol?.toLowerCase();
                            const price = data.price;
                            const timestamp = data.ts || Date.now();

                            if (symbol && typeof price === 'number') {
                                // Update positionPrices in marketStore
                                useMarketStore.getState().updatePositionPrice(symbol, price, timestamp);
                            }
                        }
                    } catch (e) {
                        // Silent - may be other event types
                    }
                };
                wsRef.current.onopen = () => {
                    console.log('📡 Portfolio WS connected (listening for balance_update)');

                    // SOTA (Jan 2026): Multi-position realtime prices
                    // Send subscription with priceOnly for all position symbols
                    if (portfolio?.open_positions && portfolio.open_positions.length > 0) {
                        const positionSymbols = [...new Set(portfolio.open_positions.map(p => p.symbol.toLowerCase()))];
                        // All position symbols go to priceOnly mode (lightweight updates)
                        // Active chart symbol is handled by useWebSocket hook
                        wsRef.current?.send(JSON.stringify({
                            type: 'subscribe',
                            symbols: ['btcusdt'],  // Default full mode symbol
                            priceOnly: positionSymbols
                        }));
                        console.log(`📊 Portfolio subscribed to priceOnly: ${positionSymbols.join(', ')}`);
                    }
                };
                wsRef.current.onclose = () => console.log('📡 Portfolio WS disconnected');
                wsRef.current.onerror = () => { }; // Silent errors - WS is optional enhancement
            } catch (e) {
                // WebSocket unavailable - REST polling will continue
            }
        }

        return () => {
            clearInterval(interval);
            clearInterval(sharkTankInterval);
            if (wsRef.current) {
                wsRef.current.close();
                wsRef.current = null;
            }
        };
    }, [fetchPortfolio]);

    const handleClosePosition = async (id: string) => {
        await fetch(apiUrl(ENDPOINTS.CLOSE_POSITION(id)), { method: 'POST' });
        fetchPortfolio();
    };

    const handleCloseAll = async () => {
        if (!portfolio?.open_positions.length) return;
        if (!confirm(`Close all ${portfolio.open_positions.length} positions?`)) return;
        for (const p of portfolio.open_positions) {
            await fetch(apiUrl(ENDPOINTS.CLOSE_POSITION(p.id)), { method: 'POST' });
        }
        fetchPortfolio();
    };

    // SOTA LocalSignalTracker: Cancel pending signal (local tracker, not exchange)
    const handleCancelPendingOrder = async (orderIdOrSymbol: string) => {
        try {
            // Extract symbol from orderId (format: sig_SYMBOL or just SYMBOL)
            const symbol = orderIdOrSymbol.replace('sig_', '').toUpperCase();
            const response = await fetch(apiUrl(`/trades/signals/cancel/${symbol}`), { method: 'POST' });
            if (response.ok) {
                fetchPortfolio();
            }
        } catch (err) {
            console.error('Failed to cancel pending signal:', err);
        }
    };

    // SOTA: Cancel all pending orders
    const handleCancelAllPending = async () => {
        if (!pendingOrders.length) return;
        if (!confirm(`Cancel all ${pendingOrders.length} pending orders?`)) return;
        try {
            const response = await fetch(apiUrl(ENDPOINTS.CANCEL_ALL_PENDING), { method: 'DELETE' });
            if (response.ok) {
                fetchPortfolio();
            }
        } catch (err) {
            console.error('Failed to cancel all pending orders:', err);
        }
    };

    // Pagination logic for Pending Orders
    const pendingOrders = portfolio?.pending_orders || [];
    const totalPendingPages = Math.max(1, Math.ceil(pendingOrders.length / ITEMS_PER_PAGE));
    const paginatedPending = useMemo(() => {
        const start = (pendingPage - 1) * ITEMS_PER_PAGE;
        return pendingOrders.slice(start, start + ITEMS_PER_PAGE);
    }, [pendingOrders, pendingPage]);

    // Loading / Error
    if (isLoading && !portfolio) {
        return (
            <div style={glassContainer}>
                <SkeletonLoader />
            </div>
        );
    }
    if (error) return <div style={{ ...glassContainer, color: COLORS.sell }}>{error}</div>;

    // SOTA: Render mobile card-based view on mobile devices (REQ-7.1, REQ-7.2)
    if (isMobile) {
        return (
            <div style={glassContainer}>
                <PortfolioMobile
                    positions={portfolio?.open_positions || []}
                    pendingOrders={portfolio?.pending_orders || []}
                    balance={{
                        wallet_balance: portfolio?.wallet_balance || 0,
                        available_balance: portfolio?.available_balance || 0,
                        unrealized_pnl: portfolio?.unrealized_pnl || 0,
                        margin_balance: portfolio?.margin_balance,
                    }}
                    sharkTankStatus={sharkTankStatus}
                    onClosePosition={handleClosePosition}
                    onCloseAllPositions={handleCloseAll}
                    onCancelOrder={handleCancelPendingOrder}
                    onCancelAllOrders={handleCancelAllPending}
                    onRefresh={fetchPortfolio}
                    isLoading={isLoading}
                />
            </div>
        );
    }

    // Desktop view (existing table-based layout)
    return (
        <div style={glassContainer}>
            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingBottom: '16px', borderBottom: `1px solid ${COLORS.bgTertiary}`, marginBottom: '16px' }}>
                <h2 style={{ fontSize: '16px', fontWeight: 700, color: COLORS.textPrimary, margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Briefcase size={18} style={{ color: COLORS.yellow }} /> Portfolio
                    {/* SOTA (Jan 2026): WebSocket connection status indicator */}
                    <WebSocketStatus compact />
                </h2>
                {portfolio?.open_positions && portfolio.open_positions.length > 0 && (
                    <button onClick={handleCloseAll} style={{ padding: '6px 12px', fontSize: '11px', fontWeight: 600, borderRadius: '6px', border: `1px solid ${COLORS.sell}40`, background: `${COLORS.sell}15`, color: COLORS.sell, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <XCircle size={12} /> Close All
                    </button>
                )}
            </div>

            {/* SOTA (Jan 2026): Enhanced Shark Tank Watchlist with collapsible sections */}
            {sharkTankStatus && (
                <SharkTankWatchlist
                    maxPositions={sharkTankStatus.max_positions}
                    currentPositions={sharkTankStatus.current_positions}
                    availableSlots={sharkTankStatus.available_slots}
                    leverage={sharkTankStatus.leverage}
                    availableMargin={sharkTankStatus.available_margin}
                    tradingMode={sharkTankStatus.trading_mode || 'PAPER'}
                    watchedTokens={sharkTankStatus.watched_tokens || []}
                    positionSymbols={sharkTankStatus.position_symbols || []}
                    pendingSymbols={sharkTankStatus.pending_symbols || []}
                    queuedSignals={sharkTankStatus.pending_list || []}
                    onTokenClick={(symbol) => {
                        // Switch chart to clicked symbol
                        window.dispatchEvent(new CustomEvent('switchSymbol', { detail: symbol }));
                    }}
                />
            )}

            {/* Metrics */}
            {/* SOTA: 4 balance fields matching Binance Futures UI */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '10px', marginBottom: '20px' }}>
                <MetricCard label="Wallet Balance" value={`$${formatPrice(portfolio?.wallet_balance || 0)}`} />
                {/* SOTA: Use realtime calculation for Unrealized PNL using Mainnet prices */}
                <RealtimePnLCard positions={portfolio?.open_positions || []} />
                <MetricCard label="Equity" value={`$${formatPrice(portfolio?.total_equity || 0)}`} />
                <MetricCard label="Available" value={`$${formatPrice(portfolio?.available_balance || 0)}`} />
            </div>

            {/* SOTA: Low margin warning - trading paused when < $10 */}
            {(portfolio?.available_balance || 0) < 10 && (
                <div style={{
                    background: 'rgba(246, 70, 93, 0.15)',
                    border: `1px solid ${COLORS.sell}`,
                    borderRadius: '8px',
                    padding: '12px 16px',
                    marginBottom: '16px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '12px'
                }}>
                    <span style={{ fontSize: '18px' }}>⚠️</span>
                    <div>
                        <div style={{ fontSize: '13px', fontWeight: 600, color: COLORS.sell }}>
                            Low Margin Warning
                        </div>
                        <div style={{ fontSize: '11px', color: COLORS.textSecondary }}>
                            Available balance ${formatPrice(portfolio?.available_balance || 0)} is below minimum ($5).
                            New orders are paused until funds are added.
                        </div>
                    </div>
                </div>
            )}

            {/* Positions Table - FIXED HEIGHT to prevent CLS */}
            <div style={{ minHeight: '250px', maxHeight: '300px', overflowY: 'auto', marginBottom: '16px', background: COLORS.bgPrimary, borderRadius: '8px', border: `1px solid ${COLORS.bgTertiary}` }}>
                {(!portfolio?.open_positions || portfolio.open_positions.length === 0) ? (
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', minHeight: '200px', color: COLORS.textTertiary }}>
                        <Briefcase size={32} style={{ marginBottom: '12px', opacity: 0.2 }} />
                        <div style={{ fontSize: '13px' }}>No open positions</div>
                    </div>
                ) : (
                    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                        <thead><tr>
                            <th style={thStyle('left')}>Symbol</th>
                            <th style={thStyle('right')}>Size</th>
                            <th style={thStyle('right')}>Entry</th>
                            <th style={thStyle('right')}>Mark</th>
                            <th style={thStyle('right')}>Margin</th>
                            <th style={thStyle('right')}>TP / SL</th>
                            <th style={thStyle('right')}>PnL (ROE)</th>
                            <th style={thStyle('center')}>Action</th>
                        </tr></thead>
                        <tbody>
                            {portfolio.open_positions.map((pos, i) => (
                                <PortfolioRow
                                    key={pos.id}
                                    pos={pos}
                                    index={i}
                                    onClose={handleClosePosition}
                                />
                            ))}
                        </tbody>
                    </table>
                )}
            </div>

            {/* Collapsible Pending Orders */}
            <div style={{ borderTop: `1px solid ${COLORS.bgTertiary}`, paddingTop: '16px', flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
                <div onClick={() => setIsPendingExpanded(!isPendingExpanded)} style={{ fontSize: '13px', fontWeight: 600, color: COLORS.textSecondary, margin: 0, display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', marginBottom: '12px', flex: 1 }}>
                    {isPendingExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                    <Clock size={14} style={{ color: COLORS.yellow }} /> Pending Orders ({pendingOrders.length})
                </div>
                {pendingOrders.length > 0 && (
                    <button onClick={handleCancelAllPending} style={{ padding: '4px 10px', fontSize: '10px', fontWeight: 600, borderRadius: '4px', border: `1px solid ${COLORS.sell}40`, background: `${COLORS.sell}15`, color: COLORS.sell, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <XCircle size={12} /> Cancel All
                    </button>
                )}
            </div>

            {isPendingExpanded && (
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
                    {/* Fixed height container - PREVENTS CLS */}
                    <div style={{ minHeight: '200px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                        {pendingOrders.length === 0 ? (
                            <div style={{ textAlign: 'center', padding: '40px', color: COLORS.textTertiary, fontSize: '12px' }}>No pending orders</div>
                        ) : (
                            paginatedPending.map(order => (
                                <PendingOrderCard
                                    key={order.id}
                                    order={order}
                                    isExpanded={expandedOrderId === order.id}
                                    onToggle={() => setExpandedOrderId(expandedOrderId === order.id ? null : order.id)}
                                    onCancel={() => handleCancelPendingOrder(order.symbol)}
                                />
                            ))
                        )}
                    </div>

                    {/* Pagination */}
                    {totalPendingPages > 1 && (
                        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '8px', marginTop: '12px', paddingTop: '12px', borderTop: `1px solid ${COLORS.bgTertiary}` }}>
                            <button onClick={() => setPendingPage(p => Math.max(1, p - 1))} disabled={pendingPage === 1} style={{ padding: '6px 10px', borderRadius: '4px', border: 'none', background: COLORS.bgTertiary, color: COLORS.textSecondary, cursor: pendingPage === 1 ? 'not-allowed' : 'pointer', opacity: pendingPage === 1 ? 0.5 : 1 }}><ChevronLeft size={14} /></button>
                            <span style={{ fontSize: '12px', color: COLORS.textSecondary }}>{pendingPage} / {totalPendingPages}</span>
                            <button onClick={() => setPendingPage(p => Math.min(totalPendingPages, p + 1))} disabled={pendingPage === totalPendingPages} style={{ padding: '6px 10px', borderRadius: '4px', border: 'none', background: COLORS.bgTertiary, color: COLORS.textSecondary, cursor: pendingPage === totalPendingPages ? 'not-allowed' : 'pointer', opacity: pendingPage === totalPendingPages ? 0.5 : 1 }}><ChevronRight size={14} /></button>
                        </div>
                    )}
                </div>
            )}

            {/* SOTA: Pending Signals Section */}
            {portfolio?.pending_signals && portfolio.pending_signals.length > 0 && (
                <div style={{ marginTop: '16px', padding: '16px', background: COLORS.bgSecondary, borderRadius: '8px', border: `1px solid ${COLORS.yellow}40` }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
                        <span style={{ fontSize: '14px', fontWeight: 700, color: COLORS.yellow }}>🎯 Pending Signals</span>
                        <span style={{ fontSize: '12px', color: COLORS.textSecondary }}>({portfolio.pending_signals.length})</span>
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                        {portfolio.pending_signals.map((sig) => {
                            const isLong = sig.signal_type === 'buy';
                            const sideColor = isLong ? COLORS.buy : COLORS.sell;
                            return (
                                <div key={sig.id} style={{
                                    padding: '10px 12px',
                                    background: COLORS.bgPrimary,
                                    borderRadius: '6px',
                                    border: `1px solid ${sideColor}40`,
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'space-between'
                                }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                                        <TokenIcon symbol={sig.symbol} size={20} />
                                        <span style={{ fontWeight: 600, color: COLORS.textPrimary }}>{sig.symbol}</span>
                                        <span style={{
                                            padding: '2px 8px',
                                            borderRadius: '4px',
                                            fontSize: '10px',
                                            fontWeight: 700,
                                            background: `${sideColor}20`,
                                            color: sideColor
                                        }}>
                                            {isLong ? 'LONG' : 'SHORT'}
                                        </span>
                                    </div>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '16px', fontSize: '11px' }}>
                                        <span style={{ color: COLORS.textSecondary }}>Entry: <span style={{ color: COLORS.textPrimary, fontFamily: 'monospace' }}>${formatPrice(sig.entry_price)}</span></span>
                                        <span style={{ color: COLORS.textSecondary }}>SL: <span style={{ color: COLORS.sell, fontFamily: 'monospace' }}>${formatPrice(sig.stop_loss)}</span></span>
                                        <span style={{ color: COLORS.textSecondary }}>Conf: <span style={{ color: COLORS.yellow, fontFamily: 'monospace' }}>{(sig.confidence * 100).toFixed(0)}%</span></span>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}
        </div>
    );
};

// --- Pending Order Card (SignalCard-style) ---
const PendingOrderCard = ({ order, isExpanded, onToggle, onCancel }: { order: PendingOrder; isExpanded: boolean; onToggle: () => void; onCancel: () => void }) => {
    // SOTA FIX: Normalize side - handle both LONG/SHORT and BUY/SELL formats
    const normalizedSide = order.side === 'BUY' || order.side === 'LONG' ? 'LONG' : 'SHORT';
    const sideColor = normalizedSide === 'LONG' ? COLORS.buy : COLORS.sell;
    const sideLabel = normalizedSide === 'LONG' ? 'BUY' : 'SELL'; // Display as BUY/SELL for clarity
    const sz = order.size || order.quantity || 0;
    const sl = order.stop_loss || 0;
    const tp1 = order.take_profit || (order.take_profits?.[0]) || 0;
    const tp2 = order.take_profits?.[1] || 0;

    return (
        <div style={{
            background: COLORS.bgSecondary,
            borderRadius: '8px',
            border: `1px solid ${sideColor}`,
            overflow: 'hidden',
            boxShadow: `0 0 15px ${sideColor}30`,
        }}>
            {/* Header (Always Visible) */}
            <div onClick={onToggle} style={{
                padding: '12px 16px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                background: `${sideColor}15`,
                cursor: 'pointer',
                borderBottom: isExpanded ? `1px solid ${COLORS.bgTertiary}` : 'none',
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <div style={{ width: '28px', height: '28px', borderRadius: '50%', background: sideColor, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#000', fontWeight: 700, fontSize: '14px' }}>
                        {normalizedSide === 'LONG' ? '↑' : '↓'}
                    </div>
                    <div>
                        <div style={{ fontSize: '14px', fontWeight: 700, color: sideColor, display: 'flex', alignItems: 'center', gap: '8px' }}>
                            {sideLabel} {order.symbol.toUpperCase()}
                            <span style={{ fontSize: '9px', padding: '2px 6px', borderRadius: '4px', background: COLORS.bgTertiary, color: COLORS.textSecondary }}>Pending</span>
                        </div>
                        <div style={{ fontSize: '11px', color: COLORS.textTertiary }}>{order.created_at || order.open_time || '--'}</div>
                    </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <span style={{ fontFamily: 'monospace', fontSize: '13px', color: COLORS.textPrimary, fontWeight: 600 }}>@${order.entry_price.toFixed(2)}</span>
                    <button
                        onClick={(e) => { e.stopPropagation(); onCancel(); }}
                        style={{
                            padding: '4px 8px',
                            fontSize: '10px',
                            fontWeight: 600,
                            borderRadius: '4px',
                            border: `1px solid ${COLORS.sell}40`,
                            background: `${COLORS.sell}15`,
                            color: COLORS.sell,
                            cursor: 'pointer',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '4px'
                        }}
                    >
                        <XCircle size={12} /> Cancel
                    </button>
                    <span style={{ color: COLORS.textTertiary, fontSize: '14px' }}>{isExpanded ? '▲' : '▼'}</span>
                </div>
            </div>

            {/* Body (Collapsible) */}
            {isExpanded && (
                <div style={{ padding: '16px' }}>
                    {/* Price Grid */}
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', marginBottom: '12px' }}>
                        <PriceItem label="Entry" value={`$${order.entry_price.toFixed(2)}`} color={COLORS.yellow} />
                        <PriceItem label="Stop Loss" value={sl > 0 ? `$${sl.toFixed(2)}` : '--'} color={COLORS.sell} />
                        <PriceItem label="TP1" value={tp1 > 0 ? `$${tp1.toFixed(2)}` : '--'} color={COLORS.buy} />
                        <PriceItem label="TP2" value={tp2 > 0 ? `$${tp2.toFixed(2)}` : '--'} color={COLORS.buy} />
                    </div>

                    {/* Details Row */}
                    <div style={{ display: 'flex', justifyContent: 'space-around', padding: '10px', background: COLORS.bgPrimary, borderRadius: '6px', fontSize: '11px' }}>
                        <div style={{ textAlign: 'center' }}><div style={{ color: COLORS.textTertiary, marginBottom: '2px' }}>Size</div><div style={{ color: COLORS.textPrimary, fontWeight: 600, fontFamily: 'monospace' }}>{sz.toFixed(4)}</div></div>
                        <div style={{ textAlign: 'center' }}><div style={{ color: COLORS.textTertiary, marginBottom: '2px' }}>Margin</div><div style={{ color: COLORS.textPrimary, fontWeight: 600, fontFamily: 'monospace' }}>${(order.margin || 0).toFixed(2)}</div></div>
                        <div style={{ textAlign: 'center' }}><div style={{ color: COLORS.textTertiary, marginBottom: '2px' }}>Leverage</div><div style={{ color: COLORS.textPrimary, fontWeight: 600 }}>{order.leverage || 1}x</div></div>
                    </div>
                </div>
            )}
        </div>
    );
};

const PriceItem = ({ label, value, color }: { label: string; value: string; color: string }) => (
    <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: '10px', color: COLORS.textTertiary, marginBottom: '4px' }}>{label}</div>
        <div style={{ fontSize: '13px', fontWeight: 700, color, fontFamily: 'monospace' }}>{value}</div>
    </div>
);

const MetricCard = ({ label, value, pnl }: { label: string; value: string; pnl?: number }) => {
    const color = pnl !== undefined ? (pnl >= 0 ? COLORS.buy : COLORS.sell) : COLORS.textPrimary;
    return (
        <div style={{ background: COLORS.bgSecondary, borderRadius: '6px', padding: '12px', border: `1px solid ${COLORS.bgTertiary}` }}>
            <div style={{ fontSize: '10px', color: COLORS.textTertiary, marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>{label}</div>
            <div style={{ fontSize: '14px', fontWeight: 700, color, fontFamily: 'monospace' }}>{value}</div>
        </div>
    );
};

const SkeletonLoader = () => (
    <>
        <div style={{ height: '24px', background: COLORS.bgSecondary, borderRadius: '4px', width: '150px', marginBottom: '16px' }}></div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '10px', marginBottom: '20px' }}>
            {[...Array(4)].map((_, i) => <div key={i} style={{ height: '50px', background: COLORS.bgSecondary, borderRadius: '6px' }}></div>)}
        </div>
        <div style={{ height: '200px', background: COLORS.bgSecondary, borderRadius: '8px' }}></div>
    </>
);

export default Portfolio;
