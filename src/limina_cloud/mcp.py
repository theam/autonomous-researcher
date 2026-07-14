"""Model Context Protocol adapter for Limina's public project contract."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from secrets import compare_digest
from typing import Annotated, Any, Literal, TypeVar
from uuid import uuid4

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import McpError
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS, ErrorData, ToolAnnotations
from pydantic import Field
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .errors import InvariantError, LiminaError
from .operations import ACTOR_LIMIT, PUBLIC_COMMAND_ID_LIMIT, ProjectOperations

Result = TypeVar("Result")
Actor = Annotated[str, Field(max_length=ACTOR_LIMIT)]
IdempotencyKey = Annotated[str, Field(max_length=PUBLIC_COMMAND_ID_LIMIT)]
EventCursor = Annotated[int, Field(ge=0)]
EventLimit = Annotated[int, Field(ge=1, le=1000)]
REQUEST_ACTOR: ContextVar[str] = ContextVar("limina_mcp_actor", default="")


class BearerTokenMiddleware:
    """Apply the instance's existing shared-token boundary to MCP."""

    def __init__(self, app: ASGIApp, token: str | None) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        authorization = headers.get(b"authorization", b"").decode("latin-1")
        if self.token is not None and not compare_digest(authorization, f"Bearer {self.token}"):
            response = JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "code": "authentication_required",
                        "message": "Authentication required.",
                        "details": {},
                    }
                },
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return
        actor = headers.get(b"x-limina-actor", b"").decode("utf-8", errors="replace").strip()
        actor_context = REQUEST_ACTOR.set(actor)
        try:
            await self.app(scope, receive, send)
        finally:
            REQUEST_ACTOR.reset(actor_context)


def _mcp_error(exc: LiminaError) -> McpError:
    code = INVALID_PARAMS if exc.http_status < 500 else INTERNAL_ERROR
    return McpError(
        ErrorData(
            code=code,
            message=exc.message,
            data={"code": exc.code, "details": exc.details},
        )
    )


def _call(operation: Callable[[], Result]) -> Result:
    try:
        return operation()
    except LiminaError as exc:
        raise _mcp_error(exc) from exc


async def _call_async(operation: Callable[[], Awaitable[Result]]) -> Result:
    try:
        return await operation()
    except LiminaError as exc:
        raise _mcp_error(exc) from exc


def _actor(ctx: Context, supplied: str) -> str:
    actor = supplied.strip() or REQUEST_ACTOR.get()
    if not actor:
        client_params = ctx.session.client_params
        client_info = getattr(client_params, "clientInfo", None)
        client_name = getattr(client_info, "name", None)
        actor = f"mcp:{client_name or 'client'}"
    if len(actor) > ACTOR_LIMIT:
        raise InvariantError(f"Actor identity must be at most {ACTOR_LIMIT} characters.")
    return actor


def _command_id(supplied: str) -> str:
    command_id = supplied.strip() or f"mcp:{uuid4()}"
    if len(command_id) > PUBLIC_COMMAND_ID_LIMIT:
        raise InvariantError(
            f"Idempotency key must be at most {PUBLIC_COMMAND_ID_LIMIT} characters."
        )
    return command_id


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)


