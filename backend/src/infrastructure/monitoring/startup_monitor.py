import asyncio
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class StartupConfig:
    total_steps: int = 100
    current_step: int = 0
    current_message: str = "Initializing..."
    start_time: Optional[datetime] = None

class StartupMonitor:
    """
    SOTA Startup Monitor (Singleton)

    Purpose:
    - Tracks backend initialization progress
    - Broadcasts real-time events to Frontend (SSE)
    - Provides "Discord-style" loading experience
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(StartupMonitor, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self.config = StartupConfig()
        self.config.start_time = datetime.now()

        # Event subscribers (asyncio.Queue for each connected client)
        self.subscribers: List[asyncio.Queue] = []

        # History of events (for late joiners)
        self.event_history: List[Dict[str, Any]] = []

        logger.info("🚀 StartupMonitor initialized")

    async def subscribe(self) -> asyncio.Queue:
        """New client connects to SSE stream"""
        queue = asyncio.Queue()

        # Replay history for late joiners
        for event in self.event_history:
            await queue.put(event)

        self.subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue):
        if queue in self.subscribers:
            self.subscribers.remove(queue)

    async def emit_progress(self, step: int, total: int, message: str, level: str = "info"):
        """
        Emit a progress event.

        Args:
            step: Current step number
            total: Total expected steps
            message: Human-readable status
            level: 'info', 'success', 'warning', 'error'
        """
        # Calculate percentage
        percent = min(100, int((step / total) * 100))

        self.config.current_step = step
        self.config.total_steps = total
        self.config.current_message = message

        event_data = {
            "type": "progress",
            "timestamp": datetime.now().isoformat(),
            "data": {
                "percent": percent,
                "step": step,
                "total": total,
                "message": message,
                "level": level
            }
        }

        # Store in history
        self.event_history.append(event_data)

        # Broadcast to all subscribers
        # We use create_task to avoid blocking the caller
        for queue in self.subscribers:
            try:
                queue.put_nowait(event_data)
            except asyncio.QueueFull:
                pass # Should not happen with unbounded queue

    async def emit_log(self, message: str):
        """Emit a detailed log message (side-channel)"""
        event_data = {
            "type": "log",
            "timestamp": datetime.now().isoformat(),
            "data": {
                "message": message
            }
        }
        # Logs don't need history replay, only live
        for queue in self.subscribers:
             try:
                queue.put_nowait(event_data)
             except:
                 pass

# Global Accessor
_monitor = StartupMonitor()

def get_startup_monitor() -> StartupMonitor:
    return _monitor
