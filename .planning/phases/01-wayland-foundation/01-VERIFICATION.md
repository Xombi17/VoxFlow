---
phase: 01-wayland-foundation
status: passed
score: "8/10"
verified_at: "2026-10-17"
evidence:
  - "All three Phase 1 plans and summaries, requirements, project/state/roadmap context, phase context/research, host-acceptance checklist, source, tests, Makefile, README, and lockfile were reviewed."
  - "The implementation provides pure state/capability contracts, injectable portal and audio adapters, safe opt-in probes, and deterministic fake coverage."
  - "The current host probe observed a Wayland session and returned structured unsupported results for the optional portal and audio transports."
automated_tests:
  status: passed
  test_count: 49
  commands:
    - command: "NETWORK_DISABLED=1 make test"
      result: "49 passed in 0.04s"
    - command: "make lint"
      result: "Passed; compileall produced no output or errors."
    - command: "uv lock --check --offline"
      result: "Passed; lock resolved 7 packages without network access."
    - command: "git diff --check"
      result: "Passed with no output."
    - command: "PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python python -m pytest -q tests/unit tests/integration"
      result: "49 passed in 0.04s"
host_validation:
  status: bounded
  observed:
    - "portal_probe.py --json detected XDG_SESSION_TYPE=wayland with Wayland display presence and returned session.wayland=available."
    - "The GlobalShortcuts probe returned shortcut.global=unsupported, code service_unavailable, version null, and no methods or signals."
    - "audio_probe.py --json returned audio.input=unsupported with code backend_unavailable; it reported no devices, no negotiated format, capture.active=false, capture.closed=true, and capture.started=false."
    - "The explicit combined diagnostic returned structured session, portal, and audio capability records without audio, transcript, clipboard, credential, or raw device data."
  limitations:
    - "The project environment has neither dbus_next nor sounddevice installed, so no live D-Bus binding or real microphone open was possible."
    - "No live portal permission dialog, shortcut binding, Activated/Deactivated observation, hold/release result, microphone permission denial, mute, disconnect, or hardware recovery result is claimed."
    - "The audio adapter does not expose system mute metadata; mute behavior remains covered by fakes and requires host audio-settings or PipeWire-native validation."
    - "The phase has no GTK/libadwaita UI yet. PLAT-03 is verified as a state contract and diagnostic vocabulary, not as a demonstrated user-visible status surface."
    - "The current opt-in diagnostic reports session, shortcut, and audio capabilities, but does not yet emit clipboard or paste capability records required by the full PLAT-01 wording."
  not_claimed:
    - "This report does not claim successful live GlobalShortcuts support, push-to-talk hold/release, microphone access, or end-to-end dictation."
    - "Offline fake tests are not substituted for Ubuntu GNOME host acceptance."
requirements:
  PLAT-01:
    planning_traceability: "REQUIREMENTS.md marks complete."
    verification: "Partial: session/shortcut/audio capability contracts and probes are evidenced; clipboard/paste capability records are not present in the current Phase 1 diagnostic."
    evidence: "src/voxflow/platform/session.py, src/voxflow/platform/portals.py, src/voxflow/platform/audio.py, tools/portal_probe.py, tools/audio_probe.py, and combined diagnostic output."
  PLAT-02:
    planning_traceability: "REQUIREMENTS.md records implemented; live portal validation pending."
    verification: "Implemented and fake-tested through the XDG GlobalShortcuts adapter; live bind/permission/signal validation remains pending."
    evidence: "src/voxflow/platform/shortcuts.py; tests/integration/test_shortcuts_fake.py; current portal probe returned a structured service_unavailable limitation."
  PLAT-03:
    planning_traceability: "REQUIREMENTS.md marks complete."
    verification: "The six-state contract and transitions are complete and tested; a user-visible UI status surface is not yet present."
    evidence: "src/voxflow/core/state.py; tests/unit/test_state.py; provider-free diagnostic state output."
  AUDIO-01:
    planning_traceability: "REQUIREMENTS.md records implemented; live host validation pending."
    verification: "Typed selection, negotiated format, actionable failure mapping, cleanup, and fake recovery paths are implemented and tested; real-device permission/mute/disconnect/recovery remains pending."
    evidence: "src/voxflow/platform/audio_devices.py, src/voxflow/platform/audio.py, tests/unit/test_audio.py, tests/integration/test_audio_probe.py, and HOST-ACCEPTANCE.md."
