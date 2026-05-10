/**
 * Analytics Dashboard — v6.3.0 Binance Truth
 *
 * Institutional-grade analytics powered by Binance API data.
 * Layout: KPI → Equity/Drawdown → Session/Symbol → Direction/Significance/DZ
 *
 * v6.3.1: Interactive tooltips, action buttons, daily breakdown,
 *         responsive mobile, snapshot history
 */

import React, { useEffect, useMemo, useCallback, useState } from 'react';
import { useAnalyticsStore } from '../stores/analyticsStore';
import { Loader2, RefreshCw, AlertTriangle, TrendingUp, TrendingDown, Database, FileBarChart } from 'lucide-react';
import type {
    AnalyticsSummary,
    SessionData,
    SymbolDecomposition,
    DirectionData,
    EquityPoint,
    HourlyData,
    DailyBreakdown,
    SnapshotData,
} from '../services/analyticsService';

// ─── Theme (Binance Dark) ─────────────────────────────────────────────

const C = {
    profit: '#0ecb81',
    loss: '#f6465d',
    warning: '#f0b90b',
    info: '#2962ff',
    neutral: '#848e9c',
    bg0: '#0b0e11',
    bg1: '#181a20',
    bg2: '#1e2329',
    bg3: '#2b3139',
    text1: '#eaecef',
    text2: '#848e9c',
    text3: '#5e6673',
};

const card: React.CSSProperties = {
    background: C.bg2,
    borderRadius: 8,
    padding: 16,
    marginBottom: 12,
    border: `1px solid ${C.bg3}`,
};

const sectionLabel: React.CSSProperties = {
    margin: '0 0 12px',
    fontSize: 13,
    fontWeight: 600,
    color: C.text2,
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
};

// ─── Helpers ──────────────────────────────────────────────────────────

const pnlColor = (v: number) => (v >= 0 ? C.profit : C.loss);
const pnl$ = (v: number) => `${v >= 0 ? '+' : ''}$${v.toFixed(2)}`;
const pct = (v: number) => `${v.toFixed(1)}%`;
const safe = (v: number | null | undefined, fallback = 0) =>
    v != null && isFinite(v) ? v : fallback;

// ─── Responsive CSS injection ─────────────────────────────────────────

const responsiveStyles = `
@keyframes spin { to { transform: rotate(360deg) } }
.analytics-kpi-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
    margin-bottom: 12px;
}
.analytics-heatmap-grid {
    display: grid;
    grid-template-columns: repeat(12, 1fr);
    gap: 3px;
}
.analytics-2col {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: 12px;
}
@media (max-width: 640px) {
    .analytics-kpi-grid {
        grid-template-columns: repeat(2, 1fr);
    }
    .analytics-heatmap-grid {
        grid-template-columns: repeat(6, 1fr);
    }
    .analytics-2col {
        grid-template-columns: 1fr;
    }
}
`;

// ─── KPI Card ─────────────────────────────────────────────────────────

interface KpiProps {
    label: string;
    value: string;
    color?: string;
    sub?: string;
}

function KpiCard({ label, value, color, sub }: KpiProps) {
    return (
        <div
            style={{
                background: C.bg2,
                borderRadius: 8,
                padding: '12px 14px',
                border: `1px solid ${C.bg3}`,
                minWidth: 0,
            }}
        >
            <div style={{ fontSize: 11, color: C.text2, marginBottom: 4 }}>{label}</div>
            <div
                style={{
                    fontSize: 18,
                    fontWeight: 700,
                    color: color || C.text1,
                    fontVariantNumeric: 'tabular-nums',
                }}
            >
                {value}
            </div>
            {sub && (
                <div style={{ fontSize: 11, color: C.text3, marginTop: 2 }}>{sub}</div>
            )}
        </div>
    );
}

// ─── Equity Curve (SVG + Tooltip) ─────────────────────────────────────

