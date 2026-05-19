from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "kb_validate.py"


ACTIVE_TEXT = """---
aliases: ["ACTIVE"]
type: active-state
---

# Active State

## Current Objective

Validate optional Goal behavior.

## Next Step

Run validator.

## Blocker

None.

## Links

- Mission: [[CHALLENGE]]
"""


CHALLENGE_TEXT = """---
aliases: ["CHALLENGE"]
type: mission
---

# Research Mission

## Objective

Validate optional Goal behavior.

## Context

Minimal fixture.

## Success Criteria

Validation passes.

## Constraints

- Keep evidence in kb/.

## Links

- Active State: [[ACTIVE]]
- Dashboard: [[DASHBOARD]]
"""


DASHBOARD_TEXT = """---
aliases: ["DASHBOARD"]
type: dashboard
---

# Limina Dashboard

## Entry Points

- [[ACTIVE]]
- [[CHALLENGE]]

## Links

- Active State: [[ACTIVE]]
- Mission: [[CHALLENGE]]
"""


def make_minimal_kb(root: Path) -> Path:
    kb_root = root / "kb"
    (kb_root / "mission").mkdir(parents=True, exist_ok=True)
    (kb_root / "research" / "hypotheses").mkdir(parents=True, exist_ok=True)
    (kb_root / "research" / "experiments").mkdir(parents=True, exist_ok=True)
    (kb_root / "research" / "findings").mkdir(parents=True, exist_ok=True)
    (kb_root / "research" / "literature").mkdir(parents=True, exist_ok=True)
    (kb_root / "reports").mkdir(parents=True, exist_ok=True)
    (kb_root / "ACTIVE.md").write_text(ACTIVE_TEXT, encoding="utf-8")
    (kb_root / "DASHBOARD.md").write_text(DASHBOARD_TEXT, encoding="utf-8")
    (kb_root / "mission" / "CHALLENGE.md").write_text(CHALLENGE_TEXT, encoding="utf-8")
    return kb_root


def run_validator(kb_root: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["LIMINA_TELEMETRY_INTERNAL"] = "1"
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--kb-root", str(kb_root)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


class GoalValidationTests(unittest.TestCase):
    def test_goal_is_optional(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kb_root = make_minimal_kb(Path(tmp))
            result = run_validator(kb_root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_valid_goal_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kb_root = make_minimal_kb(Path(tmp))
            (kb_root / "mission" / "GOAL.md").write_text(
                """/goal Advance kb/mission/CHALLENGE.md using kb/ACTIVE.md. Verify with `python3 scripts/kb_validate.py`, produce a final audit, and stop if blocked.
""",
                encoding="utf-8",
            )
            result = run_validator(kb_root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_goal_requires_command_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kb_root = make_minimal_kb(Path(tmp))
            (kb_root / "mission" / "GOAL.md").write_text(
                "Mention CHALLENGE.md, ACTIVE.md, kb_validate.py, final audit, and blocked.",
                encoding="utf-8",
            )
            result = run_validator(kb_root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("starts with /goal", result.stdout)

    def test_goal_requires_key_completion_terms(self) -> None:
        cases = {
            "mission brief": "/goal Use ACTIVE.md, kb_validate.py, final audit, and blocked stop.",
            "active state": "/goal Use CHALLENGE.md, kb_validate.py, final audit, and blocked stop.",
            "validator": "/goal Use CHALLENGE.md, ACTIVE.md, final audit, and blocked stop.",
            "blocked stop condition": "/goal Use CHALLENGE.md, ACTIVE.md, kb_validate.py, and final audit.",
        }
        for expected, goal in cases.items():
            with self.subTest(expected=expected):
                with tempfile.TemporaryDirectory() as tmp:
                    kb_root = make_minimal_kb(Path(tmp))
                    (kb_root / "mission" / "GOAL.md").write_text(goal, encoding="utf-8")
                    result = run_validator(kb_root)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(expected, result.stdout)


if __name__ == "__main__":
    unittest.main()
