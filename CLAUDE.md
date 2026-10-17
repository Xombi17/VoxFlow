<!-- GSD:project-start source:PROJECT.md -->
## Project

**VoxFlow**

VoxFlow is a Linux-first, local-first voice writing assistant for Ubuntu GNOME on Wayland. It lets one person hold a configurable shortcut, speak naturally, and receive cleaned, formatted text in the focused application through a safe Linux integration layer. It is inspired by the observable workflow of Wispr Flow, but it will be an original implementation with its own name, code, assets, and provider adapters.

**Core Value:** The user's spoken thought should become useful text in the focused app with as little manual cleanup as possible, without requiring a subscription or a hosted account.

### Constraints

- **Platform**: Ubuntu GNOME on Wayland is the first supported environment — the Linux integration must work with the compositor rather than assuming X11 global injection.
- **Execution**: Local-first hybrid — the baseline must work offline with an open local speech model; cloud providers are opt-in adapters and cannot be required for core use.
- **Privacy**: Audio and transcripts stay local by default — network transmission must be explicit, observable, and configurable.
- **Reproducibility**: Pin the runtime and dependencies, keep a lockfile, provide a Dockerfile where practical, and expose one offline `make test` command.
- **Evidence**: REA facts are static and scope-limited — dynamic behavior must be validated with our own runtime tests and explicit user acceptance checks.
- **Legal/clean-room**: Use public behavior and authorized artifact observations only; do not reproduce proprietary source, assets, secrets, or protected service access.
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

## Recommended Stack
### Core Technologies
| Technology | Version target | Purpose | Why Recommended |
|------------|----------------|---------|-----------------|
| Python | 3.12 | Desktop application and provider orchestration | Fast iteration for audio/ML integration; broad ASR ecosystem; easy offline test fixtures |
| GTK 4 + libadwaita | Ubuntu-supported stable versions | Settings, tray/status surface, permission and recovery UI | Native GNOME behavior and accessible controls without building a browser shell |
| PipeWire | Host-provided | Microphone graph and low-latency audio | Ubuntu's modern media layer; official docs describe graph processing and low-latency negotiation |
| D-Bus / XDG Desktop Portal | Host-provided | Global shortcuts, remote input, permissions | Wayland-compatible capability boundaries; user-visible grants instead of hidden global hooks |
| SQLite | Python stdlib `sqlite3` | Local settings, dictionary, snippets, history, jobs | Transactional, portable, no server, easy offline tests |
### Supporting Libraries
| Library | Version target | Purpose | When to Use |
|---------|----------------|---------|-------------|
| `dbus-next` | Current pinned release | Async portal and desktop D-Bus calls | Global shortcut and RemoteDesktop/clipboard adapters |
| `sounddevice` or PipeWire-native capture binding | Spike-dependent | Microphone frames | Use only after Phase 1 confirms device and format behavior |
| `faster-whisper` | Pinned release | Local ASR provider | CPU INT8 baseline or CUDA acceleration when available; PyAV avoids a mandatory system FFmpeg dependency |
| `pydantic` | Pinned release | Typed provider/job/settings contracts | Validate model responses and persisted settings |
| `pytest` | Pinned dev release | Unit/integration tests | Deterministic cleanup, rules, state transitions, and provider contract fixtures |
| `ruff` | Pinned dev release | Lint/format | Fast single-command hygiene for Python |
| XDG Clipboard portal (RemoteDesktop session) | Host-provided | Clipboard ownership without window focus | Primary insertion path on GNOME (Mutter lacks data-control, so `wl-clipboard` is unreliable there; Handy #1742) |
| libei via RemoteDesktop `ConnectToEIS` | Host `libei1` | Paste chord (Ctrl+V) injection | Primary on GNOME; `wtype` does NOT work on Mutter, `ydotool` needs root uinput |
| `sherpa-onnx` | Spike-dependent | Parakeet-TDT ASR provider candidate | Benchmark against faster-whisper in Phase 02.1 |
### Development Tools
| Tool | Purpose | Notes |
|------|---------|-------|
| `uv` | Python environment and lockfile | Prefer project-local `.venv` and `uv.lock`; do not install globally for the app |
| `pytest` | Offline test command | `make test` should run without model downloads or network calls |
| `dbus-monitor` / portal introspection | Platform debugging | Use during the integration spike; do not make tests depend on a live desktop session |
| Docker | Reproducible non-GUI build/test environment | GUI and Wayland acceptance tests remain host checks; unit tests must run in a container/offline |
## Installation Shape
## Alternatives Considered
| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| Python + GTK4 | Rust + GTK4 | Choose Rust if profiling shows Python orchestration or audio callbacks miss latency targets |
| `faster-whisper` | `whisper.cpp` | Choose `whisper.cpp` for a smaller native footprint, predictable CPU behavior, or a C ABI provider process |
| XDG portal GlobalShortcuts | GNOME Shell extension | Use an extension only if the target Ubuntu portal does not expose usable hold/release semantics |
| Clipboard + portal/EIS | X11 `xdotool` | Use X11 fallback only for XWayland sessions; it is not a Wayland solution |
| SQLite | JSON files | JSON is acceptable for export/import fixtures, not concurrent job/history state |
## What Not to Use
| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Mandatory cloud ASR/cleanup | Reintroduces cost, account, latency, and privacy barriers | Local provider plus optional adapters |
| `pynput` as the Wayland shortcut strategy | It does not solve compositor-mediated global input reliably | XDG portal GlobalShortcuts or an explicit GNOME integration |
| `xdotool` as the default paste path | It targets X11 and silently fails or is unsafe under Wayland | Clipboard plus portal/EIS or compositor-specific adapter |
| Unpinned model downloads in tests | Makes CI non-reproducible and requires network access | Small deterministic fixtures and mocked providers |
| Copying Wispr assets/source | Legal and maintenance risk | Original UI, names, code, and public behavior tests |
## Version Compatibility and Open Questions
- Confirm the user's Ubuntu release, GNOME version, portal backend, PipeWire version, and session capabilities before choosing the default shortcut adapter.
- Confirm whether the installed portal implements `org.freedesktop.portal.GlobalShortcuts` version 2 and whether activation/deactivation signals meet push-to-talk needs.
- Confirm whether RemoteDesktop/EIS can be granted persistently for keyboard paste without requiring screen capture.
- Benchmark `faster-whisper` CPU INT8 versus `whisper.cpp` on the user's hardware before locking the provider implementation.
## Sources
- PipeWire official docs: https://pipewire.pages.freedesktop.org/pipewire/
- XDG Desktop Portal Global Shortcuts: https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.GlobalShortcuts.html
- XDG Desktop Portal Remote Desktop: https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html
- `whisper.cpp` project and README: https://github.com/ggml-org/whisper.cpp
- `faster-whisper` project and README: https://github.com/SYSTRAN/faster-whisper
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
