"""
Execution Infrastructure Module

SOTA Priority Execution Queue Architecture (Jan 2026)
Pattern: NautilusTrader, Two Sigma, Citadel

Components:
- PriorityExecutionQueue: asyncio.PriorityQueue with duplicate detection
- ExecutionWorker: Background coroutine for sequential order processing
"""

from .priority_execution_queue import PriorityExecutionQueue
from .execution_worker import ExecutionWorker

__all__ = ['PriorityExecutionQueue', 'ExecutionWorker']
