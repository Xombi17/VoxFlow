# Phase 2: Local Dictation Engine - Context

**Gathered:** 2026-10-17
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver one bounded dictation path that captures a short utterance, produces a validated local transcript, and records local performance for the job. The same core lifecycle must accept an explicitly configured LAN or cloud ASR provider without changing its state or result contract. Cancellation, provider/model failures, and malformed results must leave a structured recoverable state. This phase does not implement text cleanup, insertion, durable history, or a user-facing settings surface.

</domain>

<spec_lock>
## Requirements (locked via AI-SPEC.md)

The Phase 2 AI-SPEC design contract is locked. Downstream agents MUST read `.planning/phases/02-local-dictation-engine/02-AI-SPEC.md` before planning or implementing.

**In scope:** bounded microphone input and local artifacts; a typed async ASR provider contract; an offline-capable local provider; optional LAN/cloud providers behind the same contract; validated transcript metadata; cooperative cancellation; recoverable failures; and local cold-start, warm-start, end-to-end, cancellation, and resource measurements.

**Out of scope:** automatic model downloads, network access in the local baseline or tests, hosted telemetry, screen/clipboard/application context, prompt-based cleanup, and unrelated agent, meeting, or collaboration capabilities.

</spec_lock>

<decisions>
## Implementation Decisions

### Bounded capture and audio artifacts
- **D-01:** Build on Phase 1 `AudioCapture` and `OpenedAudioStream`; consume the backend-negotiated `AudioFormat` and device identity rather than assuming 16 kHz mono at the platform boundary.
- **D-02:** Capture into a bounded frame buffer with an explicit maximum utterance duration. Overflow, maximum-duration, stop, and cancel paths must stop capture and produce a structured outcome instead of growing memory without a limit.
- **D-03:** Normalize audio only at the ASR input boundary. WAV fixtures and captured artifacts carry their sample-rate/channel metadata and an immutable identity/checksum; lifecycle events and diagnostics remain sample-free.
- **D-04:** Audio callbacks only hand off small immutable chunks. Model work runs outside the capture callback and outside the GTK/UI loop, with deterministic stop/close cleanup on every terminal path.

### Provider and job contract
- **D-05:** Define one typed async `ASRProvider` contract for local, LAN, and cloud implementations. Provider selection is a job configuration snapshot, and the core—not a provider or widget—owns session/job state transitions.
- **D-06:** Local transcription is the default and must work with network access disabled. A remote provider is dispatched only when explicitly configured with an observable network policy; it must not introduce a second lifecycle or UI contract.
- **D-07:** Provider results are validated once at the boundary and include transcript text, optional language/confidence metadata, timestamped segments, provider/model identity, and the input audio checksum. Malformed or mismatched results are rejected without silently coercing them.
- **D-08:** Cancellation is cooperative and bounded. Stop capture before inference where possible, reach `cancelled` or typed `failed` terminal state, retain a recoverable audio reference according to policy, and expose retry metadata rather than freezing or reporting success.

### Local model discovery and profile policy
- **D-09:** Implement the local Whisper candidate behind the provider interface, with `faster-whisper` as the initial candidate. Keep the application contract independent so a benchmark can select `whisper.cpp` or another compatible backend later.
- **D-10:** Use an explicitly selected installed model profile. Discovery reports model identity, location-independent metadata, checksum, supported language/device properties, and availability; startup and tests never download weights or silently fetch anything.
- **D-11:** Keep language hint, VAD/segmentation, beam size, device, and thread count explicit in the provider profile and job snapshot. VAD and maximum-duration segmentation must preserve timestamps for Phase 3 rather than discarding boundaries.
- **D-12:** Benchmark the candidate on the target laptop and negotiated host format before promoting a default profile. The repository may ship small deterministic fixtures, but model weights remain user-managed data outside Git.

### Local measurement and evaluation
- **D-13:** Record cold-start, warm-start, and end-to-end timings locally per provider/model profile, with stage boundaries and job identity but no audio or transcript content in metrics. Report warm latency distributions separately from cold initialization.
- **D-14:** Include cancellation latency, realtime factor, and peak resource samples in local benchmark output where the host can measure them. These are diagnostics for profile selection, not remote monitoring or a release-time network service.
- **D-15:** Keep the offline test path network-denied and model-download-free. Remote-provider behavior is covered by injectable mock/fake providers and contract tests; local inference tests use checked-in small fixtures or an explicitly installed model profile.
- **D-16:** Start the evaluation set with the AI-SPEC’s labeled fixture categories—clean utterances, restarts/self-corrections, names/numbers/technical terms, noisy or boundary cases, language hints, cancellation, and provider failures. Do not commit personal recordings; store references and checksums only.

### Claude's Discretion
The exact provider library versions, normalized PCM/WAV encoding details, benchmark report serialization, queue implementation, and target latency/resource thresholds remain implementation choices as long as the locked privacy, boundedness, validation, cancellation, and reproducibility decisions are preserved.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope and locked design
- `.planning/ROADMAP.md` §Phase 2 — goal, requirements, success criteria, and three planned work slices.
- `.planning/REQUIREMENTS.md` §Audio and Transcription — AUDIO-02, AUDIO-03, and AUDIO-04 acceptance requirements.
- `.planning/PROJECT.md` — local-first, privacy, Wayland, reproducibility, and clean-room constraints.
- `.planning/phases/02-local-dictation-engine/02-AI-SPEC.md` — locked AI-system classification, provider contract, guardrails, evaluation rubric, and offline policy.

