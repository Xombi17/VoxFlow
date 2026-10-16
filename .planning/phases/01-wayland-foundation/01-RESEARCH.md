# Phase 1 Research: Ubuntu GNOME Wayland Foundation

**Researched:** 2026-10-16
**Scope:** platform capability validation and application foundation
**Confidence:** MEDIUM until the user's live Ubuntu session is probed

## Findings

1. **Global shortcut path:** XDG Desktop Portal GlobalShortcuts version 2 defines sessions, shortcut binding, `Activated`, `Deactivated`, and `ShortcutsChanged`. This is the correct first path for compositor-mediated global shortcuts. The local backend/version must be queried; documentation alone does not prove the user's environment supports it.
2. **Keyboard/paste path:** XDG RemoteDesktop version 2 can request keyboard control with a user-visible portal flow and can connect to EIS or use D-Bus key notifications. The application must request only the device capability needed, avoid screen capture, and report when persistence is unavailable.
3. **Audio path:** PipeWire provides the host graph and negotiation layer. The first probe must enumerate devices, sample rate, channels, and permission/connection errors rather than assuming 16 kHz mono input.
4. **State boundary:** The app should have a pure state machine and fake adapters before live D-Bus/GTK integration. This keeps offline tests deterministic and makes compositor failures diagnosable.
5. **Packaging boundary:** Python 3.12, GTK4/libadwaita, and async D-Bus are suitable for a first vertical slice. Exact package versions and system dependencies must be pinned after the host probe.

## Probe Checklist

- `echo "$XDG_SESSION_TYPE"` reports `wayland` for the target session.
- `gdbus introspect` or equivalent confirms `org.freedesktop.portal.GlobalShortcuts` and reports its interface version.
- A test binding receives activation and deactivation events, or the probe records the backend limitation.
- PipeWire/Pulse-compatible device enumeration returns at least one input device with negotiated format metadata.
- A denied permission path returns a typed, user-facing reason.
- No probe writes credentials, audio, or transcripts outside the configured diagnostic location.

## Design Consequences

- The phase must not hide unsupported features behind a green “ready” state.
- Capability results should be serializable so they can appear in CLI/GTK diagnostics and be covered by fixture tests.
- Hold/release is a requirement to validate, not an assumption. If only toggle behavior works, the result belongs in the acceptance report and roadmap risk log.
- Live host checks must be separate from `make test`; CI cannot depend on a GNOME session.

## Sources

- XDG Global Shortcuts: https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.GlobalShortcuts.html
- XDG Remote Desktop: https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html
- PipeWire docs: https://pipewire.pages.freedesktop.org/pipewire/
- `.planning/research/STACK.md`
- `.planning/research/ARCHITECTURE.md`
- `.planning/research/PITFALLS.md`

---
*Research for: Phase 1 — Wayland Foundation*
