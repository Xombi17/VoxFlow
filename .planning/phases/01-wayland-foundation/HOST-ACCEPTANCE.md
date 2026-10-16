# Phase 1 Host Acceptance: Ubuntu GNOME Wayland

This checklist records the host evidence needed before Phase 2 chooses an
audio normalization or local model profile. It separates deterministic offline
checks from operations that require the target Ubuntu desktop session.

## Recording rules

- Run commands from the repository checkout with the project Python 3.12
  environment selected.
- The probes are read-only with respect to audio content: `audio_probe.py`
  enumerates devices and opens/closes a handle, but does not start capture.
- Do not commit raw probe output by default. If device names or IDs are
  sensitive, redact them before copying any result into this document.
- Do not paste audio, transcripts, clipboard contents, credentials, tokens, or
  absolute machine paths into this report.
- Record the exact command result as a short status/code/reason summary rather
  than committing the full JSON output.

## A. Offline automated evidence

Run without a live microphone, portal, model, or network connection:

```bash
NETWORK_DISABLED=1 make test
PYTHONPATH=src python3.12 -m compileall -q src tests tools
git diff --check
```

Expected evidence:

| Check | Result | Evidence / notes |
|---|---|---|
| Core capability and state tests | [ ] pass | `tests/unit/test_capabilities.py`, `tests/unit/test_state.py` |
| Portal fake tests | [ ] pass | `tests/unit/test_portals.py`, `tests/integration/test_shortcuts_fake.py` |
| Audio discovery/capture fake tests | [ ] pass | `tests/unit/test_audio.py` |
| Audio probe fake integration | [ ] pass | `tests/integration/test_audio_probe.py` |
| No whitespace errors | [ ] pass | `git diff --check` |
| No model/network dependency | [ ] pass | `NETWORK_DISABLED=1 make test` |

These checks are the evidence for Phase 1 success criterion 4: offline tests
cover capability mapping, permission/error handling, and state transitions
without a live desktop.

## B. Host metadata

Fill these fields on the target Ubuntu GNOME machine. Keep values concise and
redact device names/IDs when needed.

| Field | Recorded value |
|---|---|
| Ubuntu release (`lsb_release -ds`) | |
| GNOME Shell version (`gnome-shell --version`) | |
| Session type (`XDG_SESSION_TYPE`) | |
| Wayland display present | |
| X11 display present | |
| Desktop portal backend/version | |
| PipeWire version (`pipewire --version`) | |
| Audio backend package/version | |
| Acceptance date | |

Suggested non-invasive metadata commands:

```bash
lsb_release -ds
printf 'session=%s wayland_display_present=%s x11_display_present=%s\n' \
  "${XDG_SESSION_TYPE:-unset}" \
  "$([ -n "${WAYLAND_DISPLAY:-}" ] && printf true || printf false)" \
  "$([ -n "${DISPLAY:-}" ] && printf true || printf false)"
pipewire --version
```

For portal introspection, use the safe probe first. A direct introspection is
optional evidence when `gdbus` is installed:

```bash
PYTHONPATH=src python3.12 tools/portal_probe.py --json
gdbus introspect --session \
  --dest org.freedesktop.portal.Desktop \
  --object-path /org/freedesktop/portal/desktop
```

Inspect the `org.freedesktop.portal.GlobalShortcuts` interface in the returned
introspection. The JSON probe is the canonical redacted record.

| Host capability | Status (`available` / `needs_user_action` / `unsupported`) | Evidence code/reason |
|---|---|---|
| `session.wayland` | | |
| `shortcut.global` | | |
| `shortcut.hold` | | |
| `audio.input` | | |

## C. Shortcut binding and hold/release

Run the portal probe from the target session:

```bash
PYTHONPATH=src python3.12 tools/portal_probe.py --json
```

The probe only establishes interface availability and exposed signals. It does
not claim hold support. Use the configured VoxFlow shortcut integration or host
smoke surface to bind one trigger, then observe the portal signals while
pressing and releasing it:

```bash
  "type='signal',interface='org.freedesktop.portal.GlobalShortcuts'"
```

Record one result for each item:

| Check | Result | Evidence / notes |
|---|---|---|
| GlobalShortcuts version reported | [ ] pass / [ ] unavailable | Version: |
| Binding request displayed a user-consent/configuration path | [ ] pass / [ ] denied / [ ] not available | |
| `Activated` produced a listening-start event | [ ] pass | |
| `Deactivated` produced a listening-stop event | [ ] pass | |
| Hold/release support | [ ] supported / [ ] toggle-only / [ ] not tested | Both signals must be observed; no timing inference is accepted. |
| Permission denial was actionable | [ ] pass | Error code/reason: |

This is the evidence for Phase 1 success criterion 2. If only activation is
available, record `toggle-only` and the safe fallback; do not mark push-to-talk
hold/release as supported.

## D. Microphone enumeration and open/close

Run the safe audio probe from the target session:

```bash
PYTHONPATH=src python3.12 tools/audio_probe.py --json
```

Record only the redacted fields below. A successful probe must show a selected
input, negotiated sample rate/channel count, and `capture.closed=true` with
`capture.started=false`.

| Check | Result | Evidence / notes |
|---|---|---|
| At least one input device enumerated | [ ] pass / [ ] no device | Device name/ID (redacted): |
| Default/selected device identified | [ ] pass | |
| Open succeeded | [ ] pass / [ ] denied / [ ] unavailable | Error code/reason: |
| Negotiated sample rate | | Hz |
| Negotiated channel count | | |
| Handle closed deterministically | [ ] pass | `active=false`, `closed=true` |
| No audio data retained by probe | [ ] pass | `started=false` |

The open/close check is intentionally separate from recording. Phase 2 may add
bounded frame delivery, but it must consume this negotiated format explicitly
instead of assuming 16 kHz mono.

## E. Permission, mute, disconnect, and recovery

Perform these checks with a disposable or user-approved input device. Use the
desktop's normal privacy/audio settings where possible, then rerun the probe
after each change.

| Scenario | Action | Expected code/status | Result / evidence |
|---|---|---|---|
| Permission denied | Deny microphone access in the desktop permission flow, then probe | `permission_denied` / `needs_user_action` | |
| Muted input | Mute the selected source in GNOME audio settings, then probe | `muted` / `needs_user_action` | |
| Device missing | Disable or remove the selected input, then probe | `no_device` / `unsupported` | |
| Device disconnected | Unplug a USB/Bluetooth input during the host smoke test | `disconnected` / `needs_user_action` | |
| Recovery | Restore permission/device, refresh, select it, and probe again | `available`, then `closed=true` | |

These checks are the evidence for Phase 1 success criterion 3 and AUDIO-01.
The automated fake suite covers the same branches without opening hardware.

## F. Bounded limitations and outcome

Current repository-host observations (2026-10-16):

- The session probe previously detected Wayland, but the optional `dbus-next`
  transport was not installed, so GlobalShortcuts live binding, permission,
  and signal behavior remain unvalidated here.
- The audio probe returned `backend_unavailable` because `sounddevice` was not
  installed. No device, negotiated format, permission dialog, or disconnect
  recovery was claimed from that run.
- The offline suite uses fakes only and does not validate PipeWire, a real
  microphone, or an ASR/model provider.

Host-specific limitations to record after running the checklist:

```text
Portal limitation:
Audio backend limitation:
Permission limitation:
Hold/release outcome:
Safe fallback:
Phase 2 gate decision: [ ] ready for host-backed audio work  [ ] blocked pending host setup
```

## Acceptance outcome

| Phase 1 criterion | Evidence field / command | Outcome |
|---|---|---|
| Session and feature capabilities are actionable | Sections B–D; both JSON probes | [ ] pass / [ ] bounded limitation recorded |
| Shortcut binding and start/stop behavior is honest | Section C; fake shortcut tests | [ ] pass / [ ] toggle-only / [ ] pending host validation |
| Microphone select/open/error/recovery is deterministic | Sections D–E; `tests/unit/test_audio.py` | [ ] pass / [ ] bounded limitation recorded |
| Offline behavior is reproducible | Section A; `NETWORK_DISABLED=1 make test` | [ ] pass |