phase_success_criteria:
  - id: 1
    outcome: "BOUNDED PASS"
    statement: "The application identifies Wayland, X11, or unknown sessions and emits actionable portal/audio capability records. The implemented Phase 1 diagnostic does not yet include clipboard/paste records."
    evidence: "Session fakes, portal/audio probes, capability serialization tests, and current live probe output."
  - id: 2
    outcome: "BOUNDED PASS"
    statement: "Fake portal activation/deactivation produces listening-start/listening-stop events, and unavailable or activation-only paths report an explicit limitation and toggle fallback. Live bind and permission behavior were not tested."
    evidence: "tests/integration/test_shortcuts_fake.py; src/voxflow/platform/shortcuts.py; src/voxflow/__main__.py recommended-next-action path; HOST-ACCEPTANCE.md sections C and F."
  - id: 3
    outcome: "BOUNDED PASS"
    statement: "Fake audio backends cover selection, open/close, permission denial, missing device, mute, disconnect, format failure, cleanup failure, and retry/reopen behavior. No real microphone lifecycle can be claimed."
    evidence: "tests/unit/test_audio.py; tests/integration/test_audio_probe.py; src/voxflow/platform/audio.py; HOST-ACCEPTANCE.md sections D and E."
  - id: 4
    outcome: "PASS"
    statement: "Offline tests cover capability mapping, permission/error handling, and state transitions without a live desktop."
    evidence: "NETWORK_DISABLED=1 make test passed 49 tests; make lint and uv lock --check --offline also passed."
