---
phase: 01-wayland-foundation
plan: 02
subsystem: platform
tags: [python, wayland, xdg-portal, dbus, global-shortcuts, diagnostics]

# Dependency graph
requires:
  - 01-01
provides:
  - Redacted Wayland/X11/unknown session detection with injectable environment maps.
  - Typed, injectable XDG GlobalShortcuts portal probing and error mapping.
  - Global shortcut session/binding adapter with activation/deactivation event mapping.
  - Safe JSON portal probe and opt-in live platform diagnostics.
affects: [01-03, platform-adapters, audio-adapters, host-acceptance]

# Tech tracking
tech-stack:
  added: [Python standard library async protocols, optional lazy dbus-next transport]
  patterns: [injectable portal transport, typed capability/error mapping, portal-first signals]

key-files:
  created:
    - src/voxflow/platform/__init__.py
    - src/voxflow/platform/session.py
    - src/voxflow/platform/portals.py
    - src/voxflow/platform/shortcuts.py
    - tests/unit/test_portals.py
    - tests/integration/test_shortcuts_fake.py
    - tools/portal_probe.py
  modified:
    - src/voxflow/__main__.py

key-decisions:
  - "Keep dbus-next optional and lazy: the standard-library core and offline tests do not require a live desktop or dependency download."
  - "Use XDG GlobalShortcuts session creation and one-time binding as the only shortcut path in this plan; no X11 hooks, subprocesses, /dev/input, or network behavior."
  - "Only report hold support after both Activated and Deactivated callbacks are exposed and observed; activation-only portals are explicitly toggle-only."
  - "Portal diagnostics expose display-variable presence rather than raw paths and never include audio, transcript, clipboard, credentials, or machine paths."

patterns-established:
  - "PortalConnection is the injectable async boundary for introspection, method calls, and signal subscriptions."
  - "PortalClientError and PortalFailure normalize service, permission, cancellation, malformed-response, and request failures into capability statuses."
  - "GlobalShortcutsAdapter emits ShortcutEvent values and does not start audio or call UI/provider code."

requirements-addressed: [PLAT-01, PLAT-02, PLAT-03]
requirements-completed: [PLAT-01, PLAT-03]
requirements-pending: [PLAT-02]

# Metrics
duration: 25 min
completed: 2026-10-16
---

# Phase 1 Plan 2: Wayland Foundation Portal Adapter Summary

**Portal-first Ubuntu GNOME session detection, GlobalShortcuts binding/events, fake coverage, and safe JSON diagnostics**

## Performance

- **Tasks:** 3 completed
- **Files changed:** 7 created and 1 modified by the plan
- **Task commits:** 3 implementation commits plus 1 metadata commit to follow

## Plan Requirements

Copied from the plan frontmatter and acceptance scope:

- `requirements: [PLAT-01, PLAT-02, PLAT-03]`
- **PLAT-01:** The application reports whether it is running on Wayland, X11, or an unsupported session and lists the available shortcut, clipboard, paste, and audio capabilities.
- **PLAT-02:** The user can configure and bind a dictation shortcut through a supported Ubuntu GNOME integration without the application requiring an account or paid service.
- **PLAT-03:** The user sees a clear idle, listening, processing, success, cancelled, or failed status while a dictation job is active.

PLAT-01 and PLAT-03 are implemented in the reusable core/platform diagnostic contracts. PLAT-02 is addressed by the portal binding adapter and fake coverage, but remains pending live Ubuntu GNOME validation because this host has no installed `dbus-next` bridge and no permission-dialog smoke test was possible.

## Accomplishments

- Added `detect_session()` with injected environment support. Explicit `XDG_SESSION_TYPE` takes precedence, display variables are fallback signals, and serialized diagnostics retain only display-variable presence flags.
- Added an async `PortalConnection` protocol and `GlobalShortcutsPortal` client for `org.freedesktop.portal.GlobalShortcuts` at the standard desktop portal name/path.
- Added typed `PortalErrorCode`, `PortalClientError`, `PortalFailure`, and capability mapping for unavailable services, denied permissions, cancellation, malformed responses, and request failures.
- Added a lazy optional `dbus-next` transport. The locked project remains dependency-free for offline core tests; a missing bridge is reported as a structured unsupported capability.
- Added `GlobalShortcutsAdapter` for session creation, one-time binding, configured trigger-description preservation, and `Activated`/`Deactivated` event translation into core-facing listening-start/listening-stop events.
- Added honest hold/release semantics: both signal callbacks must be available and observed before `hold_supported` becomes true. An activation-only backend is reported as toggle-only, with no synthesized release based on timing.
- Added `tools/portal_probe.py --json` and opt-in `python -m voxflow --json --probe-portals` wiring. The default `python -m voxflow --json` remains free of live D-Bus calls.
- Added deterministic fake tests for session classification, portal availability/error mapping, activation/deactivation events, binding errors, empty bindings, and activation-only limitations.

## Task Commits

Each implementation task was committed atomically:

