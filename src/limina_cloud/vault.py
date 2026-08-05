"""Small encrypted-at-rest secret boundary for a Limina instance."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from .errors import InvariantError


class SecretCipher:
    """Encrypt project secrets without exposing keys to the domain or API."""

    def __init__(self, key: str | bytes) -> None:
        encoded = key.encode() if isinstance(key, str) else key
        try:
            self._fernet = Fernet(encoded)
        except (TypeError, ValueError) as exc:
            raise InvariantError(
                "The Limina secret-encryption key is invalid.",
                suggestion="Provide a URL-safe base64 Fernet key in LIMINA_SECRET_KEY.",
            ) from exc

    @classmethod
    def load(cls, key_path: Path) -> SecretCipher:
        """Load an operator key or create a persistent single-instance key."""
        configured = os.environ.get("LIMINA_SECRET_KEY", "").strip()
        if configured:
            return cls(configured)
        return cls(_read_or_create_key(key_path))

    @classmethod
    def ephemeral(cls) -> SecretCipher:
        return cls(Fernet.generate_key())

    def encrypt(self, *, project: str, name: str, value: str) -> str:
        payload = json.dumps(
            {"project": project, "name": name, "value": value},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        return self._fernet.encrypt(payload).decode()

    def decrypt(self, *, project: str, name: str, ciphertext: str) -> str:
        try:
            payload: Any = json.loads(self._fernet.decrypt(ciphertext.encode()))
        except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvariantError(
                f"Secret '{name}' cannot be decrypted.",
                resource=name,
                suggestion="Restore the instance secret key or replace the project secret.",
            ) from exc
        if not isinstance(payload, dict):
            raise InvariantError(f"Secret '{name}' has an invalid encrypted payload.")
        if payload.get("project") != project or payload.get("name") != name:
            raise InvariantError(
                f"Secret '{name}' is bound to a different project or name.",
                resource=name,
            )
        value = payload.get("value")
        if not isinstance(value, str):
            raise InvariantError(f"Secret '{name}' has an invalid encrypted payload.")
        return value


def _read_or_create_key(key_path: Path) -> bytes:
    path = key_path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        key = path.read_bytes().strip()
        permissions = stat.S_IMODE(path.stat().st_mode)
        if permissions & 0o077:
            raise InvariantError(
                f"The Limina secret key file '{path}' is readable by other users.",
                suggestion=f"Run `chmod 600 {path}` before starting Limina.",
            ) from None
    else:
        key = Fernet.generate_key()
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(key + b"\n")
    if not key:
        raise InvariantError(f"The Limina secret key file '{path}' is empty.")
    return key