plan_must_have_audit:
  plan_01:
    truths:
      - id: "01-T1"
        result: pass
        statement: "A clean Python 3.12 environment can import VoxFlow and run the diagnostic without a live desktop."
        evidence: ".python-version, pyproject.toml, Makefile, and provider-free python -m voxflow --json output."
      - id: "01-T2"
        result: pass
        statement: "The state machine represents idle, listening, processing, success, cancelled, and failed with transition validation."
        evidence: "src/voxflow/core/state.py and tests/unit/test_state.py."
      - id: "01-T3"
        result: pass
        statement: "Capability values distinguish available, needs_user_action, and unsupported."
        evidence: "src/voxflow/core/capabilities.py and tests/unit/test_capabilities.py."
    artifacts:
      - id: "01-A1"
        result: pass
        statement: "Project metadata declares the pinned-compatible package and test/lint entry points."
        evidence: "pyproject.toml, uv.lock, .python-version, and Makefile."
      - id: "01-A2"
        result: pass
        statement: "The typed session/job state machine exists."
        evidence: "src/voxflow/core/state.py."
      - id: "01-A3"
        result: pass
        statement: "State and capability tests cover valid/invalid transitions and serialization."
        evidence: "tests/unit/test_state.py and tests/unit/test_capabilities.py."
      - id: "01-A4"
        result: pass
        statement: "Makefile exposes an offline test target."
        evidence: "Makefile test target uses uv --offline --no-sync and NETWORK_DISABLED=1."
    key_links:
      - id: "01-K1"
        result: pass
        statement: "The default entry point uses core contracts without invoking a concrete desktop provider."
        evidence: "Default diagnostic output has empty capabilities and idle state; optional transports are lazy and probes require explicit flags."
      - id: "01-K2"
        result: pass
        statement: "Tests exercise the same state/capability types used by the diagnostic."
        evidence: "tests/unit/test_state.py, tests/unit/test_capabilities.py, and src/voxflow/__main__.py."
  plan_02:
    truths:
      - id: "02-T1"
        result: pass
        statement: "Session type and portal availability are reported separately."
        evidence: "src/voxflow/platform/session.py, src/voxflow/platform/portals.py, and portal probe output."
      - id: "02-T2"
        result: pass
        statement: "The shortcut adapter uses org.freedesktop.portal.GlobalShortcuts rather than X11 hooks or unrestricted input reads."
        evidence: "GLOBAL_SHORTCUTS_INTERFACE in portals.py; no xdotool, pynput, /dev/input, or subprocess path in src."
      - id: "02-T3"
        result: pass
        statement: "Activated/Deactivated map to start/stop events and missing release semantics are reported."
        evidence: "src/voxflow/platform/shortcuts.py and fake activation-only/both-signal tests."
      - id: "02-T4"
        result: pass
        statement: "Portal permission/configuration requirements have user-facing reasons."
        evidence: "PortalFailure mapping and permission/binding-error assertions in portal and shortcut tests."
    artifacts:
      - id: "02-A1"
        result: pass
        statement: "Typed D-Bus portal client and error mapping exist."
        evidence: "src/voxflow/platform/portals.py."
      - id: "02-A2"
        result: pass
        statement: "GlobalShortcuts adapter and signal mapping exist."
        evidence: "src/voxflow/platform/shortcuts.py."
      - id: "02-A3"
        result: pass
        statement: "The portal probe emits safe JSON capability findings."
        evidence: "tools/portal_probe.py and current JSON result."
      - id: "02-A4"
        result: pass
        statement: "Portal success and unavailable paths are covered by unit/fake integration tests."
        evidence: "tests/unit/test_portals.py and tests/integration/test_shortcuts_fake.py."
    key_links:
      - id: "02-K1"
        result: pass
        statement: "Shortcut setup returns core-facing events instead of starting audio or calling UI/model code."
        evidence: "ShortcutEvent and GlobalShortcutsAdapter implementation."
      - id: "02-K2"
        result: pass
        statement: "Portal errors become needs_user_action or unsupported capability results."
        evidence: "map_portal_error, capability_for_failure, and error-path tests."
  plan_03:
    truths:
      - id: "03-T1"
        result: pass
        statement: "Input devices can be discovered and selected through typed contracts."
        evidence: "audio_devices.py, AudioDeviceDiscovery, and selection tests."
      - id: "03-T2"
        result: pass
        statement: "Missing, denied, disconnected, muted, unsupported-format, and unavailable conditions are actionable."
        evidence: "AudioErrorCode/map_audio_error and fake error tests."
      - id: "03-T3"
        result: pass
        statement: "Negotiated sample rate, channel count, and device identity are exposed."
        evidence: "AudioFormat, OpenedAudioStream, AudioEvent, and format assertions."
      - id: "03-T4"
        result: pass
        statement: "Offline tests do not open a real microphone or require PipeWire."
        evidence: "Injectable fakes, lazy SoundDeviceBackend import, and NETWORK_DISABLED=1 test run."
    artifacts:
      - id: "03-A1"
        result: pass
        statement: "Device discovery and selection models exist."
        evidence: "src/voxflow/platform/audio_devices.py."
      - id: "03-A2"
        result: pass
        statement: "Capture lifecycle and backend error mapping exist behind an injectable backend."
        evidence: "src/voxflow/platform/audio.py."
      - id: "03-A3"
        result: pass
        statement: "Audio probe emits safe JSON device/capability data."
        evidence: "tools/audio_probe.py, probe_audio, and sample-free integration assertions."
      - id: "03-A4"
        result: pass
        statement: "Host acceptance records live checks and bounded limitations."
        evidence: ".planning/phases/01-wayland-foundation/HOST-ACCEPTANCE.md."
    key_links:
      - id: "03-K1"
        result: pass
        statement: "Audio emits core events/capabilities without UI or ASR coupling."
        evidence: "AudioEvent and audio adapter imports; no model/UI imports."
      - id: "03-K2"
        result: pass
        statement: "Audio findings can be combined with session/portal findings."
        evidence: "src/voxflow/__main__.py --probe-audio/--probe-portals paths and combined diagnostic run."
source_and_scope_review:
  production_code_changed: false
  files_added_by_this_verification:
    - ".planning/phases/01-wayland-foundation/01-VERIFICATION.md"
  generated_untracked_files_not_staged:
    - "src/voxflow.egg-info/"
    - "src/voxflow/**/__pycache__/"
    - "tests/**/__pycache__/"
    - "tools/__pycache__/"
next_gate:
  - "Run HOST-ACCEPTANCE.md on the target Ubuntu GNOME Wayland desktop after installing/configuring dbus-next and sounddevice or an equivalent supported host transport."
  - "Add or wire clipboard/paste capability records before treating PLAT-01 as fully evidenced."
  - "Add the user-visible GTK/libadwaita status surface before treating PLAT-03 as fully user-accepted."
  - "Do not select a Phase 2 local ASR format/profile until negotiated host audio evidence is recorded."

# Verdict

Phase 1 passes as a platform-foundation milestone: the code has the required
pure contracts, adapter seams, safe diagnostics, fake failure coverage, and
offline reproducibility. The pass is bounded. It does not mean that the target
desktop has accepted a shortcut or microphone, and it does not close the
clipboard/paste or user-visible UI portions identified above.

The score is **8/10**: the automated foundation and all plan-level must-have
artifacts are evidenced, while live host behavior and two user-facing
traceability details remain open.
