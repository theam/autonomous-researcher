"""Deterministic Markdown projection of the canonical challenge store."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from .errors import ConflictError
from .service import ChallengeService


def _yaml(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "untitled"


def _section(value: str | None, fallback: str = "_Not recorded._") -> str:
    return value.strip() if value and value.strip() else fallback


class MarkdownExporter:
    def __init__(self, service: ChallengeService) -> None:
        self.service = service

    def snapshot(self, slug: str) -> dict[str, str]:
        status = self.service.status(slug)
        challenge = status["challenge"]
        artifacts = self.service.list_artifacts(slug)
        by_id = {item["id"]: item for item in artifacts}
        experiments_by_hypothesis: dict[str, list[str]] = defaultdict(list)
        findings_by_hypothesis: dict[str, list[str]] = defaultdict(list)
        findings_by_experiment: dict[str, list[str]] = defaultdict(list)
        for item in artifacts:
            if item["kind"] == "E" and item["hypothesis_id"]:
                experiments_by_hypothesis[item["hypothesis_id"]].append(item["id"])
            if item["kind"] == "F":
                if item["hypothesis_id"]:
                    findings_by_hypothesis[item["hypothesis_id"]].append(item["id"])
                if item["experiment_id"]:
                    findings_by_experiment[item["experiment_id"]].append(item["id"])

        files = {
            "mission/CHALLENGE.md": self._challenge(challenge),
            "ACTIVE.md": self._active(challenge, artifacts),
            "DASHBOARD.md": self._dashboard(challenge, artifacts),
        }
        for item in artifacts:
            filename = f"{item['id']}-{_slugify(item['title'])}.md"
            if item["kind"] == "H":
                files[f"research/hypotheses/{filename}"] = self._hypothesis(
                    item,
                    experiments_by_hypothesis[item["id"]],
                    findings_by_hypothesis[item["id"]],
                )
            elif item["kind"] == "E":
                detailed = self.service.get_artifact(slug, item["id"])
                files[f"research/experiments/{filename}"] = self._experiment(
                    detailed,
                    findings_by_experiment[item["id"]],
                )
            elif item["kind"] == "F":
                files[f"research/findings/{filename}"] = self._finding(item, by_id)
        return dict(sorted(files.items()))

    def write(self, slug: str, target: Path) -> list[Path]:
        snapshot = self.snapshot(slug)
        if target.exists() and any(target.iterdir()):
            raise ConflictError(
                f"Export target '{target}' is not empty.",
                target=str(target),
                suggestion=(
                    "Choose an empty directory so stale artifacts cannot survive the export."
                ),
            )
        written: list[Path] = []
        for relative, content in snapshot.items():
            path = target / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            written.append(path)
        return written

    @staticmethod
    def _challenge(challenge: dict[str, Any]) -> str:
        return f"""---
aliases: ["CHALLENGE"]
type: mission
challenge_id: {_yaml(challenge["id"])}
challenge_slug: {_yaml(challenge["slug"])}
---

# Research Mission — {challenge["name"]}

## Objective

{challenge["objective"]}

## Context

{_section(challenge["context"])}

## Success Criteria

{challenge["success_criteria"]}

## Resources & Boundaries

_Managed by the cloud challenge policy._

## Constraints

- Persist durable evidence through typed Limina commands.
- Treat this export as a projection; the challenge service remains canonical.

## Blocked Stop Condition

Stop when the coordinator records a blocker requiring human input.

## Links

- Active State: [[ACTIVE]]
- Dashboard: [[DASHBOARD]]
"""

    @staticmethod
    def _active(challenge: dict[str, Any], artifacts: list[dict[str, Any]]) -> str:
        coordinator = challenge["coordinator"]
        working = [
            item["id"]
            for item in artifacts
            if (item["kind"] == "H" and item["status"] in {"PROPOSED", "TESTING"})
            or (item["kind"] == "E" and item["status"] in {"DESIGNED", "RUNNING"})
        ]
        working_links = "\n".join(f"- Working Note: [[{item}]]" for item in working)
        if not working_links:
            working_links = "- Dashboard: [[DASHBOARD]]"
        return f"""---
aliases: ["ACTIVE"]
type: active-state
coordinator_version: {coordinator["version"]}
---

# Active State

## Current Objective

{coordinator["current_objective"]}

## Next Step

{coordinator["next_step"]}

## Blocker

{coordinator["blocker"]}

## Links

- Mission: [[CHALLENGE]]
{working_links}
"""

    @staticmethod
    def _dashboard(challenge: dict[str, Any], artifacts: list[dict[str, Any]]) -> str:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in artifacts:
            grouped[item["kind"]].append(item)

        def lines(kind: str) -> str:
            values = grouped.get(kind, [])
            return (
                "\n".join(
                    f"- [[{item['id']}]] — {item['title']} ({item['status']})" for item in values
                )
                or "- None yet."
            )

        return f"""---
