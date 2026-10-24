"""Safe structured diagnostics for Foundry request boundaries."""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from contextvars import ContextVar
from typing import Any
from urllib.parse import urlsplit

_correlation_id: ContextVar[str | None] = ContextVar("matchlens_correlation_id", default=None)
_started_at: ContextVar[float | None] = ContextVar("matchlens_started_at", default=None)
logger = logging.getLogger("matchlens.foundry")


def foundry_request_route(endpoint: str) -> dict[str, Any]:
    """Describe the SDK route without logging credentials or request payloads.

    ``FoundryAgent`` 1.15 uses the GA project Responses API unless
    ``allow_preview=True`` is explicitly enabled. The application intentionally
    uses that default so the explicit version is carried in ``agent_reference``.
    """
    parsed = urlsplit(endpoint)
    path = parsed.path.rstrip("/") + "/openai/v1/responses"
    return {
        "request_route": "project_responses",
        "request_path": path,
        "endpoint_host": parsed.hostname,
        "agent_reference_in_body": True,
        "allow_preview": False,
    }


def safe_remote_error_metadata(exc: BaseException) -> dict[str, Any]:
    """Extract bounded, non-secret HTTP metadata from an SDK exception."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or getattr(exc, "headers", None) or {}

    status_code = getattr(exc, "status_code", None) or getattr(response, "status_code", None)
    if isinstance(status_code, bool) or not isinstance(status_code, (int, str)):
        status_code = None
    if status_code is not None:
        try:
            status_code = int(status_code)
        except (TypeError, ValueError):
            status_code = None

    request_id = None
    for header_name in ("x-ms-request-id", "x-request-id", "request-id", "traceparent"):
        try:
            value = headers.get(header_name)
        except AttributeError:
            value = None
        if value:
            request_id = str(value)[:160]
            break

    error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        body_error = body.get("error", body)
        if isinstance(body_error, dict):
            error_code = error_code or body_error.get("code") or body_error.get("type")

    metadata: dict[str, Any] = {
        "exception_type": type(exc).__name__,
        "http_status": status_code,
        "error_code": str(error_code)[:160] if error_code else None,
        "request_id": request_id,
    }
    # Keep a short service diagnostic when the SDK exposes one, while removing
    # bearer tokens and URLs that could contain query credentials.
    message = getattr(exc, "message", None)
    if isinstance(message, str) and message:
        message = re.sub(r"(?i)bearer\s+\S+", "Bearer <redacted>", message)
        message = re.sub(r"https?://\S+", "<url>", message)
        metadata["service_message"] = message[:300]
    return metadata


def start_request(correlation_id: str | None = None) -> str:
    value = correlation_id or str(uuid.uuid4())
    _correlation_id.set(value)
    _started_at.set(time.perf_counter())
    return value


def correlation_id() -> str | None:
    return _correlation_id.get()


def elapsed_ms() -> int | None:
    started = _started_at.get()
    return None if started is None else round((time.perf_counter() - started) * 1000)


def event(name: str, **fields: Any) -> None:
    """Emit JSON-safe metadata only; never include payloads or credentials."""
    record = {"event": name, "correlation_id": correlation_id(), "elapsed_ms": elapsed_ms(), **fields}
    logger.info(json.dumps(record, separators=(",", ":"), default=str))
