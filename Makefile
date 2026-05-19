PYTHON ?= python3

.PHONY: validate test generate-goal install-skills check

validate:
	LIMINA_TELEMETRY_INTERNAL=1 $(PYTHON) scripts/kb_validate.py

test:
	LIMINA_TELEMETRY_INTERNAL=1 $(PYTHON) -m unittest discover -s tests

generate-goal:
	$(PYTHON) scripts/generate_goal.py --write

install-skills:
	bash scripts/install_skills.sh

check: test validate
