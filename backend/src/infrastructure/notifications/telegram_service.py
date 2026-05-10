"""
SOTA Institutional-Grade Telegram Notification Service (Async)

Pattern: Two Sigma, Citadel, Renaissance Technologies
- Comprehensive audit trail for all trading events
- Structured data for post-trade analysis
- Professional formatting without emojis
- Fire-and-forget architecture to avoid blocking trading loop

Features:
- Signal notifications with full context
- Position lifecycle tracking (entry, update, exit)
- Daily performance summaries
- System alerts and error reporting
- Structured JSON logging for audit
"""

import aiohttp
import asyncio
import logging
import json
from typing import Optional, Dict, List, Any
from datetime import datetime
from dataclasses import dataclass, asdict
from .trade_card_generator import trade_card_generator


@dataclass
class SignalContext:
    """Structured signal information for audit"""
    symbol: str
    side: str
    confidence: float
    entry_price: float
    stop_loss: float
    take_profit: float
    atr: float
    timestamp: str
    signal_id: str
    indicators: Dict[str, Any]

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class PositionContext:
    """Structured position information for audit"""
    symbol: str
    side: str
    entry_price: float
    filled_qty: float
    margin_used: float
    leverage: int
    stop_loss: float
    take_profit: float
    order_id: str
    signal_id: str
    timestamp: str

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ExitContext:
    """Structured exit information for comprehensive audit"""
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    filled_qty: float
    realized_pnl: float
    roe_percent: float
    fees_total: float
    fees_breakdown: Dict[str, float]
    reason: str
    duration_minutes: int
    order_ids: List[str]
    signal_id: str
    timestamp: str
    max_profit: float
    max_drawdown: float

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class DailySummary:
    """Structured daily performance summary"""
    date: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    total_pnl: float
    total_fees: float
    avg_trade_duration: float
    best_trade_pnl: float
    worst_trade_pnl: float
    portfolio_value: float
    drawdown_percent: float
    win_rate: float
    profit_factor: float

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class SystemAlert:
    """Structured system alert for debugging"""
    alert_type: str  # ERROR, WARNING, INFO, CRITICAL
    component: str
    message: str
    details: Dict[str, Any]
    timestamp: str
    traceback: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)


