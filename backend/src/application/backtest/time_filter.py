"""
TimeFilter - SOTA Tiered Time-Based Trading Filter

SOTA Pattern: Tiered Sizing (Two Sigma / Renaissance approach)
Instead of binary block/allow, uses size multipliers based on liquidity patterns.

Crypto Liquidity Pattern (Vietnam Time UTC+7):
- Tier 1 (20:00-23:59 VN): EU-US overlap = BEST liquidity → 100% size
- Tier 2 (15:00-19:00, 00:00-04:00 VN): Good liquidity → 50% size (or 100% in block-only mode)
- Tier 3 (14:00 VN): Transition → 30% size (or 100% in block-only mode)
- Tier 4 (05:00-13:00 VN): Low liquidity → 0% (Block)

Usage:
    time_filter = TimeFilter()
    multiplier = time_filter.get_size_multiplier(candle_timestamp)
    if multiplier > 0:
        position_size = base_size * multiplier
"""

from datetime import datetime, timezone as tz, timedelta
from typing import Set, Optional, Tuple, List, Dict
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class TimeTier(Enum):
    """Time tiers based on liquidity patterns."""
    TIER_1 = "BEST"    # 100% - EU-US overlap
    TIER_2 = "GOOD"    # 50% - Good liquidity
    TIER_3 = "OK"      # 30% - Transition
    TIER_4 = "AVOID"   # 0% - Low liquidity


