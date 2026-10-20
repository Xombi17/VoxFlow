---
phase: 03-writing-pipeline
plan: 01
subsystem: deterministic-writing
tags: [writing, transcript, normalization, snippets, daemon]
requires: [02.1]
provides:
  - immutable raw/final writing contracts
  - dependency-free deterministic normalization pipeline
  - golden text fixtures and redacted trace metadata
  - daemon seam that inserts final text while retaining raw text
affects: [03-02, 03-03, phase-04]
tech-stack:
  added: []
  patterns: [protected-span placeholders, immutable writing result, stage hashes]
key-files:
  created:
    - src/voxflow/text/__init__.py
    - src/voxflow/text/contracts.py
    - src/voxflow/text/pipeline.py
    - tests/fixtures/text/writing_cases.json
    - tests/unit/test_text_contracts.py
    - tests/unit/test_text_pipeline.py
    - tests/integration/test_writing_pipeline.py
  modified:
    - src/voxflow/daemon.py
    - tests/integration/test_daemon_loop.py
decisions:
  - TranscriptResult remains immutable; WritingResult is the separate raw-to-final boundary.
  - Deterministic formatting protects URLs, emails, code-like spans, quotes, and dictionary words before mutation.
  - Daemon stores the latest WritingResult in memory; durable history remains Phase 4.
  - User-authored replacements are applied literally in one longest-match pass and never reprocessed.
  - Ambiguous punctuation words and multi-word self-corrections are left unchanged rather than guessed.
metrics:
  automated_tests: 228 passed
  completed: 2026-10-18
---

# Phase 3 Plan 01: Deterministic writing slice

Implemented the first Phase 3 vertical slice. A validated ASR
`TranscriptResult` is wrapped in an immutable `RawTranscript`, transformed by
the dependency-free `DeterministicWritingPipeline`, and represented by a
`WritingResult` that retains both the raw and final values.

The pipeline applies a fixed stage order for whitespace normalization, low-risk
filler removal, conservative `no`/`I mean` self-corrections, snippet and
correction matching, and punctuation/paragraph/list formatting. Protected
placeholders keep URLs, email addresses, code-like spans, quoted literals, and
dictionary words out of broad formatting rules. Each stage records only hashes,
stage names, changed flags, and rule IDs in safe metadata.

The review pass hardened the slice against adversarial inputs: replacement
strings are literal, protected spans cannot be rewritten by user rules,
longest-match rules are applied once, ambiguous punctuation/self-correction
phrases are preserved, provider/path-like identifiers are rejected from safe
metadata, blank cleanup has an explicit fallback trace, and daemon pipeline
failures retain a raw fallback result for recovery callers.

The daemon now runs the writing pipeline after capture closes and successful ASR
validation, inserts `WritingResult.final_text`, and keeps the latest result in
memory for the later recovery/history seam. Existing capture-close-before-insert
ordering and non-sensitive lifecycle output remain intact.

## Verification

- `NETWORK_DISABLED=1 PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_text_contracts.py tests/unit/test_text_pipeline.py tests/integration/test_writing_pipeline.py -q` — 11 passed.
- `NETWORK_DISABLED=1 PYTHONPATH=src .venv/bin/python -m pytest tests/integration/test_daemon_loop.py -q` — 8 passed.
- `NETWORK_DISABLED=1 make test` — 228 passed.
- `make lint` — passed (compileall).
- `uv lock --check --offline` — passed.
- `git diff --check` — passed.

## Remaining phase work

Plan 03-02 adds versioned SQLite persistence and snapshot-isolated language,
style, dictionary, correction, and snippet settings. Plan 03-03 adds explicit
optional cleanup providers and raw fallback for provider failure, timeout,
cancellation, or empty output.
