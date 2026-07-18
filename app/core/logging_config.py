"""
Structured logging — every log line includes a request ID so you can
trace a single request's full path through the AI Gateway, FIE, and DB
layer in production logs, instead of unlabeled lines that are impossible
to correlate under real concurrent traffic.

This is intentionally plain Python `logging` + a FastAPI middleware, not
a hosted observability SaaS integration — Sentry (already installed,
see API_REQUIREMENTS.md §9) covers error tracking; this covers the
"what actually happened, in order" side that Sentry alone doesn't.
"""
import logging
import time
import uuid
from contextvars import ContextVar

from fastapi import Request

_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_ctx.get()
        return True


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] [req=%(request_id)s] %(name)s: %(message)s")
    )
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]

    # Quiet down noisy third-party loggers so app-level logs aren't buried.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


async def request_logging_middleware(request: Request, call_next):
    """
    Assigns a request ID, logs entry/exit with timing, and makes the ID
    available to every log line emitted during this request via the
    contextvar above -- register this in app/main.py with
    app.middleware("http")(request_logging_middleware).
    """
    request_id = str(uuid.uuid4())[:8]
    token = _request_id_ctx.set(request_id)
    logger = logging.getLogger("paisaera.request")

    start = time.monotonic()
    logger.info(f"-> {request.method} {request.url.path}")
    try:
        response = await call_next(request)
        duration_ms = (time.monotonic() - start) * 1000
        logger.info(f"<- {request.method} {request.url.path} {response.status_code} ({duration_ms:.0f}ms)")
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception:
        duration_ms = (time.monotonic() - start) * 1000
        logger.exception(f"<- {request.method} {request.url.path} FAILED ({duration_ms:.0f}ms)")
        raise
    finally:
        _request_id_ctx.reset(token)
