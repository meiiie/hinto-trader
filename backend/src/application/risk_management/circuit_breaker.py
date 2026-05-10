"""
Circuit Breaker - Risk Management Layer (SOTA Feb 9, 2026)

Institutional-grade risk controls matching Two Sigma / Citadel patterns:
1. Per-Symbol Direction CB: Block symbol+direction after N consecutive losses
2. Daily Symbol Loss Limit: Block symbol after N total losses in a day
3. Global CB: Stop ALL trading if Portfolio Drawdown exceeds threshold
4. Trading Schedule: Block trading during configurable dead-zone windows

All params are runtime-configurable via API for zero-downtime tuning.
"""

import logging
from datetime import datetime, timedelta, timezone, time, date
from typing import Dict, List, Optional, Any, Tuple


class CircuitBreaker:
    def __init__(
        self,
        max_consecutive_losses: int = 2,
        cooldown_hours: float = 0.5,
        max_daily_drawdown_pct: float = 0.20,
        daily_symbol_loss_limit: int = 3,
        daily_loss_cooldown_hours: float = 0,
        daily_loss_size_penalty: float = 0.0,
        symbol_side_loss_limit: int = 0,
        symbol_side_loss_window_hours: float = 72.0,
        symbol_side_cooldown_hours: float = 72.0,
        # SOTA (Feb 9, 2026): Trading Schedule
        blocked_windows: Optional[List[Dict[str, str]]] = None,
        blocked_windows_utc_offset: int = 7,
        # F1: Escalating CB Cooldown
        use_escalating_cooldown: bool = False,
        escalating_schedule_str: str = "",
        # F2: Direction Block (cross-symbol directional awareness)
        use_direction_block: bool = False,
        direction_block_threshold: int = 4,
        direction_block_window_hours: float = 2.0,
        direction_block_cooldown_hours: float = 4.0,
    ):
        # Per symbol, per direction tracking
        self.state: Dict[str, Dict[str, Any]] = {}
        self.max_losses = max_consecutive_losses
        self.cooldown_hours = cooldown_hours
        self.max_daily_drawdown_pct = max_daily_drawdown_pct

        # Daily symbol loss limit (0 = disabled)
        # Tracks TOTAL losses per symbol per UTC day (both directions)
        self.daily_symbol_loss_limit = daily_symbol_loss_limit
        self.daily_loss_cooldown_hours = daily_loss_cooldown_hours  # 0 = block until end of day
        self.daily_loss_size_penalty = daily_loss_size_penalty  # 0.0 = disabled, 0.25 = -25% per loss
        self._daily_losses: Dict[str, Dict[date, int]] = {}  # {symbol: {date: count}}
        self.symbol_side_loss_limit = symbol_side_loss_limit
        self.symbol_side_loss_window_hours = symbol_side_loss_window_hours
        self.symbol_side_cooldown_hours = symbol_side_cooldown_hours
        self._symbol_side_losses: Dict[str, Dict[str, List[datetime]]] = {}

        # Global Portfolio State
        self.daily_start_balance: float = 0.0
        self.current_day: Optional[datetime] = None
        self.global_blocked_until: Optional[datetime] = None

        # SOTA (Feb 9, 2026): Trading Schedule — Dead Zone Windows
        # Format: [{"start": "09:00", "end": "11:00"}, {"start": "22:55", "end": "23:30"}]
        # Times are in local timezone (default UTC+7 for Vietnam)
        self.blocked_windows: List[Dict[str, str]] = blocked_windows or []
        self.blocked_windows_utc_offset: int = blocked_windows_utc_offset
        self.blocked_windows_enabled: bool = len(self.blocked_windows) > 0

        # F1: Escalating CB Cooldown
        # Schedule format: "2:0.5,3:2,4:8,5:24" → [(5,24),(4,8),(3,2),(2,0.5)]
        self.use_escalating_cooldown = use_escalating_cooldown
        self._escalating_schedule: List[Tuple[int, float]] = []
        if use_escalating_cooldown and escalating_schedule_str:
            for pair in escalating_schedule_str.split(','):
                pair = pair.strip()
                if ':' in pair:
                    losses_str, hours_str = pair.split(':', 1)
                    self._escalating_schedule.append((int(losses_str), float(hours_str)))
            self._escalating_schedule.sort(key=lambda x: x[0], reverse=True)

        # F2: Direction Block — cross-symbol directional awareness
        # When N unique symbols lose in the same direction within a window,
        # block that entire direction for cooldown_hours
        self.use_direction_block = use_direction_block
        self.direction_block_threshold = direction_block_threshold
        self.direction_block_window_hours = direction_block_window_hours
        self.direction_block_cooldown_hours = direction_block_cooldown_hours
        # Tracking: {side: [(symbol, timestamp), ...]}
        self._direction_losses: Dict[str, List[Tuple[str, datetime]]] = {'LONG': [], 'SHORT': []}
        self._direction_blocked_until: Dict[str, Optional[datetime]] = {'LONG': None, 'SHORT': None}

        # Metrics
        self._blocked_by_schedule: int = 0
        self._blocked_by_symbol_cb: int = 0
        self._blocked_by_daily_limit: int = 0
        self._escalating_cb_triggers: int = 0
        self._blocked_by_direction: int = 0
        self._blocked_by_symbol_side_window: int = 0

        self.logger = logging.getLogger(__name__)

    def _get_state(self, symbol: str):
        if symbol not in self.state:
            self.state[symbol] = {
                'LONG': {'losses': 0, 'blocked_until': None, 'window_blocked_until': None},
                'SHORT': {'losses': 0, 'blocked_until': None, 'window_blocked_until': None}
            }
        return self.state[symbol]

    def _record_symbol_side_loss(self, symbol: str, side: str, current_time: datetime) -> None:
        if self.symbol_side_loss_limit <= 0:
            return

        symbol_losses = self._symbol_side_losses.setdefault(symbol, {"LONG": [], "SHORT": []})
        window_cutoff = current_time - timedelta(hours=self.symbol_side_loss_window_hours)
        loss_times = [ts for ts in symbol_losses[side] if ts >= window_cutoff]
        loss_times.append(current_time)
        symbol_losses[side] = loss_times

        if len(loss_times) < self.symbol_side_loss_limit:
            return

        state = self._get_state(symbol)[side]
        unblock_time = current_time + timedelta(hours=self.symbol_side_cooldown_hours)
        current_block = state.get('window_blocked_until')
        if current_block is None or unblock_time > current_block:
            state['window_blocked_until'] = unblock_time
            self._blocked_by_symbol_side_window += 1
            self.logger.warning(
                f"SYMBOL-SIDE QUARANTINE: {symbol} {side} hit {len(loss_times)} losses "
                f"in {self.symbol_side_loss_window_hours:.1f}h, blocked until "
                f"{unblock_time.strftime('%Y-%m-%d %H:%M:%S')} UTC"
            )

    def _get_cooldown_hours(self, consecutive_losses: int) -> float:
        """Get cooldown duration based on consecutive loss count.
        If escalating is OFF, returns flat cooldown_hours.
        If escalating is ON, scans schedule for highest matching threshold."""
        if not self.use_escalating_cooldown or not self._escalating_schedule:
            return self.cooldown_hours
        # Schedule sorted descending: [(5,24),(4,8),(3,2),(2,0.5)]
        for threshold, hours in self._escalating_schedule:
            if consecutive_losses >= threshold:
                return hours
        return self.cooldown_hours

    # ═══════════════════════════════════════════════════════════════════
    # RUNTIME CONFIG (SOTA Feb 9, 2026)
    # All params can be updated at runtime via API for zero-downtime tuning
    # ═══════════════════════════════════════════════════════════════════

    def update_params(self, **kwargs):
        """
        Update CB params at runtime. Only provided keys are updated.

        Supported keys:
            max_consecutive_losses (int): Block after N same-direction losses
            cooldown_minutes (int): Cooldown duration in minutes
            daily_symbol_loss_limit (int): Max losses per symbol per day (0=disabled)
            blocked_windows (list): Dead zone windows [{"start":"09:00","end":"11:00"}]
            blocked_windows_enabled (bool): Enable/disable trading schedule
            blocked_windows_utc_offset (int): Timezone offset for windows
            max_daily_drawdown_pct (float): Global drawdown threshold (0.20 = 20%)
        """
        if 'max_consecutive_losses' in kwargs:
            self.max_losses = int(kwargs['max_consecutive_losses'])
            self.logger.info(f"CB: max_consecutive_losses = {self.max_losses}")

        if 'cooldown_minutes' in kwargs:
            self.cooldown_hours = float(kwargs['cooldown_minutes']) / 60.0
            self.logger.info(f"CB: cooldown = {kwargs['cooldown_minutes']}min ({self.cooldown_hours:.2f}h)")

        if 'daily_symbol_loss_limit' in kwargs:
            self.daily_symbol_loss_limit = int(kwargs['daily_symbol_loss_limit'])
            self.logger.info(f"CB: daily_symbol_loss_limit = {self.daily_symbol_loss_limit}")

        if 'symbol_side_loss_limit' in kwargs:
            self.symbol_side_loss_limit = int(kwargs['symbol_side_loss_limit'])
            self.logger.info(f"CB: symbol_side_loss_limit = {self.symbol_side_loss_limit}")

        if 'symbol_side_loss_window_hours' in kwargs:
            self.symbol_side_loss_window_hours = float(kwargs['symbol_side_loss_window_hours'])
            self.logger.info(f"CB: symbol_side_loss_window_hours = {self.symbol_side_loss_window_hours}")

        if 'symbol_side_cooldown_hours' in kwargs:
            self.symbol_side_cooldown_hours = float(kwargs['symbol_side_cooldown_hours'])
            self.logger.info(f"CB: symbol_side_cooldown_hours = {self.symbol_side_cooldown_hours}")

        if 'blocked_windows' in kwargs:
            raw = kwargs['blocked_windows']
            if isinstance(raw, str):
                self.blocked_windows = self._parse_windows_string(raw)
            elif isinstance(raw, list):
                self.blocked_windows = raw
            self.blocked_windows_enabled = len(self.blocked_windows) > 0
            self.logger.info(f"CB: blocked_windows = {self.blocked_windows}")

        if 'blocked_windows_enabled' in kwargs:
            self.blocked_windows_enabled = bool(kwargs['blocked_windows_enabled'])
            self.logger.info(f"CB: blocked_windows_enabled = {self.blocked_windows_enabled}")

        if 'blocked_windows_utc_offset' in kwargs:
            self.blocked_windows_utc_offset = int(kwargs['blocked_windows_utc_offset'])
            self.logger.info(f"CB: blocked_windows_utc_offset = UTC+{self.blocked_windows_utc_offset}")

        if 'max_daily_drawdown_pct' in kwargs:
            self.max_daily_drawdown_pct = float(kwargs['max_daily_drawdown_pct'])
            self.logger.info(f"CB: max_daily_drawdown_pct = {self.max_daily_drawdown_pct*100:.1f}%")

    @staticmethod
    def _parse_windows_string(s: str) -> List[Dict[str, str]]:
        """Parse '09:00-11:00,22:55-23:30' → [{"start":"09:00","end":"11:00"}, ...]"""
        windows = []
        for part in s.split(','):
            part = part.strip()
            if '-' in part:
                start, end = part.split('-', 1)
                windows.append({'start': start.strip(), 'end': end.strip()})
        return windows

    # ═══════════════════════════════════════════════════════════════════
    # TRADING SCHEDULE (SOTA Feb 9, 2026)
    # Institutional pattern: Define dead-zone windows where no new entries
    # ═══════════════════════════════════════════════════════════════════

    def is_in_blocked_window(self, current_time_utc: datetime) -> Tuple[bool, str]:
        """
        Check if current time falls within a blocked trading window.

        Args:
            current_time_utc: Current time in UTC

        Returns:
            (is_blocked, reason_string)
        """
        if not self.blocked_windows_enabled or not self.blocked_windows:
            return False, ""

        # Convert UTC to local time
        local_offset = timedelta(hours=self.blocked_windows_utc_offset)
        local_time = current_time_utc + local_offset
        local_hhmm = local_time.strftime('%H:%M')

        for window in self.blocked_windows:
            start = window.get('start', '')
            end = window.get('end', '')
            reason = window.get('reason', f'{start}-{end}')

            if not start or not end:
                continue

            # Handle overnight windows (e.g., 22:55-01:00)
            if start <= end:
                # Normal window: 09:00-11:00
                if start <= local_hhmm < end:
                    self._blocked_by_schedule += 1
                    return True, f"Dead Zone {start}-{end} (UTC+{self.blocked_windows_utc_offset}): {reason}"
            else:
                # Overnight window: 22:55-01:00
                if local_hhmm >= start or local_hhmm < end:
                    self._blocked_by_schedule += 1
                    return True, f"Dead Zone {start}-{end} (UTC+{self.blocked_windows_utc_offset}): {reason}"

        return False, ""

    # ═══════════════════════════════════════════════════════════════════
    # GLOBAL PORTFOLIO STATE
    # ═══════════════════════════════════════════════════════════════════

    def update_portfolio_state(self, current_balance: float, current_time: datetime):
        """Called every step to check global health."""
        # 1. New Day Reset
        day_key = current_time.date()
        if self.current_day != day_key:
            self.daily_start_balance = current_balance
            self.current_day = day_key

        # 2. Check Drawdown
        if self.daily_start_balance > 0:
            drawdown = (self.daily_start_balance - current_balance) / self.daily_start_balance

            if drawdown >= self.max_daily_drawdown_pct:
                if not self.global_blocked_until or current_time > self.global_blocked_until:
                    unblock_time = current_time + timedelta(hours=24)
                    self.global_blocked_until = unblock_time
                    self.logger.critical(
                        f"GLOBAL CIRCUIT BREAKER: Daily Drawdown {drawdown*100:.2f}% > "
                        f"{self.max_daily_drawdown_pct*100:.1f}%. HALTING ALL TRADING UNTIL {unblock_time}"
                    )

    # ═══════════════════════════════════════════════════════════════════
    # TRADE RECORDING
    # ═══════════════════════════════════════════════════════════════════

    def record_trade(self, symbol: str, side: str, pnl_usd: float):
        """Record trade result (legacy, uses datetime.now for time context)."""
        self.record_trade_with_time(symbol, side, pnl_usd, datetime.now(timezone.utc))

    def record_trade_with_time(self, symbol: str, side: str, pnl_usd: float, current_time: datetime):
        """SOTA method with time context — records per-direction consecutive + daily losses."""
        state = self._get_state(symbol)[side]

        if pnl_usd > 0:
            state['losses'] = 0
            state['blocked_until'] = None
        else:
            state['losses'] += 1
            if state['losses'] >= self.max_losses:
                cooldown = self._get_cooldown_hours(state['losses'])
                unblock_time = current_time + timedelta(hours=cooldown)
                state['blocked_until'] = unblock_time
                self._blocked_by_symbol_cb += 1
                if self.use_escalating_cooldown and cooldown != self.cooldown_hours:
                    self._escalating_cb_triggers += 1
                self.logger.warning(
                    f"SYMBOL CB: {symbol} {side} hit {state['losses']} consecutive losses, "
                    f"blocked for {cooldown*60:.0f}min until "
                    f"{unblock_time.strftime('%H:%M:%S')} UTC"
                )

        # F2: Direction Block — track cross-symbol directional losses
        if pnl_usd < 0:
            self._record_symbol_side_loss(symbol, side, current_time)

        if pnl_usd < 0 and self.use_direction_block:
            window_cutoff = current_time - timedelta(hours=self.direction_block_window_hours)
            # Append this loss
            self._direction_losses[side].append((symbol, current_time))
            # Prune old entries outside window
            self._direction_losses[side] = [
                (s, t) for s, t in self._direction_losses[side]
                if t >= window_cutoff
            ]
            # Count unique symbols that lost in this direction within window
            unique_losers = len(set(s for s, t in self._direction_losses[side]))
            if unique_losers >= self.direction_block_threshold:
                unblock_time = current_time + timedelta(hours=self.direction_block_cooldown_hours)
                self._direction_blocked_until[side] = unblock_time
                self._blocked_by_direction += 1
                self.logger.warning(
                    f"DIRECTION BLOCK: {unique_losers} unique symbols lost {side} "
                    f"in {self.direction_block_window_hours}h window, "
                    f"blocking ALL {side} until {unblock_time.strftime('%H:%M:%S')} UTC"
                )

        # Daily symbol loss tracking (independent from consecutive)
        if pnl_usd < 0 and self.daily_symbol_loss_limit > 0:
            day_key = current_time.date()
            if symbol not in self._daily_losses:
                self._daily_losses[symbol] = {}
            self._daily_losses[symbol][day_key] = self._daily_losses[symbol].get(day_key, 0) + 1

            if self._daily_losses[symbol][day_key] >= self.daily_symbol_loss_limit:
                if self.daily_loss_cooldown_hours > 0:
                    unblock_time = current_time + timedelta(hours=self.daily_loss_cooldown_hours)
                else:
                    unblock_time = datetime.combine(day_key + timedelta(days=1), time.min, tzinfo=timezone.utc)
                state_long = self._get_state(symbol)['LONG']
                state_short = self._get_state(symbol)['SHORT']
                state_long['blocked_until'] = max(state_long.get('blocked_until') or current_time, unblock_time)
                state_short['blocked_until'] = max(state_short.get('blocked_until') or current_time, unblock_time)
                self._blocked_by_daily_limit += 1
                cooldown_label = f"{self.daily_loss_cooldown_hours}h cooldown" if self.daily_loss_cooldown_hours > 0 else "end of day"
                self.logger.warning(
                    f"DAILY LIMIT: {symbol} hit {self._daily_losses[symbol][day_key]} losses on {day_key}, "
                    f"blocked BOTH directions until {unblock_time} ({cooldown_label})"
                )

        # Daily loss size penalty tracking (for position sizing)
        if pnl_usd < 0 and self.daily_loss_size_penalty > 0:
            day_key = current_time.date()
            if symbol not in self._daily_losses:
                self._daily_losses[symbol] = {}
            # Avoid double counting if daily_symbol_loss_limit is also active
            if self.daily_symbol_loss_limit <= 0:
                self._daily_losses[symbol][day_key] = self._daily_losses[symbol].get(day_key, 0) + 1

    # ═══════════════════════════════════════════════════════════════════
    # BLOCK CHECK
    # ═══════════════════════════════════════════════════════════════════

    def is_blocked(self, symbol: str, side: str, current_time: datetime) -> bool:
        """Check if a symbol+direction is blocked from trading."""
        # 1. Global Block
        if self.global_blocked_until and current_time < self.global_blocked_until:
            return True

        # 2. Direction Block (cross-symbol directional awareness)
        if self.use_direction_block:
            dir_blocked = self._direction_blocked_until.get(side)
            if dir_blocked and current_time < dir_blocked:
                return True

        # 3. Symbol + Direction Block (consecutive losses OR daily limit)
        state = self._get_state(symbol).get(side)
        if not state:
            return False

        window_blocked_until = state.get('window_blocked_until')
        if window_blocked_until and current_time < window_blocked_until:
            return True

        blocked_until = state['blocked_until']
        if blocked_until and current_time < blocked_until:
            return True
        return False

    def get_block_reason(self, symbol: str, side: str, current_time: datetime) -> str:
        """Get human-readable block reason for logging."""
        if self.global_blocked_until and current_time < self.global_blocked_until:
            return f"Global DD block until {self.global_blocked_until.strftime('%H:%M')}"

        if self.use_direction_block:
            dir_blocked = self._direction_blocked_until.get(side)
            if dir_blocked and current_time < dir_blocked:
                return f"Direction block: too many {side} losses across symbols, until {dir_blocked.strftime('%H:%M')}"

        state = self._get_state(symbol).get(side)
        if state and state.get('blocked_until') and current_time < state['blocked_until']:
            losses = state.get('losses', 0)
            until = state['blocked_until'].strftime('%H:%M')
            # Check if it's daily limit
            day_key = current_time.date()
            daily_count = self._daily_losses.get(symbol, {}).get(day_key, 0)
            if daily_count >= self.daily_symbol_loss_limit > 0:
                return f"Daily limit ({daily_count}/{self.daily_symbol_loss_limit} losses), blocked until {until}"
            return f"{losses} consecutive {side} losses, blocked until {until}"

        if state and state.get('window_blocked_until') and current_time < state['window_blocked_until']:
            until = state['window_blocked_until'].strftime('%H:%M')
            day_cutoff = current_time - timedelta(hours=self.symbol_side_loss_window_hours)
            losses = [
                ts for ts in self._symbol_side_losses.get(symbol, {}).get(side, [])
                if ts >= day_cutoff
            ]
            return (
                f"Rolling symbol-side quarantine ({len(losses)}/{self.symbol_side_loss_limit} losses "
                f"in {self.symbol_side_loss_window_hours:.0f}h), blocked until {until}"
            )

        return ""

    def get_daily_loss_penalty(self, symbol: str, current_time: datetime) -> float:
        """Returns size multiplier based on daily losses. 1.0 = full size, 0.0 = blocked.
        Freqtrade style: each loss reduces size by daily_loss_size_penalty (e.g. 0.25 = -25%)."""
        if self.daily_loss_size_penalty <= 0:
            return 1.0
        day_key = current_time.date()
        losses = self._daily_losses.get(symbol, {}).get(day_key, 0)
        if losses == 0:
            return 1.0
        multiplier = max(0.0, 1.0 - (losses * self.daily_loss_size_penalty))
        return multiplier


    # ═══════════════════════════════════════════════════════════════════
    # STATUS / METRICS (for API exposure)
    # ═══════════════════════════════════════════════════════════════════

    def get_status(self) -> Dict[str, Any]:
        """Get full CB status for API/monitoring."""
        current_time = datetime.now(timezone.utc)

        blocked_symbols = {}
        for symbol, directions in self.state.items():
            for side, state in directions.items():
                blocked_until = state.get('blocked_until')
                window_blocked_until = state.get('window_blocked_until')
                active_until = None
                if blocked_until and current_time < blocked_until:
                    active_until = blocked_until
                if window_blocked_until and current_time < window_blocked_until:
                    active_until = max(active_until, window_blocked_until) if active_until else window_blocked_until
                if active_until:
                    key = f"{symbol}_{side}"
                    blocked_symbols[key] = {
                        'consecutive_losses': state.get('losses', 0),
                        'blocked_until': active_until.isoformat(),
                        'window_blocked_until': window_blocked_until.isoformat() if window_blocked_until else None,
                        'remaining_seconds': (active_until - current_time).total_seconds(),
                    }

        return {
            'config': {
                'max_consecutive_losses': self.max_losses,
                'cooldown_minutes': self.cooldown_hours * 60,
                'daily_symbol_loss_limit': self.daily_symbol_loss_limit,
                'symbol_side_loss_limit': self.symbol_side_loss_limit,
                'symbol_side_loss_window_hours': self.symbol_side_loss_window_hours,
                'symbol_side_cooldown_hours': self.symbol_side_cooldown_hours,
                'max_daily_drawdown_pct': self.max_daily_drawdown_pct,
                'blocked_windows': self.blocked_windows,
                'blocked_windows_enabled': self.blocked_windows_enabled,
                'blocked_windows_utc_offset': self.blocked_windows_utc_offset,
            },
            'state': {
                'global_blocked': self.global_blocked_until is not None and current_time < self.global_blocked_until,
                'global_blocked_until': self.global_blocked_until.isoformat() if self.global_blocked_until else None,
                'blocked_symbols': blocked_symbols,
                'daily_losses': {
                    sym: {str(d): c for d, c in dates.items()}
                    for sym, dates in self._daily_losses.items()
                },
            },
            'metrics': {
                'blocked_by_schedule': self._blocked_by_schedule,
                'blocked_by_symbol_cb': self._blocked_by_symbol_cb,
                'blocked_by_daily_limit': self._blocked_by_daily_limit,
                'escalating_cb_triggers': self._escalating_cb_triggers,
                'blocked_by_direction': self._blocked_by_direction,
                'blocked_by_symbol_side_window': self._blocked_by_symbol_side_window,
            },
        }
