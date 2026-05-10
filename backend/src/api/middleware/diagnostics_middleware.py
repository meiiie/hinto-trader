"""
Diagnostics Middleware - Auto-instrument all API calls.

SOTA: Automatic request/response timing without modifying each endpoint.
"""

import time
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.infrastructure.diagnostics.session_diagnostics import get_session_diagnostics

logger = logging.getLogger(__name__)


class DiagnosticsMiddleware(BaseHTTPMiddleware):
    """
    Middleware to automatically record all API calls.

    Records:
    - Request method and path
    - Response status code
    - Latency in milliseconds
    - Any errors
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.perf_counter()

        # Skip WebSocket and health checks for cleaner logs
        path = request.url.path
        if path.startswith("/ws") or path == "/health" or path == "/":
            return await call_next(request)

        try:
            response = await call_next(request)
            latency_ms = (time.perf_counter() - start_time) * 1000

            diagnostics = get_session_diagnostics()
            diagnostics.record_api_call(
                method=request.method,
                endpoint=path,
                latency_ms=latency_ms,
                success=(200 <= response.status_code < 400),
                status_code=response.status_code
            )

            # Log slow requests (>500ms)
            if latency_ms > 500:
                logger.warning(f"🐌 Slow API: {request.method} {path} took {latency_ms:.0f}ms")

            return response

        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000

            diagnostics = get_session_diagnostics()
            diagnostics.record_api_call(
                method=request.method,
                endpoint=path,
                latency_ms=latency_ms,
                success=False,
                error=str(e),
                status_code=500
            )
            diagnostics.record_error(
                category="API_EXCEPTION",
                message=str(e),
                context={"method": request.method, "path": path}
            )

            raise
