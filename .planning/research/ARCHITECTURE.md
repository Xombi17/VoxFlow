# Architecture Research

**Domain:** Linux desktop voice dictation
**Researched:** 2026-10-16
**Confidence:** MEDIUM; platform adapter details require a live Ubuntu GNOME validation

## Standard Architecture

```text
┌────────────────────────────────────────────────────────────────────┐
│                         GTK4 / libadwaita UI                       │
│  status surface · settings · history · dictionary · recovery       │
└───────────────┬──────────────────────────────┬─────────────────────┘
                │ typed commands/events          │ read-only state
┌───────────────▼──────────────────────────────▼─────────────────────┐
│                         Application Core                            │
│ session state · job lifecycle · policy · provider selection         │
└───────┬────────────┬───────────────┬───────────────┬────────────────┘
        │            │               │               │
┌───────▼─────┐ ┌────▼─────┐ ┌──────▼──────┐ ┌──────▼────────┐
│ Platform    │ │ Audio    │ │ Text        │ │ Persistence   │
│ adapters    │ │ pipeline │ │ pipeline    │ │ SQLite        │
│ shortcuts   │ │ PipeWire │ │ ASR/cleanup │ │ settings/jobs │
│ clipboard   │ │ capture  │ │ rules/style │ │ history       │
└─────────────┘ └──────────┘ └─────────────┘ └───────────────┘
        │            │               │               │
┌───────▼────────────▼───────────────▼───────────────▼────────────────┐
│                    Provider Interfaces                              │
│ local ASR · LAN/cloud ASR · deterministic cleanup · local LLM       │
└─────────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| Platform adapter | Start/stop events, permission checks, clipboard and paste capability | `dbus-next`, XDG portals, `wl-clipboard`, optional libei/wtype |
| Audio pipeline | Select mic, capture frames, VAD/segment, retain/release audio | PipeWire-compatible capture with bounded queues |
| ASR provider | Convert audio to timestamped transcript and language metadata | `faster-whisper` first; `whisper.cpp` or remote adapter later |
| Text pipeline | Normalize transcript, apply corrections/snippets, format, style | Pure functions plus provider interface for optional local/cloud cleanup |
| Persistence | Store settings, rules, jobs, history, and recovery metadata | SQLite migrations and explicit retention policy |
| Application core | Orchestrate state transitions and expose observable status | Async service layer with typed events |
| GTK UI | Configure, inspect, cancel, retry, and explain permission states | GTK4/libadwaita, no business logic in widgets |

## Recommended Project Structure

```text
src/voxflow/
├── app.py                 # application lifecycle and dependency wiring
├── core/
│   ├── events.py          # typed domain events
│   ├── state.py           # session/job state machine
│   └── policy.py          # privacy, retention, provider policy
├── platform/
│   ├── capabilities.py    # detect Wayland/portal/audio features
│   ├── shortcuts.py       # GlobalShortcuts adapter
│   ├── paste.py           # clipboard and input injection adapters
│   └── audio.py           # PipeWire capture adapter
├── providers/
│   ├── asr.py             # ASR protocol and metadata
│   ├── local_whisper.py   # local implementation
│   ├── remote_asr.py      # optional configured endpoint
│   └── cleanup.py         # deterministic and model-backed cleanup
├── text/
│   ├── normalize.py       # filler/correction/paragraph operations
│   ├── dictionary.py      # words and correction rules
│   ├── snippets.py        # spoken trigger expansion
│   └── styles.py          # Personal/Work/Email/Other profiles
├── storage/
│   ├── db.py              # connection and transactions
│   ├── migrations/        # numbered schema migrations
│   └── repositories.py    # persistence boundaries
└── ui/
    ├── window.py          # settings/history surface
    ├── status.py          # tray/status indicator
    └── models.py          # UI projections of core state
tests/
├── unit/
├── integration/
├── fixtures/
└── acceptance/
```

### Structure Rationale

- **`core/` owns behavior:** Platform and model implementations can change without changing user-visible state transitions.
- **`platform/` is capability-based:** Wayland support is not a boolean; each adapter reports what it can do and why it cannot.
- **`providers/` is explicit:** The application never reaches into a model library from the UI or text rules.
- **`text/` is deterministic:** User rules can be tested without model downloads or network access.
- **`storage/` is transactional:** Recovery and history require durable job state, not ad hoc JSON writes.

## Architectural Patterns

### Pattern 1: Capability-driven platform adapters

**What:** Each platform feature reports `available`, `needs_user_action`, or `unsupported`, with a human-readable reason and a testable operation.

**When to use:** Any shortcut, clipboard, focused-app, or permission feature.

**Trade-offs:** More code than assuming a desktop environment, but failures become explainable and future compositors can be added without rewriting the core.

### Pattern 2: Raw transcript plus final text

**What:** A dictation job stores immutable raw ASR output and a derived final output. User rules and cleanup are transformations with versioned metadata.

**When to use:** Every dictation.

**Trade-offs:** More storage, but it enables retry, comparison, debugging, and safer model changes.

### Pattern 3: Explicit async state machine

**What:** `idle → recording → transcribing → cleaning → inserting → complete` with cancellation and recoverable failure edges.

**When to use:** Any operation involving audio, model work, or external input.

**Trade-offs:** Requires disciplined event handling, but avoids duplicate pastes and stale UI state.

## Key Data Flows

1. **Push-to-talk:** Portal shortcut activation → core starts audio session → deactivation ends capture → ASR provider → cleanup/style/rules → insertion adapter → history record.
2. **Failure recovery:** Any stage emits a typed failure → job persists retained audio and stage metadata → UI presents retry/copy/save actions → retry resumes from the earliest safe stage.
3. **Configuration:** UI writes validated settings → core reloads provider/platform adapters → future jobs use the new snapshot; active jobs retain their original configuration.

## Integration Points

| Boundary | Communication | Notes |
|----------|---------------|-------|
| GTK UI ↔ core | In-process typed events/commands | UI must not call providers directly |
| Core ↔ platform | Async adapter protocols | Each operation returns capability/error details |
| Core ↔ ASR/cleanup | Provider protocols | Providers return structured results, not UI strings |
| Core ↔ SQLite | Repository methods and transactions | Persist state before notifying UI of completion |
| Core ↔ optional cloud | HTTPS client behind provider interface | Opt-in, redact logs, and expose endpoint/model settings |

## Anti-Patterns

### Hidden global hook assumption

**What people do:** Read `/dev/input` or use X11 tools without a permission and capability model.

**Why it is wrong:** It breaks under Wayland, requires elevated access, and can violate user expectations.

**Do this instead:** Try the portal first, document a user-granted fallback, and show the active adapter in settings.

### Model call inside UI callback

**What people do:** Run transcription or cleanup directly from a GTK event handler.

**Why it is wrong:** The UI freezes, cancellation becomes unreliable, and exceptions lose job state.

**Do this instead:** Put long work in bounded async tasks and publish state events.

## Sources

- XDG Global Shortcuts portal: https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.GlobalShortcuts.html
- XDG Remote Desktop portal: https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html
- PipeWire docs: https://pipewire.pages.freedesktop.org/pipewire/
- REA evidence ledger: `.planning/research/REA-EVIDENCE.md`

---
*Architecture research for: VoxFlow*
*Researched: 2026-10-16*
