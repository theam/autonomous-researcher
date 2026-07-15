"""Codex runtime-administration CLI commands."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.panel import Panel


def register_runtime_commands(
    app: typer.Typer,
    state_for: Callable[[typer.Context], Any],
    invoke: Callable[[typer.Context, Callable[[], Any]], Any],
    emit: Callable[[typer.Context, Any, Callable[[Console, Any], None]], None],
    command_id: Callable[[], str],
) -> None:
    def _render_codex_auth(console: Console, value: dict[str, Any]) -> None:
        method = value.get("active_method") or "not authenticated"
        source = value.get("source") or "none"
        account = value.get("account_email") or "not disclosed"
        console.print(
            Panel(
                f"Method  {method}\nSource  {source}\nAccount {account}\n"
                f"Mode    {value.get('configured_mode', 'unknown')}",
                title="Codex authentication",
                border_style="green" if value.get("configured") else "yellow",
            )
        )

    @app.command("status")
    def codex_auth_status(ctx: typer.Context) -> None:
        """Show the server-owned Codex login state."""
        result = invoke(ctx, state_for(ctx).admin_client().codex_auth_status)
        emit(ctx, result, _render_codex_auth)

    @app.command("login")
    def codex_auth_login(
        ctx: typer.Context,
        method: Annotated[
            str,
            typer.Option(
                "--method",
                help="chatgpt, api-key, or access-token; machine credentials stay on the server.",
            ),
        ] = "chatgpt",
    ) -> None:
        """Authenticate Codex for every managed project on this runtime node."""
        normalized = method.strip().lower()
        if normalized not in {"chatgpt", "api-key", "access-token"}:
            raise typer.BadParameter("method must be chatgpt, api-key, or access-token")
        state = state_for(ctx)
        client = state.admin_client()
        result = invoke(ctx, lambda: client.codex_login(normalized, command_id=command_id()))
        if "login_id" not in result:
            emit(ctx, result, _render_codex_auth)
            return
        if state.as_json:
            emit(ctx, result, lambda _console, _value: None)
            return
        state.console.print(
            Panel(
                f"Open [link={result['verification_url']}]{result['verification_url']}[/link]\n"
                f"Enter code [bold]{result['user_code']}[/bold]\n\n"
                "Limina will continue as soon as the login is approved.",
                title="Sign in with ChatGPT",
                border_style="cyan",
            )
        )
        login_id = result["login_id"]
        try:
            while result["status"] == "PENDING":
                time.sleep(1)
                result = invoke(
                    ctx,
                    lambda: client.codex_login_attempt(login_id),
                )
        except KeyboardInterrupt:
            result = invoke(ctx, lambda: client.cancel_codex_login(login_id))
        color = "green" if result["status"] == "SUCCEEDED" else "red"
        state.console.print(f"[{color}]{result['status'].lower()}[/{color}]")
        if result.get("error"):
            state.error_console.print(result["error"])

    @app.command("logout")
    def codex_auth_logout(ctx: typer.Context) -> None:
        """Remove the server-owned Codex login."""
        result = invoke(ctx, state_for(ctx).admin_client().codex_logout)
        emit(ctx, result, _render_codex_auth)
