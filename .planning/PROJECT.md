# VoxFlow

## What This Is

VoxFlow is a Linux-first, local-first voice writing assistant for Ubuntu GNOME on Wayland. It lets one person hold a configurable shortcut, speak naturally, and receive cleaned, formatted text in the focused application through a safe Linux integration layer. It is inspired by the observable workflow of Wispr Flow, but it will be an original implementation with its own name, code, assets, and provider adapters.

## Core Value

The user's spoken thought should become useful text in the focused app with as little manual cleanup as possible, without requiring a subscription or a hosted account.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] User can start and stop push-to-talk dictation with a configurable global shortcut on Ubuntu GNOME Wayland.
- [ ] User receives accurate transcription from a local model, with an optional user-configured cloud provider.
- [ ] User receives polished text that removes filler, handles obvious self-corrections, adds punctuation, and preserves intended paragraphs and lists.
- [ ] User can insert the result into the focused application using a Wayland-compatible clipboard/paste path.
- [ ] User can configure language selection, app-aware writing styles, microphone, shortcut behavior, and local/cloud provider preference.
- [ ] User can manage dictionary words, corrections, snippets, recent transcripts, retryable failures, and privacy controls.
- [ ] User can run the core dictation flow without an account, paid plan, or vendor-specific licensing service.
- [ ] User can inspect failures and recover a transcript without losing captured audio when recovery is technically possible.

### Out of Scope

- Wispr Flow's proprietary code, models, branding, assets, protocols, or subscription controls — the project is clean-room and behaviorally compatible, not a copy or license bypass.
- Meeting Notetaker, speaker diarization, and meeting search in v1 — valuable but a separate product surface with different capture and storage risks.
- Mobile clients, team workspaces, billing, SSO, analytics, and hosted account sync in v1 — they are not needed to solve the Linux personal workflow.
- Silent screen scraping or arbitrary accessibility access by default — Wayland and privacy require explicit, least-privilege adapters.
- Shipping proprietary speech or language models — models must be open, locally installable, or explicitly configured by the user.

## Context

- The target behavior is Wispr Flow's desktop dictation core: speak into any text field, clean up speech while preserving intent, paste the result, and personalize output with languages, styles, dictionaries, and snippets.
- Public Wispr Flow material describes push-to-talk, hands-free mode, 100+ languages, app-category styles, dictionary/corrections, snippets, clipboard restoration, command mode, IDE context, and a separate Notetaker product. Public sources do not establish internal implementation details.
- The supplied Wispr Flow 1.6.1021 Windows installation contains an Electron ASAR. REA statically analyzed 228 selected application artifacts from the ASAR. Evidence ID and limitations are recorded in `.planning/research/REA-EVIDENCE.md`; raw evidence remains outside the repository.
- REA observed a large Electron boundary with 36 context-bridge API observations, 207 IPC operations, 10 literal IPC channels, 90 dynamic-channel operations, and 180 renderer transmissions. These are static observations, not proof of runtime reachability or enforcement.
- The first platform target is Ubuntu GNOME on Wayland. Global hooks, focused-text access, and paste behavior must be abstracted because Wayland intentionally limits cross-application control.

## Constraints

- **Platform**: Ubuntu GNOME on Wayland is the first supported environment — the Linux integration must work with the compositor rather than assuming X11 global injection.
- **Execution**: Local-first hybrid — the baseline must work offline with an open local speech model; cloud providers are opt-in adapters and cannot be required for core use.
- **Privacy**: Audio and transcripts stay local by default — network transmission must be explicit, observable, and configurable.
- **Reproducibility**: Pin the runtime and dependencies, keep a lockfile, provide a Dockerfile where practical, and expose one offline `make test` command.
- **Evidence**: REA facts are static and scope-limited — dynamic behavior must be validated with our own runtime tests and explicit user acceptance checks.
- **Legal/clean-room**: Use public behavior and authorized artifact observations only; do not reproduce proprietary source, assets, secrets, or protected service access.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Build an original alternative rather than an exact code replica | Preserves a useful compatibility target without copying proprietary implementation | — Pending |
| Target Ubuntu GNOME Wayland first | Matches the user's laptop and exposes the hardest integration constraints early | — Pending |
| Ship dictation core before Notetaker | Dictation solves the immediate Linux gap and keeps v1 coherent | — Pending |
| Use local-first hybrid providers | Removes pricing/account barriers while leaving room for better optional quality | Phase 2 implemented; target-host validation pending |
| Keep platform integration behind adapters | Wayland, XWayland, clipboard, portals, and accessibility have different capabilities | — Pending |
| Treat REA output as static evidence | The analyzer did not execute Wispr Flow and reported incomplete semantic coverage | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition**:
1. Requirements invalidated? Move to Out of Scope with reason.
2. Requirements validated? Move to Validated with phase reference.
3. New requirements emerged? Add to Active.
4. Decisions to log? Add to Key Decisions.
5. “What This Is” still accurate? Update if it drifted.

**After each milestone**:
1. Review every section.
2. Re-check the Core Value.
3. Audit Out of Scope reasons.
4. Update Context with current evidence and user feedback.

---
*Last updated: 2026-10-17 after Phase 2 close-out*
