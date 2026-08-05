# Managed runtime verification dossier

## Acceptance claims

| Claim | Mechanism | Automated evidence |
|---|---|---|
| Limina owns execution | API lifespan recovers active projects; supervisor selects and owns SDK sessions | supervisor ownership and lifecycle tests |
| Codex and Claude Code are selectable | immutable runtime column plus validated public `runtime` field | service, API, CLI, migration tests |
| Limina owns Codex login state | private `CODEX_HOME`, API-key/access-token materialization, and administrator-driven ChatGPT device login | auth lifecycle, permission, concurrency, and fresh-volume live tests |
| Users do not manage provider machinery | public CLI/OpenAPI expose project concepts; serializers remove private state | public-surface and sanitized-status tests |
| Agents use the same public boundary | authenticated MCP tools/resources call the shared project operation layer | MCP discovery, cross-transport, attribution, and resource tests |
| Team identity and roles are enforced | OIDC/JWT claims create principals; project membership gates every shared operation | signed-token, anti-spoofing, membership, and role tests |
| Browsers can attach safely | short-lived one-time live tickets carry project identity and role | ticket consumption, replay rejection, and read-only viewer tests |
| Synchronous steering works | Codex steers in-turn; Claude interrupts then redirects the same session | adapter, supervisor, and WebSocket tests |
| Asynchronous steering survives disconnects | inbox write precedes live delivery and remains pending until checkpoint | durable inbox/checkpoint tests |
| A new process can resume | provider continuation is persisted before/while managed work starts | supervisor and both adapter tests |
| Several viewers share one history | persisted event sequence is independent of WebSocket connections | event-stream ordering tests |
| Private writes are scoped | short-lived capability maps to one project; internal routes are absent from OpenAPI | capability authorization tests |
| Control-plane credentials stay private | adapters build allow-listed child environments | provider environment-boundary tests |
| Secrets are write-only | encryption at rest plus public and runtime redaction | service, API, and adapter redaction tests |
| Resource changes reach active work safely | controlled restart discards the stale turn and rematerializes its environment | resource-refresh supervisor test |
| H → E → F is enforced | experiment requires H; finding requires completed E | invariant tests |
| Parallel KB writes are safe | atomic IDs, per-experiment leases, append-only observations, CAS transitions | concurrency and stale-write tests |
| Knowledge is queryable and visualizable | PostgreSQL FTS, paginated filters, graph relations, tags, comments, revisions, and saved views | UI-readiness API and migration tests |
| Runtime work is observable | every managed turn has a correlated run record with timing, events, errors, tools, and available usage | supervisor run, run detail, and analytics tests |
| Usage and cost are not conflated | per-turn provider usage and separate provider/operator-rate provenance | resumed-thread usage, pricing, migration, API, and live Codex tests |
| Transient provider failures recover durably | typed retry classification, attempt-per-run records, persisted wake time, and bounded backoff | retry/recovery tests |
| Public diagnostics stay product-level | run events use the same sanitizer as activity/live views; receipts are scoped to signed subjects | internal-field redaction, duplicate-display-name, and cross-project replay tests |
| Export remains portable | deterministic snapshot passes the existing KB validator | export validation test |
| Schema upgrades preserve Codex projects | migration defaults old projects to Codex and renames private continuity state | upgrade/downgrade and preservation tests |

## Commands to reproduce

```bash
uv sync --extra runtimes
uv run ruff format --check src migrations tests/test_cloud_*.py
uv run ruff check src migrations tests/test_cloud_*.py
uv run python -m unittest discover -s tests
LIMINA_DATABASE_URL=postgresql+psycopg://limina:limina@localhost/limina \
  uv run alembic upgrade head --sql >/dev/null
python3 scripts/kb_validate.py
OPENAI_API_KEY=test ANTHROPIC_API_KEY=test LIMINA_API_TOKEN=acceptance-test-token \
  docker compose config
OPENAI_API_KEY=test ANTHROPIC_API_KEY=test LIMINA_API_TOKEN=acceptance-test-token \
  docker compose -f compose.cloud.yaml config
```

`make runtime-check` runs those mechanical checks. Building `Dockerfile.cloud` is a separate
acceptance step when a Docker daemon is available.

### UI control-plane shipping review — 2026-07-14

An independent API/security review initially found three defects: a cross-project comment replay,
raw internal fields in run-detail events, and possible last-owner demotion. The fixes now have
regression tests. A second independent pass verified those fixes, signed-subject receipt scoping,
secret-redacted failure storage, source-credential rejection, and concurrent owner locking, and
reported no remaining P0/P1 issue.

