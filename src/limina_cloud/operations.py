"""Public project operations shared by Limina's API transports.

The database service owns research invariants and the supervisor owns managed
execution.  This layer composes the two into the project-level capabilities
that people and external agents are allowed to use.  HTTP and MCP should stay
thin adapters over this contract.
"""

from __future__ import annotations

from typing import Any

from .exporter import MarkdownExporter
from .runtime import ProjectSupervisor
from .service import ChallengeService

ACTOR_LIMIT = 200
# Command receipts store 64 characters; composed operations reserve room for ":resource".
PUBLIC_COMMAND_ID_LIMIT = 55


def public_project(project: dict[str, Any]) -> dict[str, Any]:
    coordinator = project["coordinator"]
    return {
        "slug": project["slug"],
        "name": project["name"],
        "mission": project["objective"],
        "success_criteria": project["success_criteria"],
        "context": project["context"],
        "runtime": project["runtime_engine"],
        "status": "ARCHIVED" if project["status"] == "ARCHIVED" else coordinator["status"],
        "current_objective": coordinator["current_objective"],
        "next_step": coordinator["next_step"],
        "blocker": coordinator["blocker"],
        "created_at": project["created_at"],
        "updated_at": coordinator["updated_at"],
    }


def public_status(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "project": public_project(status["challenge"]),
        "knowledge": status["counts"],
        "active_work": [public_artifact(item) for item in status["running_experiments"]],
        "pending_guidance": status["pending_inbox"],
        "event_cursor": status["last_event_sequence"],
    }


def public_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
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


def public_resource(resource: dict[str, Any]) -> dict[str, Any]:
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


def public_event(event: dict[str, Any]) -> dict[str, Any] | None:
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
            "continuation_id",
            "turn_id",
            "version",
            "expires_at",
            "message_id",
        }
    }
    actor = event["actor"]
    if actor.startswith("limina:"):
        actor = "Limina"
    if event_type == "challenge.created" and "runtime_engine" in payload:
        payload["runtime"] = payload.pop("runtime_engine")
    if event_type in {"runtime.codex", "runtime.claude-code"} and "limina _agent" in str(
        payload.get("summary", "")
    ):
        payload["summary"] = "Updating durable project knowledge"
    return {
        "sequence": event["sequence"],
        "type": aliases.get(event_type, event_type),
        "actor": actor,
        "artifact_id": event.get("artifact_id"),
        "detail": payload,
        "created_at": event["created_at"],
    }


