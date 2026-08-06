from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from limina_cloud.auth import (
    DEFAULT_DEV_JWT_AUDIENCE,
    DEFAULT_DEV_JWT_ISSUER,
    DevJwtAuthenticator,
    LocalAuthenticator,
    OidcAuthenticator,
    Principal,
    WorkOsAuthenticator,
    authenticator_from_environment,
)
from limina_cloud.collaboration import CollaborationService
from limina_cloud.database import Database
from limina_cloud.errors import AuthenticationError, AuthorizationError
from limina_cloud.service import ChallengeService


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


class WorkOsAuthenticationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.authenticator = WorkOsAuthenticator(
            client_id="client_123",
            organization="org_123",
        )
        self.authenticator.jwks_client = StaticJwksClient(self.private_key.public_key())

    def token(self, **overrides: object) -> str:
        now = datetime.now(UTC)
        claims = {
            "iss": "https://api.workos.com/user_management/client_123",
            "sub": "user_123",
            "email": "ada@example.test",
            "org_id": "org_123",
            "permissions": [
                "limina:access",
                "limina:project-create",
                "limina:instance-admin",
            ],
            "iat": now,
            "exp": now + timedelta(minutes=5),
            **overrides,
        }
        return jwt.encode(claims, self.private_key, algorithm="RS256", headers={"kid": "test"})

    def test_workos_claims_are_projected_to_an_immutable_scoped_principal(self) -> None:
        principal = self.authenticator.authenticate(self.token())

        self.assertEqual(principal.subject, "user_123")
        self.assertEqual(principal.organization, "org_123")
        self.assertEqual(
            principal.permissions,
            frozenset(
                {
                    "limina:access",
                    "limina:project-create",
                    "limina:instance-admin",
                }
            ),
        )
        self.assertTrue(principal.instance_admin)
        self.assertFalse(principal.project_admin)
        with self.assertRaises(FrozenInstanceError):
            principal.organization = "org_other"  # type: ignore[misc]

    def test_same_signing_key_with_authkit_issuer_is_rejected(self) -> None:
        with self.assertRaises(AuthenticationError):
            self.authenticator.authenticate(
                self.token(iss="https://cultured-garland-staging.authkit.app")
            )

    def test_wrong_organization_and_missing_access_permission_are_rejected(self) -> None:
        with self.assertRaises(AuthenticationError):
            self.authenticator.authenticate(self.token(org_id="org_other"))
        with self.assertRaises(AuthenticationError):
            self.authenticator.authenticate(
                self.token(permissions=["limina:project-create", "limina:instance-admin"])
            )


