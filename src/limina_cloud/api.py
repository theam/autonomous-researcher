"""Public control plane for Limina-owned collaborative project runtimes."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from secrets import compare_digest
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from . import __version__
from .database import Database
from .engines import SUPPORTED_RUNTIME_ENGINES
from .errors import AuthenticationError, InvariantError, LiminaError
from .exporter import MarkdownExporter
from .mcp import create_mcp_server
from .operations import (
    ACTOR_LIMIT,
    PUBLIC_COMMAND_ID_LIMIT,
    ProjectOperations,
    public_event,
    public_status,
)
from .runtime import AgentFactory, ProjectSupervisor
from .service import ChallengeService
from .vault import SecretCipher


class CommandModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateProjectRequest(CommandModel):
    slug: str
    name: str
    objective: str
    success_criteria: str
    context: str = ""
    runtime: Literal["codex", "claude-code"] = "codex"


class SteeringRequest(CommandModel):
    body: str
    kind: str = "STEER"


class VariableValueRequest(CommandModel):
    value: str = Field(min_length=1, max_length=32_768)


class SecretValueRequest(CommandModel):
    value: SecretStr = Field(min_length=1, max_length=32_768)


class HypothesisRequest(CommandModel):
    title: str
    statement: str
    mechanism: str = ""
    generalization: str = ""
    shortcut_risks: str = ""
    test_plan: str = ""


class HypothesisDecisionRequest(CommandModel):
    status: str
    conclusion: str
    expected_version: int = Field(ge=1)


class ExperimentRequest(CommandModel):
    hypothesis_id: str
    title: str
    objective: str
    procedure: str = ""
    success_criteria: str = ""
    guardrails: str = ""


class ExperimentClaimRequest(CommandModel):
    ttl_seconds: int = Field(default=1800, ge=30, le=86_400)


class ObservationRequest(CommandModel):
    body: str
    evidence_ref: str | None = None


class ExperimentCompletionRequest(CommandModel):
    results: str
    analysis: str
    decision: str
    expected_version: int = Field(ge=1)


class FindingRequest(CommandModel):
    experiment_id: str
    title: str
    finding: str
    evidence: str
    improvement: str = ""
    remaining_debt: str = ""
    next_move: str = ""
    impact: str = "HIGH"


class RuntimeContext:
    def __init__(
        self,
        database: Database,
        token: str | None,
        *,
        workspace_root: Path,
        agent_factory: AgentFactory | None,
        poll_interval: float,
        internal_url: str,
        secret_key_path: Path,
    ) -> None:
        self.database = database
        self.service = ChallengeService(database, SecretCipher.load(secret_key_path))
        self.exporter = MarkdownExporter(self.service)
        self.token = token
        self.supervisor = ProjectSupervisor(
            self.service,
            self.exporter,
            workspace_root=workspace_root,
            internal_url=internal_url,
            agent_factory=agent_factory,
            poll_interval=poll_interval,
        )
        self.operations = ProjectOperations(self.service, self.exporter, self.supervisor)


def create_app(
    *,
    database_url: str | None = None,
    token: str | None = None,
    workspace_root: Path | None = None,
    agent_factory: AgentFactory | None = None,
    poll_interval: float = 1.0,
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
    runtime = RuntimeContext(
        database,
        token if token is not None else os.environ.get("LIMINA_API_TOKEN"),
        workspace_root=resolved_workspace,
        agent_factory=agent_factory,
        poll_interval=poll_interval,
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
        token=runtime.token,
        allowed_hosts=[item.strip() for item in allowed_hosts if item.strip()],
        allowed_origins=[item.strip() for item in allowed_origins if item.strip()],
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        async with mcp_server.session_manager.run():
            await runtime.supervisor.recover()
            try:
                yield
            finally:
                await runtime.supervisor.shutdown()

    app = FastAPI(
        title="Limina Project Runtime",
        version=__version__,
        description=(
            "Mission, review, resource, steering, and lifecycle control for Limina-owned runtimes."
        ),
        lifespan=lifespan,
    )
    app.state.runtime = runtime
    app.state.mcp = mcp_server
    app.mount("/mcp", mcp_app, name="mcp")
    bearer = HTTPBearer(auto_error=False)
    bearer_dependency = Depends(bearer)

    @app.exception_handler(LiminaError)
    async def handle_limina_error(_request: Request, exc: LiminaError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

    def require_auth(
        credentials: HTTPAuthorizationCredentials | None = bearer_dependency,
    ) -> None:
        if runtime.token is not None and (
            credentials is None or not compare_digest(credentials.credentials, runtime.token)
        ):
            raise AuthenticationError()

    def command_headers(
        x_limina_actor: Annotated[str, Header(min_length=1, max_length=ACTOR_LIMIT)],
        idempotency_key: Annotated[str, Header(min_length=1, max_length=PUBLIC_COMMAND_ID_LIMIT)],
    ) -> tuple[str, str]:
        return x_limina_actor, idempotency_key

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

    @app.get("/healthz")
    def health(_auth: None = Depends(require_auth)) -> dict[str, Any]:
        return {
            "ok": True,
            "version": __version__,
            "runtime_owner": "limina",
            "runtimes": list(SUPPORTED_RUNTIME_ENGINES),
            "interfaces": {"rest": "/v1", "mcp": "/mcp/"},
        }

    @app.post("/v1/projects", status_code=201)
    def create_project(
        body: CreateProjectRequest,
        headers: tuple[str, str] = Depends(command_headers),
        _auth: None = Depends(require_auth),
    ) -> dict[str, Any]:
        actor, command_id = headers
        return runtime.operations.create_project(
            slug=body.slug,
            name=body.name,
            mission=body.objective,
            success_criteria=body.success_criteria,
            context=body.context,
            runtime=body.runtime,
            actor=actor,
            command_id=command_id,
        )

    @app.get("/v1/projects")
    def list_projects(
        _auth: None = Depends(require_auth),
        include_archived: bool = Query(default=False),
    ) -> list[dict[str, Any]]:
        return runtime.operations.list_projects(include_archived=include_archived)

    @app.get("/v1/projects/{slug}")
    def get_project(slug: str, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        return runtime.operations.get_project(slug)

    @app.get("/v1/projects/{slug}/status")
    def project_status(slug: str, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        return runtime.operations.get_status(slug)

    @app.post("/v1/projects/{slug}/actions/{action}")
    async def project_action(
        slug: str,
        action: str,
        headers: tuple[str, str] = Depends(command_headers),
        _auth: None = Depends(require_auth),
    ) -> dict[str, Any]:
        actor, command_id = headers
        return await runtime.operations.apply_lifecycle(
            slug=slug, action=action, actor=actor, command_id=command_id
        )

    @app.post("/v1/projects/{slug}/steering", status_code=202)
    async def steer_project(
        slug: str,
        body: SteeringRequest,
        headers: tuple[str, str] = Depends(command_headers),
        _auth: None = Depends(require_auth),
    ) -> dict[str, Any]:
        actor, command_id = headers
        return await runtime.operations.steer(
            slug=slug,
            body=body.body,
            kind=body.kind,
            actor=actor,
            command_id=command_id,
        )

    @app.get("/v1/projects/{slug}/review")
    def review_project(slug: str, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        return runtime.operations.review(slug)

    @app.get("/v1/projects/{slug}/knowledge/{artifact_id}")
    def get_knowledge(
        slug: str, artifact_id: str, _auth: None = Depends(require_auth)
    ) -> dict[str, Any]:
        return runtime.operations.get_knowledge(slug, artifact_id)

    @app.get("/v1/projects/{slug}/events")
    def project_events(
        slug: str,
        _auth: None = Depends(require_auth),
        after: int = Query(default=0, ge=0),
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> dict[str, Any]:
        return runtime.operations.activity(slug, after=after, limit=limit)

    @app.get("/v1/projects/{slug}/snapshot")
    def snapshot(slug: str, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        return runtime.operations.snapshot(slug)

    @app.put("/v1/projects/{slug}/resources/variables/{name}")
    async def set_variable(
        slug: str,
        name: str,
        body: VariableValueRequest,
        headers: tuple[str, str] = Depends(command_headers),
        _auth: None = Depends(require_auth),
    ) -> dict[str, Any]:
        actor, command_id = headers
        return await runtime.operations.set_variable(
            slug=slug,
            name=name,
            value=body.value,
            actor=actor,
            command_id=command_id,
        )

    @app.put("/v1/projects/{slug}/resources/secrets/{name}")
    async def set_secret(
        slug: str,
        name: str,
        body: SecretValueRequest,
        headers: tuple[str, str] = Depends(command_headers),
        _auth: None = Depends(require_auth),
    ) -> dict[str, Any]:
        actor, command_id = headers
        return await runtime.operations.set_secret(
            slug=slug,
            name=name,
            value=body.value.get_secret_value(),
            actor=actor,
            command_id=command_id,
        )

    @app.get("/v1/projects/{slug}/resources")
    def list_resources(slug: str, _auth: None = Depends(require_auth)) -> list[dict[str, Any]]:
        return runtime.operations.list_resources(slug)

    @app.delete("/v1/projects/{slug}/resources/{name}")
    async def remove_resource(
        slug: str,
        name: str,
        headers: tuple[str, str] = Depends(command_headers),
        _auth: None = Depends(require_auth),
    ) -> dict[str, Any]:
        actor, command_id = headers
        return await runtime.operations.remove_resource(
            slug=slug,
            name=name,
            actor=actor,
            command_id=command_id,
        )

    @app.websocket("/v1/projects/{slug}/live")
    async def project_live(websocket: WebSocket, slug: str) -> None:
        authorization = websocket.headers.get("authorization")
        if runtime.token is not None and authorization != f"Bearer {runtime.token}":
            await websocket.close(code=4401, reason="Authentication required")
            return
        actor = websocket.headers.get("x-limina-actor", "anonymous")
        if len(actor) > ACTOR_LIMIT:
            await websocket.close(code=4400, reason="Actor identity is too long")
            return
        try:
            initial = public_status(runtime.service.status(slug))
        except LiminaError as exc:
            await websocket.close(code=4404, reason=exc.message[:120])
            return
        await websocket.accept()
        cursor_text = websocket.query_params.get("after", "0")
        try:
            cursor = max(0, int(cursor_text))
        except ValueError:
            cursor = 0
        await websocket.send_json({"type": "snapshot", "value": initial})
        try:
            while True:
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
                if message_type == "steer":
                    body = str(message.get("body", "")).strip()
                    if not body:
                        raise InvariantError("Steering message cannot be empty.")
                    delivery = await runtime.supervisor.submit_message(
                        slug=slug,
                        body=body,
                        kind=str(message.get("kind", "STEER")),
                        actor=actor,
                    )
                    await websocket.send_json({"type": "delivery", "value": delivery["delivery"]})
                elif message_type == "interrupt":
                    delivery = await runtime.supervisor.interrupt(
                        slug,
                        actor=actor,
                        reason=str(message.get("body", "Pause and await human direction.")),
                    )
                    await websocket.send_json({"type": "delivery", "value": delivery["delivery"]})
                elif message_type == "action":
                    action = str(message.get("action", "")).lower()
                    state = await runtime.operations.apply_lifecycle(
                        slug=slug,
                        action=action,
                        actor=actor,
                        command_id=str(uuid4()),
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

    @app.get("/internal/v1/projects/{slug}/status", include_in_schema=False)
    def internal_status(slug: str, _actor: str = Depends(internal_actor)) -> dict[str, Any]:
        return runtime.service.status(slug)

    @app.get("/internal/v1/projects/{slug}/artifacts", include_in_schema=False)
    def internal_artifacts(
        slug: str,
        _actor: str = Depends(internal_actor),
        kind: str | None = Query(default=None),
    ) -> list[dict[str, Any]]:
        return runtime.service.list_artifacts(slug, kind)

    @app.get("/internal/v1/projects/{slug}/artifacts/{artifact_id}", include_in_schema=False)
    def internal_artifact(
        slug: str,
        artifact_id: str,
        _actor: str = Depends(internal_actor),
    ) -> dict[str, Any]:
        return runtime.service.get_artifact(slug, artifact_id)

    @app.post("/internal/v1/projects/{slug}/hypotheses", status_code=201, include_in_schema=False)
    def internal_create_hypothesis(
        slug: str,
        body: HypothesisRequest,
        actor: str = Depends(internal_actor),
        command_id: str = Depends(internal_command_id),
    ) -> dict[str, Any]:
        return runtime.service.create_hypothesis(
            slug=slug,
            **body.model_dump(),
            actor=actor,
            command_id=command_id,
        )

    @app.post(
        "/internal/v1/projects/{slug}/hypotheses/{artifact_id}/decision",
        include_in_schema=False,
    )
    def internal_decide_hypothesis(
        slug: str,
        artifact_id: str,
        body: HypothesisDecisionRequest,
        actor: str = Depends(internal_actor),
        command_id: str = Depends(internal_command_id),
    ) -> dict[str, Any]:
        return runtime.service.decide_hypothesis(
            slug=slug,
            artifact_id=artifact_id,
            **body.model_dump(),
            actor=actor,
            command_id=command_id,
        )

    @app.post("/internal/v1/projects/{slug}/experiments", status_code=201, include_in_schema=False)
    def internal_create_experiment(
        slug: str,
        body: ExperimentRequest,
        actor: str = Depends(internal_actor),
        command_id: str = Depends(internal_command_id),
    ) -> dict[str, Any]:
        return runtime.service.create_experiment(
            slug=slug,
            **body.model_dump(),
            actor=actor,
            command_id=command_id,
        )

    @app.post(
        "/internal/v1/projects/{slug}/experiments/{artifact_id}/claim",
        include_in_schema=False,
    )
    def internal_claim_experiment(
        slug: str,
        artifact_id: str,
        body: ExperimentClaimRequest,
        actor: str = Depends(internal_actor),
        command_id: str = Depends(internal_command_id),
    ) -> dict[str, Any]:
        return runtime.service.claim_experiment(
            slug=slug,
            artifact_id=artifact_id,
            ttl_seconds=body.ttl_seconds,
            actor=actor,
            command_id=command_id,
        )

    @app.post(
        "/internal/v1/projects/{slug}/experiments/{artifact_id}/observations",
        status_code=201,
        include_in_schema=False,
    )
    def internal_observe_experiment(
        slug: str,
        artifact_id: str,
        body: ObservationRequest,
        actor: str = Depends(internal_actor),
        command_id: str = Depends(internal_command_id),
    ) -> dict[str, Any]:
        return runtime.service.append_observation(
            slug=slug,
            artifact_id=artifact_id,
            **body.model_dump(),
            actor=actor,
            command_id=command_id,
        )

    @app.post(
        "/internal/v1/projects/{slug}/experiments/{artifact_id}/complete",
        include_in_schema=False,
    )
    def internal_complete_experiment(
        slug: str,
        artifact_id: str,
        body: ExperimentCompletionRequest,
        actor: str = Depends(internal_actor),
        command_id: str = Depends(internal_command_id),
    ) -> dict[str, Any]:
        return runtime.service.complete_experiment(
            slug=slug,
            artifact_id=artifact_id,
            **body.model_dump(),
            actor=actor,
            command_id=command_id,
        )

    @app.post("/internal/v1/projects/{slug}/findings", status_code=201, include_in_schema=False)
    def internal_publish_finding(
        slug: str,
        body: FindingRequest,
        actor: str = Depends(internal_actor),
        command_id: str = Depends(internal_command_id),
    ) -> dict[str, Any]:
        return runtime.service.publish_finding(
            slug=slug,
            **body.model_dump(),
            actor=actor,
            command_id=command_id,
        )

    return app
