---
phase: 02-local-dictation-engine
plan: 01
subsystem: audio
tags: [python, audio, pipewire, wav, checksum, cancellation, offline-tests]

# Dependency graph
requires:
  - phase: 01-wayland-foundation
    provides: negotiated AudioFormat, injectable AudioCapture lifecycle, stable audio failures, and sample-free events
provides:
  - Immutable callback-to-session PCM frame handoff with bounded retention.
  - Source-format PCM16 WAV artifacts with SHA-256 identity and safe metadata serialization.
  - Cooperative completed, cancelled, overflow, max-duration, and recoverable failed capture outcomes.
  - Non-personal deterministic audio fixture and checksum manifest for offline provider tests.
affects: [02-02-local-whisper, asr-providers, audio-recovery]

# Tech tracking
tech-stack:
  added: [Python stdlib wave, queue, threading]
  patterns: [non-blocking immutable callback handoff, atomic WAV artifact writes, bounded cooperative cleanup]

key-files:
  created:
    - src/voxflow/audio/__init__.py
    - src/voxflow/audio/artifacts.py
    - src/voxflow/audio/session.py
    - tests/unit/test_audio_artifacts.py
    - tests/unit/test_audio_session.py
    - tests/integration/test_audio_session.py
    - tests/fixtures/audio/short_utterance.wav
    - tests/fixtures/audio/manifest.json
  modified:
    - src/voxflow/platform/audio_devices.py
    - src/voxflow/platform/audio.py
    - src/voxflow/core/events.py
    - tests/unit/test_audio.py
    - pyproject.toml

key-decisions:
  - "Keep OpenedAudioStream.format authoritative and use PCM16 only as the concrete source artifact encoding; no 16 kHz mono assumption is introduced at the platform boundary."
  - "Copy callback memory into immutable bytes and perform queue draining, WAV writing, and cleanup outside the callback."
  - "Serialize only artifact identity and source metadata; artifact paths, samples, and backend paths are omitted or redacted from diagnostics/events."
  - "Use pytest importlib collection mode because this plan intentionally adds same-named unit and integration modules and its required combined command must collect both deterministically."

requirements-completed: [AUDIO-02]

# Metrics
duration: not measured (execution timestamps were not captured)
completed: 2026-10-17
---

# Phase 2 Plan 1: Bounded Audio Session and Artifacts Summary

**Negotiated-format audio capture with immutable frame handoff, bounded WAV artifacts, checksums, cooperative cancellation, and deterministic fake cleanup coverage**

## Performance

- **Duration:** Not measured; the execution start timestamp was not captured.
- **Started:** Not captured.
- **Completed:** 2026-10-17.
- **Tasks:** 3 completed.
- **Files modified:** 13 tracked files in the plan implementation, tests, fixture, and supporting collection/redaction changes.

## Accomplishments

- Extended the Phase 1 `AudioStream` seam with frame callback registration. The concrete `sounddevice` adapter requests PCM16 and copies backend-owned callback memory before handing immutable bytes and the negotiated frame count to the session; it does not write files, run inference, or emit sample-bearing events.
- Added `AudioSessionConfig` and `AudioSession` with explicit duration, frame, retention, and cleanup bounds. Terminal outcomes are typed as `completed`, `cancelled`, `overflow`, `max_duration`, or `failed`, with retry metadata and a recoverable artifact when policy and captured bytes allow it.
- Added atomic source-format WAV writing through `wave`, preserving negotiated sample rate/channel metadata and recording PCM encoding, frame count, duration, and SHA-256 over the exact written WAV bytes.
- Added a generated non-personal 48 kHz mono fixture with stable manifest ID, source/license note, repository-test permission, and checksum.
- Added unit and integration coverage for user stop, cancellation during delivery, empty cancellation, retention policy, duration clipping, buffer overflow, unsupported frame delivery, backend disconnect, close failure, call ordering, handle retention, and sample/path-free diagnostics.

## Task Commits

Each implementation task was committed atomically, with focused follow-up fixes:

1. **Task 1: Extend the Phase 1 audio seam with immutable frame handoff** - `6b3e755` (`feat`)
2. **Task 1 follow-up: Redact absolute audio event device paths** - `48a7a70` (`fix`)
3. **Task 2: Implement bounded capture and source-format WAV artifacts** - `5e8df75` (`feat`)
4. **Task 3: Prove cooperative cancellation and deterministic cleanup** - `f30c5cf` (`test`)
5. **Task 3 follow-up: Harden terminal handoff and callback registration compatibility** - `061ffbf` (`fix`)

**Plan metadata:** this summary is committed separately after verification.

## Files Created/Modified

- `src/voxflow/platform/audio_devices.py` - frame callback type and stream registration contract.
- `src/voxflow/platform/audio.py` - copied PCM16 `sounddevice` callback delivery and adapter alias.
- `src/voxflow/core/events.py` - absolute device-path redaction in serialized lifecycle events.
- `src/voxflow/audio/__init__.py` - public audio session/artifact exports.
- `src/voxflow/audio/artifacts.py` - atomic source-format WAV writer and checksum metadata.
- `src/voxflow/audio/session.py` - bounded async frame buffer, terminal outcomes, cancellation, retention, and cleanup.
- `tests/unit/test_audio.py` - immutable two-chunk handoff, adapter, and event-redaction coverage.
- `tests/unit/test_audio_artifacts.py` - WAV header, checksum, fixture manifest, and validation coverage.
- `tests/unit/test_audio_session.py` - bounded session, duration, cancellation, retention, unsupported stream, and cleanup coverage.
- `tests/integration/test_audio_session.py` - fake backend lifecycle, disconnect, overflow, duration, cancellation, and close-failure scenarios.
- `tests/fixtures/audio/short_utterance.wav` - deterministic 48 kHz mono PCM16 fixture.
- `tests/fixtures/audio/manifest.json` - stable non-personal fixture metadata and SHA-256.
- `pyproject.toml` - deterministic pytest `importlib` collection for same-named unit/integration modules.