class ProjectOperations:
    """The stable, provider-neutral collaboration contract."""

    def __init__(
        self,
        service: ChallengeService,
        exporter: MarkdownExporter,
        supervisor: ProjectSupervisor,
    ) -> None:
        self.service = service
        self.exporter = exporter
        self.supervisor = supervisor

    def create_project(
        self,
        *,
        slug: str,
        name: str,
        mission: str,
        success_criteria: str,
        context: str,
        runtime: str,
        actor: str,
        command_id: str,
    ) -> dict[str, Any]:
        project = self.service.create_challenge(
            slug=slug,
            name=name,
            objective=mission,
            success_criteria=success_criteria,
            context=context,
            runtime_engine=runtime,
            actor=actor,
            command_id=command_id,
        )
        return public_project(project)

    def list_projects(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        return [
            public_project(project)
            for project in self.service.list_projects(include_archived=include_archived)
        ]

    def get_project(self, slug: str) -> dict[str, Any]:
        return public_project(self.service.get_challenge(slug))

    def get_status(self, slug: str) -> dict[str, Any]:
        return public_status(self.service.status(slug))

    async def apply_lifecycle(
        self, *, slug: str, action: str, actor: str, command_id: str
    ) -> dict[str, Any]:
        project = self.service.change_project_state(
            slug=slug,
            action=action,
            actor=actor,
            command_id=command_id,
        )
        if action.lower() in {"start", "resume"}:
            await self.supervisor.ensure_running(slug)
        elif action.lower() in {"pause", "stop", "archive"}:
            await self.supervisor.stop_runtime(slug)
        return public_project(project)

    async def steer(
        self,
        *,
        slug: str,
        body: str,
        kind: str,
        actor: str,
        command_id: str,
    ) -> dict[str, Any]:
        if kind.upper() == "INTERRUPT":
            result = await self.supervisor.interrupt(
                slug,
                actor=actor,
                reason=body,
                command_id=command_id,
            )
        else:
            result = await self.supervisor.submit_message(
                slug=slug,
                body=body,
                kind=kind,
                actor=actor,
                command_id=command_id,
            )
        message = result["message"]
        return {
            "delivery": result["delivery"],
            "kind": message["kind"],
            "accepted_at": message["created_at"],
        }

    def review(self, slug: str) -> dict[str, Any]:
        status = self.service.status(slug)
        artifacts = self.service.list_artifacts(slug)
        events = self.service.events(slug, after=0, limit=1000)
        public_events = [item for event in events if (item := public_event(event)) is not None]
        return {
            **public_status(status),
            "resources": [public_resource(item) for item in self.service.list_resources(slug)],
            "hypotheses": [public_artifact(item) for item in artifacts if item["kind"] == "H"],
            "experiments": [public_artifact(item) for item in artifacts if item["kind"] == "E"],
            "findings": [public_artifact(item) for item in artifacts if item["kind"] == "F"],
            "recent_activity": public_events[-50:],
        }

    def get_knowledge(self, slug: str, artifact_id: str) -> dict[str, Any]:
        return public_artifact(self.service.get_artifact(slug, artifact_id))

    def activity(self, slug: str, *, after: int = 0, limit: int = 200) -> dict[str, Any]:
        events = self.service.events(slug, after=after, limit=limit)
        visible = [item for event in events if (item := public_event(event)) is not None]
        return {"events": visible, "cursor": events[-1]["sequence"] if events else after}

    def snapshot(self, slug: str) -> dict[str, Any]:
        return {"files": self.exporter.snapshot(slug)}

    async def set_variable(
        self,
        *,
        slug: str,
        name: str,
        value: str,
        actor: str,
        command_id: str,
    ) -> dict[str, Any]:
        resource = self.service.set_variable(
            slug=slug,
            name=name,
            value=value,
            actor=actor,
            command_id=command_id,
        )
        await self._resource_changed(
            slug=slug,
            body=f"Project variable '{resource['name']}' was set.",
            kind="ANSWER",
            actor=actor,
            command_id=command_id,
        )
        return public_resource(resource)

    async def set_secret(
        self,
        *,
        slug: str,
        name: str,
        value: str,
        actor: str,
        command_id: str,
    ) -> dict[str, Any]:
        resource = self.service.set_secret(
            slug=slug,
            name=name,
            value=value,
            actor=actor,
            command_id=command_id,
        )
        await self._resource_changed(
            slug=slug,
            body=f"Project secret '{resource['name']}' was set.",
            kind="ANSWER",
            actor=actor,
            command_id=command_id,
        )
        return public_resource(resource)

    def list_resources(self, slug: str) -> list[dict[str, Any]]:
        return [public_resource(item) for item in self.service.list_resources(slug)]

    async def remove_resource(
        self, *, slug: str, name: str, actor: str, command_id: str
    ) -> dict[str, Any]:
        resource = self.service.remove_resource(
            slug=slug,
            name=name,
            actor=actor,
            command_id=command_id,
        )
        await self._resource_changed(
            slug=slug,
            body=f"Resource '{resource['name']}' has been revoked.",
            kind="STEER",
            actor=actor,
            command_id=command_id,
        )
        return public_resource(resource)

    async def _resource_changed(
        self,
        *,
        slug: str,
        body: str,
        kind: str,
        actor: str,
        command_id: str,
    ) -> None:
        await self.supervisor.submit_message(
            slug=slug,
            body=body,
            kind=kind,
            actor=actor,
            command_id=f"{command_id}:resource",
            live_delivery=False,
        )
        await self.supervisor.refresh_resources(slug)
        project = self.service.get_challenge(slug)
        if project["coordinator"]["status"] in {"RUNNING", "WAITING"}:
            await self.supervisor.ensure_running(slug)
