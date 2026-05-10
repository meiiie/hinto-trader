"""
Workers package for CPU-intensive operations.

Contains ThreadPoolExecutor-based workers that offload heavy calculations
from the main asyncio Event Loop.
"""

from .indicator_worker import (
    calculate_indicators_async,
    shutdown_workers
)

__all__ = [
    'calculate_indicators_async',
    'shutdown_workers'
]
