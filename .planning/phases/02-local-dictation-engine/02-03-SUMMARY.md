---
phase: 02-local-dictation-engine
plan: 03
subsystem: remote-asr
tags: [python, pydantic, remote-asr, provider-policy, offline, privacy]

# Dependency graph
requires:
  - phase: 02-local-dictation-engine
    plan: 02
    provides: typed ASR input/result contracts, checksum-bound DictationJobRunner, and local provider lifecycle
provides:
  - Explicit local/remote provider kind and local-only/remote-explicit network policy snapshots.
  - Validated HTTP(S) remote configuration with environment-variable credential references and no stored credential values.
  - Injectable remote ASR transport/provider with shared result validation, cancellation, recoverability, and retry metadata.
  - Shared offline local/remote contract tests with Internet-socket denial and a safe provider configuration probe.
affects: [phase-3-formatting, phase-5-privacy, host-acceptance]

# Tech tracking
tech-stack:
  added: [standard-library urllib remote transport]
  patterns: [immutable provider-selection snapshot, explicit network gate, injectable transport, allowlisted diagnostics]

key-files:
  created:
    - src/voxflow/providers/config.py
    - src/voxflow/providers/remote_asr.py
    - tests/unit/test_provider_config.py
    - tests/integration/test_remote_provider.py
    - tests/integration/test_provider_contracts.py
    - tools/provider_probe.py
  modified:
    - src/voxflow/providers/asr.py
    - src/voxflow/core/jobs.py

key-decisions:
  - "ProviderSelectionSnapshot is the frozen job decision; ProviderConfigSnapshot remains a compatibility alias for the Phase 2 Plan 02 contract."
  - "Remote endpoint configuration accepts only explicit HTTP(S) URLs without embedded credentials; transports resolve only an environment-variable name at request time."
  - "DictationJobRunner rejects a remote selection under local_only before constructing a provider request, while remote adapter checks the same policy defensively."
  - "The standard-library transport is lazy and guarded by NETWORK_DISABLED; tests inject fakes and deny AF_INET/AF_INET6 sockets while allowing asyncio's Unix self-pipe."

requirements-addressed: [AUDIO-03, AUDIO-04]
requirements-completed: []
requirements-pending: [AUDIO-03, AUDIO-04]

# Metrics
completed: 2026-10-17
---

# Phase 2 Plan 3: Explicit Remote ASR Policy and Shared Provider Contracts

**Opt-in remote ASR now uses the same frozen, checksum-bound job lifecycle as local ASR while offline tests and diagnostics remain network- and secret-safe.**

## Accomplishments

- Added `ProviderKind`, `NetworkPolicy`, `RemoteProviderConfig`, and the immutable
  `ProviderSelectionSnapshot`. Local provider/model defaults are `local` and
  `local_only`; remote dispatch requires `remote_explicit` at the job boundary.
- Added HTTP(S) endpoint validation for scheme, host, port, fragments, whitespace,
  and embedded credentials. Remote credentials are represented only by an
  environment-variable name and are omitted from safe job/probe diagnostics.
- Added injectable `RemoteTransport`/`RemoteASRProvider` contracts. The adapter
  maps structured status/payload responses through the shared transcript and
  checksum validator, checks provider/model identity, and maps timeout, transport,
  malformed, HTTP, and cancellation paths to stable recoverable errors.
- Added local/remote parameterized contract coverage for success, timestamp and
  checksum validation, provider failure, cancellation, retry metadata, and
  redacted diagnostics. The suite denies Internet sockets and uses no real
  endpoint.
- Added `tools/provider_probe.py`. Configuration-only runs print coarse provider,
  model, endpoint-classification, policy, and capability status. A live request
  requires both `--allow-network` and an explicit `--fixture` and emits no request
  or response content.

## Task Commits

1. **Task 1: Add explicit provider selection policy** — `0a9f176`
   (`feat(02-03): add explicit provider selection policy`)
2. **Task 2: Add injectable remote ASR provider** — `5bbd13e`
   (`feat(02-03): add injectable remote ASR provider`)
3. **Task 2 hardening: make local defaults explicit** — `a7ccf04`
   (`fix(02-03): make local provider selection defaults explicit`)
