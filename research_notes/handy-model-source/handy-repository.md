# Handy model-source notes

## Snapshot and scope

Research was performed from the public repository at commit [`9e57a0d7929fcc6417ea0d6e54c1b57f62635edd`](https://github.com/cjpais/Handy/tree/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd), version `0.9.8`. The repository is much broader than the four Whisper choices mentioned in its README: the current bundled catalog contains 69 GGUF ASR entries, plus legacy `.bin` entries and a separate Silero VAD model.

## 1. ASR models and exact model URLs

### Current catalog: Hugging Face GGUF models

The authoritative source is [`src-tauri/src/catalog/catalog.json`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/catalog/catalog.json#L1-L39). Each entry contains the exact Hugging Face repo ID (`id`), immutable commit (`revision`), every quantized filename, SHA-256, base model, and license. The runtime model ID for a catalog default is `repo_id/default_filename`; see [`catalog/mod.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/catalog/mod.rs#L71-L107).

For any catalog row, the exact pinned download URL is:

```text
https://huggingface.co/{id}/resolve/{revision}/{filename}
```

That URL construction and the mirror equivalent are implemented in [`catalog/mod.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/catalog/mod.rs#L24-L29) and [`catalog/mod.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/catalog/mod.rs#L135-L170). The complete exact ID/revision/filename/URL set is therefore the catalog file itself; it includes Whisper, Parakeet, Canary, Cohere, Voxtral, Qwen3-ASR, Fun-ASR, GigaAM, Granite, MedASR, Moonshine, MOSS, Nemotron, SenseVoice, and Breeze-ASR families.

The five curated default entries at this snapshot are:

| Runtime model ID | Base model | Default pinned URL |
|---|---|---|
| `handy-computer/parakeet-unified-en-0.6b-gguf/parakeet-unified-en-0.6b-Q8_0.gguf` | `nvidia/parakeet-unified-en-0.6b` | [`resolve/7e948f21…/parakeet-unified-en-0.6b-Q8_0.gguf`](https://huggingface.co/handy-computer/parakeet-unified-en-0.6b-gguf/resolve/7e948f21b7bdbac698d3318db9d350f1096f3b6c/parakeet-unified-en-0.6b-Q8_0.gguf) |
| `handy-computer/nemotron-3.5-asr-streaming-0.6b-gguf/nemotron-3.5-asr-streaming-0.6b-Q8_0.gguf` | `nvidia/nemotron-3.5-asr-streaming-0.6b` | [`resolve/6d44e540…/nemotron-3.5-asr-streaming-0.6b-Q8_0.gguf`](https://huggingface.co/handy-computer/nemotron-3.5-asr-streaming-0.6b-gguf/resolve/6d44e540bc31b0de1dbe174a3cea87f53a7f22fb/nemotron-3.5-asr-streaming-0.6b-Q8_0.gguf) |
| `handy-computer/canary-180m-flash-gguf/canary-180m-flash-Q8_0.gguf` | `nvidia/canary-180m-flash` | [`resolve/b147f9dc…/canary-180m-flash-Q8_0.gguf`](https://huggingface.co/handy-computer/canary-180m-flash-gguf/resolve/b147f9dc52b59f0998e410540a84727bd86457fd/canary-180m-flash-Q8_0.gguf) |
| `handy-computer/cohere-transcribe-03-2026-gguf/cohere-transcribe-03-2026-Q5_K_M.gguf` | `CohereLabs/cohere-transcribe-03-2026` | [`resolve/dfa4adeb…/cohere-transcribe-03-2026-Q5_K_M.gguf`](https://huggingface.co/handy-computer/cohere-transcribe-03-2026-gguf/resolve/dfa4adebb64f3076b7b6b90b721275cc069cb421/cohere-transcribe-03-2026-Q5_K_M.gguf) |
| `handy-computer/whisper-medium-gguf/whisper-medium-Q8_0.gguf` | `openai/whisper-medium` | [`resolve/ec78f06f…/whisper-medium-Q8_0.gguf`](https://huggingface.co/handy-computer/whisper-medium-gguf/resolve/ec78f06fded51aa82cde751678b78f76f78c8b7f/whisper-medium-Q8_0.gguf) |

The catalog also includes Whisper tiny/base/small/medium/large, English-only Whisper variants, Whisper Large v2/v3/Turbo, Parakeet variants, and the other families named above. All alternate quant URLs use the same repo and revision with the alternate `files[].filename`; the catalog records their exact hashes and sizes.

### Legacy direct-download models

The model manager still defines five older URL-backed entries. They use plain GGML/Whisper `.bin` files and are being deprecated in favor of the catalog; the code comments distinguish catalog GGUF entries from legacy URL entries ([`model.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/managers/model.rs#L868-L875)). Exact IDs and URLs are:

| ID | Filename | URL |
|---|---|---|
| `small` | `ggml-small.bin` | [`https://blob.handy.computer/ggml-small.bin`](https://blob.handy.computer/ggml-small.bin) |
| `medium` | `whisper-medium-q4_1.bin` | [`https://blob.handy.computer/whisper-medium-q4_1.bin`](https://blob.handy.computer/whisper-medium-q4_1.bin) |
| `turbo` | `ggml-large-v3-turbo.bin` | [`https://blob.handy.computer/ggml-large-v3-turbo.bin`](https://blob.handy.computer/ggml-large-v3-turbo.bin) |
| `large` | `ggml-large-v3-q5_0.bin` | [`https://blob.handy.computer/ggml-large-v3-q5_0.bin`](https://blob.handy.computer/ggml-large-v3-q5_0.bin) |
| `breeze-asr` | `breeze-asr-q5_k.bin` | [`https://blob.handy.computer/breeze-asr-q5_k.bin`](https://blob.handy.computer/breeze-asr-q5_k.bin) |

The definitions, hashes, filenames, and capability flags are in [`model.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/managers/model.rs#L646-L810). The README's manual-install section independently documents the first four legacy URLs and the Parakeet Q8 URL ([`README.md`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/README.md#L285-L351)).

### VAD model (not ASR)

Handy bundles/downloads `silero-vad-v6.2-F32.gguf` from:

[`https://huggingface.co/handy-computer/silero-vad-v6.2-gguf/resolve/main/silero-vad-v6.2-F32.gguf`](https://huggingface.co/handy-computer/silero-vad-v6.2-gguf/resolve/main/silero-vad-v6.2-F32.gguf)

The development setup copies it to `src-tauri/resources/models/` ([`AGENTS.md`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/AGENTS.md#L43-L48)); runtime resolves that resource path ([`managers/audio.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/managers/audio.rs#L324-L348)). The public model card identifies it as a GGUF conversion of `snakers4/silero-vad`, MIT-licensed, and includes a derived-file `NOTICE`: [`handy-computer/silero-vad-v6.2-gguf`](https://huggingface.co/handy-computer/silero-vad-v6.2-gguf).

## 2. Where weights are downloaded and stored

- **Per-app model directory:** `ModelManager::new` uses the portable-aware Tauri app-data directory and appends `models` ([`model.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/managers/model.rs#L623-L642)). On Linux, the README gives the typical app-data root as `~/.config/com.pais.handy/`, so legacy `.bin` files and mirror-fallback GGUF files land in `~/.config/com.pais.handy/models/` ([`README.md`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/README.md#L285-L313)).
- **Hugging Face cache:** catalog downloads use `hf-hub` and `Cache::from_env()`; the normal shared cache is the HF cache (`~/.cache/huggingface/hub` according to the README). The code accepts both the pinned revision and a legacy `main` cache ref ([`model.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/managers/model.rs#L299-L346)). `get_model_path` checks this cache first, then the per-app `models` directory ([`model.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/managers/model.rs#L2120-L2177)).
- **Portable mode:** a `portable` marker redirects `HF_HOME` to `<executable-dir>/Data/huggingface`; the app-data model directory becomes `<executable-dir>/Data/models` ([`portable.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/portable.rs#L14-L69), [`model.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/managers/model.rs#L623-L642)).
- **Download behavior:** HF downloads go through the pinned `cjpais/hf-hub` fork; if HF fails, the catalog mirror is `https://blob.handy.computer/{repo_id}/{revision}/{filename}`. Mirror bytes are downloaded to the app `models` directory, checked against the catalog size and SHA-256, then renamed from `.partial` to the final filename ([`model.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/managers/model.rs#L1553-L1573), [`model.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/managers/model.rs#L1762-L1854)). Legacy URL downloads use resumable `<filename>.partial` files and SHA-256 verification where a hash is defined ([`download.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/managers/model/download.rs#L51-L119)).
- **Dependencies:** `Cargo.toml` pins `transcribe-cpp` `0.4.0`, the `cjpais/hf-hub` git fork, and the network/transport libraries; the lockfile records the exact `hf-hub` commit and `transcribe-cpp` package ([`Cargo.toml`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/Cargo.toml#L68-L86), [`Cargo.lock`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/Cargo.lock#L2668-L2689), [`Cargo.lock`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/Cargo.lock#L7254-L7274)).

## 3. Runtime, backend, and library

- Handy is a Tauri desktop app with a Rust backend and React/TypeScript frontend ([`AGENTS.md`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/AGENTS.md#L52-L67)).
- All current catalog models are GGUF; legacy Whisper files are GGML `.bin`. Both are loaded through `transcribe-cpp` ([`Cargo.toml`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/Cargo.toml#L68-L76), [`model.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/managers/model.rs#L1239-L1241)).
- The model worker calls `transcribe_cpp::Model::load_with`, creates a `Session`, and exposes batch and streaming APIs. It runs native ASR in a separate worker process so the app can recover from a native backend crash/hang ([`engine_supervisor/worker.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/engine_supervisor/worker.rs#L1-L20), [`engine_supervisor/worker.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/engine_supervisor/worker.rs#L255-L319)).
- Linux enables `transcribe-cpp` dynamic backends plus Vulkan; macOS enables Metal; Windows x86_64 enables dynamic backends plus Vulkan. The manager selects CPU/GPU automatically or from a configured device ([`Cargo.toml`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/Cargo.toml#L117-L155), [`transcription.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/managers/transcription.rs#L573-L634)).
- VAD is separate from ASR: default `VadBackend` is Silero, with Earshot as an option. Silero is explicitly loaded with `Backend::Cpu` and one thread ([`settings.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/settings.rs#L334-L340), [`vad/silero.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/audio_toolkit/vad/silero.rs#L18-L69)).

## 4. Offline behavior

Handy advertises that it works completely offline and that audio stays on the computer ([`README.md`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/README.md#L5-L16)). The catalog is compiled into the binary and is available with zero network access ([`catalog/mod.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/catalog/mod.rs#L1-L7)). After the selected ASR weight is present in the HF cache or local model directory and the VAD resource is present in the app resources, loading and transcription do not require a cloud account, API, or network connection. Network access is needed for first-time model acquisition, optional updates, or a missing model; this is consistent with the manual-install instructions for restricted networks ([`README.md`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/README.md#L285-L357)).

## 5. License and attribution

- **Handy source:** MIT, copyright `(c) 2025 CJ Pais`; the MIT copyright and permission notice must remain in copies/substantial portions ([`LICENSE`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/LICENSE#L1-L21)). Handy separately says its name, logo, icon, and brand assets are not open source, and forks/redistributions must use their own branding ([`README.md`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/README.md#L471-L483)).
- **Model weights:** Handy's MIT code license does not automatically license the weights. The catalog copies each model card's `license` field during generation ([`gen_catalog.py`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/scripts/gen_catalog.py#L203-L259)). Across the 69 catalog entries at this snapshot: `apache-2.0` = 25, `mit` = 21, `cc-by-4.0` = 15, `other` = 7, and `cc-by-nc-4.0` = 1.
- **Practical redistribution rule:** preserve the applicable model license/attribution and any upstream `NOTICE` for every selected weight. `cc-by-4.0` requires attribution; `apache-2.0` and `mit` require retaining the relevant notices/license text; `cc-by-nc-4.0` is non-commercial. The seven `other` entries are not specific enough in Handy's catalog to infer terms, so their individual Hugging Face cards must be checked before redistribution. The Silero VAD GGUF card states MIT and includes a `NOTICE` derived from `snakers4/silero-vad` ([model card](https://huggingface.co/handy-computer/silero-vad-v6.2-gguf)).
- **Project acknowledgments:** the README credits Whisper/OpenAI, ggml, Silero, Tauri, and community contributors ([`README.md`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/README.md#L477-L483)). This is useful attribution context but does not replace each weight's license obligations.

## 6. VAD and segmentation behavior

- **Capture path:** audio is 16 kHz mono. The default Silero threshold is `0.3`; Earshot is `0.5`. Handy wraps the detector in a smoothing layer and forwards only speech frames to the recording/transcription stream ([`managers/audio.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/managers/audio.rs#L20-L22), [`audio/sink.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/audio_toolkit/audio/sink.rs#L165-L193)).
- **Smoothing timings:** prefill 450 ms, onset 60 ms, offline hangover 450 ms, and streaming hangover 1,650 ms ([`vad/mod.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/audio_toolkit/vad/mod.rs#L5-L17), [`vad/smoothed.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/audio_toolkit/vad/smoothed.rs#L54-L119)). The longer streaming tail is selected for streaming-capable models; a new speech run must meet the onset count, and the prefill buffer preserves leading audio.
- **Long recordings:** VAD is also used as a scorer for pause-aware chunking. Handy uses a positive threshold of `0.5`, negative threshold `0.35`, minimum speech 250 ms, minimum silence 100 ms, and 30 ms speech padding ([`chunking.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/audio_toolkit/chunking.rs#L21-L40)). Clips up to 40 seconds stay whole; longer clips prefer a pause near 30 seconds, require at least 5 seconds per chunk, and hard-cut at 40 seconds if no suitable pause exists ([`chunking.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/audio_toolkit/chunking.rs#L120-L165)).
- **Failure fallback:** if VAD cannot be loaded or scored, Handy stops cutting and decodes the remaining audio as one chunk; capture also forwards a frame if the detector returns an error ([`chunking.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/audio_toolkit/chunking.rs#L171-L177), [`audio/sink.rs`](https://github.com/cjpais/Handy/blob/9e57a0d7929fcc6417ea0d6e54c1b57f62635edd/src-tauri/src/audio_toolkit/audio/sink.rs#L182-L192)).

## VoxFlow takeaways

1. Handy is a local GGUF/GGML design built around `transcribe-cpp`, not a Python `faster-whisper` runtime. Its strongest directly reusable ideas are pinned model metadata, SHA-256 verification, HF-cache reuse, local mirror fallback, and CPU Silero VAD.
2. A Handy-compatible offline baseline can use `handy-computer/whisper-medium-gguf` or `handy-computer/parakeet-unified-en-0.6b-gguf`; choose the exact pinned revision and quantized filename from the catalog rather than using a moving `main` URL.
3. Do not treat the Handy MIT license as a blanket license for model weights. Keep per-model attribution/license records, and avoid the `cc-by-nc-4.0` or unspecified `other` models unless VoxFlow's redistribution policy handles them explicitly.
