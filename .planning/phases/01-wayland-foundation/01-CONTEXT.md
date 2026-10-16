# Phase 1: Wayland Foundation — Context

**Gathered:** 2026-10-16
**Status:** Ready for planning
**Source:** Existing project decisions and GSD initialization

<domain>
## Phase Boundary

Prove the Ubuntu GNOME Wayland platform capabilities needed for dictation and establish the smallest testable application skeleton. This phase does not implement speech recognition, cleanup, history, or cloud providers.

</domain>

<decisions>
## Implementation Decisions

### Product boundary

- Build the dictation core first; Command Mode and Notetaker remain v2.
- The target environment is Ubuntu GNOME on Wayland.
- The baseline must not require an account, subscription, hosted model, or network connection.

### Platform policy

- Use XDG Desktop Portals and D-Bus as the first integration path.
- Do not make X11 hooks, `xdotool`, unrestricted `/dev/input`, or silent screen/accessibility scraping the default.
- Every platform operation must report available, needs-user-action, or unsupported with an actionable reason.
- If the target portal cannot provide reliable press/release semantics, record the limitation and expose a safe toggle or explicit fallback rather than pretending push-to-talk works.

### Reproducibility

- Use Python 3.12 with a project-local environment and lockfile.
- Keep offline unit tests independent of a live desktop session.
- Do not download model weights or call the network in Phase 1 tests.

### UI and state

- Use GTK4/libadwaita for the control/status surface.
- Implement a typed state machine with idle, listening, processing, success, cancelled, and failed states before adding providers.

### Claude's Discretion

- Exact Python package versions, provided they are pinned and compatible with Ubuntu GNOME.
- Whether the initial capability probe is a CLI subcommand, a small GTK diagnostic view, or both.
- Whether the first audio probe uses `sounddevice` or a direct PipeWire binding, provided the choice is documented and replaceable.

</decisions>

<canonical_refs>
## Canonical References

- `.planning/PROJECT.md` — product boundary, constraints, and clean-room rules.
- `.planning/ROADMAP.md` — Phase 1 goal, requirements, and success criteria.
- `.planning/REQUIREMENTS.md` — PLAT-01, PLAT-02, PLAT-03, AUDIO-01.
- `.planning/research/STACK.md` — recommended Python, GTK, PipeWire, portal, and test stack.
- `.planning/research/ARCHITECTURE.md` — capability-driven adapter and state-machine boundaries.
- `.planning/research/PITFALLS.md` — Wayland and portal failure modes.
- `.planning/research/SUMMARY.md` — research-derived roadmap ordering.

</canonical_refs>

<specifics>
## Specific Ideas

- The capability result should be useful to a user troubleshooting a laptop, not only to a developer reading logs.
- A live smoke test should make clear which permission dialog or desktop capability the user must approve.
- Platform adapters should be fakes in unit tests and real D-Bus/audio probes only in host acceptance tests.

</specifics>

<deferred>
## Deferred Ideas

- Local Whisper model loading and inference — Phase 2.
- Cleanup, dictionary, snippets, and styles — Phase 3.
- Clipboard insertion and history/retry UI — Phase 4.
- Command Mode, IDE context, Notetaker, mobile, sync, and team features — v2.

</deferred>

---
*Phase: 01-wayland-foundation*
*Context gathered: 2026-10-16*
