---
id: "E001"
aliases: ["E001"]
type: experiment
status: COMPLETED
hypothesis: "H001"
created: "2026-07-15"
completed: "2026-07-15"
tags: []
---

# E001 — Fresh enterprise evaluator onboarding and PoC

> **Status**: COMPLETED
> **Hypothesis**: [[H001]]
> **Created**: 2026-07-15
> **Completed**: 2026-07-15

## Objective

Decide whether an enterprise AI engineering team should advance Limina from repository review to an
internal Codex PoC. Compare actual first-run milestone completion with the README's advertised
seven-milestone happy path, while identifying correctness, security, operability, maintainability,
and adoption risks.

## Setup

- Environment: fresh clone at `/tmp/limina-enterprise-eval.8NCHCy`, macOS host, Docker 28.0.1,
  Docker Compose 2.33.1, branch `feat/cloud-challenge-runtime` at
  `6a80aa67efd63bb435f83cc9db8ae57cb372c9f5`.
- Evaluator: Claude Code 2.1.209, model alias `fable`, `--effort max`, enterprise AI engineer role,
  non-interactive `/goal` loop.
- Data: public repository, README, code/tests, generated Limina events and knowledge, and one small
  self-referential repository-analysis PoC.
- Compute: local Docker Desktop; one exploratory run.
- External services: Anthropic for the evaluator and OpenAI Codex for the Limina-owned runtime.
  Credentials are inherited in process environment and must never be persisted or displayed.
- Raw metrics: `kb/research/data/E001/`.

## Procedure

1. Record the evaluator's README-only first impression before inspecting implementation.
2. Review architecture, trust boundaries, runtime ownership, recovery, concurrency, secret handling,
   observability, tests, and enterprise adoption gaps.
3. Follow the documented quick start with one Compose command and run `limina doctor`.
4. Kick off a Codex project, provide a public repository resource, start it, observe it, and collect
   one small evidence-backed PoC result through Limina's project surfaces.
5. Stop the project and Compose stack, verify no tracked product changes or secret disclosure, and
   record exact commands, timings, failures, recoveries, and milestones.
6. Write `ENTERPRISE_EVALUATION_REPORT.md` in the evaluation clone with an evidence-backed adoption
   recommendation, then import the report and structured metrics into this experiment.
7. A hard external process deadline ends the evaluator and tears down the named Compose project
   before 30 minutes; the evaluator must write the report incrementally and reserve time for cleanup.

## Expected Outcome

- Confirm: at least 6/7 milestones, every critical milestone, and all four guardrails pass.
- Reject: 4/7 or fewer, or a product defect blocks a critical milestone.
- Inconclusive: an external provider, Docker, or evaluator failure prevents a method-valid run.
- Primary metric: milestone completion count, with each milestone evidenced in the report.
- Secondary metrics: elapsed minutes, manual recovery count, high/medium/low findings, and whether
  a coherent H -> E -> F result is reviewable.
- Guardrails: time, credential secrecy, clean tracked tree, and no provider-session management.

## Progress

- [x] (`2026-07-15`) Froze the remote branch revision and created a clean evaluation clone.
- [x] (`2026-07-15`) Defined thresholds, method-validity checks, guardrails, and hard cleanup policy.
- [x] (`2026-07-15`) Ran Claude Fable `/goal` evaluation and live Codex PoC in 1,001.4 seconds.
- [x] (`2026-07-15`) Imported report and raw metrics and classified the result.

## Results

- Primary metric: 7/7 first-run milestones completed versus the 7/7 README contract.
- Critical milestones: 5/5 completed.
- Guardrails: 4/4 passed; the key-bearing process ran for 1,001.4 seconds against a 1,740-second
  hard deadline, no credential was disclosed, no tracked product file changed, and the evaluator
  never managed a provider session.
- Live run: Limina-owned Codex `gpt-5.4`, 37 tool calls, 97,810 ms, status `COMPLETED`.
- Durable result: the evaluated project produced H001 CONFIRMED -> E001 COMPLETED -> F001 PUBLISHED.
- Recovery debt: two manual fixes were required before the live turn succeeded: the image did not
  create `CODEX_HOME`, and the bundled Codex CLI did not authenticate from `OPENAI_API_KEY` alone.
- Full evaluator report:
  [Claude Fable enterprise evaluation](../../../docs/reviews/claude-fable-enterprise-evaluation-2026-07-15.md).
- Raw metrics: `kb/research/data/E001/manifest.json`, `summary.json`, and `runs.csv`.

## Analysis

The method-valid run confirmed the core managed-runtime capability: a user can operate a project
while Limina owns the Codex process, workspace, run record, and durable H -> E -> F result. The
score clears the predeclared adoption threshold and all guardrails. However, two reproducible
packaging/authentication defects invalidate the claim that the documented Codex quick start is
currently unattended. The result is therefore a capability confirmation and a conditional internal
PoC recommendation, not a production-readiness or zero-touch-onboarding result. One local trial also
leaves OIDC, PostgreSQL coordination, restart recovery, live steering, Claude Code execution, load,
and multi-tenant isolation unverified.

## Decision

Advance only to a trusted-operator internal PoC after fixing the missing `CODEX_HOME` initialization
and Codex API-key authentication path. Close the EDITOR environment-injection risk before expanding
membership, and do not use current Codex analytics for cost enforcement because provider usage was
null. See [[F001]] for the decision-grade finding.

## Links

- Mission: [[CHALLENGE]]
- Active State: [[ACTIVE]]
- Parent Hypothesis: [[H001]]
- Finding: [[F001]]
