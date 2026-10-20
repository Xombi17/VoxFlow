UV ?= uv
PROJECT_PYTHON ?= .venv/bin/python
PYTHONPATH := src
PROJECT_RUN = $(UV) run --offline --no-sync --python $(PROJECT_PYTHON)
PYTHON_VERSION := 3.12.14
DIST_DIR ?= dist
DOCKER_IMAGE ?= voxflow:local

.PHONY: check-env test lint build check docker-build docker-test

check-env:
	@set -eu; \
	command -v "$(UV)" >/dev/null 2>&1 || { \
	  echo "uv is required; run the setup commands in README.md." >&2; exit 1; \
	}; \
	test -x "$(PROJECT_PYTHON)" || { \
	  echo "$(PROJECT_PYTHON) is missing; run: uv venv --python $(PYTHON_VERSION) && uv sync --frozen --dev" >&2; exit 1; \
	}; \
	"$(PROJECT_PYTHON)" -c 'import sys; expected = (3, 12, 14); actual = sys.version_info[:3]; assert actual == expected, f"expected Python {expected}, got {actual}"'; \
	"$(PROJECT_PYTHON)" -c 'from pathlib import Path; assert Path(".python-version").read_text(encoding="utf-8").strip() == "$(PYTHON_VERSION)"'

test: check-env
	@NETWORK_DISABLED=1 PYTHONPATH="$(PYTHONPATH)" $(PROJECT_RUN) python -m pytest -q

lint: check-env
	@PYTHONPATH="$(PYTHONPATH)" $(PROJECT_RUN) python -m compileall -q src tests tools

build: check-env
	@$(UV) build --offline --out-dir "$(DIST_DIR)"

check: check-env
	@$(UV) lock --check --offline
	@$(MAKE) --no-print-directory lint
	@git diff --check
	@PYTHONPATH="$(PYTHONPATH)" $(PROJECT_RUN) python -c 'import json, pathlib, tomllib; root = pathlib.Path("."); project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8")); assert project["project"]["requires-python"] == "==$(PYTHON_VERSION)"; assert json.loads((root / "src/voxflow/providers/catalog.json").read_text(encoding="utf-8"))["version"] == 1; forbidden = (str(pathlib.Path.home()) + "/", "/" + "Users/", "ghp" + "_", "sk" + "-", "xoxb" + "-"); files = ("README.md", "Makefile", "Dockerfile", "packaging/dev.voxflow.VoxFlow.desktop", "packaging/voxflow.service"); assert not any(token in (root / name).read_text(encoding="utf-8") for name in files for token in forbidden)'

docker-build:
	@command -v docker >/dev/null 2>&1 || { echo "Docker is required; see README.md for the non-GUI verification command." >&2; exit 1; }
	@docker build --tag "$(DOCKER_IMAGE)" .

docker-test: docker-build
	@docker run --rm --network none "$(DOCKER_IMAGE)"