aliases: ["DASHBOARD"]
type: dashboard
challenge_slug: {_yaml(challenge["slug"])}
---

# {challenge["name"]} — Dashboard

## Entry Points

- [[CHALLENGE]]
- [[ACTIVE]]

## Hypotheses

{lines("H")}

## Experiments

{lines("E")}

## Findings

{lines("F")}

## Links

- Active State: [[ACTIVE]]
- Mission: [[CHALLENGE]]
"""

    @staticmethod
    def _hypothesis(item: dict[str, Any], experiments: list[str], findings: list[str]) -> str:
        payload = item["payload"]
        links = ["- Mission: [[CHALLENGE]]", "- Active State: [[ACTIVE]]"]
        links.extend(f"- Experiment: [[{artifact_id}]]" for artifact_id in experiments)
        links.extend(f"- Finding: [[{artifact_id}]]" for artifact_id in findings)
        return f"""---
id: {_yaml(item["id"])}
aliases: [{_yaml(item["id"])}]
type: hypothesis
status: {_yaml(item["status"])}
created: {_yaml(item["created_at"][:10])}
last_updated: {_yaml(item["updated_at"][:10])}
tags: []
---

# {item["id"]} — {item["title"]}

> **Status**: {item["status"]}
> **Created**: {item["created_at"][:10]}
> **Last updated**: {item["updated_at"][:10]}

## Statement

{_section(payload.get("statement"))}

## Mechanism

{_section(payload.get("mechanism"))}

## Why This Might Generalize

{_section(payload.get("generalization"))}

## Shortcut Risks

{_section(payload.get("shortcut_risks"))}

## Test Plan

{_section(payload.get("test_plan"))}

## Evidence

_See linked experiments and findings._

## Conclusion

{_section(payload.get("conclusion"))}

## Links

{chr(10).join(links)}
"""

    @staticmethod
    def _experiment(item: dict[str, Any], findings: list[str]) -> str:
        payload = item["payload"]
        observations = item.get("observations", [])
        progress = (
            "\n".join(
                f"- [x] ({entry['created_at'][:10]}) {entry['body']}"
                + (f" — `{entry['evidence_ref']}`" if entry.get("evidence_ref") else "")
                for entry in observations
            )
            or "- [ ] No observations recorded."
        )
        links = [
            "- Mission: [[CHALLENGE]]",
            "- Active State: [[ACTIVE]]",
            f"- Parent Hypothesis: [[{item['hypothesis_id']}]]",
        ]
        links.extend(f"- Finding: [[{artifact_id}]]" for artifact_id in findings)
        completed = payload.get("completed_at") or ""
        return f"""---
id: {_yaml(item["id"])}
aliases: [{_yaml(item["id"])}]
type: experiment
status: {_yaml(item["status"])}
hypothesis: {_yaml(item["hypothesis_id"])}
created: {_yaml(item["created_at"][:10])}
completed: {_yaml(completed)}
tags: []
---

# {item["id"]} — {item["title"]}

> **Status**: {item["status"]}
> **Hypothesis**: [[{item["hypothesis_id"]}]]
> **Created**: {item["created_at"][:10]}
> **Completed**: {completed}

## Objective

{_section(payload.get("objective"))}

## Setup

{_section(payload.get("guardrails"))}

## Procedure

{_section(payload.get("procedure"))}

## Expected Outcome

{_section(payload.get("success_criteria"))}

## Progress

{progress}

## Results

{_section(payload.get("results"))}

## Analysis

{_section(payload.get("analysis"))}

## Decision

{_section(payload.get("decision"))}

## Links

{chr(10).join(links)}
"""

    @staticmethod
    def _finding(item: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> str:
        payload = item["payload"]
        hypothesis_id = item["hypothesis_id"]
        experiment_id = item["experiment_id"]
        if hypothesis_id not in by_id or experiment_id not in by_id:
            raise RuntimeError(f"Finding {item['id']} has unresolved parents")
        return f"""---
id: {_yaml(item["id"])}
aliases: [{_yaml(item["id"])}]
type: finding
hypothesis: {_yaml(hypothesis_id)}
experiment: {_yaml(experiment_id)}
impact: {_yaml(payload["impact"])}
created: {_yaml(item["created_at"][:10])}
tags: []
---

# {item["id"]} — {item["title"]}

> **Created**: {item["created_at"][:10]}
> **Hypothesis**: [[{hypothesis_id}]]
> **Experiment**: [[{experiment_id}]]
> **Impact**: {payload["impact"]}

## Finding

{_section(payload.get("finding"))}

## Evidence

{_section(payload.get("evidence"))}

## What Improved For Real

{_section(payload.get("improvement"))}

## Remaining Debt

{_section(payload.get("remaining_debt"))}

## Next Move

{_section(payload.get("next_move"))}

## Links

- Mission: [[CHALLENGE]]
- Active State: [[ACTIVE]]
- Parent Hypothesis: [[{hypothesis_id}]]
- Parent Experiment: [[{experiment_id}]]
"""
