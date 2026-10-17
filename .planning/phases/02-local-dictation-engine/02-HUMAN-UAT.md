---
status: partial
phase: 02-local-dictation-engine
source: [02-VERIFICATION.md]
started: 2026-10-17
updated: 2026-10-17
---

## Current Test

Awaiting target Ubuntu GNOME Wayland host acceptance.

## Tests

### 1. Live microphone capture and negotiated format
expected: The configured microphone opens through the supported host adapter, records a short utterance, and reports the negotiated sample rate/channel format without sample-bearing diagnostics.
result: [pending]

### 2. Installed local model transcription
expected: An explicitly installed local faster-whisper profile is discovered without downloading weights, transcribes the checked-in fixture and one short live utterance with timestamps, and produces a checksum-bound result.
result: [pending]

### 3. Cold, warm, and end-to-end benchmark
expected: The target laptop records separate cold initialization, warm inference, end-to-end, cancellation, realtime-factor, and resource measurements using the negotiated format; no model weights, audio, transcripts, credentials, or absolute paths are committed.
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps

- The current checkout has no usable `sounddevice` transport for live microphone acceptance.
- No explicitly installed local model profile or weights were available for real transcription and cold/warm measurements.
- Complete the procedure in `02-HOST-ACCEPTANCE.md`, then rerun Phase 2 verification.
