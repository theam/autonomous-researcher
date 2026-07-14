---
aliases: ["CHALLENGE"]
type: mission
---

# Research Mission

## Objective

Make Limina the complete collaborative harness for long-running Codex and Claude Code projects,
with a backend contract ready for an observability, analytics, knowledge, steering, and kickoff UI.

## Context

Limina owns provider runtimes, durable research state, recovery, and asynchronous guidance. Users
must operate projects rather than sessions, threads, workers, or subagents. The current delivery is
CLI-, REST-, WebSocket-, and MCP-first; no GUI components are in scope.

## Success Criteria

- Team deployments use OIDC/JWT identity and project OWNER/EDITOR/VIEWER roles.
- Kickoff, sources, variables, write-only secrets, steering, review, knowledge, runs, and analytics
  have typed project-level APIs and equivalent MCP capabilities where safe.
- PostgreSQL full-text search and explicit graph relations provide the first query baseline.
- Codex and Claude Code remain Limina-owned selectable engines.
- One Docker Compose command starts the service, migrations pass, and the full acceptance suite is
  green.

## Resources & Boundaries

Use this repository and its local Docker daemon. Do not build UI components. Keep semantic/vector
retrieval deferred until evaluated against the full-text baseline. Paid live provider checks require
available user credentials and must not be claimed from contract tests.

## Constraints

- Persist durable evidence in `kb/`.
- Keep active state in `kb/ACTIVE.md`.
- Ask the user when blocked on access, trust in the evaluation, or strategic decisions.

## Blocked Stop Condition

Stop for a product/security choice that changes the public contract, or when a live provider proof
requires credentials that are not available. Continue through mechanical implementation and local
verification without asking the user to manage provider sessions.

## Links

- Active State: [[ACTIVE]]
- Dashboard: [[DASHBOARD]]
