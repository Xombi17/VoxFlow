---
phase: 02-local-dictation-engine
status: findings
reviewed: 2026-10-17
depth: standard
---

# Phase 2 Code Review

## Final verdict

Findings remain in cancellation, provider binding, model lifecycle, retention,
and remote response handling. The offline test suite is green, but the gaps
below are not covered by the current fakes.

## Review scope

- Plan scopes from `02-01-PLAN.md`, `02-02-PLAN.md`, and `02-03-PLAN.md`.
- Phase 2 implementation commits `6b3e755` through `931fe85`.
- Source files in those `files_modified` lists, plus
  `src/voxflow/core/events.py`, which git history shows was changed by the
  Phase 2 privacy fix, and the Phase 2 pytest configuration in `pyproject.toml`.
- Cross-file paths reviewed: audio callback to artifact, artifact to provider
  input, provider selection to job dispatch, local/remote result validation,
  cancellation, and benchmark/probe boundaries.

## Findings

### [High] Provider cancellation is not bounded and native work can outlive the job

- **Evidence:** `src/voxflow/core/jobs.py:192-206` awaits the provider task
  through `asyncio.shield()` with no timeout. The local provider runs model load
  and synchronous inference through `asyncio.to_thread()` at
  `src/voxflow/providers/local_whisper.py:257-260` and `:320`; its token is
  checked only before dispatch and while iterating returned segments at
  `:307` and `:324-325`. The standard-library remote transport has the same
  issue at `src/voxflow/providers/remote_asr.py:105-112`: timeout cancels the
  await, not the worker thread performing the request.
- **Observed:** A fake provider that ignores its token left `runner.cancel()`
  pending and the job in `processing` after 20 ms. A patched blocking transport
  raised `remote_timeout` while its worker remained active afterward.
- **Impact:** A stop/cancel action can hang indefinitely. Local native inference
  can continue consuming CPU/RAM after the job is marked or abandoned, and a
  timed-out remote request can continue sending audio or using credentials.
- **Action:** Add an explicit cancellation deadline at the job/provider
  boundary. Ensure the local backend can be stopped or isolated when the native
  call does not cooperate, and use a transport with a cancellable request or a
  defined post-timeout isolation policy. Return a typed cancelled/failed
  snapshot with the artifact and retry metadata once the deadline expires.

### [High] Capture cancellation can return before a typed terminal outcome

- **Evidence:** `src/voxflow/audio/session.py:291-302` returns the result of
  `_wait_for_run()`, while `:517-532` returns `self._outcome` after a timeout,
  which may still be `None`. The run task can still be inside `capture.open()`
  or cleanup when that timeout expires.
- **Observed:** With a backend whose `open()` slept for 100 ms and a
  `cleanup_timeout_ms` of 10 ms, `await session.cancel()` returned `None` while
  the run task was still active; the task only later produced `cancelled`.
- **Impact:** Callers cannot reliably update state or expose recovery metadata
  after cancellation, and the capture handle may remain active beyond the
  caller's cancellation boundary.
- **Action:** Make cancellation return a typed outcome or typed timeout/failure
  result every time. Separate the caller wait deadline from backend cleanup,
  retain a visible active-handle/retry state when cleanup is still pending, and
  add tests for cancellation during slow open, stop, close, and artifact write.

### [High] The shared runner does not bind result identity to the frozen provider selection

- **Evidence:** `src/voxflow/core/jobs.py:151-153` validates only the provider
  result and the artifact checksum. `validate_provider_result()` in
  `src/voxflow/providers/asr.py:250-260` checks schema and checksum but not
  `provider_id` or `model_id` against the job config. Remote ASR performs its
  own identity check at `src/voxflow/providers/remote_asr.py:282-285`, but the
  local provider and arbitrary protocol implementations do not receive the
  same core check.
- **Observed:** A provider configured as `selected/selected-model` returned a
  valid checksum with `other-provider/other-model`; the runner reached
  `success` and retained the mismatched result identity.
- **Impact:** A job can report success for a provider/model different from the
  immutable selection snapshot, weakening model policy and making diagnostics
  misleading. A provider implementation can accidentally or intentionally
  return an output from another backend without rejection.
