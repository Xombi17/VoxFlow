---
phase: 04-insert-and-recover
plan: 02
subsystem: durable-recovery
tags: [sqlite, history, insertion-attempts, retention, cancellation, idempotency]
requires: [04-01]
provides:
  - versioned SQLite dictation job history with intentional raw/final text storage
  - redacted history-list, attempt-trace, and diagnostic serialization boundaries
  - durable insertion-attempt records created before the paste side effect
  - daemon-owned active job/runner lifecycle persistence and explicit retry seam
  - persisted audio retention policy with terminal artifact cleanup
affects: [04-03, 05-01]
tech-stack:
  added: []
  patterns: [sqlite migration, compare-and-set attempt phase, explicit recovery API, terminal retention cleanup]
key-files:
  created:
    - src/voxflow/core/history.py
    - tests/unit/test_history.py
    - tests/unit/test_audio_retention.py
    - tests/integration/test_daemon_recovery.py
  modified:
    - src/voxflow/settings.py
    - src/voxflow/audio/session.py
    - src/voxflow/daemon.py
    - src/voxflow/platform/insert.py
requirements-completed: [INSERT-02, REC-01, REC-02, REC-03]
duration: not measured
completed: 2026-10-19
---

# Phase 4 Plan 2: Durable history and recovery summary

VoxFlow now has a local SQLite recovery boundary for dictation jobs and paste
attempts. A job is created when capture starts, remains associated with the
active runner through transcription and writing, and is updated before and
after insertion. The daemon clears its active references only after terminal
history persistence completes.

## Implemented

- Incremented the SQLite schema version and added normalized `dictation_jobs`
  and `insertion_attempts` tables without disturbing existing settings, model,
  dictionary, correction, or snippet data.
- Added typed `HistoryRecord`, redacted `HistorySummary`, and
  `InsertionAttemptRecord` contracts. Full raw/final text is available only
  through explicit `show_job`/`show` or `to_user_dict()` paths; list and trace
  serialization contains hashes, lengths, safe metadata, and allow-listed
  status fields.
- Persisted complete per-job writing settings snapshots locally while keeping
  diagnostics on the existing safe settings boundary. Provider metadata and
  failure details are filtered before durable diagnostic storage.
- Created insertion attempt rows before calling the inserter, passed the
  durable attempt ID through the existing inserter when supported, and added a
  compare-and-set phase update. Pre-chord failures are retryable; completed or
  unknown post-chord outcomes are not silently retried.
- Added a recovery controller seam with redacted list, intentional show, save,
  and serialized retry behavior. Retry calls are locked and accepted insertion
  attempts are idempotent; ambiguous post-chord retry requires explicit
  confirmation.
- Persisted `retain_audio` in the existing settings database, defaulting to
  disabled. The daemon uses a unique opaque artifact ID, deletes artifacts
  after terminal processing when retention is disabled, and keeps artifacts
  available for retry when retention is enabled. No artifact filesystem path is
  written to history or diagnostics.
- Added `AudioSession` terminal retention metadata and an idempotent artifact
  discard operation. Existing session and inserter call shapes remain
  compatible, including fake inserters that do not accept an attempt keyword.

## Focused audit remediation

- Shutdown now requests runner cancellation without awaiting the processing
  task from inside its own outer task, then cancels and awaits that processing
  task directly. Cancellation during writing stores a recoverable fallback
  `WritingResult` and a terminal cancelled state.
- A successful ASR snapshot remains durable as `processing` until raw and final
  writing text exists. The history store rejects success rows without both
  text fields.
- Insertion attempts enter a durable non-retryable ambiguous guard before the
  inserter is called. A process-window interruption therefore cannot reload as
  a safe prepared retry.
- Added `retry_transcription(job_id)` for retained artifacts, including retry
  count persistence and the normal writing/insertion completion path. Missing
  retained audio removes the retry advertisement instead of pretending the
  operation remains recoverable.
- SQLite database files are normalized to mode `0600` for both new and
  existing files, while `:memory:` connections remain unaffected.
- Startup removes disabled-retention orphan jobs and transient WAV files using
  opaque/redacted metadata, preserving the list/show privacy boundary.

## Verification evidence

- `NETWORK_DISABLED=1 PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_jobs.py tests/unit/test_history.py tests/unit/test_audio_retention.py tests/integration/test_daemon_loop.py tests/integration/test_daemon_recovery.py -q` — **34 passed**.
- `NETWORK_DISABLED=1 make test` — **310 passed**.
- `make lint` — passed; the project compile check covered `src`, `tests`, and
  `tools`.
- `uv lock --check --offline` — passed; resolved **40 packages**.
- `git diff --check` — passed.

## Host boundary and non-goals

No live GNOME, D-Bus fd passing, EIS negotiation, focused-application paste,
restore-token reuse, or terminal behavior was run or claimed. The Phase 4
recovery CLI/UI was not built; the controller is the API seam for the later
surface work.

No commit was created. `ROADMAP.md` and `STATE.md` were not edited during this
plan; unrelated pre-existing working-tree changes were preserved.

**Self-Check: PASSED** — targeted recovery/retention tests, the full offline
suite, lint, offline lock validation, and whitespace validation passed after the
final implementation mutations.
