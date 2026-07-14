---
aliases: ["ACTIVE"]
type: active-state
---

# Active State

## Current Objective

Ship a UI-ready Limina-owned supervisor with selectable Codex and Claude Code runtimes, one
authorization boundary, queryable knowledge, structured run observability, analytics, and coherent
CLI, REST, WebSocket, and MCP project contracts.

## Next Step

Build the UI against the typed project API without exposing provider sessions. When Anthropic
credentials are available, record a live Claude Code restart-and-steering smoke test; before an
untrusted production deployment, choose the workspace isolation, object storage, key management,
quota, and audit-export services described in the backend rationale.

## Blocker

No application implementation blocker. Live Claude Code provider behavior is covered by an SDK
contract test but has not yet been exercised against the Anthropic API; that proof requires valid
provider credentials. Production infrastructure choices remain deployment work, not UI contract
gaps.

## Links

- Mission: [[CHALLENGE]]
- Architecture: [Managed runtime decision](../docs/cloud-runtime-architecture.md)
- Evidence: [Managed runtime verification](../docs/cloud-runtime-evidence.md)
- UI-ready backend: [Implementation and rationale](../docs/ui-ready-backend.md)
- Lesson: [UI-ready control-plane boundaries](lessons/ui-ready-control-plane.md)