- **Action:** Enforce provider and model identity against the frozen selection
  in the single core validation path. Keep adapter-specific checks as defense
  in depth, not as the only enforcement for remote results.

### [Medium] Concurrent local jobs can load duplicate Whisper models

- **Evidence:** `LocalWhisperProvider` stores `_model` and
  `_model_load_count` without synchronization at
  `src/voxflow/providers/local_whisper.py:214-216` and checks/sets them in
  `:270-297`. Both `prepare()` and `transcribe()` dispatch `_load_model()` via
  separate worker threads at `:234-237` and `:257-259`.
- **Observed:** Two concurrent `prepare()` calls using a loader that yielded
  between entry and assignment constructed two model instances and produced a
  load count of 2.
- **Impact:** Overlapping dictation jobs can duplicate a large native model,
  increasing memory pressure and cold-start latency, contrary to the bounded
  warm-model design.
- **Action:** Protect model initialization with an async single-flight or a
  thread lock, and define whether concurrent transcriptions are serialized or
  rejected before dispatch.

### [Medium] Disabling artifact retention still retains raw PCM in the session

- **Evidence:** `AudioSession` accumulates raw chunks in
  `src/voxflow/audio/session.py:188-195` and appends drained frame bytes at
  `:392-400`. `_finish()` skips WAV creation when retention is disabled, but
  does not clear `_chunks` at `:439-456`.
- **Observed:** A cancelled session configured with `retain_artifact=False`
  returned no artifact while retaining the captured PCM in
  `session._chunks` (4 bytes for a two-frame test capture).
- **Impact:** The retention setting controls disk output but not in-memory
  retention for the lifetime of the session object. Sensitive audio can remain
  available after the user selected no artifact retention.
- **Action:** Clear queued and drained sample buffers on all terminal paths when
  retention is disabled. When an artifact is retained, clear the temporary
  chunk list after the artifact is written unless a retry path explicitly
  requires the bytes.

### [Medium] Local model timestamp handling silently coerces malformed output

- **Evidence:** `src/voxflow/providers/local_whisper.py:327-340` clamps a
  segment start to `previous_end` and an end to `audio.duration_ms` before the
  shared `Segment`/`TranscriptResult` validators run. The shared validator then
  sees the modified, non-overlapping values at
  `src/voxflow/providers/asr.py:164-171`.
- **Impact:** Overlapping or out-of-range backend timestamps are silently
  rewritten instead of rejected. Downstream formatting can receive boundaries
  that were not produced by the model, contrary to the malformed-result
  rejection and timestamp-preservation contract.
- **Action:** Reject overlap, negative values, and end times beyond the declared
  audio duration with a typed provider error. Only perform an explicit,
  documented duration segmentation step before mapping model output, and test
  malformed local segments separately from valid clipping behavior.

### [Medium] Remote response bodies are read without a size limit

- **Evidence:** `src/voxflow/providers/remote_asr.py:151-154` calls
  `response.read()` and parses the complete body before schema validation.
- **Impact:** An opted-in or compromised remote endpoint can return an
  unbounded body and consume excessive memory before the allowlisted transcript
  validation rejects it. This is especially avoidable because the response
  contract is small and structured.
- **Action:** Enforce a maximum response byte count while reading, reject an
  advertised `Content-Length` above the limit, and map oversize responses to a
  redacted recoverable provider error.

## Verification evidence

- `NETWORK_DISABLED=1 make test` - **115 passed**.
- Focused Phase 2 suites - **34 passed**.
- `make lint` - passed.
- `uv lock --check --offline` - passed; 34 packages resolved.
- Offline `compileall` for `src`, `tests`, and `tools` - passed.
- `tools/provider_probe.py --json --provider local` emitted safe local-only JSON
  with `network_request_made=false`.
- `tools/asr_benchmark.py --help` completed without importing a model backend.
- `git diff --check` - passed.

The passing tests cover the intended offline fakes and redaction checks, but do
not cover non-cooperative native work, concurrent model initialization,
retention-memory clearing, provider/model identity mismatch, or oversized
remote responses.
