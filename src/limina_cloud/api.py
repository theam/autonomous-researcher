"""Public control plane for Limina-owned collaborative project runtimes."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from . import __version__
from .database import Database
from .errors import AuthenticationError, InvariantError, LiminaError
from .exporter import MarkdownExporter
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


def _public_project(project: dict[str, Any]) -> dict[str, Any]:
    coordinator = project["coordinator"]
    return {
        "slug": project["slug"],
        "name": project["name"],
        "mission": project["objective"],
        "success_criteria": project["success_criteria"],
        "context": project["context"],
        "status": "ARCHIVED" if project["status"] == "ARCHIVED" else coordinator["status"],
        "current_objective": coordinator["current_objective"],
        "next_step": coordinator["next_step"],
        "blocker": coordinator["blocker"],
        "created_at": project["created_at"],
        "updated_at": coordinator["updated_at"],
    }


def _public_status(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "project": _public_project(status["challenge"]),
        "knowledge": status["counts"],
        "active_work": [_public_artifact(item) for item in status["running_experiments"]],
        "pending_guidance": status["pending_inbox"],
        "event_cursor": status["last_event_sequence"],
    }


def _public_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    result = {
        "id": artifact["id"],
        "kind": artifact["kind"],
        "title": artifact["title"],
        "status": artifact["status"],
        "content": artifact["payload"],
        "hypothesis_id": artifact.get("hypothesis_id"),
        "experiment_id": artifact.get("experiment_id"),
        "created_at": artifact["created_at"],
        "updated_at": artifact["updated_at"],
    }
    if "observations" in artifact:
        result["observations"] = artifact["observations"]
    return result


def _public_resource(resource: dict[str, Any]) -> dict[str, Any]:
    result = {
        "name": resource["name"],
        "type": resource["type"],
        "status": resource["status"],
        "created_at": resource["created_at"],
        "updated_at": resource["updated_at"],
    }
    if resource["type"] == "VARIABLE":
        result["value"] = resource["value"]
    else:
        result["configured"] = resource["configured"]
    return result


def _public_event(event: dict[str, Any]) -> dict[str, Any] | None:
    event_type = event["type"]
    if event_type in {"coordinator.claimed", "coordinator.released"}:
        return None
    aliases = {
        "challenge.created": "project.created",
        "coordinator.checkpointed": "project.checkpoint",
        "inbox.message_sent": "guidance.received",
        "inbox.message_acknowledged": "guidance.incorporated",
    }
    payload = {
        key: value
        for key, value in event["payload"].items()
        if key
        not in {
            "worker_id",
            "thread_id",
            "turn_id",
            "version",
            "expires_at",
            "message_id",
        }
    }
    actor = event["actor"]
    if actor.startswith("limina:"):
        actor = "Limina"
    if event_type == "runtime.codex" and "limina _agent" in str(payload.get("summary", "")):
        payload["summary"] = "Updating durable project knowledge"
    return {
        "sequence": event["sequence"],
        "type": aliases.get(event_type, event_type),
        "actor": actor,
        "artifact_id": event.get("artifact_id"),
        "detail": payload,
        "created_at": event["created_at"],
    }


def create_app(
    *,
    database_url: str | None = None,
    token: str | None = None,
    workspace_root: Path | None = None,
    agent_factory: AgentFactory | None = None,
    poll_interval: float = 1.0,
    internal_url: str | None = None,
    secret_key_path: Path | None = None,
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

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
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

    @app.exception_handler(LiminaError)
    async def handle_limina_error(_request: Request, exc: LiminaError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

    def require_auth(authorization: Annotated[str | None, Header()] = None) -> None:
        if runtime.token is not None and authorization != f"Bearer {runtime.token}":
            raise AuthenticationError()

    def command_headers(
        x_limina_actor: Annotated[str, Header(min_length=1)],
        idempotency_key: Annotated[str, Header(min_length=1)],
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
        idempotency_key: Annotated[str, Header(min_length=1)],
    ) -> str:
        return idempotency_key

    async def apply_lifecycle(
        slug: str, action: str, actor: str, command_id: str
    ) -> dict[str, Any]:
        project = runtime.service.change_project_state(
            slug=slug,
            action=action,
            actor=actor,
            command_id=command_id,
        )
        if action in {"start", "resume"}:
            await runtime.supervisor.ensure_running(slug)
        elif action in {"pause", "stop", "archive"}:
            await runtime.supervisor.stop_runtime(slug)
        return _public_project(project)

    @app.get("/healthz")
    def health(_auth: None = Depends(require_auth)) -> dict[str, Any]:
        return {"ok": True, "version": __version__, "runtime_owner": "limina"}

    @app.post("/v1/projects", status_code=201)
    def create_project(
        body: CreateProjectRequest,
        headers: tuple[str, str] = Depends(command_headers),
        _auth: None = Depends(require_auth),
    ) -> dict[str, Any]:
        actor, command_id = headers
        project = runtime.service.create_challenge(
            **body.model_dump(), actor=actor, command_id=command_id
        )
        return _public_project(project)

    @app.get("/v1/projects")
    def list_projects(
        _auth: None = Depends(require_auth),
        include_archived: bool = Query(default=False),
    ) -> list[dict[str, Any]]:
        return [
            _public_project(project)
            for project in runtime.service.list_projects(include_archived=include_archived)
        ]

    @app.get("/v1/projects/{slug}")
    def get_project(slug: str, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        return _public_project(runtime.service.get_challenge(slug))

    @app.get("/v1/projects/{slug}/status")
    def project_status(slug: str, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        return _public_status(runtime.service.status(slug))

    @app.post("/v1/projects/{slug}/actions/{action}")
    async def project_action(
        slug: str,
        action: str,
        headers: tuple[str, str] = Depends(command_headers),
        _auth: None = Depends(require_auth),
    ) -> dict[str, Any]:
        actor, command_id = headers
        return await apply_lifecycle(slug, action, actor, command_id)

    @app.post("/v1/projects/{slug}/steering", status_code=202)
    async def steer_project(
        slug: str,
        body: SteeringRequest,
        headers: tuple[str, str] = Depends(command_headers),
        _auth: None = Depends(require_auth),
    ) -> dict[str, Any]:
        actor, command_id = headers
        if body.kind.upper() == "INTERRUPT":
            result = await runtime.supervisor.interrupt(slug, actor=actor, reason=body.body)
        else:
            result = await runtime.supervisor.submit_message(
                slug=slug,
                body=body.body,
                kind=body.kind,
                actor=actor,
                command_id=command_id,
            )
        message = result["message"]
        return {
            "delivery": result["delivery"],
            "kind": message["kind"],
            "accepted_at": message["created_at"],
        }

    @app.get("/v1/projects/{slug}/review")
    def review_project(slug: str, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        status = runtime.service.status(slug)
        artifacts = runtime.service.list_artifacts(slug)
        events = runtime.service.events(slug, after=0, limit=1000)
        public_events = [item for event in events if (item := _public_event(event)) is not None]
        return {
            **_public_status(status),
            "resources": [_public_resource(item) for item in runtime.service.list_resources(slug)],
            "hypotheses": [_public_artifact(item) for item in artifacts if item["kind"] == "H"],
            "experiments": [_public_artifact(item) for item in artifacts if item["kind"] == "E"],
            "findings": [_public_artifact(item) for item in artifacts if item["kind"] == "F"],
            "recent_activity": public_events[-50:],
        }

    @app.get("/v1/projects/{slug}/knowledge/{artifact_id}")
    def get_knowledge(
        slug: str, artifact_id: str, _auth: None = Depends(require_auth)
    ) -> dict[str, Any]:
        return _public_artifact(runtime.service.get_artifact(slug, artifact_id))

    @app.get("/v1/projects/{slug}/events")
    def project_events(
        slug: str,
        _auth: None = Depends(require_auth),
        after: int = Query(default=0, ge=0),
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> dict[str, Any]:
        events = runtime.service.events(slug, after=after, limit=limit)
        public = [item for event in events if (item := _public_event(event)) is not None]
        return {"events": public, "cursor": events[-1]["sequence"] if events else after}

    @app.get("/v1/projects/{slug}/snapshot")
    def snapshot(slug: str, _auth: None = Depends(require_auth)) -> dict[str, Any]:
        return {"files": runtime.exporter.snapshot(slug)}

    @app.put("/v1/projects/{slug}/resources/variables/{name}")
    async def set_variable(
        slug: str,
        name: str,
        body: VariableValueRequest,
        headers: tuple[str, str] = Depends(command_headers),
        _auth: None = Depends(require_auth),
    ) -> dict[str, Any]:
        actor, command_id = headers
        resource = runtime.service.set_variable(
            slug=slug,
            name=name,
            value=body.value,
            actor=actor,
            command_id=command_id,
        )
        await runtime.supervisor.submit_message(
            slug=slug,
            body=f"Project variable '{resource['name']}' was set and is now available.",
            kind="ANSWER",
            actor=actor,
            command_id=f"{command_id}:resource",
        )
        project = runtime.service.get_challenge(slug)
        if project["coordinator"]["status"] in {"RUNNING", "WAITING"}:
            await runtime.supervisor.ensure_running(slug)
        return _public_resource(resource)

    @app.put("/v1/projects/{slug}/resources/secrets/{name}")
    async def set_secret(
        slug: str,
        name: str,
        body: SecretValueRequest,
        headers: tuple[str, str] = Depends(command_headers),
        _auth: None = Depends(require_auth),
    ) -> dict[str, Any]:
        actor, command_id = headers
        resource = runtime.service.set_secret(
            slug=slug,
            name=name,
            value=body.value.get_secret_value(),
            actor=actor,
            command_id=command_id,
        )
        await runtime.supervisor.submit_message(
            slug=slug,
            body=f"Project secret '{resource['name']}' was set and is now available.",
            kind="ANSWER",
            actor=actor,
            command_id=f"{command_id}:resource",
        )
        project = runtime.service.get_challenge(slug)
        if project["coordinator"]["status"] in {"RUNNING", "WAITING"}:
            await runtime.supervisor.ensure_running(slug)
        return _public_resource(resource)

    @app.get("/v1/projects/{slug}/resources")
    def list_resources(slug: str, _auth: None = Depends(require_auth)) -> list[dict[str, Any]]:
        return [_public_resource(item) for item in runtime.service.list_resources(slug)]

    @app.delete("/v1/projects/{slug}/resources/{name}")
    async def remove_resource(
        slug: str,
        name: str,
        headers: tuple[str, str] = Depends(command_headers),
        _auth: None = Depends(require_auth),
    ) -> dict[str, Any]:
        actor, command_id = headers
        resource = runtime.service.remove_resource(
            slug=slug,
            name=name,
            actor=actor,
            command_id=command_id,
        )
        await runtime.supervisor.submit_message(
            slug=slug,
            body=f"Resource '{resource['name']}' has been revoked.",
            kind="STEER",
            actor=actor,
            command_id=f"{command_id}:resource",
        )
        project = runtime.service.get_challenge(slug)
        if project["coordinator"]["status"] in {"RUNNING", "WAITING"}:
            await runtime.supervisor.ensure_running(slug)
        return _public_resource(resource)

    @app.websocket("/v1/projects/{slug}/live")
    async def project_live(websocket: WebSocket, slug: str) -> None:
        authorization = websocket.headers.get("authorization")
        if runtime.token is not None and authorization != f"Bearer {runtime.token}":
            await websocket.close(code=4401, reason="Authentication required")
            return
        actor = websocket.headers.get("x-limina-actor", "anonymous")
        try:
            initial = _public_status(runtime.service.status(slug))
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
                    event = _public_event(raw_event)
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
                    state = await apply_lifecycle(slug, action, actor, str(uuid4()))
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
