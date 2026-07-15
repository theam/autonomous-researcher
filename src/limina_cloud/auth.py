"""Provider-neutral authentication principals for REST, WebSocket, and MCP."""

from __future__ import annotations

import os
from dataclasses import dataclass
from secrets import compare_digest
from typing import Any, Protocol

import httpx
import jwt

from .errors import AuthenticationError
from .rate_limit import FailureRateLimiter


def _tokens_equal(left: str, right: str) -> bool:
    """Compare arbitrary Unicode credentials without letting malformed input raise."""

    return compare_digest(left.encode("utf-8"), right.encode("utf-8"))


@dataclass(frozen=True)
class Principal:
    subject: str
    display_name: str
    email: str | None = None
    instance_admin: bool = False
    project_admin: bool = False
    auth_mode: str = "oidc"

    @property
    def actor(self) -> str:
        return self.display_name[:200]

    @classmethod
    def local(
        cls,
        actor: str = "local-admin",
        *,
        instance_admin: bool = False,
    ) -> Principal:
        name = actor.strip() or "local-admin"
        return cls(
            subject=f"local:{name}",
            display_name=name,
            instance_admin=instance_admin,
            project_admin=True,
            auth_mode="local",
        )


class Authenticator(Protocol):
    mode: str

    def authenticate(
        self, bearer_token: str | None, *, actor_hint: str | None = None
    ) -> Principal: ...


class RateLimitedAuthenticator:
    """Transport-neutral brute-force guard used by REST, WebSocket, and MCP."""

    def __init__(self, wrapped: Authenticator, limiter: FailureRateLimiter) -> None:
        self.wrapped = wrapped
        self.limiter = limiter
        self.mode = wrapped.mode

    def authenticate(self, bearer_token: str | None, *, actor_hint: str | None = None) -> Principal:
        self.limiter.check("all-transports")
        try:
            return self.wrapped.authenticate(bearer_token, actor_hint=actor_hint)
        except AuthenticationError:
            self.limiter.failure("all-transports")
            raise


class LocalAuthenticator:
    """Shared-token authentication for a trusted local development instance."""

    mode = "local"

    def __init__(self, token: str | None, admin_token: str | None = None) -> None:
        if token and admin_token and _tokens_equal(token, admin_token):
            raise RuntimeError("LIMINA_API_TOKEN and LIMINA_ADMIN_API_TOKEN must be different.")
        self.token = token
        self.admin_token = admin_token

    def authenticate(self, bearer_token: str | None, *, actor_hint: str | None = None) -> Principal:
        if self.admin_token and bearer_token and _tokens_equal(bearer_token, self.admin_token):
            return Principal.local(actor_hint or "local-admin", instance_admin=True)
        if self.token is not None:
            if bearer_token is None or not _tokens_equal(bearer_token, self.token):
                raise AuthenticationError()
            return Principal.local(actor_hint or "local-user")
        if self.admin_token is not None:
            raise AuthenticationError()
        return Principal.local(actor_hint or "local-admin", instance_admin=True)


