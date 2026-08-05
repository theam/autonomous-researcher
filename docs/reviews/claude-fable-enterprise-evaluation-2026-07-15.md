# Limina — Enterprise Evaluation Report

- **Evaluator:** Senior AI engineer, enterprise platform team (actor: `claude-enterprise-evaluator`)
- **Method:** Autonomous Claude Code session; 29-minute key-bearing timebox; evidence-first (command output + `file:line`)
- **Repository revision:** `6a80aa67efd63bb435f83cc9db8ae57cb372c9f5` (working tree clean at start except untracked `EVALUATION_BRIEF.md`)
- **Tool versions:** Docker 28.0.1, Docker Compose v2.33.1-desktop.1 (uv/limina versions recorded below)
- **Session start (UTC):** 2026-07-15T10:38:29Z (epoch 1784111909)
- **Recommendation:** **CONDITIONAL GO** for an internal PoC (not production) — full loop works and produces durable evidence, but two release-blocking first-run Codex defects required manual intervention (both trivially fixable). See §12.
- **PoC status:** SUCCESS — real Limina-owned Codex run (`gpt-5.4`, 37 tool calls, ~98s) cloned the public repo and produced a complete H→E→F chain (H001 CONFIRMED → E001 COMPLETED → F001 PUBLISHED).

---

## 1. Locked first impression — README.md ONLY

> Locked at **2026-07-15T10:38:29Z**, before opening any other product file. Based solely on `README.md`.
> (Disclosure: session hooks auto-injected `kb/ACTIVE.md`/`kb/mission/CHALLENGE.md` excerpts and `AGENTS.md` was listed/read alongside the evaluation brief per repo `CLAUDE.md`; the impression below is deliberately grounded in README content only.)

**What it claims to be.** A collaborative *managed runtime* for long-running, evidence-driven agent projects. The pitch is an unusually crisp ownership boundary: teams operate **projects** (missions, resources, review, steering); Limina owns everything below — model sessions, turns, subagents, workspaces, retries, leases, checkpoints, restart recovery (README.md:16-22, 336-357). Engines are provider-selectable per project: **Codex** or **Claude Code** (README.md:153-176). Interfaces: CLI, REST (OpenAPI at `/openapi.json`), WebSocket, and a Streamable-HTTP MCP server, all claimed to hit one shared operation layer (README.md:64-118).

**Positive signals (as an enterprise adopter):**
- Security posture is discussed up-front and specifically: shared token explicitly labeled local-dev-only; OIDC/JWKS with issuer/audience/expiry validation and OWNER/EDITOR/VIEWER roles for teams; refuses non-local bind without auth configured (README.md:377-397). Write-only encrypted secrets, redaction from events, controlled turn-restart on rotation so revoked values don't linger (README.md:190-206). MCP deliberately refuses secret values in model-visible tool args (README.md:115-118). One-time tickets so browser WebSockets don't put bearer tokens in URLs (README.md:145).
- Operational story is one command (`docker compose up --build`), one volume, migrations applied on start; SQLite default with a documented PostgreSQL path for HA/replicas (README.md:40-50, 359-375).
- Honest scoping: semantic/vector search deliberately deferred with a stated rationale (README.md:147-149); "database is canonical, Markdown/Git are projections" (README.md:293-296). This reads like engineering judgment, not marketing.
- Apache-2.0, a real company behind it (README.md:446-448).

**Concerns/questions to verify before trusting it:**
1. Claim-density is very high (idempotency keys, CAS decisions, crash recovery, redaction, atomic ID allocation). README cites its own docs as evidence; none of it is independently verified yet — this evaluation must test the happy path for real.
2. No version/maturity signal in the README (no changelog/release badge; GitHub stars badge only). Enterprise adopters can't tell if this is 0.x churn or stable.
3. Single container runs migrations + API + supervisor (README.md:48); blast-radius and upgrade story for that coupling needs checking.
4. The security section itself says untrusted multi-tenant use needs workspace isolation, external KMS, quotas, audit export — i.e., **not** production-multi-tenant-ready out of the box (README.md:399-403). Fine for an internal PoC; must be stated plainly.
5. Live provider execution is the crux — a managed Codex run with real credentials is the make-or-break test.

