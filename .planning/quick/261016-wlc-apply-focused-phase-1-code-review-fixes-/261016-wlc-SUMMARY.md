---
quick_id: 261016-wlc
slug: apply-focused-phase-1-code-review-fixes-
status: complete
completed: 2026-10-16
---

# Phase 1 Code-Review Fixes Summary

Applied the supplied focused findings without changing the Phase 1 product
scope.

## Implementation commits

- `bdc9253` — hardened explicit session classification, portal version/error
  handling, cancellation propagation, request tokens, and injectable portal
  close boundaries.
- `e229d48` — made shortcut setup transactional and close deterministic,
  including cleanup after a failed `Deactivated` subscription.
- `af6e448` — closed failed audio handles and exposed negotiated input channel
  formats from the sounddevice boundary.
- `450e2e9` — made offline checks honest and documented the cached-uv/host
  pytest fallback; removed misleading Ruff configuration.
- `b0a602e` — added raw portal-detail redaction regression coverage.

## Verification evidence

- `make test` — `45 passed`; used the explicit host pytest fallback because the
  project-local `.venv` does not contain pytest.
- Python 3.12 full suite with the available offline host pytest path — `45
  passed`.
- `make lint` — dependency-free `compileall` check passed.
- `PYTHONPATH=src python3.12 tools/portal_probe.py --json` — valid structured
  output; this host reports `service_unavailable` because `dbus-next` is not
  installed, with no raw backend detail.
- `PYTHONPATH=src python3.12 tools/audio_probe.py --json` — valid structured
  output; this host reports `backend_unavailable` because `sounddevice` is not
  installed, with `started=false`, `active=false`, and `closed=true`.
- Provider-free `python3.12 -m voxflow --json` — valid JSON.
- `python3 -m compileall -q src tests tools` — passed.
- `git diff --check` — passed.

## Remaining limitations

- Live GlobalShortcuts v2 binding, permission, and hold/release behavior still
  require the optional `dbus-next` transport and an Ubuntu GNOME Wayland smoke
  test.
- Live microphone negotiation, permission, mute, disconnect, and recovery
  still require the optional `sounddevice` transport and host hardware.
- A minimal injected portal transport without `close_session` can only rely on
  client disappearance from D-Bus to reclaim its session; local VoxFlow state
  is still cleared deterministically.
