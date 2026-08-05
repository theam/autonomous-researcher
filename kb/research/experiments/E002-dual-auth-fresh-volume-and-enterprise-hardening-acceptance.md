---
id: "E002"
aliases: ["E002"]
type: experiment
status: COMPLETED
hypothesis: "H002"
created: "2026-07-15"
completed: ""
tags: []
---

# E002 — Dual-auth fresh-volume and enterprise hardening acceptance

> **Status**: COMPLETED
> **Hypothesis**: [[H002]]
> **Created**: 2026-07-15
> **Completed**: 2026-07-15

## Objective

Decide whether all findings from the enterprise first-run review have been resolved strongly enough
to invite a trusted internal PoC cohort without manual Codex bootstrap, known credential-injection
paths, misleading FinOps data, or avoidable operational hazards.

## Setup

- Environment: branch `feat/cloud-challenge-runtime`, starting revision
  `6a80aa67efd63bb435f83cc9db8ae57cb372c9f5` plus the uncommitted [[E001]] evidence; Python 3.13,
  Docker 28.0.1, Docker Compose 2.33.1, Codex CLI 0.144.4 on the host and the repository-pinned
  `openai-codex` runtime dependency in Docker.
- Data: the complete automated test suite, synthetic auth/usage/retry/security fixtures, a fresh
  Docker volume, and one bounded live Codex smoke mission.
- Compute: local Docker Desktop, SQLite default Compose path; PostgreSQL migration SQL generated
  offline.
- External services: OpenAI only for the final live API-key smoke test; ChatGPT device login is
  covered by SDK contract/integration tests unless a human completes the one-time browser step.
- Raw metrics: `kb/research/data/E002/`.

## Procedure

1. Freeze the finding-to-fix matrix and official/pinned Codex authentication behavior before edits.
2. Implement auth-state ownership, environment defense, telemetry/provenance, retries, probes,
   rate limiting, WebSocket ticket transport, CI/dependency parity, migration ownership, and module
   extraction in atomic test-backed slices.
3. Run focused tests after each slice and `make runtime-check` after integration.
4. Build a fresh default Compose volume with the reused key supplied through no-echo process input;
   create and start a bounded Codex project using only public Limina commands.
5. Verify the first turn succeeds unattended, child events do not expose the raw key, usage tokens
   are non-null, the project and stack stop, and all credential-bearing state is removed.
6. Run Claude Fable at maximum reasoning on the final diff; fix every correctness or security
   finding and rerun acceptance.
7. Store structured results, classify [[H002]], write the decision-grade finding, and update ACTIVE.

## Expected Outcome

- Confirm: the full matrix in [[H002]] passes and no HIGH/MEDIUM report finding remains open.
- Reject: any required live, security, accounting, or concurrency invariant fails under a
  method-valid setup.
- Inconclusive: only an external provider/account condition blocks the live slice after offline
  method validity is established.
- Primary metric: findings closed or bounded by an explicit accepted trust posture.
- Secondary metrics: tests, module line counts, live recoveries, live duration, token telemetry,
  retry behavior, health state, and credential scan results.

## Progress

- [x] (`2026-07-15`) Reproduced and documented the baseline in [[E001]] and [[F001]].
- [x] (`2026-07-15`) Verified official and pinned Codex dual-auth and token-usage contracts.
- [x] (`2026-07-15`) Completed Claude Fable pre-implementation API/security review.
- [x] (`2026-07-15`) Implemented all remediation slices and focused tests.
- [x] (`2026-07-15`) Completed full offline/live acceptance and final Claude Fable review/fix pass.

## Results

- `make runtime-check` passed: Ruff format/lint, 77 tests, PostgreSQL Alembic SQL through
  `1f6a2c8d9e10`, local/cloud Compose rendering, and KB validation.
- A fresh named volume completed one public-CLI-created Codex project without manual directory or
  login recovery. The run completed in 51,192 ms using `gpt-5.4`, 24 tool calls, and retry count 0.
- Provider usage was 19,824 input, 18,816 cached-input, 217 output, 90 reasoning-output, and 20,041
  total tokens. `usage_source=provider`; cost/provenance were correctly null because no provider
  cost or operator rate was available.
- The project published one confirmed H, one completed E, and one published F. Durable-event scans
  found no credential pattern; the auth home and file were `0700`/`0600`; cleanup left no test
  container or volume. Key-bearing execution lasted 93 seconds against the 1,740-second limit.
- Every original 2 HIGH, 4 MEDIUM, and 5 LOW finding is closed or bounded by explicit provenance
  and single-node scope in `kb/research/data/E002/finding-matrix.md`.
- Final Claude Fable review found two P1 issues (unintended API-key serialization and auth-helper
  environment inheritance) plus two P2 issues (pre-run heartbeat cleanup and non-ASCII token
  handling). All four were fixed, covered by regression tests, and returned `VERIFIED_FIXED` in a
  targeted maximum-reasoning verification pass.

## Analysis

The hypothesis is confirmed. The live comparator improved from two manual recoveries and null
usage in [[E001]] to zero recoveries and complete per-turn token telemetry. The changes operate at
shared lifecycle and trust boundaries rather than depending on the PoC mission wording. Cost is
not fabricated: operators may configure explicit rates, while unpriced runs remain null with no
false provider attribution. ChatGPT login is a supported administrator-driven alternative to an
API key, but its browser completion and refresh store remain intentionally single-node.

## Decision

Confirm [[H002]] and publish [[F002]]. The branch is suitable for a trusted internal Codex PoC. Do
not represent this result as evidence for live Claude Code, OIDC, multi-replica failover, workload
isolation, or production multi-tenancy; those remain separate acceptance experiments.

## Links

- Mission: [[CHALLENGE]]
- Active State: [[ACTIVE]]
- Parent Hypothesis: [[H002]]
- Finding: [[F002]]
