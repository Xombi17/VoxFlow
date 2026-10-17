# Phase 2 Host Acceptance: Local Dictation Engine

This checklist separates deterministic offline evidence from the target-laptop
checks needed to select a local model profile. Model weights and recordings are
host-managed inputs; they are never committed to the repository.

## Recording rules

- Run from the repository checkout with the project Python 3.12 environment.
- Select a model directory explicitly. The discovery code is read-only and does
  not create directories, download weights, or contact a model hub.
- Record only redacted status, portable profile ID, model checksum, negotiated
  sample rate/channel count, stage timings, cancellation latency, realtime
  factor, and peak resource samples.
- Do not record or commit model roots, device names/IDs, absolute paths, audio,
  transcripts, clipboard text, credentials, endpoint tokens, or model weights.

## A. Offline automated evidence

These commands use fake providers and checked-in non-personal fixtures. They do
not require a microphone, installed model weights, desktop portal, or network.

```bash
NETWORK_DISABLED=1 make test
make lint
uv lock --check --offline
PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python \
  python -m pytest -q \
  tests/unit/test_asr_contract.py \
  tests/unit/test_local_whisper.py \
  tests/unit/test_jobs.py \
  tests/evals/test_asr_benchmark.py
PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python \
  python -m compileall -q src tests tools
```

Expected result: every command exits zero. The test suite must not create model
weight files or open a socket. The benchmark schema contains only job/provider/
model IDs, negotiated format, stage timings, distributions, status/error codes,
and local resource metrics.

## B. Target host metadata

Run these non-invasive checks and keep only concise, redacted values:

```bash
lsb_release -ds
printf 'session=%s wayland_display_present=%s x11_display_present=%s\n' \
  "${XDG_SESSION_TYPE:-unset}" \
  "$([ -n "${WAYLAND_DISPLAY:-}" ] && printf true || printf false)" \
  "$([ -n "${DISPLAY:-}" ] && printf true || printf false)"
pipewire --version
PYTHONPATH=src python3.12 tools/audio_probe.py --json
```

Record:

| Field | Redacted value |
|---|---|
| Ubuntu release | |
| GNOME Shell version | |
| Session type / display capability | |
| PipeWire version | |
| Audio backend status/code | |
| Acceptance date | |

## C. Negotiated audio-format gate

1. Run the audio probe and confirm the selected input opens and closes with
   `started=false`, `active=false`, and `closed=true`.
2. Start one short, non-personal utterance through the host capture path.
3. Record only the negotiated `sample_rate` and `channels`, the terminal state,
   and the artifact checksum. Do not record the bytes or transcript.
4. Confirm the provider receives that negotiated format at its boundary; do not
   replace it with an assumed 16 kHz mono format.

| Check | Result / redacted evidence |
|---|---|
| Input enumerated and opened | |
| Negotiated sample rate | |
| Negotiated channel count | |
| Short capture terminal state | |
| Artifact checksum recorded without path | |
| Stop/close completed deterministically | |

## D. Explicit installed-model gate

Prepare a faster-whisper/CTranslate2 model directory using the project's normal
offline host provisioning process. Do not use a model name that could trigger a
hub lookup. The directory must already contain the required local model files.

Run discovery with a redacted shell variable pointing at the installed profile:

```bash
MODEL_ROOT='<redacted-installed-model-directory>'
MODEL_ID='profile-id'
PYTHONPATH=src python3.12 - <<'PY'
import os
from voxflow.providers.local_whisper import discover_local_model

result = discover_local_model(os.environ["MODEL_ROOT"], model_id=os.environ["MODEL_ID"])
print({
    "available": result.available,
    "error_code": result.error_code,
    "profile": result.profile.to_dict(),
})
PY
```

Acceptance requires `available=true`, a stable checksum, an explicit backend,
supported language/device properties, and no path in the printed profile. A
missing or incomplete profile is a typed unavailable result and is not repaired
by downloading anything.

## E. Cold/warm benchmark and promotion decision

Use the checked-in fixture or one approved non-personal host utterance. Provide
the installed profile explicitly:

```bash
PYTHONPATH=src python3.12 tools/asr_benchmark.py \
  --fixture tests/fixtures/audio/short_utterance.wav \
  --model-root '<redacted-installed-model-directory>' \
  --model-id 'profile-id' \
  --runs 5 \
  --json
```

Record only the JSON fields in the allowlisted schema. Review cold model load,
warm p50/p95 inference, end-to-end timing, cancellation latency, realtime
factor, and peak resource sample separately:

| Measurement | Redacted value | Meets local budget? |
|---|---:|---|
| Cold initialization (ms) | | |
| Warm p50 (ms) | | |
| Warm p95 (ms) | | |
| End-to-end (ms) | | |
| Cancellation latency (ms) | | |
| Realtime factor | | |
| Peak resource (MB) | | |

Promote a profile only after the negotiated-format check and separate cold and
warm measurements are reviewed on the target laptop. Keep the result local;
there is no remote metrics upload or hosted telemetry path.

## Acceptance outcome

| Gate | Outcome |
|---|---|
| Offline suite and lock check | [ ] pass / [ ] blocked |
| Negotiated host format | [ ] recorded / [ ] unavailable |
| Explicit installed profile discovery | [ ] available / [ ] blocked |
| Cold and warm benchmark | [ ] recorded / [ ] blocked |
| Default profile promotion | [ ] approved / [ ] deferred |

Host limitation to record if blocked:

```text
Audio backend limitation:
Installed model limitation:
Negotiated-format limitation:
Benchmark limitation:
Profile decision: [ ] promoted  [ ] deferred pending host evidence
```