**Verdict at this stage (README only):** promising, unusually well-articulated boundary and security story; proceed to hands-on verification with skepticism proportional to the claim density.

---

## 2. Scorecard (7 milestones)

| # | Milestone | Critical | Result | Proof |
|---|-----------|----------|--------|-------|
| 1 | README boundary (project-level ops only; no provider-session mgmt) | — | **PASS** | README frames only project ops (README.md:16-22, 336-357); code confirms one shared `ProjectOperations` choke point and strips continuity fields (`worker_id/thread_id/continuation_id/turn_id`) from public event payloads (`operations.py:96-109`). CLI exposes no session/thread/lease verbs (`limina --help`). |
| 2 | One-command server start (Docker Compose) | ✅ | **PASS** | `docker compose up --build` → `revision: head` migrations applied, `Uvicorn running on http://0.0.0.0:7433`, container `Started`. |
| 3 | Doctor/preflight | — | **PASS** | `limina doctor` → `ok http://127.0.0.1:7433 · runtime owned by limina · engines Codex, Claude Code` (exit 0). |
| 4 | Kickoff + resource setup | ✅ | **PASS** | `project create ... --runtime codex` → `Status CREATED`; `resource variable ... SOURCE_REPO_URL` set and listed as `VARIABLE`. |
| 5 | Limina-owned Codex execution | ✅ | **PASS (with HIGH first-run defects)** | Run record: `runtime: codex`, `model: gpt-5.4`, `status: COMPLETED`, `tool_calls: 37`, `duration_ms: 97810`; summary describes a real read-only clone. Two prior runs FAILED on first-run env defects (§H-1, §H-2) requiring manual intervention before the run succeeded. |
| 6 | Durable reviewable PoC result (H→E→F) | ✅ | **PASS** | `limina review` shows H001 CONFIRMED → E001 COMPLETED → F001 PUBLISHED; F001 Evidence quotes `sed -n '1,3p' LICENSE` → `Apache License / Version 2.0, January 2004`. Reviewable per-artifact via `--artifact`. |
| 7 | Clean project/server stop | ✅ | **PASS** | Project reached terminal `COMPLETE` (bounded mission satisfied), no active runtime loop; `stop` issued; `project list` → `COMPLETE`. Full teardown + `git status` in §8. |

**Scorecard summary: 7/7 PASS.** All five critical milestones (start, kickoff, execution, result, stop) pass. Milestone 5 passes only after two manual first-run fixes — logged as HIGH findings; they gate the *unattended* default path, not the capability itself.

---

## 3. Method & environment

- Inherited env (values never printed): `OPENAI_API_KEY`, `LIMINA_API_TOKEN`, `LIMINA_ACTOR=claude-enterprise-evaluator`, `LIMINA_URL=http://127.0.0.1:7433`, `COMPOSE_PROJECT_NAME=limina-enterprise-e001`. Compose inherits credentials from process environment; no `.env` file was written.
- All outputs below are sanitized; secrets never placed in command arguments.

## 4. Setup & CLI path (sanitized transcript)

All commands run from the repo root; credentials only ever passed by environment inheritance.

