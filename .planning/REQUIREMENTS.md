# Requirements: VoxFlow

**Defined:** 2026-10-16
**Core Value:** The user's spoken thought should become useful text in the focused app with as little manual cleanup as possible, without requiring a subscription or a hosted account.

## v1 Requirements

Requirements for the first Ubuntu GNOME Wayland release. Each requirement maps to exactly one roadmap phase.

### Platform and Session

- [x] **PLAT-01**: The application reports whether it is running on Wayland, X11, or an unsupported session and lists the available shortcut, clipboard, paste, and audio capabilities.
- [ ] **PLAT-02**: The user can configure and bind a dictation shortcut through a supported Ubuntu GNOME integration without the application requiring an account or paid service.
- [x] **PLAT-03**: The user sees a clear idle, listening, processing, success, cancelled, or failed status while a dictation job is active.

### Audio and Transcription

- [ ] **AUDIO-01**: The user can select a microphone, grant/deny permission, and receive actionable feedback when the device is missing, disconnected, muted, or unavailable.
- [ ] **AUDIO-02**: The user can dictate without network access using an installed local speech-to-text model.
- [ ] **AUDIO-03**: The user can configure an optional LAN or cloud speech provider without changing the core dictation workflow.
- [ ] **AUDIO-04**: The application records measured cold-start, warm-start, and end-to-end transcription latency for local provider profiles without sending telemetry.

### Text Transformation and Personalization

- [ ] **TEXT-01**: The application transforms a raw transcript into readable text by applying punctuation, paragraph/list structure, filler cleanup, and obvious spoken self-correction handling.
- [ ] **TEXT-02**: The user can choose a language or language set and a writing style for at least Personal, Work, Email, and Other contexts.
- [ ] **TEXT-03**: The user can add, edit, remove, and test dictionary words and whole-word correction rules with deterministic precedence.
- [ ] **TEXT-04**: The user can define spoken snippets that expand to saved text without modifying the immutable raw transcript.
- [ ] **TEXT-05**: The user can choose deterministic cleanup or an explicitly configured local/LAN/cloud cleanup provider, with the selected policy stored per job.

### Insertion and Recovery

- [ ] **INSERT-01**: The application inserts final text into a supported focused text field using a Wayland-compatible clipboard-first path.
- [ ] **INSERT-02**: When direct insertion is unavailable, the application preserves the final text and offers copy, retry, or save actions instead of silently discarding it.
- [ ] **REC-01**: The application stores recent jobs with raw transcript, final text, timestamps, status, provider metadata, and transformation settings.
- [ ] **REC-02**: The user can cancel an active job and retry a recoverable failed job without creating duplicate insertion.
- [ ] **REC-03**: The user can configure whether captured audio is retained temporarily for recovery, and retained audio is deleted according to that policy.

### Privacy, Configuration, and Reproducibility

- [ ] **PRIV-01**: Local transcription and cleanup are the default; network access is off unless the user explicitly selects a remote provider.
- [ ] **PRIV-02**: Logs and diagnostics redact audio, transcript content, clipboard content, credentials, and provider tokens by default.
- [ ] **CONFIG-01**: The user can configure microphone, shortcut, language, style, provider, model, retention, and insertion behavior from the application settings.
- [ ] **BUILD-01**: A clean checkout can install the pinned runtime and dependencies, run an offline `make test` command, and build the application without absolute paths or secrets.

## v2 Requirements

Deferred until the v1 dictation loop is reliable.

### Commands and Developer Context

- **CMD-01**: User can hold a separate Command Mode shortcut and ask the application to edit selected text or draft a response.
- **IDE-01**: User can opt into visible IDE context and filename/file-tag recognition in supported editors.

### Notetaker and Collaboration

- **NOTE-01**: User can record meetings or voice memos, identify speakers, summarize topics, and extract next steps.
- **SYNC-01**: User can synchronize settings, dictionary entries, snippets, and history across devices through an optional self-hosted or hosted service.
- **TEAM-01**: User can share dictionaries and snippets with a team without making personal data public.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Wispr Flow source, assets, branding, proprietary models, or service protocol | Clean-room project boundary; implementation must be original |
| Subscription/account bypass | The project removes the dependency by using local/open providers, not by defeating another product's controls |
| Mobile clients | Not needed for the first Linux laptop outcome |
| Meeting Notetaker in v1 | Separate capture, consent, diarization, retention, and search problem |
| Enterprise billing, SSO, admin controls, and usage analytics | No value for the single-user v1 target |
| Always-on microphone | Privacy and consent risk; push-to-talk/hands-free sessions are sufficient |

## User Stories

- As a Linux user, I can hold a shortcut, speak naturally, release it, and receive useful text in the application I was already using.
- As a privacy-conscious user, I can dictate offline and see exactly when a remote provider is enabled.
- As a multilingual user, I can choose the language and style that apply to the next dictation.
- As a user with names and jargon, I can teach the application dictionary entries and corrections without retraining a model.
- As a user who hit an error, I can recover the transcript or retry without losing audio or pasting twice.

## Definition of Done

- The user-visible behavior is covered by automated unit/integration tests or an explicit Ubuntu GNOME acceptance check.
- The relevant provider and platform paths have deterministic failure handling.
- Offline tests run without downloading models, contacting remote providers, or reading private machine paths.
- Settings and data retention behavior are documented and tested.
- The implementation is committed with reproducible setup instructions and no secrets.

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| PLAT-01 | Phase 1 | Complete |
| PLAT-02 | Phase 1 | Implemented; live portal validation pending |
| PLAT-03 | Phase 1 | Complete |
| AUDIO-01 | Phase 1 | Implemented; live host validation pending |
| AUDIO-02 | Phase 2 | Pending |
| AUDIO-03 | Phase 2 | Pending |
| AUDIO-04 | Phase 2 | Pending |
| TEXT-01 | Phase 3 | Pending |
| TEXT-02 | Phase 3 | Pending |
| TEXT-03 | Phase 3 | Pending |
| TEXT-04 | Phase 3 | Pending |
| TEXT-05 | Phase 3 | Pending |
| INSERT-01 | Phase 4 | Pending |
| INSERT-02 | Phase 4 | Pending |
| REC-01 | Phase 4 | Pending |
| REC-02 | Phase 4 | Pending |
| REC-03 | Phase 4 | Pending |
| PRIV-01 | Phase 5 | Pending |
| PRIV-02 | Phase 5 | Pending |
| CONFIG-01 | Phase 5 | Pending |
| BUILD-01 | Phase 5 | Pending |

**Coverage:**
- v1 requirements: 21 total
- Mapped to phases: 21
- Unmapped: 0 ✓

---
*Requirements defined: 2026-10-16*
*Last updated: 2026-10-16 after initial GSD research and scope definition*
