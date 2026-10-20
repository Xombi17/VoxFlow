---
phase: 03-writing-pipeline
plan: 03
subsystem: optional-cleanup
tags: [writing, cleanup, providers, privacy, fallback, remote-policy]
requires: [03-02]
provides:
  - injectable async cleanup provider and transport contracts
  - explicit remote cleanup policy and coarse endpoint diagnostics
  - raw-transcript fallback for provider failure, timeout, cancellation, and empty output
  - daemon cleanup-provider injection and redacted fallback status
affects: [phase-04, phase-05]
tech-stack:
  added: []
  patterns: [async provider boundary, lazy urllib transport, frozen job policy, metadata-only diagnostics]
key-files:
  created:
    - src/voxflow/providers/cleanup.py
    - tests/unit/test_cleanup_provider.py
  modified:
    - src/voxflow/providers/config.py
    - src/voxflow/providers/__init__.py
    - src/voxflow/text/contracts.py
    - src/voxflow/text/pipeline.py
    - src/voxflow/daemon.py
    - tests/integration/test_writing_pipeline.py
    - README.md
decisions:
  - Keep deterministic cleanup as the default and never invoke an optional provider for a deterministic job.
  - Require remote_explicit cleanup policy plus network disclosure before a network-required provider can run.
  - Treat provider exceptions, timeout, cancellation, invalid/blank output, and unavailable providers as recoverable raw-text fallbacks with stable codes.
  - Keep provider request text in memory only; safe request, result, config, and daemon diagnostics contain no text, credential, endpoint, or local path values.
metrics:
  targeted_tests: 64
  full_offline_tests: 267
  completed: 2026-10-18
---

# Phase 3 Plan 03: Optional cleanup providers

Added the optional cleanup boundary after the deterministic writing slice.
`CleanupRequest` carries raw text and a frozen `WritingSettings` snapshot to an
injectable async provider, while `RemoteCleanupProvider` keeps standard-library
transport lazy and refuses to dispatch unless the job policy is
`remote_explicit` with network disclosure enabled. Endpoint diagnostics are
limited to `lan`, `http`, or `https` classification.

`DeterministicWritingPipeline.run_async()` selects the deterministic path by
default or calls the injected provider. Provider success records the provider
identity and a hash-only trace. Provider errors, timeout, cancellation, empty
output, invalid output, policy rejection, and unavailable providers return a
`WritingResult` whose `final_text` is the exact raw transcript, with
`fallback=True` and a stable fallback code. The daemon accepts an injected
cleanup provider, uses the async pipeline entry point, retains the result, and
reports only redacted fallback codes.

README now documents the default local behavior, explicit remote opt-in, raw
fallback behavior, redacted diagnostics, and the offline test command.

## Focused audit remediation

The Phase 3 follow-up keeps deterministic cleanup as the default while wiring
the daemon's default settings factory to the persisted SQLite snapshot. Cleanup
policy, provider identity, network policy/disclosure, and timeout now round-trip
through the settings store, including migration defaults for the previous
writing-preferences schema. The deterministic formatter handles spoken
`semi colon`, gives the neutral `other` style an explicit case-preserving
behavior, and protects POSIX paths. Blank ASR output becomes the stable
`empty_transcript` daemon notification instead of constructing an invalid blank
writing result. Safe metadata now sanitizes ASR language values and validates
trace hashes/stage identifiers; provider output remains literal. A final review
also prevents duplicate punctuation after protected spans, enforces the frozen
per-job cleanup timeout, and rejects provider identity mismatches before
dispatch.

## Verification

- `NETWORK_DISABLED=1 PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_text_contracts.py tests/unit/test_text_pipeline.py tests/unit/test_text_settings.py tests/unit/test_cleanup_provider.py tests/integration/test_writing_pipeline.py tests/integration/test_daemon_loop.py -q` — 64 passed.
- `NETWORK_DISABLED=1 make test` — 267 passed.
- `make lint` — passed (compileall).
- `uv lock --check --offline` — passed.
- `git diff --check` — passed.

Host acceptance was not performed; this plan was verified with offline fakes and
the deterministic local path only.