The current production image was rebuilt in an isolated Compose project and returned an
authenticated health response advertising Limina runtime ownership, both engine adapters, REST,
and MCP. The smoke volume and network were removed after the check.

### API and MCP packaged smoke — 2026-07-14

`Dockerfile.cloud` was rebuilt with the direct `mcp` dependency and started as an unprivileged
container on a clean SQLite store. The published server reported:

```json
{
  "ok": true,
  "runtime_owner": "limina",
  "runtimes": ["codex", "claude-code"],
  "interfaces": {"rest": "/v1", "mcp": "/mcp/"}
}
```

An authenticated MCP `initialize` negotiated protocol `2025-06-18`. A subsequent
`limina_create_project` tool call, attributed with `X-Limina-Actor`, returned structured project
content with `isError=false`. A REST read then returned the same `mcp-smoke` project and durable
timestamps from the canonical store. This proves the packaged process, mounted Streamable HTTP
transport, authentication middleware, MCP tool dispatch, shared operation layer, and REST/MCP
state convergence without invoking either paid provider runtime.

## Codex adapter evidence

The adapter uses `openai-codex` for:

- starting and resuming threads;
- JSON-schema turn output;
- consuming notification streams;
- steering an active turn;
- interrupting active work.

These behaviors correspond to the official [Codex SDK](https://developers.openai.com/codex/sdk/)
and [app-server turn lifecycle](https://developers.openai.com/codex/app-server/) documentation.
The streaming result collector is currently a private SDK helper, isolated inside the adapter and
called out as a compatibility risk.

### Live Codex smoke — 2026-07-13

The official SDK was exercised against an actual Limina server:

1. A structured turn started SDK thread `019f5b54-d13f-7202-9ffe-1f587b3c180a` and returned
   `status=COMPLETE`.
2. A deliberately failed project was resumed through `limina resume runtime-smoke`, exercising
   recovery rather than a user-managed session.
3. The managed turn reached the capability-scoped private API from its workspace sandbox:

   ```text
   GET /internal/v1/projects/runtime-smoke/status HTTP/1.1 200 OK
   GET /internal/v1/projects/runtime-smoke/artifacts HTTP/1.1 200 OK
   ```

4. Steering submitted during the turn returned:

   ```json
   {"delivery":"LIVE"}
   ```

5. The supervisor committed:

   ```json
   {
     "status": "COMPLETE",
     "next_step": "Accept this checkpoint and close the runtime smoke test.",
     "blocker": "None",
     "knowledge": {},
     "pending_guidance": 0
   }
   ```

The first attempt found an environment-isolation defect: blanking Codex origin metadata prevented
SDK initialization. The allow-list now retains required, non-secret Codex metadata while blanking
database, admin-token, and unrelated values. A regression test covers that boundary.

### Fresh-volume Codex authentication and telemetry acceptance — 2026-07-15

[[E002]] rebuilt the current image and started an isolated Compose project with a fresh named
volume. The previously supplied API key entered the test through no-echo process input, was never a
command argument, and was removed with the container and volume after the run. Only public Limina
CLI commands created and started the project; there was no directory repair or manual `codex login`.

The first managed turn completed in 51,192 ms with `gpt-5.4`, 24 tool calls, no retry, and a durable
H→E→F chain. The provider reported 19,824 input, 18,816 cached-input, 217 output, 90 reasoning-output,
and 20,041 total tokens. `usage_source=provider`; cost and `cost_source` were null because no operator
price was configured. This is the intended honest state rather than an inferred provider price.

Post-run checks found no credential pattern in durable project events, found the Codex state
directory at mode `0700` and `auth.json` at `0600`, and found no residual test container or volume.
The complete finding matrix and raw summary are under `kb/research/data/E002/`.

The same acceptance run exercised the automated suite:

```text
Ran 77 tests in 4.720s

OK
KB validation passed.
```

ChatGPT account login is available through `limina runtime codex login --method chatgpt` and the
instance-administrator REST flow. Device start/poll/cancel and auth/turn exclusion are covered by
the pinned SDK contract tests. Completing the browser code was intentionally not part of the
API-key trial; cached ChatGPT credentials remain single-runtime-node state and serialize Codex
turns, as documented in the deployment contract.

## Claude Code adapter evidence

The adapter uses the official
[Claude Agent SDK for Python](https://platform.claude.com/docs/en/agent-sdk/python) for:

- connecting a persistent client and resuming a session ID;
- the bundled Claude Code tool and system-prompt preset;
- JSON-schema structured output;
- sandbox and tool-permission controls;
- receiving assistant, tool, task, and result messages;
- interrupting active responses;
- redirecting a live session with newly committed steering.

Contract tests replace the SDK module with a deterministic fake and verify option construction,
workspace and environment isolation, session resume/persistence, event mapping, structured
checkpoint parsing, disconnect, and interrupt-then-redirect steering. These tests exercise the
adapter protocol without spending provider credits.

No live Anthropic API smoke has yet been recorded. That remains an explicit release-evidence gap,
not an implied pass. A live smoke should create a `claude-code` project, perform one private
knowledge command, steer while it is active, restart the server, and prove the same session resumes.

## Single-instance and resource evidence — 2026-07-13

The default `docker compose up --build --detach` path built the earlier Codex-only image, created
one `limina-data` volume, applied migrations, and started one healthy server. `limina doctor`
reported `runtime_owner=limina`; a visible `DATASET_URI` and write-only `SERVICE_TOKEN` produced:

```json
[
  {"name":"DATASET_URI","type":"VARIABLE","value":"s3://example/eval.parquet"},
  {"name":"SERVICE_TOKEN","type":"SECRET","configured":true}
]
```

The secret was absent from CLI output and a byte scan of persistent storage. The encryption key was
owned by `limina:limina` with mode `0600`. Project and secret metadata survived a container restart.
Automated tests additionally reopen the key, decrypt with project/name binding, rotate, redact
runtime output, and verify logical value wiping on removal.

That historical run does not establish that the newly added Claude SDK packages correctly; the
current two-runtime result is recorded separately below.

### Two-runtime packaging and server smoke — 2026-07-14

`Dockerfile.cloud` built successfully for Linux arm64 with both `openai-codex` and
`claude-agent-sdk`, plus Claude Code's `bubblewrap` and `socat` sandbox dependencies. A container
check loaded both SDKs, executed a basic unprivileged `bubblewrap` boundary, and rendered packaged
`limina` project help. A fresh one-command Compose instance then:

1. applied the runtime migrations and became healthy;
2. advertised `runtimes=["codex", "claude-code"]`;
3. accepted one `runtime=codex` project and one `runtime=claude-code` project;
4. returned each immutable runtime through the public project projection;
5. shut down cleanly, with the isolated smoke volume removed.

This establishes image packaging, migration startup, health discovery, and runtime selection. It
does not replace the live Anthropic execution smoke described above.

## Failure boundaries reviewed

- **API restarts:** lifespan recovery recreates loops from canonical project state.
- **Runtime dies before a final checkpoint:** the continuation pointer and accepted knowledge are
  already durable; the lease eventually permits takeover.
- **Long turn:** a heartbeat renews the coordinator lease; lease loss interrupts the turn.
- **Pause/stop during a turn:** provider interruption is requested and lifecycle state wins over a
  proposed checkpoint.
- **Two replicas recover one project:** only one obtains the coordinator lease.
- **Lost HTTP response:** idempotency receipts return the original database result.
- **MCP retry:** callers may supply the same durable idempotency key; no provider session is exposed.
- **Lost WebSocket:** guidance and events remain durable; reconnect replays them.
- **Missing live turn:** feedback remains queued.
- **Concurrent artifacts:** per-kind atomic counters allocate unique IDs.
- **Concurrent experiments:** leases are scoped to experiment IDs, not the project.
- **Stale decision:** compare-and-swap rejects it without acknowledging unrelated guidance.
- **Export failure:** canonical state remains valid and export can be retried.
- **Unknown runtime value:** validation rejects it; the factory also fails closed.
- **Old database:** migration assigns existing projects to Codex and preserves their continuation.

## Known limits before production

1. Workspaces are durable directories, not isolated project containers or microVMs.
2. Bounded uploads live in the project workspace; large evidence has external URIs but no
   object-store lifecycle manager or malware-scanning pipeline.
3. Live guidance is durable-at-least-once; exact boundary failures may replay a message.
4. The Codex Python SDK is beta and one private result collector remains a compatibility risk.
5. Claude Code continuity includes provider-managed local transcript files; backup and restore of
   the Limina volume must preserve those files with the database.
6. A live Claude Code provider smoke and restart-resume proof are still required.
7. There is no transactional notification outbox, quota system, billing, or admin audit export.
8. Compose demonstrates one runtime replica; multi-replica failover still needs a target-platform
   test against managed PostgreSQL.
9. The generated local encryption key favors one-command operation. Replicas need a shared key
    from a secrets manager, and backups need separate key escrow.
10. MCP intentionally omits secret-value writes; automation that provisions secrets must use the
    trusted CLI or REST API. Remote hostnames must be added to the MCP DNS-rebinding allowlist.

These limits do not change runtime ownership. A scheduler, sandbox manager, or notification service
must remain an internal Limina concern rather than exposing provider session management to users.