function EquityCurve({ data }: { data: EquityPoint[] }) {
    const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);

    if (!data.length) return null;

    const W = 600,
        H = 180,
        pad = { top: 10, right: 40, bottom: 20, left: 10 };
    const w = W - pad.left - pad.right;
    const h = H - pad.top - pad.bottom;

    const values = data.map((d) => d.cumulative_pnl);
    const minY = Math.min(0, ...values);
    const maxY = Math.max(0, ...values);
    const rangeY = maxY - minY || 1;

    const x = (i: number) => pad.left + (i / Math.max(data.length - 1, 1)) * w;
    const y = (v: number) => pad.top + h - ((v - minY) / rangeY) * h;

    const linePath = data.map((d, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(d.cumulative_pnl).toFixed(1)}`).join(' ');
    const zeroY = y(0);

    // HWM line
    let hwm = -Infinity;
    const hwmPath = data
        .map((d, i) => {
            hwm = Math.max(hwm, d.cumulative_pnl);
            return `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(hwm).toFixed(1)}`;
        })
        .join(' ');

    const final = values[values.length - 1];
    const hovered = hoveredIdx !== null ? data[hoveredIdx] : null;

    return (
        <div style={card}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                <h3 style={{ ...sectionLabel, margin: 0 }}>Equity Curve — Binance Truth</h3>
                {hovered && (
                    <div style={{ fontSize: 10, color: C.text2, fontFamily: 'monospace', display: 'flex', gap: 8 }}>
                        <span>T{hovered.trade_num}</span>
                        <span style={{ color: C.text1 }}>{hovered.symbol?.replace('USDT', '')}</span>
                        <span style={{ color: hovered.result === 'WIN' ? C.profit : C.loss }}>{hovered.result}</span>
                        <span style={{ color: pnlColor(hovered.net_pnl) }}>{pnl$(hovered.net_pnl)}</span>
                        <span>cum: {pnl$(hovered.cumulative_pnl)}</span>
                    </div>
                )}
            </div>
            <svg
                viewBox={`0 0 ${W} ${H}`}
                style={{ width: '100%', height: 'auto' }}
                onMouseLeave={() => setHoveredIdx(null)}
            >
                {/* Zero line */}
                <line x1={pad.left} y1={zeroY} x2={W - pad.right} y2={zeroY} stroke={C.text3} strokeDasharray="4,3" strokeWidth={0.5} />

                {/* Positive/Negative fill */}
                <path
                    d={`${linePath} L${x(data.length - 1).toFixed(1)},${zeroY.toFixed(1)} L${pad.left},${zeroY.toFixed(1)} Z`}
                    fill={final >= 0 ? 'rgba(14,203,129,0.08)' : 'rgba(246,70,93,0.08)'}
                />

                {/* HWM dashed */}
                <path d={hwmPath} fill="none" stroke={C.warning} strokeWidth={0.7} strokeDasharray="3,3" opacity={0.5} />

                {/* Main line */}
                <path d={linePath} fill="none" stroke={final >= 0 ? C.profit : C.loss} strokeWidth={1.5} />

                {/* Hover crosshair */}
                {hoveredIdx !== null && (
                    <line
                        x1={x(hoveredIdx)}
                        y1={pad.top}
                        x2={x(hoveredIdx)}
                        y2={H - pad.bottom}
                        stroke={C.text3}
                        strokeDasharray="2,2"
                        strokeWidth={0.5}
                    />
                )}

                {/* Win/Loss dots — interactive */}
                {data.map((d, i) => (
                    <circle
                        key={i}
                        cx={x(i)}
                        cy={y(d.cumulative_pnl)}
                        r={hoveredIdx === i ? 4 : 2.2}
                        fill={d.result === 'WIN' ? C.profit : C.loss}
                        opacity={hoveredIdx === i ? 1 : 0.7}
                        style={{ cursor: 'pointer', transition: 'r 0.1s' }}
                        onMouseEnter={() => setHoveredIdx(i)}
                    />
                ))}

                {/* Final label */}
                <text x={W - pad.right + 4} y={y(final)} fontSize={11} fontWeight={700} fill={pnlColor(final)} dominantBaseline="middle">
                    {pnl$(final)}
                </text>

                {/* X labels */}
                <text x={pad.left} y={H - 2} fontSize={9} fill={C.text3}>T1</text>
                <text x={W - pad.right} y={H - 2} fontSize={9} fill={C.text3} textAnchor="end">T{data.length}</text>
            </svg>
        </div>
    );
}

// ─── Drawdown Chart ───────────────────────────────────────────────────

function DrawdownChart({ data }: { data: EquityPoint[] }) {
    if (data.length < 2) return null;

    const W = 600,
        H = 80,
        pad = { left: 10, right: 40, top: 5, bottom: 5 };
    const w = W - pad.left - pad.right;
    const h = H - pad.top - pad.bottom;

    let peak = -Infinity;
    const dd = data.map((d) => {
        peak = Math.max(peak, d.cumulative_pnl);
        return peak - d.cumulative_pnl;
    });
    const maxDD = Math.max(...dd, 0.01);

    const x = (i: number) => pad.left + (i / Math.max(data.length - 1, 1)) * w;
    const y = (v: number) => pad.top + (v / maxDD) * h;

    const areaPath =
        dd.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ') +
        ` L${x(dd.length - 1).toFixed(1)},${pad.top} L${pad.left},${pad.top} Z`;

    return (
        <div style={{ ...card, padding: '8px 16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                <span style={{ fontSize: 11, color: C.text2, fontWeight: 600, textTransform: 'uppercase' }}>Drawdown</span>
                <span style={{ fontSize: 12, color: C.loss, fontWeight: 700 }}>Max: ${maxDD.toFixed(2)}</span>
            </div>
            <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto' }}>
                <path d={areaPath} fill="rgba(246,70,93,0.2)" />
                <path
                    d={dd.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')}
                    fill="none"
                    stroke={C.loss}
                    strokeWidth={1.2}
                />
            </svg>
        </div>
    );
}

// ─── Session Heatmap (24h, responsive) ────────────────────────────────

function SessionHeatmap({ hourly }: { hourly: HourlyData[] }) {
    if (!hourly.length) return null;

    const maxAbsPnl = Math.max(...hourly.map((h) => Math.abs(h.net_pnl)), 0.01);

    return (
        <div style={card}>
            <h3 style={sectionLabel}>Session Heatmap (UTC+7)</h3>
            <div className="analytics-heatmap-grid">
                {hourly.map((h) => {
                    const intensity = Math.min(Math.abs(h.net_pnl) / maxAbsPnl, 1);
                    const bgColor = h.in_dead_zone
                        ? `rgba(94,102,115,${0.15 + intensity * 0.2})`
                        : h.net_pnl >= 0
                            ? `rgba(14,203,129,${0.1 + intensity * 0.5})`
                            : `rgba(246,70,93,${0.1 + intensity * 0.5})`;

                    return (
                        <div
                            key={h.hour}
                            style={{
                                background: bgColor,
                                borderRadius: 4,
                                padding: '6px 2px',
                                textAlign: 'center',
                                border: h.in_dead_zone ? `1px dashed ${C.text3}` : '1px solid transparent',
                                opacity: h.in_dead_zone ? 0.6 : 1,
                            }}
                            title={`${h.label} | ${h.trades} trades | WR ${h.win_rate}% | ${pnl$(h.net_pnl)}${h.in_dead_zone ? ' (Dead Zone)' : ''}`}
                        >
                            <div style={{ fontSize: 10, fontWeight: 600, color: C.text1 }}>{h.hour.toString().padStart(2, '0')}</div>
                            <div style={{ fontSize: 9, color: pnlColor(h.net_pnl), fontWeight: 600, marginTop: 2 }}>
                                {h.trades > 0 ? pnl$(h.net_pnl) : '-'}
                            </div>
                            <div style={{ fontSize: 8, color: C.text3, marginTop: 1 }}>
                                {h.trades > 0 ? `${h.trades}t ${pct(h.win_rate)}` : ''}
                            </div>
                        </div>
                    );
                })}
            </div>
            <div style={{ display: 'flex', gap: 12, marginTop: 8, fontSize: 10, color: C.text3, flexWrap: 'wrap' }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <span style={{ width: 10, height: 10, borderRadius: 2, background: 'rgba(14,203,129,0.4)' }} /> Profit
                </span>
                <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <span style={{ width: 10, height: 10, borderRadius: 2, background: 'rgba(246,70,93,0.4)' }} /> Loss
                </span>
                <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <span style={{ width: 10, height: 10, borderRadius: 2, border: `1px dashed ${C.text3}`, background: 'rgba(94,102,115,0.2)' }} /> Dead Zone
                </span>
            </div>
        </div>
    );
}

// ─── Symbol Attribution ───────────────────────────────────────────────

function SymbolAttribution({ data }: { data: SymbolDecomposition }) {
    const top5 = useMemo(() => [...data.symbols].sort((a, b) => b.net_pnl - a.net_pnl).slice(0, 5), [data]);
    const bot5 = useMemo(() => [...data.symbols].sort((a, b) => a.net_pnl - b.net_pnl).slice(0, 5), [data]);
    const maxAbs = Math.max(...data.symbols.map((s) => Math.abs(s.net_pnl)), 0.01);

    const renderBar = (s: (typeof data.symbols)[0]) => {
        const width = Math.min((Math.abs(s.net_pnl) / maxAbs) * 100, 100);
        return (
            <div key={s.symbol} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                <span style={{ fontSize: 11, color: C.text1, width: 80, flexShrink: 0, fontFamily: 'monospace' }}>
                    {s.symbol.replace('USDT', '')}
                </span>
                <div style={{ flex: 1, height: 14, background: C.bg3, borderRadius: 3, overflow: 'hidden' }}>
                    <div
                        style={{
                            height: '100%',
                            width: `${width}%`,
                            background: s.net_pnl >= 0 ? C.profit : C.loss,
                            borderRadius: 3,
                            opacity: 0.8,
                        }}
                    />
                </div>
                <span style={{ fontSize: 11, color: pnlColor(s.net_pnl), fontWeight: 600, width: 55, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                    {pnl$(s.net_pnl)}
                </span>
                <span style={{ fontSize: 10, color: C.text3, width: 42, textAlign: 'right' }}>
                    {pct(s.win_rate)}
                </span>
            </div>
        );
    };

    return (
        <div style={card}>
            <h3 style={sectionLabel}>Symbol Attribution</h3>
            <div style={{ display: 'flex', gap: 8, marginBottom: 8, fontSize: 10, flexWrap: 'wrap' }}>
                <span style={{ padding: '2px 8px', background: 'rgba(14,203,129,0.15)', borderRadius: 4, color: C.profit }}>
                    ALPHA+ {data.summary.alpha_count} ({pnl$(data.summary.alpha_pnl)})
                </span>
                <span style={{ padding: '2px 8px', background: 'rgba(246,70,93,0.15)', borderRadius: 4, color: C.loss }}>
                    TOXIC {data.summary.toxic_count} ({pnl$(data.summary.toxic_pnl)})
                </span>
            </div>
            <div style={{ marginBottom: 8 }}>
                <div style={{ fontSize: 10, color: C.profit, fontWeight: 600, marginBottom: 4 }}>TOP 5</div>
                {top5.map(renderBar)}
            </div>
            <div>
                <div style={{ fontSize: 10, color: C.loss, fontWeight: 600, marginBottom: 4 }}>BOTTOM 5</div>
                {bot5.map(renderBar)}
            </div>
        </div>
    );
}

// ─── Direction Split ──────────────────────────────────────────────────

function DirectionSplit({ data }: { data: DirectionData }) {
    const { long: l, short: s } = data;
    const total = l.trades + s.trades || 1;

    return (
        <div style={card}>
            <h3 style={sectionLabel}>Direction Analysis</h3>
            {/* Proportion bar */}
            <div style={{ display: 'flex', height: 8, borderRadius: 4, overflow: 'hidden', marginBottom: 12 }}>
                <div style={{ width: `${(l.trades / total) * 100}%`, background: C.profit }} />
                <div style={{ width: `${(s.trades / total) * 100}%`, background: C.loss }} />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                {[
                    { d: l, label: 'LONG', icon: <TrendingUp size={14} />, color: C.profit },
                    { d: s, label: 'SHORT', icon: <TrendingDown size={14} />, color: C.loss },
                ].map(({ d, label, icon, color }) => (
                    <div key={label} style={{ background: C.bg1, borderRadius: 6, padding: 10 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 4, color, fontSize: 12, fontWeight: 700, marginBottom: 6 }}>
                            {icon} {label}
                        </div>
                        <div style={{ fontSize: 20, fontWeight: 700, color }}>{pct(d.win_rate)} WR</div>
                        <div style={{ fontSize: 12, color: pnlColor(d.net_pnl), fontWeight: 600, marginTop: 2 }}>{pnl$(d.net_pnl)}</div>
                        <div style={{ fontSize: 10, color: C.text3, marginTop: 4 }}>
                            {d.trades} trades | R:R {safe(d.rr_ratio).toFixed(2)}
                        </div>
                    </div>
                ))}
            </div>
            {data.recommendation && (
                <div style={{ marginTop: 8, fontSize: 11, color: C.warning, background: 'rgba(240,185,11,0.08)', padding: '6px 10px', borderRadius: 4 }}>
                    {data.recommendation}
                </div>
            )}
        </div>
    );
}

// ─── Statistical Significance ─────────────────────────────────────────

function SignificancePanel({ summary }: { summary: AnalyticsSummary }) {
    const sig = summary.significance;
    if (!sig) return null;

    const color = sig.is_significant ? C.profit : C.loss;
    const label = sig.is_significant ? 'SIGNIFICANT' : 'NOT significant';

    // Progress ring for p-value (lower = better)
    const pValuePct = Math.min(sig.p_value * 100, 100);
    const circumference = 2 * Math.PI * 20;
    const strokeOffset = circumference * (1 - pValuePct / 100);

    return (
        <div style={card}>
            <h3 style={sectionLabel}>Statistical Significance</h3>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
                {/* p-value ring gauge */}
                <svg width={52} height={52} viewBox="0 0 52 52">
                    <circle cx={26} cy={26} r={20} fill="none" stroke={C.bg3} strokeWidth={3} />
                    <circle
                        cx={26} cy={26} r={20}
                        fill="none"
                        stroke={color}
                        strokeWidth={3}
                        strokeDasharray={circumference}
                        strokeDashoffset={strokeOffset}
                        strokeLinecap="round"
                        transform="rotate(-90 26 26)"
                    />
                    <text x={26} y={26} textAnchor="middle" dominantBaseline="middle" fontSize={12} fontWeight={700} fill={color}>
                        {sig.p_value.toFixed(2)}
                    </text>
                </svg>
                <div>
                    <div style={{ fontSize: 13, fontWeight: 700, color }}>{label}</div>
                    <div style={{ fontSize: 11, color: C.text3 }}>p-value (Z = {sig.z_score.toFixed(2)})</div>
                </div>
            </div>
            <div style={{ fontSize: 11, color: C.text2, lineHeight: 1.5 }}>
                Edge: <span style={{ color: pnlColor(sig.edge_pp), fontWeight: 600 }}>{sig.edge_pp >= 0 ? '+' : ''}{sig.edge_pp.toFixed(1)}pp</span>
                {' | '}WR: {pct(sig.observed_wr)} vs BE: {pct(sig.breakeven_wr)}
                <br />
                {sig.trades_needed < 9999
                    ? `Need ~${sig.trades_needed} trades for 95% confidence`
                    : 'Edge too small for significance at any reasonable N'}
            </div>
        </div>
    );
}

// ─── Dead Zone Panel ──────────────────────────────────────────────────

function DeadZonePanel({ sessions }: { sessions: SessionData }) {
    const dz = sessions.dead_zone_analysis;
    if (!dz) return null;

    return (
        <div style={card}>
            <h3 style={sectionLabel}>Dead Zone Effectiveness</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 10 }}>
                <div style={{ background: C.bg1, borderRadius: 6, padding: 8 }}>
                    <div style={{ fontSize: 10, color: C.text3 }}>Active Trading</div>
                    <div style={{ fontSize: 16, fontWeight: 700, color: C.text1 }}>{dz.non_dz_trades} trades</div>
                    <div style={{ fontSize: 11, color: C.profit }}>{pct(dz.non_dz_win_rate)} WR | {pnl$(dz.non_dz_pnl)}</div>
                </div>
                <div style={{ background: C.bg1, borderRadius: 6, padding: 8 }}>
                    <div style={{ fontSize: 10, color: C.text3 }}>Would Block</div>
                    <div style={{ fontSize: 16, fontWeight: 700, color: C.loss }}>{dz.dz_trades_would_block} trades</div>
                    <div style={{ fontSize: 11, color: C.loss }}>{pct(dz.dz_would_block_wr)} WR | {pnl$(dz.dz_would_block_pnl)}</div>
                </div>
            </div>
            {dz.dz_pnl_saved > 0 && (
                <div style={{ fontSize: 12, color: C.profit, fontWeight: 600, marginBottom: 8 }}>
                    PnL Saved: +${dz.dz_pnl_saved.toFixed(2)}
                </div>
            )}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, fontSize: 10 }}>
                {dz.current_dead_zones.map((z) => (
                    <span key={z} style={{ padding: '3px 8px', background: 'rgba(246,70,93,0.1)', borderRadius: 4, color: C.loss, border: `1px solid rgba(246,70,93,0.2)` }}>
                        {z}
                    </span>
                ))}
            </div>
            {dz.gold_hours.length > 0 && (
                <div style={{ marginTop: 8 }}>
                    <div style={{ fontSize: 10, color: C.profit, fontWeight: 600, marginBottom: 4 }}>Gold Hours</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                        {dz.gold_hours.map((h) => (
                            <span key={h.hour} style={{ fontSize: 10, padding: '2px 6px', background: 'rgba(14,203,129,0.1)', borderRadius: 3, color: C.profit }}>
                                {h.hour.toString().padStart(2, '0')}h {pnl$(h.net_pnl)} ({pct(h.win_rate)})
                            </span>
                        ))}
                    </div>
                </div>
            )}
            {dz.toxic_hours.length > 0 && (
                <div style={{ marginTop: 6 }}>
                    <div style={{ fontSize: 10, color: C.loss, fontWeight: 600, marginBottom: 4 }}>Toxic Hours</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                        {dz.toxic_hours.map((h) => (
                            <span key={h.hour} style={{ fontSize: 10, padding: '2px 6px', background: 'rgba(246,70,93,0.1)', borderRadius: 3, color: C.loss }}>
                                {h.hour.toString().padStart(2, '0')}h {pnl$(h.net_pnl)} ({pct(h.win_rate)})
                            </span>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}

// ─── Rolling Metrics ──────────────────────────────────────────────────

function RollingChart({ points }: { points: { trade_num: number; rolling_wr: number; rolling_pnl: number }[] }) {
    if (points.length < 2) return null;

    const W = 600, H = 80;
    const pad = { left: 10, right: 40, top: 5, bottom: 5 };
    const w = W - pad.left - pad.right;
    const h = H - pad.top - pad.bottom;

    const wrValues = points.map((p) => p.rolling_wr);
    const minWR = Math.min(...wrValues);
    const maxWR = Math.max(...wrValues);
    const rangeWR = maxWR - minWR || 1;

    const x = (i: number) => pad.left + (i / Math.max(points.length - 1, 1)) * w;
    const y = (v: number) => pad.top + h - ((v - minWR) / rangeWR) * h;

    const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(p.rolling_wr).toFixed(1)}`).join(' ');
    const lastWR = wrValues[wrValues.length - 1];

    return (
        <div style={{ ...card, padding: '8px 16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <span style={{ fontSize: 11, color: C.text2, fontWeight: 600, textTransform: 'uppercase' }}>Rolling 20-Trade WR</span>
                <span style={{ fontSize: 12, color: pnlColor(lastWR - 60), fontWeight: 700 }}>{pct(lastWR)}</span>
            </div>
            <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto' }}>
                {/* 60% breakeven reference */}
                <line x1={pad.left} y1={y(60)} x2={W - pad.right} y2={y(60)} stroke={C.warning} strokeDasharray="3,3" strokeWidth={0.5} opacity={0.5} />
                <path d={path} fill="none" stroke={C.info} strokeWidth={1.5} />
            </svg>
        </div>
    );
}

// ─── Daily Breakdown Table ────────────────────────────────────────────

function DailyBreakdownTable({ days }: { days: DailyBreakdown[] }) {
    if (!days.length) return null;

    // Show most recent first
    const sorted = [...days].reverse();

    return (
        <div style={card}>
            <h3 style={sectionLabel}>Daily Breakdown</h3>
            <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, fontVariantNumeric: 'tabular-nums' }}>
                    <thead>
                        <tr style={{ borderBottom: `1px solid ${C.bg3}` }}>
                            {['Date', 'Trades', 'W/L', 'WR', 'Net PnL'].map((h) => (
                                <th key={h} style={{ padding: '6px 8px', textAlign: h === 'Date' ? 'left' : 'right', color: C.text3, fontWeight: 600 }}>
                                    {h}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {sorted.map((d) => (
                            <tr key={d.date} style={{ borderBottom: `1px solid ${C.bg3}` }}>
                                <td style={{ padding: '5px 8px', color: C.text1 }}>{d.date.slice(5)}</td>
                                <td style={{ padding: '5px 8px', textAlign: 'right', color: C.text2 }}>{d.trades}</td>
                                <td style={{ padding: '5px 8px', textAlign: 'right', color: C.text2 }}>
                                    <span style={{ color: C.profit }}>{d.wins}</span>/<span style={{ color: C.loss }}>{d.losses}</span>
                                </td>
                                <td style={{ padding: '5px 8px', textAlign: 'right', color: d.win_rate >= 60 ? C.profit : d.win_rate >= 50 ? C.warning : C.loss, fontWeight: 600 }}>
                                    {pct(d.win_rate)}
                                </td>
                                <td style={{ padding: '5px 8px', textAlign: 'right', color: pnlColor(d.net_pnl), fontWeight: 600 }}>
                                    {pnl$(d.net_pnl)}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

// ─── Snapshot History ─────────────────────────────────────────────────

function SnapshotHistory({ snapshots }: { snapshots: SnapshotData[] }) {
    if (!snapshots.length) return null;

    const sorted = [...snapshots].reverse().slice(0, 10);

    return (
        <div style={card}>
            <h3 style={sectionLabel}>Historical Snapshots (Last 10 Days)</h3>
            <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10, fontVariantNumeric: 'tabular-nums' }}>
                    <thead>
                        <tr style={{ borderBottom: `1px solid ${C.bg3}` }}>
                            {['Date', 'Trades', 'WR', 'PF', 'Net', 'Edge', 'Sharpe', 'p-val'].map((h) => (
                                <th key={h} style={{ padding: '5px 6px', textAlign: h === 'Date' ? 'left' : 'right', color: C.text3, fontWeight: 600 }}>
                                    {h}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {sorted.map((s) => (
                            <tr key={s.snapshot_date} style={{ borderBottom: `1px solid ${C.bg3}` }}>
                                <td style={{ padding: '4px 6px', color: C.text1 }}>{s.snapshot_date.slice(5)}</td>
                                <td style={{ padding: '4px 6px', textAlign: 'right', color: C.text2 }}>{s.total_trades}</td>
                                <td style={{ padding: '4px 6px', textAlign: 'right', color: s.win_rate >= 60 ? C.profit : C.loss }}>{pct(s.win_rate)}</td>
                                <td style={{ padding: '4px 6px', textAlign: 'right', color: s.profit_factor >= 1 ? C.profit : C.loss }}>{safe(s.profit_factor).toFixed(2)}</td>
                                <td style={{ padding: '4px 6px', textAlign: 'right', color: pnlColor(s.total_net_pnl), fontWeight: 600 }}>{pnl$(s.total_net_pnl)}</td>
                                <td style={{ padding: '4px 6px', textAlign: 'right', color: pnlColor(s.edge_pp) }}>{s.edge_pp >= 0 ? '+' : ''}{safe(s.edge_pp).toFixed(1)}</td>
                                <td style={{ padding: '4px 6px', textAlign: 'right', color: s.sharpe_per_trade > 0 ? C.profit : C.loss }}>{safe(s.sharpe_per_trade).toFixed(3)}</td>
                                <td style={{ padding: '4px 6px', textAlign: 'right', color: s.p_value < 0.05 ? C.profit : C.text3 }}>{safe(s.p_value).toFixed(2)}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

// ─── Version Filter Tabs ──────────────────────────────────────────────

function VersionTabs({ active, onChange }: { active: string | undefined; onChange: (v: string | undefined) => void }) {
    const versions = [
        { label: 'All', value: undefined },
        { label: 'v6.2.0', value: 'v6.2.0' },
        { label: 'v6.0.0', value: 'v6.0.0' },
    ];

    return (
        <div style={{ display: 'flex', gap: 6 }}>
            {versions.map((v) => (
                <button
                    key={v.label}
                    onClick={() => onChange(v.value)}
                    style={{
                        padding: '4px 12px',
                        borderRadius: 4,
                        border: 'none',
                        cursor: 'pointer',
                        fontSize: 12,
                        fontWeight: active === v.value ? 700 : 400,
                        background: active === v.value ? C.info : C.bg3,
                        color: active === v.value ? '#fff' : C.text2,
                    }}
                >
                    {v.label}
                </button>
            ))}
        </div>
    );
}

// ─── Action Button ────────────────────────────────────────────────────

function ActionButton({ icon, label, onClick, loading, variant = 'default' }: {
    icon: React.ReactNode;
    label: string;
    onClick: () => void;
    loading?: boolean;
    variant?: 'default' | 'primary';
}) {
    return (
        <button
            onClick={onClick}
            disabled={loading}
            style={{
                padding: '5px 10px',
                borderRadius: 4,
                border: variant === 'primary' ? 'none' : `1px solid ${C.bg3}`,
                background: variant === 'primary' ? C.info : C.bg2,
                color: variant === 'primary' ? '#fff' : C.text2,
                cursor: loading ? 'not-allowed' : 'pointer',
                fontSize: 11,
                display: 'flex',
                alignItems: 'center',
                gap: 4,
                opacity: loading ? 0.6 : 1,
                whiteSpace: 'nowrap',
            }}
        >
            {icon}
            {loading ? 'Working...' : label}
        </button>
    );
}

// ─── Main Dashboard ───────────────────────────────────────────────────

const Analytics: React.FC = () => {
    const {
        summary,
        sessions,
        symbols,
        directions,
        today,
        snapshots,
        isLoading,
        error,
        versionFilter,
        setVersionFilter,
        fetchAll,
        reconcile,
    } = useAnalyticsStore();

    const [reconciling, setReconciling] = useState(false);
    const [reporting, setReporting] = useState(false);

    // Fetch on mount + version change
    useEffect(() => {
        useAnalyticsStore.setState({ lastFetch: 0 });
        fetchAll();
    }, [versionFilter, fetchAll]);

    const handleRefresh = useCallback(() => {
        useAnalyticsStore.setState({ lastFetch: 0 });
        fetchAll();
    }, [fetchAll]);

    const handleReconcile = useCallback(async () => {
        setReconciling(true);
        try {
            const result = await reconcile();
            if (result) {
                console.log(`Reconciled: ${result.trades_collected} trades, ${result.new_trades} new`);
            }
        } finally {
            setReconciling(false);
        }
    }, [reconcile]);

    const handleDailyReport = useCallback(async () => {
        setReporting(true);
        try {
            const { analyticsApi } = await import('../services/analyticsService');
            await analyticsApi.triggerDailyReport();
        } catch (e) {
            console.error('Daily report failed:', e);
        } finally {
            setReporting(false);
        }
    }, []);

    // ─── Loading ──────────────────────────────────────────────
    if (isLoading && !summary) {
        return (
            <div style={{ background: C.bg0, minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', color: C.text2 }}>
                <style>{responsiveStyles}</style>
                <Loader2 size={24} style={{ animation: 'spin 1s linear infinite' }} />
                <span style={{ marginLeft: 8 }}>Loading analytics...</span>
            </div>
        );
    }

    // ─── Error ────────────────────────────────────────────────
    if (error && !summary) {
        return (
            <div style={{ background: C.bg0, minHeight: '100vh', padding: 24, color: C.text1 }}>
                <style>{responsiveStyles}</style>
                <div style={{ ...card, textAlign: 'center', padding: 32 }}>
                    <AlertTriangle size={32} color={C.warning} style={{ marginBottom: 12 }} />
                    <div style={{ fontSize: 14, marginBottom: 8 }}>Analytics Unavailable</div>
                    <div style={{ fontSize: 12, color: C.text3, marginBottom: 16 }}>{error}</div>
                    <button
                        onClick={handleRefresh}
                        style={{
                            padding: '8px 20px',
                            borderRadius: 4,
                            border: 'none',
                            background: C.info,
                            color: '#fff',
                            cursor: 'pointer',
                            fontSize: 12,
                        }}
                    >
                        Retry
                    </button>
                </div>
            </div>
        );
    }

    if (!summary) return null;

    const risk = summary.risk_metrics;
    const sig = summary.significance;

    return (
        <div style={{ background: C.bg0, minHeight: '100vh', padding: '12px 16px 80px', color: C.text1, fontFamily: "'Inter', -apple-system, sans-serif" }}>
            <style>{responsiveStyles}</style>

            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
                <div>
                    <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Analytics</h2>
                    <span style={{ fontSize: 10, color: C.text3 }}>Binance Truth | {summary.generated_at?.slice(0, 16) || ''}</span>
                </div>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    <ActionButton
                        icon={<Database size={11} />}
                        label="Reconcile"
                        onClick={handleReconcile}
                        loading={reconciling}
                    />
                    <ActionButton
                        icon={<FileBarChart size={11} />}
                        label="Daily Report"
                        onClick={handleDailyReport}
                        loading={reporting}
                    />
                    <ActionButton
                        icon={<RefreshCw size={11} style={isLoading ? { animation: 'spin 1s linear infinite' } : {}} />}
                        label={isLoading ? 'Loading...' : 'Refresh'}
                        onClick={handleRefresh}
                        variant="primary"
                    />
                </div>
            </div>

            {/* Version Filter */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
                <VersionTabs active={versionFilter} onChange={setVersionFilter} />
                <span style={{ fontSize: 10, color: C.text3 }}>
                    {summary.version_tag || 'all'} | {summary.total_trades} trades
                </span>
            </div>

            {/* Today banner */}
            {today && today.trades > 0 && (
                <div style={{ ...card, padding: '10px 14px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderColor: pnlColor(today.net_pnl), flexWrap: 'wrap', gap: 4 }}>
                    <span style={{ fontSize: 12, color: C.text2 }}>Today ({today.date})</span>
                    <span style={{ fontSize: 13, fontWeight: 700 }}>
                        {today.trades} trades | {today.wins}W/{today.losses}L = {pct(today.win_rate)} |{' '}
                        <span style={{ color: pnlColor(today.net_pnl) }}>{pnl$(today.net_pnl)}</span>
                    </span>
                </div>
            )}

            {/* KPI Cards — responsive grid */}
            <div className="analytics-kpi-grid">
                <KpiCard label="Net PnL" value={pnl$(summary.total_net_pnl)} color={pnlColor(summary.total_net_pnl)} sub={`${summary.total_trades} trades`} />
                <KpiCard label="Win Rate" value={pct(summary.win_rate)} color={summary.win_rate > safe(summary.breakeven_wr) ? C.profit : C.loss} sub={`${summary.wins}W / ${summary.losses}L`} />
                <KpiCard label="Profit Factor" value={safe(summary.profit_factor).toFixed(3)} color={summary.profit_factor >= 1 ? C.profit : C.loss} sub={`BE: ${pct(summary.breakeven_wr)}`} />
            </div>
            <div className="analytics-kpi-grid">
                <KpiCard label="R:R Ratio" value={safe(summary.rr_ratio).toFixed(3)} color={summary.rr_ratio >= 0.75 ? C.profit : summary.rr_ratio >= 0.5 ? C.warning : C.loss} sub={`Avg W: ${pnl$(summary.avg_win)}`} />
                <KpiCard label="Edge" value={`${summary.edge_pp >= 0 ? '+' : ''}${summary.edge_pp.toFixed(1)}pp`} color={pnlColor(summary.edge_pp)} sub={`p=${sig?.p_value?.toFixed(2) || '?'}`} />
                <KpiCard label="Sharpe" value={safe(risk.sharpe_per_trade).toFixed(3)} color={risk.sharpe_per_trade > 0 ? C.profit : C.loss} sub={`Max DD: $${safe(risk.max_drawdown).toFixed(2)}`} />
            </div>

            {/* Fee drag inline */}
            <div style={{ ...card, padding: '8px 14px', display: 'flex', justifyContent: 'space-between', fontSize: 11, flexWrap: 'wrap', gap: 4 }}>
                <span style={{ color: C.text3 }}>
                    Gross: <span style={{ color: pnlColor(summary.total_gross_pnl) }}>{pnl$(summary.total_gross_pnl)}</span>
                    {' | '}Fees: <span style={{ color: C.loss }}>-${safe(summary.total_fees).toFixed(2)}</span>
                    {' | '}Net: <span style={{ color: pnlColor(summary.total_net_pnl), fontWeight: 700 }}>{pnl$(summary.total_net_pnl)}</span>
                </span>
                <span style={{ color: safe(summary.fee_drag_pct) > 80 ? C.loss : C.warning }}>
                    Fee Drag: {safe(summary.fee_drag_pct).toFixed(0)}%
                </span>
            </div>

            {/* Equity Curve + Drawdown */}
            <EquityCurve data={summary.equity_curve || []} />
            <DrawdownChart data={summary.equity_curve || []} />

            {/* Rolling WR */}
            {summary.rolling?.points && <RollingChart points={summary.rolling.points} />}

            {/* Session Heatmap */}
            {sessions && <SessionHeatmap hourly={sessions.hourly} />}

            {/* Symbol + Direction */}
            <div className="analytics-2col">
                {symbols && <SymbolAttribution data={symbols} />}
                {directions && <DirectionSplit data={directions} />}
            </div>

            {/* Significance + Dead Zone */}
            <div className="analytics-2col">
                <SignificancePanel summary={summary} />
                {sessions && <DeadZonePanel sessions={sessions} />}
            </div>

            {/* Daily Breakdown */}
            {summary.daily_breakdown && <DailyBreakdownTable days={summary.daily_breakdown} />}

            {/* Snapshot History */}
            {snapshots.length > 0 && <SnapshotHistory snapshots={snapshots} />}

            {/* Streak info */}
            <div style={{ ...card, padding: '10px 14px', display: 'flex', justifyContent: 'space-between', fontSize: 11, flexWrap: 'wrap' }}>
                <span style={{ color: C.text3 }}>
                    Current Streak: <span style={{ color: risk.current_streak >= 0 ? C.profit : C.loss, fontWeight: 700 }}>
                        {risk.current_streak >= 0 ? `+${risk.current_streak} WIN` : `${risk.current_streak} LOSS`}
                    </span>
                </span>
                <span style={{ color: C.text3 }}>
                    Max Win: <span style={{ color: C.profit }}>{risk.max_win_streak}</span>
                    {' | '}Max Loss: <span style={{ color: C.loss }}>{risk.max_loss_streak}</span>
                </span>
            </div>
        </div>
    );
};

export default Analytics;
