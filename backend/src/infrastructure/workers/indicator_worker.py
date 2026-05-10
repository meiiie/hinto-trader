"""
SOTA Indicator Worker - ThreadPoolExecutor for CPU-bound indicator calculations.

Pattern: Offload heavy Pandas/TA-Lib work from asyncio Event Loop.
Reference: Two Sigma, Citadel architecture patterns (Jan 2026).

Why ThreadPoolExecutor (not ProcessPoolExecutor)?
- TA-Lib is C-based and releases GIL during computation
- No IPC overhead (shared memory)
- Instant startup (no pickling)
- Suitable for I/O + NumPy/C code mix
"""

import asyncio
import concurrent.futures
import logging
from typing import Dict, List, Any, Optional
import pandas as pd

logger = logging.getLogger(__name__)

# Global ThreadPool - reused across all calls
# 4 workers is optimal for 50 symbols (balances parallelism vs context switching)
_executor: Optional[concurrent.futures.ThreadPoolExecutor] = None


def _get_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Lazy initialization of ThreadPoolExecutor."""
    global _executor
    if _executor is None:
        _executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="IndicatorWorker"
        )
        logger.info("🚀 IndicatorWorker ThreadPool initialized (4 workers)")
    return _executor


def calculate_indicators_sync(
    candles_data: Dict[str, List],
    talib_calculator: Any
) -> Dict[str, Any]:
    """
    CPU-heavy work - runs in ThreadPool worker.

    CRITICAL: This function runs in a SEPARATE THREAD.
    - Do NOT access asyncio objects
    - Do NOT modify shared state without locks
    - Only work with data passed as arguments

    Args:
        candles_data: Dict with 'open', 'high', 'low', 'close', 'volume' lists
        talib_calculator: TALib calculator instance (stateless, thread-safe)

    Returns:
        Dict with calculated indicator values
    """
    try:
        # Build DataFrame from raw data
        df = pd.DataFrame({
            'open': candles_data['open'],
            'high': candles_data['high'],
            'low': candles_data['low'],
            'close': candles_data['close'],
            'volume': candles_data['volume']
        })

        if df.empty or len(df) < 20:
            return {}

        results = {}

        # TALib calculations (EMA, RSI, etc.)
        if talib_calculator:
            try:
                talib_result = talib_calculator.calculate_all(df)
                if not talib_result.empty:
                    latest = talib_result.iloc[-1].to_dict()
                    # Clean NaN values
                    results = {k: (v if pd.notna(v) else 0.0) for k, v in latest.items()}
            except Exception as e:
                logger.error(f"TALib calc failed: {e}")

        return results

    except Exception as e:
        logger.error(f"Indicator calculation failed: {e}")
        return {}


async def calculate_indicators_async(
    candles: List[Any],
    talib_calculator: Any
) -> Dict[str, Any]:
    """
    Non-blocking wrapper - offloads calculation to ThreadPool.

    This is the main API to call from async code.

    Args:
        candles: List of Candle objects
        talib_calculator: TALib calculator instance

    Returns:
        Dict with indicator values (latest values)
    """
    if not candles or len(candles) < 20:
        return {}

    # Convert Candle objects to serializable data (avoids pickling issues)
    candles_data = {
        'open': [c.open for c in candles],
        'high': [c.high for c in candles],
        'low': [c.low for c in candles],
        'close': [c.close for c in candles],
        'volume': [c.volume for c in candles]
    }

    loop = asyncio.get_event_loop()
    executor = _get_executor()

    # Run in ThreadPool (non-blocking for Event Loop)
    result = await loop.run_in_executor(
        executor,
        calculate_indicators_sync,
        candles_data,
        talib_calculator
    )

    return result


async def calculate_batch_indicators_async(
    symbols_candles: Dict[str, List[Any]],
    talib_calculator: Any
) -> Dict[str, Dict[str, Any]]:
    """
    Calculate indicators for multiple symbols in parallel.

    Args:
        symbols_candles: Dict mapping symbol -> candle list
        talib_calculator: TALib calculator instance

    Returns:
        Dict mapping symbol -> indicator values
    """
    tasks = {}
    for symbol, candles in symbols_candles.items():
        tasks[symbol] = calculate_indicators_async(candles, talib_calculator)

    # Run all in parallel
    results = {}
    symbol_list = list(tasks.keys())
    task_list = list(tasks.values())

    completed = await asyncio.gather(*task_list, return_exceptions=True)

    for symbol, result in zip(symbol_list, completed):
        if isinstance(result, Exception):
            logger.error(f"Indicator calc failed for {symbol}: {result}")
            results[symbol] = {}
        else:
            results[symbol] = result

    return results


def shutdown_workers():
    """Gracefully shutdown the ThreadPool."""
    global _executor
    if _executor:
        logger.info("🛑 Shutting down IndicatorWorker ThreadPool...")
        _executor.shutdown(wait=True)
        _executor = None
        logger.info("✅ IndicatorWorker ThreadPool shutdown complete")
