---
phase: 01-wayland-foundation
plan: 01
subsystem: core
tags: [python, pytest, uv, state-machine, capabilities, wayland]

# Dependency graph
requires: []
provides:
  - Pinned Python 3.12 package metadata, src-layout imports, and an offline test entry point.
  - Pure capability and dictation-session contracts for later Wayland and audio adapters.
  - JSON diagnostic output that exposes stable capability and session-state fields.
affects: [01-02, 01-03, platform-adapters, audio-adapters]

# Tech tracking
tech-stack:
  added: [Python 3.12, uv lockfile, pytest configuration, Ruff configuration]
  patterns: [stdlib-only core contracts, immutable snapshots with validated transitions, capability records with actionable statuses]

key-files:
  created:
    - pyproject.toml
    - uv.lock
    - .python-version
    - Makefile
    - src/voxflow/__init__.py
    - src/voxflow/__main__.py
    - src/voxflow/core/state.py
    - src/voxflow/core/capabilities.py
    - tests/unit/test_state.py
    - tests/unit/test_capabilities.py
  modified: []

key-decisions:
  - "Keep the Phase 1 runtime dependency set empty: the core contracts use Python's standard library so desktop providers remain replaceable and offline tests need no model or network access."
  - "Expose available, needs_user_action, and unsupported as explicit capability statuses with stable IDs and actionable reasons."
  - "Keep the CLI diagnostic provider-free; it consumes core contracts but never imports GTK, D-Bus, PipeWire, microphone, model, or network code."

patterns-established:
  - "State transitions are validated before mutation and invalid edges raise InvalidStateTransitionError with both state names."
  - "Diagnostic serialization uses stable state, failure_reason, id, status, and reason field names."

requirements-completed: [PLAT-01, PLAT-03]

# Metrics
duration: 12 min
completed: 2026-10-16
---

# Phase 1 Plan 1: Wayland Foundation Bootstrap Summary

**Pinned Python 3.12 VoxFlow skeleton with offline JSON diagnostics, immutable dictation state transitions, and capability-aware platform contracts**

## Performance

- **Duration:** 12 min
- **Started:** 2026-10-16T17:04:01Z
- **Completed:** 2026-10-16T17:10:56Z
- **Tasks:** 3 completed
- **Files modified:** 10 planned implementation/test files

## Plan Requirements

Copied from the plan frontmatter:

- `requirements: [PLAT-01, PLAT-03]`
- **PLAT-01:** The application reports whether it is running on Wayland, X11, or an unsupported session and lists the available shortcut, clipboard, paste, and audio capabilities.
- **PLAT-03:** The user sees a clear idle, listening, processing, success, cancelled, or failed status while a dictation job is active.

## Accomplishments

- Added a Python 3.12 `src/` package with project metadata, `.python-version`, an offline `make test` target, and a uv lockfile that resolves the dependency-free core.
- Added `SessionState`, immutable `SessionSnapshot`, and `SessionStateMachine` contracts covering idle, listening, processing, success, cancelled, and failed states with validated transition edges and failure context.
- Added capability records with explicit available, needs-user-action, and unsupported statuses, stable ordering, machine-readable IDs, and actionable reasons.
- Wired `python -m voxflow --json` to serialize the core diagnostic without importing a concrete desktop provider, and covered the same contracts with deterministic tests.

## Task Commits

Each task was committed atomically:

1. **Task 1: Create the pinned Python package and offline test command** - `e771a58` (`feat`)
2. **Task 2: Implement typed state and capability contracts** - `f98ad8b` (`feat`)
3. **Task 3: Add deterministic core tests and diagnostic output** - `834c2e5` (`test`)

**Plan metadata:** pending summary metadata commit.

## Files Created/Modified

- `pyproject.toml` - Python 3.12 project metadata, package discovery, pytest settings, and Ruff settings.
- `uv.lock` - Offline-resolved lockfile for the dependency-free `voxflow` package.
- `.python-version` - Pins the project runtime to Python 3.12.
- `Makefile` - Provides the offline `test` target and a dependency-free syntax/lint check.
- `src/voxflow/__init__.py` - Defines the application name and version.
- `src/voxflow/__main__.py` - Emits the provider-free JSON diagnostic.
- `src/voxflow/core/state.py` - Defines the typed session states, transition graph, snapshots, and domain errors.
- `src/voxflow/core/capabilities.py` - Defines capability statuses, ordering, records, and serialization.
- `tests/unit/test_state.py` - Covers all six states, success/cancel/failure paths, and invalid transition immutability.
- `tests/unit/test_capabilities.py` - Covers capability serialization, status ordering, and JSON diagnostic output.

## Verification Evidence

- `PATH="/home/varad/.local/share/uv/python/cpython-3.12-linux-x86_64-gnu/bin:$PATH" PYTHONPATH=src:/usr/lib/python3/dist-packages NETWORK_DISABLED=1 make test`
  - `11 passed in 0.01s`
- `PATH="/home/varad/.local/share/uv/python/cpython-3.12-linux-x86_64-gnu/bin:$PATH" PYTHONPATH=src python3.12 -m voxflow --json`
  - `{"app": "voxflow", "capabilities": [], "state": {"failure_reason": null, "state": "idle"}, "version": "0.1.0"}`
- `git diff --check`
  - Passed with no output.

## Decisions Made

- The Phase 1 core has no runtime package dependencies; Python standard-library dataclasses, enums, and JSON keep platform adapters isolated and tests offline.
- The diagnostic uses a stable `capabilities` list and `state` object so later live probes can populate results without changing the CLI contract.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The system did not expose `python3.12` on `PATH`, but uv had a cached CPython 3.12.14 runtime. Verification used that cached interpreter without network access.
- The cached CPython 3.12.14 environment did not include pytest; the offline host pytest installation was supplied through `PYTHONPATH` for verification. No test or runtime dependency was downloaded, and the project core remains dependency-free.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The next Phase 1 plans can add real Wayland/session and microphone adapters behind the pure contracts without changing the test harness or importing desktop providers in the diagnostic entry point.
- GTK4/libadwaita, D-Bus, and PipeWire remain documented host integration boundaries and are intentionally not imported or required by this plan.

---
*Phase: 01-wayland-foundation*
*Completed: 2026-10-16*
