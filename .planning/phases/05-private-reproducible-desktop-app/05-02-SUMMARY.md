---
phase: 05-private-reproducible-desktop-app
plan: 02
status: automatic-complete-docker-blocked
subsystem: reproducible-build-packaging
tags: [python, uv, lockfile, make, docker, desktop-entry, systemd, documentation]
requires: [05-01]
provides:
  - exact Python 3.12.14 runtime and matching project/lock metadata
  - offline project-local test, check, lint, and build targets
  - pinned non-GUI Docker build/test definition and build context exclusions
  - settings desktop entry and user-local daemon service packaging
  - clean-checkout, privacy, deployment, and host-acceptance documentation
affects: [05-03]
automatic_tasks: 3/3
host_acceptance: pending
docker_verification: blocked-by-docker-socket-permission
requirements_validated: []
completed: 2026-10-19
---

# Phase 5 Plan 2: Reproducible build and desktop packaging summary

Plan 05-02 is implemented in the current worktree after Plan 05-01. Existing
Phase 3/4 and Plan 05-01 dirty changes were preserved. No commit, staging,
stash, reset, or dependency installation was performed.

## Changed files

- `.python-version` — pins Python `3.12.14`.
- `pyproject.toml` — requires exactly Python `3.12.14`; keeps runtime
  dependencies exact-pinned, including the existing `av==18.1.0` alignment.
- `uv.lock` — regenerated offline with matching `requires-python` and locked
  dependency metadata.
- `Makefile` — adds project-local `check-env`, `build`, `check`,
  `docker-build`, and `docker-test` targets while keeping `test` offline and
  free of implicit sync.
- `Dockerfile` — adds a pinned Python 3.12.14, pinned uv, non-GUI multi-stage
  build/test image with only core host libraries.
- `.dockerignore` — excludes git/planning state, environments, build output,
  models, runtime data, databases, logs, and secrets from the Docker context.
- `packaging/dev.voxflow.VoxFlow.desktop` — launches `voxflow settings` as a
  visible settings application instead of starting a second daemon.
- `packaging/voxflow.service` — documents the user-local `voxflow daemon`
  service with restrictive systemd options and no checkout path.
- `README.md` — documents pinned setup, offline checks, package build, model
  selection, settings/privacy, recovery, user-local deployment, service
  lifecycle, Docker, and the unclaimed host-only acceptance boundary.
- `.planning/phases/05-private-reproducible-desktop-app/05-02-SUMMARY.md` —
  records this implementation and the actual verification results.

No GTK Python dependency, provider network behavior, model auto-download, or
source settings/UI behavior was added or changed by this plan.

## Verification results

All commands below were run from the repository root after the final code and
packaging mutations unless noted otherwise:

- `uv lock --check --offline` — **PASS**, resolved 40 packages.
- `NETWORK_DISABLED=1 make test` — **PASS**, 367 tests passed in 2.82s.
- `make lint` — **PASS**, compile check completed without output/errors.
- `make check` — **PASS**, lock, metadata, whitespace, and path/secret checks
  completed without output/errors.
- `make build` — **PASS**, created `dist/voxflow-0.1.0.tar.gz` and
  `dist/voxflow-0.1.0-py3-none-any.whl`.
- Wheel/sdist inspection — **PASS**; both artifacts contain the full
  `voxflow` package and `voxflow/providers/catalog.json`, and contain no
  `.venv`, model, database, or home-directory paths.
- `git diff --check` — **PASS**.
- `desktop-file-validate packaging/dev.voxflow.VoxFlow.desktop` — **PASS**.
- Missing-environment guard: `make test PROJECT_PYTHON=.missing-python` —
  **PASS as a negative check**; failed immediately with the actionable
  `uv venv --python 3.12.14 && uv sync --frozen --dev` setup message and did
  not sync or run tests.

## Docker status

Docker was available as a client (`Docker version 29.9.1`), but this session
could not access its daemon. The exact build command was attempted:

```text
docker build --tag voxflow:phase5 .
```

It failed before reading/building the image with:

```text
ERROR: permission denied while trying to connect to the Docker API at unix:///var/run/docker.sock
```

Therefore `docker run --rm --network none voxflow:phase5` was not claimed or
run. The Dockerfile and `.dockerignore` are present for a machine with Docker
daemon access; the container build/run evidence remains **blocked**, not
passed.

The available systemd check also reported the expected clean-machine install
gap: `systemd-analyze verify packaging/voxflow.service` exited 1 because
`%h/.local/bin/voxflow` is not installed in this checkout. The desktop entry
syntax check passed. No live GTK, GNOME Wayland, portal, microphone, EIS, or
focused-application behavior is claimed here.
