"""Pure authorization projections for API and UI presentation."""

from __future__ import annotations

from collections.abc import Iterable

from .auth import WORKOS_PROJECT_CREATE_PERMISSION, Principal

INSTANCE_READ = "instance:read"
PROJECT_CREATE = "project:create"
INSTANCE_ADMIN = "instance:admin"

PROJECT_READ = "project:read"
PROJECT_DRAFT_WRITE = "project:draft-write"
ATTENTION_RESOLVE = "attention:resolve"
ARTIFACT_REVIEW = "artifact:review"
KNOWLEDGE_COLLABORATE = "knowledge:collaborate"
PROJECT_LIFECYCLE = "project:lifecycle"
RESOURCE_WRITE = "resource:write"
SECRET_WRITE = "secret:write"
MEMBER_MANAGE = "member:manage"
NOTIFICATION_MANAGE = "notification:manage"
PROJECT_ARCHIVE = "project:archive"

_INSTANCE_CAPABILITY_ORDER = (INSTANCE_READ, PROJECT_CREATE, INSTANCE_ADMIN)
_PROJECT_CAPABILITY_ORDER = (
    PROJECT_READ,
    PROJECT_DRAFT_WRITE,
    ATTENTION_RESOLVE,
    ARTIFACT_REVIEW,
    KNOWLEDGE_COLLABORATE,
    PROJECT_LIFECYCLE,
    RESOURCE_WRITE,
    SECRET_WRITE,
    MEMBER_MANAGE,
    NOTIFICATION_MANAGE,
    PROJECT_ARCHIVE,
)
_ROLE_CAPABILITIES = {
    "VIEWER": frozenset({PROJECT_READ}),
    "EDITOR": frozenset(
        {
            PROJECT_READ,
            ATTENTION_RESOLVE,
            ARTIFACT_REVIEW,
            KNOWLEDGE_COLLABORATE,
            PROJECT_LIFECYCLE,
            RESOURCE_WRITE,
        }
    ),
    "OWNER": frozenset(_PROJECT_CAPABILITY_ORDER),
}
_LIFECYCLE_STATES = {
    "CREATED",
    "RUNNING",
    "WAITING",
    "PAUSED",
    "STOPPED",
    "COMPLETE",
    "FAILED",
    "ARCHIVED",
}
_ACTION_STATES = {
    "start": frozenset({"CREATED", "STOPPED"}),
    "pause": frozenset({"RUNNING", "WAITING"}),
    "resume": frozenset({"PAUSED", "WAITING", "STOPPED", "FAILED"}),
    "stop": frozenset({"CREATED", "RUNNING", "WAITING", "PAUSED", "FAILED"}),
}
_LIFECYCLE_ACTION_ORDER = ("start", "pause", "resume", "stop", "archive")
_ROLE_LEVEL = {"VIEWER": 1, "EDITOR": 2, "OWNER": 3}
_PERSONAL_ATTENTION_ACTIONS = {
    ("project_complete", "ACKNOWLEDGE"),
    ("stalled_project", "SNOOZE"),
    ("unattended_run", "SNOOZE"),
}


def instance_capabilities(principal: Principal) -> tuple[str, ...]:
    """Return coarse instance operations granted by a verified principal."""

    granted = {INSTANCE_READ}
    if (
        principal.project_admin
        or principal.auth_mode == "oidc"
        or WORKOS_PROJECT_CREATE_PERMISSION in principal.permissions
    ):
        granted.add(PROJECT_CREATE)
    if principal.instance_admin:
        granted.add(INSTANCE_ADMIN)
    return tuple(item for item in _INSTANCE_CAPABILITY_ORDER if item in granted)


def project_capabilities(role: str | None) -> tuple[str, ...]:
    """Project capabilities for a durable OWNER/EDITOR/VIEWER membership."""

    if role is None:
        return ()
    normalized = role.strip().upper()
    try:
        granted = _ROLE_CAPABILITIES[normalized]
    except KeyError:
        raise ValueError("Project role must be OWNER, EDITOR, or VIEWER.") from None
    return tuple(item for item in _PROJECT_CAPABILITY_ORDER if item in granted)


def lifecycle_allowed_actions(status: str, capabilities: Iterable[str]) -> tuple[str, ...]:
    """Return state-valid lifecycle actions without granting any new authority."""

    normalized = status.strip().upper()
    if normalized not in _LIFECYCLE_STATES:
        raise ValueError(f"Unknown project lifecycle status '{status}'.")
    if normalized == "ARCHIVED":
        return ()

    granted = frozenset(capabilities)
    actions: set[str] = set()
    if PROJECT_LIFECYCLE in granted:
        actions.update(action for action, states in _ACTION_STATES.items() if normalized in states)
    if PROJECT_ARCHIVE in granted and normalized not in {"RUNNING", "WAITING"}:
        actions.add("archive")
    return tuple(item for item in _LIFECYCLE_ACTION_ORDER if item in actions)


def attention_action_minimum_role(item_type: str, action: str) -> str:
    """Return the durable membership needed for one advertised attention action."""

    normalized = (item_type.strip().lower(), action.strip().upper())
    if normalized[0] == "notification_failure":
        return "OWNER"
    if normalized in _PERSONAL_ATTENTION_ACTIONS:
        return "VIEWER"
    return "EDITOR"


def authorized_attention_actions(
    item_type: str,
    actions: Iterable[str],
    role: str,
) -> tuple[str, ...]:
    """Intersect episode actions with the member's durable project role."""

    normalized_role = role.strip().upper()
    if normalized_role not in _ROLE_LEVEL:
        raise ValueError("Project role must be OWNER, EDITOR, or VIEWER.")
    return tuple(
        action
        for action in actions
        if _ROLE_LEVEL[normalized_role]
        >= _ROLE_LEVEL[attention_action_minimum_role(item_type, action)]
    )
