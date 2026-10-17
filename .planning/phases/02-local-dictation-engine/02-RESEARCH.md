# Phase 2 Research: Local Dictation Engine

**Researched:** 2026-10-17
**Scope:** bounded audio capture, local Whisper transcription, optional remote ASR, and local-only measurements
**Confidence:** MEDIUM; the Phase 1 host report still lacks real microphone format and target-hardware evidence

## Research Summary

Phase 2 should extend the already-verified Phase 1 seams rather than replace them. `AudioCapture` owns device selection and backend lifecycle, `OpenedAudioStream.format` is the authoritative negotiated input format, `SessionStateMachine` provides the existing user-visible vocabulary, and optional host transports remain lazy. The new work belongs in adjacent `audio`, `core`, `providers`, and `evals` packages so the provider-free diagnostic and offline tests remain safe.

The roadmap's three slices are implementable as three dependent plans. The local provider must define the reusable provider/result contract before the remote adapter can implement it, so the remote plan depends on the local provider plan even though both use the same contract. No phase split is justified.

## Existing Codebase Findings

1. `src/voxflow/platform/audio_devices.py` exposes `AudioFormat`, `AudioDevice`, `AudioBackend`, `AudioStream`, and `OpenedAudioStream`; the stream protocol currently has lifecycle methods but no frame-delivery boundary.
2. `src/voxflow/platform/audio.py` has an injectable async `AudioCapture`, stable `AudioErrorCode` mapping, lazy `SoundDeviceBackend`, and a `max_buffer_frames` configuration value that is metadata only. The live backend currently discards callback frames.
3. `src/voxflow/core/events.py` deliberately emits sample-free `AudioEvent` records. Audio chunks must therefore remain inside the audio-session/artifact boundary and must never be added to lifecycle events or diagnostics.
4. `src/voxflow/core/state.py` provides validated `idle`, `listening`, `processing`, `success`, `cancelled`, and `failed` transitions. Phase 2 can add a serializable in-memory job record without changing the established state vocabulary or introducing SQLite before Phase 4.
5. Phase 1 fake tests establish the preferred pattern: injectable backends, stable typed failures, deterministic cleanup assertions, and no live PipeWire, D-Bus, model, or network dependency in `make test`.
6. `pyproject.toml` currently has no runtime dependencies and `uv.lock` resolves only the Phase 1 skeleton. Adding Pydantic and the selected local backend is a Phase 2 dependency change; model weights remain user-managed data outside Git.

## Locked Design Consequences

- Preserve every decision in `.planning/phases/02-local-dictation-engine/02-AI-SPEC.md`; it is authoritative over this research note.
- Consume the backend-negotiated sample rate and channel count. Do not make the platform boundary assume 16 kHz mono.
- Add a frame handoff that copies small immutable chunks out of the callback. Model work must run outside the callback and GTK loop.
- Enforce both a bounded buffer and an explicit maximum utterance duration. Overflow, stop, maximum-duration, and cancellation must all terminate deterministically and retain a recoverable artifact reference when policy allows.
- Normalize only at the ASR boundary. WAV artifacts preserve source format metadata and carry a stable SHA-256 identity.
- Validate provider results once at the boundary. Reject malformed fields or an `audio_sha256` mismatch; do not silently coerce or report success.
- Make local provider selection and model discovery explicit. Discovery may inspect configured installed profiles but must never download, update, or silently fetch weights.
- Keep language hint, VAD/segmentation, beam size, device, and thread count in the provider profile/job snapshot. Preserve segment timestamps for Phase 3.
- Treat remote access as an explicit network policy decision. The local default and all offline tests must remain network-denied.
- Record cold-start, warm-start, end-to-end, cancellation, realtime-factor, and resource metrics locally without transcript, audio, token, credential, or machine-path content.

## Recommended Plan Boundaries

### 02-01 — Bounded audio session and artifacts

Create an adjacent `src/voxflow/audio/` layer around the Phase 1 capture seam. Extend the replaceable stream boundary only enough to hand off immutable frames, implement a bounded async session, write source-format WAV artifacts with checksums, and test stop/cancel/overflow/cleanup with fakes. Keep the existing platform probe sample-free.

### 02-02 — Local Whisper provider and measurement

