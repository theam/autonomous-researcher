# Limina cloud CLI

## The user story

I create a project by telling Limina what outcome matters, what success means, and what context it
should respect. I grant it named resources. I start it and leave; Limina owns the Codex runtime and
continues from durable state.

Later I can review what it has established, give feedback asynchronously, or enter the live
project and watch it work. Inside the live view I type normal strategic guidance. I never select a
thread, recover a session, dispatch a subagent, claim a lease, or write a checkpoint.

## Start an instance with one Docker command

Configure the two instance credentials once in `.env`:

```dotenv
OPENAI_API_KEY=...
LIMINA_API_TOKEN=replace-with-a-long-random-value
```

Then the complete single-instance server starts with:

```bash
docker compose up --build
```

The named `limina-data` volume preserves the SQLite database, Codex workspaces, and the generated
secret-encryption key across container replacement. No database container or migration command is
needed for this mode; the image applies schema migrations before starting the server.

The direct Python development path remains available:

```bash
uv sync --extra codex
export LIMINA_API_TOKEN=local-secret
uv run limina serve
```

For a PostgreSQL-backed deployment or future horizontal replicas:

```bash
export LIMINA_API_TOKEN=local-secret
export OPENAI_API_KEY=...
docker compose -f compose.cloud.yaml up --build
```

All following commands use `LIMINA_URL` (default `http://127.0.0.1:7433`) and
`LIMINA_API_TOKEN`.

## Create and resource a project

```bash
limina project create retrieval \
  --name "Retrieval quality" \
  --mission "Improve multilingual product retrieval" \
  --success "Increase held-out NDCG by 10% without a P95 latency regression" \
  --context "The current baseline is hybrid BM25 plus embeddings"

limina resource variable retrieval SOURCE_REPO_URL https://github.com/acme/search
limina resource variable retrieval EVAL_SET_URI s3://research/eval-v3.parquet

limina resource secret retrieval GITHUB_TOKEN --from-env GITHUB_TOKEN
limina resource secret retrieval AWS_SESSION_TOKEN --from-env AWS_SESSION_TOKEN

limina resource list retrieval
```

Variables are visible configuration and resource references. Secrets are write-only: omit
`--from-env` for a hidden confirmation prompt, or use `--from-stdin` in automation. Limina encrypts
them before database persistence, never returns their values, and injects both types only into the
managed runtime for that project. Use TLS whenever the API is reachable beyond localhost.

When upgrading the earlier prototype schema, existing resource URIs become uppercase-named
variables. Re-add any former `--credential-env` bindings once with `resource secret`; secret values
were never stored in the old schema and therefore cannot be migrated automatically.

## Start it and leave it running

```bash
limina start retrieval
limina status retrieval
limina watch retrieval
```

`watch` follows the durable activity stream. `Ctrl-C` stops watching; it does not stop the
project.

## Steer asynchronously

```bash
limina steer retrieval "The latency guardrail is more important than the 10% target."
limina steer retrieval "Approved to spend up to $100 on the larger evaluation." --kind APPROVAL
```

Limina commits guidance before delivery. If a turn is active, it also delivers the message inside
that turn. Otherwise it wakes the project and supplies the guidance to its next managed turn.

## Enter the live project

```bash
limina attach retrieval
```

The terminal first shows the current project state, replays subsequent durable activity, and then
accepts direct feedback:

```text
limina> Compare against the cross-encoder baseline before drawing a conclusion.
limina> /pause
limina> /resume
limina> /interrupt
limina> /detach
```

- plain text steers the active turn, or queues durably if the turn just ended;
- `/pause`, `/resume`, and `/stop` change project lifecycle;
- `/interrupt` interrupts the active turn and pauses the project;
- `/detach` only leaves the view; execution continues.

Several teammates may attach simultaneously. Each sees the same persisted event sequence, and
each message carries their `--actor`/`LIMINA_ACTOR` identity.

## Review knowledge

```bash
limina review retrieval
limina review retrieval --artifact F003
limina export retrieval ./retrieval-kb
```

The summary groups hypotheses, experiments, and findings. Opening an artifact shows its accepted
content and evidence. Export produces the validator-compatible Markdown KB for offline review,
Obsidian, archival, or a Git review branch.

## Manage projects

```bash
limina project list
limina project show retrieval
limina pause retrieval
limina resume retrieval
limina stop retrieval
limina project archive retrieval
```

Stopping and archiving never delete knowledge. Archive requires the project not to be actively
running.

## Machine-readable use

All non-interactive public commands support global `--json`:

```bash
limina --json status retrieval | jq '.project.status'
limina --json review retrieval | jq '.findings[] | {id, title}'
```

`attach` is intentionally interactive and rejects `--json`; use `watch --no-follow --json` for
event consumers.

## What users never operate

Limina contains a hidden project-scoped command protocol so its managed Codex runtime can commit
H → E → F artifacts safely. It is omitted from public help and OpenAPI, protected by a short-lived
capability, and not part of the user workflow. If a human finds themselves managing sessions,
threads, workers, subagents, leases, versions, or checkpoints, the abstraction has failed.
