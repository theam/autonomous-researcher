---
id: "H002"
aliases: ["H002"]
type: hypothesis
status: CONFIRMED
created: "2026-07-15"
last_updated: "2026-07-15"
tags: []
---

# H002 — Enterprise finding remediation closes managed runtime release blockers

> **Status**: CONFIRMED
> **Created**: 2026-07-15
> **Last updated**: 2026-07-15

## Statement

If the enterprise-review findings in [[F001]] are remediated with runtime-side state initialization,
dual Codex authentication, defense-in-depth environment policy, per-turn usage accounting, explicit
cost provenance, bounded retries, scoped local administration, probe/rate-limit/WebSocket hardening,
locked CI, single-owner migrations, and focused module extraction, then a fresh-volume API-key Codex
project will complete unattended with non-null token telemetry and the full offline acceptance matrix
will pass without credential disclosure or regression of the project-level CLI/API/MCP contract.

## Mechanism

Limina will own Codex authentication as instance state instead of assuming an environment variable is
sufficient. A runtime auth manager will create and permission `CODEX_HOME`, materialize API-key or
enterprise-token login through the pinned SDK, support administrator-driven ChatGPT device login,
serialize auth mutation against active turns, and remove raw credentials from the child environment.
Independent policy, usage, retry, probe, rate-limit, and transport modules make the trust boundaries
explicit and testable instead of relying on scattered denylists or aspirational database columns.

## Why This Might Generalize

The fixes target lifecycle and trust-boundary mechanisms shared by all projects: fresh and existing
volumes, authentication selection, legacy resource rows, resumed threads, transient failures, health
orchestration, local and OIDC administration, and browser attachments. They do not depend on the
license-check PoC wording used in [[E001]].

## Shortcut Risks

- Mocked auth tests could pass while the bundled Codex CLI/SDK contract differs in Docker.
- Thread-cumulative token totals could look non-null while double-counting resumed turns.
- Rejecting dangerous variables only at write time would leave legacy rows exploitable.
- Removing the raw key from the environment does not make `CODEX_HOME/auth.json` unreadable to the
  Codex process; documentation and the threat model must remain honest.
- A single-node device-login flow does not establish safe multi-replica OAuth refresh behavior.
- Refactoring only new code would not resolve the oversized existing service modules.

## Test Plan

- Experiment: [[E002]].
- Comparator: [[E001]] at `6a80aa67efd63bb435f83cc9db8ae57cb372c9f5`, which required two
  manual recoveries, returned null usage/cost, and recorded 2 HIGH, 4 MEDIUM, and 5 LOW findings.
- Primary metric: enterprise finding disposition, requiring every H/M finding closed and every LOW
  finding either closed or explicitly resolved by a bounded, documented trust posture.
- Required live result: fresh named volume plus only documented API-key configuration completes one
  Codex turn with no directory creation or manual `codex login`; input/output token usage is non-null.
- Required offline slices: auth precedence/device login/admin lock; legacy env scrub; per-turn usage
  across a resumed thread; cost provenance; retry taxonomy/backoff; rate limiting; liveness/readiness;
  WebSocket subprotocol tickets; migration ownership; locked CI; module-size boundary; API/MCP tests.
- Guardrails: no secret in argv, logs, events, repository, or test output; paid key-bearing execution
  under 30 minutes; no provider-session surface exposed to project users or MCP; tracked docs state
  ChatGPT auth's single-runtime-node and readable-credential-store limitations.
- Confirm if: `make runtime-check` passes, all new regression tests pass, core orchestration modules
  are each under 1,000 lines, and the live API-key smoke test meets the required result and guardrails.
- Reject if: a method-valid fresh-volume API-key run still needs manual intervention, any dangerous
  legacy resource reaches a child process, resumed-turn usage double-counts, or an auth mutation can
  race an active Codex turn.
- Inconclusive if: an external OpenAI outage or account restriction prevents the live proof after all
  local method-validity checks pass; retain the offline result separately.

## Evidence

- [[F001]] and the
  [Claude Fable enterprise evaluation](../../../docs/reviews/claude-fable-enterprise-evaluation-2026-07-15.md)
  provide reproduced failures and severity-ranked debt.
- Official Codex authentication documentation confirms ChatGPT browser/device login, API-key login
  through stdin, enterprise access-token login, `CODEX_HOME` credential caching, and explicit login
  method enforcement.
- The pinned SDK exposes device-code/API-key login and per-turn token notifications; code inspection
  confirmed Limina currently reads the nested token object incorrectly.
- Claude Fable's remediation design review identified the required auth lock, per-turn rather than
  thread-total accounting, defense-in-depth variable scrub, and single-node ChatGPT scope.

## Conclusion

Confirmed by [[E002]] and [[F002]]. The full offline matrix passed, a fresh named volume completed
its first managed Codex project with no manual recovery and non-null per-turn provider usage, and
the final Claude Fable review's two P1 and two P2 findings were fixed and independently re-verified.
This establishes readiness for a trusted internal Codex PoC; it does not establish multi-tenant,
multi-replica, or Claude Code production readiness.

## Links

- Mission: [[CHALLENGE]]
- Active State: [[ACTIVE]]
- Experiment: [[E002]]
- Finding: [[F002]]
