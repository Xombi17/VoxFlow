# AI-SPEC — Phase 2: Local Dictation Engine

> AI design contract for the local-first speech-to-text subsystem. It is consumed by the phase planner and evaluator; it does not authorize network use or model downloads during tests.

---

## 1. System Classification

**System Type:** Hybrid — speech recognition with an optional provider adapter

**Description:**
The system converts a bounded microphone recording into a structured transcript for one desktop user. “Good” means the local provider works without network access, returns a valid transcript with language and timing metadata, respects cancellation, and stays within a measured latency/memory budget on the target laptop. Remote providers are optional implementations of the same contract, never a required control path.

**Critical Failure Modes:**
1. Audio is captured or retained after the user believes recording has stopped.
2. A local model silently requires network access or downloads weights during a dictation/test.
3. A provider returns malformed or ambiguous metadata that causes incorrect downstream formatting.
4. Cancellation freezes the UI or leaves a job falsely marked complete.
5. Model latency or memory use makes the desktop flow unusable on the target laptop.

---

## 1b. Domain Context

**Industry Vertical:** Personal productivity / desktop accessibility
**User Population:** One Linux desktop user dictating messages, notes, prompts, and code-related prose into existing applications.
**Stakes Level:** Medium
**Output Consequence:** The transcript is passed to a cleanup/insertion pipeline and may be pasted into an external application. Incorrect words are annoying and can be costly in professional communication, but v1 does not make autonomous decisions or send messages.

### What Domain Experts Evaluate Against

| Dimension | Good | Bad | Stakes | Source |
|-----------|------|-----|--------|--------|
| Transcript fidelity | Names, numbers, technical terms, and sentence boundaries are retained or flagged | Silent omissions, hallucinated phrases, or dropped negations | High | Speech-to-text product behavior |
| Endpoint behavior | Start/stop/cancel boundaries match the user's action | Audio continues after release or clips the beginning/end | Critical | Desktop dictation workflow |
| Latency | Warm short utterances feel immediate and cold-start behavior is explained | UI blocks or the user cannot tell whether processing is alive | High | Productivity UX |
| Privacy | Offline mode stays offline and provider selection is visible | Audio/transcript leaves the machine unexpectedly | Critical | Local-first requirement |
| Recoverability | Provider failure leaves a retryable job and never loses captured audio against policy | A failed request discards work | High | Reliability requirement |

### Known Failure Modes in This Domain

- Background noise and silence can cause hallucinated text or slow inference.
- Short utterances are vulnerable to clipped first/last phonemes when capture starts/stops too aggressively.
- Technical names and code identifiers are often phonetically ambiguous and need later dictionary/context handling.
- Model download, warm-up, and GPU initialization can dominate perceived latency.
- Multiple concurrent jobs can exhaust memory or produce out-of-order insertion.

### Regulatory / Compliance Context

No regulated deployment is in scope for v1. The application must still provide explicit consent, local-by-default processing, retention controls, and clear network disclosure because voice recordings and transcripts can contain sensitive personal or workplace information.

### Domain Expert Roles for Evaluation

| Role | Responsibility |
|------|---------------|
| Target user | Labels whether a transcript is usable without manual correction and whether latency feels acceptable |
| Linux desktop integrator | Validates microphone permissions, PipeWire device behavior, cancellation, and Wayland session boundaries |
| Privacy reviewer | Verifies offline behavior, retention, redacted logs, and explicit provider selection |

---

## 2. Framework Decision

**Selected Framework:** Direct typed provider adapters; no AI orchestration framework

**Version:** Python 3.12 application code with pinned provider/library versions in `pyproject.toml` and `uv.lock`

**Rationale:**
Phase 2 is a bounded inference pipeline, not an agent, RAG system, or multi-step LLM workflow. LangChain, LangGraph, CrewAI, and provider-native agent frameworks would add abstraction and network-oriented assumptions without improving ASR correctness. A small protocol with Pydantic models makes local, LAN, and cloud implementations interchangeable and keeps the offline path auditable.

**Alternatives Considered:**

| Framework | Ruled Out Because |
|-----------|------------------|
| LangChain/LangGraph | Designed for chains/agents and adds unnecessary orchestration to a single ASR call |
| `whisper.cpp` direct C/C++ integration | Strong alternative, but defer final selection until target hardware and packaging benchmark |
| `faster-whisper` | Preferred candidate local backend, but treated as a provider implementation rather than application framework |
| OpenAI/other hosted SDK | Optional adapter only; cannot be the offline baseline |

**Vendor Lock-In Accepted:** No for the core contract; partial for optional provider adapters chosen by the user.

---

## 3. Framework Quick Reference

### Installation

```bash
# Project dependency shape; exact versions are pinned during Phase 2 planning.
uv add faster-whisper pydantic
uv add --dev pytest ruff
```

