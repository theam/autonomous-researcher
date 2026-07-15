---
aliases: ["ACTIVE"]
type: active-state
---

# Active State

## Current Objective

Prepare a bounded trusted internal PoC using the now-hardened managed Codex runtime while keeping
production, Claude Code, and multi-replica claims behind their own evidence gates.

## Next Step

Select two or three real internal Codex missions and define cohort success/stop criteria. Create a
separate experiment for live Claude Code or OIDC/PostgreSQL validation before claiming either.

## Blocker

No implementation blocker. A cohort mission/data choice is required for the next research cycle.
The reused OpenAI key should be rotated because it was supplied in chat, even though the bounded
runtime test did not persist or disclose it in repository, event, container, or volume state.

## Links

- Mission: [[CHALLENGE]]
- Architecture: [Managed runtime decision](../docs/cloud-runtime-architecture.md)
- Evidence: [Managed runtime verification](../docs/cloud-runtime-evidence.md)
- UI-ready backend: [Implementation and rationale](../docs/ui-ready-backend.md)
- Lesson: [UI-ready control-plane boundaries](lessons/ui-ready-control-plane.md)
- Hypothesis: [[H001]]
- Completed experiment: [[E001]]
- Enterprise evaluator report: [Claude Fable review](../docs/reviews/claude-fable-enterprise-evaluation-2026-07-15.md)
- Confirmed remediation hypothesis: [[H002]]
- Completed remediation experiment: [[E002]]
- Release finding: [[F002]]
