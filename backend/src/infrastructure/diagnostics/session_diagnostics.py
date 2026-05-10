"""
Session Diagnostics Service - SOTA Logging and Performance Analysis

This service captures comprehensive diagnostics during runtime and generates
a detailed report when the backend is shut down (Ctrl+C).

SOTA Best Practices (Binance, Google SRE, Jan 2026):
1. Request-level instrumentation with timing
2. Error aggregation and categorization
3. Graceful shutdown with report generation
4. Memory-efficient circular buffers
5. Thread-safe operations

Usage:
    from src.infrastructure.diagnostics.session_diagnostics import get_session_diagnostics

    diagnostics = get_session_diagnostics()
    diagnostics.record_api_call("GET", "/trades/portfolio", 150, True)
    diagnostics.record_error("API", "Connection timeout", {"endpoint": "/balance"})

    # On shutdown (Ctrl+C):
    diagnostics.generate_report()  # Saves to backend/logs/session_report_YYYYMMDD_HHMMSS.md
"""

import os
import time
import logging
import atexit
import signal
from datetime import datetime
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from threading import Lock
import json

logger = logging.getLogger(__name__)


@dataclass
class APICallRecord:
    """Single API call record."""
    timestamp: datetime
    method: str
    endpoint: str
    latency_ms: float
    success: bool
    error: Optional[str] = None
    status_code: int = 200


@dataclass
class ErrorRecord:
    """Single error record."""
    timestamp: datetime
    category: str
    message: str
    context: Dict[str, Any] = field(default_factory=dict)


