#!/usr/bin/env python3
"""
Generate a Codex /goal command from kb/mission/CHALLENGE.md.

The script uses only the Python standard library so a fresh Limina checkout can
generate its Codex Goal before any optional dependency setup.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path


SECTION_RE = re.compile(r"^##\s+(.+?)\s*$")
PLACEHOLDER_MARKERS = (
    "what should the agent research",
    "what exists today",
    "what has been tried",
    "what counts as a successful research outcome",
)


@dataclass(frozen=True)
class Challenge:
    objective: str
    context: str
    success: str
    resources: str
    constraints: str
    blocked: str


class GoalError(Exception):
    """Raised when the mission brief is not ready for Goal generation."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a Codex /goal from kb/mission/CHALLENGE.md.")
    parser.add_argument("--kb-root", default="./kb", help="Path to the kb/ directory (default: ./kb)")
    parser.add_argument("--write", action="store_true", help="Write kb/mission/GOAL.md as well as printing the Goal")
    return parser.parse_args()


def normalize_heading(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def parse_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        match = SECTION_RE.match(line.strip())
        if match:
            current = normalize_heading(match.group(1))
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def pick_section(sections: dict[str, str], *names: str) -> str:
    for name in names:
        value = sections.get(normalize_heading(name), "").strip()
        if value:
            return value
    return ""


def is_placeholder(value: str) -> bool:
    compact = re.sub(r"[\s_*`>#{}.-]+", " ", value.lower()).strip()
    if not compact:
        return True
    if compact in {"", "1", "1 2", "1 2 3"}:
        return True
    if compact.replace(" ", "") in {"...", "1...2...", "...1..."}:
        return True
    return any(marker in compact for marker in PLACEHOLDER_MARKERS)


def clean_inline(value: str, fallback: str = "") -> str:
    lines: list[str] = []
    in_frontmatter = False
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if line == "---":
            in_frontmatter = not in_frontmatter
            continue
        if in_frontmatter or not line:
            continue
        line = re.sub(r"^[-*]\s+", "", line)
        line = re.sub(r"^\d+\.\s+", "", line)
        line = line.strip(" _{}")
        if line and line != "...":
            lines.append(line)
    return " ".join(lines) if lines else fallback


def load_challenge(kb_root: Path) -> Challenge:
    challenge_path = kb_root / "mission" / "CHALLENGE.md"
    if not challenge_path.exists():
        raise GoalError(f"Missing {challenge_path}. Create the mission brief before generating a Goal.")

    sections = parse_sections(challenge_path.read_text(encoding="utf-8"))
    objective_raw = pick_section(sections, "Objective")
    success_raw = pick_section(sections, "Success Criteria", "Success Metric", "Evaluation Target")

    missing: list[str] = []
    if is_placeholder(objective_raw):
        missing.append("Objective")
    if is_placeholder(success_raw):
        missing.append("Success Criteria")
    if missing:
        joined = " and ".join(missing)
        raise GoalError(
            f"Cannot generate a Codex Goal yet: kb/mission/CHALLENGE.md still needs a real {joined}. "
            "Replace the placeholder text with observable mission details and run this command again."
        )

    return Challenge(
        objective=clean_inline(objective_raw),
        context=clean_inline(pick_section(sections, "Context", "Context & Baseline", "Background"), "No additional context provided."),
        success=clean_inline(success_raw),
        resources=clean_inline(
            pick_section(sections, "Resources & Boundaries", "Resource Envelope", "Resources"),
            "the project repository and resources explicitly approved by the user",
        ),
        constraints=clean_inline(
            pick_section(sections, "Constraints"),
            "persist durable evidence in kb/, keep active state in kb/ACTIVE.md, and ask the user when blocked",
        ),
        blocked=clean_inline(
            pick_section(sections, "Blocked Stop Condition", "Escalation Rules"),
            "stop, update kb/ACTIVE.md with the blocker, and ask for the exact missing input, access, budget, or decision",
        ),
    )


def build_goal(challenge: Challenge) -> str:
    return (
        "/goal Advance the Limina research mission in kb/mission/CHALLENGE.md: "
        f"{challenge.objective}. Use this context: {challenge.context}. "
        f"Treat success as: {challenge.success}. "
        "Follow AGENTS.md and keep durable state in kb/. At each continuation, read kb/ACTIVE.md and the linked working set, "
        "choose the next highest-value unknown, preserve the H -> E -> F evidence chain, update kb/ACTIVE.md before stopping, "
        "and run concrete tools or document why none are possible. "
        "Verify completion with a passing `python3 scripts/kb_validate.py` run and a final audit that separates confirmed findings, "
        "proxy evidence, blocked claims, and remaining uncertainty. "
        f"Use only these resources and boundaries: {challenge.resources}. "
        f"Respect these constraints: {challenge.constraints}. "
        f"If blocked or budget-limited, do not mark the Goal complete; {challenge.blocked}."
    )


def render_goal_markdown(goal: str, challenge: Challenge) -> str:
    return f"""---
aliases: ["GOAL"]
type: codex-goal
---

# Codex Goal

> **Generated**: {date.today().isoformat()}

## Command

```text
{goal}
```

## Completion Evidence

- `python3 scripts/kb_validate.py` passes.
- `kb/ACTIVE.md` reflects the final objective, next step, blocker, and working set.
- The final audit separates confirmed findings, proxy evidence, blocked claims, and remaining uncertainty.

## Iteration Policy

Use `kb/mission/CHALLENGE.md` as the mission brief, `kb/ACTIVE.md` as the current state, and the linked working set for detailed context. Preserve the `H -> E -> F` evidence chain.

## Blocked Stop Condition

If blocked or budget-limited, do not mark the Goal complete. {challenge.blocked}.
"""


def main() -> int:
    args = parse_args()
    kb_root = Path(args.kb_root).resolve()

    try:
        challenge = load_challenge(kb_root)
    except GoalError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    goal = build_goal(challenge)
    if args.write:
        goal_path = kb_root / "mission" / "GOAL.md"
        goal_path.write_text(render_goal_markdown(goal, challenge), encoding="utf-8")
        print(f"Wrote {goal_path}")
        print()
    print(goal)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
