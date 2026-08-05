---
id: "F001"
aliases: ["F001"]
type: finding
hypothesis: "H001"
experiment: "E001"
impact: "HIGH"
created: "2026-07-15"
tags: []
---

# F001 — Managed Codex PoC works but fresh-volume onboarding is not unattended

> **Created**: 2026-07-15
> **Hypothesis**: [[H001]]
> **Experiment**: [[E001]]
> **Impact**: HIGH

## Finding

Limina completed a real managed Codex PoC and produced a durable, reviewable H -> E -> F chain, but
the advertised fresh-volume Codex path required two manual environment recoveries; the branch merits
a conditional trusted-operator internal PoC after those release-blocking onboarding defects are
fixed, not production adoption.

## Evidence

- [[E001]] completed 7/7 first-run milestones and all 5 critical milestones while passing all four
  predeclared time, credential, repository-integrity, and provider-session guardrails.
- The key-bearing evaluator process ran for 1,001.4 seconds against a 1,740-second hard deadline.
- The successful Limina-owned run used Codex `gpt-5.4`, completed 37 tool calls in 97,810 ms, cloned
  the public repository read-only, and published H001 CONFIRMED -> E001 COMPLETED -> F001 PUBLISHED.
- Before success, the first run failed because `/var/lib/limina/codex` did not exist; the second
  failed because the bundled Codex CLI returned `401 Missing bearer` despite `OPENAI_API_KEY` being
  present. Both were reproduced and recovered without tracked product edits.
- Provider usage and cost fields were null. The full evidence and code citations are in the
  [Claude Fable enterprise evaluation](../../../docs/reviews/claude-fable-enterprise-evaluation-2026-07-15.md)
  and structured metrics under `kb/research/data/E001/`.

## What Improved For Real

This closes the prior live-proof gap for the Codex engine. The test directly established that
Limina can own the provider process and workspace, inject a project resource, record structured run
observability, enforce the evidence chain, expose the result for review, and stop cleanly without
making the evaluator manage provider sessions, threads, workers, or subagents.

## Remaining Debt

- The image must create `CODEX_HOME` on a fresh volume.
- The Codex adapter must establish the bundled CLI's authentication state from the configured API
  key without a manual `codex login` step.
- EDITOR-supplied variables can include interpreter-hijack names such as `NODE_OPTIONS`; the runtime
  overlay needs an allowlist or stronger scrubbing before membership expands beyond trusted users.
- Codex usage and cost are unavailable, so current analytics cannot enforce a spend budget.
- Claude Code execution, OIDC, PostgreSQL/multi-replica coordination, restart recovery, live
  steering, load, and production isolation remain unverified in this experiment.

## Next Move

Fix the two fresh-volume blockers and add an opt-in paid smoke test that proves a clean Compose volume
can complete one Codex turn using only documented configuration. Then close the variable-injection
boundary and rerun [[E001]] before onboarding an internal PoC cohort.

## Links

- Mission: [[CHALLENGE]]
- Active State: [[ACTIVE]]
- Parent Hypothesis: [[H001]]
- Parent Experiment: [[E001]]
