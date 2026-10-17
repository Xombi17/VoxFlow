# Handy model licensing and VoxFlow assessment

This note records the model, weight, and runtime conclusions needed for VoxFlow.
The Handy source snapshot is commit [`9e57a0d7929fcc6417ea0d6e54c1b57f62635edd`](https://github.com/cjpais/Handy/tree/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd), version `0.9.8`. The catalog was generated at `2026-08-17T11:27:14+00:00` and contains 69 GGUF ASR entries. This is research evidence, not legal advice.

## 1. Exact Handy model set and download sources

**Takeaway:** Handy's current model source is a pinned Hugging Face GGUF catalog, not a small set of weights embedded in the application. The catalog gives every model repository, immutable revision, quantized filename, byte size, SHA-256, language/capability metadata, and default quantization. The complete authoritative matrix is [`catalog.json`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/catalog/catalog.json); the runtime URL construction is in [`catalog/mod.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/catalog/mod.rs#L24-L29).

**Cited Findings:**

- For every catalog file, the immutable download URL is:

  ```text
  https://huggingface.co/{id}/resolve/{revision}/{filename}
  ```

  Handy's mirror fallback is:

  ```text
  https://blob.handy.computer/{id}/{revision}/{filename}
  ```

  The fallback, partial-file handling, size check, SHA-256 check, and atomic rename are implemented in [`catalog/mod.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/catalog/mod.rs#L135-L170) and [`model.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/managers/model.rs#L1762-L1854).
- The 69 catalog repository IDs, grouped by model family, are:

  - **Parakeet/NVIDIA:** `parakeet-unified-en-0.6b-gguf`, `parakeet-tdt-0.6b-v3-gguf`, `parakeet-tdt-0.6b-v2-gguf`, `parakeet-tdt_ctc-110m-gguf`, `parakeet-ctc-0.6b-gguf`, `parakeet-rnnt-0.6b-gguf`, `parakeet-ctc-1.1b-gguf`, `parakeet-primeline-gguf`, `parakeet-tdt-1.1b-gguf`, `parakeet-rnnt-1.1b-gguf`, `parakeet-tdt_ctc-1.1b-gguf`, and `multitalker-parakeet-streaming-0.6b-v1-gguf`.
  - **Nemotron:** `nemotron-3.5-asr-streaming-0.6b-gguf`, `nemotron-speech-streaming-en-0.6b-gguf`.
  - **Canary:** `canary-180m-flash-gguf`, `canary-1b-flash-gguf`, `canary-1b-v2-gguf`, `canary-1b-gguf`, `canary-qwen-2.5b-gguf`.
  - **Whisper/OpenAI:** `whisper-tiny-gguf`, `whisper-tiny.en-gguf`, `whisper-base-gguf`, `whisper-base.en-gguf`, `whisper-small.en-gguf`, `whisper-small-gguf`, `whisper-medium.en-gguf`, `whisper-medium-gguf`, `whisper-large-v3-turbo-gguf`, `whisper-large-gguf`, `whisper-large-v2-gguf`, `whisper-large-v3-gguf`.
  - **Cohere:** `cohere-transcribe-03-2026-gguf`, `cohere-transcribe-arabic-07-2026-gguf`.
  - **Voxtral/Mistral:** `Voxtral-Mini-4B-Realtime-2602-gguf`, `Voxtral-Mini-3B-2507-gguf`, `Voxtral-Small-24B-2507-gguf`.
  - **Qwen:** `Qwen3-ASR-0.6B-gguf`, `Qwen3-ASR-1.7B-gguf`.
  - **FunASR:** `Fun-ASR-MLT-Nano-2512-gguf`, `Fun-ASR-Nano-2512-gguf`, `SenseVoiceSmall-gguf`.
  - **GigaAM:** `gigaam-v3-ctc-gguf`, `gigaam-v3-e2e-ctc-gguf`, `gigaam-v3-rnnt-gguf`, `gigaam-v3-e2e-rnnt-gguf`.
  - **Granite:** `granite-speech-4.1-2b-nar-gguf`, `granite-4.0-1b-speech-gguf`, `granite-speech-4.1-2b-gguf`, `granite-speech-4.1-2b-plus-gguf`.
  - **Other:** `medasr-gguf`, `moss-transcribe-diarize-gguf`, `Breeze-ASR-25-gguf`.
  - **Moonshine:** `moonshine-streaming-tiny-gguf`, `moonshine-tiny-gguf`, `moonshine-tiny-ar-gguf`, `moonshine-tiny-ja-gguf`, `moonshine-tiny-ko-gguf`, `moonshine-tiny-uk-gguf`, `moonshine-tiny-vi-gguf`, `moonshine-tiny-zh-gguf`, `moonshine-base-gguf`, `moonshine-base-ar-gguf`, `moonshine-base-ja-gguf`, `moonshine-base-ko-gguf`, `moonshine-base-uk-gguf`, `moonshine-base-vi-gguf`, `moonshine-base-zh-gguf`, `moonshine-streaming-small-gguf`, `moonshine-streaming-medium-gguf`.

  Every repository has Q4/Q5/Q6/Q8 and floating-point variants where supported; some 2B+ models also expose BF16. Exact filenames, revisions, hashes, and exceptions are in the catalog rather than inferred from these repository IDs.
- Handy's five curated catalog defaults are Parakeet Unified EN 0.6B, Nemotron Streaming 3.5, Canary 180M Flash, Cohere Transcribe, and Whisper Medium. Their defaults are respectively Q8, Q8, Q8, Q5_K_M, and Q8. The exact pinned URLs are documented in [`handy-repository.md`](./handy-repository.md#current-catalog-hugging-face-gguf-models).
- The catalog's language range is broad but uneven:
  - Whisper multilingual variants advertise 99 languages; `.en` variants are English-only.
  - Nemotron Streaming 3.5 advertises 28 languages and streaming/token timestamps.
  - Canary v2 and Parakeet TDT v3 advertise 25 European languages; Canary 1B is four-language and Canary-Qwen is English-only.
  - Qwen3-ASR 0.6B advertises 30 languages; Fun-ASR MLT advertises 31; Cohere Transcribe advertises 14; Voxtral Realtime advertises 13.
  - GigaAM is Russian-only; MedASR is English medical speech; Moonshine is split into English, Arabic, Japanese, Korean, Ukrainian, Vietnamese, and Chinese repositories.
  - Streaming, translation, language detection, and timestamp type are per-model fields. They must be preserved in VoxFlow metadata instead of inferred from the model family.
- Representative catalog sizes show the deployment spread:

  | Catalog entry | Default/representative file | Size | Catalog capability/score context |
  |---|---:|---:|---|
  | Parakeet Unified EN 0.6B | Q8_0 | 731,357,568 bytes | streaming; speed 79, accuracy 90 |
  | Canary 180M Flash | Q8_0 | 218,447,552 bytes | four languages; speed 98, accuracy 88 |
  | Whisper Medium | Q8_0 | 831,538,144 bytes | 99 languages; speed 42, accuracy 84 |
  | Cohere Transcribe | Q5_K_M | 1,770,270,208 bytes | 14 languages; speed 63, accuracy 92 |
  | Voxtral Mini 4B Realtime | Q5_K_M | 3,281,439,008 bytes | streaming; speed 11, accuracy 87 |
  | Moonshine Tiny | Q8_0 | 35,466,912 bytes | English; speed 100, accuracy 74 |

  The `speed_score` and `accuracy_score` are Handy catalog metadata, not an independent VoxFlow benchmark. The catalog has no RAM or latency guarantee for the target Ubuntu host; real measurements must be taken with the selected quantization and backend.
- Handy also retains five legacy, non-catalog `.bin` downloads: `small`, `medium`, `turbo`, `large`, and `breeze-asr`. Their exact URLs are in [`model.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/managers/model.rs#L646-L810) and the existing [`handy-repository.md`](./handy-repository.md#legacy-direct-download-models).
- VAD is separate from ASR. Handy uses the GGUF-converted Silero VAD v6.2 model at [`handy-computer/silero-vad-v6.2-gguf`](https://huggingface.co/handy-computer/silero-vad-v6.2-gguf), normally stored as `silero-vad-v6.2-F32.gguf`; the app can use Earshot as an alternative. The model is MIT-licensed and has a derived-file notice.

**Inferences:**

- A model downloader must treat `(repo_id, pinned_revision, filename, SHA-256)` as one immutable artifact identity. A moving `main` URL is insufficient for reproducible VoxFlow installs.
- Bundling the entire catalog is undesirable: it would create a multi-family, multi-quant distribution with weights ranging from roughly 35 MB to many GB and with materially different language, streaming, and license behavior.
- For a first native-backend spike, a Whisper GGUF is the lowest-risk target because the current VoxFlow provider is already Whisper-oriented. Parakeet, Canary, Cohere, Voxtral, FunASR, and Granite need architecture support in the native engine even if their files are all GGUF.

**Gaps:**

- The catalog commit is pinned, but some current Hugging Face `main` cards have newer revisions. Any shipping manifest must fetch the license and `NOTICE` at the exact catalog revision, not only at current `main`.
- Handy's model cards expose benchmark fields such as WER and real-time-factor measurements, but those measurements are not a substitute for VoxFlow's host-specific latency, RAM, and cancellation tests.

## 2. Code, model, and redistribution licenses

**Takeaway:** Handy's source license is MIT, but every ASR/VAD weight has an independent license. The catalog snapshot has 25 Apache-2.0 entries, 21 MIT entries, 15 CC-BY-4.0 entries, 7 `other` entries, and 1 CC-BY-NC-4.0 entry. The license field is copied from model-card metadata during catalog generation; it is not a blanket permission to ship every file.

**Cited Findings:**

- Handy source code is MIT-licensed in [`LICENSE`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/LICENSE). Handy separately says its name, logo, icons, and brand assets are not open source and that redistributors should use their own branding in the [`README`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/README.md#L471-L483).
- The catalog license distribution is calculated from the generated catalog by [`gen_catalog.py`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/scripts/gen_catalog.py#L203-L259). The exact repository IDs in each catalog license class are:
  - **Apache-2.0 (25):** all 12 Whisper repositories; both Cohere repositories; all three Voxtral repositories; both Qwen3-ASR repositories; all four Granite repositories; `moss-transcribe-diarize-gguf`; and `Breeze-ASR-25-gguf`.
  - **MIT (21):** all four GigaAM repositories; all 17 Moonshine repositories.
  - **CC-BY-4.0 (15):** Parakeet Unified EN; Canary 180M Flash; Parakeet TDT v3/v2; Canary 1B Flash/v2; Canary-Qwen 2.5B; Parakeet TDT-CTC 110M; Parakeet CTC/RNNT 0.6B; Parakeet CTC/PrimeLine/TDT/RNNT/TDT-CTC 1.1B.
  - **CC-BY-NC-4.0 (1):** `canary-1b-gguf`.
  - **Other (7):** Nemotron Streaming 3.5; Fun-ASR MLT Nano; Fun-ASR Nano; MedASR; Nemotron Speech Streaming EN; Multitalker Parakeet; SenseVoiceSmall. The catalog count includes `multitalker-parakeet-streaming-0.6b-v1-gguf` once; the apparent seven-item list must be checked against the exact generated row when producing a compliance manifest because similar NVIDIA entries can have different model-card names and license links.
- Representative model-card evidence:
  - Parakeet TDT v3 quantization is labeled `cc-by-4.0` in its [Handy model card](https://huggingface.co/handy-computer/parakeet-tdt-0.6b-v3-gguf) and advertises 25 languages.
  - Canary 1B is explicitly labeled `cc-by-nc-4.0` in its [Handy model card](https://huggingface.co/handy-computer/canary-1b-gguf); it is not suitable for a commercial VoxFlow distribution without separate permission.
  - Canary 1B v2 is labeled `cc-by-4.0` in its [Handy model card](https://huggingface.co/handy-computer/canary-1b-v2-gguf), while the older Canary 1B entry is non-commercial.
  - Nemotron Speech Streaming EN and Multitalker Parakeet identify the [NVIDIA Open Model License](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/) in their model cards ([Nemotron](https://huggingface.co/handy-computer/nemotron-speech-streaming-en-0.6b-gguf), [Multitalker](https://huggingface.co/handy-computer/multitalker-parakeet-streaming-0.6b-v1-gguf)). Nemotron 3.5 uses the same `license_name` in its model-card metadata.
  - SenseVoiceSmall points to FunASR's [MODEL_LICENSE](https://github.com/modelscope/FunASR/blob/main/MODEL_LICENSE); Fun-ASR entries likewise use a nonstandard model license rather than a simple Apache/MIT grant ([MLT model card](https://huggingface.co/handy-computer/Fun-ASR-MLT-Nano-2512-gguf)).
  - MedASR is labeled `other` and points to the [Google MedASR model card](https://huggingface.co/google/medasr), which contains the HAI-DEF terms. It must not be treated as ordinary MIT/Apache speech software or marketed as a medical device based only on its model name.
  - Silero VAD has a separate MIT/notice record in its [Handy conversion card](https://huggingface.co/handy-computer/silero-vad-v6.2-gguf).
- Standard obligations are license-specific: MIT and Apache-2.0 require preserving the applicable copyright/license and Apache notices; CC-BY-4.0 requires attribution, a license link, and indicating changes; CC-BY-NC-4.0 is non-commercial. The canonical texts are [MIT](https://opensource.org/license/mit), [Apache-2.0](https://www.apache.org/licenses/LICENSE-2.0), and [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/).

**Inferences:**

- VoxFlow may safely keep model bytes user-managed for the current phase and avoid redistributing third-party weights. This is the cleanest default for local-first operation and avoids making the application installer a model-license bundle.
- If a later downloader is added, a manifest should carry the model-card license identifier, source URL, pinned revision, SHA-256, and required `LICENSE`/`NOTICE` text. It should permit Apache/MIT/CC-BY candidates only after verifying the pinned repository card and should exclude CC-BY-NC by default.
- The seven `other` rows need a human-reviewed policy. In particular, NVIDIA Open Model License, FunASR's custom license, and HAI-DEF terms should be stored as distinct license classes rather than collapsed into `other` or `open`.
- The `transcribe-cpp` dependency is separate from Handy's MIT application code. VoxFlow should verify that dependency's source license and native backend licenses before copying, linking, or vendoring any implementation; the safer first design is an independently version-pinned helper process with no Handy source dependency.

**Gaps:**

- A final redistribution decision still requires checking each `LICENSE` and `NOTICE` at the exact catalog-pinned commit. Current Hugging Face `main` metadata can move after Handy's catalog generation.
- This research does not provide a legal opinion on model-output rights, training-data obligations, patent exposure, or whether every quantized derivative inherits the exact upstream terms. Those points should be reviewed before shipping bundled weights.
- No model weight was copied into VoxFlow during this research.

## 3. VoxFlow compatibility and recommendation

**Takeaway:** VoxFlow cannot load Handy's GGUF/GGML artifacts with its current `faster-whisper` provider. The models are potentially usable through a new native backend, but the safe scope is one explicit Whisper-family GGUF file, kept user-managed, before adding a catalog or GUI downloader.

**Cited Findings:**

- Handy loads GGUF/GGML through Rust `transcribe-cpp`, with a worker process around native model loading and streaming/batch inference ([Cargo manifest](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/Cargo.toml#L68-L86), [worker](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/engine_supervisor/worker.rs#L255-L320)). Linux enables dynamic native backends and Vulkan; CPU remains an explicit path ([backend selection](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/managers/transcription.rs#L573-L634)).
- VoxFlow's current [`local_whisper.py`](../../src/voxflow/providers/local_whisper.py) is a lazy `faster-whisper`/CTranslate2 adapter. It expects a model directory containing `config.json` and `model.bin`, passes that directory to `faster_whisper.WhisperModel`, and uses `local_files_only=True`.
- A Handy `ggml-small.bin` or `*.gguf` file is therefore the wrong artifact shape and backend for the existing `model_root`; it cannot be made usable by changing only the model ID. This is an integration boundary, not evidence that Whisper models themselves are unsupported.
- VoxFlow already has the reusable contracts needed for a sibling provider: [`ASRProvider`](../../src/voxflow/providers/asr.py), `TranscriptResult`, cancellation, job validation/retry, source-audio checksum binding, and benchmark/probe tooling. The current Phase 2 acceptance flow intentionally treats model weights as host-managed inputs ([benchmark](../../tools/asr_benchmark.py), [host acceptance](../../.planning/phases/02-local-dictation-engine/02-HOST-ACCEPTANCE.md)).
- The current audio session negotiates and records a source-format WAV. A native helper should resample/normalize at the provider boundary if its model requires mono 16 kHz; the capture callback should not become model-specific. Handy's own capture/VAD path uses 16 kHz mono and separate Silero smoothing ([audio sink](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/audio_toolkit/audio/sink.rs#L165-L193), [VAD smoothing](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/audio_toolkit/vad/smoothed.rs#L54-L119)).

**Inferences:**

- The smallest safe implementation is an opt-in `local-whisper-cpp` provider using a short-lived, project-local native helper. It should accept one explicit `.gguf` file, emit stable JSON segments/language, honor cancellation, and leave the existing `local-whisper` provider unchanged.
- Start with one Whisper GGUF artifact, preferably `handy-computer/whisper-small-gguf` for a lower CPU/memory baseline or `handy-computer/whisper-medium-gguf` when 99-language coverage is more important. Do not start with Parakeet, Canary, Cohere, Voxtral, or medical/special-license models; they add architecture and licensing variables to the first spike.
- Discovery should recognize only explicit top-level `.gguf` files in the first slice, compute file size and SHA-256, report backend/format/model ID, and never mutate the model directory. Legacy `.bin` support can follow after GGUF works.
- The provider should preserve VoxFlow's existing `TranscriptResult` and `DictationJobRunner` contracts, pass the original audio artifact checksum through, and parse only bounded JSON output from the helper. No shell invocation, implicit download, or network access belongs in the provider.
- A later model registry can borrow Handy's useful safety properties: pinned URL/revision, expected size/hash, resumable partial file, cancellation, verification, atomic rename, and explicit user action. It should not silently reuse Handy's app-data directory or shared Hugging Face cache.
- Keep model bytes user-managed for now. This matches VoxFlow's current offline test and acceptance boundary, avoids a large installer, and postpones per-model license compliance until there is a concrete distribution policy.

**Gaps:**

- No real Handy-format model has been loaded through a VoxFlow-compatible helper on the target Ubuntu GNOME/Wayland host yet. A host spike still needs to verify native loading, negotiated WAV conversion, JSON timestamps, cold start, inference latency, cancellation, and failure recovery.
- No decision has been made between linking a native library and using a subprocess. The subprocess is the safer first experiment because it isolates native/GPU crashes and keeps Python provider behavior deterministic.
- Silero VAD is not currently a drop-in VoxFlow dependency. VoxFlow should first validate its existing capture/session behavior, then decide whether to add Silero, use an existing VAD seam, or rely on explicit push-to-talk boundaries.
- No VoxFlow source files were changed by this research. Existing notes are [`handy-repository.md`](./handy-repository.md) and [`voxflow-integration.md`](./voxflow-integration.md).
