# UI-ready control-plane boundaries

A collaborative Limina UI should consume project concepts, not provider machinery. Keep identity,
RBAC, lifecycle, guidance, knowledge query, run observability, and analytics behind the shared
`ProjectOperations` boundary so REST, WebSocket, MCP, and CLI cannot disagree.

Use PostgreSQL full-text search and explicit relations as the first credible knowledge-query
baseline. They are deterministic, indexable, and explainable. Add semantic retrieval only after an
evaluation shows that it improves real review decisions enough to justify embedding lifecycle and
ranking complexity.

Browser WebSockets should use a short-lived, one-time, project-scoped ticket issued after normal
bearer authentication. Store only its hash and consume it transactionally. This preserves project
roles without exposing a long-lived bearer token in a URL.

Scope idempotency receipts to the authenticated subject, not a display name, and validate every
cached result against its project boundary before returning it. Apply the same public event
sanitizer to activity, live, review, and run-detail surfaces so adding observability cannot expose
the provider machinery the product contract intentionally owns.

Treat every managed provider turn as a durable product run. Correlate runtime events at creation,
record interruption and failure explicitly, and leave unavailable provider usage fields null rather
than estimating them.

## Links

- Active state: [[ACTIVE]]
- Architecture: [UI-ready backend](../../docs/ui-ready-backend.md)
- Verification: [Managed runtime evidence](../../docs/cloud-runtime-evidence.md)