1. **Server start (one command, adapted `-d` for non-interactive session):** `docker compose up --build -d` → image built (`pip install` of `limina_cloud_runtime-0.1.0` wheel + `openai-codex-0.1.0b3`, `openai-codex-cli-bin-0.137.0a4`, `claude-agent-sdk-0.2.119`), network/volume created, `Container limina-enterprise-e001-limina-1 Started`. Server logs: `{'database': 'sqlite:////var/lib/limina/runtime.db', 'revision': 'head'}` (migrations applied) then `Uvicorn running on http://0.0.0.0:7433`. ~10:40Z, ≈2.5 min including build.
2. **Host CLI:** `uv tool install .` → `Installed 1 executable: limina`. (DX gap: `limina --version` is not a supported option.)
3. **Doctor:** `limina doctor` → `ok http://127.0.0.1:7433 · runtime owned by limina · engines Codex, Claude Code` (exit 0).
4. **Kickoff:** `limina project create limina-readiness-poc --runtime codex --name ... --mission "Inspect the public Limina repository ... one small compatibility/readiness claim ... H -> E -> F" --success "One hypothesis, one experiment ... stop after the first finding" --context "Bounded ... 10-minute budget ... read-only"` → panel shows `Engine Codex`, `Status CREATED`, `Next: Frame the first falsifiable hypothesis`.
5. **Resource:** `limina resource variable limina-readiness-poc SOURCE_REPO_URL https://github.com/theam/limina` → listed as `VARIABLE` by `limina resource list`.
6. **Start:** `limina start limina-readiness-poc` → `Status RUNNING`.
7. **First-run product defect (HIGH, reproducible):** seconds later `limina status` → `Status FAILED`, blocker: `Codex process closed stdout. stderr_tail=... CODEX_HOME points to "/var/lib/limina/codex", but that path does not exist`. Root cause: `Dockerfile.cloud:26` sets `CODEX_HOME=/var/lib/limina/codex` but only `/var/lib/limina/workspaces` is ever created (Dockerfile step `mkdir -p /var/lib/limina/workspaces`); on a fresh named volume the Codex CLI aborts. Positive: the failure surfaced as a structured project blocker with stderr tail — no log spelunking needed.
8. **Recovery via documented path:** environment-level workaround (no product edit): `docker exec -u limina limina-enterprise-e001-limina-1 mkdir -p /var/lib/limina/codex`, then `limina resume limina-readiness-poc` → `Status RUNNING`. Volume state observed: `runtime.db`, `secret.key` (mode `-rw-------`, owner `limina`), `workspaces/`.

## 5. PoC narrative (real Codex run through Limina)

**Mission (bounded):** "Inspect the public Limina repository at `SOURCE_REPO_URL` and establish one small compatibility/readiness claim, via H → E → F; stop after the first finding." Resource: `SOURCE_REPO_URL=https://github.com/theam/limina`.

**Timeline (all through Limina project surfaces only — never Codex directly):**
- `10:41:34` first `start` → `runtime.turn_failed` in <1s. Blocker (structured): `CODEX_HOME points to "/var/lib/limina/codex", but that path does not exist`. → **Finding H-1.**
- `10:42:34` after creating the missing dir at the environment level, `resume` → Codex started but emitted 10 `runtime.codex … error` events then `turn_failed`. Blocker: `401 Unauthorized: Missing bearer … url: https://api.openai.com/v1/responses`. `OPENAI_API_KEY` was confirmed present in the container env (presence-only check, value never printed), so env-only auth was insufficient. → **Finding H-2.**
- `10:46:24` after establishing Codex `auth.json` at the environment level (key fed via **stdin**, never argv, never printed), `resume` → `RUNNING`.
- `10:48:02` `runtime.turn_completed`: *"cloned the public repository read-only, recorded hypothesis H001, ran experiment E001 against the cloned repo, observed LICENSE output showing Apache License and Version 2.0…, confirmed the hypothesis, and published finding F001."* Managed workspace: `/tmp/limina-src.hBgUC0/repo` (Limina-owned, inside the container).

**Artifacts produced (durable, reviewable via `limina review`):**
- **H001** (CONFIRMED) "Apache-2.0 license readiness" — falsifiable statement + mechanism + test plan + conclusion.
- **E001** (COMPLETED) "Inspect LICENSE header in cloned repo" — objective/procedure/success-criteria/guardrails/results/analysis, Decision `SUPPORTED`.
- **F001** (PUBLISHED) "Repository license is Apache 2.0" — Evidence: ``sed -n '1,3p' LICENSE`` → `Apache License / Version 2.0, January 2004 / http://www.apache.org/licenses/`; Impact MEDIUM.

**Run record (REST `/v1/projects/…/runs`, proof of managed execution):** `id 3f62de0a…`, `runtime codex`, `model gpt-5.4`, `status COMPLETED`, `tool_calls 37`, `duration_ms 97810`, `retry_count 0`. `usage.{input_tokens,output_tokens,cost_microusd}: null` (Codex SDK supplied no usage → **Finding M-2**). Two prior FAILED runs recorded honestly. **Analytics:** `runs.total 3`, `success_rate 0.3333`, `knowledge.by_kind {H:1,E:1,F:1}`, `guidance.average_acknowledgement_seconds 388`, daily timeseries present.

