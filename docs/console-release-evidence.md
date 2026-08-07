# Limina Console release evidence

Date: 2026-08-07
Candidate branch: `feat/limina-console-tam50`

This ledger separates what the local release candidate proves from what still requires an external
tenant, destination, or paid executor. Passing a local fake is not presented as live-provider
evidence.

## Confirmed in the repository

- `/v2` is the only public application API; `/internal/v1` remains private and absent from public
  OpenAPI.
- WorkOS-shaped issuer, organization, permission, expiry, and signature fixtures cover positive and
  hostile token cases. Developer JWT mode is loopback-only, explicitly enabled, and subject to the
  same durable project membership rules.
- The Next.js BFF keeps access tokens server-side. Live tickets are one-use, project-scoped,
  origin-protected, bounded, and carried in the `limina.v2` WebSocket subprotocol.
- All eight attention kinds materialize without a queue read through a 30-second runtime-owned
  reconciliation cycle. Singular requests support answer, selection, confirmation, rejection, and
  structured artifact review; terminal/archive expiration, project-wide failed-run acknowledgement,
  recovery auto-clear, per-user snoozes, durable steering, capability-filtered actions, and typed
  stale/invalid-action conflicts have automated coverage.
- Notification credentials are encrypted and write-only. Outbox delivery is transactional,
  idempotent, bounded, retryable, HMAC-signed for generic webhooks, secret-redacted, redirect-free,
  and protected against DNS-rebinding with connect-time IP pinning.
- Every attention notification deep-links to its exact durable episode; Slack and webhooks remain
  transports rather than alternate control planes.
- The generated TypeScript client matches the checked-in `/v2` OpenAPI contract.
- The production Compose topology runs PostgreSQL, migrations, runtime, Next.js, and Caddy with
  explicit auth-mode selection.
- Desktop and mobile Chromium journeys cover meaningful rendering, keyboard skip navigation,
  critical/serious axe findings, hierarchical workspace/project/settings navigation, project
  creation, write-only secret rendering, live-ticket issue, and attached WebSocket connection.
- The Vercel-inspired navigation pass replaces the horizontal project tabs and settings card grid
  with a persistent project rail, route-level settings categories, read-state-first rows, and
  URL-addressable edit/add forms. The project brief and preflight remain on Overview rather than
  being duplicated as configurable settings.

Independent judgment records:

- [Claude Code Opus 5 navigation acceptance](reviews/claude-fable-console-navigation-acceptance-2026-08-07.md)
  — **APPROVE** after reciprocal resolution; no open P0/P1.
- [Claude Code Opus 5 implementation acceptance](reviews/claude-fable-console-acceptance-2026-08-06.md)
  — **APPROVE WITH FOLLOW-UPS**, no P0/P1.
- [Canonical TAM-50 evaluation](../apps/web/evaluation.md) — **Compliant**, 24/24 UX checks and
  7/7 applicable TAM-50 checks pass; imagery N/A.
- [TAM resolution event](../apps/web/resolution-event.md) — closed as `corrected`, with no open fix
  and no accepted drift.

## Final local acceptance

### Backend, migrations, deployment manifests, and durable state

Command: `make runtime-check`

```text
uv run ruff format --check src migrations tests/test_cloud_*.py tests/test_console_*.py
63 files already formatted
uv run ruff check src migrations tests/test_cloud_*.py tests/test_console_*.py
All checks passed!
uv run python -m unittest discover -s tests
...............................................................................................................................
----------------------------------------------------------------------
Ran 127 tests in 7.812s

OK
LIMINA_DATABASE_URL=postgresql+psycopg://limina:limina@localhost/limina uv run alembic upgrade head --sql >/dev/null
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Generating static SQL
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> 474c29565487, initial challenge runtime
INFO  [alembic.runtime.migration] Running upgrade 474c29565487 -> 9a62d4f771c1, resource variables and encrypted secrets
INFO  [alembic.runtime.migration] Running upgrade 9a62d4f771c1 -> c0d3c1a2b7e9, add selectable runtime engines
INFO  [alembic.runtime.migration] Running upgrade c0d3c1a2b7e9 -> 7e4a19b8d2c6, UI-ready collaboration, knowledge graph, and runtime observability.
INFO  [alembic.runtime.migration] Running upgrade 7e4a19b8d2c6 -> 1f6a2c8d9e10, Add per-turn token detail and cost provenance.
INFO  [alembic.runtime.migration] Running upgrade 1f6a2c8d9e10 -> console_attention_and_review, Add attention episodes, dispositions, and revision-pinned reviews.
INFO  [alembic.runtime.migration] Running upgrade console_attention_and_review -> console_notifications, Add project notification channels, rules, outbox, and delivery history.
OPENAI_API_KEY=test ANTHROPIC_API_KEY=test LIMINA_API_TOKEN=test docker compose config >/dev/null
OPENAI_API_KEY=test ANTHROPIC_API_KEY=test LIMINA_API_TOKEN=test LIMINA_UI_AUTH_MODE=local LIMINA_ALLOW_LOCAL_AUTH=1 LIMINA_CONSOLE_DEV_AUTH=1 LIMINA_DEV_JWT_SECRET=test-only-secret-000000000000000000000000 docker compose -f compose.cloud.yaml config >/dev/null
LIMINA_TELEMETRY_INTERNAL=1 python3 scripts/kb_validate.py
KB validation passed.
```

