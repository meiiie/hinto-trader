
import time
import os
import logging
import asyncio
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)

class RequestProfilerMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, enabled: bool = False, slow_threshold_ms: int = 500):
        super().__init__(app)
        self.enabled = enabled
        self.slow_threshold_ms = slow_threshold_ms
        self._output_dir = "logs/profiles"

        if self.enabled:
            os.makedirs(self._output_dir, exist_ok=True)
            # Try importing pyinstrument
            try:
                from pyinstrument import Profiler
                self.Profiler = Profiler
                logger.info("✅ Request Profiler Enabled (pyinstrument)")
            except ImportError:
                logger.warning("⚠️ PROFILER ERROR: 'pyinstrument' not installed. pip install pyinstrument")
                self.enabled = False

    async def dispatch(self, request: Request, call_next):
        if not self.enabled:
            return await call_next(request)

        # Skip profiling for static files or trivial endpoints
        if request.url.path in ["/health", "/docs", "/openapi.json"]:
            return await call_next(request)

        from pyinstrument import Profiler
        profiler = Profiler(interval=0.001, async_mode="enabled")
        profiler.start()

        start_time = time.perf_counter()
        try:
            response = await call_next(request)
            return response
        finally:
            end_time = time.perf_counter()
            duration_ms = (end_time - start_time) * 1000

            profiler.stop()

            # Log all requests
            logger.info(f"⏱️ {request.method} {request.url.path}: {duration_ms:.2f}ms")

            # Dump profile if slow
            if duration_ms > self.slow_threshold_ms:
                try:
                    timestamp = int(time.time())
                    safe_path = request.url.path.replace('/', '_')
                    filename = f"{self._output_dir}/slow_{timestamp}_{safe_path}.html"

                    # Offload file writing
                    html_report = profiler.output_html()
                    with open(filename, "w", encoding="utf-8") as f:
                        f.write(html_report)

                    logger.warning(f"🐢 SLOW REQUEST DETECTED: {duration_ms:.2f}ms. Profile saved to {filename}")
                except Exception as e:
                    logger.error(f"Failed to save profile: {e}")
