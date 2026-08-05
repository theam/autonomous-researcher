---
aliases: ["ACTIVE"]
type: active-state
---

# Active State

## Current Objective

Use the value-first, dual-path documentation to prepare the next internal PoC while keeping the
managed runtime as the recommendation and the project template as the lightweight alternative.

## Next Step

Use the recommended runtime path for the internal PoC and separately smoke-test the template
onboarding flow before the next release.

## Blocker

No documentation blocker. The reused OpenAI key should still be rotated because it was supplied in
chat, even though the bounded runtime test did not persist or disclose it in repository, event,
container, or volume state.

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
