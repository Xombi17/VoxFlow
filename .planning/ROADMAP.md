# Roadmap: VoxFlow

## Overview

VoxFlow will be built as a Linux-first vertical slice. The roadmap starts by proving what Ubuntu GNOME Wayland permits for global shortcuts, microphone capture, clipboard, and paste. It then adds a local transcription loop, turns raw speech into personalized writing, makes insertion and recovery dependable, and finishes with privacy, settings, packaging, and acceptance checks. Command Mode, Notetaker, mobile, sync, and team features remain deferred until the dictation core is validated.

## Phases

- [x] **Phase 1: Wayland Foundation** - Prove platform capabilities and establish the testable application skeleton. (completed 2026-10-16)
- [ ] **Phase 2: Local Dictation Engine** - Capture microphone audio and transcribe it locally with optional providers.
- [ ] **Phase 3: Writing Pipeline** - Transform speech into polished, personalized text with deterministic rules and provider adapters.
- [ ] **Phase 4: Insert and Recover** - Paste into supported focused applications and recover from failure without data loss or duplicates.
- [ ] **Phase 5: Private, Reproducible Desktop App** - Finish settings, privacy controls, packaging, offline tests, and Ubuntu acceptance.

## Phase Details

### Phase 1: Wayland Foundation

**Goal**: The project can explain and exercise the user's Ubuntu GNOME Wayland capabilities without relying on unsupported X11 assumptions.
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: [PLAT-01, PLAT-02, PLAT-03, AUDIO-01]
**Success Criteria** (what must be TRUE):

  1. The application reports session type and per-feature capabilities with actionable reasons for unavailable features.
  2. A user can bind a shortcut through the selected supported path and observe start/stop/cancel state changes in a host smoke test, or the UI clearly reports the tested limitation and provides a supported fallback.
  3. A selected microphone can be opened, denied, disconnected, and recovered with deterministic status transitions.
  4. Offline unit tests cover capability mapping, permission errors, and session state transitions without needing a live desktop.

**Plans**: 3 plans

Plans:
**Wave 1**

- [x] 01-01: Bootstrap pinned Python/GTK project structure, core state contracts, and offline test harness.

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 01-02: Implement Ubuntu GNOME Wayland capability probes and GlobalShortcuts/permission spike.
- [x] 01-03: Implement microphone discovery/capture probe and document the validated host integration matrix.

### Phase 2: Local Dictation Engine

**Goal**: A user can capture a short utterance and obtain a local transcript with measured performance.
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: [AUDIO-02, AUDIO-03, AUDIO-04]
**Success Criteria** (what must be TRUE):

  1. With network access disabled, an installed local model transcribes a recorded fixture and a live short utterance.
  2. The same core job accepts an explicitly configured LAN/cloud provider without changing the job lifecycle or UI contract.
  3. The app exposes cold-start, warm-start, and end-to-end timings for provider profiles without transmitting telemetry.
  4. Cancellation and model/provider errors leave a structured recoverable job state instead of freezing the UI.

**Plans**: 3 plans

Plans:

- [ ] 02-01: Add PipeWire-compatible audio session, bounded buffers, WAV/fixture support, and cancellation.
- [ ] 02-02: Add local Whisper provider with model discovery, checksum metadata, VAD/segmentation, and benchmarks.
- [ ] 02-03: Add optional remote provider protocol, provider configuration, and offline/mock contract tests.

### Phase 3: Writing Pipeline

**Goal**: Raw speech becomes readable text while preserving the original transcript and user control.
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: [TEXT-01, TEXT-02, TEXT-03, TEXT-04, TEXT-05]
**Success Criteria** (what must be TRUE):

  1. Golden fixtures demonstrate punctuation, paragraph/list formatting, filler cleanup, and obvious self-correction handling.
  2. A user can select language and Personal/Work/Email/Other style profiles for future jobs.
  3. Dictionary words, whole-word corrections, and snippets apply deterministically, with longer/explicit rules winning according to documented precedence.
  4. The raw transcript remains available beside the final output, and optional cleanup providers are visibly selected per job.

**Plans**: 3 plans

Plans:

- [ ] 03-01: Build immutable raw/final text contracts and deterministic normalization/formatting pipeline.
- [ ] 03-02: Add SQLite-backed dictionary, corrections, snippets, language settings, and style profiles.
- [ ] 03-03: Add deterministic cleanup and optional local/LAN/cloud cleanup provider interface with fixture tests.

### Phase 4: Insert and Recover

**Goal**: A completed dictation reliably reaches the focused app or remains recoverable with no duplicate paste.
**Mode:** mvp
**Depends on**: Phase 3
**Requirements**: [INSERT-01, INSERT-02, REC-01, REC-02, REC-03]
**Success Criteria** (what must be TRUE):

  1. Final text is inserted into at least one supported Wayland text field through the clipboard-first adapter and the capability is reported.
  2. Unsupported or denied insertion leaves copy, retry, and save actions with the final text intact.
  3. History records raw/final text, status, provider, transformation settings, timestamps, and recovery metadata.
  4. Cancelling or retrying a job does not paste duplicate text, and temporary audio retention follows the configured policy.

**Plans**: 3 plans

Plans:

- [ ] 04-01: Implement clipboard-first insertion, portal/EIS or supported keyboard fallback, and focused-app capability reporting.
- [ ] 04-02: Add durable job history, audio retention, retry/cancel transitions, and idempotent insertion attempts.
- [ ] 04-03: Build status/history/recovery UI and host acceptance checks for GTK, browser, terminal, and XWayland cases.

### Phase 5: Private, Reproducible Desktop App

**Goal**: The personal Linux app is understandable, privacy-preserving, reproducible, and ready for daily use.
**Mode:** mvp
**Depends on**: Phase 4
**Requirements**: [PRIV-01, PRIV-02, CONFIG-01, BUILD-01]
**Success Criteria** (what must be TRUE):

  1. Local providers are the default, remote providers require explicit configuration, and the UI shows the current network/privacy policy.
  2. Diagnostics redact sensitive content and automated tests prove no model/network dependency is needed for the offline test command.
  3. Settings expose microphone, shortcut, language, style, provider, model, retention, and insertion behavior with validation and persistence.
  4. A clean Linux checkout can install pinned dependencies, run `make test` offline, and build the application without machine-specific absolute paths or secrets.
  5. The Ubuntu GNOME Wayland acceptance checklist passes or documents bounded known limitations and safe fallbacks.

**Plans**: 3 plans

Plans:

- [ ] 05-01: Finish settings, privacy/retention policy, redacted diagnostics, and configuration migrations.
- [ ] 05-02: Add packaging, `.python-version`, lockfile, Dockerfile, Makefile, README setup/run/test/deploy instructions.
- [ ] 05-03: Run full acceptance/regression review, update evidence and handoff docs, and prepare the first milestone release.

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Wayland Foundation | 3/3 | Complete    | 2026-10-16 |
| 2. Local Dictation Engine | 0/3 | Not started | - |
| 3. Writing Pipeline | 0/3 | Not started | - |
| 4. Insert and Recover | 0/3 | Not started | - |
| 5. Private, Reproducible Desktop App | 0/3 | Not started | - |

---
*Roadmap created: 2026-10-16*
