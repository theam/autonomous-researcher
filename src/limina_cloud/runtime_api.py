"""Operational probes and instance-admin runtime authentication routes."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from . import __version__
from .auth import Principal
from .engines import SUPPORTED_RUNTIME_ENGINES
from .schemas import CodexAuthLoginRequest, CodexAuthStatus, CodexDeviceLogin, HealthResponse


def register_runtime_admin_routes(
    app: FastAPI,
    runtime: Any,
    *,
    principal_dependency: Any,
    instance_admin_dependency: Any,
    command_dependency: Any,
    public_errors: dict[int, Any],
) -> None:
    @app.get("/livez")
    def live() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/readyz", response_model=None)
    def ready() -> Any:
        try:
            with runtime.database.session() as session:
                session.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse(status_code=503, content={"ok": False})
        return {"ok": True}

    @app.get("/healthz", response_model=HealthResponse, responses=public_errors)
    def health(_principal: Principal = principal_dependency) -> dict[str, Any]:
        return {
            "ok": True,
            "version": __version__,
            "runtime_owner": "limina",
            "auth_mode": runtime.authenticator.mode,
            "runtimes": list(SUPPORTED_RUNTIME_ENGINES),
            "interfaces": {"rest": "/v2", "mcp": "/mcp/"},
        }

    @app.get(
        "/v2/runtime/engines/codex/auth",
        response_model=CodexAuthStatus,
        responses=public_errors,
        tags=["runtime administration"],
    )
    def codex_auth_status(
        _principal: Principal = instance_admin_dependency,
    ) -> dict[str, Any]:
        return runtime.supervisor.codex_auth.status()

    @app.post(
        "/v2/runtime/engines/codex/auth/login",
        response_model=CodexDeviceLogin | CodexAuthStatus,
        responses=public_errors,
        tags=["runtime administration"],
    )
    def codex_auth_login(
        body: CodexAuthLoginRequest,
        command_id: str = command_dependency,
        _principal: Principal = instance_admin_dependency,
    ) -> dict[str, Any]:
        if body.method == "chatgpt":
            return runtime.supervisor.codex_auth.start_device_login(command_id)
        return runtime.supervisor.codex_auth.login_from_environment(body.method)

    @app.get(
        "/v2/runtime/engines/codex/auth/login/{login_id}",
        response_model=CodexDeviceLogin,
        responses=public_errors,
        tags=["runtime administration"],
    )
    def codex_auth_login_attempt(
        login_id: str,
        _principal: Principal = instance_admin_dependency,
    ) -> dict[str, Any]:
        return runtime.supervisor.codex_auth.login_attempt(login_id)

    @app.delete(
        "/v2/runtime/engines/codex/auth/login/{login_id}",
        response_model=CodexDeviceLogin,
        responses=public_errors,
        tags=["runtime administration"],
    )
    def cancel_codex_auth_login(
        login_id: str,
        _principal: Principal = instance_admin_dependency,
    ) -> dict[str, Any]:
        return runtime.supervisor.codex_auth.cancel_device_login(login_id)

    @app.delete(
        "/v2/runtime/engines/codex/auth",
        response_model=CodexAuthStatus,
        responses=public_errors,
        tags=["runtime administration"],
    )
    def codex_auth_logout(
        _principal: Principal = instance_admin_dependency,
    ) -> dict[str, Any]:
        return runtime.supervisor.codex_auth.logout()
