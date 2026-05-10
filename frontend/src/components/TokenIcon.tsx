/**
 * TokenIcon Component - Crypto Token Icons
 *
 * SOTA Pattern: Wrapper around @web3icons/react with dynamic import
 *
 * Usage:
 * <TokenIcon symbol="BTC" size={24} />
 * <TokenIcon symbol="ETH" size={20} />
 */

// Import specific token icons directly
import { TokenBTC, TokenETH, TokenUSDT, TokenBNB, TokenSOL } from '@web3icons/react';

interface TokenIconProps {
    symbol: string;
    size?: number;
    className?: string;
}

// Map symbol to icon component
const TOKEN_ICONS: Record<string, React.ComponentType<{ size?: number; className?: string }>> = {
    BTC: TokenBTC,
    ETH: TokenETH,
    USDT: TokenUSDT,
    BNB: TokenBNB,
    SOL: TokenSOL,
};

/**
 * Render crypto token icon
 *
 * Supports major tokens: BTC, ETH, USDT, BNB, SOL
 * Falls back to text if icon not found
 */
export const TokenIcon = ({ symbol, size = 24, className }: TokenIconProps) => {
    const upperSymbol = symbol.toUpperCase();
    const IconComponent = TOKEN_ICONS[upperSymbol];

    if (IconComponent) {
        return <IconComponent size={size} className={className} />;
    }

    // Fallback: colored circle with first letter
    return (
        <div
            style={{
                width: size,
                height: size,
                borderRadius: '50%',
                backgroundColor: '#F0B90B',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: size * 0.5,
                fontWeight: 700,
                color: '#000',
            }}
            className={className}
        >
            {upperSymbol[0]}
        </div>
    );
};

export default TokenIcon;