**Interpretation:** the *capability* — Limina owning a Codex session, injecting a project resource, cloning read-only into a managed workspace, enforcing H→E→F, and exposing durable/reviewable/observable results — is **real and verified**. The two failures were first-run environment-wiring defects in the packaged image, not model or protocol failures; classified as **product failures** (§7), each with a one-line fix.

## 6. Architecture & code inspection findings (verified good — with `file:line`)

Scale: 18 modules, ~9,925 LOC, flat `src/limina_cloud/` package; clean unidirectional layering `models → database → service/collaboration → operations → transports`, with `runtime/engines` owning execution.

- **One operations layer for all interfaces (confirmed):** `ProjectOperations` (`operations.py:129`) is the shared, authz-enforcing choke point; the 46 public `/v1` routes, the `/live` WebSocket, and every MCP tool delegate to it (`api.py:291,386,863,870`; `mcp.py:135`). *Caveat:* the hidden agent H/E/F write path uses a second internal surface `/internal/v1/*` → `ChallengeService` under capability-token auth, bypassing `operations` by design (`api.py:959-1096`, `cli.py:82-94`).
- **Runtime ownership & restart recovery (confirmed):** `ProjectSupervisor.recover()` re-spawns RUNNING/WAITING projects (`runtime.py:764-767`) from the FastAPI lifespan (`api.py:174`); Codex `thread_resume` vs `thread_start` (`runtime.py:337-349`), Claude `resume=continuation_id` (`runtime.py:516`); continuation persisted before tools run (`runtime.py:1165-1182`).
- **Durability/concurrency (confirmed):** atomic artifact IDs via `INSERT … ON CONFLICT … RETURNING` (`service.py:1403-1417`); CAS on decisions guarded by `version` → `ConflictError` (`service.py:1460-1495`); idempotency receipts replay/reject by key (`service.py:1283-1334`); append-only `Event` with autoincrement `sequence` (`models.py:402-419`); `WorkLease` with atomic acquire + expiry + heartbeat (`service.py:1526-1577`, `runtime.py:1119-1143`).
- **H→E→F invariants (confirmed):** experiment forces parent H into `TESTING` (`service.py:617-650`); finding requires `experiment.status == COMPLETED` (`service.py:884-889`).
- **Trust boundary (confirmed TRUE, matches README.md:409-410):** the managed child never receives DB URL or admin token — `_isolated_environment` blanks every non-safe parent var to `""` and re-adds only an allowlist; only a per-project `secrets.token_urlsafe(32)` capability is passed and popped at run end (`runtime.py:75-95,1184-1201,1107`).
- **Secrets (confirmed):** Fernet (AES-128-CBC+HMAC) encryption (`vault.py:11-27`); key file created `O_EXCL,0o600` with perm-rejection of group/other-readable keys (`vault.py:75-83`); ciphertext binds `{project,name}` (`vault.py:41-64`); API returns `value:None`, only `configured:bool` (`service.py:1672-1675`); redaction from events/decisions/errors (`runtime.py:161-199`). Provider/loader var **shadowing refused at write time** via reserved-name + prefix denylist (`service.py:44-71,1341-1363`).
- **AuthN/Z (confirmed):** constant-time shared-token compare (`auth.py:57`); OIDC requires `exp/iat/iss/sub/aud`, HTTPS issuer, blocks `none` alg, bounded leeway (`auth.py:79-132`); RBAC VIEWER/EDITOR/OWNER enforced per route (`operations.py`, `collaboration.py:108-117`); non-local bind refused without auth (`cli.py:732-738`, `auth.py:173-181`). One-time WS tickets hashed-at-rest, single-use, ≤120s TTL (`collaboration.py:301-346`).
- **Packaging/ops (confirmed):** non-root container uid 10001 (`Dockerfile.cloud:19-22`); `uv.lock` present; 4 linear Alembic migrations; Postgres path with `pg_isready` gate + one-shot migrate service (`compose.cloud.yaml`). 64 test functions across 11 files (all provider SDKs faked; no live-paid path).

## 7. Risks & findings (severity-ranked, with `file:line`)

