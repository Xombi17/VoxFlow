---
phase: 02
slug: local-dictation-engine
status: draft
nyquist_compliant: false
wave_0_complete: true
created: 2026-10-17
---

# Phase 02 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x with project-local uv environment |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python python -m pytest -q <targeted-tests>` |
| **Full suite command** | `NETWORK_DISABLED=1 make test` |
| **Estimated runtime** | Under 10 seconds for offline fakes; host model benchmark is explicit and separate |

---

## Sampling Rate

- **After every task commit:** Run the task's targeted pytest command and `git diff --check`.
- **After every plan wave:** Run `NETWORK_DISABLED=1 make test`, `make lint`, and `uv lock --check --offline` after dependency changes.
- **Before `/gsd:verify-work`:** Full offline suite must be green; host acceptance must record whether a real model/profile was available.
- **Max feedback latency:** 10 seconds for offline tests.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 02-01 | 1 | AUDIO-02 | T2-01/T2-02 | Bounded immutable frame handoff; negotiated format preserved | unit | `python -m pytest -q tests/unit/test_audio_session.py` | ❌ W0 | ⬜ pending |
| 02-01-02 | 02-01 | 1 | AUDIO-02 | T2-01/T2-03 | WAV artifacts retain metadata and checksum without sample-bearing diagnostics | unit | `python -m pytest -q tests/unit/test_audio_artifacts.py` | ❌ W0 | ⬜ pending |
| 02-01-03 | 02-01 | 1 | AUDIO-02 | T2-01/T2-04 | Stop, cancel, overflow, duration, and teardown reach terminal recoverable outcomes | integration | `python -m pytest -q tests/integration/test_audio_session.py` | ❌ W0 | ⬜ pending |
| 02-02-01 | 02-02 | 2 | AUDIO-02 | T2-03/T2-05 | Provider results are typed, timestamped, and checksum-bound | unit | `python -m pytest -q tests/unit/test_asr_contract.py tests/unit/test_jobs.py` | ❌ W0 | ⬜ pending |
| 02-02-02 | 02-02 | 2 | AUDIO-02 | T2-03/T2-05 | Installed model discovery never downloads and local provider is lazy | unit | `python -m pytest -q tests/unit/test_local_whisper.py` | ❌ W0 | ⬜ pending |
| 02-02-03 | 02-02 | 2 | AUDIO-04 | T2-05/T2-06 | Cold/warm/end-to-end/cancel/resource metrics are local-only and redacted | eval | `python -m pytest -q tests/evals/test_asr_benchmark.py` | ❌ W0 | ⬜ pending |
| 02-03-01 | 02-03 | 3 | AUDIO-03 | T2-07 | Remote dispatch requires explicit provider and network policy | unit | `python -m pytest -q tests/unit/test_provider_config.py` | ❌ W0 | ⬜ pending |
| 02-03-02 | 02-03 | 3 | AUDIO-03 | T2-07/T2-08 | Injectable remote transport maps valid, malformed, failed, and cancelled responses | integration | `python -m pytest -q tests/integration/test_remote_provider.py` | ❌ W0 | ⬜ pending |
| 02-03-03 | 02-03 | 3 | AUDIO-03/AUDIO-04 | T2-04/T2-07 | Local and remote fakes share one job lifecycle and no test opens a socket | integration | `python -m pytest -q tests/integration/test_provider_contracts.py` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_audio_session.py` — created by 02-01-01 before implementation assertions are finalized.
- [ ] `tests/unit/test_audio_artifacts.py` — created by 02-01-02.
- [ ] `tests/integration/test_audio_session.py` — created by 02-01-03.
- [ ] `tests/unit/test_asr_contract.py`, `tests/unit/test_jobs.py`, and `tests/unit/test_local_whisper.py` — created by 02-02.
- [ ] `tests/evals/test_asr_benchmark.py` — created by 02-02-03.
- [ ] `tests/unit/test_provider_config.py`, `tests/integration/test_remote_provider.py`, and `tests/integration/test_provider_contracts.py` — created by 02-03.

The existing pytest/uv infrastructure covers framework installation and network-disabled execution; no separate Wave 0 implementation is required.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real bounded microphone session receives a short utterance using the negotiated PipeWire-compatible format | AUDIO-02 | Current Phase 1 host lacks a live audio backend/device result | Run the Phase 2 host acceptance command from `02-HOST-ACCEPTANCE.md`; record only redacted status, negotiated format, artifact checksum, and terminal state. |
| Installed local model transcribes a non-personal speech fixture with cold and warm timings on the target laptop | AUDIO-02/AUDIO-04 | Model weights and CPU/GPU behavior are user-managed host data | Select an installed profile, run `tools/asr_benchmark.py --json`, and record p50/p95, realtime factor, cancellation, and resource results without transcript/audio/path content. |
| Optional configured LAN/cloud provider reaches the same lifecycle with explicit network disclosure | AUDIO-03 | Requires a user-controlled endpoint and consent; offline tests must not contact it | Configure a redacted endpoint in the host acceptance procedure, run one opt-in smoke test, and confirm the local-only path refuses the same provider. |

---

## Validation Sign-Off

- [ ] All tasks have a targeted automated verify command.
- [ ] Sampling continuity: no three consecutive tasks lack automated verification.
- [x] Wave 0 reuses the existing pytest/uv infrastructure; new test files are listed above.
- [ ] No watch-mode flags are used.
- [ ] `nyquist_compliant: true` set only after execution and host evidence are reviewed.

**Approval:** pending
