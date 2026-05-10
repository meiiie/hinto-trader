"""
SOTA Trade Card Image Generator (Feb 2026)

Pattern: Professional trading platforms (TradingView, Binance)
- Generate beautiful trade cards for Telegram sharing
- Mini chart visualization with entry/SL/TP markers
- Dark theme with gradient backgrounds
- Designed for social media sharing

Dependencies:
- Pillow (PIL) for image generation
- Optional: matplotlib for mini charts
"""

from PIL import Image, ImageDraw, ImageFont
from typing import Optional, Dict, Any
from io import BytesIO
import os
import logging

logger = logging.getLogger(__name__)

# Colors (Dark Theme)
COLORS = {
    'background': '#0d1117',
    'card_bg': '#161b22',
    'header_long': '#238636',
    'header_short': '#da3633',
    'header_win': '#238636',
    'header_loss': '#da3633',
    'text_primary': '#f0f6fc',
    'text_secondary': '#8b949e',
    'text_muted': '#6e7681',
    'border': '#30363d',
    'accent_green': '#3fb950',
    'accent_red': '#f85149',
    'accent_blue': '#58a6ff',
}


class TradeCardGenerator:
    """Generate beautiful trade card images for Telegram."""

    def __init__(self):
        self.width = 800
        self.height = 500
        self._load_fonts()

    def _load_fonts(self):
        """Load fonts with fallback to default."""
        try:
            # Try to load Inter font (modern, clean)
            font_path = os.path.join(os.path.dirname(__file__), 'fonts', 'Inter-Regular.ttf')
            font_bold_path = os.path.join(os.path.dirname(__file__), 'fonts', 'Inter-Bold.ttf')

            if os.path.exists(font_path):
                self.font_regular = ImageFont.truetype(font_path, 18)
                self.font_large = ImageFont.truetype(font_path, 28)
                self.font_small = ImageFont.truetype(font_path, 14)
            else:
                # Fallback to system fonts
                self.font_regular = ImageFont.load_default()
                self.font_large = ImageFont.load_default()
                self.font_small = ImageFont.load_default()

            if os.path.exists(font_bold_path):
                self.font_bold = ImageFont.truetype(font_bold_path, 24)
                self.font_title = ImageFont.truetype(font_bold_path, 32)
            else:
                self.font_bold = self.font_large
                self.font_title = self.font_large

        except Exception as e:
            logger.warning(f"Font loading failed, using defaults: {e}")
            self.font_regular = ImageFont.load_default()
            self.font_large = ImageFont.load_default()
            self.font_small = ImageFont.load_default()
            self.font_bold = ImageFont.load_default()
            self.font_title = ImageFont.load_default()

    def generate_entry_card(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        quantity: float,
        leverage: int,
        stop_loss: float,
        take_profit: float,
        margin: float,
        timestamp: str
    ) -> bytes:
        """Generate entry trade card image."""

        # Create image
        img = Image.new('RGB', (self.width, self.height), COLORS['background'])
        draw = ImageDraw.Draw(img)

        # Header bar
        header_color = COLORS['header_long'] if side == 'LONG' else COLORS['header_short']
        draw.rectangle([0, 0, self.width, 70], fill=header_color)

        # Title
        side_emoji = "🟢" if side == "LONG" else "🔴"
        title = f"{side_emoji} ENTRY | {symbol} {side}"
        draw.text((30, 20), title, font=self.font_title, fill=COLORS['text_primary'])

        # Main content area
        y = 100

        # Section: Fill Details
        draw.text((30, y), "📊 FILL DETAILS", font=self.font_bold, fill=COLORS['accent_blue'])
        y += 40

        notional = entry_price * quantity
        details = [
            (f"Price:", f"${entry_price:,.4f}"),
            (f"Quantity:", f"{quantity:.6f}"),
            (f"Notional:", f"${notional:,.2f}"),
        ]

        for label, value in details:
            draw.text((50, y), label, font=self.font_regular, fill=COLORS['text_secondary'])
            draw.text((200, y), value, font=self.font_regular, fill=COLORS['text_primary'])
            y += 30

        y += 20

        # Section: Risk Management
        draw.text((30, y), "🛡️ RISK MANAGEMENT", font=self.font_bold, fill=COLORS['accent_blue'])
        y += 40

        sl_pct = ((stop_loss - entry_price) / entry_price * 100) if entry_price > 0 else 0
        tp_pct = ((take_profit - entry_price) / entry_price * 100) if entry_price > 0 else 0

        risk_details = [
            (f"Margin:", f"${margin:,.2f}"),
            (f"Leverage:", f"{leverage}×"),
            (f"Stop Loss:", f"${stop_loss:,.4f} ({sl_pct:+.2f}%)"),
            (f"Take Profit:", f"${take_profit:,.4f} ({tp_pct:+.2f}%)"),
        ]

        for label, value in risk_details:
            draw.text((50, y), label, font=self.font_regular, fill=COLORS['text_secondary'])
            draw.text((200, y), value, font=self.font_regular, fill=COLORS['text_primary'])
            y += 30

        # Footer with timestamp
        draw.rectangle([0, self.height - 40, self.width, self.height], fill=COLORS['card_bg'])
        draw.text((30, self.height - 30), f"⏰ {timestamp}", font=self.font_small, fill=COLORS['text_muted'])
        draw.text((self.width - 200, self.height - 30), "Hinto", font=self.font_small, fill=COLORS['text_muted'])

        # Convert to bytes
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        return buffer.getvalue()

    def generate_exit_card(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float,
        quantity: float,
        realized_pnl: float,
        roe_percent: float,
        fees: float,
        reason: str,
        duration_minutes: int,
        timestamp: str
    ) -> bytes:
        """Generate exit trade card image."""

        # Create image
        img = Image.new('RGB', (self.width, self.height), COLORS['background'])
        draw = ImageDraw.Draw(img)

        # Header bar (color based on PnL)
        header_color = COLORS['header_win'] if realized_pnl >= 0 else COLORS['header_loss']
        draw.rectangle([0, 0, self.width, 70], fill=header_color)

        # Title
        status = "WIN" if realized_pnl > 0 else "LOSS" if realized_pnl < 0 else "BE"
        status_emoji = "💰" if realized_pnl > 0 else "💔" if realized_pnl < 0 else "⚖️"
        side_emoji = "🟢" if side == "LONG" else "🔴"
        title = f"{status_emoji} CLOSED | {symbol} {side_emoji} | {status}"
        draw.text((30, 20), title, font=self.font_title, fill=COLORS['text_primary'])

        # Main content
        y = 100

        # Trade Details
        draw.text((30, y), "📊 TRADE DETAILS", font=self.font_bold, fill=COLORS['accent_blue'])
        y += 40

        price_move_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price > 0 else 0

        details = [
            (f"Entry:", f"${entry_price:,.4f}"),
            (f"Exit:", f"${exit_price:,.4f} ({price_move_pct:+.2f}%)"),
            (f"Quantity:", f"{quantity:.6f}"),
            (f"Duration:", f"{duration_minutes}m"),
        ]

        for label, value in details:
            draw.text((50, y), label, font=self.font_regular, fill=COLORS['text_secondary'])
            draw.text((200, y), value, font=self.font_regular, fill=COLORS['text_primary'])
            y += 30

        y += 20

        # P&L Summary
        draw.text((30, y), "💵 P&L SUMMARY", font=self.font_bold, fill=COLORS['accent_blue'])
        y += 40

        pnl_color = COLORS['accent_green'] if realized_pnl >= 0 else COLORS['accent_red']
        gross_pnl = realized_pnl + fees

        pnl_details = [
            (f"Gross:", f"${gross_pnl:+,.2f}"),
            (f"Fees:", f"-${fees:.4f}"),
            (f"Net:", f"${realized_pnl:+,.2f}"),
            (f"ROE:", f"{roe_percent:+.2f}%"),
        ]

        for i, (label, value) in enumerate(pnl_details):
            draw.text((50, y), label, font=self.font_regular, fill=COLORS['text_secondary'])
            color = pnl_color if i >= 2 else COLORS['text_primary']  # Highlight Net and ROE
            draw.text((200, y), value, font=self.font_regular, fill=color)
            y += 30

        # Large PnL display (right side)
        pnl_text = f"${realized_pnl:+,.2f}"
        roe_text = f"{roe_percent:+.2f}%"
        draw.text((500, 150), pnl_text, font=self.font_title, fill=pnl_color)
        draw.text((500, 200), roe_text, font=self.font_bold, fill=pnl_color)

        # Reason badge
        draw.rectangle([500, 260, 700, 295], fill=COLORS['card_bg'], outline=COLORS['border'])
        draw.text((520, 267), reason, font=self.font_small, fill=COLORS['text_secondary'])

        # Footer
        draw.rectangle([0, self.height - 40, self.width, self.height], fill=COLORS['card_bg'])
        draw.text((30, self.height - 30), f"⏰ {timestamp}", font=self.font_small, fill=COLORS['text_muted'])
        draw.text((self.width - 200, self.height - 30), "Hinto", font=self.font_small, fill=COLORS['text_muted'])

        # Convert to bytes
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        return buffer.getvalue()


# Global instance
trade_card_generator = TradeCardGenerator()