class SessionDiagnostics:
    """
    SOTA Session Diagnostics Service.

    Tracks:
    - All API calls with latency
    - Errors by category
    - WebSocket events
    - Trading operations
    - Performance metrics

    Generates comprehensive report on shutdown.
    """

    MAX_RECORDS = 10000  # Circular buffer size

    def __init__(self):
        self._lock = Lock()
        self._start_time = datetime.now()
        self._api_calls: List[APICallRecord] = []
        self._errors: List[ErrorRecord] = []
        self._ws_events: List[Dict] = []
        self._trading_ops: List[Dict] = []

        # Aggregated metrics
        self._endpoint_stats: Dict[str, Dict] = defaultdict(lambda: {
            "count": 0,
            "total_ms": 0,
            "errors": 0,
            "min_ms": float('inf'),
            "max_ms": 0
        })

        self._error_counts: Dict[str, int] = defaultdict(int)

        # Report output directory
        self._log_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
            "logs"
        )
        os.makedirs(self._log_dir, exist_ok=True)

        # Register shutdown handlers
        atexit.register(self._on_shutdown)
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info("📊 SessionDiagnostics initialized")

    def record_api_call(
        self,
        method: str,
        endpoint: str,
        latency_ms: float,
        success: bool,
        error: Optional[str] = None,
        status_code: int = 200
    ):
        """Record an API call with timing."""
        with self._lock:
            record = APICallRecord(
                timestamp=datetime.now(),
                method=method,
                endpoint=endpoint,
                latency_ms=latency_ms,
                success=success,
                error=error,
                status_code=status_code
            )

            # Circular buffer
            if len(self._api_calls) >= self.MAX_RECORDS:
                self._api_calls.pop(0)
            self._api_calls.append(record)

            # Update aggregated stats
            stats = self._endpoint_stats[endpoint]
            stats["count"] += 1
            stats["total_ms"] += latency_ms
            stats["min_ms"] = min(stats["min_ms"], latency_ms)
            stats["max_ms"] = max(stats["max_ms"], latency_ms)
            if not success:
                stats["errors"] += 1

    def record_error(self, category: str, message: str, context: Dict = None):
        """Record an error."""
        with self._lock:
            record = ErrorRecord(
                timestamp=datetime.now(),
                category=category,
                message=message,
                context=context or {}
            )

            if len(self._errors) >= self.MAX_RECORDS:
                self._errors.pop(0)
            self._errors.append(record)

            self._error_counts[category] += 1

    def record_ws_event(self, event_type: str, details: Dict = None):
        """Record WebSocket event."""
        with self._lock:
            if len(self._ws_events) >= 1000:
                self._ws_events.pop(0)
            self._ws_events.append({
                "timestamp": datetime.now().isoformat(),
                "type": event_type,
                "details": details or {}
            })

    def record_trading_op(self, operation: str, symbol: str, result: str, details: Dict = None):
        """Record trading operation."""
        with self._lock:
            if len(self._trading_ops) >= 1000:
                self._trading_ops.pop(0)
            self._trading_ops.append({
                "timestamp": datetime.now().isoformat(),
                "operation": operation,
                "symbol": symbol,
                "result": result,
                "details": details or {}
            })

    def generate_report(self) -> str:
        """Generate comprehensive diagnostic report."""
        with self._lock:
            end_time = datetime.now()
            duration = end_time - self._start_time

            lines = [
                f"# Session Diagnostics Report",
                f"",
                f"**Generated**: {end_time.strftime('%Y-%m-%d %H:%M:%S')}",
                f"**Session Duration**: {duration}",
                f"**Start Time**: {self._start_time.strftime('%Y-%m-%d %H:%M:%S')}",
                f"",
                f"---",
                f"",
                f"## Summary",
                f"",
                f"| Metric | Value |",
                f"|--------|-------|",
                f"| Total API Calls | {len(self._api_calls)} |",
                f"| Total Errors | {len(self._errors)} |",
                f"| WebSocket Events | {len(self._ws_events)} |",
                f"| Trading Operations | {len(self._trading_ops)} |",
                f"",
            ]

            # Error Summary
            if self._error_counts:
                lines.extend([
                    f"## Error Summary",
                    f"",
                    f"| Category | Count |",
                    f"|----------|-------|",
                ])
                for cat, count in sorted(self._error_counts.items(), key=lambda x: -x[1]):
                    lines.append(f"| {cat} | {count} |")
                lines.append("")

            # Endpoint Performance
            if self._endpoint_stats:
                lines.extend([
                    f"## API Endpoint Performance",
                    f"",
                    f"| Endpoint | Calls | Avg (ms) | Min | Max | Errors |",
                    f"|----------|-------|----------|-----|-----|--------|",
                ])

                for endpoint, stats in sorted(self._endpoint_stats.items(), key=lambda x: -x[1]["count"]):
                    avg_ms = stats["total_ms"] / stats["count"] if stats["count"] > 0 else 0
                    min_ms = stats["min_ms"] if stats["min_ms"] != float('inf') else 0
                    lines.append(
                        f"| {endpoint[:40]} | {stats['count']} | {avg_ms:.0f} | {min_ms:.0f} | {stats['max_ms']:.0f} | {stats['errors']} |"
                    )
                lines.append("")

            # Recent Errors (last 20)
            if self._errors:
                lines.extend([
                    f"## Recent Errors (Last 20)",
                    f"",
                    f"```",
                ])
                for err in self._errors[-20:]:
                    lines.append(f"[{err.timestamp.strftime('%H:%M:%S')}] [{err.category}] {err.message}")
                    if err.context:
                        lines.append(f"    Context: {json.dumps(err.context)}")
                lines.extend(["```", ""])

            # WebSocket Events (reconnects, disconnects)
            ws_reconnects = [e for e in self._ws_events if "reconnect" in e.get("type", "").lower()]
            if ws_reconnects:
                lines.extend([
                    f"## WebSocket Reconnects ({len(ws_reconnects)})",
                    f"",
                    f"```",
                ])
                for event in ws_reconnects[-10:]:
                    lines.append(f"[{event['timestamp']}] {event['type']}: {event.get('details', {})}")
                lines.extend(["```", ""])

            # Trading Operations (recent)
            if self._trading_ops:
                lines.extend([
                    f"## Recent Trading Operations (Last 20)",
                    f"",
                    f"| Time | Operation | Symbol | Result |",
                    f"|------|-----------|--------|--------|",
                ])
                for op in self._trading_ops[-20:]:
                    time_str = op["timestamp"].split("T")[1][:8] if "T" in op["timestamp"] else op["timestamp"]
                    lines.append(f"| {time_str} | {op['operation']} | {op['symbol']} | {op['result']} |")
                lines.append("")

            # Slowest Endpoints
            slow_calls = sorted(self._api_calls, key=lambda x: -x.latency_ms)[:10]
            if slow_calls:
                lines.extend([
                    f"## Slowest API Calls",
                    f"",
                    f"| Time | Endpoint | Latency (ms) | Status |",
                    f"|------|----------|--------------|--------|",
                ])
                for call in slow_calls:
                    status = "✅" if call.success else "❌"
                    time_str = call.timestamp.strftime('%H:%M:%S')
                    lines.append(f"| {time_str} | {call.endpoint[:30]} | {call.latency_ms:.0f} | {status} |")
                lines.append("")

            return "\n".join(lines)

    def save_report(self) -> str:
        """Save report to file and return path."""
        report = self.generate_report()
        filename = f"session_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        filepath = os.path.join(self._log_dir, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(report)

        logger.info(f"📄 Session report saved: {filepath}")
        return filepath

    def _on_shutdown(self):
        """Called on graceful shutdown."""
        try:
            filepath = self.save_report()
            print(f"\n📊 Session diagnostics saved to: {filepath}")
        except Exception as e:
            logger.error(f"Failed to save session report: {e}")

    def _signal_handler(self, signum, frame):
        """Handle Ctrl+C signal."""
        print("\n🛑 Shutdown signal received...")
        self._on_shutdown()
        # Re-raise to allow default handler
        signal.default_int_handler(signum, frame)

    def get_stats(self) -> Dict:
        """Get current stats for API exposure."""
        with self._lock:
            return {
                "session_start": self._start_time.isoformat(),
                "total_api_calls": len(self._api_calls),
                "total_errors": len(self._errors),
                "error_counts": dict(self._error_counts),
                "ws_events": len(self._ws_events),
                "trading_ops": len(self._trading_ops)
            }


# Singleton
_diagnostics_instance: Optional[SessionDiagnostics] = None


def get_session_diagnostics() -> SessionDiagnostics:
    """Get or create the singleton diagnostics instance."""
    global _diagnostics_instance
    if _diagnostics_instance is None:
        _diagnostics_instance = SessionDiagnostics()
    return _diagnostics_instance
