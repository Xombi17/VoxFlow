# Project Research Summary

**Project:** VoxFlow
**Domain:** Linux desktop voice dictation and local-first voice writing
**Researched:** 2026-10-16
**Confidence:** MEDIUM overall; HIGH for public Wispr Flow behavior and Wayland constraints documented by portals

## Executive Summary

VoxFlow should be built as a capability-driven Linux desktop application, not as a browser wrapper or a hidden X11 automation script. The core value is an end-to-end dictation loop: start/stop capture, transcribe locally, transform speech into useful writing, and insert it into the focused application while preserving recovery paths.

The recommended first implementation is Python 3.12 with GTK4/libadwaita, SQLite, async D-Bus/portal adapters, PipeWire-compatible audio capture, and a local Whisper provider. Optional cloud or LAN providers must sit behind the same typed interfaces. The biggest uncertainty is not ASR; it is whether the target Ubuntu GNOME Wayland session exposes enough global shortcut and keyboard/clipboard capability for a polished push-to-talk experience.

## Key Findings

### Recommended Stack

Use Python for the first vertical slice, GTK4/libadwaita for native GNOME UI, PipeWire for audio, XDG portals for shortcuts/input permissions, SQLite for local state, and `faster-whisper` or `whisper.cpp` behind an ASR protocol. Resolve the final ASR engine only after a hardware benchmark.

### Expected Features

**Must have:** push-to-talk, microphone setup, local transcription, cleanup/punctuation, insertion, cancellation, history, retry, and privacy controls.

**Should have:** dictionary/corrections, snippets, explicit styles, provider selection, latency status, and app-category hints.

**Defer:** Command Mode, IDE recognition/file tagging, Notetaker, mobile, team sync, and enterprise controls.

### Architecture Approach

Keep the GTK UI, application state machine, platform adapters, audio pipeline, text pipeline, provider interfaces, and SQLite persistence separate. Each platform operation returns a capability result, each job stores raw and final text, and each stage has durable state so failures can be retried without duplicate insertion.

### Critical Pitfalls

1. **Wayland is not X11** — validate portals and insertion on the real Ubuntu GNOME session.
2. **Hold/release may not be portable** — probe GlobalShortcuts support and retain a toggle fallback.
3. **Large models can destroy UX** — benchmark cold/warm latency and CPU/GPU memory before choosing defaults.
4. **Cleanup can change meaning** — keep raw transcripts and constrain transformations with fixtures.
5. **Recovery is part of the product** — persist stage state and idempotent insertion attempts.

## Implications for Roadmap

### Phase 1: Platform Feasibility and Foundation
**Rationale:** Wayland capabilities determine whether the core user flow is possible.
**Delivers:** repository skeleton, capability probe, portal shortcut spike, clipboard/paste spike, audio-device probe, and test harness.
**Addresses:** platform, reproducibility, and permission constraints.
**Avoids:** building the application around unsupported X11 assumptions.

### Phase 2: Audio and Local Transcription
**Rationale:** Once the capture boundary is known, build the smallest real dictation loop and benchmark it.
**Delivers:** capture lifecycle, ASR provider contract, local model loading, VAD/segmentation, and latency metrics.
**Uses:** PipeWire and local Whisper stack.
**Implements:** audio pipeline and provider boundary.

### Phase 3: Text Transformation and Personalization
**Rationale:** Raw transcription is not the product outcome; useful writing is.
**Delivers:** cleanup, punctuation, corrections, styles, dictionary, snippets, language settings, and raw/final comparison.
**Uses:** deterministic rules first, optional model-backed cleanup second.
**Implements:** text pipeline and personalization storage.

### Phase 4: Insertion, History, and Recovery
**Rationale:** Cross-app insertion and failure recovery make the flow dependable rather than a demo.
**Delivers:** clipboard/paste adapters, job history, retry, cancellation, recovery UI, and idempotency safeguards.
**Uses:** platform capability results and SQLite job state.
**Implements:** persistence and insertion boundary.

### Phase 5: Settings, Privacy, Packaging, and Acceptance
**Rationale:** A personal desktop tool must be controllable, private, and reproducible.
**Delivers:** settings UI, provider controls, retention policy, offline test command, package/install path, Docker build/test path, and Ubuntu GNOME acceptance suite.
**Uses:** all previous components.
**Implements:** production hardening without expanding to Notetaker.

### Phase Ordering Rationale

- Platform feasibility comes before model work because a fast transcript that cannot be inserted is not useful.
- ASR precedes cleanup because cleanup needs a stable transcript contract and benchmark data.
- Personalization precedes recovery UX because history must store the exact transformation configuration.
- Packaging and privacy come after the vertical loop but before calling the tool usable.

## Research Flags

Phases needing deeper research during planning:
- **Phase 1:** Ubuntu GNOME portal backend support and hold/release semantics.
- **Phase 2:** Target-hardware ASR benchmark and model distribution/licensing.
- **Phase 4:** Wayland paste/input injection options and focused-app behavior.

Phases with standard patterns:
- **Phase 3:** deterministic text rules, SQLite migrations, and provider interfaces.
- **Phase 5:** Python packaging, tests, and reproducible build scaffolding.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | MEDIUM | Official platform/model docs checked; versions and local hardware still need validation |
| Features | HIGH | Public Wispr Flow pages and help articles provide observable behavior |
| Architecture | MEDIUM | Standard separation is clear; portal path remains environment-dependent |
| Pitfalls | HIGH | Wayland/portal limitations and public recovery behavior are documented |

**Overall confidence:** MEDIUM

### Gaps to Address

- Whether the user's Ubuntu portal backend supports a reliable push-to-talk hold/release lifecycle.
- Whether clipboard plus portal/EIS can paste into the user's primary applications without requiring broad permissions.
- Which local ASR model provides the right latency/quality balance on the user's CPU/GPU.
- Whether model-backed cleanup is needed for v1 or deterministic rules are sufficient for the first acceptance corpus.

## Sources

### Primary

- Wispr Flow public product and comparison pages — observable feature behavior.
- Wispr Flow Help Center — command mode, shortcuts, languages, styles, dictionary, IDE behavior, and recovery.
- XDG Desktop Portal Global Shortcuts — global shortcut session/binding/activation contract.
- XDG Desktop Portal Remote Desktop — user-granted keyboard input, clipboard integration, and EIS options.
- PipeWire official documentation — graph processing and low-latency audio framework.

### Secondary

- `whisper.cpp` README — offline Linux support, quantization, CPU/GPU options, VAD, and model sizes.
- `faster-whisper` README — CTranslate2 inference, CPU/GPU modes, VAD, and Python requirements.

### Artifact evidence

- `.planning/research/REA-EVIDENCE.md` — retained REA Evidence ID, digest, static Electron boundary observations, and limitations.

---
*Research completed: 2026-10-16*
*Ready for roadmap: yes*
