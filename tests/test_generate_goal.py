from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "generate_goal.py"


def write_challenge(kb_root: Path, text: str) -> None:
    mission = kb_root / "mission"
    mission.mkdir(parents=True)
    (mission / "CHALLENGE.md").write_text(text, encoding="utf-8")


class GenerateGoalTests(unittest.TestCase):
    def test_write_generates_goal_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kb_root = Path(tmp) / "kb"
            write_challenge(
                kb_root,
                """---
aliases: ["CHALLENGE"]
type: mission
---

# Research Mission

## Objective

Improve search relevance for long catalog queries.

## Context

Current hybrid search misses multi-intent queries.

## Success Criteria

- Produce a recommendation backed by at least 2 experiments.
- Preserve p95 latency under 250ms.

## Constraints

- Do not use production data.

## Links

- Active State: [[ACTIVE]]
""",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--kb-root", str(kb_root), "--write"],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            goal_path = kb_root / "mission" / "GOAL.md"
            self.assertTrue(goal_path.exists())
            goal_text = goal_path.read_text(encoding="utf-8")
            self.assertIn("/goal Advance the Limina research mission", goal_text)
            self.assertIn("kb/mission/CHALLENGE.md", goal_text)
            self.assertIn("kb/ACTIVE.md", goal_text)
            self.assertIn("scripts/kb_validate.py", goal_text)
            self.assertIn("budget-limited", goal_text)

    def test_placeholder_challenge_fails_with_friendly_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kb_root = Path(tmp) / "kb"
            write_challenge(
                kb_root,
                """# Research Mission

## Objective

{What should the agent research?}

## Success Criteria

{What counts as a successful research outcome?}
""",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--kb-root", str(kb_root)],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("still needs a real Objective and Success Criteria", result.stderr)
            self.assertFalse((kb_root / "mission" / "GOAL.md").exists())


if __name__ == "__main__":
    unittest.main()
