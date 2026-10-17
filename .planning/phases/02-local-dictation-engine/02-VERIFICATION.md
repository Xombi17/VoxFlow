---
phase: 02-local-dictation-engine
status: human_needed
verified_at: "2026-10-17"
requirements: [AUDIO-02, AUDIO-03, AUDIO-04]
---

# Phase 2 Verification: Local Dictation Engine

## Verdict

**Status: `human_needed`**

The Phase 2 implementation and offline evidence satisfy the deterministic
contract checks. The remaining work is target-host acceptance, not an observed
offline test failure: this checkout has no usable live microphone transport or
explicitly installed local model profile/weights for real transcription and
cold/warm performance measurement.

The roadmap and requirements files remain unchanged. This verification checks
the source and tests directly; plan summaries are supporting context only.

## Phase goal and success criteria

| Criterion | Result | Evidence and boundary |
|---|---|---|
| 1. With network disabled, an installed local model transcribes a recorded fixture and a live short utterance. | **Human needed** | `src/voxflow/providers/local_whisper.py` implements read-only model discovery, lazy `faster-whisper` loading, explicit local-only policy, cancellation, and timestamp mapping. `tests/unit/test_local_whisper.py` uses a fake model and verifies discovery, checksum changes, lazy reuse, settings, segments, cancellation, and model failure. The real model/weights, microphone, negotiated host format, and live utterance were not available for this verification. |
| 2. The same core job accepts an explicitly configured LAN/cloud provider without changing the job lifecycle or UI contract. | **Pass (offline contract)** | `src/voxflow/core/jobs.py` owns one provider-independent lifecycle; `src/voxflow/providers/remote_asr.py` implements the shared async contract; `tests/integration/test_provider_contracts.py` runs the same success, validation, checksum, failure, cancellation, retry, and redaction scenarios for fake local and remote providers. No live endpoint was contacted. |
| 3. The app exposes cold-start, warm-start, and end-to-end timings without telemetry. | **Human needed** | `src/voxflow/evals/metrics.py` and `tools/asr_benchmark.py` provide allowlisted local records for cold initialization, warm p50/p95, end-to-end, cancellation latency, realtime factor, and peak resource use. `tests/evals/test_asr_benchmark.py` verifies these fields and redaction with a fake provider. A real target-laptop local-model benchmark was not run. |
| 4. Cancellation and model/provider errors leave a structured recoverable job state. | **Pass** | `DictationJobRunner` preserves the artifact/config snapshot and maps cancellation, provider errors, invalid results, checksum mismatches, and remote policy rejection to terminal recoverable snapshots. Audio session cancellation, overflow, duration, backend disconnect, and cleanup failure are covered by `tests/unit/test_audio_session.py` and `tests/integration/test_audio_session.py`. |

## Requirement traceability

| Requirement | Verification status | Direct evidence | Remaining evidence |
|---|---|---|---|
| **AUDIO-02** — offline dictation using an installed local STT model | **Human needed** | Bounded negotiated-format capture and source-format WAV artifacts in `src/voxflow/audio/session.py` and `src/voxflow/audio/artifacts.py`; explicit installed-profile discovery and lazy local adapter in `src/voxflow/providers/local_whisper.py`; fake-model/offline tests pass. | Run `02-HOST-ACCEPTANCE.md` sections B–E on the target Ubuntu GNOME Wayland host with an explicitly installed model profile, negotiated audio format, and one short utterance. |
| **AUDIO-03** — optional LAN/cloud provider using the same workflow | **Pass (offline contract)** | `ProviderSelectionSnapshot` defaults to local/local-only; remote configuration requires validated HTTP(S), explicit `remote_explicit` policy, and credential environment-variable references. The shared job/provider contract tests pass with Internet sockets denied. | A live LAN/cloud smoke test remains optional and was intentionally not run; it requires operator-supplied endpoint, credential, consent, and `--allow-network`. |
| **AUDIO-04** — measured local cold/warm/end-to-end latency without telemetry | **Human needed** | `BenchmarkRecord` is allowlisted to IDs, negotiated format, timings, distributions, status/error codes, realtime factor, and resource metrics. Fake benchmark tests pass and `tools/asr_benchmark.py --help` exposes the explicit fixture/profile interface. | Record real cold and warm measurements on the target laptop with the negotiated host format and an explicitly installed model before promoting a default profile. |

## Must-have evidence audit

