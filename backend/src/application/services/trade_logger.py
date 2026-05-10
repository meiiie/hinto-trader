"""
TradeLogger - SOTA Trade Logging Service

Ghi log chi tiết về trading events vào file Markdown.
Giúp debug và theo dõi luồng xử lý TP/SL.

Features:
- Log position opens, closes, TP hits, SL hits
- Log price updates every 10 seconds per symbol
- Markdown format for human readability
- Immediate flush (no buffering)
- Daily rotation

Output: documents/trading-logs/trading_YYYYMMDD.md
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, TextIO
from dataclasses import dataclass, field
from pathlib import Path
import threading

logger = logging.getLogger(__name__)


@dataclass
class TradeLogEntry:
    """Single log entry for trade events."""
    timestamp: datetime
    event_type: str  # 'OPEN', 'PRICE_UPDATE', 'TP_HIT', 'SL_HIT', 'CLOSE', 'EVENT'
    symbol: str
    side: str
    position_id: str
    data: Dict[str, Any] = field(default_factory=dict)

    def to_markdown(self) -> str:
        """Convert to Markdown format."""
        ts = self.timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]  # ISO with milliseconds

        lines = [
            f"### [{ts}] {self.event_type}",
            f"**Symbol:** {self.symbol} | **Side:** {self.side} | **ID:** {self.position_id[:8] if self.position_id else 'N/A'}",
            ""
        ]

        for key, value in self.data.items():
            if isinstance(value, float):
                if 'pct' in key.lower() or 'percent' in key.lower():
                    lines.append(f"- **{key}:** {value:.2f}%")
                elif value > 1000:
                    lines.append(f"- **{key}:** ${value:,.2f}")
                else:
                    lines.append(f"- **{key}:** ${value:.6f}")
            elif isinstance(value, int):
                lines.append(f"- **{key}:** {value}")
            elif isinstance(value, datetime):
                lines.append(f"- **{key}:** {value.isoformat()}")
            else:
                lines.append(f"- **{key}:** {value}")

        lines.append("")
        lines.append("---")
        lines.append("")
        return "\n".join(lines)


class TradeLogger:
    """
    SOTA Trade Logging Service - Detailed Markdown logs for debugging.

    Writes to: documents/trading-logs/trading_YYYYMMDD.md
    Format: Human-readable Markdown with timestamps

    Thread-safe with lock for concurrent writes.
    """

    PRICE_UPDATE_INTERVAL = 10.0  # Log price updates every 10 seconds per symbol

    def __init__(self, log_dir: str = "documents/trading-logs"):
        """
        Initialize TradeLogger.

        Args:
            log_dir: Directory for log files (relative to project root)
        """
        self.log_dir = Path(log_dir)
        self._current_file: Optional[TextIO] = None
        self._current_date: Optional[str] = None
        self._last_price_log: Dict[str, float] = {}  # symbol -> timestamp
        self._lock = threading.Lock()
        self._max_log_age_days = 7  # MEMORY FIX (Feb 8, 2026): Auto-delete logs older than 7 days

        # Ensure log directory exists
        self._ensure_log_dir()

        # MEMORY FIX (Feb 8, 2026): Clean up old log files on startup
        self._cleanup_old_logs()

        logger.info(f"📝 TradeLogger initialized: {self.log_dir}")

    def _ensure_log_dir(self):
        """Create log directory if it doesn't exist."""
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to create log directory: {e}")

    def _cleanup_old_logs(self):
        """MEMORY FIX (Feb 8, 2026): Delete log files older than _max_log_age_days."""
        try:
            cutoff = datetime.now() - timedelta(days=self._max_log_age_days)
            removed = 0
            for log_file in self.log_dir.glob("trading_*.md"):
                try:
                    # Parse date from filename: trading_YYYYMMDD.md
                    date_str = log_file.stem.replace("trading_", "")
                    file_date = datetime.strptime(date_str, "%Y%m%d")
                    if file_date < cutoff:
                        log_file.unlink()
                        removed += 1
                except (ValueError, OSError):
                    continue
            if removed:
                logger.info(f"🧹 Cleaned up {removed} old log file(s) (>{self._max_log_age_days} days)")
        except Exception as e:
            logger.warning(f"Log cleanup failed (non-critical): {e}")

    def _get_log_file(self) -> Optional[TextIO]:
        """Get current log file, rotating daily."""
        today = datetime.now().strftime("%Y%m%d")

        if self._current_date != today:
            # Close old file
            if self._current_file:
                try:
                    self._current_file.close()
                except:
                    pass

            # Open new file
            log_path = self.log_dir / f"trading_{today}.md"
            try:
                # Append mode, create if not exists
                self._current_file = open(log_path, 'a', encoding='utf-8')
                self._current_date = today

                # Write header if new file
                if log_path.stat().st_size == 0:
                    self._write_header()

            except Exception as e:
                logger.error(f"Failed to open log file: {e}")
                return None

        return self._current_file

    def _write_header(self):
        """Write header to new log file."""
        if not self._current_file:
            return

        header = f"""# Trading Log - {datetime.now().strftime("%Y-%m-%d")}

Generated by TradeLogger - SOTA Trade Logging Service

---

"""
        self._current_file.write(header)
        self._current_file.flush()

    def _write_entry(self, entry: TradeLogEntry):
        """Write entry to log file with immediate flush."""
        with self._lock:
            file = self._get_log_file()
            if file:
                try:
                    file.write(entry.to_markdown())
                    file.flush()  # Immediate flush - no buffering
                except Exception as e:
                    logger.error(f"Failed to write log entry: {e}")

    def log_event(self, message: str, symbol: str = "SYSTEM", side: str = "-"):
        """
        Log a generic event message.

        Args:
            message: Event message
            symbol: Trading symbol (default: SYSTEM)
            side: Position side (default: -)
        """
        entry = TradeLogEntry(
            timestamp=datetime.now(),
            event_type="EVENT",
            symbol=symbol,
            side=side,
            position_id="",
            data={"message": message}
        )
        self._write_entry(entry)
        logger.debug(f"📝 LOG: {message}")

    def log_position_opened(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        quantity: float,
        stop_loss: float,
        take_profit: float,
        leverage: int,
        position_id: str,
        margin: float = 0.0,
        atr: float = 0.0
    ) -> None:
        """
        Log position entry with all details.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            side: 'LONG' or 'SHORT'
            entry_price: Entry price
            quantity: Position size
            stop_loss: Stop loss price
            take_profit: Take profit price (TP1)
            leverage: Position leverage
            position_id: Unique position ID
            margin: Margin used
            atr: ATR value for trailing
        """
        # Calculate risk/reward
        risk = abs(entry_price - stop_loss)
        reward = abs(take_profit - entry_price) if take_profit > 0 else 0
        rr_ratio = reward / risk if risk > 0 else 0

        entry = TradeLogEntry(
            timestamp=datetime.now(),
            event_type="🟢 POSITION OPENED",
            symbol=symbol,
            side=side,
            position_id=position_id,
            data={
                "entry_price": entry_price,
                "quantity": quantity,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "leverage": leverage,
                "margin": margin,
                "atr": atr,
                "risk": risk,
                "reward": reward,
                "risk_reward_ratio": f"{rr_ratio:.2f}R"
            }
        )
        self._write_entry(entry)
        logger.info(f"📝 Logged OPEN: {symbol} {side} @ ${entry_price:.4f}")

    def log_price_update(
        self,
        symbol: str,
        current_price: float,
        tp_price: float,
        sl_price: float,
        side: str,
        entry_price: float = 0.0,
        position_id: str = ""
    ) -> None:
        """
        Log price update every 10 seconds per symbol.

        Args:
            symbol: Trading pair
            current_price: Current market price
            tp_price: Take profit price
            sl_price: Stop loss price
            side: 'LONG' or 'SHORT'
            entry_price: Entry price for PnL calculation
            position_id: Position ID
        """
        now = datetime.now().timestamp()
        last_log = self._last_price_log.get(symbol, 0)

        # Only log every 10 seconds per symbol
        if now - last_log < self.PRICE_UPDATE_INTERVAL:
            return

        self._last_price_log[symbol] = now

        # Calculate distances
        if side == 'LONG':
            distance_to_tp = tp_price - current_price if tp_price > 0 else 0
            distance_to_sl = current_price - sl_price if sl_price > 0 else 0
            pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
        else:  # SHORT
            distance_to_tp = current_price - tp_price if tp_price > 0 else 0
            distance_to_sl = sl_price - current_price if sl_price > 0 else 0
            pnl_pct = ((entry_price - current_price) / entry_price * 100) if entry_price > 0 else 0

        entry = TradeLogEntry(
            timestamp=datetime.now(),
            event_type="📊 PRICE UPDATE",
            symbol=symbol,
            side=side,
            position_id=position_id,
            data={
                "current_price": current_price,
                "entry_price": entry_price,
                "tp_price": tp_price,
                "sl_price": sl_price,
                "distance_to_TP": distance_to_tp,
                "distance_to_SL": distance_to_sl,
                "unrealized_pnl_pct": pnl_pct
            }
        )
        self._write_entry(entry)

    def log_tp_hit(
        self,
        symbol: str,
        side: str,
        hit_price: float,
        tp_level: int,  # 1, 2, or 3
        partial_close_qty: float,
        remaining_qty: float,
        new_sl: float,
        execution_status: str,  # 'SUCCESS', 'FAILED', 'PENDING'
        position_id: str = "",
        entry_price: float = 0.0,
        realized_pnl: float = 0.0
    ) -> None:
        """
        Log TP hit event with execution details.

        Args:
            symbol: Trading pair
            side: 'LONG' or 'SHORT'
            hit_price: Price at which TP was hit
            tp_level: TP level (1, 2, or 3)
            partial_close_qty: Quantity closed
            remaining_qty: Remaining quantity
            new_sl: New stop loss after TP
            execution_status: 'SUCCESS', 'FAILED', or 'PENDING'
            position_id: Position ID
            entry_price: Entry price for PnL calculation
            realized_pnl: Realized PnL from partial close
        """
        # Calculate profit
        if entry_price > 0:
            if side == 'LONG':
                profit_per_unit = hit_price - entry_price
            else:
                profit_per_unit = entry_price - hit_price
            partial_profit = profit_per_unit * partial_close_qty
        else:
            partial_profit = realized_pnl

        close_pct = partial_close_qty / (partial_close_qty + remaining_qty) * 100 if (partial_close_qty + remaining_qty) > 0 else 0

        entry = TradeLogEntry(
            timestamp=datetime.now(),
            event_type=f"🎯 TP{tp_level} HIT",
            symbol=symbol,
            side=side,
            position_id=position_id,
            data={
                "hit_price": hit_price,
                "entry_price": entry_price,
                "tp_level": tp_level,
                "close_percent": close_pct,
                "partial_close_qty": partial_close_qty,
                "remaining_qty": remaining_qty,
                "new_stop_loss": new_sl,
                "partial_profit": partial_profit,
                "execution_status": execution_status
            }
        )
        self._write_entry(entry)
        logger.info(f"📝 Logged TP{tp_level}: {symbol} @ ${hit_price:.4f} [{execution_status}]")

    def log_sl_hit(
        self,
        symbol: str,
        side: str,
        hit_price: float,
        close_qty: float,
        realized_pnl: float,
        exit_reason: str,
        position_id: str = "",
        entry_price: float = 0.0,
        roe_percent: float = 0.0  # SOTA FIX (Feb 2026): Add ROE for complete statistics
    ) -> None:
        """
        Log SL hit event.

        Args:
            symbol: Trading pair
            side: 'LONG' or 'SHORT'
            hit_price: Price at which SL was hit
            close_qty: Quantity closed
            realized_pnl: Realized PnL (NET including fees)
            exit_reason: Reason for exit (e.g., 'STOP_LOSS', 'TRAILING_STOP')
            position_id: Position ID
            entry_price: Entry price
            roe_percent: Return on Equity percentage (SOTA Feb 2026)
        """
        # Calculate loss percentage
        loss_pct = 0
        if entry_price > 0:
            if side == 'LONG':
                loss_pct = (hit_price - entry_price) / entry_price * 100
            else:
                loss_pct = (entry_price - hit_price) / entry_price * 100

        entry = TradeLogEntry(
            timestamp=datetime.now(),
            event_type="🔴 SL HIT",
            symbol=symbol,
            side=side,
            position_id=position_id,
            data={
                "hit_price": hit_price,
                "entry_price": entry_price,
                "close_qty": close_qty,
                "realized_pnl": realized_pnl,
                "pnl_percent": loss_pct,
                "roe_percent": roe_percent,  # SOTA FIX (Feb 2026): Log ROE
                "exit_reason": exit_reason
            }
        )
        self._write_entry(entry)
        logger.info(f"📝 Logged SL: {symbol} @ ${hit_price:.4f} | PnL: ${realized_pnl:.2f} | ROE: {roe_percent:.2f}%")

    def log_position_closed(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float,
        quantity: float,
        final_pnl: float,
        hold_duration_seconds: float,
        max_drawdown: float,
        max_profit: float,
        exit_reason: str,
        position_id: str = "",
        tp_hit_count: int = 0
    ) -> None:
        """
        Log position close with full statistics.

        Args:
            symbol: Trading pair
            side: 'LONG' or 'SHORT'
            entry_price: Entry price
            exit_price: Exit price
            quantity: Position size
            final_pnl: Final realized PnL
            hold_duration_seconds: How long position was held
            max_drawdown: Maximum drawdown during position
            max_profit: Maximum profit during position
            exit_reason: Reason for exit
            position_id: Position ID
            tp_hit_count: Number of TP levels hit
        """
        # Calculate ROE
        if entry_price > 0:
            if side == 'LONG':
                roe_pct = (exit_price - entry_price) / entry_price * 100
            else:
                roe_pct = (entry_price - exit_price) / entry_price * 100
        else:
            roe_pct = 0

        # Format duration
        hours = int(hold_duration_seconds // 3600)
        minutes = int((hold_duration_seconds % 3600) // 60)
        seconds = int(hold_duration_seconds % 60)
        duration_str = f"{hours}h {minutes}m {seconds}s"

        entry = TradeLogEntry(
            timestamp=datetime.now(),
            event_type="⬛ POSITION CLOSED",
            symbol=symbol,
            side=side,
            position_id=position_id,
            data={
                "entry_price": entry_price,
                "exit_price": exit_price,
                "quantity": quantity,
                "final_pnl": final_pnl,
                "roe_percent": roe_pct,
                "hold_duration": duration_str,
                "max_drawdown": max_drawdown,
                "max_profit": max_profit,
                "tp_levels_hit": tp_hit_count,
                "exit_reason": exit_reason
            }
        )
        self._write_entry(entry)
        logger.info(f"📝 Logged CLOSE: {symbol} | PnL: ${final_pnl:.2f} | Reason: {exit_reason}")

    def log_tp_check(
        self,
        symbol: str,
        side: str,
        current_price: float,
        high_price: float,
        low_price: float,
        tp_price: float,
        tp_hit: bool,
        position_id: str = "",
        check_price_type: str = "CLOSE"  # SOTA SYNC: Document price type used
    ) -> None:
        """
        Log TP check result for debugging.

        Args:
            symbol: Trading pair
            side: 'LONG' or 'SHORT'
            current_price: Current close price
            high_price: Candle high
            low_price: Candle low
            tp_price: TP target price
            tp_hit: Whether TP was hit
            position_id: Position ID
            check_price_type: Price type used for check (CLOSE, HIGH, LOW)
        """
        # SOTA SYNC: Use CLOSE price for check (matches SL logic)
        check_price = current_price
        distance = abs(check_price - tp_price)

        entry = TradeLogEntry(
            timestamp=datetime.now(),
            event_type="🔍 TP CHECK" if not tp_hit else "✅ TP TRIGGERED",
            symbol=symbol,
            side=side,
            position_id=position_id,
            data={
                "close_price": current_price,
                "high_price": high_price,
                "low_price": low_price,
                "tp_target": tp_price,
                "check_price": check_price,
                "check_price_type": check_price_type,
                "distance_to_tp": distance,
                "tp_hit": "YES" if tp_hit else "NO"
            }
        )
        self._write_entry(entry)

    def log_sl_check(
        self,
        symbol: str,
        side: str,
        current_price: float,
        sl_price: float,
        sl_hit: bool,
        position_id: str = ""
    ) -> None:
        """
        Log SL check result for debugging.

        Args:
            symbol: Trading pair
            side: 'LONG' or 'SHORT'
            current_price: Current close price (used for SL check)
            sl_price: SL target price
            sl_hit: Whether SL was hit
            position_id: Position ID
        """
        distance = abs(current_price - sl_price)

        entry = TradeLogEntry(
            timestamp=datetime.now(),
            event_type="🔍 SL CHECK" if not sl_hit else "⚠️ SL TRIGGERED",
            symbol=symbol,
            side=side,
            position_id=position_id,
            data={
                "close_price": current_price,
                "sl_target": sl_price,
                "distance_to_sl": distance,
                "sl_hit": "YES" if sl_hit else "NO"
            }
        )
        self._write_entry(entry)

    def log_grace_period(
        self,
        symbol: str,
        side: str,
        time_since_entry: float,
        grace_period: float,
        tp_queued: bool = False,
        position_id: str = ""
    ) -> None:
        """
        Log grace period status.

        Args:
            symbol: Trading pair
            side: Position side
            time_since_entry: Seconds since entry
            grace_period: Grace period duration
            tp_queued: Whether TP was queued during grace period
            position_id: Position ID
        """
        entry = TradeLogEntry(
            timestamp=datetime.now(),
            event_type="⏳ GRACE PERIOD",
            symbol=symbol,
            side=side,
            position_id=position_id,
            data={
                "time_since_entry": f"{time_since_entry:.1f}s",
                "grace_period": f"{grace_period:.1f}s",
                "remaining": f"{max(0, grace_period - time_since_entry):.1f}s",
                "tp_queued": "YES" if tp_queued else "NO"
            }
        )
        self._write_entry(entry)

    def close(self):
        """Close the log file."""
        with self._lock:
            if self._current_file:
                try:
                    self._current_file.close()
                except:
                    pass
                self._current_file = None


# Singleton instance
_trade_logger: Optional[TradeLogger] = None


def get_trade_logger() -> TradeLogger:
    """Get or create TradeLogger singleton."""
    global _trade_logger
    if _trade_logger is None:
        _trade_logger = TradeLogger()
    return _trade_logger


def init_trade_logger(log_dir: str = "documents/trading-logs") -> TradeLogger:
    """Initialize TradeLogger with custom log directory."""
    global _trade_logger
    _trade_logger = TradeLogger(log_dir=log_dir)
    return _trade_logger
