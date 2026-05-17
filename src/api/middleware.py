"""PHI-free logging middleware for clinicvoice.

Logs only metadata: method, path, status_code, duration_ms, request_id.
NEVER logs request body, query parameters, header values, or response body.
Adds an ``X-Request-ID`` header to every response so traces can be correlated
across services without exposing patient data.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("clinicvoice.api")


class PHIFreeLoggingMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that emits PHI-free request logs.

    Per the clinicvoice rules in CLAUDE.md, logs may contain only hashed
    IDs, durations, speaker counts, and status codes. This middleware enforces
    that contract for the API edge.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # Honor an inbound request id if present; otherwise mint one.
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = request_id

        start = time.perf_counter()
        status_code = 500
        response: Response | None = None
        try:
            response = await call_next(request)
            status_code = response.status_code
            # Mirror the request id on the response for client-side correlation.
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000.0, 2)
            # IMPORTANT: never include body, query, or header values here.
            logger.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": status_code,
                    "duration_ms": duration_ms,
                    "request_id": request_id,
                },
            )

    @staticmethod
    def attach_request_id_header(response: Response, request_id: str) -> None:
        """Helper used by route handlers to mirror the request id on responses."""
        if request_id:
            response.headers["X-Request-ID"] = request_id


async def _set_request_id_header(request: Request, call_next):  # pragma: no cover
    """Pure-function variant for ASGI stacks that prefer middleware factories."""
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


__all__ = ["PHIFreeLoggingMiddleware"]
