# REA Evidence Ledger

**Target:** user-supplied Wispr Flow Windows installation, version 1.6.1021
**Artifact analyzed:** Electron `app.asar`
**Analysis date:** 2026-10-16
**Evidence ID:** `ev_d57a82d507c25605f34aff9db374e3fbe0ef694c6e34fae6d6288592a2695bff`
**Root artifact SHA-256:** `75a900edf6fdf68836f48c9de256c2060454bb6fc4ece077253758d884e8e5ed`

## Observations

- REA inventoried and parsed 228 selected application artifacts.
- The artifact contains an Electron/webpack application with main, renderer, preload, worker, HTML, and package manifest artifacts.
- Static analysis observed 36 context-bridge API observations.
- Static analysis observed 207 IPC operations, including 10 literal channels, 90 dynamic-channel operations, 180 renderer transmissions, and 27 renderer listeners.
- Static analysis observed 12 sender-validation observations.
- The analyzed archive contains native modules associated with SQLite and Windows cryptography, plus audio/Opus worker artifacts.
- Renderer artifact names include `hub`, `overlay`, `status`, `scratchpad`, `meeting_recorder`, `meeting_ax_inspector`, `contextMenu`, `accessibility_drop`, and `feature_tour`.

## Inferences useful for the clean-room design

- The shipped application is a multi-surface desktop client rather than a single transcription screen.
- The desktop client has a separated main/renderer boundary and uses IPC to coordinate UI and privileged operations.
- Audio processing is likely split across worker/native boundaries, but the exact runtime path is not established by this static analysis.
- Local history/state is plausible because SQLite is packaged, but the analysis does not prove which tables or user flows depend on it.
- The visible renderer surface includes more than dictation; Notetaker-related surfaces are present in this version, so they remain explicitly out of scope for the first VoxFlow milestone.

## Limitations and unknowns

- JavaScript and HTML were parsed as inert text; the application was not executed.
- Static imports, IPC, workers, endpoints, and storage relationships do not prove runtime reachability, defaults, or policy enforcement.
- The graph has incomplete semantic coverage because the analyzer hit resource limits on several large modules.
- Three unpacked native modules have integrity contradictions between declared and observed hashes. Their observed bytes are marked untrusted:
  - `.webpack/main/native_modules/build/Release/node_sqlite3.node`
  - `.webpack/main/native_modules/lib/crypt32-ia32.node`
  - `.webpack/main/native_modules/lib/crypt32-x64.node`
- No claim in this ledger establishes Wispr Flow's proprietary model, backend protocol, internal algorithm, or exact UI implementation.

## Use in this project

This ledger informs feature boundaries and compatibility hypotheses only. It must not be used to copy source, reconstruct proprietary service access, bypass licensing, or reproduce branding/assets. Runtime behavior for VoxFlow will be specified by public behavior, explicit user acceptance tests, and original implementation decisions.
