"""Fail-closed public Foundry access gate."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hmac
import os
from threading import Lock
from typing import Iterator


class PublicAccessError(RuntimeError):
    status_code = 403


class PublicAccessDisabled(PublicAccessError):
    pass


class PublicAccessInvalid(PublicAccessError):
    pass


class FoundryProcessLimitExceeded(PublicAccessError):
    """A process-local Foundry budget or concurrency limit was reached."""

    status_code = 429


FOUNDRY_DAILY_ATTEMPT_LIMIT = 10
FOUNDRY_LIFETIME_ATTEMPT_LIMIT = 40


@dataclass
class _FoundryProcessState:
    lock: Lock = field(default_factory=Lock)
    utc_day: str = ""
    daily_attempts: int = 0
    lifetime_attempts: int = 0
    active_attempts: int = 0


_foundry_process_state = _FoundryProcessState()


def _utc_day() -> str:
    return datetime.now(timezone.utc).date().isoformat()


@contextmanager
def reserve_foundry_attempt() -> Iterator[tuple[int, int]]:
    """Reserve one live Foundry execution using atomic process-local counters.

    The attempt is counted before the caller invokes Foundry, so errors and
    timeouts consume the budget. The active slot is released on every exit.
    These limits intentionally reset with the process and are not a spending
    ceiling.
    """
    with _foundry_process_state.lock:
        today = _utc_day()
        if _foundry_process_state.utc_day != today:
            _foundry_process_state.utc_day = today
            _foundry_process_state.daily_attempts = 0
        if _foundry_process_state.daily_attempts >= FOUNDRY_DAILY_ATTEMPT_LIMIT:
            raise FoundryProcessLimitExceeded("The process-wide daily Foundry attempt limit has been reached.")
        if _foundry_process_state.lifetime_attempts >= FOUNDRY_LIFETIME_ATTEMPT_LIMIT:
            raise FoundryProcessLimitExceeded("The process-wide Foundry lifetime attempt limit has been reached.")
        if _foundry_process_state.active_attempts >= 1:
            raise FoundryProcessLimitExceeded("A Foundry execution is already active; try again shortly.")
        _foundry_process_state.daily_attempts += 1
        _foundry_process_state.lifetime_attempts += 1
        _foundry_process_state.active_attempts += 1
        usage = (_foundry_process_state.daily_attempts, _foundry_process_state.lifetime_attempts)
    try:
        yield usage
    finally:
        with _foundry_process_state.lock:
            _foundry_process_state.active_attempts -= 1


def _reset_foundry_process_limits_for_tests() -> None:
    """Reset process-local state for isolated offline tests only."""
    with _foundry_process_state.lock:
        _foundry_process_state.utc_day = _utc_day()
        _foundry_process_state.daily_attempts = 0
        _foundry_process_state.lifetime_attempts = 0
        _foundry_process_state.active_attempts = 0


def verify_access_guid(value: str | None) -> None:
    """Verify the public opt-in code without logging or exposing it."""
    if os.getenv("FOUNDRY_PUBLIC_ENABLED", "false").lower() != "true":
        raise PublicAccessDisabled("Microsoft Foundry Live is disabled for this deployment.")
    expected = os.getenv("FOUNDRY_PUBLIC_ACCESS_GUID", "")
    if not expected or not value or not hmac.compare_digest(value, expected):
        raise PublicAccessInvalid("The Foundry access code is invalid.")


def supported_public_match(match_id: str) -> bool:
    allowed = {item.strip() for item in os.getenv("FOUNDRY_PUBLIC_MATCH_IDS", "match-001").split(",") if item.strip()}
    return match_id in allowed
