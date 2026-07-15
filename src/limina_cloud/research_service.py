"""H → E → F research commands mixed into the transactional challenge service."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from .errors import InvariantError, NotFoundError
from .models import Artifact, Observation, WorkLease, utcnow

ARTIFACT_ID_RE = re.compile(r"^(H|E|F|L|CR|SR)\d{3,}$")


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _iso(value: datetime | str) -> str:
    if isinstance(value, str):
        return value
    return _aware(value).isoformat()


class ResearchServiceMixin:
    def create_hypothesis(
        self,
        *,
        slug: str,
        title: str,
        statement: str,
        mechanism: str,
        generalization: str,
        shortcut_risks: str,
        test_plan: str,
        actor: str,
        command_id: str,
    ) -> dict[str, Any]:
        self._require_text("title", title)
        self._require_text("statement", statement)

        def operation(session: Session) -> dict[str, Any]:
            challenge = self._challenge(session, slug)
            artifact = Artifact(
                challenge_id=challenge.id,
                artifact_id=self._allocate_artifact_id(session, challenge.id, "H"),
                kind="H",
                title=title.strip(),
                status="PROPOSED",
                payload={
                    "statement": statement.strip(),
                    "mechanism": mechanism.strip(),
                    "generalization": generalization.strip(),
                    "shortcut_risks": shortcut_risks.strip(),
                    "test_plan": test_plan.strip(),
                    "conclusion": "",
                },
                created_by=actor,
            )
            session.add(artifact)
            session.flush()
            self._record_revision(session, artifact, actor, command_id)
            self._record_event(
                session,
                challenge=challenge,
                event_type="hypothesis.created",
                actor=actor,
                command_id=command_id,
                artifact_id=artifact.artifact_id,
                payload={"title": artifact.title},
            )
            return self._artifact_dict(artifact)

        return self._execute(command_id, "hypothesis.create", actor, operation)

    def decide_hypothesis(
        self,
        *,
        slug: str,
        artifact_id: str,
        status: str,
        conclusion: str,
        expected_version: int,
        actor: str,
        command_id: str,
    ) -> dict[str, Any]:
        status = status.upper()
        if status not in {"CONFIRMED", "REJECTED", "TESTING"}:
            raise InvariantError("Hypothesis status must be CONFIRMED, REJECTED, or TESTING.")
        self._require_text("conclusion", conclusion)

        def operation(session: Session) -> dict[str, Any]:
            challenge = self._challenge(session, slug)
            artifact = self._artifact(session, challenge.id, artifact_id, kind="H")
            payload = dict(artifact.payload)
            payload["conclusion"] = conclusion.strip()
            self._cas_artifact(
                session,
                artifact,
                expected_version=expected_version,
                status=status,
                payload=payload,
                actor=actor,
                command_id=command_id,
            )
            self._record_event(
                session,
                challenge=challenge,
                event_type="hypothesis.decided",
                actor=actor,
                command_id=command_id,
                artifact_id=artifact.artifact_id,
                payload={"status": status, "version": artifact.version},
            )
            return self._artifact_dict(artifact)

        return self._execute(command_id, "hypothesis.decide", actor, operation)

    def create_experiment(
        self,
        *,
        slug: str,
        hypothesis_id: str,
        title: str,
        objective: str,
        procedure: str,
        success_criteria: str,
        guardrails: str,
        actor: str,
        command_id: str,
    ) -> dict[str, Any]:
        self._require_text("title", title)
        self._require_text("objective", objective)

        def operation(session: Session) -> dict[str, Any]:
            challenge = self._challenge(session, slug)
            hypothesis = self._artifact(session, challenge.id, hypothesis_id, kind="H")
            transitioned = session.execute(
                update(Artifact)
                .where(
                    Artifact.uid == hypothesis.uid,
                    Artifact.status == "PROPOSED",
                )
                .values(
                    status="TESTING",
                    version=Artifact.version + 1,
                    updated_at=utcnow(),
                )
            )
            if transitioned.rowcount == 1:
                session.flush()
                session.refresh(hypothesis)
                self._record_revision(session, hypothesis, actor, command_id)
            else:
                accepts_experiment = session.execute(
                    update(Artifact)
                    .where(
                        Artifact.uid == hypothesis.uid,
                        Artifact.status == "TESTING",
                    )
                    .values(updated_at=Artifact.updated_at)
                )
                if accepts_experiment.rowcount != 1:
                    session.refresh(hypothesis)
                    raise InvariantError(
                        f"Cannot add an experiment to {hypothesis.artifact_id} "
                        f"because it is {hypothesis.status}.",
                        artifact_id=hypothesis.artifact_id,
                        status=hypothesis.status,
                    )

            artifact = Artifact(
                challenge_id=challenge.id,
                artifact_id=self._allocate_artifact_id(session, challenge.id, "E"),
                kind="E",
                title=title.strip(),
                status="DESIGNED",
                payload={
                    "objective": objective.strip(),
                    "procedure": procedure.strip(),
                    "success_criteria": success_criteria.strip(),
                    "guardrails": guardrails.strip(),
                    "results": "",
                    "analysis": "",
                    "decision": "",
                    "completed_at": None,
                },
                parent_hypothesis_id=hypothesis.artifact_id,
                created_by=actor,
            )
            session.add(artifact)
            session.flush()
            self._record_revision(session, artifact, actor, command_id)

            self._record_event(
                session,
                challenge=challenge,
                event_type="experiment.created",
                actor=actor,
                command_id=command_id,
                artifact_id=artifact.artifact_id,
                payload={"hypothesis_id": hypothesis.artifact_id, "title": artifact.title},
            )
            return self._artifact_dict(artifact)

        return self._execute(command_id, "experiment.create", actor, operation)

    def claim_experiment(
        self,
        *,
        slug: str,
        artifact_id: str,
        ttl_seconds: int,
        actor: str,
        command_id: str,
    ) -> dict[str, Any]:
        if ttl_seconds < 30 or ttl_seconds > 86_400:
            raise InvariantError("Lease TTL must be between 30 seconds and 24 hours.")

        def operation(session: Session) -> dict[str, Any]:
            challenge = self._challenge(session, slug)
            artifact = self._artifact(session, challenge.id, artifact_id, kind="E")
            if artifact.status not in {"DESIGNED", "RUNNING"}:
                raise InvariantError(
                    f"Cannot claim {artifact.artifact_id} while it is {artifact.status}.",
                    artifact_id=artifact.artifact_id,
                    status=artifact.status,
                )

            now = utcnow()
            lease = self._acquire_lease(
                session,
                challenge_id=challenge.id,
                scope=artifact.artifact_id,
                owner=actor,
                ttl_seconds=ttl_seconds,
            )

            if artifact.status == "DESIGNED":
                artifact.status = "RUNNING"
                artifact.version += 1
                artifact.updated_at = now
                self._record_revision(session, artifact, actor, command_id)
            self._record_event(
                session,
                challenge=challenge,
                event_type="experiment.claimed",
                actor=actor,
                command_id=command_id,
                artifact_id=artifact.artifact_id,
                payload={"expires_at": _iso(lease["expires_at"])},
            )
            return {
                "artifact": self._artifact_dict(artifact),
                "lease": {
                    "owner": lease["owner"],
                    "token": lease["token"],
                    "expires_at": _iso(lease["expires_at"]),
                    "version": lease["version"],
                },
            }

        return self._execute(command_id, "experiment.claim", actor, operation)

    def append_observation(
        self,
        *,
        slug: str,
        artifact_id: str,
        body: str,
        evidence_ref: str | None,
        actor: str,
        command_id: str,
    ) -> dict[str, Any]:
        self._require_text("observation", body)

        def operation(session: Session) -> dict[str, Any]:
            challenge = self._challenge(session, slug)
            artifact = self._artifact(session, challenge.id, artifact_id, kind="E")
            if artifact.status != "RUNNING":
                raise InvariantError(
                    f"Observations require a RUNNING experiment; "
                    f"{artifact.artifact_id} is {artifact.status}.",
                    artifact_id=artifact.artifact_id,
                    status=artifact.status,
                )
            self._require_active_lease(session, challenge.id, artifact.artifact_id, actor)
            observation = Observation(
                challenge_id=challenge.id,
                experiment_id=artifact.artifact_id,
                body=body.strip(),
                evidence_ref=evidence_ref.strip() if evidence_ref else None,
                actor=actor,
                command_id=command_id,
            )
            session.add(observation)
            session.flush()
            self._record_event(
                session,
                challenge=challenge,
                event_type="experiment.observed",
                actor=actor,
                command_id=command_id,
                artifact_id=artifact.artifact_id,
                payload={
                    "observation_id": observation.id,
                    "evidence_ref": observation.evidence_ref,
                },
            )
            return self._observation_dict(observation)

        return self._execute(command_id, "experiment.observe", actor, operation)

    def complete_experiment(
        self,
        *,
        slug: str,
        artifact_id: str,
        results: str,
        analysis: str,
        decision: str,
        expected_version: int,
        actor: str,
        command_id: str,
    ) -> dict[str, Any]:
        self._require_text("results", results)
        self._require_text("analysis", analysis)
        self._require_text("decision", decision)

        def operation(session: Session) -> dict[str, Any]:
            challenge = self._challenge(session, slug)
            artifact = self._artifact(session, challenge.id, artifact_id, kind="E")
            if artifact.status != "RUNNING":
                raise InvariantError(
                    f"Only a RUNNING experiment can complete; "
                    f"{artifact.artifact_id} is {artifact.status}.",
                    artifact_id=artifact.artifact_id,
                    status=artifact.status,
                )
            self._require_active_lease(session, challenge.id, artifact.artifact_id, actor)
            payload = dict(artifact.payload)
            payload.update(
                {
                    "results": results.strip(),
                    "analysis": analysis.strip(),
                    "decision": decision.strip(),
                    "completed_at": utcnow().date().isoformat(),
                }
            )
            self._cas_artifact(
                session,
                artifact,
                expected_version=expected_version,
                status="COMPLETED",
                payload=payload,
                actor=actor,
                command_id=command_id,
            )
            session.execute(
                delete(WorkLease).where(
                    WorkLease.challenge_id == challenge.id,
                    WorkLease.scope == artifact.artifact_id,
                    WorkLease.owner == actor,
                )
            )
            self._record_event(
                session,
                challenge=challenge,
                event_type="experiment.completed",
                actor=actor,
                command_id=command_id,
                artifact_id=artifact.artifact_id,
                payload={"version": artifact.version},
            )
            return self._artifact_dict(artifact)

        return self._execute(command_id, "experiment.complete", actor, operation)

    def publish_finding(
        self,
        *,
        slug: str,
        experiment_id: str,
        title: str,
        finding: str,
        evidence: str,
        improvement: str,
        remaining_debt: str,
        next_move: str,
        impact: str,
        actor: str,
        command_id: str,
    ) -> dict[str, Any]:
        self._require_text("title", title)
        self._require_text("finding", finding)
        self._require_text("evidence", evidence)
        impact = impact.upper()
        if impact not in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}:
            raise InvariantError("Impact must be CRITICAL, HIGH, MEDIUM, or LOW.")

        def operation(session: Session) -> dict[str, Any]:
            challenge = self._challenge(session, slug)
            experiment = self._artifact(session, challenge.id, experiment_id, kind="E")
            if experiment.status != "COMPLETED":
                raise InvariantError(
                    f"Cannot publish a finding before {experiment.artifact_id} is COMPLETED.",
                    artifact_id=experiment.artifact_id,
                    status=experiment.status,
                )
            hypothesis = self._artifact(
                session, challenge.id, experiment.parent_hypothesis_id or "", kind="H"
            )
            artifact = Artifact(
                challenge_id=challenge.id,
                artifact_id=self._allocate_artifact_id(session, challenge.id, "F"),
                kind="F",
                title=title.strip(),
                status="PUBLISHED",
                payload={
                    "finding": finding.strip(),
                    "evidence": evidence.strip(),
                    "improvement": improvement.strip(),
                    "remaining_debt": remaining_debt.strip(),
                    "next_move": next_move.strip(),
                    "impact": impact,
                },
                parent_hypothesis_id=hypothesis.artifact_id,
                parent_experiment_id=experiment.artifact_id,
                created_by=actor,
            )
            session.add(artifact)
            session.flush()
            self._record_revision(session, artifact, actor, command_id)
            self._record_event(
                session,
                challenge=challenge,
                event_type="finding.published",
                actor=actor,
                command_id=command_id,
                artifact_id=artifact.artifact_id,
                payload={
                    "hypothesis_id": hypothesis.artifact_id,
                    "experiment_id": experiment.artifact_id,
                    "impact": impact,
                },
            )
            return self._artifact_dict(artifact)

        return self._execute(command_id, "finding.publish", actor, operation)

    def get_artifact(self, slug: str, artifact_id: str) -> dict[str, Any]:
        if not ARTIFACT_ID_RE.fullmatch(artifact_id.upper()):
            raise NotFoundError(
                f"Artifact '{artifact_id}' does not exist.", artifact_id=artifact_id
            )
        with self.database.session() as session:
            challenge = self._challenge(session, slug)
            artifact = self._artifact(session, challenge.id, artifact_id.upper())
            result = self._artifact_dict(artifact)
            if artifact.kind == "E":
                observations = session.scalars(
                    select(Observation)
                    .where(
                        Observation.challenge_id == challenge.id,
                        Observation.experiment_id == artifact.artifact_id,
                    )
                    .order_by(Observation.created_at, Observation.id)
                ).all()
                result["observations"] = [self._observation_dict(item) for item in observations]
                lease = session.get(WorkLease, (challenge.id, artifact.artifact_id))
                if lease is not None and _aware(lease.expires_at) > utcnow():
                    result["lease"] = self._lease_dict(lease)
            return result

    def list_artifacts(self, slug: str, kind: str | None = None) -> list[dict[str, Any]]:
        with self.database.session() as session:
            challenge = self._challenge(session, slug)
            statement = select(Artifact).where(Artifact.challenge_id == challenge.id)
            if kind:
                statement = statement.where(Artifact.kind == kind.upper())
            artifacts = session.scalars(statement.order_by(Artifact.artifact_id)).all()
            return [self._artifact_dict(item) for item in artifacts]