## Verification Evidence

- `PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python python -m pytest -q tests/unit/test_audio.py` → **16 passed**.
- `PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python python -m pytest -q tests/unit/test_audio_artifacts.py tests/unit/test_audio_session.py` → **10 passed**.
- `NETWORK_DISABLED=1 PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python python -m pytest -q tests/integration/test_audio_session.py tests/unit/test_audio_session.py` → **11 passed**.
- `PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python python -m pytest -q tests/unit/test_audio.py tests/unit/test_audio_artifacts.py tests/unit/test_audio_session.py tests/integration/test_audio_session.py` → **30 passed**.
- `NETWORK_DISABLED=1 make test` → **65 passed**.
- `PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python python -m compileall -q src tests tools` → passed with no output/errors.
- `make lint` → passed; compileall completed without output/errors.
- `uv lock --check --offline` → passed; lock resolved 7 packages without network access.
- `git diff --check` → passed with no whitespace errors.

## Artifact and Cancellation Evidence

- The fixture manifest records SHA-256 `4dcd827fa00ad38a00930c3d6468c91f7d071a5debcdf4923a08d496a16fbefa` for `short_utterance.wav`; tests recompute the digest from the checked-in bytes.
- WAV tests verified 48,000 Hz, one channel, 16-bit PCM, 960 frames, and a stable checksum over the written file.
- Overflow retained two configured frames and returned `overflow`; max-duration clipping at a 1 ms limit retained 48 negotiated-format frames and returned `max_duration`.
- Empty cancellation returned `cancelled` with no artifact. Cancellation after frame delivery returned `cancelled` with a checksum artifact under the default retention policy; disabled retention returned no artifact.
- Close failure returned typed `failed` with `backend_unavailable`, retry metadata, the retained artifact reference, and the Phase 1 active-handle retry state. Fake call assertions showed `start → stop → close` with no duplicate close/start work.
- Serialized `AudioEvent`, session outcome, artifact, and fixture manifest data contain no raw audio bytes or absolute repository/home paths.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Redacted absolute device paths from lifecycle event serialization**
- **Found during:** Task 2 acceptance review.
- **Issue:** The existing `AudioEvent.to_dict()` preserved a backend device ID verbatim, which could be an absolute host path and violated the plan's diagnostic privacy criterion.
- **Fix:** Redacted absolute device IDs at serialization and added a regression assertion.
- **Files modified:** `src/voxflow/core/events.py`, `tests/unit/test_audio.py`.
- **Verification:** Audio unit suite and full plan suite passed.
- **Committed in:** `48a7a70`.

**2. [Rule 3 - Blocking] Enabled deterministic pytest collection for duplicate test module names**
- **Found during:** Task 3 required combined verification command.
- **Issue:** Pytest's default import mode raised an import mismatch between the required `tests/unit/test_audio_session.py` and `tests/integration/test_audio_session.py` modules.
- **Fix:** Added `--import-mode=importlib` to the existing pytest configuration so both plan-required modules collect without renaming them or changing runtime code.
- **Files modified:** `pyproject.toml`.
- **Verification:** The exact Task 3 command passed with 11 tests and the full suite passed with 65 tests.
- **Committed in:** `f30c5cf`.

**3. [Rule 1 - Bug] Hardened pre-run terminal requests and callback registration compatibility**
- **Found during:** post-task lifecycle review.
- **Issue:** A stop requested before the run task started could open the backend unnecessarily, and alternate replaceable fakes may expose `set_frame_callback` rather than the primary registration spelling.
- **Fix:** Finish pre-run terminal requests without opening capture and accept the explicit callback alias while retaining the primary contract.
- **Files modified:** `src/voxflow/audio/session.py`, `src/voxflow/platform/audio.py`.
- **Verification:** Targeted session/audio suites and the full plan suite passed.
- **Committed in:** `061ffbf`.

---

**Total deviations:** 3 auto-fixed (1 missing-critical privacy issue, 1 blocking verification configuration issue, 1 lifecycle bug/compatibility hardening). **Impact:** All fixes are directly required to satisfy the plan's privacy, deterministic verification, and terminal-lifecycle criteria; no provider or network scope was added.

## Issues Encountered

- The current host does not have the optional `sounddevice` package installed. No live microphone, PipeWire callback, real negotiated host format, permission flow, disconnect, or hardware recovery result was claimed. Offline fake streams and the checked-in fixture cover this plan's reproducible verification.
- No ASR library, model weights, network request, socket, or live desktop transport was used by the tests.

## User Setup Required

Live Ubuntu GNOME Wayland microphone validation is optional for this plan. To perform it later, install/configure the optional `sounddevice` host transport in the project environment and run the Phase 1 audio acceptance procedure. The offline test and fixture path requires no account, model download, network access, or personal recording.

## Next Phase Readiness

- Phase 2 Plan 02 can consume `AudioSessionOutcome.artifact`, `AudioArtifact.audio_sha256`, and `AudioArtifact.source_format` at the ASR boundary without assuming 16 kHz mono.
- The local model/provider work and live host microphone evidence remain outstanding; this plan supplies the bounded capture/artifact prerequisite rather than claiming end-to-end local transcription.

---
*Phase: 02-local-dictation-engine*
*Completed: 2026-10-17*
