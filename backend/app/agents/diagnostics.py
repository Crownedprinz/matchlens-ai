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


def exception_chain(exc: BaseException):
    """Yield an exception and its nested causes without following cycles."""
    seen: set[int] = set()
    pending: list[object] = [exc]
    while pending:
        candidate = pending.pop(0)
        if not isinstance(candidate, BaseException) or id(candidate) in seen:
            continue
        seen.add(id(candidate))
        yield candidate
        pending.extend(
            [
                getattr(candidate, "inner_exception", None),
                candidate.__cause__,
                candidate.__context__,
                *candidate.args,
            ]
        )


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
    chain = list(exception_chain(exc))
    detail_candidates = list(reversed(chain))

    def response_for(candidate: BaseException):
        return getattr(candidate, "response", None)

    def status_for(candidate: BaseException):
        response = response_for(candidate)
        value = getattr(candidate, "status_code", None) or getattr(response, "status_code", None)
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def response_body_for(candidate: BaseException):
        response = response_for(candidate)
        body = getattr(candidate, "body", None)
        if isinstance(body, dict):
            return body
        json_method = getattr(response, "json", None)
        if callable(json_method):
            try:
                body = json_method()
            except Exception:
                body = None
            if isinstance(body, dict):
                return body
        return None

    def error_body_for(candidate: BaseException):
        body = response_body_for(candidate)
        error = body.get("error") if isinstance(body, dict) else None
        return error if isinstance(error, dict) else body if isinstance(body, dict) else None

    def code_for(candidate: BaseException):
        value = getattr(candidate, "code", None) or getattr(candidate, "error_code", None)
        body_error = error_body_for(candidate)
        value = value or body_error.get("code") if body_error else value
        value = value or body_error.get("type") if body_error else value
        return safe_field(value)

    def safe_field(value: Any):
        if not isinstance(value, str) or not 1 <= len(value) <= 160:
            return None
        return value if re.fullmatch(r"[A-Za-z0-9._:/-]+", value) else None

    def safe_details_for(candidate: BaseException):
        error = error_body_for(candidate)
        if not error:
            return None
        details: dict[str, Any] = {}
        for source_key, output_key in (("type", "type"), ("target", "target"), ("param", "param")):
            value = safe_field(error.get(source_key))
            if value:
                details[output_key] = value
        nested = error.get("details")
        if isinstance(nested, list):
            safe_nested = []
            for item in nested[:8]:
                if not isinstance(item, dict):
                    continue
                safe_item = {
                    key: value
                    for key in ("code", "type", "target")
                    if (value := safe_field(item.get(key)))
                }
                if safe_item:
                    safe_nested.append(safe_item)
            if safe_nested:
                details["details"] = safe_nested
        return details or None

    def request_id_for(candidate: BaseException):
        response = response_for(candidate)
        headers = getattr(response, "headers", None) or getattr(candidate, "headers", None) or {}
        try:
            header_values = {str(key).lower(): value for key, value in headers.items()}
        except AttributeError:
            header_values = {}
        for header_name in ("x-ms-request-id", "x-request-id", "request-id", "traceparent"):
            safe_value = safe_field(header_values.get(header_name))
            if safe_value:
                return safe_value
        return safe_field(getattr(candidate, "request_id", None))

    root = detail_candidates[-1] if detail_candidates else exc
    for candidate in detail_candidates:
        if status_for(candidate) is not None or code_for(candidate) or request_id_for(candidate):
            root = candidate
            break

    status_code = next((value for candidate in detail_candidates if (value := status_for(candidate)) is not None), None)
    error_code = next((value for candidate in detail_candidates if (value := code_for(candidate))), None)
    request_id = next((value for candidate in detail_candidates if (value := request_id_for(candidate))), None)
    service_details = next((value for candidate in detail_candidates if (value := safe_details_for(candidate))), None)
    return {
        "outer_exception_type": type(exc).__name__,
        "root_exception_type": type(root).__name__,
        "http_status": status_code,
        "error_code": error_code,
        "request_id": request_id,
        "service_details": service_details,
    }


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
