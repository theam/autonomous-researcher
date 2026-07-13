# Cloud runtime verification dossier

## Acceptance claims

| Claim | Mechanism | Automated evidence |
|---|---|---|
| Limina owns execution | API lifespan recovers `RUNNING`/`WAITING` projects; supervisor creates SDK sessions and checkpoints | supervisor ownership and lifecycle tests |
| Users do not manage Codex machinery | public CLI/OpenAPI expose only project concepts; serializers remove private state | public-surface and sanitized-status tests |
| Synchronous steering works | active SDK turn handle receives steering; WebSocket sends project messages | supervisor live-steer and WebSocket attach tests |
| Asynchronous steering survives disconnects | inbox write precedes live delivery and remains pending until checkpoint | durable inbox/checkpoint tests |
| New process can resume | thread ID is persisted through `on_thread` before tools execute | supervisor thread persistence test |
| Several viewers share one history | persisted event sequence is replayed independently of WebSocket connection | API event-stream ordering tests |
| Private agent writes are scoped | short-lived capability maps to one project; internal routes are absent from OpenAPI | capability authorization test |
| Control-plane credentials stay out of Codex | adapter builds an allow-listed environment plus project variables/secrets | adapter/runtime boundary test |
| Secrets are write-only | authenticated encryption at rest; public projections and events contain metadata only | service and API redaction tests |
| H → E → F is enforced | experiment requires H; finding requires completed E | invariant tests |
| Parallel KB writes are safe | atomic ID allocation, per-experiment leases, append-only observations, CAS transitions | concurrency and stale-write tests |
| Export remains portable | deterministic snapshot passes the existing KB validator | export validation test |
| Production schema is reproducible | Alembic upgrade/downgrade and PostgreSQL DDL compile | migration tests |

## Commands to reproduce

```bash
uv sync --extra codex
uv run ruff check src/limina_cloud tests/test_cloud_api.py tests/test_cloud_cli.py \
  tests/test_cloud_runtime.py tests/test_cloud_migrations.py
uv run python -m unittest \
  tests.test_cloud_api \
  tests.test_cloud_cli \
  tests.test_cloud_runtime \
  tests.test_cloud_migrations
python3 scripts/kb_validate.py
OPENAI_API_KEY=test LIMINA_API_TOKEN=acceptance-test-token docker compose config
LIMINA_API_TOKEN=acceptance-test-token docker compose -f compose.cloud.yaml config
```

The final handoff should include verbatim output from those commands. A Docker image build is a
separate acceptance check when a Docker daemon is available.

## Codex integration evidence

The implementation uses `openai-codex` and its pinned Codex runtime. The adapter depends on:

- starting and resuming threads;
- starting a turn with a JSON output schema;
- consuming the turn notification stream;
- steering an active turn;
- interrupting an active turn.

These behaviors correspond to the official [Codex SDK](https://developers.openai.com/codex/sdk/)
and [app-server turn lifecycle](https://developers.openai.com/codex/app-server/) documentation.
The branch also isolates its one private SDK helper import inside `CodexAgentSession`; this is the
main compatibility risk while the Python package remains beta.

### Live managed-runtime smoke test — 2026-07-13

The official SDK was exercised against the actual Limina server, not only a fake session:

1. A direct structured turn started SDK thread
   `019f5b54-d13f-7202-9ffe-1f587b3c180a` and returned `status=COMPLETE`.
2. A deliberately failed project was resumed through `limina resume runtime-smoke`, exercising
   startup recovery instead of creating a fresh user-managed session.
3. The managed Codex turn reached the capability-scoped private API from its workspace sandbox:

   ```text
   GET /internal/v1/projects/runtime-smoke/status HTTP/1.1 200 OK
   GET /internal/v1/projects/runtime-smoke/artifacts HTTP/1.1 200 OK
   ```

4. Steering submitted while the turn was active returned:

   ```json
   {"delivery":"LIVE"}
   ```

5. The supervisor committed the final project checkpoint:

   ```json
   {
     "status": "COMPLETE",
     "next_step": "Accept this checkpoint and close the runtime smoke test.",
     "blocker": "None",
     "knowledge": {},
     "pending_guidance": 0
   }
   ```

The first smoke attempt also caught a real isolation defect: blanking Codex's own origin metadata
prevented SDK initialization. The allow-list now retains non-secret Codex process metadata while
explicitly emptying database, admin-token, and unrelated environment values. That boundary has a
dedicated regression test.

### Single-instance and resource smoke test — 2026-07-13

The actual default path, `docker compose up --build --detach`, built the Codex runtime image,
created one `limina-data` volume, applied both migrations, and started one healthy server process.
`limina doctor` reported `runtime_owner=limina`; a project was created; `DATASET_URI` was set as a
visible variable; and `SERVICE_TOKEN` was submitted through `--from-env`. The list response was:

```json
[
  {"name":"DATASET_URI","type":"VARIABLE","value":"s3://example/eval.parquet"},
  {"name":"SERVICE_TOKEN","type":"SECRET","configured":true}
]
```

The literal secret was absent from CLI output and a byte scan of the persistent directory. Inside
the container the key was owned by `limina:limina` with mode `0600`. After a real container restart,
the project and configured-secret metadata remained available. Automated tests additionally reopen
that key, decrypt the project secret, verify project/name binding, rotate it, redact runtime output,
and verify logical value wiping on removal.

## Failure boundaries reviewed

- **API restarts:** lifespan recovery recreates project loops from database state.
- **Runtime dies before a final checkpoint:** the thread pointer and any accepted KB commands are
  already durable; the lease eventually permits takeover.
- **Long turn:** a background heartbeat renews the coordinator lease; lease loss interrupts the
  turn rather than allowing a stale checkpoint.
- **Pause/stop during a turn:** SDK interruption is requested and lifecycle state wins over the
  turn's proposed checkpoint.
- **Two replicas recover the same project:** only one obtains the coordinator lease.
- **Lost HTTP response:** idempotency receipts return the original database result.
- **Lost WebSocket:** accepted guidance and events remain in PostgreSQL; reconnect replays them.
- **Missing live turn:** feedback remains queued instead of failing.
- **Concurrent artifact creation:** per-kind atomic counters allocate unique IDs.
- **Concurrent independent experiments:** leases are scoped to experiment IDs, not the project.
- **Stale decision:** compare-and-swap rejects it without acknowledging unrelated guidance.
- **Export failure:** canonical state remains valid; export can be retried.

## Known limits before production

The branch is a strong application prototype, not a finished multi-tenant control plane.

1. Public auth is one bearer token and actor attribution is caller-supplied; add OIDC and
   project-level RBAC.
2. Workspaces are durable directories, not yet isolated project containers or microVMs.
3. Large evidence uses external URIs but no built-in object-store lifecycle manager.
4. Live steering is durable-at-least-once at the inbox boundary; a process failure at the exact
   SDK-delivery boundary can cause replay.
5. The Python SDK is beta and the streaming result collector used by the adapter is private.
6. There is no transactional notification outbox, quota system, billing, or admin audit export.
7. Compose demonstrates one runtime replica; multi-replica failover should be exercised against
   managed PostgreSQL and the target container scheduler.
8. The auto-generated local encryption key favors one-command operation. Replicas must instead
   share `LIMINA_SECRET_KEY` from a proper secret manager, and backups need a separate key escrow.

Those limits do not change the public ownership model. Adding a workflow scheduler, sandbox
manager, or notification service must remain an internal Limina concern.
