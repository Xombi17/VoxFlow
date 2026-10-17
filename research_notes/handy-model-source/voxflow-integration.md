# Handy and VoxFlow model integration

Snapshot used for the Handy comparison: `cjpais/Handy` `main` at commit
`9e57a0d7929fcc6417ea0d6e54c1b57f62635edd` (2026-10-15). The requested deep-
research `researcher.md` was available at the synced skill path and was read
before source inspection. No Handy code or VoxFlow source was copied or
modified.

## Handy public architecture and user flow

### Product flow

Handy's documented core loop is: press a configurable shortcut, hold/release or
toggle recording, speak, release, run local VAD/transcription, then paste the
result into the focused text field. Its README lists Whisper Small/Medium/
Turbo/Large and Parakeet V3 as local model choices and says the app works on
Linux, macOS, and Windows.

- [Handy README: How It Works and local models](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/README.md#how-it-works)
- [Handy README: Quick Start](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/README.md#quick-start)

In the source, a shortcut event is routed through a coordinator that applies
toggle, push-to-talk, or hold-or-toggle activation. `TranscribeAction::start`
starts model/VAD preparation in background work, checks that a model path is
available, changes tray/overlay state, then starts capture. Stop retrieves the
samples, finalizes live or batch transcription, saves a WAV/history entry when
enabled, optionally post-processes, and pastes on the main thread. Failures are
shown as events/toasts and failed history entries can retain the recording for
retry.

- [shortcut/handler.rs](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/shortcut/handler.rs)
- [actions.rs: recording start/stop](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/actions.rs#L388-L814)
- [managers/audio.rs: capture manager](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/managers/audio.rs#L448-L889)

### Runtime architecture

Handy is a Tauri 2 application with a React/TypeScript frontend and a Rust
backend. Audio capture uses `handy-recorder`; VAD can use bundled Silero; the
backend uses `transcribe-cpp` for GGML/GGUF models. The Cargo manifest selects
native backends by target (Vulkan/dynamic backends on Linux and Windows x64,
Metal on macOS) and includes the native input/clipboard and model-management
dependencies.

- [Cargo manifest](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/Cargo.toml)
- [README acknowledgement of Whisper, ggml, Silero, and Tauri](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/README.md#acknowledgments)

Native inference is isolated in a child worker. The parent `EngineSupervisor`
starts a worker, sends framed JSON requests plus little-endian f32 PCM, and
receives loaded-model, transcript, streaming-update, and error responses. The
worker alone initializes native backends, loads a model, runs batch/streaming
inference, and exits on parent disappearance. This is a deliberate crash/hang
boundary for GPU/native failures; the supervisor can retry with a CPU-only
worker. The worker loads a model path with `transcribe_cpp::Model::load_with`,
reads capabilities, then runs `Session`/`Stream` operations.

- [engine_supervisor module](https://github.com/cjpais/Handy/tree/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/engine_supervisor)
- [engine protocol](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/engine_supervisor/protocol.rs)
- [worker model load and run](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/engine_supervisor/worker.rs#L255-L320)
- [transcription manager](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/managers/transcription.rs#L496-L663)

### Model family, format, discovery, and storage

The important interoperability fact is that Handy's Whisper-family model
artifacts are not CTranslate2 directories. The current source accepts legacy
single-file Whisper GGML `.bin` files and GGUF `.gguf` files through
`transcribe-cpp`; its model README documents filenames such as
`ggml-small.bin`, `whisper-medium-q4_1.bin`, and `ggml-large-v3-turbo.bin`.
Parakeet and other architectures are also represented in the catalog, so
"same model family" should mean Whisper first, not the whole Handy catalog.

Handy has a richer model registry than VoxFlow Phase 2:

1. `ModelManager` stores user models under the app data `models` directory.
   Portable builds use `Data/models`; normal builds use the Tauri app-data
   location. The manager creates this directory at startup.
2. A compiled catalog describes recommended models, names, language/capability
   metadata, quant files, revisions, sizes, and SHA-256 hashes. Current catalog
   entries are mostly pinned Hugging Face GGUF models; older URL-backed `.bin`
   entries remain runnable but are treated as legacy in onboarding.
3. The manager scans the local models directory for top-level `.bin` and `.gguf`
   files and scans the Hugging Face cache for compatible GGUF snapshots. A
   lightweight GGUF header probe reads metadata without loading tensor data.
   Unknown custom `.bin` files are surfaced with capabilities left unknown and
   reconciled after the native model loads.
4. Downloads are explicit UI actions. They support progress, cancellation,
   resumable partial files, pinned revisions, SHA-256 verification, a shared HF
   cache, and static mirror fallback. Completion is emitted as an event only
   after verification.
5. Model selection is persisted. Switching can eagerly load the model or defer
   loading according to the unload setting; an idle watcher can unload the
   worker to return memory to the OS. A settings rescan discovers files added
   outside the app.

- [ModelInfo, sources, catalog normalization, and manager](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/managers/model.rs)
- [Local `.bin`/`.gguf` discovery](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/managers/model.rs#L1239-L1394)
- [HF-cache discovery](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/managers/model.rs#L1396-L1551)
- [GGUF capability probe](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/managers/model_capabilities.rs)
- [Catalog and pinned hashes/revisions](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/catalog/mod.rs)
- [Resumable download and verification](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/managers/model/download.rs)
- [Handy README: manual model installation](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/README.md#manual-model-installation-for-proxy-users-or-network-restrictions)

### CLI and UI flow

The Tauri frontend initializes a model store, loads the catalog/status, listens
for progress/verification/completion/failure/deletion events, and exposes:

- first-run onboarding with existing local models plus featured downloads;
- a model dropdown containing downloaded models;
- a Models settings page with search, language/streaming/translation filters,
  rescan, download/cancel/delete, and active-model switching;
- loading/unloaded/error state events and a tray model menu.

The CLI is intentionally useful both as a remote-control surface and a
headless test surface. It supports toggle/cancel flags plus `--transcribe-file`,
`--model`, `--device-index`, `--list-devices`, `--list-models`, `--repeat`, and
`--json`. The headless path requires an installed model and does not download
one.

- [React model store](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src/stores/modelStore.ts)
- [Onboarding model flow](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src/components/onboarding/Onboarding.tsx)
- [Models settings](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src/components/settings/models/ModelsSettings.tsx)
- [Model Tauri commands](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/commands/models.rs)
- [CLI flags](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/cli.rs)

### Wayland behavior that is useful as evidence, not as a drop-in design

Handy documents limited Wayland support. On Linux it recommends `wtype`,
`dotool`, or `ydotool` for input, but also documents that `wtype` does not work
on GNOME/Mutter and that Ubuntu 26.04 needs a configured `ydotool` service. Its
GNOME shortcut instructions use a desktop custom shortcut that launches
`handy --toggle-transcription`, and Linux also has a SIGUSR2 toggle path. Its
clipboard path prefers `wl-copy`, then sends a simulated paste chord through a
tool/fallback chain. The recording overlay is disabled by default on Linux
because it can take focus and break paste-back.

- [Handy README: Linux notes and Wayland limitations](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/README.md#linux-notes)
- [Handy clipboard/tool fallback](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/clipboard.rs)
- [Handy Linux input caveat](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/input.rs#L169-L178)

## VoxFlow Phase 2 comparison

### What already maps cleanly

VoxFlow already has the right backend-independent seam for adding another local
engine. `ASRProvider` accepts an immutable `AudioInput` and cancellation token;
`TranscriptResult` carries language/confidence, timestamped segments, provider
and model IDs, and the input SHA-256; `DictationJobRunner` validates the result
once and preserves recoverable artifact/config/retry state. A new local backend
should implement this contract rather than adding a second job lifecycle.

- `src/voxflow/providers/asr.py:61-260`
- `src/voxflow/core/jobs.py:95-260`

The capture side also should remain unchanged for this integration. `AudioSession`
uses the negotiated `OpenedAudioStream.format`, bounds duration/memory, writes a
source-format WAV artifact, and handles stop/cancel/overflow/max-duration and
cleanup failures with typed outcomes. This is intentionally different from a
model-specific 16 kHz capture assumption.

- `src/voxflow/audio/session.py:62-120,227-289,317-480`
- `.planning/phases/02-local-dictation-engine/02-01-PLAN.md:24-42,100-128`

### What is currently incompatible

`src/voxflow/providers/local_whisper.py` is specifically a lazy
`faster-whisper`/CTranslate2 adapter. A usable profile must be a directory with
`config.json` and `model.bin`; discovery computes a deterministic directory
checksum and reports portable metadata, but never downloads or creates files.
The provider passes the directory to `faster_whisper.WhisperModel` with
`local_files_only=True`, explicit device/compute/thread settings, and maps the
library's segments into VoxFlow milliseconds.

- `src/voxflow/providers/local_whisper.py:27-167,192-367`
- `tests/unit/test_local_whisper.py:77-199`

Therefore a Handy `ggml-small.bin` or `*.gguf` file cannot be pointed at the
current `model_root`: it is the wrong shape and backend. This is an artifact
compatibility issue, not evidence that the upstream Whisper model family is
unsupported. VoxFlow can already run a Whisper-family model when it is supplied
in the CTranslate2 format expected by `faster-whisper`; it cannot run Handy's
native single-file artifacts without a second backend.

### Phase 2 scope and current user flow

Phase 2 has no GTK model UI and no model downloader. The only model-facing
operator flow is an explicit benchmark command:

```text
tools/asr_benchmark.py --fixture <WAV> --model-root <installed directory> \
  --model-id <portable ID> --runs N --json
```

`voxflow --json` is a provider-free/platform diagnostic, and
`tools/provider_probe.py` validates local/remote provider policy. The Phase 2
acceptance document explicitly treats weights as host-managed inputs and
prohibits automatic downloads, model weights, personal audio, transcripts,
credentials, and absolute paths in evidence.

- `tools/asr_benchmark.py:20-59`
- `src/voxflow/__main__.py:19-143`
- `tools/provider_probe.py:1-107`
- `.planning/phases/02-local-dictation-engine/02-HOST-ACCEPTANCE.md:1-17,86-145`
- `.planning/phases/02-local-dictation-engine/02-VERIFICATION.md:12-18,53-87`

The current Phase 2 implementation is therefore a good contract foundation,
not a Handy-like end-user model flow. The later settings/UI work should consume
model profiles through the provider contract instead of making the UI import
`faster_whisper` or a native backend.

### Observed verification during this review

The current checkout passed `NETWORK_DISABLED=1 make test` with **115 passed in
0.18s**, `make lint`, and `uv lock --check --offline`. The benchmark help
command exposes only the current `faster-whisper` directory/profile interface.
These results confirm the safe baseline; they do not provide real Handy-format
model or live Ubuntu GNOME acceptance evidence. Existing Phase 2 documents say
the live microphone transport and an installed real model are still absent.

## Smallest safe next step and boundaries

### Recommendation

Add one opt-in `local-whisper-cpp` vertical slice for **a single explicit
Whisper-family GGUF model**. Do not replace `LocalWhisperProvider`, add Parakeet,
copy Handy's catalog, or build the full model-download UI in this step.

The first action should be a short host spike that proves the chosen native
helper can load one Handy-compatible Whisper GGUF (and, separately, whether
legacy GGML `.bin` is required), accept the negotiated WAV, emit stable JSON
segments/language, and stop promptly. Handy uses `transcribe-cpp`, but VoxFlow
should not link to Handy source or its private runtime; use an independently
version-pinned project-local/native helper boundary, preferably a subprocess
with no shell invocation. If the helper cannot provide stable segment JSON or
bounded cancellation, stop at the spike and keep the current backend.

### Adapter changes in the bounded slice

1. Add a separate `WhisperCppModelProfile`/discovery path. Keep the current
   CTranslate2 directory path intact. For the new path, recognize only explicit
   top-level `.gguf` (and later `.bin`) files, ignore hidden/partial files and
   directories, compute file SHA-256 plus size, and report `backend`, `format`,
   `model_id`, language capability (`unknown` when the file does not expose it),
   and availability without mutating the directory.
2. Add `WhisperCppProvider(ASRProvider)` with provider ID
   `local-whisper-cpp`. It should receive only `AudioInput` and the frozen
   selection snapshot, convert the source-format artifact to the helper's
   required mono/16 kHz PCM at the provider boundary if needed, pass explicit
   language/VAD options, parse timestamped JSON, and return the existing
   `TranscriptResult` with the original artifact checksum. Do not put resampling
   or native work in `AudioSession`'s callback or in GTK.
3. Start with a short-lived helper process for correctness and crash isolation.
   Treat process startup as cold latency. A persistent warm worker can be a
   follow-up only if target-host measurements show that process startup breaks
   the local latency budget; Handy's worker-supervisor design is useful evidence
   for that follow-up, not a reason to add a large supervisor now.
4. Extend `LocalModelProfile` only as a compatibility-neutral model metadata
   contract, or introduce a small sibling profile type. Do not make
   `REQUIRED_MODEL_FILES = ("config.json", "model.bin")` global to all local
   backends.

### Discovery and storage flow

For this step, model bytes remain user-managed and no download is added. Keep
the existing explicit `--model-root` convention for deterministic Phase 2
acceptance. A later application model registry can default to
`$XDG_DATA_HOME/voxflow/models` (or `~/.local/share/voxflow/models`) and expose
an explicit “scan/add existing model” action. It should store only portable
profile ID, backend/format, checksum, and user-approved metadata; it should not
silently reuse Handy's app-data directory or shared HF cache.

If a downloader is added later, copy only the safety properties worth keeping:
explicit user action, pinned URL/revision, expected byte size/hash, resumable
`.partial` file, cancellation, verification, and atomic rename. Do not make
network download the first-run requirement or the offline test setup.

### CLI and future UI flow

The smallest CLI change is to extend the benchmark/probe interface with an
explicit backend and file form, for example:

```text
asr_benchmark.py --backend whisper-cpp --model-file <file.gguf> \
  --model-id whisper-small-gguf --fixture <WAV> --json
```

The existing CTranslate2 flags remain valid. The safe JSON schema should expose
only backend/model IDs, format, checksum, negotiated audio format, timings,
status/error codes, and resource measurements. Add `--backend`/`--model-file`
tests before adding any GUI.

When the GTK/settings surface arrives, present both backends in one model list
with badges for backend/format/availability and an explicit scan/add action.
Selecting a model should persist a provider/model snapshot and the next job
should use the same `DictationJobRunner`; switching settings must not mutate an
active job. A download card may be added later as an explicit, observable
network action. Do not copy Handy's download-first onboarding or auto-select-
the-first-downloaded-model behavior as VoxFlow's local-first default.

### Tests and acceptance additions

- Discovery tests for valid GGUF, unsupported/unknown header, legacy `.bin`,
  hidden/partial/directory entries, stable checksum, missing file, and
  read-only behavior; safe serialization must contain no absolute path.
- Fake helper tests for explicit invocation arguments, language/VAD settings,
  JSON segment mapping, malformed output, process failure, checksum binding,
  cancellation/termination, and no shell/network/download behavior.
- Reuse the existing provider-contract scenarios so local CTranslate2 and
  `local-whisper-cpp` have identical success, invalid-result, provider-failure,
  cancellation, and retry semantics.
- Benchmark/probe tests must verify the new backend is selectable without
  loading native code and that output contains no audio, transcript text,
  credentials, tokens, or machine path.
- Add one host-only acceptance row requiring one explicit GGUF file, negotiated
  capture format, fixture transcription, and separate cold/warm or
  process-start/inference timing. Keep it separate from `make test`.

### Behaviors not to copy

- Do not copy Handy's direct desktop custom-shortcut/signal strategy as VoxFlow's
  Wayland integration. VoxFlow already has a compositor-mediated XDG
  GlobalShortcuts adapter with typed Activated/Deactivated capability checks in
  `src/voxflow/platform/portals.py` and `src/voxflow/platform/shortcuts.py`.
- Do not make `wtype`, `dotool`, `ydotool`, `xdotool`, or Enigo the default
  insertion mechanism. Handy's own README documents GNOME/Mutter limitations and
  the need for machine-specific ydotool setup. VoxFlow's planned clipboard-first
  insertion must retain a recovery path when compositor-compatible input is not
  available.
- Do not copy Handy branding, icons, UI composition, catalog descriptions,
  model score claims, source URLs, or its proprietary-looking product behavior.
  The project boundary is clean-room and original.
- Do not copy automatic network downloads, shared-cache assumptions, or a
  first-run model download requirement. VoxFlow's local model is installed and
  selected explicitly; network use is opt-in.
- Do not copy always-on microphone behavior or focus-stealing recording overlays.
  VoxFlow's scope is push-to-talk/explicit sessions, and Wayland focus changes
  are particularly risky for paste-back.

### Bottom line

The smallest safe next step is an isolated, opt-in `local-whisper-cpp` adapter
for one explicit GGUF Whisper model, preceded by a host helper spike. It reuses
VoxFlow's existing audio artifact, ASR validation, cancellation, job, benchmark,
and privacy boundaries while leaving `faster-whisper` as the default. Discovery
and CLI support should come before GTK, and explicit local storage should come
before any download catalog. Handy's strongest reusable ideas are a portable
model profile, pre-load capability probing, verified storage, and native-worker
failure isolation; its shortcut, paste, onboarding, and network behavior needs
to be adapted to VoxFlow's Ubuntu GNOME Wayland and local-first constraints.
