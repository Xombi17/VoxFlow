---
phase: 01-wayland-foundation
plan: 03
subsystem: audio
tags: [python, audio, microphone, pipewire, diagnostics, offline-tests]

# Dependency graph
requires:
  - 01-01
  - 01-02
provides:
  - Injectable input-device discovery, selection, and negotiated-format contracts.
  - Async capture lifecycle with deterministic close cleanup and sample-free core events.
  - Stable actionable audio error/capability mapping for no-device, denied, disconnected, muted, unsupported-format, and unavailable-backend paths.
  - Safe audio JSON probe and explicit `--probe-audio` diagnostic integration.
  - Reproducible Phase 1 Ubuntu GNOME Wayland host-acceptance checklist.
affects: [02-local-dictation-engine, audio-adapters, host-acceptance]

# Tech tracking
tech-stack:
  added: [lazy optional sounddevice host adapter]
  patterns: [injectable audio backend, negotiated-format boundary, sample-free lifecycle events, deterministic async cleanup]

key-files:
  created:
    - src/voxflow/core/events.py
    - src/voxflow/platform/audio_devices.py
    - src/voxflow/platform/audio.py
    - tests/unit/test_audio.py
    - tests/integration/test_audio_probe.py
    - tools/audio_probe.py
    - .planning/phases/01-wayland-foundation/HOST-ACCEPTANCE.md
  modified:
    - src/voxflow/__main__.py

key-decisions:
  - "Keep sounddevice optional and lazy so offline tests do not install or import a host audio library, while leaving the live backend replaceable behind AudioBackend."
  - "Expose the backend-negotiated sample rate and channel count before Phase 2 chooses an ASR format; no 16 kHz mono assumption is made."
  - "The safe probe opens and closes a selected handle but never starts capture or serializes audio data; every cleanup path reports closed/active state."
  - "Map audio failures to stable codes and actionable capability statuses instead of leaking backend exception text or pretending hardware was validated."

patterns-established:
  - "AudioDeviceDiscovery selects an explicit device or the declared default and returns a typed capability result."
  - "AudioCapture emits AudioEvent lifecycle records with sequence, device, format, and error metadata only."
  - "Host probes are opt-in; the default diagnostic remains free of live D-Bus, audio, model, and network access."

requirements-addressed: [AUDIO-01]
requirements-completed: []
requirements-pending: [AUDIO-01]

# Metrics
completed: 2026-10-16
---

# Phase 1 Plan 3: Audio Foundation Summary

**Injectable microphone discovery/capture contracts, safe audio diagnostics,
offline fake coverage, and a bounded Ubuntu GNOME Wayland acceptance checklist**

## Plan Requirements

Copied from the plan frontmatter and acceptance scope:

- `requirements: [AUDIO-01]`
- **AUDIO-01:** The user can select a microphone, grant/deny permission, and receive actionable feedback when the device is missing, disconnected, muted, or unavailable.

AUDIO-01 is addressed by the typed device/capture boundary, stable error
mapping, safe probe, and offline fake coverage. It remains pending for the
live Ubuntu GNOME microphone permission, disconnect, mute, and recovery checks
listed in `HOST-ACCEPTANCE.md`.

## Accomplishments

- Added `AudioDevice`, `AudioFormat`, `AudioDeviceSelection`, `AudioBackend`,
  `AudioStream`, and `OpenedAudioStream` contracts with validation and explicit
  negotiated sample-rate/channel metadata.
- Added `AudioDeviceDiscovery` with default/explicit selection and typed
  capability results for available, missing, muted, and backend-failure paths.
- Added async `AudioCapture` lifecycle methods for open/start/stop/close,
  bounded configuration metadata, context-manager cleanup, and deterministic
  closure after disconnect/stop failures.
- Added stable `AudioErrorCode` values and actionable failure records for
  `no_device`, `permission_denied`, `disconnected`, `muted`,
  `unsupported_format`, and `backend_unavailable`.
- Added sample-free `AudioEvent` lifecycle records for opened, started,
  stopped, failed, and closed states. No event or diagnostic contains captured
  bytes.
- Added a lazy optional `SoundDeviceBackend` that opens a host input stream
  without making `sounddevice` an offline project dependency or retaining
  frames in the probe path.
- Added `tools/audio_probe.py --json` and explicit
  `python3.12 -m voxflow --json --probe-audio` wiring. The default diagnostic
  still does not contact an audio or desktop backend.
- Added fake unit/integration coverage for selection, no device, permission
  denial, mute, disconnect, unsupported format, open/start/stop/close, safe
  JSON, and cleanup after failures.
- Added a host acceptance checklist separating offline evidence from live
  Ubuntu GNOME checks and requiring redaction before any result is recorded.

## Task Commits

Each implementation task was committed atomically:

