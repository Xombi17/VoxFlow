PYTHON ?= python3
UV ?= uv
PROJECT_PYTHON ?= .venv/bin/python
PYTHONPATH := src

.PHONY: test lint

test:
	@set -eu; \
	if command -v $(UV) >/dev/null 2>&1 && \
	   $(UV) run --offline --no-sync --python $(PROJECT_PYTHON) \
	   -c 'import pytest' >/dev/null 2>&1; then \
	  NETWORK_DISABLED=1 PYTHONPATH=$(PYTHONPATH) \
	    $(UV) run --offline --no-sync --python $(PROJECT_PYTHON) -m pytest -q; \
	elif $(PYTHON) -c 'import pytest' >/dev/null 2>&1; then \
	  echo "Using $(PYTHON) pytest fallback; no project-local pytest is cached."; \
	  NETWORK_DISABLED=1 PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m pytest -q; \
	else \
	  echo "pytest is unavailable in the cached project or fallback Python." >&2; \
	  echo "Install/cache dev tooling, then rerun make test." >&2; \
	  exit 1; \
	fi

lint:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m compileall -q src tests tools