| Must-have area | Result | Source/test evidence |
|---|---|---|
| Negotiated format is preserved; no platform-level 16 kHz mono assumption | **Pass** | `OpenedAudioStream.format` is consumed by `AudioSession`; WAV tests verify 48 kHz/mono source metadata and the session tests verify source-format duration clipping. |
| Bounded immutable frame handoff and artifact identity | **Pass** | `AudioSession._on_frame()` copies callback data to immutable bytes, bounds accepted frames, and returns typed overflow/max-duration outcomes. `write_wav_artifact()` writes source-format PCM16 WAV bytes and hashes the exact file. Audio artifact/session tests pass. |
| Deterministic stop/cancel/close and recoverable capture failures | **Pass** | Fake lifecycle tests assert `start -> stop -> close`, empty cancellation has no artifact, captured cancellation retains an artifact under policy, disconnect and close failures are typed/retryable, and close failure preserves the Phase 1 active-handle retry state. |
| Typed result validation and checksum binding | **Pass** | `Segment`/`TranscriptResult` validation rejects invalid bounds, confidence, identities, overlap, and malformed results; `DictationJobRunner` requires the provider result checksum to match the artifact. Contract/job tests pass. |
| Explicit, read-only local model discovery and lazy provider loading | **Pass for offline implementation evidence** | Discovery reports portable metadata/checksum and typed missing/incomplete results without creating files. Fake-provider tests verify one model load, explicit settings, timestamp mapping, pre-dispatch cancellation, and redacted failure details. Real model inference remains host-gated. |
| Local-only measurement and privacy boundary | **Pass for offline implementation evidence** | `BenchmarkRecord.to_dict()` has an allowlisted schema; benchmark tests reject audio/transcript/token/credential/path leakage and verify cold/warm/end-to-end/cancellation/realtime/resource fields. |
| Optional remote provider and policy guard | **Pass** | Local-only is the default; remote dispatch is rejected before transport invocation unless `remote_explicit` is selected. Fake remote tests cover valid, malformed, HTTP, checksum, cancellation, failure, and redaction cases; provider contract tests deny Internet sockets. |
| Real microphone, local model, and target-laptop measurements | **Human needed** | Not available on this host; see explicit limitations below. |

## Commands and observed results

All commands were run from the repository root using the project-local Python
3.12 environment and offline uv mode where applicable.

| Command | Result |
|---|---|
| `NETWORK_DISABLED=1 make test` | **Pass — 115 passed in 0.18s** |
| `PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python python -m pytest -q tests/unit/test_audio.py tests/unit/test_audio_artifacts.py tests/unit/test_audio_session.py tests/integration/test_audio_session.py tests/unit/test_asr_contract.py tests/unit/test_local_whisper.py tests/unit/test_jobs.py tests/evals/test_asr_benchmark.py tests/unit/test_provider_config.py tests/integration/test_remote_provider.py tests/integration/test_provider_contracts.py` | **Pass — 80 passed in 0.15s** |
| `make lint` | **Pass — compileall/lint target completed with no output** |
| `uv lock --check --offline` | **Pass — resolved 34 packages with no lock changes** |
| `PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python python -m compileall -q src tests tools` | **Pass — no output/errors** |
| `git diff --check` | **Pass — no whitespace errors** |
| `PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python python tools/provider_probe.py --json --provider local` | **Pass — `provider_kind=local`, `network_policy=local_only`, `capability_status=offline_ready`, `network_request_made=false`** |
| `NETWORK_DISABLED=1 PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python python tools/provider_probe.py --json --provider remote --model remote-model --endpoint http://127.0.0.1:9000/asr --network-policy remote_explicit --allow-network --fixture tests/fixtures/audio/short_utterance.wav` | **Pass — `error_code=network_disabled`, `network_request_made=false`** |
| `PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python python tools/audio_probe.py --json` | **Structured host limitation — `audio.input=unsupported`, `backend_unavailable`, no device/format, `capture.started=false`, `capture.closed=true`, `capture.active=false`** |
| `PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python python tools/asr_benchmark.py --help` | **Pass — explicit fixture/model-root/model-id interface shown; no model loaded** |
| Optional module availability check for `faster_whisper`, `sounddevice`, and `dbus_next` | **Observed: `True`, `False`, `False`, respectively** |

## Explicit host limitations

- The current environment does not have `sounddevice`; the audio probe cannot
  enumerate or open a real microphone. No real permission, mute, disconnect,
  recovery, callback, or negotiated sample-format result is claimed.
- `faster_whisper` is installed as a Python adapter dependency, but no
  explicitly installed model profile/weights were supplied for this run. The
  local model benchmark and real fixture transcription therefore remain
  unverified on target hardware. The repository contains no model weights.
- `dbus_next` is absent, carrying forward the Phase 1 limitation for live
  portal/shortcut integration. It does not affect the Phase 2 fake-provider
  contract checks, but no full desktop push-to-talk-to-transcript smoke test is
  claimed.
- No LAN/cloud endpoint or credential was used. Remote behavior is verified by
  injected transports and a network-disabled probe; live remote acceptance is
  intentionally operator opt-in.
- The Phase 1 verification remains bounded at the host layer: fake audio and
  platform tests are not substitutes for Ubuntu GNOME Wayland acceptance.

## Verification scope and file safety

- Reviewed `.planning/ROADMAP.md`, `.planning/REQUIREMENTS.md`,
  `.planning/STATE.md`, all three Phase 2 plans and summaries, `02-CONTEXT.md`,
  `02-AI-SPEC.md`, `02-RESEARCH.md`, `02-HOST-ACCEPTANCE.md`, and the Phase 1
  verification/host-acceptance/review artifacts.
- Inspected the Phase 2 audio, job, provider, evaluation, tool, fixture, and
  test source directly.
- This verification adds only this file. It does not modify source code,
  `STATE.md`, `ROADMAP.md`, `REQUIREMENTS.md`, or any existing summary, and no
  commit was created.

## Next acceptance action

Run the redacted host procedure in
`.planning/phases/02-local-dictation-engine/02-HOST-ACCEPTANCE.md`: record the
negotiated microphone format, discover an explicitly installed model without a
download, run one fixture/short-utterance transcription, and capture separate
cold/warm/end-to-end local metrics. Re-verify this phase after that evidence is
available.