class OidcAuthenticator:
    """Validate signed JWT access tokens using standard OIDC discovery and JWKS."""

    mode = "oidc"

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_url: str | None = None,
        algorithms: tuple[str, ...] = ("RS256",),
        admin_claim: str | None = None,
        admin_value: str = "admin",
        leeway_seconds: int = 30,
    ) -> None:
        self.issuer = issuer.rstrip("/")
        if not self.issuer.startswith("https://"):
            raise RuntimeError("LIMINA_OIDC_ISSUER must use HTTPS.")
        if not algorithms or any(item.lower() == "none" for item in algorithms):
            raise RuntimeError("LIMINA_OIDC_ALGORITHMS must contain signed JWT algorithms.")
        self.audience = audience
        self.algorithms = algorithms
        self.admin_claim = admin_claim
        self.admin_value = admin_value
        if not 0 <= leeway_seconds <= 300:
            raise RuntimeError("OIDC clock-skew leeway must be between 0 and 300 seconds.")
        self.leeway_seconds = leeway_seconds
        discovered_jwks = jwks_url or self._discover_jwks_url()
        if not discovered_jwks.startswith("https://"):
            raise RuntimeError("The OIDC JWKS endpoint must use HTTPS.")
        self.jwks_client = jwt.PyJWKClient(discovered_jwks, cache_keys=True)

    def _discover_jwks_url(self) -> str:
        discovery_url = f"{self.issuer}/.well-known/openid-configuration"
        try:
            response = httpx.get(discovery_url, timeout=10.0, follow_redirects=False)
            response.raise_for_status()
            metadata = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError(
                f"Cannot load OIDC discovery metadata from {discovery_url}."
            ) from exc
        if metadata.get("issuer") != self.issuer:
            raise RuntimeError("OIDC discovery issuer does not exactly match LIMINA_OIDC_ISSUER.")
        jwks_url = metadata.get("jwks_uri")
        if not isinstance(jwks_url, str) or not jwks_url.startswith("https://"):
            raise RuntimeError("OIDC discovery metadata must provide an HTTPS jwks_uri.")
        return jwks_url

    def authenticate(self, bearer_token: str | None, *, actor_hint: str | None = None) -> Principal:
        del actor_hint  # OIDC identity always comes from signed claims.
        if not bearer_token:
            raise AuthenticationError()
        try:
            signing_key = self.jwks_client.get_signing_key_from_jwt(bearer_token)
            claims = jwt.decode(
                bearer_token,
                signing_key.key,
                algorithms=list(self.algorithms),
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.leeway_seconds,
                options={"require": ["exp", "iat", "iss", "sub", "aud"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError("The bearer token is invalid or expired.") from exc
        subject = str(claims.get("sub", "")).strip()
        if not subject:
            raise AuthenticationError("The bearer token has no subject.")
        display_name = str(
            claims.get("name") or claims.get("preferred_username") or claims.get("email") or subject
        ).strip()
        email = str(claims["email"]).strip() if claims.get("email") else None
        return Principal(
            subject=subject,
            display_name=display_name,
            email=email,
            instance_admin=self._is_admin(claims),
        )

    def _is_admin(self, claims: dict[str, Any]) -> bool:
        if not self.admin_claim:
            return False
        value = claims.get(self.admin_claim)
        if isinstance(value, list):
            return self.admin_value in {str(item) for item in value}
        return str(value) == self.admin_value


def authenticator_from_environment(
    *, local_token: str | None = None, local_admin_token: str | None = None
) -> Authenticator:
    issuer = os.environ.get("LIMINA_OIDC_ISSUER", "").strip()
    audience = os.environ.get("LIMINA_OIDC_AUDIENCE", "").strip()
    if issuer or audience:
        if not issuer or not audience:
            raise RuntimeError("LIMINA_OIDC_ISSUER and LIMINA_OIDC_AUDIENCE must be set together.")
        algorithms = tuple(
            item.strip()
            for item in os.environ.get("LIMINA_OIDC_ALGORITHMS", "RS256").split(",")
            if item.strip()
        )
        return OidcAuthenticator(
            issuer=issuer,
            audience=audience,
            jwks_url=os.environ.get("LIMINA_OIDC_JWKS_URL") or None,
            algorithms=algorithms,
            admin_claim=os.environ.get("LIMINA_OIDC_ADMIN_CLAIM") or None,
            admin_value=os.environ.get("LIMINA_OIDC_ADMIN_VALUE", "admin"),
            leeway_seconds=int(os.environ.get("LIMINA_OIDC_LEEWAY_SECONDS", "30")),
        )
    if not local_token and os.environ.get("LIMINA_ALLOW_INSECURE_NO_AUTH", "").lower() not in {
        "1",
        "true",
        "yes",
    }:
        raise RuntimeError(
            "Configure LIMINA_API_TOKEN for local development or LIMINA_OIDC_ISSUER and "
            "LIMINA_OIDC_AUDIENCE for team deployment."
        )
    return LocalAuthenticator(
        local_token,
        local_admin_token
        if local_admin_token is not None
        else os.environ.get("LIMINA_ADMIN_API_TOKEN") or None,
    )
