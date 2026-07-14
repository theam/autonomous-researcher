---
aliases: ["ACTIVE"]
type: active-state
---

# Active State

## Current Objective

Ship one Limina-owned supervisor with selectable Codex and Claude Code runtimes, operated through
one coherent CLI, REST, WebSocket, and MCP project contract.

## Next Step

When Anthropic credentials are available, record a live Claude Code restart-and-steering smoke
test. Re-run the API/MCP taste and shipping review after restoring the local Claude CLI login.

## Blocker

The API/MCP implementation passes the full mechanical suite and packaged container smoke. Live
Claude Code provider behavior is covered by an SDK contract test but has not yet been exercised
against the Anthropic API; the local Claude CLI OAuth session is also expired.

## Links

- Mission: [[CHALLENGE]]
- Architecture: [Managed runtime decision](../docs/cloud-runtime-architecture.md)
- Evidence: [Managed runtime verification](../docs/cloud-runtime-evidence.md)