### Core Imports

```python
from pathlib import Path
from pydantic import BaseModel, Field

from voxflow.providers.asr import ASRProvider, AudioInput, TranscriptResult
```

### Entry Point Pattern

```python
async def transcribe_job(provider: ASRProvider, audio: AudioInput) -> TranscriptResult:
    """Run one bounded provider call; the caller owns durable job state."""
    result = await provider.transcribe(audio)
    return TranscriptResult.model_validate(result)
```

### Key Abstractions

| Concept | What It Is | When You Use It |
|---------|------------|-----------------|
| `ASRProvider` | Stable async interface for local/LAN/cloud transcription | Every provider implementation |
| `AudioInput` | Path/stream metadata, sample format, language hint, retention policy | Before dispatching inference |
| `TranscriptResult` | Text, segments, language, confidence/timing metadata, provider identity | Downstream cleanup and history |
| `ProviderCapabilities` | Offline/network/GPU/language/cancellation support declaration | Settings and capability UI |
| `CancellationToken` | Cooperative cancellation signal checked at capture and inference boundaries | User cancel and shutdown |

### Common Pitfalls

1. Treating a lazy generator or background future as completed before consuming its result.
2. Loading a model inside every request instead of reusing a bounded warm worker.
3. Letting provider exceptions escape without preserving the job's captured-audio reference.

### Recommended Project Structure

```text
src/voxflow/
├── providers/asr.py          # Protocols and Pydantic contracts
├── providers/local_whisper.py
├── providers/remote_asr.py
├── audio/session.py          # Capture lifecycle and format normalization
├── core/jobs.py              # Durable state transitions
└── evals/asr_fixtures.py    # Offline fixtures and metrics
```

---

## 4. Implementation Guidance

**Model Configuration:**
Default to a user-selected local model profile. The first profile should be a quantized CPU-capable model that can run on the target laptop. Language, VAD, beam size, thread count, and device are explicit settings stored with each job. Do not auto-download a model during application startup or tests.

**Core Pattern:**
Capture audio into a bounded, normalized local artifact; persist the job as `recorded`; dispatch to a provider worker; validate the structured result; persist `transcribed`; then release or retain audio according to policy. The core never imports a concrete model library.

**Tool Use:**
Use PipeWire-compatible capture and host device enumeration. Use model libraries only inside provider modules. Use local fixture files for tests. Remote providers must expose endpoint, transport, model, and network policy in configuration and history.

**State Management:**
Persist state transitions before emitting UI completion events. A job has an immutable input identity, provider snapshot, cancellation state, error code, and retry count. No provider may mutate the original audio or raw transcript.

**Context Window Strategy:**
ASR receives only the current bounded audio segment plus explicit language/model settings. No screen, clipboard, history, or unrelated application context is sent to the provider in Phase 2.

---

## 4b. AI Systems Best Practices

### Structured Outputs with Pydantic

```python
from pydantic import BaseModel, Field

class Segment(BaseModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str

class TranscriptResult(BaseModel):
    text: str
    language: str | None = None
    language_probability: float | None = Field(default=None, ge=0, le=1)
    segments: list[Segment] = []
    provider_id: str
    model_id: str
    audio_sha256: str
```

Validate provider output once at the boundary. On validation failure, persist a typed provider error and retain audio according to policy; do not retry indefinitely or coerce malformed fields silently.

### Async-First Design

Capture callbacks must hand off small immutable audio chunks to an async worker; they must not perform model inference. Inference runs off the GTK main loop and reports progress through typed events. Cancellation is cooperative and bounded by a documented maximum wait; the common mistake is to cancel the UI task while the native model worker continues consuming resources.

### Prompt Engineering Discipline

Phase 2 has no prompt-based cleanup. If a provider uses a prompt-like initial context, it must be explicit, versioned, limited to user-approved language hints, and excluded from sensitive screen/clipboard context.

### Context Window Management

Use bounded audio windows, VAD, and explicit maximum utterance duration. Split long audio at safe boundaries and preserve segment timestamps so Phase 3 can format without re-running ASR.

### Cost and Latency Budget

Local providers have no per-call monetary cost but have CPU/GPU, RAM, thermal, and battery costs. Record cold-start, warm-start, realtime factor, peak memory, and cancellation latency locally. Remote providers are disabled by default and must show network use; no usage-based budget is assumed for the core product.

---

## 5. Evaluation Strategy

### Dimensions

