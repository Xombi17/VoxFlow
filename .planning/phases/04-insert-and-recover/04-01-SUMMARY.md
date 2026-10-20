---
phase: 04-insert-and-recover
plan: 01
subsystem: portal-eis-insertion
tags: [clipboard, remote-desktop, libei, xkbcommon, recovery-boundary, daemon]
requires: [02.1-02, 02.1-03, 03-01, 03-02, 03-03]
provides:
  - serialized redacted insertion attempts with side-effect classification
  - configurable compositor-keymap-derived EIS chord sequences
  - transactional RemoteDesktop/Clipboard setup and callback cleanup
  - insertion capability reporting and nonfatal daemon startup
affects: [04-02, 04-03]
tech-stack:
  added: []
  patterns: [asyncio lock, redacted attempt trace, portal rollback, fake-backed capability probe]
key-files:
  created: []
  modified:
    - src/voxflow/platform/insert.py
    - src/voxflow/platform/insert_cli.py
    - src/voxflow/platform/eis.py
    - src/voxflow/platform/portals.py
    - src/voxflow/core/capabilities.py
    - src/voxflow/__main__.py
    - src/voxflow/daemon.py
    - tests/unit/test_insert.py
    - tests/unit/test_eis.py
    - tests/unit/test_remote_desktop_portal.py
    - tests/unit/test_capabilities.py
    - tests/integration/test_daemon_loop.py
key-decisions:
  - Keep positional InsertOutcome construction and send_paste_chord compatibility while adding attempt metadata.
  - Treat invocation of the paste chord as the side-effect boundary; transfer timeout is unknown_after_side_effect and never retryable automatically.
  - Keep GlobalShortcuts capability mapping unchanged and add insertion-specific status mapping, including unavailable.
  - Continue dictation capture/transcription when insertion consent or service availability fails; retain the WritingResult and report a truthful save/retry hint.
requirements-completed: [INSERT-01, INSERT-03]
duration: not measured
completed: 2026-10-18
---

# Phase 4 Plan 1: Portal/EIS insertion hardening summary

VoxFlow insertion is now serialized, observable through redacted attempt metadata, rollback-safe at the portal boundary, and nonfatal to completed dictation when insertion is unavailable.

## Implemented

- Added unique attempt IDs, ordered safe trace events, retryability, and side-effect classifications to `InsertOutcome`.
- Added one `asyncio.Lock` per `Inserter`, so concurrent calls cannot interleave clipboard ownership, chord, or transfer handling.
- Added configurable key-name chords with Ctrl+V as the default and Ctrl+Shift+V support. Aliases normalize literal character keysyms to the lowercase names expected by xkbcommon, and EIS emits keymap-derived key codes only; it does not type transcript characters.
- Added per-attempt SelectionTransfer generations so late callbacks are drained/ignored after timeout and cannot satisfy an explicit retry. EIS chord cleanup now releases pressed keys and stops emulation on every emission failure while preserving the original exception.
- Changed failure hints to state that text is retained instead of claiming it was copied when clipboard ownership is unavailable.
- Added RemoteDesktop setup rollback after session creation, delayed restore-token persistence until clipboard-enabled startup succeeds, and explicit signal unsubscribe cleanup.
- Added insertion-specific capability mapping for available, needs-user-action, unavailable, and unsupported outcomes, plus `--probe-portals` insertion readiness/consent metadata. Portal setup remains pending/unavailable until EIS and keymap readiness is verified; unknown portal methods map to unsupported.
- Updated the daemon to continue shortcut/capture setup when RemoteDesktop/Clipboard startup fails, retain the completed `WritingResult`, and expose an explicit unavailable `InsertOutcome` with unique retry-safe attempt metadata for the future recovery controller.
- Added fake-backed coverage for serialization, trace redaction/order, pre/post-chord classification, key sequence emission, portal rollback, callback cleanup, capability redaction, and daemon retention.

## Verification evidence

- `NETWORK_DISABLED=1 PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_insert.py tests/unit/test_remote_desktop_portal.py tests/unit/test_eis.py tests/unit/test_capabilities.py tests/unit/test_portals.py tests/integration/test_daemon_loop.py tests/integration/test_writing_pipeline.py -q` — **104 passed**.
- `NETWORK_DISABLED=1 make test` — **293 passed**.
- `make lint` — passed (Python 3.12 compile check for `src`, `tests`, and `tools`).
- `uv lock --check --offline` — passed (`Resolved 40 packages in 2ms`).
- `git diff --check` — passed.

## Host boundary and blockers

No live GNOME, D-Bus fd passing, EIS negotiation, focused-app paste, restore-token reuse across logout/login, or terminal behavior was claimed or run. Those remain explicit host acceptance work. Phase 4 persistence/recovery UI was not implemented.

## Deviations from Plan

None. The optional GNOME Shell extension fallback remains deferred under the locked phase non-goal because no host acceptance evidence shows the portal/EIS path is insufficient.

**Self-Check: PASSED** — targeted and full offline verification completed after the final code/test mutations; no commit was created per user instruction.