1. **Task 1: Define device discovery and capture contracts** - `f8ee51f` (`feat`)
2. **Task 2: Add safe host audio probe and diagnostic integration** - `f816896` (`feat`)
3. **Task 3: Record Phase 1 host acceptance and format findings** - `0739e69` (`docs`)
4. **Supplemental audio backend error normalization** - `0a39ee2` (`fix`)

**Plan metadata:** recorded in a separate metadata commit after verification.

## Files Created/Modified

- `src/voxflow/core/events.py` - sample-free typed audio lifecycle events.
- `src/voxflow/platform/audio_devices.py` - device, format, stream, and backend protocols.
- `src/voxflow/platform/audio.py` - error mapping, discovery, capture lifecycle, lazy host backend, and probe report.
- `src/voxflow/__main__.py` - explicit `--probe-audio` diagnostic integration.
- `tests/unit/test_audio.py` - deterministic fake backend/device/capture tests.
- `tests/integration/test_audio_probe.py` - safe probe and explicit diagnostic integration tests.
- `tools/audio_probe.py` - direct safe JSON host probe.
- `.planning/phases/01-wayland-foundation/HOST-ACCEPTANCE.md` - live acceptance checklist and current bounded limitations.

## Verification Evidence

- `PATH="/home/varad/.local/share/uv/python/cpython-3.12-linux-x86_64-gnu/bin:$PATH" PYTHONPATH="src:/usr/lib/python3/dist-packages" NETWORK_DISABLED=1 python3.12 -m pytest -q tests/unit/test_audio.py tests/integration/test_audio_probe.py tests/unit/test_capabilities.py`
  - `15 passed in 0.02s`
- `PATH="/home/varad/.local/share/uv/python/cpython-3.12-linux-x86_64-gnu/bin:$PATH" PYTHONPATH="src:/usr/lib/python3/dist-packages" NETWORK_DISABLED=1 make PYTHONPATH="src:/usr/lib/python3/dist-packages" test`
  - `31 passed in 0.03s`
- `PATH="/home/varad/.local/share/uv/python/cpython-3.12-linux-x86_64-gnu/bin:$PATH" PYTHONPATH="src:/usr/lib/python3/dist-packages" python3.12 -m compileall -q src tests tools`
  - Passed.
- `PATH="/home/varad/.local/share/uv/python/cpython-3.12-linux-x86_64-gnu/bin:$PATH" PYTHONPATH=src python3.12 tools/audio_probe.py --json`
  - Valid safe JSON. Current host reports `audio.input=unsupported` with
    `backend_unavailable`; `capture.active=false`, `capture.closed=true`, and
    `capture.started=false` because `sounddevice` is not installed.
- `PATH="/home/varad/.local/share/uv/python/cpython-3.12-linux-x86_64-gnu/bin:$PATH" PYTHONPATH=src python3.12 -m voxflow --json --probe-audio`
  - Valid JSON with the same explicit audio finding and no raw device paths or
    audio data.
- `git diff --check`
  - Passed with no whitespace errors.

## Host Limitations

- No real microphone was opened or recorded in tests. The current host's live
  audio probe could not enumerate or negotiate a device because the optional
  `sounddevice` library is not installed.
- The optional `sounddevice` adapter does not expose system mute metadata, so a
  muted-source result still requires the host audio settings check or a future
  PipeWire-native mute adapter.
- No live microphone permission denial, mute, disconnect, or recovery result
  can be claimed from this environment. These checks are explicit in the host
  acceptance document and remain required before Phase 2 selects a model/input
  profile.
- The previous portal probe evidence remains bounded by the missing optional
  `dbus-next` transport; live GlobalShortcuts binding and hold/release are also
  still pending host validation.

## Deviations from Plan

- No plan behavior was changed. The live host checks could not be completed due
  to missing optional host transports; the probe returned structured limitation
  results as designed.
- The plan's requested `sounddevice`/PipeWire choice is represented as a lazy
  optional `sounddevice` adapter. It is not added to the locked offline runtime
  dependencies.

## User Setup Required

- For live validation, provide an Ubuntu GNOME Wayland session with an input
  microphone and install/configure the optional `sounddevice` host transport.
- For shortcut validation, provide the optional `dbus-next` transport and run
  the portal binding/activation checklist from the target desktop session.
- No account, model download, network request, credential, or real audio
  recording is required for the offline tests.

## Next Phase Readiness

- Phase 2 can consume `OpenedAudioStream.format` instead of assuming a sample
  rate or channel layout, and can add bounded frame delivery behind the same
  `AudioBackend` boundary.
- AUDIO-01 remains pending live host evidence for permission, mute,
  disconnect, and recovery behavior.
- No ASR/model import, model download, network call, X11 hook, unrestricted
  input read, or captured audio fixture was added.

---
*Phase: 01-wayland-foundation*
*Completed: 2026-10-16*
