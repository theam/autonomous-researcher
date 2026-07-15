---
id: "F002"
aliases: ["F002"]
type: finding
hypothesis: "H002"
experiment: "E002"
impact: "HIGH"
created: "2026-07-15"
tags: []
---

# F002 — Enterprise blockers are closed for a trusted internal Codex PoC

> **Created**: 2026-07-15
> **Hypothesis**: [[H002]]
> **Experiment**: [[E002]]
> **Impact**: HIGH

## Finding

Limina now owns unattended fresh-volume Codex authentication and execution strongly enough for a
trusted internal PoC: the original enterprise release blockers are closed, API-key and ChatGPT
login are instance-managed, parallel API-key work is preserved, and operational/FinOps claims are
backed by explicit telemetry and provenance rather than aspirational fields.

## Evidence

- [[E002]] passed 77 automated tests plus Ruff, PostgreSQL migration SQL, both Compose contracts,
  and KB validation.
- The method-valid fresh-volume run completed in 51,192 ms with no manual recovery, 24 tool calls,
  a durable H→E→F chain, and 20,041 provider-reported total tokens.
- The raw credential was absent from child environments and durable event scans; private Codex
  state used `0700`/`0600`; key-bearing state was removed after 93 seconds.
- The complete 11-finding disposition is in `kb/research/data/E002/finding-matrix.md`.
- Claude Fable's final blocker review found two P1 and two P2 defects. Regression-backed fixes then
  received a targeted `VERIFIED_FIXED` verdict at maximum reasoning.

## What Improved For Real

An operator can now start one local server, authenticate Codex with either a ChatGPT account or a
server API key, and let Limina own subsequent sessions, turns, retries, continuation, and evidence.
Independent API-key projects can run concurrently; login mutation cannot race active turns; unsafe
legacy resources are scrubbed; retries and wake time survive restarts; browsers avoid URL tickets;
project and instance-administrator authority are separate; usage and cost provenance are queryable.

## Remaining Debt

- ChatGPT credentials are one runtime node's shared state and ChatGPT-backed turns are serialized;
  browser completion was contract-tested but not performed in the API-key live trial.
- Live Claude Code, OIDC IdP, PostgreSQL multi-replica failover, and restart/chaos trials remain
  separate evidence gaps.
- Provider cost stays null unless the provider supplies it or the operator configures all three
  explicit price rates; there is not yet a quota or billing system.
- Durable workspaces are process-level sandboxes, not per-project containers or microVMs. External
  KMS, audit export, object-store lifecycle, and workload isolation remain production work.

## Next Move

Run a bounded trusted internal cohort on two or three real Codex projects. Evaluate live Claude
Code and OIDC/PostgreSQL deployment as distinct experiments before widening access or making a
production-readiness claim.

## Links

- Mission: [[CHALLENGE]]
- Active State: [[ACTIVE]]
- Parent Hypothesis: [[H002]]
- Parent Experiment: [[E002]]
