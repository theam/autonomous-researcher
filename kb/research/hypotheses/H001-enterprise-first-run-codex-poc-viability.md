---
id: "H001"
aliases: ["H001"]
type: hypothesis
status: CONFIRMED
created: "2026-07-15"
last_updated: "2026-07-15"
tags: []
---

# H001 — Enterprise first-run Codex PoC viability

> **Status**: CONFIRMED
> **Created**: 2026-07-15
> **Last updated**: 2026-07-15

## Statement

If a fresh enterprise AI engineer evaluates commit
`6a80aa67efd63bb435f83cc9db8ae57cb372c9f5` using only the public repository and documented CLI,
then Limina will complete at least 6 of 7 first-run milestones, including every execution-critical
milestone, without requiring provider-session, thread, or subagent management. The key-enabled
evaluation window must remain under 30 minutes, no credential may be exposed, and no tracked
product file may be changed.

## Mechanism

The single Compose entry point, project-level CLI, Limina-owned Codex adapter, durable event stream,
and enforced H -> E -> F knowledge contract should collapse infrastructure and session handling into
one project workflow. An evaluator should therefore be able to move from README comprehension to a
small observable Codex PoC while interacting only with Limina's human-facing project boundary.

## Why This Might Generalize

The milestones exercise general installation, authentication, kickoff, resource, execution,
observation, evidence, and shutdown paths rather than application-specific benchmark behavior.
Success would support a broader internal PoC recommendation, although one laptop and one provider
run cannot establish production scalability, isolation, reliability, or cost.

## Shortcut Risks

- The evaluator is an expert coding agent rather than a representative human enterprise engineer.
- A self-referential repository PoC may avoid difficult private-network and connector setup.
- One successful stochastic Codex turn cannot establish restart recovery or long-run reliability.
- Reading implementation after recording the initial impression may help recover from weak docs;
  documentation and implementation observations must therefore be separated in the report.

## Test Plan

- Experiment: [[E001]].
- Comparator: the README's advertised seven-milestone quick-start contract.
- Primary metric: completed first-run milestones out of 7.
- Critical milestones: server start, project kickoff, managed Codex execution, observable durable
  result, and clean stop.
- Guardrails: key-enabled window < 30 minutes; no secret in repository, transcript excerpt, report,
  or process arguments; no tracked product edits; no direct management of Codex sessions or agents.
- Trial plan: one time-boxed exploratory run because this is a first-run DX audit; stochastic runtime
  quality is reported as provisional rather than generalized.
- Confirm if: at least 6/7 milestones complete, all critical milestones complete, and every guardrail
  passes.
- Reject if: 4/7 or fewer complete, or a product defect prevents any critical milestone under the
  documented method-valid setup.
- Inconclusive if: provider availability, local Docker failure, or evaluator tooling blocks a
  method-valid product test before the budget expires.

## Evidence

- The README advertises one-command startup and project-level Codex execution.
- The managed runtime contract and automated verification are documented in
  [the runtime dossier](../../../docs/cloud-runtime-evidence.md), but a fresh-user live provider run
  has not yet tested the complete advertised path.
- Claude Code's official `/goal` documentation provides an independently evaluated, time-bounded
  execution loop suitable for the evaluator role.

## Conclusion

**CONFIRMED, with adoption conditions.** [[E001]] completed 7/7 milestones, including all five
critical milestones, and passed every guardrail. A real Limina-owned Codex run produced a durable
H -> E -> F chain without exposing provider sessions to the evaluator. Two HIGH fresh-volume
integration defects required manual environment recovery, so the result supports a conditional
internal PoC recommendation only after those defects are fixed; it does not support unattended or
production-readiness claims.

## Links

- Mission: [[CHALLENGE]]
- Active State: [[ACTIVE]]
- Experiment: [[E001]]
- Finding: [[F001]]
