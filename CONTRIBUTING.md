# Contributing

Thanks for improving Limina. The project is intentionally small: Markdown contracts, a persistent `kb/` research graph, and Python scripts that keep the graph honest.

## Local Setup

```bash
git clone https://github.com/theam/limina.git
cd limina
uv sync --locked --all-extras --dev
make test
make validate
```

To install the bundled skills locally:

```bash
make install-skills
```

## Development Flow

1. Keep changes focused and easy to review.
2. Update docs when behavior changes.
3. Add or update tests for scripts, validators, hooks, or telemetry changes.
4. Run `make test` and `make validate` before opening a PR.
5. If you change setup UX, verify that Claude Code remains straightforward and Codex still gets a usable `/goal`.

## Pull Request Checklist

- [ ] The user-facing workflow is documented.
- [ ] `make test` passes.
- [ ] `make validate` passes.
- [ ] No generated, private, or large local artifacts are committed.
- [ ] New dependencies are justified in `pyproject.toml` and `uv.lock` is refreshed.

## Style

- Prefer plain Markdown and small Python scripts.
- Keep command output and errors actionable.
- Preserve the `H -> E -> F` research graph unless the change explicitly updates the validator and docs together.
