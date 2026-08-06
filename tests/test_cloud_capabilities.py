from __future__ import annotations

import unittest

from limina_cloud.auth import Principal
from limina_cloud.capabilities import (
    ARTIFACT_REVIEW,
    ATTENTION_RESOLVE,
    INSTANCE_ADMIN,
    INSTANCE_READ,
    KNOWLEDGE_COLLABORATE,
    MEMBER_MANAGE,
    NOTIFICATION_MANAGE,
    PROJECT_ARCHIVE,
    PROJECT_CREATE,
    PROJECT_DRAFT_WRITE,
    PROJECT_LIFECYCLE,
    PROJECT_READ,
    RESOURCE_WRITE,
    SECRET_WRITE,
    attention_action_minimum_role,
    authorized_attention_actions,
    instance_capabilities,
    lifecycle_allowed_actions,
    project_capabilities,
)


class CapabilityProjectionTests(unittest.TestCase):
    def test_instance_capabilities_use_verified_coarse_permissions(self) -> None:
        operator = Principal(
            "operator",
            "Opal Operator",
            instance_admin=True,
            auth_mode="workos",
            organization="org_123",
            permissions=frozenset(
                {"limina:access", "limina:project-create", "limina:instance-admin"}
            ),
        )
        limited = Principal(
            "limited",
            "Lina Limited",
            instance_admin=True,
            auth_mode="workos",
            organization="org_123",
            permissions=frozenset({"limina:access", "limina:instance-admin"}),
        )

        self.assertEqual(
            instance_capabilities(operator),
            (INSTANCE_READ, PROJECT_CREATE, INSTANCE_ADMIN),
        )
        self.assertEqual(instance_capabilities(limited), (INSTANCE_READ, INSTANCE_ADMIN))

    def test_project_role_matrix_is_explicit_and_ordered(self) -> None:
        self.assertEqual(project_capabilities(None), ())
        self.assertEqual(project_capabilities("viewer"), (PROJECT_READ,))
        self.assertEqual(
            project_capabilities("EDITOR"),
            (
                PROJECT_READ,
                ATTENTION_RESOLVE,
                ARTIFACT_REVIEW,
                KNOWLEDGE_COLLABORATE,
                PROJECT_LIFECYCLE,
                RESOURCE_WRITE,
            ),
        )
        self.assertEqual(
            project_capabilities("OWNER"),
            (
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
            ),
        )
        with self.assertRaises(ValueError):
            project_capabilities("ADMIN")

    def test_lifecycle_actions_intersect_role_and_current_state(self) -> None:
        editor = project_capabilities("EDITOR")
        owner = project_capabilities("OWNER")

        self.assertEqual(lifecycle_allowed_actions("RUNNING", editor), ("pause", "stop"))
        self.assertEqual(
            lifecycle_allowed_actions("STOPPED", editor),
            ("start", "resume"),
        )
        self.assertEqual(
            lifecycle_allowed_actions("STOPPED", owner),
            ("start", "resume", "archive"),
        )
        self.assertEqual(lifecycle_allowed_actions("COMPLETE", editor), ())
        self.assertEqual(lifecycle_allowed_actions("COMPLETE", owner), ("archive",))
        self.assertEqual(lifecycle_allowed_actions("ARCHIVED", owner), ())
        self.assertEqual(lifecycle_allowed_actions("RUNNING", project_capabilities("VIEWER")), ())
        with self.assertRaises(ValueError):
            lifecycle_allowed_actions("UNKNOWN", owner)

    def test_attention_actions_intersect_episode_semantics_and_role(self) -> None:
        self.assertEqual(
            attention_action_minimum_role("notification_failure", "ACKNOWLEDGE"),
            "OWNER",
        )
        self.assertEqual(
            attention_action_minimum_role("unattended_run", "SNOOZE"),
            "VIEWER",
        )
        self.assertEqual(
            authorized_attention_actions("run_failure", ["ACKNOWLEDGE"], "VIEWER"),
            (),
        )
        self.assertEqual(
            authorized_attention_actions("run_failure", ["ACKNOWLEDGE"], "EDITOR"),
            ("ACKNOWLEDGE",),
        )
        self.assertEqual(
            authorized_attention_actions("notification_failure", ["ACKNOWLEDGE"], "EDITOR"),
            (),
        )
        self.assertEqual(
            authorized_attention_actions("notification_failure", ["ACKNOWLEDGE"], "OWNER"),
            ("ACKNOWLEDGE",),
        )


if __name__ == "__main__":
    unittest.main()
