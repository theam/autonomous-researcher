"""Stable domain errors shared by the CLI and HTTP API."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LiminaError(Exception):
    message: str
    code: str = "limina_error"
    details: dict[str, Any] = field(default_factory=dict)
    exit_code: int = 1
    http_status: int = 400

    def __str__(self) -> str:
        return self.message


class NotFoundError(LiminaError):
    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message, "not_found", details, 3, 404)


class ConflictError(LiminaError):
    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message, "version_conflict", details, 4, 409)


class InvariantError(LiminaError):
    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message, "invariant_violation", details, 5, 422)


class LeaseConflictError(LiminaError):
    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message, "lease_conflict", details, 6, 409)


class AuthenticationError(LiminaError):
    def __init__(self, message: str = "Authentication required.") -> None:
        super().__init__(message, "authentication_required", {}, 7, 401)


class AuthorizationError(LiminaError):
    def __init__(
        self, message: str = "You do not have access to this project.", **details: Any
    ) -> None:
        super().__init__(message, "permission_denied", details, 7, 403)


class RateLimitError(LiminaError):
    def __init__(self, *, retry_after_seconds: int) -> None:
        super().__init__(
            "Too many failed authentication attempts.",
            "rate_limited",
            {"retry_after_seconds": retry_after_seconds},
            9,
            429,
        )


class TransportError(LiminaError):
    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message, "transport_error", details, 8, 503)