1. **Task 1: Add session and portal capability detection** - `13e63af` (`feat`)
2. **Task 2: Implement GlobalShortcuts press/release mapping** - `2f4ec2a` (`feat`)
3. **Task 3: Add a JSON host portal probe and diagnostic wiring** - `7297d30` (`feat`)
4. **Supplemental portal response/error normalization** - `753d3f9` (`fix`)

**Plan metadata:** included in the metadata commit for this plan.

## Files Created/Modified

- `src/voxflow/platform/__init__.py` - platform adapter package marker.
- `src/voxflow/platform/session.py` - redacted session detection and session capability record.
- `src/voxflow/platform/portals.py` - injectable portal protocol, typed errors, GlobalShortcuts probe/binding, and optional lazy D-Bus transport.
- `src/voxflow/platform/shortcuts.py` - portal session/binding lifecycle and typed signal events.
- `src/voxflow/__main__.py` - preserves the offline default diagnostic and adds explicit opt-in platform probing.
- `tests/unit/test_portals.py` - session and portal fake tests.
- `tests/integration/test_shortcuts_fake.py` - fake GlobalShortcuts event and failure tests.
- `tools/portal_probe.py` - safe direct host probe emitting structured JSON only.

## Verification Evidence

- `PATH="/home/varad/.local/share/uv/python/cpython-3.12-linux-x86_64-gnu/bin:$PATH" PYTHONPATH="src:/usr/lib/python3/dist-packages" NETWORK_DISABLED=1 make PYTHONPATH="src:/usr/lib/python3/dist-packages" test`
  - `21 passed in 0.03s`
- `PATH="/home/varad/.local/share/uv/python/cpython-3.12-linux-x86_64-gnu/bin:$PATH" PYTHONPATH="src:/usr/lib/python3/dist-packages" python3.12 -m pytest -q tests/unit/test_portals.py tests/integration/test_shortcuts_fake.py`
  - `10 passed in 0.01s`
- `PATH="/home/varad/.local/share/uv/python/cpython-3.12-linux-x86_64-gnu/bin:$PATH" PYTHONPATH=src python3.12 tools/portal_probe.py --json`
  - Valid JSON. Host session was reported as Wayland; `org.freedesktop.portal.GlobalShortcuts` was reported `unsupported` with `service_unavailable` because `dbus-next` is not installed.
- `PATH="/home/varad/.local/share/uv/python/cpython-3.12-linux-x86_64-gnu/bin:$PATH" PYTHONPATH=src python3.12 -m voxflow --json`
  - Valid provider-free JSON with empty capabilities and idle state.
- `PATH="/home/varad/.local/share/uv/python/cpython-3.12-linux-x86_64-gnu/bin:$PATH" PYTHONPATH=src python3.12 -m voxflow --json --probe-portals`
  - Valid JSON with session capability, portal result, and recommended next action.
- `python3.12 -m compileall -q src tests tools` using the cached project CPython 3.12 runtime
  - Passed.
- `git diff --check`
  - Passed with no whitespace errors.

## Decisions Made

- The real desktop connection is optional and lazy because the repository lockfile intentionally contains no runtime package dependency for Phase 1. This keeps `make test` offline and lets host packaging add `dbus-next` later.
- The probe reports capability and next-action data rather than treating a missing service as a process error. This makes unsupported compositor/backend combinations diagnosable.
- The adapter maps signals only to core events. Audio capture, state mutation, and UI behavior remain outside the platform adapter boundary.

## Deviations from Plan

- The plan's example command `python3.12 -m pytest` could not run directly because `python3.12` is not on the default `PATH`; verification used the cached project CPython 3.12 executable path already documented by plan 01-01.
- The cached CPython 3.12 runtime does not include pytest. The existing host pytest installation was supplied via `/usr/lib/python3/dist-packages` without installing dependencies or using the network.
- A live D-Bus binding/permission smoke test was not completed because this environment does not have `dbus-next` installed. The JSON probe returned the required structured unavailable result.

## Issues Encountered

- A plain `make test` under the cached CPython 3.12 failed with `No module named pytest`; overriding the Make variable with the already-installed host pytest path made the complete offline suite pass.
- The host exposes `XDG_SESSION_TYPE=wayland` and `WAYLAND_DISPLAY`, but portal capability could not be introspected without the optional D-Bus transport dependency. This is recorded as a bounded host limitation, not as a successful live portal validation.

## User Setup Required

- For live validation, make the optional `dbus-next` transport available in the project environment and run `python3.12 tools/portal_probe.py --json` from Ubuntu GNOME Wayland. Then bind the configured shortcut and verify both activation and deactivation callbacks through the host smoke test.
- No account, paid service, model download, network request, audio capture, or credential setup is required for the offline tests or safe probe.

## Next Phase Readiness

- Plan 01-03 can add microphone discovery/capture behind the same `src/voxflow/platform` boundary and combine its safe findings with this portal report.
- PLAT-02 still needs live backend/version, permission, and hold/release evidence before Phase 1 can claim full shortcut validation.
- No X11/global-hook library, subprocess call, unrestricted `/dev/input` read, or network behavior was added.

---
*Phase: 01-wayland-foundation*
*Completed: 2026-10-16*