| Dimension | Rubric (Pass/Fail or 1-5) | Measurement Approach | Priority |
|-----------|--------------------------|---------------------|----------|
| Transcript fidelity | Pass if required words, negations, numbers, and names are present; score 1-5 for word error against labeled reference | Code-based WER/CER plus human review of edge cases | Critical |
| Endpoint integrity | Pass if no audio after stop and no clipped boundary makes the fixture unusable | Capture timestamps, state-machine tests, host smoke test | Critical |
| Offline guarantee | Pass if network-disabled fixture run completes without download or socket use | Code-based network-deny test and filesystem/model-cache inspection | Critical |
| Latency | Pass if configured target profile meets the recorded warm-start budget; report cold start separately | Local benchmark with p50/p95 timing | High |
| Cancellation | Pass if cancellation reaches a terminal state and worker resources are released within the documented bound | Integration test with cooperative fake provider and one live host check | High |
| Resource use | Pass if peak memory and CPU are within the selected model profile's declared limits | Benchmark metrics captured locally | High |
| Metadata validity | Pass if every result validates and carries provider/model/audio identity | Pydantic validation and schema tests | High |

### Eval Tooling

**Primary Tool:** Pytest + a small local benchmark/evaluation runner; no hosted tracing service in v1.

**Setup:**

```bash
make test
python -m pytest tests/evals -m offline
```

**CI/CD Integration:**

```bash
# Must not download models or use network.
NETWORK_DISABLED=1 make test
```

### Reference Dataset

**Size:** 20 examples to start.

**Composition:**
- 6 clean short utterances with punctuation and paragraphs.
- 4 self-corrections and restarts.
- 3 names/technical terms and numbers.
- 3 noisy/silent/short-boundary fixtures.
- 2 language-selection fixtures.
- 2 cancellation and provider-failure fixtures.

**Labeling:**
The target user labels transcript usability and endpoint correctness. A second review is required for names, numbers, privacy, and failure cases. Exact reference text and audio checksums are stored in test fixtures; no personal recordings are committed.

---

## 6. Guardrails

### Online (Real-Time)

| Guardrail | Trigger | Intervention |
|-----------|---------|--------------|
| Recording state | Start/stop/cancel event or maximum duration reached | Stop capture, show status, and persist state |
| Network policy | Remote provider selected while network policy is local-only | Block dispatch and explain the setting |
| Provider output schema | Result fails validation or audio identity mismatches | Reject result, retain recoverable job, show retry/save |
| Resource ceiling | Model worker exceeds configured memory/time budget | Cancel or stop the job, preserve audio, show smaller-model guidance |

### Offline (Flywheel)

| Metric | Sampling Strategy | Action on Degradation |
|--------|-------------------|----------------------|
| WER and usability | Run the 20-fixture set on every provider/model change | Block default-model promotion until reviewed |
| Warm latency | Benchmark representative utterances on target hardware | Adjust model profile, VAD, or thread defaults |
| Cancellation latency | Run cancellation fixtures and inspect worker shutdown | Fix provider adapter before release |
| Unexpected network/filesystem access | Run network-denied tests and inspect model cache changes | Treat as a release blocker |

---

## 7. Production Monitoring

**Tracing Tool:** Local structured job events in SQLite/log files; Arize Phoenix and hosted telemetry are intentionally not enabled in the privacy-first v1 baseline.

**Key Metrics to Track:**
- transcription success/failure counts by provider profile, without transcript content;
- cold and warm latency distributions;
- cancellation and retry counts;
- model load failures and peak memory samples;
- local versus remote provider usage, as a local aggregate only.

**Alert Thresholds:**
No remote alerting in v1. Surface a local warning when the selected model repeatedly exceeds its declared latency/memory budget or when a provider fails three consecutive jobs.

**Smart Sampling Strategy:**
Offer an explicit “export redacted diagnostics” action. Include only job IDs, stage/status, timings, provider/model IDs, error codes, and capability state. Never include audio, transcript, clipboard, raw prompts, tokens, or endpoint credentials.

---

## Checklist

- [x] System type classified
- [x] Critical failure modes identified (≥ 3)
- [x] Domain context researched (Section 1b: vertical, stakes, expert criteria, failure modes)
- [x] Regulatory/compliance context identified or explicitly noted as none
- [x] Domain expert roles defined for evaluation involvement
- [x] Framework selected with rationale documented
- [x] Alternatives considered and ruled out
- [x] Framework quick reference written (install, imports, pattern, pitfalls)
- [x] AI systems best practices written (Section 4b: Pydantic, async, prompt discipline, context)
- [x] Evaluation dimensions grounded in domain rubric ingredients
- [x] Each eval dimension has a concrete rubric (Good/Bad in domain language)
- [x] Eval tooling selected — local-only override documented instead of Arize Phoenix
- [x] Reference dataset spec written (size ≥ 10, composition + labeling defined)
- [x] CI/CD eval integration specified
- [x] Online guardrails defined
- [x] Production monitoring configured (local tracing + redacted sampling strategy)
