UV ?= uv
PROJECT_PYTHON ?= .venv/bin/python
PYTHONPATH := src
PROJECT_RUN = $(UV) run --offline --no-sync --python $(PROJECT_PYTHON)

.PHONY: test lint

test:
	@set -eu; \
	command -v "$(UV)" >/dev/null 2>&1 || { \
	  echo "uv is required; run the setup commands in README.md." >&2; exit 1; \
	}; \
	test -x "$(PROJECT_PYTHON)" || { \
	  echo "$(PROJECT_PYTHON) is missing; run: uv sync --dev" >&2; exit 1; \
	}; \
	$(PROJECT_RUN) python -c 'import sys; assert (3, 12) <= sys.version_info[:2] < (3, 13), sys.version'; \
	NETWORK_DISABLED=1 PYTHONPATH=$(PYTHONPATH) $(PROJECT_RUN) python -m pytest -q

lint:
	@set -eu; \
	command -v "$(UV)" >/dev/null 2>&1 || { \
	  echo "uv is required; run the setup commands in README.md." >&2; exit 1; \
	}; \
	test -x "$(PROJECT_PYTHON)" || { \
	  echo "$(PROJECT_PYTHON) is missing; run: uv sync --dev" >&2; exit 1; \
	}; \
	$(PROJECT_RUN) python -c 'import sys; assert (3, 12) <= sys.version_info[:2] < (3, 13), sys.version'; \
	PYTHONPATH=$(PYTHONPATH) $(PROJECT_RUN) python -m compileall -q src tests tools
