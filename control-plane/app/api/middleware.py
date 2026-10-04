"""Per-request context: request ID, timing and one structured log line per request."""

import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

from app.core.logging import request_id_var, tenant_id_var, user_id_var

logger = logging.getLogger("app.request")

REQUEST_ID_HEADER = "X-Request-ID"
# Accept a caller-supplied ID only if it is short and safe to log.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


async def request_context(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    incoming = request.headers.get(REQUEST_ID_HEADER, "")
    request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
    tokens = (
        request_id_var.set(request_id),
        tenant_id_var.set(None),
        user_id_var.set(None),
    )
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
    finally:
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        level = logging.ERROR if status_code >= 500 else logging.INFO
        logger.log(
            level,
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": status_code,
                "duration_ms": duration_ms,
            },
        )
        request_id_var.reset(tokens[0])
        tenant_id_var.reset(tokens[1])
        user_id_var.reset(tokens[2])