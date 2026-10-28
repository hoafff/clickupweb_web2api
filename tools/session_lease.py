"""Exclusive, process-local owner lease for ONE authenticated browser UI context.

This deliberately does not create a new ClickUp conversation or support multiple
independent clients. A lease can be claimed ONCE per process lifetime and is not
re-claimable until the entire browser worker restarts after operator inspection.

Do not use this mechanism to substitute for identity/authz when hosting remotely.
"""
from __future__ import annotations

from secrets import token_urlsafe
from threading import Lock
import hmac


class SessionAlreadyClaimedError(Exception):
    """Only one logical owner can hold the browser's conversation context."""


class SessionNotClaimedError(Exception):
    """No owner has been assigned to this browser worker."""


class SessionAccessDeniedError(Exception):
    """The owner token is absent, malformed or incorrect."""


class ExclusiveSessionLease:
    """One process-lifetime bearer capability, returned once, never logged."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._owner_secret: str | None = None

    def claim(self) -> str:
        """Return a new secret exactly once. No release/reclaim without restart."""
        with self._lock:
            if self._owner_secret is not None:
                raise SessionAlreadyClaimedError()
            value = token_urlsafe(32)
            self._owner_secret = value
            return value

    def check(self, candidate: str | None) -> None:
        with self._lock:
            secret = self._owner_secret
        if secret is None:
            raise SessionNotClaimedError()
        if (
            not candidate
            or len(candidate) > 256
            or not hmac.compare_digest(candidate, secret)
        ):
            raise SessionAccessDeniedError()

    def has_owner(self) -> bool:
        with self._lock:
            return self._owner_secret is not None
