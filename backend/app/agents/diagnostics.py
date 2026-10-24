"""Safe structured diagnostics for Foundry request boundaries."""
from __future__ import annotations

import json
import logging
import time
import uuid
from contextvars import ContextVar
from typing import Any

_correlation_id: ContextVar[str | None] = ContextVar("matchlens_correlation_id", default=None)
_started_at: ContextVar[float | None] = ContextVar("matchlens_started_at", default=None)
logger = logging.getLogger("matchlens.foundry")


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
