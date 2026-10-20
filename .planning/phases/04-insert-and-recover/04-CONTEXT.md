---
phase: 04-insert-and-recover
status: ready-for-planning
source: phase reconnaissance and Phase 3 transition
---

# Phase 4 Context: Insert and Recover

## User outcome

As a VoxFlow user, when insertion succeeds I want the final writing result in
the focused application exactly once. When the compositor, clipboard portal,
EIS, or a later processing step fails, I want the raw/final text and job state
to remain recoverable without silently retrying a paste that may already have
occurred.

## Scope

This phase delivers INSERT-01, INSERT-02, INSERT-03, REC-01, REC-02, and
REC-03. It builds on the offline portal/EIS insertion implementation from
Phase 02.1 and the immutable `WritingResult` from Phase 3.

The phase is intentionally API/CLI-first. The polished GTK settings and
history surfaces remain Phase 5 work; Phase 4 must provide a stable recovery
controller that a future UI can call.

## Locked implementation decisions

### Insertion is an observable side-effect state machine

Every insertion receives a unique attempt ID and emits a redacted trace with
events such as:

`attempt_started`, `selection_set`, `ownership_confirmed`, `release_settled`,
`chord_sent`, `transfer_received`, `selection_write_done`, and
`outcome_recorded`.

Trace entries contain only attempt ID, event name, monotonic elapsed time, and
safe status fields. They never contain text, clipboard bytes, restore tokens,
credentials, or local paths.

The inserter serializes concurrent calls with an `asyncio.Lock`. A transfer
timeout after `chord_sent` is `unknown_after_side_effect`, not an ordinary
retryable failure. A failure before the chord is `failed_before_side_effect`
and may be retried.

### Wayland insertion remains portal/EIS only

The primary path stays RemoteDesktop + Clipboard portal + libei EIS. No
`wl-copy`, `wtype`, `ydotool`, per-character typing, or X11 injection is added
to the GNOME path. Ctrl+V remains the default keymap-derived chord; a future
configured chord may express Ctrl+Shift+V without changing the transport.

Portal session setup is transactional. If any post-creation step fails, the
partially opened session is closed, subscriptions are removed, and the typed
failure is preserved. Insertion capability reporting must distinguish
available, needs-user-action, unavailable, and unsupported states.

### Permission failure does not lose a dictation

RemoteDesktop/Clipboard availability is an insertion capability, not a reason
to prevent capture and transcription. The daemon may start without an
inserter, retain the completed `WritingResult` in history, and expose recovery
actions. A fallback message must not claim that text was copied when no
clipboard ownership was established.

### Recovery is durable and idempotent

SQLite remains the local persistence boundary. Durable history stores the raw
and final text because the user explicitly needs recovery, but normal logs and
safe diagnostics continue to use hash-only metadata.

The minimum durable records are:

- dictation job: IDs, timestamps, status, raw/final text, provider/model,
  transformation settings snapshot, fallback/error metadata, retry count,
  audio retention state, and insertion outcome;
- insertion attempt: attempt ID, job ID, phase, chord-sent flag, transfer
  completion, ownership result, outcome, retryability, and safe trace.

Persist an insertion attempt before emitting the paste chord. Only attempts
that failed before the chord are automatically retryable. Attempts with an
unknown post-chord result require explicit user confirmation and are never
silently retried.

### Audio retention is explicit

`retain_audio=false` means the artifact may exist transiently for the current
ASR call but is deleted after the terminal job action. `retain_audio=true`
keeps it available for retry until the user deletes the job or a configured
expiry removes it. The policy and resulting artifact state are persisted.

## Integration boundary

The daemon currently creates `DictationJobRunner` inline and discards it after
processing. Phase 4 retains the active runner/job record, persists transitions,
and routes the `WritingResult` through a recovery controller before calling
`Inserter.insert()`.

The existing insertion order remains mandatory:

1. shortcut release;
2. capture stop and close;
3. ASR and writing pipeline;
4. durable job record;
5. insertion attempt preparation;
6. one keymap-correct paste chord;
7. transfer/write completion;
8. durable terminal outcome.

## Recovery action contract

Expose a small controller/API with explicit availability:

- `list`: safe metadata only;
- `show`: intentional user action that can return raw/final text;
- `copy`: only when a usable clipboard session exists;
- `retry`: only for pre-side-effect retry-safe attempts;
- `save`: always available through a user-selected local path.

The future GTK UI consumes this controller. Phase 4 does not add full GTK.

## Host boundary

Fake-backed tests can prove ordering, redaction, rollback, lock behavior, and
idempotency decisions. They cannot prove real D-Bus fd passing, EIS negotiation,
GNOME Text Editor/Firefox behavior, or restore-token reuse after logout/login.
Those remain explicit user-run acceptance checks in
`04-HOST-ACCEPTANCE.md` and the upstream Phase 02.1 acceptance artifact.

## Explicit non-goals

- no GNOME Shell extension unless host acceptance proves the portal/EIS path is
  insufficient;
- no automatic retry after a paste chord has been emitted;
- no clipboard restore unless current ownership is positively confirmed;
- no transcript content in standard diagnostics;
- no complete GTK history/settings UI in this phase.
