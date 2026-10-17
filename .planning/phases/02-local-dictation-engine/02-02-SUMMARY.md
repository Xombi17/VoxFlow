---
phase: 02-local-dictation-engine
plan: 02
subsystem: local-asr
tags: [python, pydantic, faster-whisper, offline, benchmarks, privacy]

# Dependency graph
requires:
  - 02-01
provides:
  - Typed Pydantic ASR input, segment, transcript, capability, cancellation, and provider configuration contracts.
  - Provider-independent checksum-bound dictation job runner with recoverable cancellation/failure snapshots.
  - Read-only installed-model discovery and lazy faster-whisper adapter with explicit local inference settings.
  - Allowlisted local benchmark records and target-host acceptance procedure.
affects: [02-03-remote-asr, phase-3-formatting, host-acceptance]

# Tech tracking
tech-stack:
  added: [pydantic==2.12.4, faster-whisper==1.2.1]
  patterns: [typed provider boundary, explicit installed model profile, lazy model load, local-only metrics]

key-decisions:
  - "The core imports only ASR contracts; faster-whisper is imported dynamically inside the local adapter after an installed profile is selected."
  - "A model profile checksum hashes relative file names, sizes, and bytes; serialized discovery metadata omits the model root."
  - "Provider results are validated and checksum-bound before a job can reach success; safe snapshots omit transcript text and local paths."
  - "Benchmark output is an allowlisted local schema with separate cold initialization, warm p50/p95, end-to-end, cancellation, realtime-factor, and peak-resource fields."

patterns-established:
  - "DictationJobRunner accepts any async ASRProvider and preserves the AudioArtifact reference across success, cancellation, and provider failure."
  - "LocalWhisperProvider passes language, VAD, beam, device, thread, and local-files-only settings explicitly and reuses one loaded model per profile instance."
  - "Offline tests use fake model modules/providers and never require model weights, sockets, a microphone, or a desktop session."

requirements-addressed: [AUDIO-02, AUDIO-04]
requirements-completed: []
requirements-pending: [AUDIO-02, AUDIO-04]

# Metrics
completed: 2026-10-17
---

# Phase 2 Plan 2: Local ASR Contracts, Provider, and Measurement Summary

## Accomplishments

- Pinned the runtime dependencies in `pyproject.toml` and updated `uv.lock`:
  `pydantic==2.12.4` and `faster-whisper==1.2.1`. Model weights remain outside
  the repository and are not fetched by startup, discovery, or tests.
- Added `src/voxflow/providers/asr.py` with strict immutable Pydantic models for
  `AudioInput`, `Segment`, `TranscriptResult`, `ProviderCapabilities`,
  `CancellationToken`, `ProviderConfigSnapshot`, and the async `ASRProvider`
  protocol. Segment bounds, confidence, identity, language metadata, and SHA-256
  identity are validated at the provider boundary.
- Added `src/voxflow/core/jobs.py` with `DictationJobRunner` and immutable
  `DictationJobSnapshot`. The runner owns provider dispatch, cancellation,
  checksum matching, terminal state, retry metadata, and safe serialization. It
  does not import `faster_whisper`, network clients, GTK, clipboard, or screen
  context.
- Added `src/voxflow/providers/local_whisper.py` with explicit read-only model
  discovery, deterministic profile checksums, typed unavailable results, lazy
  `faster_whisper` import/model construction, one-instance model reuse, explicit
  language/VAD/beam/device/thread settings, local-files-only loading, cooperative
  cancellation, and millisecond timestamp mapping.
- Added the ASR fixture manifest with stable IDs/checksums and categories for
  clean speech, restarts/self-corrections, names/numbers/technical terms,
  noisy/silent/boundary cases, language hints, cancellation, and provider
  failure. It contains no personal recordings or reference transcript text.
- Added `src/voxflow/evals/metrics.py` and `tools/asr_benchmark.py`. The local
  benchmark measures cold preparation, warm inference distributions, end-to-end
  job time, cancellation latency, realtime factor, and peak resource samples.
  Serialization is allowlisted to IDs, negotiated format, timings,
  distributions, status/error codes, and resource values.
- Added `02-HOST-ACCEPTANCE.md` with exact offline commands and redacted
  target-laptop gates for negotiated audio format, explicit installed-model
  discovery, cold/warm measurements, and model-profile promotion.

## Task commits

1. **Typed ASR contracts, dependencies, and provider-independent jobs** —
   `7c251cc` (`feat(02-02): add typed local ASR job contracts`)
2. **Installed-model discovery and lazy local Whisper adapter** — `75cc1d7`
   (`feat(02-02): add lazy local Whisper provider`)
3. **Local-only benchmark metrics, fixtures, and host acceptance** — `88b00ae`
   (`feat(02-02): add local ASR benchmarks`)

## Verification evidence

- `uv sync --dev` — completed; project environment installed the locked package
  set, including `pydantic==2.12.4` and `faster-whisper==1.2.1`. No model
  weights were installed.
- `PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python python -m pytest -q tests/unit/test_asr_contract.py tests/unit/test_jobs.py` — **10 passed**.
- `NETWORK_DISABLED=1 PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python python -m pytest -q tests/unit/test_local_whisper.py` — **7 passed**.
- `PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python python -m pytest -q tests/evals/test_asr_benchmark.py` — **3 passed**.
- Combined plan tests after the final adapter hardening change — **20 passed**.
- `NETWORK_DISABLED=1 make test` — **85 passed**.
- `make lint` — passed; the project lint target completed its compileall check.
- `uv lock --check --offline` — passed; the lock resolved **34 packages** with
  no lock changes required.
- `PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python python -m compileall -q src tests tools` — passed.
- `PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python python tools/asr_benchmark.py --help` — passed and displayed the explicit fixture/model input interface without importing a model backend.
- `git diff --check` — passed with no whitespace errors.

## Host acceptance status and limitations

- The deterministic offline acceptance path is complete and green. Tests use
  fake model/provider implementations and do not open sockets or create model
  weight files.
- A real local model benchmark was **not claimed** in this environment. No
  explicitly installed faster-whisper model profile/weights were available for
  the host acceptance run; the installed Python package is only the adapter
  dependency.
- A real microphone/negotiated PipeWire format was **not claimed**. The Phase 1
  host evidence recorded `sounddevice` as unavailable, so no live input device,
  permission, mute, disconnect, or recovery result was re-used as Phase 2
  evidence.
- Default model-profile promotion remains deferred until the target Ubuntu GNOME
  Wayland laptop supplies a redacted negotiated format and separate cold/warm
  benchmark results using an explicitly installed profile.
- No model weights, personal audio, transcripts, credentials, endpoint tokens,
  or unredacted machine paths were added to this plan's commits.

## Next phase readiness

- Phase 2 plan 3 can reuse `ASRProvider`, `TranscriptResult`,
  `DictationJobRunner`, and the cancellation/retry vocabulary for an explicit
  remote adapter without changing core lifecycle behavior.
- AUDIO-02 and AUDIO-04 still require the documented target-laptop evidence
  before a local model profile is promoted as the default.

---
*Phase: 02-local-dictation-engine*
*Plan: 02 completed: 2026-10-17*
