---
phase: 03-writing-pipeline
status: ready-for-planning
source: phase discussion and codebase reconnaissance
---

# Phase 3 Context: Writing Pipeline

## User outcome

As a VoxFlow user, I want the raw words recognised by the local ASR provider
to become readable text without losing the exact transcript, so that the text
inserted into my focused application needs less manual cleanup and remains
recoverable when a transformation provider fails.

## Scope

This phase delivers TEXT-01 through TEXT-06:

- deterministic punctuation, paragraph/list structure, filler cleanup, and
  conservative spoken self-correction handling;
- one language preference and the Personal, Work, Email, and Other writing
  styles;
- dictionary terms, whole-word corrections, and spoken snippets with explicit
  deterministic precedence;
- a per-job cleanup policy that can be deterministic or explicitly provider
  backed;
- raw fallback when an optional cleanup provider fails, times out, is
  cancelled, or returns blank output.

The GTK settings surface, durable history, clipboard restoration, and audio
retention UI remain in later phases. Phase 3 must expose typed seams that
those phases can consume without changing the raw/final contract.

## Locked implementation decisions

### Raw and final text are different values

`TranscriptResult` remains the immutable ASR result and is never rewritten.
Phase 3 adds a separate immutable writing contract containing:

- the raw transcript text and provider metadata;
- the final text selected for insertion;
- the language and style snapshot used for the job;
- the cleanup policy/provider identity;
- an ordered transformation trace with stage names, changed flags, and
  content hashes only;
- fallback status and a stable fallback code when applicable.

Diagnostics must not include raw text, final text, snippets, dictionary values,
or local paths. Text may be held in the in-memory result and passed to the
inserter, but safe serialization is metadata-only.

### Deterministic cleanup is the first path

The first tracer slice is dependency-free and synchronous. It operates on
plain text and a frozen settings snapshot; it does not call a model or the
network. Its order is fixed and tested:

1. protect URLs, email addresses, code-like spans, and quoted literals;
2. normalize whitespace without flattening explicit line boundaries;
3. remove a small, documented set of low-risk filler phrases;
4. apply conservative spoken self-correction patterns such as
   `X, no, Y` and `X, I mean Y` only when the replacement is unambiguous;
5. expand the longest matching spoken snippet;
6. apply the longest enabled whole-word correction, with stable ID order as
   the tie-breaker;
7. apply style-aware punctuation and paragraph/list formatting while leaving
   protected spans untouched.

The implementation must prefer leaving uncertain text unchanged over silently
changing a name, URL, code fragment, quoted text, or intentional repetition.

### Personalization precedence

Rules are applied from a frozen per-job snapshot, not from mutable global
state. Snippets win over corrections because they are explicit multi-word
commands; within each rule kind, the longest normalized trigger wins, then the
lowest stable rule ID. Dictionary entries protect vocabulary from accidental
normalization but are not replacement rules. Disabled rules are ignored.

### Language and styles

The MVP stores one writing-language preference as `auto` or a validated BCP-47
like tag. The four built-in styles are immutable named profiles:
`personal`, `work`, `email`, and `other`. A style controls formatting policy,
not provider selection. Custom style editing is deferred until the settings
surface exists.

### Optional cleanup provider boundary

Provider-backed cleanup is added only after the deterministic contract is
stable. It receives the raw text plus the frozen writing settings through an
injectable async protocol. Local/LAN/cloud implementations must declare their
network policy and use the existing explicit remote-provider patterns. Any
provider error, timeout, cancellation, or blank result returns a recoverable
writing result whose inserted text is the raw transcript and whose fallback
code explains the reason.

## Integration boundary

The daemon currently runs `DictationJobRunner`, reads
`snapshot.result.text`, and passes it to `Inserter.insert()`. Phase 3 changes
only the seam after successful ASR:

1. create a frozen writing settings snapshot;
2. run the writing pipeline against the validated `TranscriptResult`;
3. retain the `WritingResult` for recovery/history callers;
4. pass `WritingResult.final_text` to the existing inserter.

The daemon must continue to insert only after capture closes and must not print
transcript content in lifecycle logs.

## Verification contract

- Golden JSON fixtures cover punctuation, paragraphs, lists, fillers,
  self-correction, protected spans, snippets, corrections, and unchanged
  text.
- Unit tests prove frozen contracts, safe serialization, rule precedence, and
  deterministic repeatability.
- Integration tests prove raw text remains unchanged while final text reaches
  the inserter, and that provider failure falls back without losing the raw
  transcript.
- All checks run offline with temporary SQLite databases and fake providers.

## Explicit non-goals

- no LLM prompt or hosted account requirement;
- no automatic app/window inspection;
- no mutation of `TranscriptResult`;
- no UI work in this phase;
- no durable job history or clipboard restoration in this phase.
