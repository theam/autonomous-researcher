"""Public control plane for Limina-owned collaborative project runtimes."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import __version__
from .api_errors import register_error_handlers
from .auth import (
    Authenticator,
    Principal,
    RateLimitedAuthenticator,
    authenticator_from_environment,
)
from .console_api import register_console_routes
from .database import Database
from .errors import AuthenticationError, AuthorizationError, InvariantError, LiminaError
from .event_broker import EventBroker
from .exporter import MarkdownExporter
from .internal_api import register_internal_agent_routes
from .mcp import create_mcp_server
from .notification_service import NotificationService
from .operations import (
    ACTOR_LIMIT,
    PUBLIC_COMMAND_ID_LIMIT,
    ProjectOperations,
    public_event,
    public_status,
)
from .rate_limit import FailureRateLimiter
from .runtime import AgentFactory, ProjectSupervisor
from .runtime_api import register_runtime_admin_routes
from .schemas import (
    AnalyticsResponse,
    ArtifactResponse,
    CloneProjectRequest,
    CommentRequest,
    CommentResponse,
    CreateProjectRequest,
    ErrorResponse,
    EventPage,
    GuidancePage,
    GuidanceReceipt,
    KickoffTemplate,
    KnowledgeGraphResponse,
    KnowledgePage,
    LiveTicketResponse,
    MemberRequest,
    MemberResponse,
    PreflightResponse,
    ProjectPage,
    ProjectResponse,
    ProjectStatusResponse,
    RelationRequest,
    RelationResponse,
    ResourceResponse,
    ReviewResponse,
    RevisionResponse,
    RuntimeRunDetail,
    RuntimeRunPage,
    SavedViewRequest,
    SavedViewResponse,
    SecretValueRequest,
    SnapshotResponse,
    SourceRequest,
    SourceResponse,
    SteeringRequest,
    TagResponse,
    UpdateProjectRequest,
    VariableValueRequest,
)
from .service import ChallengeService
from .stream_api import register_stream_routes
from .vault import SecretCipher

logger = logging.getLogger(__name__)


class RuntimeContext:
    def __init__(
        self,
        database: Database,
        authenticator: Authenticator,
        *,
        workspace_root: Path,
        agent_factory: AgentFactory | None,
        poll_interval: float,
        attention_reconcile_interval: float,
        internal_url: str,
        secret_key_path: Path,
    ) -> None:
        self.database = database
        self.console_url = os.environ.get("LIMINA_CONSOLE_PUBLIC_URL", "http://127.0.0.1:7433")
        cipher = SecretCipher.load(secret_key_path)
        self.notifications = NotificationService(database, cipher)

        def enqueue_notification(session: Any, challenge: Any, episode: Any) -> None:
            self.notifications.enqueue_attention(
                session,
                challenge=challenge,
                episode=episode,
                console_url=self.console_url,
            )

        self.service = ChallengeService(
            database,
            cipher,
            attention_notification_sink=enqueue_notification,
        )
        self.exporter = MarkdownExporter(self.service)
        self.authenticator = authenticator
        self.supervisor = ProjectSupervisor(
            self.service,
            self.exporter,
            workspace_root=workspace_root,
            internal_url=internal_url,
            agent_factory=agent_factory,
            poll_interval=poll_interval,
        )
        self.operations = ProjectOperations(
            self.service,
            self.exporter,
            self.supervisor,
            notification_service=self.notifications,
            console_url=self.console_url,
        )
        self.event_broker = EventBroker(database)
        if attention_reconcile_interval <= 0:
            raise ValueError("attention_reconcile_interval must be positive")
        self._attention_reconcile_interval = attention_reconcile_interval
        self._notification_stop = asyncio.Event()
        self._notification_task: asyncio.Task[None] | None = None

    async def start_background_services(self) -> None:
        await self.event_broker.start()
        self._notification_stop.clear()
        if self._notification_task is None or self._notification_task.done():
            self._notification_task = asyncio.create_task(
                self._run_notification_worker(), name="limina-notification-worker"
            )

    async def stop_background_services(self) -> None:
        self._notification_stop.set()
        task = self._notification_task
        self._notification_task = None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await self.event_broker.stop()

    async def _run_notification_worker(self) -> None:
        worker_id = f"notification:{os.getpid()}"
        loop = asyncio.get_running_loop()
        next_attention_reconcile = 0.0
        while not self._notification_stop.is_set():
            if loop.time() >= next_attention_reconcile:
                try:
                    await asyncio.to_thread(self.operations.reconcile_attention)
                except Exception:  # pragma: no cover - process-level resilience
                    logger.exception("The attention reconciliation cycle failed.")
                finally:
                    next_attention_reconcile = loop.time() + self._attention_reconcile_interval
            try:
                await asyncio.to_thread(self.notifications.run_once, worker_id=worker_id)
            except Exception:  # pragma: no cover - process-level resilience
                logger.exception("The notification worker cycle failed.")
            try:
                await asyncio.wait_for(
                    self._notification_stop.wait(),
                    timeout=min(1.0, self._attention_reconcile_interval),
                )
            except TimeoutError:
                continue


def create_app(
    *,
    database_url: str | None = None,
    token: str | None = None,
    admin_token: str | None = None,
    authenticator: Authenticator | None = None,
    workspace_root: Path | None = None,
    agent_factory: AgentFactory | None = None,
    poll_interval: float = 1.0,
    attention_reconcile_interval: float = 30.0,
    internal_url: str | None = None,
    secret_key_path: Path | None = None,
    mcp_allowed_hosts: list[str] | None = None,
    mcp_allowed_origins: list[str] | None = None,
) -> FastAPI:
    database = Database(database_url)
    database.initialize()
    resolved_workspace = workspace_root or Path(
        os.environ.get("LIMINA_WORKSPACE_ROOT", ".limina/workspaces")
    )
    resolved_key_path = secret_key_path or Path(
        os.environ.get("LIMINA_SECRET_KEY_PATH", resolved_workspace.parent / "secret.key")
    )
    base_authenticator = authenticator or authenticator_from_environment(
        local_token=token if token is not None else os.environ.get("LIMINA_API_TOKEN"),
        local_admin_token=admin_token
        if admin_token is not None
        else os.environ.get("LIMINA_ADMIN_API_TOKEN") or None,
    )
    transport_authenticator = RateLimitedAuthenticator(
        base_authenticator,
        FailureRateLimiter(
            limit=int(os.environ.get("LIMINA_GLOBAL_AUTH_FAILURE_LIMIT", "1000")),
            window_seconds=int(os.environ.get("LIMINA_AUTH_FAILURE_WINDOW_SECONDS", "60")),
        ),
    )
    runtime = RuntimeContext(
        database,
        transport_authenticator,
        workspace_root=resolved_workspace,
        agent_factory=agent_factory,
        poll_interval=poll_interval,
        attention_reconcile_interval=attention_reconcile_interval,
        internal_url=internal_url or os.environ.get("LIMINA_INTERNAL_URL", "http://127.0.0.1:7433"),
        secret_key_path=resolved_key_path,
    )
    allowed_hosts = mcp_allowed_hosts or os.environ.get(
        "LIMINA_MCP_ALLOWED_HOSTS", "127.0.0.1:*,localhost:*,[::1]:*"
    ).split(",")
    allowed_origins = mcp_allowed_origins or os.environ.get(
        "LIMINA_MCP_ALLOWED_ORIGINS",
        "http://127.0.0.1:*,http://localhost:*,http://[::1]:*",
    ).split(",")
    mcp_server, mcp_app = create_mcp_server(
        runtime.operations,
        authenticator=runtime.authenticator,
        allowed_hosts=[item.strip() for item in allowed_hosts if item.strip()],
        allowed_origins=[item.strip() for item in allowed_origins if item.strip()],
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        async with mcp_server.session_manager.run():
            await runtime.start_background_services()
            await runtime.supervisor.recover()
            try:
                yield
            finally:
                await runtime.supervisor.shutdown()
                await runtime.stop_background_services()

    app = FastAPI(
        title="Limina Project Runtime",
        version=__version__,
        description=(
            "Mission, review, resource, steering, and lifecycle control for Limina-owned runtimes."
        ),
        lifespan=lifespan,
        openapi_url="/v2/openapi.json",
        docs_url="/v2/docs",
        redoc_url=None,
    )
    app.state.runtime = runtime
    app.state.mcp = mcp_server
    app.mount("/mcp", mcp_app, name="mcp")
    cors_origins = [
        item.strip()
        for item in os.environ.get("LIMINA_CORS_ORIGINS", "").split(",")
        if item.strip()
    ]
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        )
    bearer = HTTPBearer(auto_error=False)
    bearer_dependency = Depends(bearer)
    auth_limiter = FailureRateLimiter(
        limit=int(os.environ.get("LIMINA_AUTH_FAILURE_LIMIT", "10")),
        window_seconds=int(os.environ.get("LIMINA_AUTH_FAILURE_WINDOW_SECONDS", "60")),
    )

    register_error_handlers(app)

    def require_auth(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = bearer_dependency,
        x_limina_actor: Annotated[str | None, Header(max_length=ACTOR_LIMIT)] = None,
    ) -> Principal:
        token_value = credentials.credentials if credentials is not None else None
        key = request.client.host if request.client else "unknown"
        auth_limiter.check(key)
        try:
            principal = runtime.authenticator.authenticate(token_value, actor_hint=x_limina_actor)
        except AuthenticationError:
            auth_limiter.failure(key)
            raise
        auth_limiter.success(key)
        return principal

    def command_headers(
        idempotency_key: Annotated[str, Header(min_length=1, max_length=PUBLIC_COMMAND_ID_LIMIT)],
    ) -> str:
        return idempotency_key

    principal_dependency = Depends(require_auth)
    command_dependency = Depends(command_headers)

    def require_instance_admin(principal: Principal = principal_dependency) -> Principal:
        if not principal.instance_admin:
            raise AuthorizationError("Instance administrator access is required.")
        return principal

    instance_admin_dependency = Depends(require_instance_admin)

    def internal_actor(
        slug: str,
        authorization: Annotated[str | None, Header()] = None,
        x_limina_agent_lane: Annotated[str | None, Header()] = None,
    ) -> str:
        prefix = "Bearer "
        if authorization is None or not authorization.startswith(prefix):
            raise AuthenticationError("An internal project capability is required.")
        return runtime.supervisor.capability_actor(
            authorization.removeprefix(prefix), slug, x_limina_agent_lane
        )

    def internal_command_id(
        idempotency_key: Annotated[str, Header(min_length=1, max_length=64)],
    ) -> str:
        return idempotency_key

    public_errors = {
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
    }

    register_runtime_admin_routes(
        app,
        runtime,
        principal_dependency=principal_dependency,
        instance_admin_dependency=instance_admin_dependency,
        command_dependency=command_dependency,
        public_errors=public_errors,
    )
    register_console_routes(
        app,
        runtime,
        principal_dependency=principal_dependency,
        command_dependency=command_dependency,
        public_errors=public_errors,
    )
    register_stream_routes(
        app,
        runtime.event_broker,
        principal_dependency=principal_dependency,
        public_errors=public_errors,
    )

    @app.post(
        "/v2/projects",
        status_code=201,
        response_model=ProjectResponse,
        responses=public_errors,
    )
    def create_project(
        body: CreateProjectRequest,
        command_id: str = command_dependency,
        principal: Principal = principal_dependency,
    ) -> dict[str, Any]:
        return runtime.operations.create_project(
            slug=body.slug,
            name=body.name,
            mission=body.objective,
            success_criteria=body.success_criteria,
            context=body.context,
            runtime=body.runtime,
            actor=principal.actor,
            command_id=command_id,
            principal=principal,
        )

    @app.get("/v2/projects", response_model=ProjectPage, responses=public_errors)
    def list_projects(
        principal: Principal = principal_dependency,
        include_archived: bool = Query(default=False),
        cursor: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=200),
    ) -> dict[str, Any]:
        return runtime.operations.list_projects(
            include_archived=include_archived,
            principal=principal,
            cursor=cursor,
            limit=limit,
        )

    @app.get("/v2/project-templates", response_model=list[KickoffTemplate], responses=public_errors)
    def list_project_templates(
        _principal: Principal = principal_dependency,
    ) -> list[dict[str, Any]]:
        return runtime.operations.kickoff_templates()

    @app.get("/v2/projects/{slug}", response_model=ProjectResponse, responses=public_errors)
    def get_project(slug: str, principal: Principal = principal_dependency) -> dict[str, Any]:
        return runtime.operations.get_project(slug, principal=principal)

    @app.patch("/v2/projects/{slug}", response_model=ProjectResponse, responses=public_errors)
    def update_project(
        slug: str,
        body: UpdateProjectRequest,
        command_id: str = command_dependency,
        principal: Principal = principal_dependency,
    ) -> dict[str, Any]:
        return runtime.operations.update_project(
            slug=slug,
            values=body.model_dump(exclude={"expected_version"}, exclude_unset=True),
            expected_version=body.expected_version,
            command_id=command_id,
            principal=principal,
        )

    @app.post(
        "/v2/projects/{slug}/clone",
        status_code=201,
        response_model=ProjectResponse,
        responses=public_errors,
    )
    def clone_project(
        slug: str,
        body: CloneProjectRequest,
        command_id: str = command_dependency,
        principal: Principal = principal_dependency,
    ) -> dict[str, Any]:
        return runtime.operations.clone_project(
            source_slug=slug,
            slug=body.slug,
            name=body.name,
            command_id=command_id,
            principal=principal,
        )

    @app.get(
        "/v2/projects/{slug}/status",
        response_model=ProjectStatusResponse,
        responses=public_errors,
    )
    def project_status(slug: str, principal: Principal = principal_dependency) -> dict[str, Any]:
        return runtime.operations.get_status(slug, principal=principal)

    @app.get(
        "/v2/projects/{slug}/preflight",
        response_model=PreflightResponse,
        responses=public_errors,
    )
    def project_preflight(slug: str, principal: Principal = principal_dependency) -> dict[str, Any]:
        return runtime.operations.preflight(slug, principal=principal)

    @app.post(
        "/v2/projects/{slug}/actions/{action}",
        response_model=ProjectResponse,
        responses=public_errors,
    )
    async def project_action(
        slug: str,
        action: str,
        command_id: str = command_dependency,
        principal: Principal = principal_dependency,
    ) -> dict[str, Any]:
        return await runtime.operations.apply_lifecycle(
            slug=slug,
            action=action,
            actor=principal.actor,
            command_id=command_id,
            principal=principal,
        )

    @app.post(
        "/v2/projects/{slug}/steering",
        status_code=202,
        response_model=GuidanceReceipt,
        responses=public_errors,
    )
    async def steer_project(
        slug: str,
        body: SteeringRequest,
        command_id: str = command_dependency,
        principal: Principal = principal_dependency,
    ) -> dict[str, Any]:
        return await runtime.operations.steer(
            slug=slug,
            body=body.body,
            kind=body.kind,
            actor=principal.actor,
            command_id=command_id,
            principal=principal,
        )

    @app.get("/v2/projects/{slug}/guidance", response_model=GuidancePage, responses=public_errors)
    def guidance_history(
        slug: str,
        principal: Principal = principal_dependency,
        status: str | None = Query(default=None),
        cursor: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        return runtime.operations.guidance(
            slug,
            status=status,
            cursor=cursor,
            limit=limit,
            principal=principal,
        )

    @app.get("/v2/projects/{slug}/review", response_model=ReviewResponse, responses=public_errors)
    def review_project(
        slug: str,
        principal: Principal = principal_dependency,
        cursor: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        return runtime.operations.review(slug, principal=principal, cursor=cursor, limit=limit)

    @app.get("/v2/projects/{slug}/knowledge", response_model=KnowledgePage, responses=public_errors)
    def query_knowledge(
        slug: str,
        principal: Principal = principal_dependency,
        query: str | None = Query(default=None, max_length=500),
        kind: str | None = Query(default=None),
        status: str | None = Query(default=None),
        tag: str | None = Query(default=None),
        cursor: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        return runtime.operations.query_knowledge(
            slug,
            query=query,
            kind=kind,
            status=status,
            tag=tag,
            cursor=cursor,
            limit=limit,
            principal=principal,
        )

    @app.get(
        "/v2/projects/{slug}/knowledge/graph",
        response_model=KnowledgeGraphResponse,
        responses=public_errors,
    )
    def knowledge_graph(slug: str, principal: Principal = principal_dependency) -> dict[str, Any]:
        return runtime.operations.knowledge_graph(slug, principal=principal)

    @app.post(
        "/v2/projects/{slug}/knowledge/relations",
        status_code=201,
        response_model=RelationResponse,
        responses=public_errors,
    )
    def create_relation(
        slug: str,
        body: RelationRequest,
        principal: Principal = principal_dependency,
    ) -> dict[str, Any]:
        return runtime.operations.create_relation(
            slug=slug,
            source_id=body.source_id,
            target_id=body.target_id,
            relation_type=body.type,
            description=body.description,
            principal=principal,
        )

    @app.delete(
        "/v2/projects/{slug}/knowledge/relations/{relation_id}",
        response_model=RelationResponse,
        responses=public_errors,
    )
    def delete_relation(
        slug: str, relation_id: str, principal: Principal = principal_dependency
    ) -> dict[str, Any]:
        return runtime.operations.delete_relation(slug, relation_id, principal=principal)

    @app.get(
        "/v2/projects/{slug}/knowledge/views",
        response_model=list[SavedViewResponse],
        responses=public_errors,
    )
    def saved_views(slug: str, principal: Principal = principal_dependency) -> list[dict[str, Any]]:
        return runtime.operations.saved_views(slug, principal=principal)

    @app.put(
        "/v2/projects/{slug}/knowledge/views",
        response_model=SavedViewResponse,
        responses=public_errors,
    )
    def save_view(
        slug: str,
        body: SavedViewRequest,
        principal: Principal = principal_dependency,
    ) -> dict[str, Any]:
        return runtime.operations.save_view(
            slug=slug, name=body.name, query=body.query, principal=principal
        )

    @app.delete(
        "/v2/projects/{slug}/knowledge/views/{view_id}",
        response_model=SavedViewResponse,
        responses=public_errors,
    )
    def delete_view(
        slug: str, view_id: str, principal: Principal = principal_dependency
    ) -> dict[str, Any]:
        return runtime.operations.delete_view(slug, view_id, principal=principal)

    @app.get(
        "/v2/projects/{slug}/knowledge/{artifact_id}",
        response_model=ArtifactResponse,
        responses=public_errors,
    )
    def get_knowledge(
        slug: str, artifact_id: str, principal: Principal = principal_dependency
    ) -> dict[str, Any]:
        return runtime.operations.get_knowledge(slug, artifact_id, principal=principal)

    @app.get(
        "/v2/projects/{slug}/knowledge/{artifact_id}/revisions",
        response_model=list[RevisionResponse],
        responses=public_errors,
    )
    def knowledge_revisions(
        slug: str, artifact_id: str, principal: Principal = principal_dependency
    ) -> list[dict[str, Any]]:
        return runtime.operations.revisions(slug, artifact_id, principal=principal)

    @app.get(
        "/v2/projects/{slug}/knowledge/{artifact_id}/comments",
        response_model=list[CommentResponse],
        responses=public_errors,
    )
    def knowledge_comments(
        slug: str, artifact_id: str, principal: Principal = principal_dependency
    ) -> list[dict[str, Any]]:
        return runtime.operations.comments(slug, artifact_id, principal=principal)

    @app.post(
        "/v2/projects/{slug}/knowledge/{artifact_id}/comments",
        status_code=201,
        response_model=CommentResponse,
        responses=public_errors,
    )
    def add_knowledge_comment(
        slug: str,
        artifact_id: str,
        body: CommentRequest,
        command_id: str = command_dependency,
        principal: Principal = principal_dependency,
    ) -> dict[str, Any]:
        return runtime.operations.add_comment(
            slug=slug,
            artifact_id=artifact_id,
            body=body.body,
            command_id=command_id,
            principal=principal,
        )

    @app.get(
        "/v2/projects/{slug}/knowledge/{artifact_id}/tags",
        response_model=TagResponse,
        responses=public_errors,
    )
    def knowledge_tags(
        slug: str, artifact_id: str, principal: Principal = principal_dependency
    ) -> dict[str, Any]:
        return {"tags": runtime.operations.tags(slug, artifact_id, principal=principal)}

    @app.put(
        "/v2/projects/{slug}/knowledge/{artifact_id}/tags/{tag}",
        response_model=TagResponse,
        responses=public_errors,
    )
    def add_knowledge_tag(
        slug: str,
        artifact_id: str,
        tag: str,
        principal: Principal = principal_dependency,
    ) -> dict[str, Any]:
        return {"tags": runtime.operations.add_tag(slug, artifact_id, tag, principal=principal)}

    @app.delete(
        "/v2/projects/{slug}/knowledge/{artifact_id}/tags/{tag}",
        response_model=TagResponse,
        responses=public_errors,
    )
    def remove_knowledge_tag(
        slug: str,
        artifact_id: str,
        tag: str,
        principal: Principal = principal_dependency,
    ) -> dict[str, Any]:
        return {"tags": runtime.operations.remove_tag(slug, artifact_id, tag, principal=principal)}

    @app.get("/v2/projects/{slug}/events", response_model=EventPage, responses=public_errors)
    def project_events(
        slug: str,
        principal: Principal = principal_dependency,
        after: int = Query(default=0, ge=0),
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> dict[str, Any]:
        return runtime.operations.activity(slug, after=after, limit=limit, principal=principal)

    @app.get(
        "/v2/projects/{slug}/snapshot", response_model=SnapshotResponse, responses=public_errors
    )
    def snapshot(slug: str, principal: Principal = principal_dependency) -> dict[str, Any]:
        return runtime.operations.snapshot(slug, principal=principal)

    @app.put(
        "/v2/projects/{slug}/resources/variables/{name}",
        response_model=ResourceResponse,
        response_model_exclude_none=True,
        responses=public_errors,
    )
    async def set_variable(
        slug: str,
        name: str,
        body: VariableValueRequest,
        command_id: str = command_dependency,
        principal: Principal = principal_dependency,
    ) -> dict[str, Any]:
        return await runtime.operations.set_variable(
            slug=slug,
            name=name,
            value=body.value,
            actor=principal.actor,
            command_id=command_id,
            principal=principal,
        )

    @app.put(
        "/v2/projects/{slug}/resources/secrets/{name}",
        response_model=ResourceResponse,
        response_model_exclude_none=True,
        responses=public_errors,
    )
    async def set_secret(
        slug: str,
        name: str,
        body: SecretValueRequest,
        command_id: str = command_dependency,
        principal: Principal = principal_dependency,
    ) -> dict[str, Any]:
        return await runtime.operations.set_secret(
            slug=slug,
            name=name,
            value=body.value.get_secret_value(),
            actor=principal.actor,
            command_id=command_id,
            principal=principal,
        )

    @app.get(
        "/v2/projects/{slug}/resources",
        response_model=list[ResourceResponse],
        response_model_exclude_none=True,
        responses=public_errors,
    )
    def list_resources(
        slug: str, principal: Principal = principal_dependency
    ) -> list[dict[str, Any]]:
        return runtime.operations.list_resources(slug, principal=principal)

    @app.delete(
        "/v2/projects/{slug}/resources/{name}",
        response_model=ResourceResponse,
        response_model_exclude_none=True,
        responses=public_errors,
    )
    async def remove_resource(
        slug: str,
        name: str,
        command_id: str = command_dependency,
        principal: Principal = principal_dependency,
    ) -> dict[str, Any]:
        return await runtime.operations.remove_resource(
            slug=slug,
            name=name,
            actor=principal.actor,
            command_id=command_id,
            principal=principal,
        )

    @app.get(
        "/v2/projects/{slug}/members",
        response_model=list[MemberResponse],
        responses=public_errors,
    )
    def list_members(
        slug: str, principal: Principal = principal_dependency
    ) -> list[dict[str, Any]]:
        return runtime.operations.members(slug, principal=principal)

    @app.put(
        "/v2/projects/{slug}/members",
        response_model=MemberResponse,
        responses=public_errors,
    )
    def set_member(
        slug: str,
        body: MemberRequest,
        principal: Principal = principal_dependency,
    ) -> dict[str, Any]:
        return runtime.operations.set_member(
            slug=slug,
            subject=body.subject,
            display_name=body.display_name,
            email=body.email,
            role=body.role,
            principal=principal,
        )

    @app.delete(
        "/v2/projects/{slug}/members",
        response_model=MemberResponse,
        responses=public_errors,
    )
    def remove_member(
        slug: str,
        subject: str = Query(min_length=1, max_length=300),
        principal: Principal = principal_dependency,
    ) -> dict[str, Any]:
        return runtime.operations.remove_member(slug, subject, principal=principal)

    @app.post(
        "/v2/projects/{slug}/live-ticket",
        response_model=LiveTicketResponse,
        responses=public_errors,
    )
    def live_ticket(slug: str, principal: Principal = principal_dependency) -> dict[str, Any]:
        return runtime.operations.issue_live_ticket(slug, principal=principal)

    @app.get(
        "/v2/projects/{slug}/sources",
        response_model=list[SourceResponse],
        responses=public_errors,
    )
    def list_sources(
        slug: str, principal: Principal = principal_dependency
    ) -> list[dict[str, Any]]:
        return runtime.operations.sources(slug, principal=principal)

    @app.put(
        "/v2/projects/{slug}/sources",
        response_model=SourceResponse,
        responses=public_errors,
    )
    def set_source(
        slug: str,
        body: SourceRequest,
        principal: Principal = principal_dependency,
    ) -> dict[str, Any]:
        return runtime.operations.set_source(
            slug=slug,
            name=body.name,
            source_type=body.type,
            uri=body.uri,
            media_type=body.media_type,
            metadata=body.metadata,
            principal=principal,
        )

    @app.post(
        "/v2/projects/{slug}/sources/upload",
        status_code=201,
        response_model=SourceResponse,
        responses=public_errors,
    )
    async def upload_source(
        slug: str,
        name: Annotated[str, Form(min_length=1, max_length=200)],
        file: Annotated[UploadFile, File()],
        principal: Principal = principal_dependency,
    ) -> dict[str, Any]:
        runtime.operations.collaboration.require_role(slug, principal, "EDITOR")
        limit = int(os.environ.get("LIMINA_UPLOAD_LIMIT_BYTES", str(25 * 1024 * 1024)))
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", file.filename or "source.bin").strip(".-")
        safe_name = safe_name[:160] or "source.bin"
        relative = Path(".limina") / "sources" / uuid4().hex / safe_name
        workspace = (runtime.supervisor.workspace_root / slug).resolve()
        destination = workspace / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            destination.parent.resolve().relative_to(workspace)
        except ValueError as exc:
            raise InvariantError("The project upload directory is outside its workspace.") from exc
        size = 0
        import hashlib

        digest = hashlib.sha256()
        try:
            with destination.open("xb") as output:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > limit:
                        raise InvariantError(f"Uploaded sources must be at most {limit} bytes.")
                    digest.update(chunk)
                    output.write(chunk)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return runtime.operations.set_source(
            slug=slug,
            name=name,
            source_type="UPLOAD",
            uri=f"workspace://{relative.as_posix()}",
            media_type=file.content_type,
            metadata={
                "filename": file.filename or safe_name,
                "size_bytes": size,
                "sha256": digest.hexdigest(),
            },
            principal=principal,
        )

    @app.delete(
        "/v2/projects/{slug}/sources/{source_id}",
        response_model=SourceResponse,
        responses=public_errors,
    )
    def remove_source(
        slug: str, source_id: str, principal: Principal = principal_dependency
    ) -> dict[str, Any]:
        return runtime.operations.remove_source(slug, source_id, principal=principal)

    @app.get("/v2/projects/{slug}/runs", response_model=RuntimeRunPage, responses=public_errors)
    def list_runs(
        slug: str,
        principal: Principal = principal_dependency,
        status: str | None = Query(default=None),
        cursor: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        return runtime.operations.runs(
            slug, status=status, cursor=cursor, limit=limit, principal=principal
        )

    @app.get(
        "/v2/projects/{slug}/runs/{run_id}",
        response_model=RuntimeRunDetail,
        responses=public_errors,
    )
    def get_run(
        slug: str, run_id: str, principal: Principal = principal_dependency
    ) -> dict[str, Any]:
        return runtime.operations.run(slug, run_id, principal=principal)

    @app.get(
        "/v2/projects/{slug}/analytics",
        response_model=AnalyticsResponse,
        responses=public_errors,
    )
    def project_analytics(
        slug: str,
        principal: Principal = principal_dependency,
        days: int = Query(default=30, ge=1, le=365),
    ) -> dict[str, Any]:
        return runtime.operations.analytics(slug, days=days, principal=principal)

    @app.websocket("/v2/projects/{slug}/live")
    async def project_live(websocket: WebSocket, slug: str) -> None:
        protocols = list(websocket.scope.get("subprotocols", []))
        if "limina.v2" not in protocols:
            await websocket.close(code=4400, reason="The limina.v2 subprotocol is required.")
            return
        ticket_protocols = [
            item.removeprefix("limina.ticket.")
            for item in protocols
            if item.startswith("limina.ticket.")
        ]
        if len(ticket_protocols) > 1:
            await websocket.close(code=4400, reason="Only one live ticket may be supplied.")
            return
        ticket = ticket_protocols[0] if ticket_protocols else None
        console_origin = os.environ.get("LIMINA_CONSOLE_PUBLIC_URL", "").strip().rstrip("/")
        if ticket and console_origin and websocket.headers.get("origin") != console_origin:
            await websocket.close(code=4403, reason="The live attachment origin is not allowed.")
            return
        auth_key = websocket.client.host if websocket.client else "unknown"
        try:
            auth_limiter.check(auth_key)
            if ticket:
                principal, role = runtime.operations.collaboration.consume_live_ticket(slug, ticket)
            else:
                authorization = websocket.headers.get("authorization", "")
                prefix = "Bearer "
                token_value = (
                    authorization.removeprefix(prefix) if authorization.startswith(prefix) else None
                )
                principal = runtime.authenticator.authenticate(
                    token_value,
                    actor_hint=websocket.headers.get("x-limina-actor"),
                )
                role = runtime.operations.collaboration.require_role(slug, principal, "VIEWER")
            initial = public_status(runtime.service.status(slug), role=role)
        except LiminaError as exc:
            if exc.http_status == 401 or ticket:
                auth_limiter.failure(auth_key)
            await websocket.close(
                code=4403 if exc.http_status == 403 else 4401, reason=exc.message[:120]
            )
            return
        auth_limiter.success(auth_key)
        await websocket.accept(subprotocol="limina.v2")
        cursor_text = websocket.query_params.get("after", "0")
        try:
            cursor = max(0, int(cursor_text))
        except ValueError:
            cursor = 0
        await websocket.send_json({"type": "snapshot", "value": initial})
        event_loop = asyncio.get_running_loop()
        last_role_check = event_loop.time()
        try:
            while True:
                if event_loop.time() - last_role_check >= 5.0:
                    role = runtime.operations.collaboration.require_role(slug, principal, "VIEWER")
                    last_role_check = event_loop.time()
                raw_events = runtime.service.events(slug, after=cursor, limit=200)
                for raw_event in raw_events:
                    cursor = raw_event["sequence"]
                    event = public_event(raw_event)
                    if event is not None:
                        await websocket.send_json({"type": "event", "value": event})
                try:
                    message = await asyncio.wait_for(websocket.receive_json(), timeout=0.25)
                except TimeoutError:
                    continue
                message_type = str(message.get("type", "steer")).lower()
                role = runtime.operations.collaboration.require_role(slug, principal, "VIEWER")
                last_role_check = event_loop.time()
                if role == "VIEWER":
                    raise InvariantError("Viewers can observe live work but cannot steer it.")
                if message_type == "steer":
                    body = str(message.get("body", "")).strip()
                    if not body:
                        raise InvariantError("Steering message cannot be empty.")
                    delivery = await runtime.operations.steer(
                        slug=slug,
                        body=body,
                        kind=str(message.get("kind", "STEER")),
                        actor=principal.actor,
                        command_id=str(uuid4()),
                        principal=principal,
                    )
                    await websocket.send_json(
                        {"type": "delivery", "value": delivery["delivery"], "receipt": delivery}
                    )
                elif message_type == "interrupt":
                    delivery = await runtime.operations.steer(
                        slug=slug,
                        actor=principal.actor,
                        body=str(message.get("body", "Pause and await human direction.")),
                        kind="INTERRUPT",
                        command_id=str(uuid4()),
                        principal=principal,
                    )
                    await websocket.send_json(
                        {"type": "delivery", "value": delivery["delivery"], "receipt": delivery}
                    )
                elif message_type == "action":
                    action = str(message.get("action", "")).lower()
                    state = await runtime.operations.apply_lifecycle(
                        slug=slug,
                        action=action,
                        actor=principal.actor,
                        command_id=str(uuid4()),
                        principal=principal,
                    )
                    await websocket.send_json({"type": "state", "value": state})
                else:
                    raise InvariantError(
                        "Live messages must be steer, interrupt, or action.",
                        message_type=message_type,
                    )
        except WebSocketDisconnect:
            return
        except LiminaError as exc:
            await websocket.send_json(
                {"type": "error", "value": {"code": exc.code, "message": exc.message}}
            )

    register_internal_agent_routes(
        app,
        runtime,
        internal_actor=internal_actor,
        internal_command_id=internal_command_id,
    )

    return app
