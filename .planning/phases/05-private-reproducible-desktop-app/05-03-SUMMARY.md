---
phase: 05-private-reproducible-desktop-app
plan: 03
status: automatic-complete-host-pending
subsystem: final-offline-evidence-and-host-matrix
tags: [acceptance, regression, packaging, privacy, reproducibility, host-pending]
requires: [05-01, 05-02]
provides:
  - final offline/build/path regression record for the current worktree
  - redacted Phase 5 settings/privacy/packaging/GTK/host acceptance matrix
affects: [milestone-release]
automatic_tasks: 1/1
host_acceptance: pending
docker_verification: blocked-by-docker-socket-permission
requirements_validated: []
completed: 2026-10-19
---

# Phase 5 Plan 3: Automatic evidence and host-pending summary

The automatic and documentation portion requested for Plan 05-03 is complete
in the current worktree. The redacted user-run matrix is in
`05-HOST-ACCEPTANCE.md`. The existing dirty implementation and planning work
was preserved. The parent workflow later reconciled `STATE.md`, `ROADMAP.md`,
and `REQUIREMENTS.md` without changing source code or claiming host evidence.

This summary covers the automatic regression/evidence task only. The Plan 05-03
human checkpoint was not run. Shared status reconciliation was not performed
because the requested scope explicitly limited changes to the two Phase 5
artifacts named above.

## Automatic tasks complete

- Re-ran the final offline lock, test, lint, check, build, compile, whitespace,
  package-content, path, and secret checks after Plans 05-01 and 05-02.
- Added the Phase 5 host matrix with every live settings, privacy, packaging,
  GTK, Wayland, portal, audio, EIS, insertion, and recovery row explicitly
  marked `PENDING / NOT RUN`.
- Recorded the dependency on the still-pending Phase 02.1 and Phase 4 host
  artifacts. No fake-backed or offline result was promoted to host evidence.

## Final automatic verification

All commands below ran from the repository root on 2026-10-19. They were
headless and did not run live GNOME, GTK, portal, microphone, audio, EIS, or
focused-application checks.

| Command | Result |
|---|---|
| `uv lock --check --offline` | **PASS**, exit 0; resolved 40 packages in 1 ms. |
| `NETWORK_DISABLED=1 make test` | **PASS**, exit 0; 367 tests passed in 1.21 s. |
| `make lint` | **PASS**, exit 0; project compile check completed without output/errors. |
| `make check` | **PASS**, exit 0; lock resolved 40 packages in 0.81 ms; compile/lint, whitespace, metadata, and built-in path/secret checks completed. |
| `make build` | **PASS**, exit 0; created `dist/voxflow-0.1.0.tar.gz` and `dist/voxflow-0.1.0-py3-none-any.whl`. |
| `PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python python -m compileall -q src tests tools` | **PASS**, exit 0. |
| `git diff --check` | **PASS**, exit 0. |
| Wheel/sdist content, path, and secret audit | **PASS**; wheel has 49 members and sdist has 65 members; both contain the provider catalogue and UI settings module, with no environment/model/database files, current-machine absolute paths, or token-shaped secret values. The README/Makefile/Dockerfile/packaging surface also had no current-machine absolute paths or token-shaped secret values. |
| `desktop-file-validate packaging/dev.voxflow.VoxFlow.desktop` | **PASS**, exit 0. |
| `systemd-analyze verify packaging/voxflow.service` | **BLOCKED in this source checkout**; the documented user-local `voxflow` launcher is not installed, so systemd reported that `%h/.local/bin/voxflow` is not executable. This is not a live user-service acceptance result. |

The package audit checked both generated artifacts without extracting them into
the repository. It verified required package data and rejected `.venv`, model,
database, artifact, current-machine path, and token-shaped secret findings.

## Docker status

Docker was appropriate to attempt because Plan 05-02 provides a non-GUI
Dockerfile and the README documents the build/run path. The exact build command
was attempted:

```text
docker build --tag voxflow:phase5 .
```

It exited before image construction because this session could not access the
Docker daemon:

```text
ERROR: permission denied while trying to connect to the Docker API at unix:///var/run/docker.sock
```

`docker run --rm --network none voxflow:phase5` was not run because the image
was not built and daemon access was unavailable. Docker verification is
**BLOCKED**, not passed. A machine with Docker daemon access must run both the
build and network-disabled container commands.

## Host-pending status and dependencies

No live GTK rendering, GTK4/libadwaita availability, Wayland session check,
GlobalShortcuts hold/release behavior, microphone permission or recovery,
RemoteDesktop/Clipboard consent, EIS negotiation/keymap readiness, focused-app
insertion, terminal/XWayland behavior, restore-token reuse, recovery side
effects, or host audio-retention behavior was run or inferred here.

The following remain explicit blockers for release readiness:

1. `.planning/phases/02.1-walking-skeleton-on-gnome-50/02.1-HOST-ACCEPTANCE.md`
   is **PENDING / NOT RUN**. SKEL-01, SKEL-02, and SKEL-03 remain unvalidated.
2. `.planning/phases/04-insert-and-recover/04-HOST-ACCEPTANCE.md` is
   **PENDING / NOT RUN**. INSERT-01/02/03 and REC-01/02/03 remain
   unvalidated.
3. `05-HOST-ACCEPTANCE.md` is **PENDING / NOT RUN** for all live Phase 5
   settings/privacy, packaging, GTK, and host rows.
4. Docker build/run evidence is blocked by daemon socket permission.
5. Shared project status now records all automatic plans as complete while
   retaining the Phase 02.1, Phase 4, and Phase 5 host gates as pending. The
   requirement traceability remains explicit about implementation evidence
   versus live-host validation.

The automatic evidence demonstrates offline settings/privacy implementation,
redacted diagnostics, packaging metadata, buildability, and the 367-test
regression suite. It does not validate PRIV-01, PRIV-02, CONFIG-01, or BUILD-01
as fully user-visible release requirements until the applicable host and clean
installation evidence is reconciled by the parent workflow.
