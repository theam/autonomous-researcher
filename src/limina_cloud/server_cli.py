"""Connectivity diagnostics and server process CLI commands."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import typer
import uvicorn
from rich.console import Console

from .api import create_app
from .auth import authenticator_from_environment
from .engines import runtime_engine_label


def register_server_commands(
    app: typer.Typer,
    state_for: Callable[[typer.Context], Any],
    invoke: Callable[[typer.Context, Callable[[], Any]], Any],
    emit: Callable[[typer.Context, Any, Callable[[Console, Any], None]], None],
) -> None:
    @app.command()
    def doctor(ctx: typer.Context) -> None:
        """Verify connectivity, authentication, and runtime ownership."""
        state = state_for(ctx)
        result = invoke(ctx, state.public_client().health)
        emit(
            ctx,
            result,
            lambda console, value: console.print(
                f"[green]ok[/green] {state.url} · runtime owned by {value['runtime_owner']} · "
                f"engines {', '.join(runtime_engine_label(item) for item in value['runtimes'])}"
            ),
        )

    @app.command()
    def serve(
        database_url: Annotated[
            str, typer.Option("--database-url", envvar="LIMINA_DATABASE_URL")
        ] = "sqlite:///.limina/server.db",
        workspace_root: Annotated[
            Path, typer.Option("--workspace-root", envvar="LIMINA_WORKSPACE_ROOT")
        ] = Path(".limina/workspaces"),
        host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
        port: Annotated[int, typer.Option("--port")] = 7433,
        token: Annotated[str | None, typer.Option("--token", envvar="LIMINA_API_TOKEN")] = None,
        admin_token: Annotated[
            str | None,
            typer.Option("--admin-token", envvar="LIMINA_ADMIN_API_TOKEN"),
        ] = None,
    ) -> None:
        """Run a complete Limina instance, including all managed project runtimes."""
        remote_auth_configured = bool(
            (os.environ.get("LIMINA_OIDC_ISSUER") and os.environ.get("LIMINA_OIDC_AUDIENCE"))
            or (
                os.environ.get("LIMINA_WORKOS_CLIENT_ID")
                and os.environ.get("LIMINA_WORKOS_ORGANIZATION_ID")
            )
        )
        insecure_local = os.environ.get("LIMINA_ALLOW_INSECURE_NO_AUTH", "").lower() in {
            "1",
            "true",
            "yes",
        }
        if (
            host not in {"127.0.0.1", "localhost", "::1"}
            and not (token or admin_token)
            and not remote_auth_configured
            and not insecure_local
        ):
            raise typer.BadParameter(
                "a shared token, OIDC, or WorkOS configuration is required for a non-local bind"
            )
        authenticator = authenticator_from_environment(
            local_token=token,
            local_admin_token=admin_token,
            bind_host=host,
        )
        uvicorn.run(
            create_app(
                database_url=database_url,
                authenticator=authenticator,
                workspace_root=workspace_root,
                internal_url=f"http://127.0.0.1:{port}",
            ),
            host=host,
            port=port,
        )
