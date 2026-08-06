PYTHON ?= python3
UV ?= uv

.PHONY: validate test generate-goal install-skills check runtime-sync runtime-test runtime-lint runtime-check runtime-schema-sql runtime-compose

validate:
	LIMINA_TELEMETRY_INTERNAL=1 $(PYTHON) scripts/kb_validate.py

test:
	LIMINA_TELEMETRY_INTERNAL=1 $(PYTHON) -m unittest discover -s tests

generate-goal:
	$(PYTHON) scripts/generate_goal.py --write

install-skills:
	bash scripts/install_skills.sh

check: test validate

runtime-sync:
	$(UV) sync --extra runtimes

runtime-test:
	$(UV) run python -m unittest discover -s tests

runtime-lint:
	$(UV) run ruff format --check src migrations tests/test_cloud_*.py tests/test_console_*.py
	$(UV) run ruff check src migrations tests/test_cloud_*.py tests/test_console_*.py

runtime-schema-sql:
	LIMINA_DATABASE_URL=postgresql+psycopg://limina:limina@localhost/limina $(UV) run alembic upgrade head --sql >/dev/null

runtime-compose:
	OPENAI_API_KEY=test ANTHROPIC_API_KEY=test LIMINA_API_TOKEN=test docker compose config >/dev/null
	OPENAI_API_KEY=test ANTHROPIC_API_KEY=test LIMINA_API_TOKEN=test LIMINA_UI_AUTH_MODE=local LIMINA_ALLOW_LOCAL_AUTH=1 LIMINA_CONSOLE_DEV_AUTH=1 LIMINA_DEV_JWT_SECRET=test-only-secret-000000000000000000000000 docker compose -f compose.cloud.yaml config >/dev/null

runtime-check: runtime-lint runtime-test runtime-schema-sql runtime-compose validate
