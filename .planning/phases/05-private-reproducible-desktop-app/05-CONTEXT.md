---
phase: 05-private-reproducible-desktop-app
status: ready-for-execution
source: repository reconnaissance, Phase 4 transition, and roadmap requirements
---

# Phase 5 Context: Private, Reproducible Desktop App

## User outcome

As a Linux user, I can open VoxFlow's settings, see which local or remote
provider and model will be used, choose my microphone/shortcut/writing and
insertion behavior, and change retention without editing files. The default
path remains local and offline. If I need help, diagnostics explain capability
and policy state without exposing my words, audio, clipboard, credentials, or
machine paths. I can install the same pinned project on a clean Linux checkout,
run the offline test command, and understand which GNOME checks still require
my desktop session.

## Current baseline

- The repository targets Python 3.12; `.python-version` says `3.12`, the
  project requires `>=3.12,<3.13`, and `uv.lock` is present. The checked-out
  project venv currently reports Python 3.12.14.
- `src/voxflow/settings.py` has a SQLite key/value store plus schema version 3,
  writing preferences, dictionary/correction/snippet tables, selected model,
  cleanup policy, and `retain_audio`. Its migration is idempotent but is still
  a single compatibility routine rather than an explicit migration sequence.
- `src/voxflow/core/history.py` stores raw/final text intentionally for recovery
  while `list`/trace serialization is hash/count/allow-list based. Database
  files are normalized to mode `0600`. `src/voxflow/recovery.py` exposes the
  provider/GTK-free `list`, `show`, `save`, `copy`, and pre-side-effect `retry`
  actions.
- The daemon reads writing and audio-retention settings at startup, persists
  job/attempt state, and already deletes non-retained capture artifacts at
  terminal processing. The missing layer is user-facing configuration and a
  single redacted diagnostic projection across settings, capabilities, daemon,
  provider, and recovery state.
- There is no `src/voxflow/ui/`, no settings subcommand/window, no Dockerfile,
  and no package/build target. `Makefile` has offline `test` and compile-only
  `lint`; `packaging/` contains the desktop entry and user systemd unit.
- Phase 4 automatic work is complete through plan 04-03, but its GNOME host
  acceptance remains `PENDING / NOT RUN`. No real D-Bus fd passing, EIS
  negotiation, focused-app insertion, restore-token reuse, or terminal behavior
  is claimed by offline summaries.
- The working tree already contains broad uncommitted Phase 3/4 implementation
  and planning changes. Phase 5 execution must preserve those changes and only
  touch the files named by its own plan.

## Phase scope

### In scope

1. **Settings and policy**
   - Add a typed application-settings boundary over SQLite for microphone,
     shortcut trigger/behavior, language, style, ASR provider/model, cleanup
     provider/policy, audio retention, and insertion behavior.
   - Preserve the existing selected-model key, writing rules, job history, and
     insertion attempts while introducing explicit numbered migrations for the
     next schema version.
   - Validate settings before persistence and make local/offline the safe
     default. A remote provider must carry `remote_explicit` policy and positive
     network disclosure; secrets remain environment-variable references only.
   - Expose settings through a headless typed controller/JSON command and a
     lazy GTK4/libadwaita window. GTK widgets display state and dispatch typed
     commands; they do not call providers or SQLite directly.

2. **Privacy, retention, and diagnostics**
   - Keep `retain_audio=false` as the default and make the current audio
     lifecycle visible. Any explicit clear/delete action must remove retained
     artifacts using opaque IDs and update durable metadata transactionally.
   - Add one safe diagnostic projection for settings, capability states,
     provider policy, version/build information, and redacted recovery/job
     counts. It may include hashes, counts, coarse endpoint classes, stable
     error codes, and capability reasons; it must not include transcript/audio/
     clipboard content, tokens, credential values, endpoint URLs, or absolute
     paths.
   - Keep intentional `recovery show`/`save` as the only text-bearing recovery
     actions. Normal daemon output, settings output, and diagnostic bundles stay
     redacted.

3. **Reproducible project and deployment shape**
   - Make the Python version, dependency declarations, lockfile, build backend,
     and package data agree. Do not introduce an unpinned runtime dependency.
   - Add a non-GUI Docker build/test path with all required Linux packages for
     the offline core checks. Docker is evidence for reproducible build/test,
     not evidence for GNOME portal or focused-application behavior.
   - Make `make test` remain one explicit offline command and add deterministic
     build/check targets without allowing them to fetch models or contact
     providers. Document clean-checkout setup, local model installation,
     settings/daemon use, user service installation, package build, Docker
     verification, and the host-only acceptance boundary.

