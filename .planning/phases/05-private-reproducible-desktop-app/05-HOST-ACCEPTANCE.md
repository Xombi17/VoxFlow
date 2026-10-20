# Phase 5 Host Acceptance

**Status: PENDING / NOT RUN**

This is a redacted, user-run acceptance matrix for the settings, privacy,
packaging, GTK, and Ubuntu GNOME Wayland boundaries. No live GTK, Wayland,
portal, microphone, EIS, focused-application, systemd-session, or model-host
check was run for this artifact. The automatic evidence is recorded separately
in `05-03-SUMMARY.md`; it does not fill any live row below.

## Evidence boundary and upstream dependency

The Phase 02.1 host artifact remains **PENDING / NOT RUN**. Its identity,
GlobalShortcuts, microphone, first-consent, insertion, terminal, restore-token,
and latency rows are not evidence for this phase until the user runs them on
the target host:

`.planning/phases/02.1-walking-skeleton-on-gnome-50/02.1-HOST-ACCEPTANCE.md`

The Phase 4 host artifact also remains **PENDING / NOT RUN**. Its insertion,
denial/unavailability, recovery, cancellation, duplicate-prevention, and
audio-retention rows are dependencies for the Phase 5 release decision:

`.planning/phases/04-insert-and-recover/04-HOST-ACCEPTANCE.md`

Offline tests, fake portal/audio tests, `insert-test` transport results,
Docker evidence, or a successful settings JSON command must not be promoted to
live GNOME evidence. Phase 5 cannot validate INSERT, SKEL, or REC requirements
without the corresponding Phase 02.1 and Phase 4 host rows.

## Redaction rules

Record only versions, opaque job/attempt IDs, status codes, counts, hashes,
coarse policy/provider classes, capability reasons, dialog counts, and timing
statistics. Do not attach or paste transcripts, raw/final text, audio,
clipboard bytes, restore tokens, credentials, database dumps, model paths,
artifact paths, screenshots containing user data, or absolute machine paths.
Keep intentional `recovery show`/`save` payloads private and record only exit
status and hash/length match flags.

## Host metadata

| Metadata | Evidence | Result |
|---|---|---|
| Date, operator alias, revision under test | User-run record | **PENDING / NOT RUN** |
| OS release, GNOME Shell/Mutter, Wayland session | About/session metadata | **PENDING / NOT RUN** |
| xdg-desktop-portal and active backend versions | Package/probe metadata | **PENDING / NOT RUN** |
| GlobalShortcuts, RemoteDesktop, Clipboard interface versions | Portal metadata | **PENDING / NOT RUN** |
| PipeWire, PortAudio, libei, libxkbcommon, Python versions | Package/runtime metadata | **PENDING / NOT RUN** |
| GTK4/libadwaita availability and display backend | Settings launch/import result | **PENDING / NOT RUN** |
| Text Editor, Firefox, terminal, and XWayland target versions | Application metadata | **PENDING / NOT RUN** |
| Installed/selected model ID and provider class | Redacted model listing | **PENDING / NOT RUN** |
| Microphone stable ID, language/style, cleanup and retention policy | Redacted settings view | **PENDING / NOT RUN** |
| Shortcut trigger and hold/toggle mode | Redacted settings/daemon status | **PENDING / NOT RUN** |

## User-run commands

Run these from the repository root on the target machine. Review output before
recording it; keep sensitive values private.

```bash
vf() {
  NETWORK_DISABLED=1 PYTHONPATH=src uv run --offline --no-sync \
    --python .venv/bin/python python -m voxflow "$@"
}

vf settings --json
vf models list --json
vf --json --probe-portals --probe-audio
vf install-identity
vf recovery --help
vf daemon
```

For the packaged path, use the user-local installation documented in
`README.md`, then launch `voxflow settings` from the desktop entry and manage
the user service. Do not record the resolved home directory or service data
paths.

## Settings and privacy matrix

Every row is a live host check and starts unexecuted. A headless automated test
or a JSON response from the current checkout does not change its disposition.

| ID | User action | Required redacted evidence | Dependency | Result |
|---|---|---|---|---|
| S1 | Launch `voxflow settings` and the desktop entry on the target session. | GTK/libadwaita launch status, app identity, and visible capability reasons. | GTK host | **PENDING / NOT RUN** |
| S2 | Edit microphone, shortcut trigger/mode, language, style, ASR provider/model, cleanup policy, retention, and insertion preferences through the settings surface. | Per-category validation status; no values or device paths. | S1 | **PENDING / NOT RUN** |
| S3 | Close/reopen settings and restart the user daemon after a settings change. | Persistence flags and daemon reload/restart status; no database path. | S2; Phase 4 host setup | **PENDING / NOT RUN** |
| S4 | Inspect the default policy and select a remote ASR or cleanup option only with explicit disclosure. | `local_only`/`remote_explicit`, provider class, disclosure state, and rejection code for missing consent. | S1; network remains disabled for local run | **PENDING / NOT RUN** |
| S5 | Run settings, diagnostic, model-list, daemon-status, and recovery-list output with canary data present privately. | Forbidden-content absence; record only status, counts, hashes, and stable codes. | S2; Phase 4 recovery host rows | **PENDING / NOT RUN** |
| S6 | Exercise the default `retain_audio=false` policy across successful, failed, and cancelled jobs. | Terminal state, retained/deleted/not-available state, and artifact-exists boolean only. | Phase 4 R8; live audio and insertion | **PENDING / NOT RUN** |
| S7 | Opt into audio retention for one disposable run, inspect the state, then restore the prior policy. | Opt-in state and retained-file boolean; no path or audio. | Phase 4 R9; live audio | **PENDING / NOT RUN** |
| S8 | Run the settings/headless fallback on a host without GTK4/libadwaita, if such a host is available. | Typed `gtk_unavailable`/equivalent result and usable redacted JSON path. | Headless host condition | **PENDING / NOT RUN** |
| S9 | Run explicit recovery `show`/`save` privately and verify redacted list output after restart. | Exit codes, file mode, hash/length match flags, and no text in normal output. | Phase 4 R5 | **PENDING / NOT RUN** |

