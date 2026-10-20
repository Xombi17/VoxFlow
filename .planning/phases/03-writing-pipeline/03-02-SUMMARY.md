---
phase: 03-writing-pipeline
plan: 02
subsystem: persisted-personalization
tags: [writing, settings, sqlite, dictionary, corrections, snippets]
requires: [03-01]
provides:
  - versioned SQLite persistence for writing preferences and personalization rules
  - immutable per-job writing settings snapshots
  - shared deterministic rule precedence and protected-span matching
affects: [03-03, phase-04, phase-05]
tech-stack:
  added: []
  patterns: [schema-versioned SQLite tables, typed settings store, snapshot isolation]
key-files:
  created:
    - src/voxflow/text/rules.py
    - tests/unit/test_text_settings.py
  modified:
    - src/voxflow/settings.py
    - src/voxflow/text/contracts.py
    - src/voxflow/text/pipeline.py
    - src/voxflow/text/__init__.py
    - tests/unit/test_text_pipeline.py
    - tests/integration/test_writing_pipeline.py
decisions:
  - Keep the existing settings key/value table and selected_model_id API unchanged.
  - Store writing preferences, dictionary entries, and correction/snippet rules in normalized SQLite tables behind WritingSettingsStore.
  - Load only enabled personalization records into immutable WritingSettings tuples for each job.
  - Apply snippets before corrections; within a rule kind, longest normalized trigger wins and the lowest rule ID breaks ties.
  - Dictionary entries protect vocabulary during later transformations and never replace text.
metrics:
  targeted_tests: 23
  full_offline_tests: 235
  completed: 2026-10-18
---

# Phase 3 Plan 02: Persisted personalization

Implemented versioned SQLite persistence for the Phase 3 writing language,
style, dictionary, correction, and snippet settings. The existing `settings`
key/value table and selected-model accessors remain compatible. First use and
repeated migrations create/update a schema marker and normalized tables without
writing to a real home directory when a test database is supplied.

`WritingSettingsStore` provides typed preference and rule CRUD, enable/disable
operations, rule testing helpers, validation before writes, and safe not-found
behavior. Invalid language, style, blank triggers, and blank replacements are
rejected before persistence. Dictionary, correction, and snippet records retain
stable integer IDs.

`load_writing_settings()` reads the current database state once and constructs a
frozen `WritingSettings` snapshot. Enabled dictionary values, rule IDs, and
rule records are copied into immutable tuples; later database edits do not
change an existing snapshot. Safe serialization contains policy values and
counts/IDs only.

Rule matching now lives in `src/voxflow/text/rules.py`. It uses protected spans
for URLs, email addresses, code-like text, quoted literals, and dictionary
terms. Enabled rules are ordered by longest normalized trigger and then lowest
stable ID, with snippets run before corrections. The deterministic pipeline
uses these shared helpers while remaining pure and SQLite-free.

## Verification

- `NETWORK_DISABLED=1 PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_text_settings.py tests/unit/test_text_contracts.py tests/unit/test_text_pipeline.py tests/integration/test_writing_pipeline.py -q` — 23 passed.
- `NETWORK_DISABLED=1 make test` — 235 passed.
- `make lint` — passed (`compileall`).
- `uv lock --check --offline` — passed.
- `git diff --check` — passed.

Host acceptance was not performed; this plan contains offline SQLite and text
pipeline behavior only.