4. **Final evidence and release review**
   - Run the complete offline regression and packaging checks after the
     implementation plans finish.
   - Reconcile Phase 02.1 and Phase 4 acceptance artifacts with actual user-run
     Ubuntu GNOME results. Keep every unrun check explicitly unclaimed and
     classify failures as pass, bounded limitation, or blocked with a concrete
     reason.
   - Update requirement/roadmap/state evidence only for behavior supported by
     automated results or recorded host observations.

### Out of scope

- Command Mode, Notetaker, mobile, sync, team, billing, analytics, or account
  features.
- A cloud provider, hosted telemetry, automatic model download, or background
  network connection.
- Replacing the portal/EIS insertion path, adding X11 injection as the GNOME
  default, or inventing a GTK overlay that steals focus from the target app.
- Treating fake portal/audio tests, Docker, or static REA evidence as proof of
  live GNOME behavior.

## Locked implementation decisions

### 1. Keep the local SQLite boundary and migrate forward

The existing `settings.py` connection/migration boundary remains the storage
entry point. Add explicit migration functions and a current schema version
after v3 rather than replacing the database or moving settings to JSON. A
database with a newer schema fails closed with an actionable error. Migrations
must be idempotent, transactional, preserve existing rows, and be covered with
fixtures for first use plus legacy v1/v2/v3 shapes.

### 2. Separate policy from presentation

The settings controller owns validation and returns immutable snapshots. The
GTK window and JSON/CLI surface consume those snapshots. The daemon continues
to snapshot settings per job, so changing settings cannot mutate an active job.
The UI may show the exact current policy (`local_only` versus
`remote_explicit`) and coarse endpoint class, but never displays a credential
value or writes one to SQLite.

### 3. Diagnostics are allow-listed, not scrubbed after assembly

Build diagnostic dictionaries from named safe fields. Do not serialize arbitrary
exception strings, settings objects, provider config objects, paths, or full
history records and then attempt substring redaction. The existing
`to_safe_dict()` methods remain the source of safe job/provider/capability
metadata; new aggregation code must preserve those boundaries.

### 4. GTK is optional at import time

The core package and offline tests must run without `gi` or a live display.
GTK4/libadwaita imports are lazy and the settings command reports a typed
capability failure when the host GUI dependency is missing. Host acceptance may
exercise the native window; Docker and `make test` do not claim to do so.

### 5. Host acceptance is a final evidence gate, not an implementation blocker

Phase 5 plans may execute against the Phase 4 automatic APIs while Phase 4 host
acceptance is pending. The pending host artifact is a dependency risk for final
release status, not a reason to defer settings, privacy, or packaging work.
The final plan must not mark INSERT/SKEL/REC or the host portions of Phase 5
validated from offline tests alone.

## Plan sequencing and dependencies

| Wave | Plan | Depends on | Delivery |
|---|---|---|---|
| 1 | 05-01 | Phase 4 automatic API/CLI surface (04-03); Phase 4 host evidence is not required to start | Typed settings/policy, migrations, privacy/retention behavior, redacted diagnostics, lazy settings UI |
| 2 | 05-02 | 05-01 | Pinned runtime/build metadata, Dockerfile, Makefile checks, packaging, and verified documentation |
| 3 | 05-03 | 05-01 and 05-02; host evidence is checked here | Full regression, host acceptance/evidence reconciliation, release readiness and state updates |

## Requirement coverage

| Requirement | Phase 5 commitment | Evidence needed |
|---|---|---|
| PRIV-01 | Local ASR/cleanup and `local_only` are default; remote selection is explicit and visible | Unit/integration policy tests plus settings/diagnostic inspection |
| PRIV-02 | Diagnostics, logs, history list, and provider metadata use allow-listed redaction | Redaction tests with transcript/token/path fixtures and safe CLI output review |
| CONFIG-01 | Validated persistence and settings surfaces cover microphone, shortcut, language, style, provider, model, retention, and insertion behavior | Headless controller tests; GTK host check remains explicit |
| BUILD-01 | Clean pinned checkout builds, tests offline, and has no machine-specific path/secret assumptions | `uv lock --check --offline`, `make test`, package build, Docker build/run, path/secret audit |

## Acceptance boundary

Automated evidence can establish settings validation, migration preservation,
redaction, retention state transitions, package reproducibility, and offline
regression. It cannot establish portal consent, hold/release semantics, EIS
keymap readiness, focused-app insertion, restore-token reuse, microphone
permission, or real GTK behavior on the target host. Those checks remain in the
Phase 02.1/Phase 4 host artifacts and the new Phase 5 host acceptance artifact;
all remain unclaimed until the user records them.

## Phase success

Phase 5 is implementation-complete when the three plans' automatic checks pass,
the clean-checkout/build instructions are reproducible, and the host matrix is
filled with honest dispositions. It is release-ready only when the parent
reconciles the pending Phase 4/02.1 host evidence and updates requirement status
without converting missing evidence into a pass.
