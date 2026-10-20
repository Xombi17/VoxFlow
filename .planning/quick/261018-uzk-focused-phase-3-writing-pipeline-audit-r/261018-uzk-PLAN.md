---
quick_id: 261018-uzk
description: Focused Phase 3 writing pipeline audit remediation
mode: quick-full
---

# Focused Phase 3 Writing Pipeline Audit Remediation

## Must-haves

- Spoken `semi colon` formats deterministically without a lookup failure.
- The daemon loads persisted writing settings from `db_path` by default while an injected factory still wins.
- Built-in styles have a small, explicit, tested formatting difference.
- Cleanup policy, provider identity, network disclosure/policy, and timeout persist and round-trip.
- Blank ASR text produces a stable recoverable daemon notification rather than a crash.
- POSIX paths are protected from user-rule rewrites.
- Safe metadata validates trace hashes and stage identifiers and sanitizes language values.
- Provider output is returned literally, including leading/trailing whitespace, with edge coverage.

## Tasks

1. Update the text contracts, rules, deterministic pipeline, settings persistence, and daemon fallback/settings wiring with the smallest compatible changes.
2. Add focused unit and integration regressions covering each audited behavior, preserving existing tests and unrelated working-tree edits.
3. Run targeted tests, `NETWORK_DISABLED=1 make test`, `make lint`, `uv lock --check --offline`, and `git diff --check`; inspect the final diff without modifying `.planning/ROADMAP.md` or `.planning/STATE.md`.

## Constraints

- Deterministic cleanup remains the default.
- Remote cleanup remains explicit and observable.
- No host acceptance claims.
- Do not stage or commit pre-existing unrelated changes.
