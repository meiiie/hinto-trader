import { THEME } from '../styles/theme';
import {
    IconRefresh,
    IconScan,
    IconHourglass,
    IconTrendingUp,
    IconPause,
    IconStop
} from '../assets/icons';

/**
 * Trading State definitions from backend TradingStateMachine
 */
export type TradingState = 'BOOTSTRAP' | 'SCANNING' | 'ENTRY_PENDING' | 'IN_POSITION' | 'COOLDOWN' | 'HALTED';

interface StateIndicatorProps {
    state: TradingState;
    cooldownRemaining?: number;
    orderId?: string | null;
    positionId?: string | null;
    reason?: string;
}

/**
 * State configuration with colors and SVG icons
 */
const STATE_CONFIG: Record<TradingState, {
    color: string;
    bgColor: string;
    Icon: React.FC<{ size?: number; color?: string }>;
    label: string;
    description: string
}> = {
    BOOTSTRAP: {
        color: THEME.text.tertiary,
        bgColor: 'rgba(133, 133, 133, 0.15)',
        Icon: IconRefresh,
        label: 'Khởi động',
        description: 'Đang tải dữ liệu lịch sử...'
    },
    SCANNING: {
        color: THEME.status.buy,
        bgColor: 'rgba(46, 189, 133, 0.15)',
        Icon: IconScan,
        label: 'Quét tín hiệu',
        description: 'Sẵn sàng bắt tín hiệu'
    },
    ENTRY_PENDING: {
        color: THEME.accent.yellow,
        bgColor: 'rgba(240, 185, 11, 0.15)',
        Icon: IconHourglass,
        label: 'Chờ khớp lệnh',
        description: 'Đang chờ giá entry'
    },
    IN_POSITION: {
        color: '#2196F3',
        bgColor: 'rgba(33, 150, 243, 0.15)',
        Icon: IconTrendingUp,
        label: 'Đang giao dịch',
        description: 'Có vị thế đang mở'
    },
    COOLDOWN: {
        color: '#FF9800',
        bgColor: 'rgba(255, 152, 0, 0.15)',
        Icon: IconPause,
        label: 'Nghỉ ngơi',
        description: 'Đợi 4 nến trước khi tiếp tục'
    },
    HALTED: {
        color: THEME.status.sell,
        bgColor: 'rgba(246, 70, 93, 0.15)',
        Icon: IconStop,
        label: 'Dừng khẩn cấp',
        description: 'Hệ thống tạm dừng do lỗi'
    }
};

/**
 * StateIndicator Component - Displays current trading state machine status
 *
 * SOTA Pattern: Uses professional SVG icons instead of emojis
 *
 * Usage:
 * <StateIndicator
 *   state="SCANNING"
 *   cooldownRemaining={3}
 *   orderId="abc-123"
 * />
 */
export default function StateIndicator({
    state,
    cooldownRemaining,
    orderId,
    positionId,
    reason
}: StateIndicatorProps) {
    const config = STATE_CONFIG[state];
    const { Icon } = config;

    return (
        <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            padding: '6px 12px',
            borderRadius: '8px',
            backgroundColor: config.bgColor,
            border: `1px solid ${config.color}40`,
            minWidth: '140px', // SOTA: Prevent layout shift
            whiteSpace: 'nowrap', // SOTA: Keep label on one line
        }}>
            {/* SVG Icon */}
            <Icon size={16} color={config.color} />

            {/* State Info */}
            <div style={{ flex: 1 }}>
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                }}>
                    <span style={{
                        fontSize: '13px',
                        fontWeight: 700,
                        color: config.color,
                        textTransform: 'uppercase',
                        letterSpacing: '0.05em',
                    }}>
                        {config.label}
                    </span>

                    {/* Cooldown countdown */}
                    {state === 'COOLDOWN' && cooldownRemaining !== undefined && (
                        <span style={{
                            fontSize: '11px',
                            padding: '1px 6px',
                            borderRadius: '4px',
                            backgroundColor: config.color,
                            color: '#000',
                            fontWeight: 600,
                        }}>
                            {cooldownRemaining} nến
                        </span>
                    )}

                    {/* Pending order indicator */}
                    {state === 'ENTRY_PENDING' && orderId && (
                        <span style={{
                            fontSize: '10px',
                            padding: '1px 6px',
                            borderRadius: '4px',
                            backgroundColor: THEME.bg.vessel,
                            color: THEME.text.tertiary,
                            fontFamily: 'monospace',
                        }}>
                            Order: {orderId.substring(0, 8)}...
                        </span>
                    )}

                    {/* Active position indicator */}
                    {state === 'IN_POSITION' && positionId && (
                        <span style={{
                            fontSize: '10px',
                            padding: '1px 6px',
                            borderRadius: '4px',
                            backgroundColor: THEME.bg.vessel,
                            color: THEME.text.tertiary,
                            fontFamily: 'monospace',
                        }}>
                            Pos: {positionId.substring(0, 8)}...
                        </span>
                    )}
                </div>

                {/* Description */}
                <div style={{
                    fontSize: '11px',
                    color: THEME.text.tertiary,
                    marginTop: '2px',
                }}>
                    {reason || config.description}
                </div>
            </div>

            {/* Status dot */}
            <span style={{
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                backgroundColor: config.color,
                boxShadow: `0 0 8px ${config.color}`,
                animation: state === 'SCANNING' ? 'pulse 2s infinite' : 'none',
            }} />
        </div>
    );
}