class DevelopmentJwtAuthenticationTests(unittest.TestCase):
    secret = "development-secret-with-at-least-32-bytes"

    @staticmethod
    def token(secret: str, **overrides: object) -> str:
        now = datetime.now(UTC)
        claims = {
            "iss": DEFAULT_DEV_JWT_ISSUER,
            "aud": DEFAULT_DEV_JWT_AUDIENCE,
            "sub": "dev-user",
            "org_id": "org_dev",
            "permissions": ["limina:access", "limina:project-create"],
            "iat": now,
            "exp": now + timedelta(minutes=5),
            **overrides,
        }
        return jwt.encode(claims, secret, algorithm="HS256")

    def test_dev_jwt_requires_issuer_audience_org_and_permissions(self) -> None:
        authenticator = DevJwtAuthenticator(
            secret=self.secret,
            organization="org_dev",
            bind_host="127.0.0.1",
        )

        principal = authenticator.authenticate(self.token(self.secret))
        self.assertEqual(principal.organization, "org_dev")
        self.assertEqual(principal.auth_mode, "dev-jwt")
        self.assertFalse(principal.project_admin)
        invalid_claims = (
            {"iss": "urn:limina:another-dev-issuer"},
            {"aud": "another-api"},
            {"org_id": "org_other"},
            {"permissions": ["limina:project-create"]},
        )
        for overrides in invalid_claims:
            with self.subTest(overrides=overrides), self.assertRaises(AuthenticationError):
                authenticator.authenticate(self.token(self.secret, **overrides))

    def test_dev_auth_environment_rejects_non_loopback_startup(self) -> None:
        environment = {
            "LIMINA_CONSOLE_DEV_AUTH": "1",
            "LIMINA_DEV_JWT_SECRET": self.secret,
            "LIMINA_DEV_JWT_ORGANIZATION_ID": "org_dev",
        }
        with (
            mock.patch.dict(os.environ, environment, clear=True),
            self.assertRaisesRegex(RuntimeError, "loopback"),
        ):
            authenticator_from_environment(bind_host="0.0.0.0")

    def test_dev_auth_requires_explicit_enablement_and_complete_configuration(self) -> None:
        without_enablement = {
            "LIMINA_DEV_JWT_SECRET": self.secret,
            "LIMINA_DEV_JWT_ORGANIZATION_ID": "org_dev",
        }
        with (
            mock.patch.dict(os.environ, without_enablement, clear=True),
            self.assertRaisesRegex(RuntimeError, "LIMINA_CONSOLE_DEV_AUTH=1"),
        ):
            authenticator_from_environment(bind_host="127.0.0.1")

        with (
            mock.patch.dict(
                os.environ,
                {"LIMINA_CONSOLE_DEV_AUTH": "1"},
                clear=True,
            ),
            self.assertRaisesRegex(RuntimeError, "requires LIMINA_DEV_JWT_SECRET"),
        ):
            authenticator_from_environment(bind_host="127.0.0.1")

    def test_dev_auth_requires_an_explicit_strong_secret(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "at least 32 bytes"):
            DevJwtAuthenticator(
                secret="too-short",
                organization="org_dev",
                bind_host="localhost",
            )


class LocalAuthenticationTests(unittest.TestCase):
    def test_project_and_instance_tokens_have_distinct_authority(self) -> None:
        authenticator = LocalAuthenticator("project-token", "admin-token")
        project_user = authenticator.authenticate("project-token", actor_hint="researcher")
        administrator = authenticator.authenticate("admin-token", actor_hint="operator")

        self.assertTrue(project_user.project_admin)
        self.assertFalse(project_user.instance_admin)
        self.assertTrue(administrator.project_admin)
        self.assertTrue(administrator.instance_admin)

    def test_equal_project_and_instance_tokens_are_rejected(self) -> None:
        with self.assertRaises(RuntimeError):
            LocalAuthenticator("same", "same")

    def test_non_ascii_invalid_token_is_rejected_without_a_type_error(self) -> None:
        authenticator = LocalAuthenticator("project-token", "admin-token")

        with self.assertRaises(AuthenticationError):
            authenticator.authenticate("not-the-token-é")


class ProjectAuthorizationBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "authorization.db"
        self.database = Database(f"sqlite:///{database_path}")
        self.database.initialize()
        self.service = ChallengeService(self.database)
        self.service.create_challenge(
            slug="private-project",
            name="Private project",
            objective="Keep instance and project authority separate.",
            context="",
            success_criteria="Only members and explicit local project admins can read it.",
            actor="owner",
            command_id=str(uuid4()),
            owner_subject="owner",
            owner_display_name="Olivia Owner",
        )
        self.collaboration = CollaborationService(self.database)

    def tearDown(self) -> None:
        self.database.dispose()
        self.temp_dir.cleanup()

    def test_oidc_instance_admin_has_no_implicit_project_visibility(self) -> None:
        principal = Principal(
            "instance-admin",
            "Alice Admin",
            instance_admin=True,
            auth_mode="oidc",
        )

        self.assertEqual(self.collaboration.visible_project_slugs(principal), set())
        with self.assertRaises(AuthorizationError):
            self.collaboration.require_role("private-project", principal, "VIEWER")

    def test_local_token_retains_full_project_access(self) -> None:
        principal = LocalAuthenticator("local-token").authenticate("local-token")

        self.assertIsNone(self.collaboration.visible_project_slugs(principal))
        self.assertEqual(
            self.collaboration.require_role("private-project", principal, "OWNER"),
            "OWNER",
        )


if __name__ == "__main__":
    unittest.main()
