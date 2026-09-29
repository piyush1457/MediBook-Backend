"""Structured JSON logging + request-id middleware. Never logs secrets."""

import json
import logging
import sys
import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

_configured = False


def setup_logging(level: str = "INFO") -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    _configured = True


def log_event(logger: logging.Logger, event: str, **fields: object) -> None:
    safe = {
        k: v
        for k, v in fields.items()
        if k not in {"password", "token", "secret", "hashed_password"}
    }
    logger.info(json.dumps({"event": event, **{k: str(v) for k, v in safe.items()}}))


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("X-Request-Id", uuid.uuid4().hex[:12])
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        logger = logging.getLogger("app.requests")
        logger.info(
            json.dumps(
                {
                    "event": "request",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                }
            )
        )
        return response