class TimeFilter:
    """
    SOTA Tiered Time-Based Trading Filter.

    Based on institutional research from Two Sigma, Renaissance, and
    Binance market analysis. Uses Vietnam timezone (UTC+7).

    Tier Breakdown (Vietnam Time):
        - Tier 1 (20:00-23:59): EU-US overlap, highest liquidity
        - Tier 2 (15:00-19:00, 00:00-04:00): Europe/US sessions
        - Tier 3 (14:00): Transition hour
        - Tier 4 (05:00-13:00): Asia low volume, BLOCKED
    """

    # Tier definitions (Vietnam Time UTC+7)
    TIER_1_VN: Set[int] = {20, 21, 22, 23}       # Best hours - 100%
    TIER_2_VN: Set[int] = {15, 16, 17, 18, 19,   # Good hours - 50%
                           0, 1, 2, 3, 4}
    TIER_3_VN: Set[int] = {14}                   # OK hours - 30%
    TIER_4_VN: Set[int] = {5, 6, 7, 8, 9, 10,    # Block hours - 0%
                           11, 12, 13}

    # Size multipliers per tier
    TIER_MULTIPLIERS = {
        TimeTier.TIER_1: 1.0,   # Full size
        TimeTier.TIER_2: 0.5,   # Half size
        TimeTier.TIER_3: 0.3,   # Small size
        TimeTier.TIER_4: 0.0,   # No trade
    }

    # Legacy: Death hours (for backward compatibility with --time-filter flag)
    DEATH_HOURS_LOCAL: Set[int] = {0, 5, 11, 22}

    def __init__(
        self,
        timezone_offset_hours: int = 7,  # UTC+7 = Vietnam
        use_tiered_sizing: bool = True,  # SOTA: Use tiers instead of binary
        block_but_full_size: bool = False, # SOTA: Block Tier 4 but use 100% size for others
        custom_death_hours: Optional[Set[int]] = None,
        blocked_windows: Optional[List[Dict[str, str]]] = None,  # Precise minute-level windows
    ):
        """
        Args:
            timezone_offset_hours: Offset from UTC (e.g., 7 for Vietnam UTC+7)
            use_tiered_sizing: If True, use SOTA tiered approach. If False, use legacy binary.
            block_but_full_size: If True, block Tier 4 but use 100% size for Tier 1-3.
            custom_death_hours: Override default death hours if provided (legacy mode)
            blocked_windows: Precise minute-level blocked windows matching LIVE
                Format: [{"start": "09:00", "end": "14:00"}, ...]
                Times are in local timezone (UTC+offset)
        """
        self.tz_offset = timezone_offset_hours
        self.use_tiered_sizing = use_tiered_sizing
        self.block_but_full_size = block_but_full_size
        self.death_hours = custom_death_hours or self.DEATH_HOURS_LOCAL
        self.blocked_windows = blocked_windows or []
        self._use_precise_windows = len(self.blocked_windows) > 0

        # Parse blocked windows into (start_minutes, end_minutes) tuples
        self._parsed_windows = []
        for w in self.blocked_windows:
            start_h, start_m = map(int, w["start"].split(":"))
            end_h, end_m = map(int, w["end"].split(":"))
            start_total = start_h * 60 + start_m
            end_total = end_h * 60 + end_m
            self._parsed_windows.append((start_total, end_total))

        if self._use_precise_windows:
            total_blocked = sum((e - s) for s, e in self._parsed_windows) / 60
            logger.info(f"⏰ TimeFilter: PRECISE DEAD ZONES (matches LIVE)")
            for w in self.blocked_windows:
                logger.info(f"   DZ: {w['start']}-{w['end']} UTC+{self.tz_offset}")
            logger.info(f"   Total blocked: {total_blocked:.1f}h/day, Active: {24-total_blocked:.1f}h/day")
        else:
            mode = "TIERED" if use_tiered_sizing else "BINARY"
            if block_but_full_size:
                mode += " (BLOCK_FULL_SIZE)"
            logger.info(
                f"⏰ TimeFilter initialized: "
                f"Mode={mode}, TZ=UTC+{self.tz_offset}"
            )
            if use_tiered_sizing:
                t1_size = "100%"
                t2_size = "100%" if block_but_full_size else "50%"
                t3_size = "100%" if block_but_full_size else "30%"
                logger.info(f"   Tier 1 ({t1_size}): {sorted(self.TIER_1_VN)} VN time")
                logger.info(f"   Tier 2 ({t2_size}): {sorted(self.TIER_2_VN)} VN time")
                logger.info(f"   Tier 3 ({t3_size}): {sorted(self.TIER_3_VN)} VN time")
                logger.info(f"   Tier 4 (0%): {sorted(self.TIER_4_VN)} VN time")

    def _utc_to_local_hour(self, utc_dt: datetime) -> int:
        """Convert UTC datetime to local hour."""
        if utc_dt.tzinfo is None:
            utc_dt = utc_dt.replace(tzinfo=tz.utc)
        local_hour = (utc_dt.hour + self.tz_offset) % 24
        return local_hour

    def _utc_to_local_minutes(self, utc_dt: datetime) -> int:
        """Convert UTC datetime to local time in total minutes (0-1439)."""
        if utc_dt.tzinfo is None:
            utc_dt = utc_dt.replace(tzinfo=tz.utc)
        local_dt = utc_dt + timedelta(hours=self.tz_offset)
        return local_dt.hour * 60 + local_dt.minute

    def _is_in_precise_window(self, utc_dt: datetime) -> bool:
        """Check if timestamp falls within any precise blocked window."""
        local_mins = self._utc_to_local_minutes(utc_dt)
        for start_mins, end_mins in self._parsed_windows:
            if start_mins <= end_mins:
                if start_mins <= local_mins < end_mins:
                    return True
            else:
                # Overnight window, e.g. 23:00-00:00 or 22:55-01:00.
                if local_mins >= start_mins or local_mins < end_mins:
                    return True
        return False

    def get_tier(self, utc_timestamp: datetime) -> Tuple[TimeTier, float]:
        """
        Get the time tier and size multiplier for a timestamp.

        Args:
            utc_timestamp: Candle timestamp in UTC

        Returns:
            Tuple of (TimeTier, multiplier)
        """
        local_hour = self._utc_to_local_hour(utc_timestamp)

        if local_hour in self.TIER_1_VN:
            tier = TimeTier.TIER_1
        elif local_hour in self.TIER_2_VN:
            tier = TimeTier.TIER_2
        elif local_hour in self.TIER_3_VN:
            tier = TimeTier.TIER_3
        else:
            tier = TimeTier.TIER_4

        multiplier = self.TIER_MULTIPLIERS[tier]

        # SOTA Logic: If block_but_full_size is True
        # Use 1.0 for all allowed tiers (1, 2, 3)
        # Still use 0.0 for Tier 4
        if self.block_but_full_size and tier != TimeTier.TIER_4:
            multiplier = 1.0

        return tier, multiplier

    def get_size_multiplier(self, utc_timestamp: datetime) -> float:
        """
        Get position size multiplier based on time tier or precise windows.

        Returns:
            0.0 if blocked (dead zone), 1.0 if allowed
        """
        # Precise windows mode (matches LIVE exactly)
        if self._use_precise_windows:
            return 0.0 if self._is_in_precise_window(utc_timestamp) else 1.0

        if not self.use_tiered_sizing:
            return 1.0 if self.is_allowed(utc_timestamp) else 0.0

        _, multiplier = self.get_tier(utc_timestamp)
        return multiplier

    def is_allowed(self, utc_timestamp: datetime) -> bool:
        """Check if trading is allowed at this timestamp."""
        # Precise windows mode (matches LIVE exactly)
        if self._use_precise_windows:
            return not self._is_in_precise_window(utc_timestamp)

        if self.use_tiered_sizing:
            _, multiplier = self.get_tier(utc_timestamp)
            return multiplier > 0
        else:
            local_hour = self._utc_to_local_hour(utc_timestamp)
            return local_hour not in self.death_hours

    def get_blocked_hours_utc(self) -> Set[int]:
        """Get death hours converted to UTC for reference."""
        if self.use_tiered_sizing:
            return {(h - self.tz_offset) % 24 for h in self.TIER_4_VN}
        else:
            return {(h - self.tz_offset) % 24 for h in self.death_hours}

    def get_stats_header(self) -> str:
        """Return formatted header for logging."""
        if self.use_tiered_sizing:
            t1_size = "100%"
            t2_size = "100%" if self.block_but_full_size else "50%"
            t3_size = "100%" if self.block_but_full_size else "30%"
            mode_str = "TIERED MODE (BLOCK_FULL_SIZE)" if self.block_but_full_size else "TIERED MODE (SOTA)"

            return (
                f"Time Filter: {mode_str}\n"
                f"   Tier 1 ({t1_size}): hours {sorted(self.TIER_1_VN)} VN\n"
                f"   Tier 2 ({t2_size}): hours {sorted(self.TIER_2_VN)} VN\n"
                f"   Tier 3 ({t3_size}): hours {sorted(self.TIER_3_VN)} VN\n"
                f"   Tier 4 (BLOCK): hours {sorted(self.TIER_4_VN)} VN"
            )
        else:
            blocked_local = sorted(self.death_hours)
            blocked_utc = sorted(self.get_blocked_hours_utc())
            return (
                f"Time Filter: BINARY MODE (Legacy)\n"
                f"   Death Hours (UTC+{self.tz_offset}): {blocked_local}\n"
                f"   Death Hours (UTC): {blocked_utc}"
            )
