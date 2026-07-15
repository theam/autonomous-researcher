"""Knowledge graph, review, saved-view, and project-source collaboration surfaces."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Text, cast, func, or_, select
from sqlalchemy.exc import IntegrityError

from .errors import ConflictError, InvariantError, NotFoundError
from .models import (
    Artifact,
    ArtifactComment,
    ArtifactRevision,
    ArtifactTag,
    KnowledgeRelation,
    ProjectSource,
    SavedKnowledgeView,
    utcnow,
)

SOURCE_TYPES = {"URL", "CONNECTOR", "UPLOAD"}
RELATION_TYPE_LIMIT = 80


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _page_offset(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        return max(0, int(base64.urlsafe_b64decode(cursor + "===").decode("ascii")))
    except (ValueError, UnicodeDecodeError):
        raise InvariantError("The pagination cursor is invalid.") from None


def _next_cursor(offset: int, count: int, total: int) -> str | None:
    next_offset = offset + count
    if next_offset >= total:
        return None
    return base64.urlsafe_b64encode(str(next_offset).encode("ascii")).decode("ascii").rstrip("=")


class KnowledgeCollaborationMixin:
    def query_knowledge(
        self,
        slug: str,
        *,
        query: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        tag: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        offset = _page_offset(cursor)
        limit = min(max(limit, 1), 200)
        with self.database.session() as session:
            challenge = self._challenge(session, slug)
            filters: list[Any] = [Artifact.challenge_id == challenge.id]
            if kind:
                filters.append(Artifact.kind == kind.upper())
            if status:
                filters.append(Artifact.status == status.upper())
            if tag:
                filters.append(
                    Artifact.artifact_id.in_(
                        select(ArtifactTag.artifact_id).where(
                            ArtifactTag.challenge_id == challenge.id,
                            ArtifactTag.tag == self._normalize_tag(tag),
                        )
                    )
                )
            statement = select(Artifact)
            if query and query.strip():
                text_query = query.strip()
                if self.database.engine.dialect.name == "postgresql":
                    document = func.to_tsvector(
                        "simple",
                        func.coalesce(Artifact.title, "")
                        + " "
                        + func.coalesce(cast(Artifact.payload, Text), ""),
                    )
                    ts_query = func.websearch_to_tsquery("simple", text_query)
                    filters.append(document.op("@@")(ts_query))
                    statement = statement.order_by(func.ts_rank_cd(document, ts_query).desc())
                else:
                    normalized_query = text_query.lower()
                    filters.append(
                        or_(
                            func.lower(Artifact.title).contains(normalized_query, autoescape=True),
                            func.lower(cast(Artifact.payload, Text)).contains(
                                normalized_query, autoescape=True
                            ),
                        )
                    )
            total = session.scalar(select(func.count()).select_from(Artifact).where(*filters)) or 0
            rows = session.scalars(
                statement.where(*filters)
                .order_by(Artifact.updated_at.desc(), Artifact.artifact_id)
                .offset(offset)
                .limit(limit)
            ).all()
            tags = self._tags_by_artifact(
                session, challenge.id, [item.artifact_id for item in rows]
            )
            return {
                "items": [
                    self._artifact_dict(item, tags=tags.get(item.artifact_id, [])) for item in rows
                ],
                "next_cursor": _next_cursor(offset, len(rows), total),
                "total": total,
                "search_backend": "postgresql-fts"
                if self.database.engine.dialect.name == "postgresql"
                else "portable-substring",
            }

    def revisions(self, slug: str, artifact_id: str) -> list[dict[str, Any]]:
        with self.database.session() as session:
            challenge = self._challenge(session, slug)
            artifact = self._artifact(session, challenge.id, artifact_id)
            rows = session.scalars(
                select(ArtifactRevision)
                .where(ArtifactRevision.artifact_uid == artifact.uid)
                .order_by(ArtifactRevision.version.desc())
            ).all()
            return [
                {
                    "version": row.version,
                    "status": row.status,
                    "title": row.title,
                    "content": dict(row.payload),
                    "actor": row.actor,
                    "created_at": _iso(row.created_at),
                }
                for row in rows
            ]

    def graph(self, slug: str) -> dict[str, Any]:
        with self.database.session() as session:
            challenge = self._challenge(session, slug)
            artifacts = session.scalars(
                select(Artifact)
                .where(Artifact.challenge_id == challenge.id)
                .order_by(Artifact.artifact_id)
            ).all()
            explicit = session.scalars(
                select(KnowledgeRelation)
                .where(KnowledgeRelation.challenge_id == challenge.id)
                .order_by(KnowledgeRelation.created_at, KnowledgeRelation.id)
            ).all()
            tags = self._tags_by_artifact(
                session, challenge.id, [item.artifact_id for item in artifacts]
            )
            edges = [self._relation_dict(item, derived=False) for item in explicit]
            for item in artifacts:
                if item.parent_hypothesis_id:
                    edges.append(
                        self._derived_relation(
                            item.parent_hypothesis_id, item.artifact_id, "TESTED_BY"
                        )
                    )
                if item.parent_experiment_id:
                    edges.append(
                        self._derived_relation(item.parent_experiment_id, item.artifact_id, "FOUND")
                    )
            return {
                "nodes": [
                    self._artifact_dict(item, tags=tags.get(item.artifact_id, []))
                    for item in artifacts
                ],
                "edges": edges,
            }

    def create_relation(
        self,
        *,
        slug: str,
        source_id: str,
        target_id: str,
        relation_type: str,
        description: str,
        actor: str,
    ) -> dict[str, Any]:
        relation_type = relation_type.strip().upper().replace(" ", "_")
        if not relation_type or len(relation_type) > RELATION_TYPE_LIMIT:
            raise InvariantError("Relation type must be 1 to 80 characters.")
        if source_id == target_id:
            raise InvariantError("A knowledge relation cannot point to itself.")
        with self.database.session() as session, session.begin():
            challenge = self._challenge(session, slug)
            self._artifact(session, challenge.id, source_id)
            self._artifact(session, challenge.id, target_id)
            relation = KnowledgeRelation(
                challenge_id=challenge.id,
                source_artifact_id=source_id,
                target_artifact_id=target_id,
                relation_type=relation_type,
                description=description.strip(),
                created_by=actor,
            )
            session.add(relation)
            try:
                session.flush()
            except IntegrityError as exc:
                raise ConflictError("That knowledge relation already exists.") from exc
            self._event(
                session,
                challenge,
                "knowledge.relation_created",
                actor,
                {"relation_id": relation.id, "source_id": source_id, "target_id": target_id},
                artifact_id=source_id,
            )
            return self._relation_dict(relation, derived=False)

    def delete_relation(self, slug: str, relation_id: str, *, actor: str) -> dict[str, Any]:
        with self.database.session() as session, session.begin():
            challenge = self._challenge(session, slug)
            relation = session.scalar(
                select(KnowledgeRelation).where(
                    KnowledgeRelation.challenge_id == challenge.id,
                    KnowledgeRelation.id == relation_id,
                )
            )
            if relation is None:
                raise NotFoundError("Knowledge relation does not exist.")
            result = self._relation_dict(relation, derived=False)
            session.delete(relation)
            self._event(
                session,
                challenge,
                "knowledge.relation_removed",
                actor,
                {"relation_id": relation_id},
                artifact_id=relation.source_artifact_id,
            )
            return result

    def comments(self, slug: str, artifact_id: str) -> list[dict[str, Any]]:
        with self.database.session() as session:
            challenge = self._challenge(session, slug)
            artifact = self._artifact(session, challenge.id, artifact_id)
            rows = session.scalars(
                select(ArtifactComment)
                .where(
                    ArtifactComment.challenge_id == challenge.id,
                    ArtifactComment.artifact_id == artifact.artifact_id,
                )
                .order_by(ArtifactComment.created_at)
            ).all()
            return [self._comment_dict(item) for item in rows]

    def add_comment(
        self,
        *,
        slug: str,
        artifact_id: str,
        body: str,
        actor: str,
        command_id: str,
    ) -> dict[str, Any]:
        body = self._required("comment", body)
        if len(body) > 32_768:
            raise InvariantError("Comment must be at most 32768 characters.")
        try:
            with self.database.session() as session, session.begin():
                challenge = self._challenge(session, slug)
                artifact = self._artifact(session, challenge.id, artifact_id)
                existing = session.scalar(
                    select(ArtifactComment).where(ArtifactComment.command_id == command_id)
                )
                if existing is not None:
                    return self._validated_comment_replay(
                        existing,
                        challenge_id=challenge.id,
                        artifact_id=artifact.artifact_id,
                        actor=actor,
                        command_id=command_id,
                    )
                comment = ArtifactComment(
                    challenge_id=challenge.id,
                    artifact_id=artifact.artifact_id,
                    body=body,
                    actor=actor,
                    command_id=command_id,
                )
                session.add(comment)
                session.flush()
                self._event(
                    session,
                    challenge,
                    "knowledge.comment_added",
                    actor,
                    {"comment_id": comment.id},
                    artifact_id=artifact.artifact_id,
                    command_id=command_id,
                )
                return self._comment_dict(comment)
        except IntegrityError as exc:
            with self.database.session() as retry_session:
                challenge = self._challenge(retry_session, slug)
                artifact = self._artifact(retry_session, challenge.id, artifact_id)
                existing = retry_session.scalar(
                    select(ArtifactComment).where(ArtifactComment.command_id == command_id)
                )
                if existing is not None:
                    return self._validated_comment_replay(
                        existing,
                        challenge_id=challenge.id,
                        artifact_id=artifact.artifact_id,
                        actor=actor,
                        command_id=command_id,
                    )
            raise ConflictError(
                "The comment conflicted with another concurrent write.",
                command_id=command_id,
            ) from exc

    def tags(self, slug: str, artifact_id: str) -> list[str]:
        with self.database.session() as session:
            challenge = self._challenge(session, slug)
            self._artifact(session, challenge.id, artifact_id)
            return list(
                session.scalars(
                    select(ArtifactTag.tag)
                    .where(
                        ArtifactTag.challenge_id == challenge.id,
                        ArtifactTag.artifact_id == artifact_id.upper(),
                    )
                    .order_by(ArtifactTag.tag)
                ).all()
            )

    def add_tag(self, slug: str, artifact_id: str, tag: str, *, actor: str) -> list[str]:
        tag = self._normalize_tag(tag)
        with self.database.session() as session, session.begin():
            challenge = self._challenge(session, slug)
            artifact = self._artifact(session, challenge.id, artifact_id)
            if session.get(ArtifactTag, (challenge.id, artifact.artifact_id, tag)) is None:
                session.add(
                    ArtifactTag(
                        challenge_id=challenge.id,
                        artifact_id=artifact.artifact_id,
                        tag=tag,
                        created_by=actor,
                    )
                )
                self._event(
                    session,
                    challenge,
                    "knowledge.tag_added",
                    actor,
                    {"tag": tag},
                    artifact_id=artifact.artifact_id,
                )
            session.flush()
            return list(
                session.scalars(
                    select(ArtifactTag.tag)
                    .where(
                        ArtifactTag.challenge_id == challenge.id,
                        ArtifactTag.artifact_id == artifact.artifact_id,
                    )
                    .order_by(ArtifactTag.tag)
                ).all()
            )

    def remove_tag(self, slug: str, artifact_id: str, tag: str, *, actor: str) -> list[str]:
        tag = self._normalize_tag(tag)
        with self.database.session() as session, session.begin():
            challenge = self._challenge(session, slug)
            artifact = self._artifact(session, challenge.id, artifact_id)
            item = session.get(ArtifactTag, (challenge.id, artifact.artifact_id, tag))
            if item is None:
                raise NotFoundError("Knowledge tag does not exist.", tag=tag)
            session.delete(item)
            self._event(
                session,
                challenge,
                "knowledge.tag_removed",
                actor,
                {"tag": tag},
                artifact_id=artifact.artifact_id,
            )
            session.flush()
            return list(
                session.scalars(
                    select(ArtifactTag.tag)
                    .where(
                        ArtifactTag.challenge_id == challenge.id,
                        ArtifactTag.artifact_id == artifact.artifact_id,
                    )
                    .order_by(ArtifactTag.tag)
                ).all()
            )

    def saved_views(self, slug: str) -> list[dict[str, Any]]:
        with self.database.session() as session:
            challenge = self._challenge(session, slug)
            rows = session.scalars(
                select(SavedKnowledgeView)
                .where(SavedKnowledgeView.challenge_id == challenge.id)
                .order_by(SavedKnowledgeView.name)
            ).all()
            return [self._view_dict(item) for item in rows]

    def save_view(
        self, *, slug: str, name: str, query: dict[str, Any], actor: str
    ) -> dict[str, Any]:
        name = self._required("view name", name)
        allowed = {"query", "kind", "status", "tag"}
        if set(query) - allowed:
            raise InvariantError("Saved view query contains unsupported filters.")
        if len(json.dumps(query, ensure_ascii=False)) > 8192:
            raise InvariantError("Saved view query is too large.")
        with self.database.session() as session, session.begin():
            challenge = self._challenge(session, slug)
            view = session.scalar(
                select(SavedKnowledgeView).where(
                    SavedKnowledgeView.challenge_id == challenge.id,
                    SavedKnowledgeView.name == name,
                )
            )
            if view is None:
                view = SavedKnowledgeView(
                    challenge_id=challenge.id, name=name, query=query, created_by=actor
                )
                session.add(view)
            else:
                view.query = query
                view.updated_at = utcnow()
            session.flush()
            self._event(
                session,
                challenge,
                "knowledge.view_saved",
                actor,
                {"view_id": view.id, "name": name},
            )
            return self._view_dict(view)

    def delete_view(self, slug: str, view_id: str, *, actor: str) -> dict[str, Any]:
        with self.database.session() as session, session.begin():
            challenge = self._challenge(session, slug)
            view = session.scalar(
                select(SavedKnowledgeView).where(
                    SavedKnowledgeView.challenge_id == challenge.id,
                    SavedKnowledgeView.id == view_id,
                )
            )
            if view is None:
                raise NotFoundError("Saved knowledge view does not exist.")
            result = self._view_dict(view)
            session.delete(view)
            self._event(
                session,
                challenge,
                "knowledge.view_removed",
                actor,
                {"view_id": view_id},
            )
            return result

    def sources(self, slug: str) -> list[dict[str, Any]]:
        with self.database.session() as session:
            challenge = self._challenge(session, slug)
            rows = session.scalars(
                select(ProjectSource)
                .where(ProjectSource.challenge_id == challenge.id, ProjectSource.status == "ACTIVE")
                .order_by(ProjectSource.name)
            ).all()
            return [self._source_dict(item) for item in rows]

    def set_source(
        self,
        *,
        slug: str,
        name: str,
        source_type: str,
        uri: str,
        media_type: str | None,
        metadata: dict[str, Any],
        actor: str,
    ) -> dict[str, Any]:
        source_type = source_type.upper()
        if source_type not in SOURCE_TYPES:
            raise InvariantError("Source type must be URL, CONNECTOR, or UPLOAD.")
        name = self._required("source name", name)
        uri = self._required("source URI", uri)
        if len(name) > 200 or len(uri) > 4096 or (media_type and len(media_type) > 200):
            raise InvariantError("Source name, URI, or media type exceeds its size limit.")
        if source_type in {"URL", "CONNECTOR"}:
            self._validate_source_uri(uri, require_http=source_type == "URL")
        self._validate_source_metadata(metadata)
        with self.database.session() as session, session.begin():
            challenge = self._challenge(session, slug)
            source = session.scalar(
                select(ProjectSource).where(
                    ProjectSource.challenge_id == challenge.id,
                    ProjectSource.name == name,
                )
            )
            if source is None:
                source = ProjectSource(
                    challenge_id=challenge.id,
                    name=name,
                    source_type=source_type,
                    uri=uri,
                    media_type=media_type,
                    metadata_json=metadata,
                    created_by=actor,
                )
                session.add(source)
            else:
                source.source_type = source_type
                source.uri = uri
                source.media_type = media_type
                source.metadata_json = metadata
                source.status = "ACTIVE"
                source.updated_at = utcnow()
            session.flush()
            self._event(
                session,
                challenge,
                "source.configured",
                actor,
                {"source_id": source.id, "name": source.name, "type": source_type},
            )
            return self._source_dict(source)

    def remove_source(self, slug: str, source_id: str, *, actor: str) -> dict[str, Any]:
        with self.database.session() as session, session.begin():
            challenge = self._challenge(session, slug)
            source = session.scalar(
                select(ProjectSource).where(
                    ProjectSource.challenge_id == challenge.id,
                    ProjectSource.id == source_id,
                    ProjectSource.status == "ACTIVE",
                )
            )
            if source is None:
                raise NotFoundError("Active project source does not exist.")
            source.status = "REMOVED"
            source.updated_at = utcnow()
            self._event(
                session,
                challenge,
                "source.removed",
                actor,
                {"source_id": source.id, "name": source.name},
            )
            return self._source_dict(source)