4. **Task 3: Add shared contracts and safe provider probe** — `b9bbb96`
   (`test(02-03): add shared provider contracts and safe probe`)
5. **Probe hardening: report network-disabled live probes accurately** — `931fe85`
   (`fix(02-03): report network-disabled probe accurately`)

## Files Created/Modified

- `src/voxflow/providers/config.py` — frozen provider/network selection and
  validated remote endpoint/configuration models.
- `src/voxflow/providers/asr.py` — reuses the configuration snapshot in the
  shared ASR boundary and accepts JSON segment arrays as immutable tuples.
- `src/voxflow/core/jobs.py` — freezes job configuration and rejects remote
  dispatch under local-only policy before provider invocation.
- `src/voxflow/providers/remote_asr.py` — injectable transport boundary, lazy
  standard-library HTTP transport, response mapping, and redacted failures.
- `tests/unit/test_provider_config.py` — endpoint, credential-reference,
  default-policy, dispatch, and immutability coverage.
- `tests/integration/test_remote_provider.py` — fake remote response, status,
  schema, checksum, policy, cancellation, and redaction coverage.
- `tests/integration/test_provider_contracts.py` — shared local/remote lifecycle
  assertions with Internet-socket denial.
- `tools/provider_probe.py` — safe JSON provider configuration/live opt-in probe.
- `.planning/phases/02-local-dictation-engine/02-03-SUMMARY.md` — this evidence
  record.

## Verification Evidence

- `NETWORK_DISABLED=1 make test` — **115 passed** in 0.17s.
- `PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python python -m pytest -q tests/unit/test_provider_config.py tests/unit/test_jobs.py tests/integration/test_remote_provider.py tests/integration/test_provider_contracts.py` — **35 passed** in 0.07s.
- `NETWORK_DISABLED=1 PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python python -m pytest -q tests/integration/test_remote_provider.py` — **8 passed**.
- `NETWORK_DISABLED=1 PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python python -m pytest -q tests/integration/test_provider_contracts.py` — **12 passed** with Internet socket denial; asyncio Unix-domain self-pipes remain available for the test event loop.
- `PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python python tools/provider_probe.py --json --provider local` — exited 0 and emitted safe JSON with `provider_kind=local`, `network_policy=local_only`, `capability_status=offline_ready`, and `network_request_made=false`.
- The same provider probe under `NETWORK_DISABLED=1` — exited 0 with identical safe output.
- An explicitly remote probe with `--allow-network --fixture` under
  `NETWORK_DISABLED=1` — exited 0 with `error_code=network_disabled` and
  `network_request_made=false`; no socket was opened and no credential or fixture
  path appeared in the JSON.
- `make lint` — passed; compileall completed without errors.
- `uv lock --check --offline` — passed; resolved 34 packages with no lockfile change.
- `PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python python -m compileall -q src tests tools` — passed.
- `git diff --check` — passed with no whitespace errors.

The offline checks did not open Internet sockets, contact a remote endpoint,
resolve a credential value, download a model, or serialize raw audio,
transcripts, response bodies, or absolute paths in diagnostics.

## Host / Live Endpoint Limitations

- No live LAN/cloud endpoint smoke test was run. The plan explicitly permits that
  test only after offline checks and only with operator-supplied endpoint,
  credential environment, consent, and `--allow-network --fixture`.
- No remote provider credentials or endpoint tokens were added to the checkout.
- Local model, microphone, and negotiated-format host evidence remains governed
  by `02-HOST-ACCEPTANCE.md`; this plan does not claim that host evidence.

## Next Phase Readiness

- Phase 3 can consume the same `TranscriptResult` and `DictationJobSnapshot`
  regardless of local or explicitly selected remote provider.
- A future host smoke test can inject or select `UrllibRemoteTransport` only on
  an explicitly remote-enabled job; local-only remains the safe default.
- AUDIO-03/AUDIO-04 implementation evidence is complete for this plan, while
  live endpoint and target-laptop evidence remain intentionally pending.

---
*Phase: 02-local-dictation-engine*
*Plan: 03 completed: 2026-10-17*