## Packaging and deployment matrix

These rows validate the documented user installation shape on a clean Linux
checkout. They do not validate portal or focused-application behavior.

| ID | User action | Required redacted evidence | Dependency | Result |
|---|---|---|---|---|
| P1 | Create the pinned Python environment and run the documented frozen setup. | Python version, lock status, and setup exit status. | Clean checkout | **PENDING / NOT RUN** |
| P2 | Build and install the wheel with the documented user-local tool command. | Artifact names, install exit status, and launcher availability; no resolved paths. | P1 | **PENDING / NOT RUN** |
| P3 | Launch the installed desktop entry. | Settings window/typed capability result and desktop-entry identity. | P2; GTK host | **PENDING / NOT RUN** |
| P4 | Install, enable, restart, inspect, stop, and remove the user systemd unit. | User-service status/exit codes and no duplicate daemon observation. | P2; graphical user session | **PENDING / NOT RUN** |
| P5 | Confirm uninstall leaves history, settings, models, and restore state untouched until separately reviewed. | Redacted existence/permission flags and user confirmation. | P4; Phase 4 recovery rows | **PENDING / NOT RUN** |
| P6 | Re-run the offline test/build commands after installation. | Exit status and test count; no host behavior inferred. | P1/P2 | **PENDING / NOT RUN** |

## Ubuntu GNOME and upstream dependency matrix

| ID | User action | Required redacted evidence | Upstream artifact | Result |
|---|---|---|---|---|
| H1 | Run identity and capability probes in the target Wayland session. | App ID, capability states/reasons, consent/reuse booleans, and audio capability. | Phase 02.1 Identity; Phase 4 I1/I2 | **PENDING / NOT RUN** |
| H2 | Hold and release the configured shortcut while running the daemon. | Activated/deactivated semantics, capture state counts, and no duplicate triggers. | Phase 02.1 Trigger; Phase 4 I4 | **PENDING / NOT RUN** |
| H3 | Grant/deny microphone access and exercise missing, muted, or disconnected-device recovery. | Device capability/status codes and recovery action; no device path. | Phase 02.1; Phase 4 I4 | **PENDING / NOT RUN** |
| H4 | Approve first RemoteDesktop/Clipboard consent and record the permission indicator. | Dialog count, requested access class, and capability result. | Phase 02.1 Persistence; Phase 4 I2 | **PENDING / NOT RUN** |
| H5 | Exercise focused insertion in Text Editor and Firefox with repeated attempts. | 20/20 exactly-once counts, opaque IDs, transport/visible-once flags, and release-to-text p50/p95. | Phase 02.1 Insertion/Latency; Phase 4 I3/I4 | **PENDING / NOT RUN** |
| H6 | Record GNOME Terminal Ctrl+V/Ctrl+Shift+V and one confirmed XWayland target. | Target/backend metadata, chord outcomes, and bounded workaround. | Phase 02.1 Terminal; Phase 4 I5/I6 | **PENDING / NOT RUN** |
| H7 | Log out/in, redefine `vf`, and repeat probe/insertion with the same app identity. | Token permission flag, reuse boolean, dialog count, indicator lifecycle, and paste result. | Phase 02.1 Persistence; Phase 4 I7 | **PENDING / NOT RUN** |
| H8 | Arrange denied or insertion-unavailable conditions while capture/ASR remains usable. | Safe error code, retained job ID, recovery action availability, and no silent discard. | Phase 4 R1/R2 | **PENDING / NOT RUN** |
| H9 | Exercise pre-chord retry, ambiguous post-chord refusal, cancellation, and duplicate prevention. | Attempt linkage, side-effect phase, retryability, chord count, and final status. | Phase 4 R3/R4/R7 | **PENDING / NOT RUN** |
| H10 | Exercise default deletion and opt-in retention on the live daemon, including restart cleanup. | Terminal case, retention metadata, artifact-exists boolean, and recovery availability. | Phase 4 R8/R9 | **PENDING / NOT RUN** |

## Acceptance decision

| Decision | Result | Owner / next step |
|---|---|---|
| Phase 5 settings/privacy host acceptance | **PENDING / NOT RUN** | User runs S1–S9 and records redacted outcomes. |
| Phase 5 packaging/deployment host acceptance | **PENDING / NOT RUN** | User runs P1–P6 on a clean Linux checkout. |
| Phase 02.1 dependency gate | **PENDING / NOT RUN** | User completes `02.1-HOST-ACCEPTANCE.md` first. |
| Phase 4 dependency gate | **PENDING / NOT RUN** | User completes `04-HOST-ACCEPTANCE.md` and reconciles upstream rows. |
| Release readiness | **PENDING / NOT RUN** | Parent reconciles all three artifacts; no automatic result closes a live row. |

Host operator decision, accepted limitations, date, and redacted evidence
references: **PENDING / NOT RUN**.
