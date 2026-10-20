---
phase: 05-private-reproducible-desktop-app
plan: 01
status: automatic-complete-host-pending
subsystem: settings-privacy-diagnostics-ui
tags: [settings, migrations, privacy, diagnostics, retention, recovery, gtk]
requires: [04-03]
provides:
  - typed immutable application settings over the existing SQLite boundary
  - explicit schema-v4 forward migration with legacy preservation
  - allow-listed diagnostics and bounded artifact cleanup
  - headless settings controller and lazy GTK4/libadwaita surface
  - fixed voxflow settings dispatch
affects: [05-02, 05-03]
automatic_tasks: 3/3
host_acceptance: pending
requirements_validated: []
automatic_completed: 2026-10-19
---

# Phase 5 Plan 1: Settings, privacy, diagnostics, and UI summary

The three automatic tasks in Plan 05-01 are complete in the current worktree.
The implementation preserves the existing Phase 3/4 SQLite, writing, history,
daemon, and recovery APIs while adding the Phase 5 policy and presentation
boundary. The dirty Phase 3/4 worktree was preserved; no commit, staging,
stash, reset, or dependency installation was performed.

## Automatic implementation

- `src/voxflow/settings.py` now exposes frozen `ApplicationSettings` and an
  `ApplicationSettingsStore` facade over the existing `WritingSettingsStore`.
  It validates microphone and shortcut IDs, shortcut mode, provider policy,
  disclosure, selected model IDs, keymap chord names, retention, insertion
  preferences, and bounded timings before one transactional update. Local ASR,
  deterministic cleanup, `local_only`, Ctrl+V, and disabled audio retention
  remain the defaults. The existing `selected_model_id` key remains
  authoritative.
- The SQLite boundary advances from schema v3 to v4 through an ordered,
  idempotent migration registry. Legacy v1/v2/v3 writing settings, rules,
  selected model data, jobs, and insertion attempts remain intact. A newer
  unknown schema fails closed.
- `src/voxflow/core/diagnostics.py` builds diagnostics from named safe fields:
  application/schema identity, policy, coarse provider identity, capabilities,
  state, aggregate history/retention/error counts, and no arbitrary serialized
  settings, history, exception, endpoint, path, transcript, audio, clipboard,
  credential, or restore-token content.
- `HistoryStore.clear_artifact()` and the recovery `delete` action provide an
  idempotent opaque-ID cleanup boundary. Daemon terminal/orphan cleanup now
  resolves artifacts only beneath the configured capture directory and avoids
  symlinks/out-of-directory targets.
- `src/voxflow/ui/settings.py` provides a GTK-free `SettingsController`, safe
  JSON/headless output and updates, stable validation/storage errors, and a
  GTK4/libadwaita window imported only when the GUI action is requested.
  `voxflow settings` is included in the fixed dispatcher. Missing GTK reports
  the typed `gtk_unavailable` result; the headless path remains usable.
- Added/updated tests in `tests/unit/test_text_settings.py`,
  `tests/unit/test_privacy_policy.py`, `tests/unit/test_diagnostics.py`, and
  `tests/integration/test_settings_surface.py`. Existing history, retention,
  daemon, recovery, CLI, and Phase 3 settings coverage was retained.

## Offline verification

Commands were run from the repository root after the final source mutation:

- `NETWORK_DISABLED=1 PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_text_settings.py tests/unit/test_provider_config.py tests/unit/test_privacy_policy.py -q` — **29 passed**.
- `NETWORK_DISABLED=1 PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_diagnostics.py tests/unit/test_privacy_policy.py tests/unit/test_history.py tests/unit/test_audio_retention.py tests/integration/test_daemon_recovery.py tests/integration/test_recovery_actions.py -q` — **37 passed**.
- `NETWORK_DISABLED=1 PYTHONPATH=src .venv/bin/python -m pytest tests/integration/test_settings_surface.py tests/unit/test_cli_dispatch.py tests/unit/test_text_settings.py -q` — **18 passed**.
- `NETWORK_DISABLED=1 make test` — **367 passed**.
- `make lint` — passed; the repository target runs the Python 3.12 compile check for `src`, `tests`, and `tools`.
- `PYTHONPATH=src .venv/bin/python -m compileall -q src tests tools` — passed.
- `PYTHONPATH=src .venv/bin/python -c 'import voxflow.ui; import voxflow.ui.settings; print("headless-import-ok")'` — passed with `headless-import-ok`.
- `uv lock --check --offline` — passed; resolved 40 packages.
- `git diff --check` — passed.

These checks establish offline settings validation/migration, policy enforcement,
redaction, retention cleanup, recovery boundaries, headless controller behavior,
and importability. They do not establish live desktop behavior.

## Host acceptance remains pending

No live GTK rendering, GTK4/libadwaita availability, Wayland session behavior,
XDG portal consent, GlobalShortcuts hold/release signals, microphone permission,
RemoteDesktop/Clipboard fd passing, EIS negotiation/keymap readiness,
focused-application insertion, restore-token reuse, or GNOME recovery behavior
was run or inferred from the offline tests. Those checks remain for the Phase 5
host acceptance/release evidence and the pending Phase 4/02.1 host artifacts.
PRIV-01, PRIV-02, and CONFIG-01 therefore remain unvalidated in the shared
requirements tracker until the parent phase reconciles automated evidence with
the required host checks.