def create_mcp_server(
    operations: ProjectOperations,
    *,
    token: str | None,
    allowed_hosts: list[str],
    allowed_origins: list[str],
) -> tuple[FastMCP, ASGIApp]:
    """Build an MCP server and its authenticated Streamable HTTP app."""

    server = FastMCP(
        "Limina",
        instructions=(
            "Operate durable Limina projects at the mission boundary. Review work and knowledge, "
            "steer strategy, provide project variables, and manage project lifecycle. Limina owns "
            "provider sessions, threads, subagents, workspaces, and execution recovery. Never ask "
            "the user to manage those internals. Secret values must be configured through the "
            "trusted Limina CLI or REST API, not through model-visible MCP arguments."
        ),
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
        log_level="WARNING",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        ),
    )

    read_only = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
    mutation = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
    destructive = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)

    @server.tool(annotations=read_only)
    def limina_list_projects(include_archived: bool = False) -> list[dict[str, Any]]:
        """List Limina projects visible to this team instance."""

        return _call(lambda: operations.list_projects(include_archived=include_archived))

    @server.tool(annotations=read_only)
    def limina_get_project_status(project: str) -> dict[str, Any]:
        """Get a project's mission, state, next step, blocker, and knowledge counts."""

        return _call(lambda: operations.get_status(project))

    @server.tool(annotations=mutation)
    def limina_create_project(
        slug: str,
        name: str,
        mission: str,
        success_criteria: str,
        runtime: Literal["codex", "claude-code"] = "codex",
        context: str = "",
        actor: Actor = "",
        idempotency_key: IdempotencyKey = "",
        *,
        ctx: Context,
    ) -> dict[str, Any]:
        """Create a durable project; execution begins only after a start action.

        Actor is the teammate steering the project. Supply a stable idempotency_key
        if the client may retry the request.
        """

        return _call(
            lambda: operations.create_project(
                slug=slug,
                name=name,
                mission=mission,
                success_criteria=success_criteria,
                context=context,
                runtime=runtime,
                actor=_actor(ctx, actor),
                command_id=_command_id(idempotency_key),
            )
        )

    @server.tool(annotations=destructive)
    async def limina_manage_project(
        project: str,
        action: Literal["start", "pause", "resume", "stop", "archive"],
        actor: Actor = "",
        idempotency_key: IdempotencyKey = "",
        *,
        ctx: Context,
    ) -> dict[str, Any]:
        """Start, pause, resume, stop, or archive a Limina-managed project."""

        return await _call_async(
            lambda: operations.apply_lifecycle(
                slug=project,
                action=action,
                actor=_actor(ctx, actor),
                command_id=_command_id(idempotency_key),
            )
        )

    @server.tool(annotations=mutation)
    async def limina_steer_project(
        project: str,
        message: str,
        kind: Literal["STEER", "ANSWER", "APPROVAL", "BLOCKER", "INTERRUPT"] = "STEER",
        actor: Actor = "",
        idempotency_key: IdempotencyKey = "",
        *,
        ctx: Context,
    ) -> dict[str, Any]:
        """Give durable feedback or direction to a project, including active work."""

        return await _call_async(
            lambda: operations.steer(
                slug=project,
                body=message,
                kind=kind,
                actor=_actor(ctx, actor),
                command_id=_command_id(idempotency_key),
            )
        )

    @server.tool(annotations=read_only)
    def limina_review_project(project: str) -> dict[str, Any]:
        """Review accepted knowledge, active evidence, resources, and recent activity."""

        return _call(lambda: operations.review(project))

    @server.tool(annotations=read_only)
    def limina_get_knowledge(project: str, artifact_id: str) -> dict[str, Any]:
        """Read one hypothesis, experiment, or finding by its durable artifact ID."""

        return _call(lambda: operations.get_knowledge(project, artifact_id))

    @server.tool(annotations=read_only)
    def limina_list_activity(
        project: str,
        after: EventCursor = 0,
        limit: EventLimit = 200,
    ) -> dict[str, Any]:
        """Read ordered durable activity after a cursor; use the returned cursor next time."""

        return _call(lambda: operations.activity(project, after=after, limit=limit))

    @server.tool(annotations=mutation)
    async def limina_set_project_variable(
        project: str,
        name: str,
        value: str,
        actor: Actor = "",
        idempotency_key: IdempotencyKey = "",
        *,
        ctx: Context,
    ) -> dict[str, Any]:
        """Set visible project configuration or a resource reference; never use for secrets."""

        return await _call_async(
            lambda: operations.set_variable(
                slug=project,
                name=name,
                value=value,
                actor=_actor(ctx, actor),
                command_id=_command_id(idempotency_key),
            )
        )

    @server.tool(annotations=read_only)
    def limina_list_project_resources(project: str) -> list[dict[str, Any]]:
        """List project variables and redacted secret metadata."""

        return _call(lambda: operations.list_resources(project))

    @server.tool(annotations=destructive)
    async def limina_remove_project_resource(
        project: str,
        name: str,
        actor: Actor = "",
        idempotency_key: IdempotencyKey = "",
        *,
        ctx: Context,
    ) -> dict[str, Any]:
        """Revoke a project variable or secret without exposing its value."""

        return await _call_async(
            lambda: operations.remove_resource(
                slug=project,
                name=name,
                actor=_actor(ctx, actor),
                command_id=_command_id(idempotency_key),
            )
        )

    @server.resource(
        "limina://projects",
        name="Limina projects",
        description="All active Limina projects as JSON.",
        mime_type="application/json",
    )
    def projects_resource() -> str:
        return _json(_call(lambda: operations.list_projects()))

    @server.resource(
        "limina://projects/{project}/status",
        name="Limina project status",
        description="Mission, active state, and knowledge counts for one project.",
        mime_type="application/json",
    )
    def project_status_resource(project: str) -> str:
        return _json(_call(lambda: operations.get_status(project)))

    @server.resource(
        "limina://projects/{project}/review",
        name="Limina project review",
        description="The complete review surface for one project.",
        mime_type="application/json",
    )
    def project_review_resource(project: str) -> str:
        return _json(_call(lambda: operations.review(project)))

    @server.resource(
        "limina://projects/{project}/knowledge/{artifact_id}",
        name="Limina knowledge artifact",
        description="One durable hypothesis, experiment, or finding.",
        mime_type="application/json",
    )
    def knowledge_resource(project: str, artifact_id: str) -> str:
        return _json(_call(lambda: operations.get_knowledge(project, artifact_id)))

    @server.resource(
        "limina://projects/{project}/snapshot",
        name="Limina knowledge snapshot",
        description="Deterministic Markdown knowledge-base files for one project.",
        mime_type="application/json",
    )
    def snapshot_resource(project: str) -> str:
        return _json(_call(lambda: operations.snapshot(project)))

    streamable_http_app = server.streamable_http_app()
    return server, BearerTokenMiddleware(streamable_http_app, token)
