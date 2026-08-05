"""Private project-scoped research protocol routes for managed agents."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Query

from .schemas import (
    ExperimentClaimRequest,
    ExperimentCompletionRequest,
    ExperimentRequest,
    FindingRequest,
    HypothesisDecisionRequest,
    HypothesisRequest,
    ObservationRequest,
)


def register_internal_agent_routes(
    app: FastAPI,
    runtime: Any,
    *,
    internal_actor: Any,
    internal_command_id: Any,
) -> None:
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
