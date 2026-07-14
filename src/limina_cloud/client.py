"""Public project client and the private agent-side research client."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

import httpx

from .database import Database
from .errors import (
    AuthenticationError,
    ConflictError,
    InvariantError,
    LeaseConflictError,
    LiminaError,
    NotFoundError,
    TransportError,
)
from .exporter import MarkdownExporter
from .service import ChallengeService

ERROR_TYPES: dict[str, type[LiminaError]] = {
    "not_found": NotFoundError,
    "version_conflict": ConflictError,
    "invariant_violation": InvariantError,
    "lease_conflict": LeaseConflictError,
    "authentication_required": AuthenticationError,
}


class PublicRuntimeClient(Protocol):
    def health(self) -> dict[str, Any]: ...
    def create_project(
        self, payload: dict[str, Any], *, actor: str, command_id: str
    ) -> dict[str, Any]: ...
    def projects(self, *, include_archived: bool = False) -> list[dict[str, Any]]: ...
    def project(self, slug: str) -> dict[str, Any]: ...
    def project_status(self, slug: str) -> dict[str, Any]: ...
    def project_action(
        self, slug: str, action: str, *, actor: str, command_id: str
    ) -> dict[str, Any]: ...
    def steer_project(
        self, slug: str, payload: dict[str, Any], *, actor: str, command_id: str
    ) -> dict[str, Any]: ...
    def review(self, slug: str) -> dict[str, Any]: ...
    def knowledge(self, slug: str, artifact_id: str) -> dict[str, Any]: ...
    def activity(self, slug: str, *, after: int, limit: int) -> dict[str, Any]: ...
    def set_variable(
        self, slug: str, name: str, value: str, *, actor: str, command_id: str
    ) -> dict[str, Any]: ...
    def set_secret(
        self, slug: str, name: str, value: str, *, actor: str, command_id: str
    ) -> dict[str, Any]: ...
    def resources(self, slug: str) -> list[dict[str, Any]]: ...
    def remove_resource(
        self, slug: str, name: str, *, actor: str, command_id: str
    ) -> dict[str, Any]: ...
    def snapshot(self, slug: str) -> dict[str, str]: ...
    def close(self) -> None: ...


class LocalRuntimeClient:
    def __init__(self, database_url: str) -> None:
        self.database = Database(database_url)
        self.database.initialize()
        self.service = ChallengeService(self.database)
        self.exporter = MarkdownExporter(self.service)

    def health(self) -> dict[str, Any]:
        return {"ok": True, "mode": "embedded", "backend": self.database.engine.dialect.name}

    def status(self, slug: str) -> dict[str, Any]:
        return self.service.status(slug)

    def artifacts(self, slug: str, kind: str | None = None) -> list[dict[str, Any]]:
        return self.service.list_artifacts(slug, kind)

    def artifact(self, slug: str, artifact_id: str) -> dict[str, Any]:
        return self.service.get_artifact(slug, artifact_id)

    def create_hypothesis(
        self, slug: str, payload: dict[str, Any], *, actor: str, command_id: str
    ) -> dict[str, Any]:
        return self.service.create_hypothesis(
            slug=slug, **payload, actor=actor, command_id=command_id
        )

    def decide_hypothesis(
        self, slug: str, artifact_id: str, payload: dict[str, Any], *, actor: str, command_id: str
    ) -> dict[str, Any]:
        return self.service.decide_hypothesis(
            slug=slug, artifact_id=artifact_id, **payload, actor=actor, command_id=command_id
        )

    def create_experiment(
        self, slug: str, payload: dict[str, Any], *, actor: str, command_id: str
    ) -> dict[str, Any]:
        return self.service.create_experiment(
            slug=slug, **payload, actor=actor, command_id=command_id
        )

    def claim_experiment(
        self, slug: str, artifact_id: str, payload: dict[str, Any], *, actor: str, command_id: str
    ) -> dict[str, Any]:
        return self.service.claim_experiment(
            slug=slug, artifact_id=artifact_id, **payload, actor=actor, command_id=command_id
        )

    def observe_experiment(
        self, slug: str, artifact_id: str, payload: dict[str, Any], *, actor: str, command_id: str
    ) -> dict[str, Any]:
        return self.service.append_observation(
            slug=slug, artifact_id=artifact_id, **payload, actor=actor, command_id=command_id
        )

    def complete_experiment(
        self, slug: str, artifact_id: str, payload: dict[str, Any], *, actor: str, command_id: str
    ) -> dict[str, Any]:
        return self.service.complete_experiment(
            slug=slug, artifact_id=artifact_id, **payload, actor=actor, command_id=command_id
        )

    def publish_finding(
        self, slug: str, payload: dict[str, Any], *, actor: str, command_id: str
    ) -> dict[str, Any]:
        return self.service.publish_finding(
            slug=slug, **payload, actor=actor, command_id=command_id
        )

    def snapshot(self, slug: str) -> dict[str, str]:
        return self.exporter.snapshot(slug)

    def close(self) -> None:
        self.database.dispose()


class HttpRuntimeClient:
    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        agent_lane: str | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        if agent_lane:
            headers["X-Limina-Agent-Lane"] = agent_lane
        self.client = httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=30.0)

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/healthz")

    def create_project(
        self, payload: dict[str, Any], *, actor: str, command_id: str
    ) -> dict[str, Any]:
        return self._request("POST", "/v1/projects", payload, actor, command_id)

    def projects(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {
                "include_archived": str(include_archived).lower(),
                "limit": 200,
            }
            if cursor:
                params["cursor"] = cursor
            page = self._request("GET", "/v1/projects", params=params)
            items.extend(page["items"])
            cursor = page.get("next_cursor")
            if not cursor:
                return items

    def project(self, slug: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/projects/{slug}")

    def project_status(self, slug: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/projects/{slug}/status")

    def project_action(
        self, slug: str, action: str, *, actor: str, command_id: str
    ) -> dict[str, Any]:
        return self._request("POST", f"/v1/projects/{slug}/actions/{action}", {}, actor, command_id)

    def steer_project(
        self, slug: str, payload: dict[str, Any], *, actor: str, command_id: str
    ) -> dict[str, Any]:
        return self._request("POST", f"/v1/projects/{slug}/steering", payload, actor, command_id)

    def review(self, slug: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/projects/{slug}/review")

    def knowledge(self, slug: str, artifact_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/projects/{slug}/knowledge/{artifact_id}")

    def activity(self, slug: str, *, after: int, limit: int) -> dict[str, Any]:
        return self._request(
            "GET", f"/v1/projects/{slug}/events", params={"after": after, "limit": limit}
        )

    def set_variable(
        self, slug: str, name: str, value: str, *, actor: str, command_id: str
    ) -> dict[str, Any]:
        return self._request(
            "PUT",
            f"/v1/projects/{slug}/resources/variables/{name}",
            {"value": value},
            actor,
            command_id,
        )

    def set_secret(
        self, slug: str, name: str, value: str, *, actor: str, command_id: str
    ) -> dict[str, Any]:
        return self._request(
            "PUT",
            f"/v1/projects/{slug}/resources/secrets/{name}",
            {"value": value},
            actor,
            command_id,
        )

    def resources(self, slug: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/v1/projects/{slug}/resources")

    def remove_resource(
        self, slug: str, name: str, *, actor: str, command_id: str
    ) -> dict[str, Any]:
        return self._request(
            "DELETE", f"/v1/projects/{slug}/resources/{name}", None, actor, command_id
        )

    def status(self, slug: str) -> dict[str, Any]:
        return self._request("GET", f"/internal/v1/projects/{slug}/status")

    def artifacts(self, slug: str, kind: str | None = None) -> list[dict[str, Any]]:
        params = {"kind": kind} if kind else None
        return self._request("GET", f"/internal/v1/projects/{slug}/artifacts", params=params)

    def artifact(self, slug: str, artifact_id: str) -> dict[str, Any]:
        return self._request("GET", f"/internal/v1/projects/{slug}/artifacts/{artifact_id}")

    def create_hypothesis(
        self, slug: str, payload: dict[str, Any], *, actor: str, command_id: str
    ) -> dict[str, Any]:
        return self._request(
            "POST", f"/internal/v1/projects/{slug}/hypotheses", payload, actor, command_id
        )

    def decide_hypothesis(
        self, slug: str, artifact_id: str, payload: dict[str, Any], *, actor: str, command_id: str
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/internal/v1/projects/{slug}/hypotheses/{artifact_id}/decision",
            payload,
            actor,
            command_id,
        )

    def create_experiment(
        self, slug: str, payload: dict[str, Any], *, actor: str, command_id: str
    ) -> dict[str, Any]:
        return self._request(
            "POST", f"/internal/v1/projects/{slug}/experiments", payload, actor, command_id
        )

    def claim_experiment(
        self, slug: str, artifact_id: str, payload: dict[str, Any], *, actor: str, command_id: str
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/internal/v1/projects/{slug}/experiments/{artifact_id}/claim",
            payload,
            actor,
            command_id,
        )

    def observe_experiment(
        self, slug: str, artifact_id: str, payload: dict[str, Any], *, actor: str, command_id: str
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/internal/v1/projects/{slug}/experiments/{artifact_id}/observations",
            payload,
            actor,
            command_id,
        )

    def complete_experiment(
        self, slug: str, artifact_id: str, payload: dict[str, Any], *, actor: str, command_id: str
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/internal/v1/projects/{slug}/experiments/{artifact_id}/complete",
            payload,
            actor,
            command_id,
        )

    def publish_finding(
        self, slug: str, payload: dict[str, Any], *, actor: str, command_id: str
    ) -> dict[str, Any]:
        return self._request(
            "POST", f"/internal/v1/projects/{slug}/findings", payload, actor, command_id
        )

    def snapshot(self, slug: str) -> dict[str, str]:
        result = self._request("GET", f"/v1/projects/{slug}/snapshot")
        return result["files"]

    def close(self) -> None:
        self.client.close()

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        actor: str | None = None,
        command_id: str | None = None,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        headers: dict[str, str] = {}
        if actor is not None:
            headers["X-Limina-Actor"] = actor
        if command_id is not None:
            headers["Idempotency-Key"] = command_id
        try:
            response = self.client.request(
                method, path, json=payload, headers=headers, params=params
            )
        except httpx.HTTPError as exc:
            raise TransportError(
                f"Cannot reach Limina runtime at {self.client.base_url}.",
                reason=str(exc),
            ) from exc
        if response.is_success:
            return response.json()
        try:
            error = response.json().get("error", {})
        except ValueError as exc:
            raise TransportError(
                f"Runtime returned HTTP {response.status_code} without a valid error body."
            ) from exc
        code = error.get("code", "transport_error")
        message = error.get("message", f"Runtime returned HTTP {response.status_code}.")
        details = error.get("details", {})
        error_type = ERROR_TYPES.get(code)
        if error_type is NotFoundError:
            raise NotFoundError(message, **details)
        if error_type is ConflictError:
            raise ConflictError(message, **details)
        if error_type is InvariantError:
            raise InvariantError(message, **details)
        if error_type is LeaseConflictError:
            raise LeaseConflictError(message, **details)
        if error_type is AuthenticationError:
            raise AuthenticationError(message)
        raise TransportError(message, status=response.status_code, **details)


def write_snapshot(files: dict[str, str], target: Path) -> list[Path]:
    if target.exists() and any(target.iterdir()):
        raise ConflictError(
            f"Export target '{target}' is not empty.",
            target=str(target),
            suggestion="Choose an empty directory so stale artifacts cannot survive the export.",
        )
    written: list[Path] = []
    for relative, content in sorted(files.items()):
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written