### Phase 1 contracts and evidence
- `.planning/phases/01-wayland-foundation/01-CONTEXT.md` — adapter boundaries, state vocabulary, and local/offline decisions carried forward.
- `.planning/phases/01-wayland-foundation/01-01-SUMMARY.md` — Python 3.12 package, immutable state snapshots, capability records, and offline test harness.
- `.planning/phases/01-wayland-foundation/01-02-SUMMARY.md` — injectable adapter and lazy optional transport patterns.
- `.planning/phases/01-wayland-foundation/01-03-SUMMARY.md` — negotiated audio format, capture lifecycle, bounded configuration, and deterministic cleanup.
- `.planning/phases/01-wayland-foundation/01-VERIFICATION.md` — verified boundaries and the explicit warning not to choose an ASR format before host audio evidence.
- `.planning/phases/01-wayland-foundation/HOST-ACCEPTANCE.md` — host audio limitations and the required negotiated-format acceptance checks.

### Architecture and stack
- `.planning/research/ARCHITECTURE.md` — application-core, audio, provider, and event boundaries.
- `.planning/research/STACK.md` — Python, PipeWire-compatible audio, local ASR candidates, pinned dependencies, and offline test constraints.
- `.planning/STATE.md` — current Phase 2 position and unresolved target-hardware/model-profile concern.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/voxflow/platform/audio_devices.py`: `AudioFormat`, `AudioDevice`, `AudioBackend`, `OpenedAudioStream`, and async stream protocols already model negotiated input formats and replaceable host transports.
- `src/voxflow/platform/audio.py`: `AudioDeviceDiscovery`, `AudioCapture`, `AudioCaptureConfig`, stable `AudioErrorCode`/`AudioFailure` mapping, lazy `SoundDeviceBackend`, and deterministic close/error behavior are the Phase 2 capture seam.
- `src/voxflow/core/events.py`: immutable, sample-free `AudioEvent` records provide the safe lifecycle-event pattern for capture and future job/provider events.
- `src/voxflow/core/state.py`: `SessionStateMachine` and immutable snapshots already define idle/listening/processing/success/cancelled/failed transitions and failure context.
- `tests/unit/test_audio.py` and `tests/integration/test_audio_probe.py`: injectable fake-backend patterns cover lifecycle, format, error, and cleanup branches without a live microphone.

### Established Patterns
- Core contracts use Python 3.12 standard-library dataclasses, `StrEnum`, and `Protocol`; optional host libraries are lazy and absent from the offline baseline unless explicitly needed.
- Adapters are injectable and return typed capability/failure information. Raw backend exception text, device paths, and audio samples are not emitted by safe diagnostics.
- Async lifecycle operations validate state before mutation, preserve failed handles when cleanup is incomplete, and emit deterministic sample-free events.
- `Makefile` runs tests through the project-local Python/uv environment with `NETWORK_DISABLED=1`; new provider and fixture tests must preserve that offline path.

### Integration Points
- Add Phase 2 core/provider contracts beside `src/voxflow/core` and `src/voxflow/providers`, while keeping concrete model imports out of the core and UI entry point.
- Extend `AudioCapture` or an adjacent audio-session layer to consume frames from `OpenedAudioStream`, enforce bounded buffering, and hand a normalized artifact to the provider boundary.
- Keep local and remote providers behind the same job orchestration and result validation path; the existing `SessionStateMachine` is the observable state vocabulary until richer durable job state is introduced later.
- Preserve the provider-free default of `src/voxflow/__main__.py`; any benchmark or host/model probe must be explicit and safe, with local-only output.

</code_context>

<specifics>
## Specific Ideas

- The user should be able to capture a short utterance and receive a local transcript with measured performance even when the network is disabled.
- The local and explicitly selected remote paths should look identical to the core job lifecycle and UI contract; provider choice is a visible policy decision, not an implicit fallback.
- Phase 1’s negotiated sample rate and channel count are authoritative. Model normalization must adapt to that evidence instead of baking in a 16 kHz mono assumption.
- Timing and resource measurements belong on the local machine and must never become telemetry. Diagnostics may identify job/provider/model stages, but must not include audio, transcript, clipboard, credentials, or machine-specific paths.
- The provider receives only the current bounded audio segment and explicit language/model settings; no screen, clipboard, history, or unrelated application context is part of Phase 2.

</specifics>

<deferred>
## Deferred Ideas

- Text punctuation, filler removal, self-correction handling, paragraph/list formatting, dictionary rules, snippets, and writing styles — Phase 3.
- Durable SQLite job history, insertion, retry/copy/save UI, duplicate-paste prevention, and user-configurable audio retention — Phase 4.
- Full settings UX, privacy-policy controls, redacted diagnostic export, packaging, and final Ubuntu acceptance — Phase 5.
- Automatic model download/update/catalog management and hardware-specific profile installation — later product work; Phase 2 only discovers and uses explicitly installed profiles.
- Partial/continuous streaming transcription, always-on capture, speaker diarization, meeting notes, Command Mode, IDE context, mobile, sync, and team features — v2 or later.

</deferred>

---

*Phase: 02-local-dictation-engine*
*Context gathered: 2026-10-17*