Create `src/voxflow/providers/asr.py` as the typed Pydantic contract, `src/voxflow/providers/local_whisper.py` as the lazy `faster-whisper` implementation, and `src/voxflow/core/jobs.py` as the provider-independent job runner. Add explicit installed-model discovery/checksum metadata, VAD/maximum-duration segmentation with timestamps, deterministic fake-provider tests, and a local benchmark/evaluation runner. Add a host acceptance document for the target laptop and negotiated audio format.

### 02-03 — Optional remote adapter and shared contract tests

Add explicit remote endpoint/network-policy configuration and an injectable HTTP transport in `src/voxflow/providers/remote_asr.py`. Reuse the Phase 2 job and result contract, reject remote dispatch under local-only policy, redact endpoint/auth details from diagnostics, and exercise the same lifecycle with offline fake responses. No network call belongs in the test suite.

## Validation Architecture

The primary automated gate is the existing project-local pytest command:

```bash
NETWORK_DISABLED=1 make test
```

Targeted checks should run after each plan task. The full suite should run after each wave. Provider tests use checked-in non-personal WAV fixtures, fake model/transport implementations, and a network-deny guard; live model inference is an explicit host acceptance command that requires an already-installed profile. Benchmark output is JSON containing only job/provider/model IDs, stage timings, distributions, cancellation latency, realtime factor, and resource samples.

Manual host evidence remains necessary for a real short utterance, PipeWire callback behavior, negotiated sample format, and target-laptop cold/warm performance. The host procedure must redact device names, absolute paths, audio, transcripts, credentials, and endpoint tokens before any result is committed.

## Risks and Mitigations

| Risk | Planning mitigation |
|------|---------------------|
| The `sounddevice` callback is synchronous and can block or retain mutable buffers | Copy small immutable chunks in the callback, enqueue through a bounded non-blocking handoff, and perform WAV/model work in an async worker |
| Phase 1 has no live audio format evidence | Preserve `OpenedAudioStream.format`, require a host acceptance gate, and keep normalization at the provider boundary |
| `faster-whisper` loads weights or initializes native resources slowly | Lazy-load one bounded warm model per explicit profile; record cold and warm stages separately; never download in startup/tests |
| VAD drops boundaries needed by later formatting | Keep source timestamps and emit timestamped segments after VAD/maximum-duration segmentation |
| A cancelled native inference continues consuming resources | Pass a cooperative token, stop capture first, bound the wait, record cancellation latency, and retain a recoverable job state |
| Remote configuration accidentally becomes a default network path | Require a remote provider selection plus explicit `remote_explicit` policy, validate endpoint schemes, and test the local-only rejection |
| Provider output is accepted with the wrong input identity | Validate `audio_sha256` against the immutable artifact before the job can reach success |

## Sources Consulted

- `.planning/phases/02-local-dictation-engine/02-AI-SPEC.md` — locked provider, guardrail, evaluation, and privacy contract.
- `.planning/phases/02-local-dictation-engine/02-CONTEXT.md` — Phase 2 boundary, decisions D-01 through D-16, and code context.
- `.planning/phases/01-wayland-foundation/01-CONTEXT.md` — adapter and offline-test decisions carried forward.
- `.planning/phases/01-wayland-foundation/01-01-SUMMARY.md` — Python/pytest/core state patterns.
- `.planning/phases/01-wayland-foundation/01-02-SUMMARY.md` — injectable lazy transport pattern.
- `.planning/phases/01-wayland-foundation/01-03-SUMMARY.md` — negotiated format, capture lifecycle, and cleanup contract.
- `.planning/phases/01-wayland-foundation/01-VERIFICATION.md` — bounded host evidence and Phase 2 gate.
- `.planning/phases/01-wayland-foundation/HOST-ACCEPTANCE.md` — required host format and microphone checks.
- `.planning/research/ARCHITECTURE.md` — application/core/audio/provider boundaries.
- `.planning/research/STACK.md` — Python, PipeWire-compatible audio, `faster-whisper`, Pydantic, uv, and offline test constraints.
- `.planning/research/PITFALLS.md` — model latency, callback, normalization, cancellation, and provider privacy pitfalls.
- `src/voxflow/platform/audio.py`, `src/voxflow/platform/audio_devices.py`, `src/voxflow/core/events.py`, `src/voxflow/core/state.py` — current implementation seams.
- `tests/unit/test_audio.py`, `tests/integration/test_audio_probe.py` — current fake backend and cleanup assertions.

---
*Research for: Phase 2 — Local Dictation Engine*
