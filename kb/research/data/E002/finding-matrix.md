# E002 finding disposition matrix

| Finding | Disposition | Direct evidence |
|---|---|---|
| H-1 fresh `CODEX_HOME` missing | Closed | Image and both Compose paths create private Codex state directories; fresh-volume live trial completed without intervention. |
| H-2 environment-only key does not authenticate Codex | Closed | Limina materialized the SDK credential store before the managed turn; live trial completed without manual `codex login`. |
| M-1 editor-controlled interpreter environment | Closed | Central write-time rejection and read-time legacy scrub cover interpreter, loader, VCS, proxy, provider, and control-plane names; regression tests exercise both boundaries. |
| M-2 missing Codex usage/cost | Closed with explicit provenance | Live provider usage was non-null and per-turn; provider or operator-rate cost provenance is stored separately, and cost remains honestly null when neither source exists. |
| M-3 CI/wheel dependency drift | Closed | CI uses Python 3.13, `uv sync --locked --all-extras`, Ruff, tests, and KB validation; the competing requirements file was removed. |
| M-4 liveness and container health | Closed | Unauthenticated `/livez` and `/readyz`, authenticated `/healthz`, image healthcheck, and orchestration health dependencies are tested. |
| L-1 one local token is omnipotent | Closed | Project and instance-administrator tokens are distinct, equal values fail startup, and runtime-auth routes require the administrator token. |
| L-2 no failed-auth throttling | Closed | Per-client REST throttling and a separately configurable higher transport-wide MCP/WebSocket ceiling are bounded and tested. |
| L-3 oversized modules | Closed for the release boundary | Runtime, service, collaboration, API, and CLI responsibilities were extracted into focused modules; every source module is below 1,000 lines. |
| L-4 two migration owners | Closed | Cloud Compose uses a one-shot migration service and overrides the runtime command to serve only. |
| L-5 live ticket in URL | Closed | Browser attach uses a one-time `limina.ticket.*` WebSocket subprotocol and the server echoes only the stable `limina.v1` protocol. |

## Links

- Parent experiment: [[E002]]
- Parent hypothesis: [[H002]]
- Prior finding: [[F001]]
