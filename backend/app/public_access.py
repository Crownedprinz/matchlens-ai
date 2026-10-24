"""Fail-closed public Foundry access gate."""
from __future__ import annotations

import hmac
import os


class PublicAccessError(RuntimeError):
    status_code = 403


class PublicAccessDisabled(PublicAccessError):
    pass


class PublicAccessInvalid(PublicAccessError):
    pass


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