### Frontend contract, security boundary, static analysis, and unit tests

Commands: `pnpm contract:check`, `pnpm check:auth-boundary`, `pnpm typecheck`, `pnpm lint`, and
`pnpm test` from `apps/web`.

```text
$ cd ../.. && uv run python scripts/console_contract.py --check
✨ openapi-typescript 7.13.0
🚀 /Users/adrian-theam/.codex/worktrees/3a40/researcher/contracts/openapi.v2.json → /var/folders/f_/3v3v82zj2njg7175zh3vt6r80000gp/T/limina-client-imyo8y48/generated.ts [109.9ms]
$ node scripts/check-authorization-boundary.mjs
$ tsc --noEmit
$ eslint . --max-warnings=0
$ vitest run

 RUN  v3.2.4 /Users/adrian-theam/.codex/worktrees/3a40/researcher/apps/web

 ✓ lib/request-origin.test.ts (2 tests) 3ms
 ✓ lib/attention-presenter.test.ts (2 tests) 15ms
 ✓ lib/env-schema.test.ts (4 tests) 3ms
 ✓ components/action-notice.test.tsx (2 tests) 33ms
 ✓ components/attention-desk.test.tsx (2 tests) 15ms

 Test Files  5 passed (5)
      Tests  12 passed (12)
```

### Production build

Command: `pnpm build` from `apps/web`.

```text
$ LIMINA_ALLOW_LOCAL_AUTH=1 next build
   ▲ Next.js 15.5.21

   Creating an optimized production build ...
 ✓ Compiled successfully in 1456ms
   Linting and checking validity of types ...
   Collecting page data ...
 ✓ Generating static pages (10/10)
   Finalizing page optimization ...
   Collecting build traces ...
```

### Live desktop and mobile browser acceptance

Command: `pnpm test:e2e` from `apps/web`, against the deployed Compose instance.

```text
$ playwright test

Running 18 tests using 8 workers

  18 passed (9.6s)
```

The browser run created deterministic `console-e2e-*` fixtures. Those exact rows were deleted
after the pass; the local handoff database contains only `retrieval-reliability` and
`retrieval-reliability-clone`.

### Deployed local topology

```text
NAMES                   STATUS                    PORTS
researcher-web-1        Up 34 minutes (healthy)
researcher-ingress-1    Up 35 minutes
researcher-runtime-1    Up 35 minutes (healthy)   127.0.0.1:7433->7433/tcp
researcher-postgres-1   Up 2 hours (healthy)      5432/tcp
```

`GET http://127.0.0.1:7433/api/health` returned HTTP 200 with:

```json
{"ok":true,"runtime":"ready"}
```

## External proof still required before a public team launch

| Gate | Why local evidence is insufficient | Required proof |
|---|---|---|
| Dedicated WorkOS staging tenant | Fixtures cannot prove the tenant's actual token/refresh claims or permission setup | Sign in, refresh, deep-link return, deny missing `limina:access`, org mismatch, directory search, and sign out against the dedicated client |
| Slack workspace | Payload tests cannot prove real Slack rendering, revocation, rate behavior, or operator trust choice | Configure a staging incoming webhook, send every severity, inspect desktop/mobile rendering, revoke it, and observe typed failure attention |
| Public generic-webhook endpoint | Unit transport tests prove pinning/signing but not a real internet TLS/delivery path | Deliver to an owned HTTPS endpoint, verify signature/replay rejection, rotate the secret, and exercise timeout/retry/dead-letter behavior |
| Both paid executor providers | Contract fakes cannot establish provider account policy, model availability, or current SDK behavior | Complete one bounded Codex and one Claude Code project, answer a live request, steer while active, restart, and prove continuation plus H/E/F evidence |
| Multi-replica/request spike | Local Compose is one runtime process | Run PostgreSQL-backed multi-process SSE/live/attention load and document replay, backpressure, auth-cache expiry, and no duplicate notifications |

## Launch policy decision

The implemented default makes `unattended_run` informational and snoozable. It does not stop a
runtime automatically. A hard wall-clock or turn-count stop remains a leader-approved policy change,
not an implicit behavior hidden in this release.