**HIGH — H-1 · Default Codex path is broken on a fresh volume (product failure).** `Dockerfile.cloud:26` sets `CODEX_HOME=/var/lib/limina/codex`, but the image only creates `/var/lib/limina/workspaces` (`Dockerfile.cloud` `mkdir -p …/workspaces`). First `limina start` on a new `limina-data` volume → project `FAILED`, blocker `CODEX_HOME … does not exist`. Reproduced live. *Fix:* add `…/codex` to the image `mkdir`. Enterprise impact: the advertised one-command Codex quick-start fails out of the box for every new deployment.

**HIGH — H-2 · Env-only Codex auth does not authenticate (product/integration failure).** With `OPENAI_API_KEY` present in the container env, the bundled `codex_cli_bin` still returned `401 … Missing bearer` against `api.openai.com`; the run only succeeded after an `auth.json` was established under `CODEX_HOME`. The adapter passes `OPENAI_API_KEY` into the child env (`runtime.py:56-64,323`) but never runs the `codex login` / `auth.json` step the bundled CLI requires. *Fix:* materialize `auth.json` from the injected key in the Codex adapter (or document a login step). Impact: "add `OPENAI_API_KEY`, `docker compose up`" does not yield a working Codex run unattended. (Claude Code path not exercised — no credential; may or may not share this gap.)

**MEDIUM — M-1 · EDITOR-role env-var injection into the runtime process (security).** Reserved-name checking is a denylist (`service.py:1341-1363`) that blocks provider/loader vars but **not** interpreter hijack vars (`NODE_OPTIONS`, `BASH_ENV`, `GIT_SSH_COMMAND`, `PROMPT_COMMAND`, `PERL5LIB`). Project variables are overlaid onto the model-CLI process env (`runtime.py:1216`) — the same process that holds the provider API key and capability token — and `set_variable` needs only EDITOR (`operations.py:351`) and triggers a turn restart. An EDITOR could set `NODE_OPTIONS=--require …` (Claude runtime is Node) to run code in the runtime-process context, outside the inner bash sandbox. *Fix:* allowlist variable names or scrub known hijack vars.

**MEDIUM — M-2 · No token/cost telemetry for Codex (observability/FinOps).** Run + analytics `input_tokens/output_tokens/cost_microusd` are all `null`; the SDK supplied no usage (README.md:143-144 hedges "when the SDK supplies it", so honest, but) cost showback/quotas are unavailable for Codex in practice. `tool_calls` (37) and `duration_ms` are captured. Also `RuntimeRun.retry_count` is persisted but never incremented and `CoordinatorState.wake_at` is written nowhere (`models.py:441,166`) — aspirational columns.

**MEDIUM — M-3 · CI/wheel dependency drift (supply chain).** `requirements.txt` (used by CI) omits `pyjwt[crypto]` and `python-multipart` (both in `pyproject.toml:19-20`) and adds `python-frontmatter`; CI installs via `pip -r requirements.txt`, not `uv.lock`, so it tests a different dependency set than the shipped wheel. CI also runs Python 3.12 while the image ships 3.13 and does not run `ruff`.

**MEDIUM — M-4 · No unauthenticated liveness probe / no container HEALTHCHECK (operations).** `GET /healthz` requires auth (`api.py:270`) and there is no `HEALTHCHECK` in `Dockerfile.cloud`; k8s/ECS liveness probes need credentials or custom wiring.

**LOW.** L-1 local shared token = `instance_admin` OWNER on all projects (`auth.py:33`) — by-design dev mode, but any token holder is full admin. L-2 no rate-limiting/lockout on token or ticket brute force (not found). L-3 god modules (`service.py` 1693 LOC, `collaboration.py` 1415, `api.create_app` ~975-line function) — maintainability. L-4 migrations run twice under `compose.cloud` (entrypoint + migrate service). L-5 live-ticket passed as URL query param (`api.py:868`) — mitigated by hash-at-rest + single-use + ≤120s TTL.

## 8. Guardrail evidence

