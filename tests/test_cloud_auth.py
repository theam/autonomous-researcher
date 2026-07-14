from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from limina_cloud.auth import OidcAuthenticator
from limina_cloud.errors import AuthenticationError


class StaticJwksClient:
    def __init__(self, public_key: object) -> None:
        self.public_key = public_key

    def get_signing_key_from_jwt(self, _token: str) -> SimpleNamespace:
        return SimpleNamespace(key=self.public_key)


class OidcAuthenticationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.authenticator = OidcAuthenticator(
            issuer="https://identity.example.test",
            audience="limina-api",
            jwks_url="https://identity.example.test/.well-known/jwks.json",
            admin_claim="roles",
            admin_value="limina-admin",
        )
        self.authenticator.jwks_client = StaticJwksClient(self.private_key.public_key())

    def token(self, **overrides: object) -> str:
        now = datetime.now(UTC)
        claims = {
            "iss": "https://identity.example.test",
            "aud": "limina-api",
            "sub": "user-123",
            "name": "Ada Investigator",
            "email": "ada@example.test",
            "roles": ["limina-admin"],
            "iat": now,
            "exp": now + timedelta(minutes=5),
            **overrides,
        }
        return jwt.encode(claims, self.private_key, algorithm="RS256", headers={"kid": "test"})

    def test_signed_oidc_claims_define_the_principal(self) -> None:
        principal = self.authenticator.authenticate(
            self.token(), actor_hint="untrusted-header-value"
        )
        self.assertEqual(principal.subject, "user-123")
        self.assertEqual(principal.actor, "Ada Investigator")
        self.assertEqual(principal.email, "ada@example.test")
        self.assertTrue(principal.instance_admin)

    def test_wrong_audience_and_expired_tokens_are_rejected(self) -> None:
        with self.assertRaises(AuthenticationError):
            self.authenticator.authenticate(self.token(aud="another-api"))
        with self.assertRaises(AuthenticationError):
            self.authenticator.authenticate(
                self.token(exp=datetime.now(UTC) - timedelta(seconds=60))
            )


if __name__ == "__main__":
    unittest.main()