class TelegramService:
    """
    SOTA Institutional-Grade Telegram Notification Service

    Provides comprehensive audit trail and professional notifications
    for all trading activities. Designed for production environments
    with real money at stake.
    """

    def __init__(self, bot_token: str, chat_id: str, enabled: bool = True,
                 audit_log_path: Optional[str] = None):
        """
        Initialize Telegram Service

        Args:
            bot_token: Telegram bot token
            chat_id: Telegram chat ID
            enabled: Whether notifications are enabled
            audit_log_path: Path to JSON audit log file (optional)
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = enabled
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.logger = logging.getLogger("TelegramService")
        self.audit_log_path = audit_log_path or "logs/telegram_audit.json"

        # SOTA (Feb 2026): Shared aiohttp session (reuse connections, avoid socket leak)
        self._session: Optional[aiohttp.ClientSession] = None

        # Track notification statistics
        self._stats = {
            'sent': 0,
            'failed': 0,
            'last_sent': None
        }

        if not self.enabled:
            self.logger.info("[TELEGRAM] Notifications DISABLED")
            return

        if not bot_token or not chat_id:
            self.logger.warning("[TELEGRAM] Config Missing (Token/ChatID). Disabled.")
            self.enabled = False
        else:
            self.logger.info("[TELEGRAM] Notifications ENABLED")

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create shared aiohttp session (connection pooling)."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        """Close shared session on shutdown."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def send_message(self, message: str, silent: bool = False,
                          parse_mode: str = "HTML") -> bool:
        """
        Send async message to Telegram

        Args:
            message: Message text (HTML format)
            silent: Whether to send silently
            parse_mode: Parse mode (HTML, Markdown, MarkdownV2)

        Returns:
            True if sent successfully, False otherwise
        """
        if not self.enabled:
            return False

        # Telegram message limit is 4096 characters
        if len(message) > 4000:
            message = message[:3997] + "..."

        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": parse_mode,
            "disable_notification": silent,
            "disable_web_page_preview": True
        }

        try:
            session = await self._get_session()
            async with session.post(
                f"{self.base_url}/sendMessage",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    self._stats['sent'] += 1
                    self._stats['last_sent'] = datetime.now().isoformat()
                    return True
                else:
                    err_text = await response.text()
                    self.logger.error(f"[TELEGRAM] Send Failed: {response.status} - {err_text}")
                    self._stats['failed'] += 1
                    return False
        except Exception as e:
            self.logger.error(f"[TELEGRAM] Network Error: {e}")
            self._stats['failed'] += 1
            return False

    async def send_document(self, document_path: str, caption: str = "") -> bool:
        """
        Send document (CSV, JSON, etc.) to Telegram

        Args:
            document_path: Path to document
            caption: Document caption

        Returns:
            True if sent successfully
        """
        if not self.enabled:
            return False

        try:
            import os as _os
            filename = _os.path.basename(document_path)
            session = await self._get_session()
            with open(document_path, 'rb') as f:
                data = aiohttp.FormData()
                data.add_field('chat_id', self.chat_id)
                data.add_field('document', f, filename=filename)
                data.add_field('caption', caption[:1024])  # Telegram caption limit

                async with session.post(
                    f"{self.base_url}/sendDocument",
                    data=data,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        self._stats['sent'] += 1
                        return True
                    else:
                        err_text = await response.text()
                        self.logger.error(f"[TELEGRAM] Document Send Failed: {response.status}")
                        return False
        except FileNotFoundError:
            self.logger.error(f"[TELEGRAM] Document not found: {document_path}")
            return False
        except Exception as e:
            self.logger.error(f"[TELEGRAM] Document Error: {e}")
            return False

    async def send_photo(self, photo_path: str, caption: str = "") -> bool:
        """
        Send photo/image to Telegram (for charts, screenshots)

        SOTA (Feb 2026): For ProfitChartGenerator equity curves

        Args:
            photo_path: Absolute path to image file
            caption: Photo caption (HTML format, max 1024 chars)

        Returns:
            True if sent successfully
        """
        if not self.enabled:
            return False

        try:
            import os as _os
            session = await self._get_session()
            with open(photo_path, 'rb') as f:
                data = aiohttp.FormData()
                data.add_field('chat_id', self.chat_id)
                data.add_field('photo', f, filename=_os.path.basename(photo_path))
                data.add_field('caption', caption[:1024])  # Telegram caption limit
                data.add_field('parse_mode', 'HTML')

                async with session.post(
                    f"{self.base_url}/sendPhoto",
                    data=data,
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as response:
                    if response.status == 200:
                        self._stats['sent'] += 1
                        self._stats['last_sent'] = datetime.now().isoformat()
                        self.logger.info(f"[TELEGRAM] Photo sent: {photo_path}")
                        return True
                    else:
                        err_text = await response.text()
                        self.logger.error(f"[TELEGRAM] Photo Send Failed: {response.status} - {err_text}")
                        self._stats['failed'] += 1
                        return False
        except FileNotFoundError:
            self.logger.error(f"[TELEGRAM] Photo not found: {photo_path}")
            return False
        except Exception as e:
            self.logger.error(f"[TELEGRAM] Photo Error: {e}")
            self._stats['failed'] += 1
            return False

    async def send_photo_bytes(
        self,
        image_bytes: bytes,
        caption: str = "",
        filename: str = "trade_card.png",
        buttons: list = None
    ) -> bool:
        """
        SOTA (Feb 2026): Send photo from bytes (for generated trade cards)

        Args:
            image_bytes: PNG/JPG bytes
            caption: Photo caption (HTML format, max 1024 chars)
            filename: Filename to display
            buttons: Optional inline keyboard buttons

        Returns:
            True if sent successfully
        """
        if not self.enabled:
            return False

        try:
            session = await self._get_session()
            data = aiohttp.FormData()
            data.add_field('chat_id', self.chat_id)
            data.add_field('photo', image_bytes, filename=filename, content_type='image/png')
            data.add_field('caption', caption[:1024])
            data.add_field('parse_mode', 'HTML')

            # Add inline keyboard if provided
            if buttons:
                import json as json_module
                keyboard = {"inline_keyboard": buttons}
                data.add_field('reply_markup', json_module.dumps(keyboard))

            async with session.post(
                f"{self.base_url}/sendPhoto",
                data=data,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as response:
                if response.status == 200:
                    self._stats['sent'] += 1
                    self._stats['last_sent'] = datetime.now().isoformat()
                    self.logger.info(f"[TELEGRAM] Trade card sent: {filename}")
                    return True
                else:
                    err_text = await response.text()
                    self.logger.error(f"[TELEGRAM] Photo Bytes Send Failed: {response.status} - {err_text}")
                    self._stats['failed'] += 1
                    return False
        except Exception as e:
            self.logger.error(f"[TELEGRAM] Photo Bytes Error: {e}")
            self._stats['failed'] += 1
            return False

    async def send_message_with_buttons(
        self,
        text: str,
        buttons: list,
        silent: bool = False
    ) -> bool:
        """
        SOTA (Feb 2026): Send message with inline keyboard buttons

        Args:
            text: Message text (HTML format)
            buttons: List of button rows, each row is a list of button dicts
                     Example: [[{"text": "Close", "callback_data": "close_BTCUSDT"}]]
            silent: If true, send silently

        Returns:
            True if sent successfully
        """
        if not self.enabled:
            return False

        try:
            import json as json_module
            keyboard = {"inline_keyboard": buttons}

            # Truncate message if too long
            if len(text) > 4000:
                text = text[:3997] + "..."

            session = await self._get_session()
            async with session.post(
                f"{self.base_url}/sendMessage",
                json={
                    'chat_id': self.chat_id,
                    'text': text,
                    'parse_mode': 'HTML',
                    'disable_notification': silent,
                    'reply_markup': keyboard
                },
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    self._stats['sent'] += 1
                    self._stats['last_sent'] = datetime.now().isoformat()
                    return True
                else:
                    err_text = await response.text()
                    self.logger.error(f"[TELEGRAM] Button Message Failed: {response.status} - {err_text}")
                    self._stats['failed'] += 1
                    return False
        except Exception as e:
            self.logger.error(f"[TELEGRAM] Button Message Error: {e}")
            self._stats['failed'] += 1
            return False


    def _log_audit(self, event_type: str, data: Dict[str, Any]):
        """Log event to audit file with auto-rotation (max 5MB)."""
        try:
            import os as _os

            # Rotate if file exceeds 5MB
            MAX_SIZE = 5 * 1024 * 1024
            if _os.path.exists(self.audit_log_path):
                try:
                    if _os.path.getsize(self.audit_log_path) > MAX_SIZE:
                        rotated = f"{self.audit_log_path}.old"
                        if _os.path.exists(rotated):
                            _os.remove(rotated)
                        _os.rename(self.audit_log_path, rotated)
                except OSError:
                    pass

            audit_entry = {
                'timestamp': datetime.now().isoformat(),
                'event_type': event_type,
                'data': data
            }

            with open(self.audit_log_path, 'a') as f:
                f.write(json.dumps(audit_entry) + '\n')
        except Exception as e:
            self.logger.warning(f"[AUDIT] Failed to log: {e}")

    # =========================================================================
    # SIGNAL NOTIFICATIONS
    # =========================================================================

    async def notify_signal_generated(self, context: SignalContext) -> bool:
        """
        Notify when a new trading signal is generated

        Args:
            context: SignalContext with full signal details

        Returns:
            True if notification sent
        """
        # Log to audit
        self._log_audit('SIGNAL_GENERATED', context.to_dict())

        # Calculate risk/reward
        if context.side == 'LONG':
            risk = context.entry_price - context.stop_loss
            reward = context.take_profit - context.entry_price
        else:
            risk = context.stop_loss - context.entry_price
            reward = context.entry_price - context.take_profit

        rr_ratio = abs(reward / risk) if risk != 0 else 0

        msg = f"""<b>[SIGNAL] {context.symbol} {context.side}</b>

<b>Signal ID:</b> <code>{context.signal_id}</code>
<b>Timestamp:</b> {context.timestamp}
<b>Confidence:</b> {context.confidence:.1%}

<b>TRADE PARAMETERS</b>
<code>
Entry:   ${context.entry_price:,.4f}
Stop:    ${context.stop_loss:,.4f} ({(risk/context.entry_price)*100:+.2f}%)
Target:  ${context.take_profit:,.4f} ({(reward/context.entry_price)*100:+.2f}%)
R/R:     1:{rr_ratio:.2f}
ATR:     ${context.atr:,.4f} ({(context.atr/context.entry_price)*100:.2f}%)
</code>

<b>INDICATORS</b>
<code>{json.dumps(context.indicators, indent=2)}</code>
"""
        return await self.send_message(msg)

    # =========================================================================
    # POSITION NOTIFICATIONS
    # =========================================================================

    async def notify_position_opened(self, context: PositionContext) -> bool:
        """
        Notify when a position is successfully opened

        Args:
            context: PositionContext with position details

        Returns:
            True if notification sent
        """
        # SOTA FIX (Feb 2026): Validate all fields to prevent None formatting errors
        # None values cause TypeError: unsupported format string passed to NoneType.__format__
        symbol = context.symbol or 'UNKNOWN'
        side = context.side or 'UNKNOWN'
        entry_price = context.entry_price if context.entry_price is not None else 0.0
        filled_qty = context.filled_qty if context.filled_qty is not None else 0.0
        margin_used = context.margin_used if context.margin_used is not None else 0.0
        leverage = context.leverage if context.leverage is not None else 1
        stop_loss = context.stop_loss if context.stop_loss is not None else 0.0
        take_profit = context.take_profit if context.take_profit is not None else 0.0
        order_id = context.order_id or 'N/A'
        signal_id = context.signal_id or 'N/A'
        timestamp = context.timestamp or 'N/A'

        # Log to audit
        self._log_audit('POSITION_OPENED', context.to_dict())

        # Calculate risk amount (with safe division)
        notional = filled_qty * entry_price
        if entry_price > 0:
            risk_amount = notional * (abs(entry_price - stop_loss) / entry_price)
        else:
            risk_amount = 0.0

        # Determine side emoji and color indicator
        side_emoji = "🟢" if side == "LONG" else "🔴"

        # Calculate percentages for SL/TP display
        sl_pct = ((stop_loss - entry_price) / entry_price * 100) if entry_price > 0 and stop_loss > 0 else 0
        tp_pct = ((take_profit - entry_price) / entry_price * 100) if entry_price > 0 and take_profit > 0 else 0

        msg = f"""{side_emoji} <b>ENTRY</b> │ {symbol} <b>{side}</b>
━━━━━━━━━━━━━━━━━━━━━━

📋 <b>ORDER INFO</b>
├─ ID: <code>{order_id}</code>
├─ Signal: <code>{signal_id}</code>
└─ Time: {timestamp}

📊 <b>FILL DETAILS</b>
├─ Price:   <code>${entry_price:,.4f}</code>
├─ Qty:     <code>{filled_qty:.6f}</code>
└─ Value:   <code>${notional:,.2f}</code>

🛡️ <b>RISK MANAGEMENT</b>
├─ Margin:  <code>${margin_used:,.2f}</code>
├─ Lever:   <code>{leverage}×</code>
├─ Stop:    <code>${stop_loss:,.4f}</code> ({sl_pct:+.2f}%)
├─ Target:  <code>${take_profit:,.4f}</code> ({tp_pct:+.2f}%)
└─ Risk:    <code>${risk_amount:,.2f}</code>
"""
        # SOTA (Feb 2026): Add inline buttons for quick actions
        # TradingView chart link for the symbol
        chart_symbol = symbol.replace('USDT', 'USDT.P')  # Binance Perp format
        tradingview_url = f"https://www.tradingview.com/chart/?symbol=BINANCE:{chart_symbol}"
        binance_url = f"https://www.binance.com/en/futures/{symbol}"

        buttons = [
            [
                {"text": "📊 TradingView", "url": tradingview_url},
                {"text": "💹 Binance", "url": binance_url}
            ]
        ]

        # SOTA (Feb 2026): Try to generate trade card image (Option B)
        try:
            image_bytes = trade_card_generator.generate_entry_card(
                symbol=symbol,
                side=side,
                entry_price=entry_price,
                quantity=filled_qty,
                leverage=leverage,
                stop_loss=stop_loss,
                take_profit=take_profit,
                margin=margin_used,
                timestamp=timestamp
            )

            # Send image with short caption (Option B)
            # Use same SOTA message format as fallback, but simpler is better for caption
            # Caption limit is 1024 chars, so full message fits
            sent = await self.send_photo_bytes(image_bytes, caption=msg, filename=f"entry_{symbol}.png", buttons=buttons)
            if sent:
                return True

        except Exception as e:
            self.logger.warning(f"⚠️ Failed to generate/send entry card: {e}. Falling back to text.")

        # Fallback to text + buttons (Option A + C)
        return await self.send_message_with_buttons(msg, buttons)

    async def notify_position_update(
        self,
        symbol: str,
        side: str,
        current_price: float,
        entry_price: float,
        unrealized_pnl: float,
        roe_percent: float,
        max_profit: float,
        max_drawdown: float,
        duration_minutes: int,
        timestamp: str
    ) -> bool:
        """
        Notify position update (significant PnL changes)

        Args:
            symbol: Trading pair
            side: LONG or SHORT
            current_price: Current market price
            entry_price: Entry price
            unrealized_pnl: Unrealized PnL
            roe_percent: ROE percentage
            max_profit: Maximum profit reached
            max_drawdown: Maximum drawdown
            duration_minutes: Position duration
            timestamp: Update timestamp

        Returns:
            True if notification sent
        """
        price_change = ((current_price - entry_price) / entry_price) * 100
        if side == 'SHORT':
            price_change = -price_change

        pnl_emoji = "+" if unrealized_pnl >= 0 else ""

        msg = f"""<b>[UPDATE] {symbol} {side}</b>

<b>Duration:</b> {duration_minutes}m | <b>Time:</b> {timestamp}

<b>PRICE</b>
<code>
Current: ${current_price:,.4f} ({price_change:+.2f}%)
Entry:   ${entry_price:,.4f}
</code>

<b>PERFORMANCE</b>
<code>
PnL:     {pnl_emoji}${unrealized_pnl:,.2f}
ROE:     {roe_percent:+.2f}%
Max P:   ${max_profit:,.2f}
Max DD:  ${max_drawdown:,.2f}
</code>
"""
        return await self.send_message(msg, silent=True)  # Silent for updates

    async def notify_position_closed(self, context: ExitContext) -> bool:
        """
        Comprehensive position exit notification with full audit trail

        Args:
            context: ExitContext with complete exit details

        Returns:
            True if notification sent
        """
        # Log to audit
        self._log_audit('POSITION_CLOSED', context.to_dict())

        # SOTA (Feb 2026): Determine status emoji and indicator
        if context.realized_pnl > 0:
            status_emoji = "💰"
            status = "WIN"
        elif context.realized_pnl < 0:
            status_emoji = "💔"
            status = "LOSS"
        else:
            status_emoji = "⚖️"
            status = "BREAKEVEN"

        side_emoji = "🟢" if context.side == "LONG" else "🔴"

        # Format fees breakdown with box drawing
        fees_list = [f"├─ {k}: <code>${v:.4f}</code>" for k, v in list(context.fees_breakdown.items())[:-1]]
        if context.fees_breakdown:
            last_key = list(context.fees_breakdown.keys())[-1]
            last_val = context.fees_breakdown[last_key]
            fees_list.append(f"└─ {last_key}: <code>${last_val:.4f}</code>")
        fees_str = "\n".join(fees_list) if fees_list else "└─ None"

        # Format order IDs with box drawing
        orders_list = [f"├─ <code>{oid}</code>" for oid in context.order_ids[:-1]] if len(context.order_ids) > 1 else []
        if context.order_ids:
            orders_list.append(f"└─ <code>{context.order_ids[-1]}</code>")
        orders_str = "\n".join(orders_list) if orders_list else "└─ None"

        # Calculate price move percentage
        price_move_pct = ((context.exit_price - context.entry_price) / context.entry_price * 100) if context.entry_price > 0 else 0

        pnl_sign = "+" if context.realized_pnl >= 0 else ""
        gross_pnl = context.realized_pnl + context.fees_total
        gross_sign = "+" if gross_pnl >= 0 else ""

        msg = f"""{status_emoji} <b>CLOSED</b> │ {context.symbol} {side_emoji} {context.side} │ <b>{status}</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 <b>EXIT INFO</b>
├─ Reason: <code>{context.reason}</code>
├─ Duration: <code>{context.duration_minutes}m</code>
└─ Time: {context.timestamp}

📊 <b>TRADE DETAILS</b>
├─ Entry:  <code>${context.entry_price:,.4f}</code>
├─ Exit:   <code>${context.exit_price:,.4f}</code> ({price_move_pct:+.2f}%)
└─ Qty:    <code>{context.filled_qty:.6f}</code>

💵 <b>P&L SUMMARY</b>
├─ Gross:  <code>{gross_sign}${gross_pnl:,.2f}</code>
├─ Fees:   <code>−${context.fees_total:.4f}</code>
├─ Net:    <code>{pnl_sign}${context.realized_pnl:,.2f}</code>
└─ ROE:    <code>{context.roe_percent:+.2f}%</code>

🧾 <b>FEES</b>
{fees_str}

📈 <b>EXTREMES</b>
├─ Max ↑: <code>${context.max_profit:,.2f}</code>
└─ Max ↓: <code>${context.max_drawdown:,.2f}</code>

🆔 <b>ORDER IDs</b>
{orders_str}
"""
        # SOTA (Feb 2026): Try to generate trade card image (Option B)
        try:
            image_bytes = trade_card_generator.generate_exit_card(
                symbol=context.symbol,
                side=context.side,
                entry_price=context.entry_price,
                exit_price=context.exit_price,
                quantity=context.filled_qty,
                realized_pnl=context.realized_pnl,
                roe_percent=context.roe_percent,
                fees=context.fees_total,
                reason=context.reason,
                duration_minutes=context.duration_minutes,
                timestamp=context.timestamp
            )

            # Send image with short caption (Option B)
            sent = await self.send_photo_bytes(image_bytes, caption=msg, filename=f"exit_{context.symbol}.png")
            if sent:
                return True

        except Exception as e:
            self.logger.warning(f"⚠️ Failed to generate/send exit card: {e}. Falling back to text.")

        return await self.send_message(msg)

    # =========================================================================
    # DAILY SUMMARY
    # =========================================================================

    async def notify_daily_summary(self, summary: DailySummary) -> bool:
        """
        Daily performance summary notification

        Args:
            summary: DailySummary with day's performance

        Returns:
            True if notification sent
        """
        # Log to audit
        self._log_audit('DAILY_SUMMARY', summary.to_dict())

        net_pnl = summary.total_pnl - summary.total_fees

        # SOTA (Feb 2026): Determine overall day status
        if net_pnl > 0:
            day_emoji = "📈"
            day_status = "PROFITABLE"
        elif net_pnl < 0:
            day_emoji = "📉"
            day_status = "LOSS"
        else:
            day_emoji = "⚖️"
            day_status = "BREAKEVEN"

        pnl_sign = "+" if net_pnl >= 0 else ""
        gross_sign = "+" if summary.total_pnl >= 0 else ""

        # Calculate win rate
        win_rate = (summary.winning_trades / summary.total_trades * 100) if summary.total_trades > 0 else 0

        msg = f"""{day_emoji} <b>DAILY REPORT</b> │ {summary.date} │ <b>{day_status}</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 <b>TRADE STATISTICS</b>
├─ Total:     <code>{summary.total_trades}</code>
├─ Winners:   <code>{summary.winning_trades}</code> 🟢
├─ Losers:    <code>{summary.losing_trades}</code> 🔴
├─ Win Rate:  <code>{win_rate:.1f}%</code>
└─ Avg Dur:   <code>{summary.avg_trade_duration:.1f}m</code>

💵 <b>FINANCIAL PERFORMANCE</b>
├─ Gross:     <code>{gross_sign}${summary.total_pnl:,.2f}</code>
├─ Fees:      <code>−${summary.total_fees:,.2f}</code>
├─ Net:       <code>{pnl_sign}${net_pnl:,.2f}</code>
├─ Portfolio: <code>${summary.portfolio_value:,.2f}</code>
├─ Drawdown:  <code>{summary.drawdown_percent:.2f}%</code>
└─ P.Factor:  <code>{summary.profit_factor:.2f}</code>

🏆 <b>BEST / WORST</b>
├─ Best:  <code>+${summary.best_trade_pnl:,.2f}</code> 🟢
└─ Worst: <code>${summary.worst_trade_pnl:,.2f}</code> 🔴
"""
        return await self.send_message(msg)

    # =========================================================================
    # SYSTEM ALERTS
    # =========================================================================

    async def notify_system_alert(self, alert: SystemAlert) -> bool:
        """
        System alert notification for errors and warnings

        Args:
            alert: SystemAlert with alert details

        Returns:
            True if notification sent
        """
        # Log to audit
        self._log_audit(f'SYSTEM_ALERT_{alert.alert_type}', alert.to_dict())

        # Format details
        details_str = "\n".join([f"  {k}: {v}" for k, v in alert.details.items()])

        # Determine priority indicator
        priority = {
            'CRITICAL': '[CRITICAL]',
            'ERROR': '[ERROR]',
            'WARNING': '[WARNING]',
            'INFO': '[INFO]'
        }.get(alert.alert_type, '[ALERT]')

        msg = f"""<b>{priority} {alert.component}</b>

<b>Time:</b> {alert.timestamp}
<b>Type:</b> {alert.alert_type}

<b>MESSAGE</b>
<code>{alert.message}</code>

<b>CONTEXT</b>
<code>{details_str}</code>
"""
        if alert.traceback:
            msg += f"""
<b>TRACEBACK</b>
<pre>{alert.traceback[:1000]}</pre>
"""

        # Critical and Error alerts are not silent
        silent = alert.alert_type not in ['CRITICAL', 'ERROR']
        return await self.send_message(msg, silent=silent)

    # =========================================================================
    # UTILITY METHODS
    # =========================================================================

    def get_stats(self) -> Dict[str, Any]:
        """Get notification statistics"""
        return self._stats.copy()

    async def send_test_message(self) -> bool:
        """Send test message to verify configuration"""
        msg = f"""<b>[TEST] Telegram Service</b>

Status: OPERATIONAL
Time: {datetime.now().isoformat()}
Audit Log: {self.audit_log_path}

This is a test message to verify Telegram configuration.
"""
        return await self.send_message(msg)