- **Under-29-min key-bearing execution:** session start `10:38:29Z`; Codex key-bearing run `10:46:24 → 10:48:02Z`; report/stop/cleanup completed well within the box (see final response for elapsed).
- **Zero credential disclosure:** `OPENAI_API_KEY` never printed, quoted, persisted to the repo, or placed in a command argument. Presence checks were boolean-only (`[ -n "$VAR ] && echo present`); Compose inherited the key from the environment; the `codex login` step read the key from **stdin**. Command outputs were filtered for `sk-`/`Bearer` patterns.
- **Zero tracked product edits:** only two untracked files added at repo root (`ENTERPRISE_EVALUATION_REPORT.md`, `EVALUATION_BRIEF.md`); no tracked file modified. Confirmed by `git status` (§ final response). Environment-level fixes (dir create, `codex login`) were applied **inside the container volume**, never to repository files.
- **Zero direct provider-session management:** every action used a `limina` project surface (CLI/REST). Codex/Claude were never invoked directly to do research; the one `docker exec … codex login` was an *environment credential setup* to unblock Limina's own managed run, not research steering or session management.

## 9. Evidence classification

- **Confirmed (first-hand command output / `file:line`):** all 7 milestones; the H→E→F chain and its LICENSE evidence; the Codex run record (`gpt-5.4`, 37 tool calls, 98s); analytics counts; H-1 and H-2 (reproduced live); the §6 architecture/security properties (read in source); M-2/M-3/M-4 (observed output + files).
- **Proxy evidence (code-read, not runtime-exercised):** OIDC/JWKS validation, RBAC role enforcement per route, restart-recovery, lease heartbeat, CAS/idempotency, secret encryption/redaction, WS one-time tickets, M-1 env-injection vector — all read in source but not dynamically triggered in this run.
- **Blocked claims (could not verify):** Claude Code live execution (no `ANTHROPIC_API_KEY`; not attempted); Codex token/cost telemetry (SDK returned null); multi-replica Postgres coordination; OIDC end-to-end (no IdP); live steering/interrupt mid-turn (mission completed in one turn).
- **Uncertainty:** whether H-2 affects the Claude path identically; whether a newer `codex_cli_bin` would honor env-only auth; long-run recovery under real process kills.

## 10. Limitations

Single ~13-minute hands-on run, SQLite single-container topology only, one bounded Codex mission, one evaluator. No load/soak, no chaos/restart test, no OIDC IdP, no Postgres/HA, no Claude Code run, no dependency CVE scan. Findings are not a security audit; M-1 is a code-substantiated vector, not an exploited one. Do not extrapolate production readiness from this PoC.

## 11. Prioritized next steps

1. **Fix H-1** (`mkdir …/codex` in `Dockerfile.cloud`) and **H-2** (materialize Codex `auth.json` from `OPENAI_API_KEY` in the adapter) — these gate any unattended PoC. Add a regression test that a fresh volume completes one Codex turn.
2. **Close M-1**: allowlist project-variable names / scrub `NODE_OPTIONS`,`BASH_ENV`,`GIT_SSH_COMMAND`,… before overlay.
3. **Reconcile M-3**: generate `requirements.txt` from `pyproject`/`uv.lock`; run CI from the lock; add `ruff` to CI; align Python versions.
4. **Ops M-4**: add an unauthenticated `/livez` and a container `HEALTHCHECK`.
5. Exercise the **Claude Code** path and **OIDC**; validate Codex **cost telemetry** or document its absence for FinOps.
6. Then a bounded internal PoC with 2–3 real projects on trusted operators before any wider rollout.

## 12. Final recommendation

**CONDITIONAL GO — internal PoC only (explicitly NOT production).**

The engineering substance is strong and largely verified in source: a genuinely clean project/provider-session ownership boundary, one shared authorization+operations layer across CLI/REST/WS/MCP, real durability primitives (atomic IDs, CAS, idempotency, append-only ordered events, leases), a verified credential-isolation boundary for the managed child, encrypted write-only secrets with redaction, and OIDC/RBAC for teams. The end-to-end loop — start → doctor → kickoff → resource → Limina-owned Codex execution → durable reviewable H→E→F → observability → stop — **works and produced real, cited evidence**.

**Conditions to clear before handing to PoC users:** (1) fix H-1 and H-2 so the documented one-command Codex path works unattended; (2) restrict membership to trusted operators until M-1 (EDITOR env-injection) is closed; (3) don't depend on Codex cost analytics (M-2). With those, this is a compelling internal-PoC platform. It is **NOT** production-multi-tenant-ready out of the box — the project's own security section concurs (workspace isolation, external KMS, quotas, audit export all remain deployment work; README.md:399-403).
