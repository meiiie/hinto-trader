/**
 * SVG Icon Library - SOTA Professional Trading UI Icons
 *
 * Based on Binance 2025 design patterns:
 * - Consistent 24x24 viewBox
 * - Stroke-based for flexibility
 * - currentColor for easy theming
 */

interface IconProps {
    size?: number;
    color?: string;
    className?: string;
}

// 🔍 Scanning state
export const IconScan = ({ size = 16, color = 'currentColor', className }: IconProps) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
        strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
        <circle cx="11" cy="11" r="8" />
        <path d="m21 21-4.35-4.35" />
    </svg>
);

// 📈 In Position / Chart trending
export const IconTrendingUp = ({ size = 16, color = 'currentColor', className }: IconProps) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
        strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
        <polyline points="23 6 13.5 15.5 8.5 10.5 1 18" />
        <polyline points="17 6 23 6 23 12" />
    </svg>
);

// ⏳ Entry Pending / Hourglass
export const IconHourglass = ({ size = 16, color = 'currentColor', className }: IconProps) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
        strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
        <path d="M5 22h14" />
        <path d="M5 2h14" />
        <path d="M17 22v-4.172a2 2 0 0 0-.586-1.414L12 12l-4.414 4.414A2 2 0 0 0 7 17.828V22" />
        <path d="M7 2v4.172a2 2 0 0 0 .586 1.414L12 12l4.414-4.414A2 2 0 0 0 17 6.172V2" />
    </svg>
);

// 🛑 Halted / Stop sign
export const IconStop = ({ size = 16, color = 'currentColor', className }: IconProps) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
        strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
        <path d="M5.8 2 2 5.8V18.2L5.8 22h12.4l3.8-3.8V5.8L18.2 2Z" />
        <path d="m15 9-6 6" />
        <path d="m9 9 6 6" />
    </svg>
);

// ⏸️ Cooldown / Pause
export const IconPause = ({ size = 16, color = 'currentColor', className }: IconProps) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
        strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
        <rect x="6" y="4" width="4" height="16" rx="1" />
        <rect x="14" y="4" width="4" height="16" rx="1" />
    </svg>
);

// 🔄 Bootstrap / Loading
export const IconRefresh = ({ size = 16, color = 'currentColor', className }: IconProps) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
        strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
        <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
        <path d="M3 3v5h5" />
        <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" />
        <path d="M16 16h5v5" />
    </svg>
);

// 📅 Calendar / Entry time
export const IconCalendar = ({ size = 16, color = 'currentColor', className }: IconProps) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
        strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
        <rect x="3" y="4" width="18" height="18" rx="2" />
        <path d="M16 2v4" />
        <path d="M8 2v4" />
        <path d="M3 10h18" />
    </svg>
);

// ⚡ Lightning / Fast execution
export const IconLightning = ({ size = 16, color = 'currentColor', className }: IconProps) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
        strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
        <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
    </svg>
);

// ▲ Arrow Up / Buy
export const IconArrowUp = ({ size = 16, color = 'currentColor', className }: IconProps) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
        strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
        <path d="m18 15-6-6-6 6" />
    </svg>
);

// ▼ Arrow Down / Sell
export const IconArrowDown = ({ size = 16, color = 'currentColor', className }: IconProps) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
        strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
        <path d="m6 9 6 6 6-6" />
    </svg>
);

// 🇻🇳 Vietnam Flag (simple representation)
export const IconVietnam = ({ size = 16, color: _color = 'currentColor', className }: IconProps) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
        <rect x="2" y="4" width="20" height="16" rx="2" fill="#DA251D" />
        <polygon points="12,6 13.5,10.5 18,10.5 14.5,13.5 16,18 12,15 8,18 9.5,13.5 6,10.5 10.5,10.5" fill="#FFFF00" />
    </svg>
);

// 🔔 Alert / Notification
export const IconBell = ({ size = 16, color = 'currentColor', className }: IconProps) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
        strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
        <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
        <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
    </svg>
);

// 💰 Wallet / Balance
export const IconWallet = ({ size = 16, color = 'currentColor', className }: IconProps) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
        strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
        <path d="M21 12V7H5a2 2 0 0 1 0-4h14v4" />
        <path d="M3 5v14a2 2 0 0 0 2 2h16v-5" />
        <path d="M18 12a2 2 0 0 0 0 4h4v-4Z" />
    </svg>
);

// ✓ Check / Success
export const IconCheck = ({ size = 16, color = 'currentColor', className }: IconProps) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
        strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
        <polyline points="20 6 9 17 4 12" />
    </svg>
);

// ✕ Close / Error
export const IconClose = ({ size = 16, color = 'currentColor', className }: IconProps) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
        strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
        <path d="M18 6 6 18" />
        <path d="m6 6 12 12" />
    </svg>
);

// 🎯 Target / Take Profit
export const IconTarget = ({ size = 16, color = 'currentColor', className }: IconProps) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
        strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
        <circle cx="12" cy="12" r="10" />
        <circle cx="12" cy="12" r="6" />
        <circle cx="12" cy="12" r="2" />
    </svg>
);

// 🛡️ Shield / Stop Loss
export const IconShield = ({ size = 16, color = 'currentColor', className }: IconProps) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
        strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    </svg>
);
