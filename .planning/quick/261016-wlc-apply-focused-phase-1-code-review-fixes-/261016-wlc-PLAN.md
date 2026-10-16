---
quick_id: 261016-wlc
slug: apply-focused-phase-1-code-review-fixes-
status: planned
---

# Apply Focused Phase 1 Code-Review Fixes

## Scope

Address the supplied Phase 1 findings only. Preserve the dependency-free,
injectable platform boundaries and add regression coverage for every fixed
behavior.

## Tasks

1. **Session and portal contracts**
   - Make an explicit unrecognized `XDG_SESSION_TYPE` authoritative and map it
     to `unknown`.
   - Require GlobalShortcuts version 2 before reporting availability, preserve
     the introspected version, redact portal error details, propagate task
     cancellation, generate unique request tokens, and add injectable session
     and transport close boundaries.
   - Add unit tests for version gating, redaction, cancellation, token
     uniqueness, and close behavior.

2. **Shortcut lifecycle**
   - Make setup transactional: if `Deactivated` subscription fails after
     `Activated`, unsubscribe the first callback, release the created session,
     clear partial state, and return a typed failure.
   - Propagate cancellation, make close attempt all ordinary cleanup steps, and
     clear local state deterministically.
   - Extend fake integration coverage for failure, cancellation, cleanup, and
     transport release.

3. **Audio lifecycle and negotiated formats**
   - Close streams opened before validation failure, close and clear handles
     after start failure, and clean failed handles before reopening.
   - Have the sounddevice adapter expose its queried maximum input channels and
     safely honor requested/default formats without starting capture in probes.
   - Redact probe-only device names and non-path identifiers while preserving
     format/default/count capability data. Add regression tests.

4. **Offline verification tooling**
   - Keep Python 3.12 and the lockfile as-is.
   - Make `make test` prefer a project-local cached uv environment without
     syncing, then use the available host pytest as a documented fallback.
   - Keep `make lint` as a real dependency-free compile check and remove
     unresolvable/misleading Ruff configuration.

## Verification

- Focused unit and integration tests for each changed subsystem.
- Full offline `make test`.
- Portal and audio probe JSON commands.
- Project-local compile check and `make lint`.
- `python -m compileall -q src tests tools`.
- `git diff --check`.
