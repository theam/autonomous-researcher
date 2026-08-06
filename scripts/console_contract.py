#!/usr/bin/env python3
"""Generate or verify the Limina Console's public v2 contract artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from limina_cloud.api import create_app

ROOT = Path(__file__).resolve().parents[1]
OPENAPI_PATH = ROOT / "contracts" / "openapi.v2.json"
CHECKSUM_PATH = ROOT / "contracts" / "openapi.v2.sha256"
CLIENT_PATH = ROOT / "apps" / "web" / "lib" / "limina" / "generated.ts"
GENERATOR_PATH = ROOT / "apps" / "web" / "node_modules" / ".bin" / "openapi-typescript"


def contract_bytes() -> bytes:
    """Build the schema from a disposable local runtime without starting workers."""

    with tempfile.TemporaryDirectory(prefix="limina-contract-") as temporary:
        root = Path(temporary)
        app = create_app(
            database_url=f"sqlite:///{root / 'contract.db'}",
            token="contract-local-token",
            admin_token="contract-admin-token",
            workspace_root=root / "workspaces",
            secret_key_path=root / "secret.key",
        )
        try:
            schema = app.openapi()
        finally:
            app.state.runtime.database.dispose()
    paths = schema.get("paths", {})
    if any(str(path).startswith(("/v1", "/internal/")) for path in paths):
        raise RuntimeError("The public OpenAPI contract contains a private or legacy route.")
    return (json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def generated_client(schema_path: Path) -> bytes:
    if not GENERATOR_PATH.exists():
        raise RuntimeError("Run `pnpm --dir apps/web install` before generating the client.")
    with tempfile.TemporaryDirectory(prefix="limina-client-") as temporary:
        output = Path(temporary) / "generated.ts"
        subprocess.run(
            [str(GENERATOR_PATH), str(schema_path), "--output", str(output)],
            cwd=ROOT,
            check=True,
        )
        return output.read_bytes()


def write_contract() -> None:
    OPENAPI_PATH.parent.mkdir(parents=True, exist_ok=True)
    CLIENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    schema = contract_bytes()
    OPENAPI_PATH.write_bytes(schema)
    CHECKSUM_PATH.write_text(hashlib.sha256(schema).hexdigest() + "\n", encoding="utf-8")
    CLIENT_PATH.write_bytes(generated_client(OPENAPI_PATH))


def check_contract() -> None:
    expected_schema = contract_bytes()
    actual_schema = OPENAPI_PATH.read_bytes()
    if actual_schema != expected_schema:
        raise SystemExit(
            "contracts/openapi.v2.json drifted; run `uv run python scripts/console_contract.py`."
        )
    expected_checksum = hashlib.sha256(actual_schema).hexdigest()
    if CHECKSUM_PATH.read_text(encoding="utf-8").strip() != expected_checksum:
        raise SystemExit("contracts/openapi.v2.sha256 does not match the committed schema.")
    if CLIENT_PATH.read_bytes() != generated_client(OPENAPI_PATH):
        raise SystemExit(
            "The generated TypeScript contract drifted; run `uv run python scripts/console_contract.py`."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail instead of updating artifacts")
    args = parser.parse_args()
    check_contract() if args.check else write_contract()


if __name__ == "__main__":
    main()
