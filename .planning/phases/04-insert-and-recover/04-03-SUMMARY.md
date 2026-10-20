---
phase: 04-insert-and-recover
plan: 03
status: automatic-complete-host-pending
subsystem: recovery-cli
tags: [recovery, cli, history, clipboard, retry, host-acceptance]
requires: [04-02]
provides:
  - typed recovery controller with redacted metadata and explicit text access
  - fixed top-level recovery CLI dispatch for list/show/save/copy/retry
  - offline coverage for recovery actions, failure codes, redaction, and retry guards
affects: [05-01, 05-03]
automatic_tasks: 2/2
host_acceptance: pending
requirements_validated: []
automatic_completed: 2026-10-19
duration: not measured
---

# Phase 4 Plan 3: Automatic recovery surface summary

The two automatic tasks in Plan 04-03 are complete in the current worktree.
The blocking GNOME host-acceptance task was not run. This is a partial summary;
the plan and Phase 4 remain host-pending, and no INSERT or REC requirement is
marked validated here.

## Automatic implementation confirmed

- `src/voxflow/recovery.py` provides the provider/GTK-free `RecoveryController`
  and stable action results. `list` returns metadata and action availability
  without raw/final text; `show` is the explicit text-bearing action; `save`
  writes UTF-8 files with mode `0600` without replacing an existing target;
  `copy` requires a completed clipboard transfer and does not send a paste
  chord; and `retry` claims a durable pre-side-effect guard before insertion
  and refuses ambiguous or already-completed attempts.
- `src/voxflow/__main__.py` includes `recovery` in the fixed subcommand
  allowlist and dispatches it to `voxflow.recovery.main`.
- `src/voxflow/platform/insert_cli.py` supplies the existing lazy inserter
  opener used by recovery actions, preserving the portal-owned cleanup path.
- `README.md` documents the recovery commands, redacted listing behavior,
  explicit `show`/save behavior, manual clipboard transfer semantics, and
  pre-chord-only retry behavior.
- `src/voxflow/core/history.py` supplies the durable job/attempt records and
  compare-and-set retry guard consumed by the controller.

## Current worktree evidence files

- `tests/unit/test_recovery.py`
- `tests/unit/test_recovery_cli.py`
- `tests/integration/test_recovery_actions.py`

These tests cover all five actions, unavailable and invalid states, redacted
list/diagnostic output, explicit show/save, completed-transfer requirements,
pre-chord retry claims, ambiguous retry refusal, cleanup, cancellation, and
cross-process retry claiming.

## Offline verification

The following commands were run from the repository root with no live desktop
interaction:

- `NETWORK_DISABLED=1 PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_recovery.py -q`
  — **14 passed** in 0.12s.
- `NETWORK_DISABLED=1 PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_recovery_cli.py tests/integration/test_recovery_actions.py -q`
  — **23 passed** in 0.35s.
- `NETWORK_DISABLED=1 make test` — **348 passed** in 1.03s.
- `make lint` — passed.
- `uv lock --check --offline` — passed; resolved 40 packages in 0.80ms.
- `git diff --check` — passed.

These checks establish offline controller/CLI behavior only. They do not prove
D-Bus fd passing, EIS negotiation, compositor keymap readiness, focused-app
insertion, clipboard ownership across a real target, or host recovery behavior.

## Host acceptance remains pending

`.planning/phases/04-insert-and-recover/04-HOST-ACCEPTANCE.md` remains
`PENDING / NOT RUN`. No live host checks were run or inferred from the offline
tests. The following remain open in that matrix:

- identity registration, capability probing, and first-consent behavior;
- Text Editor and Firefox insertion, including the 20/20 attempt sets and
  release-to-text p50/p95 measurements;
- terminal Ctrl+V/Ctrl+Shift+V behavior and a confirmed XWayland target;
- logout/login restore-token reuse and dialog count;
- denied and unavailable insertion while capture/ASR remains recoverable;
- safe pre-chord retry, ambiguous post-chord refusal, explicit show/save,
  clipboard-only copy, cancellation, duplicate prevention, and both audio
  retention settings.

INSERT-01, INSERT-02, INSERT-03, REC-01, REC-02, and REC-03 are therefore not
validated by this summary. The parent should reconcile the host evidence with
the upstream Phase 02.1 acceptance artifact before marking any requirement or
the phase complete.

## Planning status and blockers

No shared `.planning/STATE.md`, `.planning/ROADMAP.md`, or
`.planning/REQUIREMENTS.md` tracking was changed. The phase-local host
acceptance artifact was also left unchanged. The remaining blocker is the
user-run GNOME acceptance checkpoint defined by Task 3 of Plan 04-03; this
summary intentionally closes only the automatic portion.
