# Claude Code Opus 5 acceptance review — Limina Console

Date: 2026-08-06

Reviewed branch: `feat/limina-console-tam50`

Review posture: independent, max-reasoning acceptance pass after Codex implementation and the first reciprocal audit

Verdict: **APPROVE WITH FOLLOW-UPS**

Claude reviewed the implemented backend, web application, authorization boundary, attention lifecycle, notification path, deployment topology, tests, and product documentation. The reviewer did not author the final fixes it judged.

## Release-blocking closure

| Prior finding | Final disposition | Evidence accepted by the reviewer |
|---|---|---|
| Attention existed only after a UI read | **Closed** | Runtime-owned reconciliation runs every 30 seconds and materializes all attention kinds without a browser request. |
| Run failure state could remain stale or duplicate | **Closed** | Derivation is based on the latest run, recovery auto-clears, project-wide acknowledgement closes the episode, and the acknowledged source cannot reopen. |
| Confirmation and structured review did not carry full domain meaning | **Closed** | Confirmation supports Confirm and Reject with required rationale; structured ArtifactReview resolves the exact request, closes review episodes, writes guidance, and wakes the supervisor. |
| Requests could survive terminal project state | **Closed** | Open requests expire on archive and coordinator Complete/Failed transitions. |

Claude reported **no new P0 or P1 finding** and considered the release candidate ready for the independent TAM-50 evaluation and leader testing, contingent on the mechanical acceptance suite.

## Boundaries explicitly re-verified

- Public API is `/v2`; `/internal/v1` is private and excluded from public OpenAPI.
- WorkOS/BFF authentication keeps access tokens server-side and project authorization remains capability-driven.
- Developer auth is explicit, loopback-only, and has no default administrator identity.
- Notification delivery uses durable outbox semantics, encrypted write-only credentials, exact-episode deep links, HMAC signing, and connect-time IP pinning.
- The UI metadata and implementation bind to TAM-50 version `0.2.6`.

## Non-blocking follow-ups

The reviewer retained these as P2/P3 improvements, not release blockers:

- Preserve kickoff-draft input more explicitly across a rare server-side conflict path.
- Expire a superseded generic steering request when the later checkpoint leaves `WAITING`.
- Apply project-scoped not-found mapping uniformly to every project route.
- Narrow generic free-form `REVIEW` handling so only structured ArtifactReview can close a review request.
- Eliminate a theoretical acknowledgement-marker race if the derived source changes at the same instant.
- Avoid invoking a newly enabled notification rule for an episode already closed during the same scan; revisit full-scan scaling.
- Add a root `global-error` boundary in addition to the implemented route error and not-found boundaries.

## Collaboration record

Codex accepted and implemented each blocking objection rather than treating the first review as approval. Claude then re-read the changed implementation and closed those findings. Codex independently retained the follow-ups above as explicit debt and sent the same frozen UI artifact to a separate canonical TAM evaluator.
